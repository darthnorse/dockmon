"""Tag-based host visibility on the primary read surfaces.

Three hosts: h1 carries tag `dev`, h2 carries tag `test`, h3 is untagged.
Principals: unrestricted (group without scope rows), dev-scoped (group scoped to
`dev`), orphan (group scoped to a tag no host carries -> sees nothing).
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main as main_module
from auth.api_key_auth import (
    invalidate_group_permissions_cache,
    invalidate_group_tag_scopes_cache,
    invalidate_user_groups_cache,
)
from auth.capabilities import ALL_CAPABILITIES
from database import Agent, ApiKey, CustomGroup, DockerHostDB, GroupPermission, GroupTagScope, Tag, TagAssignment, User, UserGroupMembership
from main import app
from models.docker_models import Container, DockerHost

HOSTS = {
    "h1": DockerHost(id="h1", name="Dev Host", url="tcp://h1:2376", status="online"),
    "h2": DockerHost(id="h2", name="Test Host", url="tcp://h2:2376", status="online"),
    "h3": DockerHost(id="h3", name="Untagged Host", url="tcp://h3:2376", status="offline"),
}


def _container(cid: str, host_id: str, state: str = "running") -> Container:
    return Container(
        id=cid, short_id=cid, name=f"c-{cid}", image="nginx:latest", state=state,
        status="Up", host_id=host_id, host_name=HOSTS[host_id].name, created="2026-09-16T00:00:00Z",
    )


CONTAINERS = [
    _container("aaa111111111", "h1"),
    _container("bbb222222222", "h1", state="exited"),
    _container("ccc333333333", "h2"),
    _container("ddd444444444", "h3"),
]


def _tag(session, name: str) -> Tag:
    tag = Tag(id=str(uuid.uuid4()), name=name)
    session.add(tag)
    session.flush()
    return tag


def _group_with_all_caps(session, name: str, *scope_tags: Tag) -> CustomGroup:
    group = CustomGroup(name=name, description="scope test")
    session.add(group)
    session.flush()
    for cap in ALL_CAPABILITIES:
        session.add(GroupPermission(group_id=group.id, capability=cap, allowed=True))
    for tag in scope_tags:
        session.add(GroupTagScope(group_id=group.id, tag_id=tag.id))
    session.flush()
    return group


def _api_key_for(session, username: str, group: CustomGroup) -> str:
    user = User(username=username, password_hash="$2b$12$test_hash_not_real", created_at=datetime.now(timezone.utc))
    session.add(user)
    session.flush()
    raw_key = f"dockmon_{secrets.token_hex(16)}"
    session.add(ApiKey(
        created_by_user_id=user.id, group_id=group.id, name=f"{username}-key",
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(), key_prefix=raw_key[:12],
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return raw_key


class ScopedClient:
    def __init__(self, client: TestClient, api_key: str):
        self._client = client
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def get(self, url: str, **kwargs):
        return self._client.get(url, headers=self._headers, **kwargs)

    def post(self, url: str, **kwargs):
        return self._client.post(url, headers=self._headers, **kwargs)


@pytest.fixture(autouse=True)
def reset_auth_caches():
    invalidate_group_permissions_cache()
    invalidate_user_groups_cache()
    invalidate_group_tag_scopes_cache()
    yield
    invalidate_group_permissions_cache()
    invalidate_user_groups_cache()
    invalidate_group_tag_scopes_cache()


@pytest.fixture
def seeded_hosts(db_session, monkeypatch):
    dev, test, unused = _tag(db_session, "dev"), _tag(db_session, "test"), _tag(db_session, "unused")
    db_session.add(TagAssignment(tag_id=dev.id, subject_type="host", subject_id="h1"))
    db_session.add(TagAssignment(tag_id=test.id, subject_type="host", subject_id="h2"))
    db_session.commit()

    monkeypatch.setattr(main_module.monitor, "hosts", dict(HOSTS))

    async def get_containers(host_id=None):
        return [c for c in CONTAINERS if host_id is None or c.host_id == host_id]

    monkeypatch.setattr(main_module.monitor, "get_containers", get_containers)
    monkeypatch.setattr(main_module.monitor, "get_last_containers", lambda: list(CONTAINERS))
    return {"dev": dev, "test": test, "unused": unused}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def unrestricted_client(client, db_session, seeded_hosts):
    group = _group_with_all_caps(db_session, "Unrestricted")
    return ScopedClient(client, _api_key_for(db_session, "admin", group))


@pytest.fixture
def dev_scoped_client(client, db_session, seeded_hosts):
    group = _group_with_all_caps(db_session, "Dev", seeded_hosts["dev"])
    return ScopedClient(client, _api_key_for(db_session, "dev_user", group))


@pytest.fixture
def orphan_client(client, db_session, seeded_hosts):
    group = _group_with_all_caps(db_session, "Orphan", seeded_hosts["unused"])
    return ScopedClient(client, _api_key_for(db_session, "orphan_user", group))


@pytest.mark.integration
class TestHostsEndpoint:
    def test_unrestricted_sees_all_hosts(self, unrestricted_client):
        response = unrestricted_client.get("/api/hosts")
        assert response.status_code == 200
        assert {h["id"] for h in response.json()} == {"h1", "h2", "h3"}

    def test_dev_scoped_sees_only_dev_host(self, dev_scoped_client):
        response = dev_scoped_client.get("/api/hosts")
        assert response.status_code == 200
        assert {h["id"] for h in response.json()} == {"h1"}

    def test_orphan_sees_no_hosts(self, orphan_client):
        response = orphan_client.get("/api/hosts")
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.integration
class TestContainersEndpoint:
    def test_unrestricted_sees_all_containers(self, unrestricted_client):
        response = unrestricted_client.get("/api/containers")
        assert response.status_code == 200
        assert {c["host_id"] for c in response.json()} == {"h1", "h2", "h3"}

    def test_dev_scoped_sees_only_dev_containers(self, dev_scoped_client):
        response = dev_scoped_client.get("/api/containers")
        assert response.status_code == 200
        assert {c["host_id"] for c in response.json()} == {"h1"}
        assert len(response.json()) == 2

    def test_dev_scoped_query_for_hidden_host_is_empty(self, dev_scoped_client):
        response = dev_scoped_client.get("/api/containers?host_id=h2")
        assert response.status_code == 200
        assert response.json() == []

    def test_orphan_sees_no_containers(self, orphan_client):
        response = orphan_client.get("/api/containers")
        assert response.status_code == 200
        assert response.json() == []


@pytest.fixture
def seeded_agents(db_session, seeded_hosts):
    for host_id, host in HOSTS.items():
        db_session.add(DockerHostDB(id=host_id, name=host.name, url=host.url, connection_type="agent"))
    db_session.flush()
    for host_id in ("h1", "h2"):
        db_session.add(Agent(
            id=f"agent-{host_id}", host_id=host_id, engine_id=f"engine-{host_id}", version="1.0.0",
            proto_version="1", capabilities={}, status="online",
        ))
    db_session.commit()


@pytest.mark.integration
class TestDashboardHostsEndpoint:
    def test_unrestricted_sees_all_hosts(self, unrestricted_client):
        response = unrestricted_client.get("/api/dashboard/hosts")
        assert response.status_code == 200
        data = response.json()
        assert {h["id"] for h in data["groups"]["All Hosts"]} == {"h1", "h2", "h3"}
        assert data["total_hosts"] == 3

    def test_dev_scoped_sees_only_dev_host(self, dev_scoped_client):
        response = dev_scoped_client.get("/api/dashboard/hosts")
        assert response.status_code == 200
        data = response.json()
        assert {h["id"] for h in data["groups"]["All Hosts"]} == {"h1"}
        assert data["total_hosts"] == 1

    def test_orphan_sees_no_hosts(self, orphan_client):
        response = orphan_client.get("/api/dashboard/hosts")
        assert response.status_code == 200
        assert response.json()["groups"]["All Hosts"] == []
        assert response.json()["total_hosts"] == 0


@pytest.mark.integration
class TestAgentListEndpoint:
    def test_unrestricted_sees_all_agents(self, unrestricted_client, seeded_agents):
        response = unrestricted_client.get("/api/agent/list")
        assert response.status_code == 200
        assert {a["host_id"] for a in response.json()["agents"]} == {"h1", "h2"}
        assert response.json()["total"] == 2

    def test_dev_scoped_sees_only_dev_agent(self, dev_scoped_client, seeded_agents):
        response = dev_scoped_client.get("/api/agent/list")
        assert response.status_code == 200
        assert [a["host_id"] for a in response.json()["agents"]] == ["h1"]
        assert response.json()["total"] == 1

    def test_orphan_sees_no_agents(self, orphan_client, seeded_agents):
        response = orphan_client.get("/api/agent/list")
        assert response.status_code == 200
        assert response.json()["agents"] == []
        assert response.json()["total"] == 0
        assert response.json()["connected_count"] == 0


# ---------------------------------------------------------------------------
# WebSocket /ws: session-cookie auth, per-connection visible set
# ---------------------------------------------------------------------------

def _session_user(session, username: str, group: CustomGroup) -> User:
    user = User(username=username, password_hash="$2b$12$test_hash_not_real", created_at=datetime.now(timezone.utc))
    session.add(user)
    session.flush()
    session.add(UserGroupMembership(user_id=user.id, group_id=group.id))
    session.commit()
    return user


@pytest.fixture
def ws_sessions(db_session, seeded_hosts, monkeypatch):
    """Map cookie value -> session dict for the users below; monkeypatches session validation."""
    admin = _session_user(db_session, "ws_admin", _group_with_all_caps(db_session, "WS Unrestricted"))
    dev = _session_user(db_session, "ws_dev", _group_with_all_caps(db_session, "WS Dev", seeded_hosts["dev"]))
    sessions = {
        "admin-cookie": {"user_id": admin.id, "username": admin.username},
        "dev-cookie": {"user_id": dev.id, "username": dev.username},
    }
    monkeypatch.setattr(
        "auth.cookie_sessions.cookie_session_manager.validate_session",
        lambda session_id, client_ip: sessions.get(session_id),
    )
    monkeypatch.setattr(main_module.monitor, "get_last_containers", lambda: [])
    return {"admin": admin, "dev": dev}


def _connect(client: TestClient, cookie: str):
    return client.websocket_connect("/ws", cookies={"session_id": cookie})


def _drain_until(ws, msg_type: str, limit: int = 5):
    for _ in range(limit):
        message = ws.receive_json()
        if message["type"] == msg_type:
            return message
    raise AssertionError(f"no {msg_type} message received")


@pytest.mark.integration
class TestWebSocketVisibility:
    def test_initial_state_and_immediate_update_are_scoped(self, client, ws_sessions):
        with _connect(client, "dev-cookie") as ws:
            initial = _drain_until(ws, "initial_state")
            assert [h["id"] for h in initial["data"]["hosts"]] == ["h1"]
            assert {c["host_id"] for c in initial["data"]["containers"]} == {"h1"}
            update = _drain_until(ws, "containers_update")
            assert {c["host_id"] for c in update["data"]["containers"]} == {"h1"}
            assert all(k.startswith("h1:") for k in update["data"]["container_sparklines"])

    def test_unrestricted_initial_state_has_everything(self, client, ws_sessions):
        with _connect(client, "admin-cookie") as ws:
            initial = _drain_until(ws, "initial_state")
            assert {h["id"] for h in initial["data"]["hosts"]} == {"h1", "h2", "h3"}
            assert {c["host_id"] for c in initial["data"]["containers"]} == {"h1", "h2", "h3"}

    def test_broadcasts_for_hidden_hosts_are_not_delivered(self, client, ws_sessions):
        manager = main_module.monitor.manager
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.portal.call(manager.broadcast, {"type": "host_status_changed", "data": {"host_id": "h2", "status": "offline"}})
            ws.portal.call(manager.broadcast, {"type": "new_event", "event": {"category": "container", "host_id": "h2", "container_id": "x"}})
            ws.portal.call(manager.broadcast, {"type": "host_status_changed", "data": {"host_id": "h1", "status": "offline"}})
            delivered = ws.receive_json()
            assert delivered == {"type": "host_status_changed", "data": {"host_id": "h1", "status": "offline"}}

    def test_subscribe_stats_for_hidden_container_is_refused(self, client, ws_sessions):
        realtime = main_module.monitor.realtime
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": "ccc333333333"})
            ws.send_json({"type": "subscribe_stats", "container_id": "aaa111111111"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert set(realtime.stats_subscribers) == {"h1:aaa111111111"}

    def test_subscribe_with_explicit_host_must_match_the_pair(self, client, ws_sessions):
        realtime = main_module.monitor.realtime
        with _connect(client, "admin-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": "aaa111111111", "host_id": "h2"})
            ws.send_json({"type": "subscribe_stats", "container_id": "ccc333333333", "host_id": "h2"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert set(realtime.stats_subscribers) == {"h2:ccc333333333"}
            ws.send_json({"type": "unsubscribe_stats", "container_id": "ccc333333333", "host_id": "h1"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert set(realtime.stats_subscribers) == {"h2:ccc333333333"}

    def test_non_string_container_id_does_not_close_the_socket(self, client, ws_sessions):
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": 123})
            ws.send_json({"type": "unsubscribe_stats", "container_id": ["x"]})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_scope_tightened_while_subscribed_revokes_stream(self, client, ws_sessions, db_session):
        realtime = main_module.monitor.realtime
        manager = main_module.monitor.manager
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": "aaa111111111"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert "h1:aaa111111111" in realtime.stats_subscribers

            db_session.query(TagAssignment).filter_by(subject_id="h1").delete()
            db_session.commit()
            ws.portal.call(manager.refresh_visible_hosts_for_user, ws_sessions["dev"].id)

            assert "h1:aaa111111111" not in realtime.stats_subscribers
            ws.send_json({"type": "subscribe_stats", "container_id": "aaa111111111"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert "h1:aaa111111111" not in realtime.stats_subscribers


@pytest.mark.integration
class TestShellWebSocketVisibility:
    def test_hidden_host_closes_with_4404(self, client, ws_sessions):
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/shell/h2/ccc333333333", cookies={"session_id": "dev-cookie"}):
                pass
        assert exc.value.code == 4404
