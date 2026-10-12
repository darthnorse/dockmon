import collections
import hashlib
import io
import json
import shutil
import sqlite3
import stat
import tarfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from backup import validate
from backup.errors import BackupSpaceError, BackupValidationError
from backup.validate import check_database, extract_archive
from tests.unit.backup.conftest import HEAD_REVISION as HEAD
from tests.unit.backup.conftest import OLDER_REVISION, seed_database



def _manifest(files: dict, **overrides) -> dict:
    manifest = {
        "format_version": 1,
        "app_version": "test",
        "alembic_revision": HEAD,
        "created_at": "2026-09-25T00:00:00Z",
        "stats_history_included": True,
        "files": {
            name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        },
        "summary": {"hosts": 0, "users": 0, "alert_rules": 0, "stacks": []},
    }
    manifest.update(overrides)
    return manifest


def _regular(name: str, data: bytes) -> tuple:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    return info, data


def _write_tar(path: Path, members: list, fmt=tarfile.USTAR_FORMAT) -> Path:
    with tarfile.open(path, "w:gz", format=fmt) as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data) if data is not None else None)
    return path


def _valid_members(extra: dict = None, manifest_overrides: dict = None) -> list:
    files = {"dockmon.db": b"db-bytes", "encryption.key": b"key-bytes", "stacks/web/compose.yaml": b"services: {}\n"}
    files.update(extra or {})
    manifest = json.dumps(_manifest(files, **(manifest_overrides or {}))).encode()
    return [_regular("manifest.json", manifest)] + [_regular(n, d) for n, d in files.items()]


def test_valid_archive_extracts_with_strict_modes(tmp_path):
    tar_path = _write_tar(tmp_path / "a.tar.gz", _valid_members())
    dest = tmp_path / "out"

    manifest = extract_archive(tar_path, dest)

    assert manifest["alembic_revision"] == HEAD
    assert (dest / "stacks/web/compose.yaml").read_bytes() == b"services: {}\n"
    assert stat.S_IMODE((dest / "encryption.key").stat().st_mode) == 0o600
    assert stat.S_IMODE((dest / "stacks").stat().st_mode) == 0o700


def _special(name: str, kind: bytes, linkname: str = "") -> tuple:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = linkname
    return info, None


@pytest.mark.parametrize(
    "member",
    [
        _special("stacks/web/.env", tarfile.SYMTYPE, "/etc/shadow"),
        _special("stacks/web/.env", tarfile.LNKTYPE, "encryption.key"),
        _special("stacks/web/.env", tarfile.FIFOTYPE),
        _special("stacks/web/.env", tarfile.CHRTYPE),
        _special("stacks/web", tarfile.DIRTYPE),
    ],
    ids=["symlink", "hardlink", "fifo", "chardev", "directory"],
)
def test_non_regular_members_rejected(tmp_path, member):
    tar_path = _write_tar(tmp_path / "a.tar.gz", _valid_members() + [member])
    with pytest.raises(BackupValidationError):
        extract_archive(tar_path, tmp_path / "out")


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        "../escape",
        "stacks/web/../../escape",
        "stacks/web/data/db.sqlite",
        "stacks/Bad/compose.yaml",
        "stacks/web/..",
        "logs/dockmon.log",
        "stacks/web/café.env",
    ],
)
def test_names_outside_the_allowlist_rejected(tmp_path, name):
    members = _valid_members(extra={name: b"x"})
    tar_path = _write_tar(tmp_path / "a.tar.gz", members, fmt=tarfile.GNU_FORMAT)
    with pytest.raises(BackupValidationError):
        extract_archive(tar_path, tmp_path / "out")
    assert not (tmp_path / "escape").exists()


def test_duplicate_member_rejected(tmp_path):
    members = _valid_members() + [_regular("encryption.key", b"key-bytes")]
    tar_path = _write_tar(tmp_path / "a.tar.gz", members)
    with pytest.raises(BackupValidationError, match="uplicate"):
        extract_archive(tar_path, tmp_path / "out")


def test_pax_headers_rejected(tmp_path):
    members = _valid_members()
    members[1][0].pax_headers = {"comment": "x"}
    tar_path = _write_tar(tmp_path / "a.tar.gz", members, fmt=tarfile.PAX_FORMAT)
    with pytest.raises(BackupValidationError):
        extract_archive(tar_path, tmp_path / "out")


def test_manifest_must_come_first(tmp_path):
    members = _valid_members()
    members = members[1:] + members[:1]
    tar_path = _write_tar(tmp_path / "a.tar.gz", members)
    with pytest.raises(BackupValidationError, match="manifest"):
        extract_archive(tar_path, tmp_path / "out")


def test_file_not_in_manifest_rejected(tmp_path):
    members = _valid_members()
    members.append(_regular("stacks/web/.env", b"A=1\n"))
    tar_path = _write_tar(tmp_path / "a.tar.gz", members)
    with pytest.raises(BackupValidationError):
        extract_archive(tar_path, tmp_path / "out")


def test_manifest_file_missing_from_archive_rejected(tmp_path):
    members = _valid_members()[:-1]
    tar_path = _write_tar(tmp_path / "a.tar.gz", members)
    with pytest.raises(BackupValidationError, match="missing"):
        extract_archive(tar_path, tmp_path / "out")


def test_hash_mismatch_rejected(tmp_path):
    members = _valid_members()
    info, _ = members[1]
    members[1] = (info, b"XX-bytes")
    tar_path = _write_tar(tmp_path / "a.tar.gz", members)
    with pytest.raises(BackupValidationError, match="checksum"):
        extract_archive(tar_path, tmp_path / "out")


def test_unsupported_format_version_rejected(tmp_path):
    members = _valid_members(manifest_overrides={"format_version": 2})
    tar_path = _write_tar(tmp_path / "a.tar.gz", members)
    with pytest.raises(BackupValidationError, match="format"):
        extract_archive(tar_path, tmp_path / "out")


def test_oversized_member_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "MAX_STACK_FILE_BYTES", 4)
    tar_path = _write_tar(tmp_path / "a.tar.gz", _valid_members())
    with pytest.raises(BackupValidationError, match="large|malformed"):
        extract_archive(tar_path, tmp_path / "out")


def test_total_expanded_size_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "MAX_TOTAL_BYTES", 20)
    tar_path = _write_tar(tmp_path / "a.tar.gz", _valid_members())
    with pytest.raises(BackupValidationError, match="large"):
        extract_archive(tar_path, tmp_path / "out")


def test_member_count_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "MAX_MEMBERS", 2)
    tar_path = _write_tar(tmp_path / "a.tar.gz", _valid_members())
    with pytest.raises(BackupValidationError, match="many"):
        extract_archive(tar_path, tmp_path / "out")


def test_not_a_gzip_tar_rejected(tmp_path):
    path = tmp_path / "junk.tar.gz"
    path.write_bytes(b"definitely not gzip")
    with pytest.raises(BackupValidationError):
        extract_archive(path, tmp_path / "out")


@pytest.fixture
def key() -> bytes:
    return Fernet.generate_key()


@pytest.fixture
def good_db(tmp_path, head_db_template, key) -> Path:
    path = tmp_path / "dockmon.db"
    shutil.copy2(head_db_template, path)
    seed_database(path, key, "h")
    return path


def test_good_database_passes(good_db, key):
    check_database(good_db, key, HEAD)


def test_older_revision_accepted(tmp_path, older_db_template, key):
    path = tmp_path / "older.db"
    shutil.copy2(older_db_template, path)
    check_database(path, key, OLDER_REVISION)


def test_newer_or_unknown_revision_rejected(good_db, key):
    conn = sqlite3.connect(good_db)
    conn.execute("UPDATE alembic_version SET version_num = '099_from_the_future'")
    conn.commit()
    conn.close()
    with pytest.raises(BackupValidationError, match="newer"):
        check_database(good_db, key, "099_from_the_future")


def test_revision_must_match_manifest(good_db, key):
    with pytest.raises(BackupValidationError, match="manifest"):
        check_database(good_db, key, OLDER_REVISION)


def test_missing_required_table_rejected(good_db, key):
    conn = sqlite3.connect(good_db)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("DROP TABLE users")
    conn.commit()
    conn.close()
    with pytest.raises(BackupValidationError, match="users"):
        check_database(good_db, key, HEAD)


def test_wrong_key_rejected(good_db):
    with pytest.raises(BackupValidationError, match="key"):
        check_database(good_db, Fernet.generate_key(), HEAD)


def test_corrupt_database_rejected(good_db, key):
    data = bytearray(good_db.read_bytes())
    data[len(data) // 2 : len(data) // 2 + 4096] = b"\xff" * 4096
    good_db.write_bytes(bytes(data))
    with pytest.raises(BackupValidationError):
        check_database(good_db, key, HEAD)


def test_not_a_database_rejected(tmp_path, key):
    path = tmp_path / "dockmon.db"
    path.write_bytes(b"not sqlite at all" * 100)
    with pytest.raises(BackupValidationError):
        check_database(path, key, HEAD)


def test_foreign_key_violation_rejected(good_db, key):
    conn = sqlite3.connect(good_db)
    fk_tables = [
        (t, fk)
        for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for fk in conn.execute(f"PRAGMA foreign_key_list('{t}')")
    ]
    assert fk_tables, "schema has no foreign keys to violate"
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO user_group_memberships (user_id, group_id, added_at) VALUES (999, 999, '2026-01-01')"
    )
    conn.commit()
    conn.close()
    with pytest.raises(BackupValidationError, match="foreign key"):
        check_database(good_db, key, HEAD)


@pytest.mark.parametrize(
    "summary",
    [{}, {"hosts": "1", "users": 0, "alert_rules": 0, "stacks": []},
     {"hosts": 0, "users": 0, "alert_rules": 0, "stacks": ["Bad Name"]},
     {"hosts": True, "users": 0, "alert_rules": 0, "stacks": []}],
)
def test_malformed_summary_rejected(tmp_path, summary):
    tar_path = _write_tar(tmp_path / "a.tar.gz", _valid_members(manifest_overrides={"summary": summary}))
    with pytest.raises(BackupValidationError, match="summary"):
        extract_archive(tar_path, tmp_path / "out")


def test_declared_total_must_fit_before_anything_is_written(tmp_path, monkeypatch):
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(validate.shutil, "disk_usage", lambda _p: usage(100, 99, 1))
    tar_path = _write_tar(tmp_path / "a.tar.gz", _valid_members())
    with pytest.raises(BackupSpaceError):
        extract_archive(tar_path, tmp_path / "out")
    assert not (tmp_path / "out" / "dockmon.db").exists()


def test_member_size_must_match_manifest_before_writing(tmp_path):
    members = _valid_members()
    info, _ = members[1]
    members[1] = _regular(info.name, b"longer than declared")
    tar_path = _write_tar(tmp_path / "a.tar.gz", members)
    with pytest.raises(BackupValidationError, match="size"):
        extract_archive(tar_path, tmp_path / "out")
    assert not (tmp_path / "out" / info.name).exists()


@pytest.mark.parametrize("size", [-1, True, 10**12])
def test_manifest_sizes_must_be_plausible(tmp_path, size):
    members = _valid_members()
    manifest = json.loads(members[0][1])
    manifest["files"]["stacks/web/compose.yaml"]["size"] = size
    data = json.dumps(manifest).encode()
    members[0] = _regular("manifest.json", data)
    tar_path = _write_tar(tmp_path / "a.tar.gz", members)
    with pytest.raises(BackupValidationError, match="malformed"):
        extract_archive(tar_path, tmp_path / "out")


@pytest.mark.parametrize(
    "overrides",
    [{"created_at": "2026-09-25 10:00:00"}, {"created_at": "yesterday"}, {"app_version": 5}, {"app_version": "x" * 65}],
)
def test_manifest_timestamp_and_version_are_checked(tmp_path, overrides):
    tar_path = _write_tar(tmp_path / "a.tar.gz", _valid_members(manifest_overrides=overrides))
    with pytest.raises(BackupValidationError):
        extract_archive(tar_path, tmp_path / "out")


def test_wrong_key_for_the_scheduled_passphrase_is_rejected(good_db, key):
    conn = sqlite3.connect(good_db)
    conn.execute(
        "UPDATE global_settings SET backup_passphrase_encrypted = ?",
        (Fernet(Fernet.generate_key()).encrypt(b"scheduled").decode(),),
    )
    conn.commit()
    conn.close()
    with pytest.raises(BackupValidationError, match="key"):
        check_database(good_db, key, HEAD)


def test_backup_from_before_the_scheduled_passphrase_column_is_accepted(tmp_path, older_db_template, key):
    path = tmp_path / "older.db"
    shutil.copy2(older_db_template, path)
    conn = sqlite3.connect(path)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(global_settings)")}
    conn.close()
    assert "backup_passphrase_encrypted" not in columns
    check_database(path, key, OLDER_REVISION)
