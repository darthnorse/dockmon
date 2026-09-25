import errno
import json
from datetime import datetime, timedelta, timezone

import pytest

from backup import downloads
from backup.errors import BackupSpaceError
from backup.downloads import create_download, current_download, open_download, sweep
from backup.restore import apply_staged
from tests.unit.backup.conftest import FAST_KDF, PASSPHRASE


def _expire(paths, download_id):
    meta_path = paths.downloads_dir / f"{download_id}.json"
    meta = json.loads(meta_path.read_text())
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None).isoformat() + "Z"
    meta_path.write_text(json.dumps(dict(meta, expires_at=past)))


def test_unlocked_sweep_never_touches_an_in_progress_backup(install):
    install.downloads_dir.mkdir(parents=True)
    partial = install.downloads_dir / ("a" * 32 + ".partial")
    partial.write_bytes(b"half written")
    orphan = install.downloads_dir / ("b" * 32 + ".dmbak")
    orphan.write_bytes(b"renamed, meta not written yet")
    half_meta = install.downloads_dir / ("c" * 32 + ".json")
    half_meta.write_text('{"download_id": "cc')

    assert current_download(install) is None
    sweep(install)

    assert partial.exists() and orphan.exists() and half_meta.exists()


def test_locked_sweep_removes_leftovers_of_an_interrupted_create(install):
    install.downloads_dir.mkdir(parents=True)
    partial = install.downloads_dir / ("a" * 32 + ".partial")
    partial.write_bytes(b"half written")

    sweep(install, locked=True)

    assert not partial.exists()


def test_expired_downloads_are_removed_by_any_sweep(install):
    meta = create_download(install, PASSPHRASE, True, FAST_KDF)
    _expire(install, meta["download_id"])

    sweep(install)

    assert list(install.downloads_dir.iterdir()) == []


def test_meta_is_written_atomically(install, monkeypatch):
    written = []
    real_replace = downloads.os.replace

    def spy(src, dst):
        written.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(downloads.os, "replace", spy)
    meta = create_download(install, PASSPHRASE, True, FAST_KDF)
    assert any(dst.endswith(f"{meta['download_id']}.json") for _src, dst in written)


def test_startup_sweeps_expired_downloads(install):
    meta = create_download(install, PASSPHRASE, True, FAST_KDF)
    _expire(install, meta["download_id"])

    apply_staged(install, lambda _p: True)

    assert not (install.downloads_dir / f"{meta['download_id']}.dmbak").exists()


def test_live_download_survives_startup_and_stays_downloadable(install):
    meta = create_download(install, PASSPHRASE, True, FAST_KDF)
    apply_staged(install, lambda _p: True)
    path, _ = open_download(install, meta["download_id"])
    assert path.exists()


def test_failed_metadata_write_leaves_no_orphaned_backup(install, monkeypatch):
    def full(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(downloads.os, "replace", full)
    with pytest.raises(BackupSpaceError):
        create_download(install, PASSPHRASE, True, FAST_KDF)
    assert list(install.downloads_dir.iterdir()) == []
