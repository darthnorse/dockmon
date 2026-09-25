import hashlib
import io
import json
import sqlite3
import tarfile
from collections import namedtuple
from pathlib import Path

import pytest

from backup import archive
from deployment import stack_storage
from backup.archive import create_backup
from backup.crypto import decrypt_stream
from backup.errors import BackupError, BackupSpaceError
from backup.validate import extract_archive
from tests.unit.backup.conftest import FAST_KDF, HEAD_REVISION, PASSPHRASE, host_names

EXPECTED_FILES = {
    "manifest.json",
    "dockmon.db",
    "encryption.key",
    "stacks/web/compose.yaml",
    "stacks/web/.env",
    "stacks/web/app.env",
    "stacks/web/.env.prod",
    "stacks/api/docker-compose.yml",
}


def _backup(paths, **kwargs) -> bytes:
    out = io.BytesIO()
    create_backup(paths, out, PASSPHRASE, kdf=FAST_KDF, **kwargs)
    return out.getvalue()


def _open(blob: bytes, tmp_path: Path) -> tuple:
    tar_path = tmp_path / "backup.tar.gz"
    with open(tar_path, "wb") as f:
        decrypt_stream(io.BytesIO(blob), f, PASSPHRASE)
    dest = tmp_path / "extracted"
    manifest = extract_archive(tar_path, dest)
    return manifest, dest


def _files_under(root: Path) -> set:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_archive_contains_exactly_the_allowlisted_files(install, tmp_path):
    manifest, dest = _open(_backup(install), tmp_path)

    assert _files_under(dest) == EXPECTED_FILES
    assert set(manifest["files"]) == EXPECTED_FILES - {"manifest.json"}


def test_bind_mount_data_symlinks_and_invalid_stacks_are_excluded(install, tmp_path):
    _, dest = _open(_backup(install), tmp_path)
    names = _files_under(dest)

    assert not any("data/db.sqlite" in n for n in names)
    assert "stacks/web/notes.txt" not in names
    assert "stacks/web/link.env" not in names
    assert not any(n.startswith("stacks/Bad Name") for n in names)


def test_extracted_content_matches_source(install, tmp_path):
    _, dest = _open(_backup(install), tmp_path)

    assert (dest / "encryption.key").read_bytes() == install.key_path.read_bytes()
    assert (dest / "stacks/web/.env").read_text() == "A=old\n"
    assert host_names(dest / "dockmon.db") == ["source-host"]


def test_manifest_describes_the_backup(install, tmp_path):
    manifest, dest = _open(_backup(install), tmp_path)

    assert manifest["format_version"] == 1
    assert manifest["alembic_revision"] == HEAD_REVISION
    assert manifest["created_at"].endswith("Z")
    assert manifest["stats_history_included"] is True
    assert manifest["summary"]["hosts"] == 1
    assert manifest["summary"]["stacks"] == ["api", "web"]
    for name, entry in manifest["files"].items():
        content = (dest / name).read_bytes()
        assert entry["size"] == len(content)
        assert entry["sha256"] == hashlib.sha256(content).hexdigest()


def test_snapshot_includes_committed_wal_data_and_excludes_uncommitted(install, tmp_path):
    committed = sqlite3.connect(install.db_path)
    committed.execute("PRAGMA wal_autocheckpoint=0")
    committed.execute(
        "INSERT INTO docker_hosts (id, name, url, is_podman, connection_type) "
        "VALUES ('h2', 'committed-host', 'tcp://x:2376', 0, 'remote')"
    )
    committed.commit()

    writer = sqlite3.connect(install.db_path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute(
        "INSERT INTO docker_hosts (id, name, url, is_podman, connection_type) "
        "VALUES ('h3', 'uncommitted-host', 'tcp://y:2376', 0, 'remote')"
    )
    try:
        _, dest = _open(_backup(install), tmp_path)
    finally:
        writer.execute("ROLLBACK")
        writer.close()
        committed.close()

    assert host_names(dest / "dockmon.db") == ["committed-host", "source-host"]


def test_excluding_stats_history_empties_only_the_snapshot(install, tmp_path):
    manifest, dest = _open(_backup(install, include_stats=False), tmp_path)

    assert manifest["stats_history_included"] is False
    assert _count(dest / "dockmon.db", "container_stats_history") == 0
    assert _count(dest / "dockmon.db", "host_stats_history") == 0
    assert _count(install.db_path, "container_stats_history") == 1
    assert _count(install.db_path, "host_stats_history") == 1


def test_stack_file_changed_during_snapshot_is_recopied(install, tmp_path, monkeypatch):
    original = archive._snapshot_database
    calls = []

    def snapshot_then_edit(*args, **kwargs):
        result = original(*args, **kwargs)
        if not calls:
            (install.stacks_dir / "web" / ".env").write_text("A=edited-during-backup\n")
        calls.append(1)
        return result

    monkeypatch.setattr(archive, "_snapshot_database", snapshot_then_edit)
    _, dest = _open(_backup(install), tmp_path)

    assert (dest / "stacks/web/.env").read_text() == "A=edited-during-backup\n"


def test_stacks_that_never_settle_fail_the_backup(install, monkeypatch):
    counter = iter(range(10_000))
    monkeypatch.setattr(
        archive, "_stack_fingerprint", lambda files: next(counter)
    )
    with pytest.raises(BackupError, match="changing"):
        _backup(install)


def test_insufficient_free_space_fails_before_snapshot(install, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(archive.shutil, "disk_usage", lambda _p: usage(100, 99, 1))
    with pytest.raises(BackupError, match="space"):
        _backup(install)
    assert not (install.data_dir / ".backup-tmp").exists() or not any(
        (install.data_dir / ".backup-tmp").iterdir()
    )


def test_temp_files_removed_after_success(install):
    _backup(install)
    tmp_root = install.data_dir / ".backup-tmp"
    assert not tmp_root.exists() or not any(tmp_root.iterdir())


def test_temp_files_removed_after_failure(install, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("disk exploded")

    monkeypatch.setattr(archive, "encrypt_stream", boom)
    with pytest.raises(OSError):
        _backup(install)
    tmp_root = install.data_dir / ".backup-tmp"
    assert not tmp_root.exists() or not any(tmp_root.iterdir())


def test_short_passphrase_rejected_before_any_work(install, monkeypatch):
    monkeypatch.setattr(
        archive, "_snapshot_database", lambda *a, **k: pytest.fail("snapshot ran")
    )
    with pytest.raises(ValueError):
        create_backup(install, io.BytesIO(), "short", kdf=FAST_KDF)


def test_manifest_is_the_first_member(install, tmp_path):
    tar_path = tmp_path / "raw.tar.gz"
    with open(tar_path, "wb") as f:
        decrypt_stream(io.BytesIO(_backup(install)), f, PASSPHRASE)
    with tarfile.open(tar_path, "r:gz") as tf:
        first = tf.next()
        assert first.name == "manifest.json"
        assert json.load(tf.extractfile(first))["format_version"] == 1


def test_creation_enforces_the_restore_member_limit(install, monkeypatch):
    monkeypatch.setattr(archive, "MAX_MEMBERS", 3)
    with pytest.raises(BackupError, match="files"):
        _backup(install)


def test_managed_stack_files_does_not_parse_an_oversized_compose(install, monkeypatch):
    monkeypatch.setattr(stack_storage, "MAX_COMPOSE_SCAN_BYTES", 10)
    files = stack_storage.managed_stack_files(install.stacks_dir / "web")
    assert [p.name for p in files] == ["compose.yaml"]


def test_creation_total_counts_the_manifest_like_restore_does(install, monkeypatch):
    manifest = create_backup(install, io.BytesIO(), PASSPHRASE, kdf=FAST_KDF)
    payload = sum(entry["size"] for entry in manifest["files"].values())
    monkeypatch.setattr(archive, "MAX_TOTAL_BYTES", payload + 10)
    with pytest.raises(BackupError, match="limit"):
        _backup(install)


def test_stack_bytes_held_in_memory_are_capped(install, monkeypatch):
    monkeypatch.setattr(archive, "MAX_STACK_BYTES_IN_MEMORY", 10)
    with pytest.raises(BackupError, match="stack"):
        _backup(install)


def test_insufficient_space_is_a_space_error(install, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(archive.shutil, "disk_usage", lambda _p: usage(100, 99, 1))
    with pytest.raises(BackupSpaceError):
        _backup(install)
