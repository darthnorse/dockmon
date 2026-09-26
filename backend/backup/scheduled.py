"""Scheduled backups written to an operator-mounted directory (DOCKMON_BACKUP_DIR, default /backups).

Nothing here emits events, alerts or audit rows: callers run it in a worker
thread and report on the event loop. The caller holds the operation lock for a run.

Files are named dockmon-scheduled-<writer>-<UTC timestamp>-<rand>-<version>.dmbak.
The writer id lives in DATA_DIR, outside the backup, so a restored or cloned
install never lists, serves or prunes another install's files on a shared share.
"""

import errno
import logging
import os
import re
import secrets
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from backup.archive import FREE_SPACE_MARGIN, create_backup, live_database_bytes, managed_stack_bytes, parse_utc_iso, utc_iso
from backup.crypto import DEFAULT_KDF, KdfParams
from backup.errors import (
    BackupBusyError,
    BackupConflictError,
    BackupDecryptError,
    BackupError,
    BackupNotFoundError,
    BackupSpaceError,
    BackupValidationError,
    disk_space_errors,
)
from backup.fsutil import fsync_dir
from backup.paths import BackupPaths
from utils.version import get_app_version

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = "/backups"
MOUNTINFO = Path("/proc/self/mountinfo")
WRITER_ID_FILE = ".backup-writer-id"
ARMED_AT_FILE = ".backup-schedule-armed"
GENERIC_FAILURE = "Scheduled backup failed; see the DockMon log"
MIN_RETENTION, MAX_RETENTION = 1, 365

_FILE_NAME = re.compile(
    r"^dockmon-scheduled-(?P<writer>[0-9a-f]{8})-(?P<stamp>\d{8}T\d{6}\.\d{6}Z)"
    r"-(?P<rand>[0-9a-f]{4})-(?P<version>[A-Za-z0-9._-]{1,32})\.dmbak$"
)
_OTHER_BACKUP = re.compile(r"^dockmon-.+\.dmbak$")
_SAFE_VERSION = re.compile(r"[^A-Za-z0-9._-]")
_UNSUPPORTED_LINK = (errno.EPERM, errno.ENOTSUP, errno.EXDEV, errno.ENOSYS, errno.EOPNOTSUPP)
_UNSUPPORTED_FSYNC = (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP)


class DestinationError(BackupError):
    """The backup destination is missing, not mounted, or not writable."""


@dataclass
class ScheduledRun:
    status: str
    file: Optional[str] = None
    error: Optional[str] = None


def backup_dir() -> Path:
    return Path(os.environ.get("DOCKMON_BACKUP_DIR", DEFAULT_BACKUP_DIR))


def allow_unmounted() -> bool:
    return os.environ.get("DOCKMON_BACKUP_ALLOW_UNMOUNTED", "").strip().lower() in ("1", "true", "yes")


def _read_writer_id(path: Path) -> Optional[str]:
    try:
        value = path.read_text().strip()
    except FileNotFoundError:
        return None
    return value if re.fullmatch(r"[0-9a-f]{8}", value) else None


def writer_id(paths: BackupPaths) -> str:
    """This install's writer id, created once; a corrupt file is replaced."""
    path = paths.data_dir / WRITER_ID_FILE
    for _ in range(3):
        existing = _read_writer_id(path)
        if existing:
            return existing
        tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(4))
            f.flush()
            os.fsync(f.fileno())
        try:
            if os.path.lexists(path):
                os.replace(tmp, path)
            else:
                _link_or_rename(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        _fsync_dir_tolerant(path.parent)
    raise BackupError("Could not create the backup writer id")


def _link_or_rename(tmp: Path, path: Path) -> None:
    """Create path from tmp unless another process got there first."""
    try:
        os.link(tmp, path)
    except FileExistsError:
        return
    except OSError as e:
        if e.errno not in _UNSUPPORTED_LINK:
            raise
        if not os.path.lexists(path):
            os.replace(tmp, path)


def read_armed_at(paths: BackupPaths) -> Optional[datetime]:
    """When scheduling was last enabled or changed on this install (kept outside the backup)."""
    try:
        return parse_utc_iso((paths.data_dir / ARMED_AT_FILE).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def write_armed_at(paths: BackupPaths, at: datetime) -> None:
    path = paths.data_dir / ARMED_AT_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(utc_iso(at))
    os.replace(tmp, path)


def public_error(error: BaseException) -> str:
    """The only text a failure may carry into settings, events, alerts and responses."""
    if isinstance(error, BackupSpaceError):
        return "Not enough disk space for the backup"
    if isinstance(
        error,
        (DestinationError, BackupBusyError, BackupConflictError, BackupNotFoundError, BackupDecryptError,
         BackupValidationError),
    ):
        return str(error)
    return GENERIC_FAILURE


def _decode_mount_path(field: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def _mount_point_of(path: Path) -> Optional[str]:
    try:
        lines = MOUNTINFO.read_text().splitlines()
    except OSError:
        return None
    target = os.path.realpath(path)
    best = None
    for line in lines:
        fields = line.split()
        if len(fields) < 5:
            continue
        mount_point = _decode_mount_path(fields[4])
        inside = target == mount_point or target.startswith(mount_point.rstrip("/") + "/")
        if inside and (best is None or len(mount_point) > len(best)):
            best = mount_point
    return best


def _probe_writable(dest: Path) -> None:
    probe = dest / f".dockmon-write-probe-{secrets.token_hex(4)}"
    fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    probe.unlink()


def destination_status(dest: Path, data_dir: Path) -> dict:
    status = {
        "path": str(dest),
        "exists": dest.is_dir(),
        "is_mountpoint": False,
        "writable": False,
        "same_filesystem_as_data": False,
        "free_bytes": None,
    }
    if not status["exists"]:
        return status
    mount_point = _mount_point_of(dest)
    status["is_mountpoint"] = mount_point not in (None, "/")
    try:
        _probe_writable(dest)
        status["writable"] = True
    except OSError:
        pass
    try:
        status["same_filesystem_as_data"] = dest.stat().st_dev == data_dir.stat().st_dev
        status["free_bytes"] = shutil.disk_usage(dest).free
    except OSError:
        pass
    return status


def _check_destination(dest: Path) -> None:
    if not dest.is_dir():
        raise DestinationError("The backup destination does not exist")
    if _mount_point_of(dest) in (None, "/") and not allow_unmounted():
        raise DestinationError(
            "The backup destination is not a mounted volume, so backups would be lost with the container"
        )
    try:
        _probe_writable(dest)
    except OSError:
        raise DestinationError("DockMon cannot write to the backup destination") from None


def _needed_bytes(paths: BackupPaths) -> int:
    return live_database_bytes(paths.db_path) + managed_stack_bytes(paths.stacks_dir) + FREE_SPACE_MARGIN


def _new_name(writer: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    version = _SAFE_VERSION.sub("_", get_app_version())[:32] or "unknown"
    return f"dockmon-scheduled-{writer}-{stamp}-{secrets.token_hex(2)}-{version}.dmbak"


def _fsync_dir_tolerant(path: Path) -> None:
    try:
        fsync_dir(path)
    except OSError as e:
        if e.errno not in _UNSUPPORTED_FSYNC:
            raise


def _publish(partial: Path, final: Path) -> None:
    """Make the finished file visible under its final name without ever replacing another file."""
    try:
        os.link(partial, final)
        partial.unlink()
    except OSError as e:
        if e.errno not in _UNSUPPORTED_LINK:
            raise
        if os.path.lexists(final):
            raise BackupError("A backup with that name already exists") from None
        os.rename(partial, final)
    _fsync_dir_tolerant(final.parent)


def _own_files(dest: Path, writer: str) -> List[Tuple[str, Path, int]]:
    """This writer's regular files as (stamp, path, size), newest first; entries that vanish mid-scan are skipped."""
    owned = []
    for entry in os.scandir(dest):
        match = _FILE_NAME.match(entry.name)
        if not match or match.group("writer") != writer:
            continue
        try:
            info = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISREG(info.st_mode):
            owned.append((match.group("stamp"), Path(entry.path), info.st_size))
    return sorted(owned, reverse=True)


def _prune(dest: Path, writer: str, keep: int, just_written: Path) -> None:
    others = [path for _stamp, path, _size in _own_files(dest, writer) if path != just_written]
    for path in others[max(keep - 1, 0):]:
        path.unlink()


def run_scheduled_backup(
    paths: BackupPaths,
    dest: Path,
    passphrase: str,
    include_stats: bool,
    retention: int,
    kdf: KdfParams = DEFAULT_KDF,
) -> ScheduledRun:
    """Write one scheduled backup into dest and apply retention. The caller holds the operation lock."""
    writer = writer_id(paths)
    final = dest / _new_name(writer)
    partial = final.with_name(final.name + ".partial")
    try:
        _check_destination(dest)
        if shutil.disk_usage(dest).free < _needed_bytes(paths):
            raise BackupSpaceError("Not enough free space at the backup destination")
        with disk_space_errors("Ran out of disk space while writing the scheduled backup"):
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                create_backup(paths, f, passphrase, include_stats=include_stats, kdf=kdf)
                f.flush()
                os.fsync(f.fileno())
            _publish(partial, final)
    except Exception as e:
        partial.unlink(missing_ok=True)
        logger.error(f"Scheduled backup failed: {e}", exc_info=not isinstance(e, BackupError))
        return ScheduledRun(status="failed", error=public_error(e))

    try:
        _prune(dest, writer, retention, final)
    except Exception as e:
        logger.warning(f"Scheduled backup retention failed: {e}")
        return ScheduledRun(status="warning", file=final.name, error="The backup was written, but applying retention failed")
    return ScheduledRun(status="ok", file=final.name)


def sweep_partials(dest: Path, writer: str) -> None:
    """Remove this writer's partial files left by a run that was killed. Caller holds the operation lock."""
    if not dest.is_dir():
        return
    for entry in os.scandir(dest):
        if entry.name.endswith(".dmbak.partial"):
            match = _FILE_NAME.match(entry.name[: -len(".partial")])
            if match and match.group("writer") == writer and entry.is_file(follow_symlinks=False):
                Path(entry.path).unlink(missing_ok=True)


def list_files(dest: Path, writer: str) -> dict:
    if not dest.is_dir():
        return {"files": [], "other_backups": 0}
    files = [
        {"name": path.name, "size": size, "created_at": utc_iso(datetime.strptime(stamp, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc))}
        for stamp, path, size in _own_files(dest, writer)
    ]
    other = sum(
        1
        for entry in os.scandir(dest)
        if _OTHER_BACKUP.match(entry.name)
        and not ((match := _FILE_NAME.match(entry.name)) and match.group("writer") == writer)
    )
    return {"files": files, "other_backups": other}


def _own_file_path(dest: Path, writer: str, name: str) -> Path:
    match = _FILE_NAME.match(name or "")
    if not match or match.group("writer") != writer:
        raise BackupNotFoundError("No such backup file")
    return dest / name


def scheduled_file_path(dest: Path, writer: str, name: str) -> Path:
    """The path of one of this writer's regular files (not a symlink)."""
    path = _own_file_path(dest, writer, name)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise BackupNotFoundError("No such backup file") from None
    if not stat.S_ISREG(info.st_mode):
        raise BackupNotFoundError("No such backup file")
    return path


def open_file(dest: Path, writer: str, name: str) -> Tuple[int, int]:
    """Open one of this writer's regular files without following symlinks; returns (fd, size).

    O_NONBLOCK so a FIFO planted under a backup name cannot block the open.
    """
    path = _own_file_path(dest, writer, name)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise BackupNotFoundError("No such backup file") from None
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise BackupNotFoundError("No such backup file")
    return fd, info.st_size


def delete_file(dest: Path, writer: str, name: str) -> None:
    scheduled_file_path(dest, writer, name).unlink()
