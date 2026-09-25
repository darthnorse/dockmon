"""Server-side backup files waiting to be downloaded.

A backup is created by one request and fetched by a plain GET, so the browser
streams it to disk instead of holding it in memory. Only the newest one is
kept, and it expires after DOWNLOAD_TTL.
"""

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from backup.archive import create_backup
from backup.crypto import KdfParams
from backup.errors import BackupNotFoundError
from backup.fsutil import fsync_dir
from backup.paths import BackupPaths

DOWNLOAD_TTL = timedelta(minutes=15)
_DOWNLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
_SAFE_VERSION = re.compile(r"[^A-Za-z0-9._-]")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.replace(tzinfo=None).isoformat() + "Z"


def _meta_path(paths: BackupPaths, download_id: str) -> Path:
    return paths.downloads_dir / f"{download_id}.json"


def _file_path(paths: BackupPaths, download_id: str) -> Path:
    return paths.downloads_dir / f"{download_id}.dmbak"


def _entries(paths: BackupPaths) -> List[Tuple[str, dict]]:
    found = []
    for meta_path in paths.downloads_dir.glob("*.json") if paths.downloads_dir.exists() else []:
        try:
            found.append((meta_path.stem, json.loads(meta_path.read_text())))
        except (OSError, ValueError):
            continue
    return found


def _delete(paths: BackupPaths, download_id: str) -> None:
    _file_path(paths, download_id).unlink(missing_ok=True)
    _meta_path(paths, download_id).unlink(missing_ok=True)


def sweep(paths: BackupPaths, keep_none: bool = False) -> None:
    """Delete expired downloads (or all of them), plus partial files left by a crash."""
    if not paths.downloads_dir.exists():
        return
    now = _now()
    live = set()
    for download_id, meta in _entries(paths):
        expires = meta.get("expires_at", "")
        try:
            expired = datetime.fromisoformat(expires.rstrip("Z")).replace(tzinfo=timezone.utc) <= now
        except (AttributeError, ValueError):
            expired = True
        if keep_none or expired:
            _delete(paths, download_id)
        else:
            live.add(download_id)
    for leftover in paths.downloads_dir.iterdir():
        if leftover.stem not in live:
            leftover.unlink(missing_ok=True)


def create_download(paths: BackupPaths, passphrase: str, include_stats: bool, kdf: KdfParams) -> dict:
    """Write a new backup for download, replacing any earlier one. Caller holds the operation lock."""
    sweep(paths, keep_none=True)
    paths.downloads_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    download_id = uuid.uuid4().hex
    partial = paths.downloads_dir / f"{download_id}.partial"
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            manifest = create_backup(paths, f, passphrase, include_stats=include_stats, kdf=kdf)
            f.flush()
            os.fsync(f.fileno())
        os.rename(partial, _file_path(paths, download_id))
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    created = _now()
    version = _SAFE_VERSION.sub("_", manifest["app_version"])[:32]
    meta = {
        "download_id": download_id,
        "filename": f"dockmon-backup-{version}-{created.strftime('%Y%m%dT%H%M%SZ')}.dmbak",
        "size": _file_path(paths, download_id).stat().st_size,
        "created_at": _iso(created),
        "expires_at": _iso(created + DOWNLOAD_TTL),
        "alembic_revision": manifest["alembic_revision"],
        "stats_history_included": manifest["stats_history_included"],
    }
    with open(_meta_path(paths, download_id), "w") as f:
        json.dump(meta, f)
        f.flush()
        os.fsync(f.fileno())
    fsync_dir(paths.downloads_dir)
    return meta


def current_download(paths: BackupPaths) -> Optional[dict]:
    sweep(paths)
    entries = _entries(paths)
    return entries[0][1] if entries else None


def open_download(paths: BackupPaths, download_id: str) -> Tuple[Path, dict]:
    if not _DOWNLOAD_ID.match(download_id or ""):
        raise BackupNotFoundError("No such backup download")
    sweep(paths)
    meta_path, file_path = _meta_path(paths, download_id), _file_path(paths, download_id)
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        raise BackupNotFoundError("No such backup download") from None
    if not file_path.is_file():
        raise BackupNotFoundError("No such backup download")
    return file_path, meta
