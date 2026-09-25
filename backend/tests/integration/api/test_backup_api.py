"""/api/v2/backup: capability + all-hosts gate, CSRF origin check, lock, error mapping,
download/upload/restore round trip, and the post-restore audit hook."""

import asyncio
import hashlib
import io
import os
import secrets
import time
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from auth.api_key_auth import get_current_user_or_api_key
from auth.capabilities import ALL_CAPABILITIES, OPERATOR_CAPABILITIES, READONLY_CAPABILITIES
from backup import routes as backup_routes
from backup.completion import announce_completed_restore
from backup.crypto import decrypt_stream
from backup.oplock import operation_lock
from backup.restore import ApplyOutcome, apply_staged, pending_manifest, read_completed_marker
from database import ApiKey, AuditLog, CustomGroup, GroupPermission, GroupTagScope, Tag, User, UserGroupMembership
from main import app, monitor
from manage_backup import migrate_candidate
from security.rate_limiting import rate_limiter
from tests.unit.backup.conftest import FAST_KDF, build_install, host_names

PASSPHRASE = "correct horse battery staple"


def _group(session, name, caps):
    group = CustomGroup(name=name, description="t")
    session.add(group)
    session.flush()
    for cap in caps:
        session.add(GroupPermission(group_id=group.id, capability=cap, allowed=True))
    session.flush()
    return group


def _api_key(session, username, group):
    user = User(username=username, password_hash="$2b$12$test_hash_not_real", created_at=datetime.now(timezone.utc))
    session.add(user)
    session.flush()
    raw = f"dockmon_{secrets.token_hex(16)}"
    session.add(ApiKey(created_by_user_id=user.id, group_id=group.id, name=f"{username}-key",
                       key_hash=hashlib.sha256(raw.encode()).hexdigest(), key_prefix=raw[:12],
                       created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    session.add(UserGroupMembership(user_id=user.id, group_id=group.id))
    session.commit()
    return {"Authorization": f"Bearer {raw}"}, user


@pytest.fixture(scope="module")
def head_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("backup-api") / "head.db"
    assert migrate_candidate(path)
    return path


@pytest.fixture
def paths(tmp_path, head_db):
    return build_install(tmp_path / "live", head_db, "live-host", "old")


@pytest.fixture
def client(paths, monkeypatch):
    app.dependency_overrides[backup_routes.get_backup_paths] = lambda: paths
    monkeypatch.setattr(backup_routes, "BACKUP_KDF", FAST_KDF)
    monkeypatch.setitem(rate_limiter.limits, "backup", (1000, 1000, 1000))
    yield TestClient(app)
    app.dependency_overrides.pop(backup_routes.get_backup_paths, None)


@pytest.fixture
def keys(db_session):
    admins = _group(db_session, "Administrators", ALL_CAPABILITIES)
    operators = _group(db_session, "Operators", OPERATOR_CAPABILITIES)
    scoped = _group(db_session, "Scoped Admins", ALL_CAPABILITIES)
    tag = Tag(id=str(uuid.uuid4()), name="dev")
    db_session.add(tag)
    db_session.flush()
    db_session.add(GroupTagScope(group_id=scoped.id, tag_id=tag.id))
    db_session.commit()
    admin, admin_user = _api_key(db_session, "admin", admins)
    operator, _ = _api_key(db_session, "operator", operators)
    scoped_admin, _ = _api_key(db_session, "scoped", scoped)
    return type("Keys", (), {"admin": admin, "operator": operator, "scoped": scoped_admin, "admin_user": admin_user})


def _create_download(client, keys, **body):
    response = client.post("/api/v2/backup", json={"passphrase": PASSPHRASE, **body}, headers=keys.admin)
    assert response.status_code == 200, response.text
    return response.json()


def _download(client, keys, download_id) -> bytes:
    response = client.get(f"/api/v2/backup/downloads/{download_id}", headers=keys.admin)
    assert response.status_code == 200, response.text
    return response.content


def _upload(client, keys, blob: bytes):
    return client.post(
        "/api/v2/backup/uploads",
        content=blob,
        headers={**keys.admin, "Content-Type": "application/octet-stream"},
    )


@pytest.mark.integration
class TestAccess:
    def test_capability_is_admin_only(self):
        assert "backup.manage" in ALL_CAPABILITIES
        assert "backup.manage" not in OPERATOR_CAPABILITIES
        assert "backup.manage" not in READONLY_CAPABILITIES

    def test_unauthenticated_is_rejected(self, client):
        assert client.get("/api/v2/backup/status").status_code == 401

    def test_missing_capability_is_forbidden(self, client, keys):
        assert client.get("/api/v2/backup/status", headers=keys.operator).status_code == 403
        response = client.post("/api/v2/backup", json={"passphrase": PASSPHRASE}, headers=keys.operator)
        assert response.status_code == 403

    def test_tag_scoped_admin_is_forbidden_before_body_validation(self, client, keys):
        assert client.get("/api/v2/backup/status", headers=keys.scoped).status_code == 403
        response = client.post("/api/v2/backup", json={}, headers=keys.scoped)
        assert response.status_code == 403
        assert "all hosts" in response.json()["detail"]

    def test_cookie_session_needs_a_same_origin_header(self, client, keys):
        admin_user = keys.admin_user
        app.dependency_overrides[get_current_user_or_api_key] = lambda: {
            "auth_type": "session", "user_id": admin_user.id, "username": admin_user.username,
            "display_name": admin_user.username,
        }
        try:
            body = {"passphrase": PASSPHRASE}
            assert client.post("/api/v2/backup", json=body).status_code == 403
            cross = client.post("/api/v2/backup", json=body, headers={"Origin": "https://evil.example"})
            assert cross.status_code == 403
            same = client.post("/api/v2/backup", json=body, headers={"Origin": "http://testserver"})
            assert same.status_code == 200, same.text
            assert client.get("/api/v2/backup/status").status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_user_or_api_key, None)


@pytest.mark.integration
class TestDownload:
    def test_download_decrypts_and_never_records_the_passphrase(self, client, keys, db_session, tmp_path):
        meta = _create_download(client, keys, include_stats=False)
        assert meta["filename"].endswith(".dmbak")
        assert meta["expires_at"].endswith("Z")

        blob = _download(client, keys, meta["download_id"])
        assert len(blob) == meta["size"]
        out = io.BytesIO()
        decrypt_stream(io.BytesIO(blob), out, PASSPHRASE)

        rows = db_session.query(AuditLog).filter(AuditLog.entity_type == "backup").all()
        assert rows and all(PASSPHRASE not in (str(r.details) or "") for r in rows)

    def test_download_headers_prevent_caching(self, client, keys):
        meta = _create_download(client, keys)
        response = client.get(f"/api/v2/backup/downloads/{meta['download_id']}", headers=keys.admin)
        assert response.headers["cache-control"] == "no-store"
        assert "attachment" in response.headers["content-disposition"]

    def test_a_new_backup_replaces_the_previous_download(self, client, keys):
        first = _create_download(client, keys)
        second = _create_download(client, keys)
        missing = client.get(f"/api/v2/backup/downloads/{first['download_id']}", headers=keys.admin)
        assert missing.status_code == 404
        assert _download(client, keys, second["download_id"])

    @pytest.mark.parametrize("bad_id", ["../../etc/passwd", "nothex", "0" * 31])
    def test_bad_download_ids_are_not_found(self, client, keys, bad_id):
        response = client.get(f"/api/v2/backup/downloads/{bad_id}", headers=keys.admin)
        assert response.status_code in (404, 422)

    def test_short_passphrase_is_rejected(self, client, keys):
        response = client.post("/api/v2/backup", json={"passphrase": "short"}, headers=keys.admin)
        assert response.status_code == 422

    def test_busy_lock_returns_409_and_is_released_after_errors(self, client, keys, paths):
        with operation_lock(paths):
            response = client.post("/api/v2/backup", json={"passphrase": PASSPHRASE}, headers=keys.admin)
            assert response.status_code == 409
            assert client.get("/api/v2/backup/status", headers=keys.admin).json()["busy"] is True
        paths.key_path.unlink()
        assert client.post("/api/v2/backup", json={"passphrase": PASSPHRASE}, headers=keys.admin).status_code >= 400
        assert client.get("/api/v2/backup/status", headers=keys.admin).json()["busy"] is False

    def test_disconnect_mid_download_leaves_the_download_intact(self, client, keys):
        meta = _create_download(client, keys)
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": f"/api/v2/backup/downloads/{meta['download_id']}",
            "raw_path": b"", "query_string": b"", "root_path": "", "server": ("testserver", 80),
            "client": ("testclient", 5000),
            "headers": [(b"host", b"testserver"), (b"authorization", keys.admin["Authorization"].encode())],
        }
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message["type"])
            if message["type"] == "http.response.body":
                raise OSError("client went away")

        async def run():
            try:
                await app(scope, receive, send)
            except Exception:
                pass

        asyncio.run(run())
        assert sent[0] == "http.response.start"
        assert len(_download(client, keys, meta["download_id"])) == meta["size"]


@pytest.mark.integration
class TestRestore:
    def _backup_blob(self, client, keys) -> bytes:
        return _download(client, keys, _create_download(client, keys)["download_id"])

    def test_upload_and_stage_then_apply(self, client, keys, paths):
        blob = self._backup_blob(client, keys)
        upload = _upload(client, keys, blob)
        assert upload.status_code == 200, upload.text
        assert upload.json()["size"] == len(blob)

        response = client.post(
            "/api/v2/backup/restore",
            json={"upload_id": upload.json()["upload_id"], "passphrase": PASSPHRASE},
            headers=keys.admin,
        )
        assert response.status_code == 200, response.text
        assert response.json()["summary"]["hosts"] == 1

        status = client.get("/api/v2/backup/status", headers=keys.admin).json()
        assert status["pending"]["created_at"].endswith("Z")
        assert str(paths.data_dir) not in str(status)
        assert pending_manifest(paths) is not None
        assert apply_staged(paths, lambda _p: True) is ApplyOutcome.APPLIED
        assert host_names(paths.db_path) == ["live-host"]

    def test_wrong_passphrase_is_400_and_the_upload_is_consumed(self, client, keys, paths):
        upload = _upload(client, keys, self._backup_blob(client, keys)).json()
        response = client.post(
            "/api/v2/backup/restore",
            json={"upload_id": upload["upload_id"], "passphrase": "wrong passphrase!!"},
            headers=keys.admin,
        )
        assert response.status_code == 400
        assert "passphrase" in response.json()["detail"].lower()
        again = client.post(
            "/api/v2/backup/restore",
            json={"upload_id": upload["upload_id"], "passphrase": PASSPHRASE},
            headers=keys.admin,
        )
        assert again.status_code == 404

    def test_upload_requires_octet_stream(self, client, keys):
        response = client.post("/api/v2/backup/uploads", content=b"x", headers={**keys.admin, "Content-Type": "text/plain"})
        assert response.status_code == 415

    def test_upload_over_the_cap_is_413_and_leaves_nothing(self, client, keys, paths, monkeypatch):
        monkeypatch.setattr(backup_routes, "MAX_ARCHIVE_BYTES", 10)
        response = _upload(client, keys, b"x" * 100)
        assert response.status_code == 413
        incoming = paths.data_dir / ".dockmon-restore" / "incoming"
        assert not incoming.exists() or not any(incoming.iterdir())

    def test_declared_length_over_the_cap_is_rejected_up_front(self, client, keys, monkeypatch):
        monkeypatch.setattr(backup_routes, "MAX_ARCHIVE_BYTES", 10)
        response = client.post(
            "/api/v2/backup/uploads", content=b"x" * 5,
            headers={**keys.admin, "Content-Type": "application/octet-stream", "Content-Length": "99999"},
        )
        assert response.status_code in (400, 413)

    @pytest.mark.parametrize("upload_id", ["../../etc/passwd", "not-a-uuid", ""])
    def test_bad_upload_ids(self, client, keys, upload_id):
        response = client.post(
            "/api/v2/backup/restore", json={"upload_id": upload_id, "passphrase": PASSPHRASE}, headers=keys.admin,
        )
        assert response.status_code in (404, 422)

    def test_second_stage_conflicts_unless_replace(self, client, keys):
        blob = self._backup_blob(client, keys)
        for replace, expected in ((False, 200), (False, 409), (True, 200)):
            upload = _upload(client, keys, blob).json()
            response = client.post(
                "/api/v2/backup/restore",
                json={"upload_id": upload["upload_id"], "passphrase": PASSPHRASE, "replace": replace},
                headers=keys.admin,
            )
            assert response.status_code == expected, response.text

    def test_an_unstaged_upload_survives_another_upload(self, client, keys):
        blob = self._backup_blob(client, keys)
        first = _upload(client, keys, blob).json()
        _upload(client, keys, blob)
        response = client.post(
            "/api/v2/backup/restore",
            json={"upload_id": first["upload_id"], "passphrase": PASSPHRASE},
            headers=keys.admin,
        )
        assert response.status_code == 200, response.text

    def test_an_expired_upload_cannot_be_staged(self, client, keys, paths):
        upload = _upload(client, keys, self._backup_blob(client, keys)).json()
        stale = paths.incoming_dir / f"{upload['upload_id']}.dmbak"
        old = time.time() - backup_routes.UPLOAD_TTL_SECONDS - 60
        os.utime(stale, (old, old))
        response = client.post(
            "/api/v2/backup/restore",
            json={"upload_id": upload["upload_id"], "passphrase": PASSPHRASE},
            headers=keys.admin,
        )
        assert response.status_code == 404
        assert not stale.exists()

    def test_cancel_pending(self, client, keys, paths):
        upload = _upload(client, keys, self._backup_blob(client, keys)).json()
        client.post("/api/v2/backup/restore", json={"upload_id": upload["upload_id"], "passphrase": PASSPHRASE},
                    headers=keys.admin)
        response = client.delete("/api/v2/backup/restore/pending", headers=keys.admin)
        assert response.status_code == 200
        assert response.json() == {"cancelled": True}
        assert pending_manifest(paths) is None

    def test_rollback_routes(self, client, keys, paths):
        upload = _upload(client, keys, self._backup_blob(client, keys)).json()
        client.post("/api/v2/backup/restore", json={"upload_id": upload["upload_id"], "passphrase": PASSPHRASE},
                    headers=keys.admin)
        apply_staged(paths, lambda _p: True)

        rollbacks = client.get("/api/v2/backup/status", headers=keys.admin).json()["rollbacks"]
        assert len(rollbacks) == 1
        rollback_id = rollbacks[0]["id"]
        staged = client.post(f"/api/v2/backup/rollbacks/{rollback_id}/stage", json={}, headers=keys.admin)
        assert staged.status_code == 200, staged.text
        client.delete("/api/v2/backup/restore/pending", headers=keys.admin)

        assert client.delete(f"/api/v2/backup/rollbacks/{rollback_id}", headers=keys.admin).status_code == 204
        assert client.delete(f"/api/v2/backup/rollbacks/{rollback_id}", headers=keys.admin).status_code == 404
        assert client.delete("/api/v2/backup/rollbacks/..%2F..%2Fetc", headers=keys.admin).status_code == 404


@pytest.mark.integration
class TestCompletionHook:
    def _applied(self, client, keys, paths):
        upload = _upload(client, keys, _download(client, keys, _create_download(client, keys)["download_id"])).json()
        client.post("/api/v2/backup/restore", json={"upload_id": upload["upload_id"], "passphrase": PASSPHRASE},
                    headers=keys.admin)
        assert apply_staged(paths, lambda _p: True) is ApplyOutcome.APPLIED

    def test_records_once_attributed_to_the_initiator(self, client, keys, paths, db_session):
        self._applied(client, keys, paths)
        events = FakeEventLogger()
        asyncio.run(announce_completed_restore(paths, monitor.db, events))
        asyncio.run(announce_completed_restore(paths, monitor.db, events))

        restore_id = read_completed_marker(paths)["restore_id"]
        rows = db_session.query(AuditLog).filter(AuditLog.entity_id == restore_id).all()
        assert len(rows) == 1
        assert rows[0].action == "restore"
        assert rows[0].username == "API Key: admin-key"
        assert rows[0].user_id is None
        assert len(events.titles) == 1

    def test_event_failure_is_retried_without_a_second_audit_row(self, client, keys, paths, db_session):
        self._applied(client, keys, paths)
        failing = FakeEventLogger(fail=True)
        asyncio.run(announce_completed_restore(paths, monitor.db, failing))
        assert read_completed_marker(paths)["logged"] is False

        events = FakeEventLogger()
        asyncio.run(announce_completed_restore(paths, monitor.db, events))

        restore_id = read_completed_marker(paths)["restore_id"]
        assert db_session.query(AuditLog).filter(AuditLog.entity_id == restore_id).count() == 1
        assert events.titles == ["DockMon was restored from a backup"]
        assert read_completed_marker(paths)["logged"] is True


class FakeEventLogger:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.titles = []

    def log_system_event(self, title, message, severity, event_type):
        if self.fail:
            raise RuntimeError("event queue closed")
        self.titles.append(title)
