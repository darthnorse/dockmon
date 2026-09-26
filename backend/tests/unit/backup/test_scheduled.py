import errno
import threading
import io
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backup import scheduled
from backup.crypto import decrypt_stream
from backup.errors import BackupBusyError, BackupNotFoundError, BackupSpaceError
from backup.scheduled import (
    ScheduledRun,
    delete_file,
    destination_status,
    list_files,
    open_file,
    public_error,
    run_scheduled_backup,
    writer_id,
)
from tests.unit.backup.conftest import FAST_KDF, PASSPHRASE


@pytest.fixture
def dest(tmp_path, monkeypatch):
    path = tmp_path / "nas"
    path.mkdir()
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "22 1 0:21 / / rw - overlay overlay rw\n"
        f"23 22 0:40 / {str(path).replace(' ', chr(92) + '040')} rw - nfs4 nas:/export rw\n"
    )
    monkeypatch.setattr(scheduled, "MOUNTINFO", mountinfo)
    monkeypatch.delenv("DOCKMON_BACKUP_ALLOW_UNMOUNTED", raising=False)
    return path


def _run(install, dest, retention=7, include_stats=True) -> ScheduledRun:
    return run_scheduled_backup(
        install, dest, PASSPHRASE, include_stats=include_stats, retention=retention, kdf=FAST_KDF
    )


def _name(writer: str, stamp: str, version: str = "2.5.1", rand: str = "abcd") -> str:
    return f"dockmon-scheduled-{writer}-{stamp}-{rand}-{version}.dmbak"


def test_run_writes_a_decryptable_archive_and_lists_it(install, dest):
    result = _run(install, dest)

    assert result.status == "ok", result.error
    files = list_files(dest, writer_id(install))["files"]
    assert [f["name"] for f in files] == [result.file]
    assert files[0]["created_at"].endswith("Z")
    out = io.BytesIO()
    with open(dest / result.file, "rb") as f:
        decrypt_stream(f, out, PASSPHRASE)
    assert not list(dest.glob("*.partial"))
    assert oct((dest / result.file).stat().st_mode & 0o777) == oct(0o600)


def test_writer_id_is_stable_and_kept_out_of_the_database(install):
    first = writer_id(install)
    assert first == writer_id(install)
    assert len(first) == 8
    assert (install.data_dir / ".backup-writer-id").read_text().strip() == first


def test_retention_orders_by_timestamp_not_version_and_ignores_foreign_files(install, dest):
    writer = writer_id(install)
    old_new_version = _name(writer, "20260101T030000.000000Z", version="2.10.0")
    newer_old_version = _name(writer, "20260201T030000.000000Z", version="2.9.1")
    for name in (old_new_version, newer_old_version):
        (dest / name).write_bytes(b"x")
    foreign = [
        "dockmon-backup-2.5.1-20260101T030000Z.dmbak",
        _name("ffffffff", "20250101T030000.000000Z"),
        "notes.txt",
    ]
    for name in foreign:
        (dest / name).write_bytes(b"x")
    (dest / _name(writer, "20240101T030000.000000Z")).mkdir()

    result = _run(install, dest, retention=2)

    assert result.status == "ok"
    remaining = {p.name for p in dest.iterdir()}
    assert result.file in remaining
    assert newer_old_version in remaining
    assert old_new_version not in remaining
    assert set(foreign) <= remaining
    assert list_files(dest, writer)["other_backups"] == 2


def test_the_file_just_written_survives_a_backwards_clock(install, dest):
    writer = writer_id(install)
    future = _name(writer, "29990101T000000.000000Z")
    (dest / future).write_bytes(b"x")

    result = _run(install, dest, retention=1)

    assert (dest / result.file).exists()


def test_missing_destination_fails_without_leftovers(install, tmp_path, monkeypatch):
    result = _run(install, tmp_path / "does-not-exist")
    assert result.status == "failed"
    assert result.error == "The backup destination does not exist"


def test_unmounted_destination_fails_unless_allowed(install, tmp_path, monkeypatch, dest):
    plain = tmp_path / "container-layer"
    plain.mkdir()
    result = _run(install, plain)
    assert result.status == "failed"
    assert "not a mounted volume" in result.error

    monkeypatch.setenv("DOCKMON_BACKUP_ALLOW_UNMOUNTED", "true")
    assert _run(install, plain).status == "ok"


def test_unwritable_destination_fails(install, dest, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(scheduled, "_probe_writable", refuse)
    result = _run(install, dest)
    assert result.status == "failed"
    assert result.error == "DockMon cannot write to the backup destination"


def test_out_of_space_while_writing_leaves_no_partial(install, dest, monkeypatch):
    def full(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(scheduled, "create_backup", full)
    result = _run(install, dest)
    assert result.status == "failed"
    assert "space" in result.error
    assert list(dest.iterdir()) == []


def test_publish_falls_back_when_hard_links_are_unsupported(install, dest, monkeypatch):
    writer_id(install)
    def no_links(*_args, **_kwargs):
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(scheduled.os, "link", no_links)
    result = _run(install, dest)
    assert result.status == "ok"
    assert (dest / result.file).is_file()
    assert not list(dest.glob("*.partial"))


def test_directory_fsync_unsupported_on_the_share_is_tolerated(install, dest, monkeypatch):
    writer_id(install)
    def cifs_fsync(_path):
        raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(scheduled, "fsync_dir", cifs_fsync)
    assert _run(install, dest).status == "ok"


def test_prune_failure_is_a_warning(install, dest, monkeypatch):
    writer = writer_id(install)
    (dest / _name(writer, "20200101T000000.000000Z")).write_bytes(b"x")
    real_unlink = Path.unlink

    def stuck(self, *args, **kwargs):
        if "20200101" in self.name:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", stuck)
    result = _run(install, dest, retention=1)
    assert result.status == "warning"
    assert "retention" in result.error


def test_destination_status(install, dest):
    status = destination_status(dest, install.data_dir)
    assert status["exists"] and status["writable"] and status["is_mountpoint"]
    assert status["same_filesystem_as_data"] is True
    assert status["free_bytes"] > 0
    assert not [p for p in dest.iterdir()]


def test_mountinfo_escapes_are_decoded(install, tmp_path, monkeypatch):
    spaced = tmp_path / "my backups"
    spaced.mkdir()
    mountinfo = tmp_path / "mountinfo2"
    mountinfo.write_text(f"23 22 0:40 / {str(spaced).replace(' ', chr(92) + '040')} rw - cifs //nas/b rw\n")
    monkeypatch.setattr(scheduled, "MOUNTINFO", mountinfo)
    assert destination_status(spaced, install.data_dir)["is_mountpoint"] is True


def test_open_and_delete_accept_only_this_writers_regular_files(install, dest):
    result = _run(install, dest)
    fd, size = open_file(dest, writer_id(install), result.file)
    os.close(fd)
    assert size == (dest / result.file).stat().st_size

    other = _name("ffffffff", "20260101T030000.000000Z")
    (dest / other).write_bytes(b"x")
    link = _name(writer_id(install), "20260102T030000.000000Z")
    os.symlink("/etc/hostname", dest / link)
    for bad in ("../../etc/passwd", other, link, "dockmon-backup-x.dmbak", ""):
        with pytest.raises(BackupNotFoundError):
            open_file(dest, writer_id(install), bad)
        with pytest.raises(BackupNotFoundError):
            delete_file(dest, writer_id(install), bad)

    delete_file(dest, writer_id(install), result.file)
    assert not (dest / result.file).exists()


def test_public_error_never_leaks_unexpected_exception_text():
    assert public_error(RuntimeError("/app/data/secret path")) == "Scheduled backup failed; see the DockMon log"
    assert public_error(BackupBusyError("Another backup or restore operation is running")) == (
        "Another backup or restore operation is running"
    )
    assert "space" in public_error(BackupSpaceError("Ran out of disk space"))


def test_space_check_ignores_bind_mount_data_that_is_never_backed_up(install, dest, monkeypatch):
    big = install.stacks_dir / "web" / "data" / "huge.bin"
    big.write_bytes(b"x" * (4 * 1024 * 1024))
    needed = scheduled._needed_bytes(install)
    assert needed < 4 * 1024 * 1024 + scheduled.FREE_SPACE_MARGIN


def test_a_fifo_with_a_backup_name_is_refused_without_hanging(install, dest):
    fifo = dest / f"dockmon-scheduled-{writer_id(install)}-20260101T000000.000000Z-abcd-2.5.1.dmbak"
    os.mkfifo(fifo)
    with pytest.raises(BackupNotFoundError):
        open_file(dest, writer_id(install), fifo.name)
    with pytest.raises(BackupNotFoundError):
        scheduled.scheduled_file_path(dest, writer_id(install), fifo.name)


def test_writer_id_is_created_once_even_when_raced(install, monkeypatch):
    ids = set()
    threads = [threading.Thread(target=lambda: ids.add(writer_id(install))) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(ids) == 1
    assert (install.data_dir / ".backup-writer-id").read_text().strip() in ids
