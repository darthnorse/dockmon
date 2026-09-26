"""Create an encrypted backup of DockMon's own state.

The archive holds a VACUUM INTO snapshot of the database, the Fernet key the
snapshot's encrypted columns need, and the compose/env files DockMon manages.
Container data (including relative bind mounts inside stack directories) is
deliberately not included.
"""

import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Dict, List, Tuple

from backup.crypto import DEFAULT_KDF, MIN_PASSPHRASE_LENGTH, KdfParams, encrypt_stream
from backup.errors import BackupError, BackupSpaceError, disk_space_errors
from backup.fsutil import IO_BLOCK
from backup.paths import BackupPaths
from utils.stack_files import managed_stack_files, validate_stack_name
from utils.version import get_app_version

logger = logging.getLogger(__name__)

MANIFEST_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DB_NAME = "dockmon.db"
KEY_NAME = "encryption.key"
STACKS_PREFIX = "stacks"
STATS_HISTORY_TABLES = ("container_stats_history", "host_stats_history")
STACK_COPY_ATTEMPTS = 3
FREE_SPACE_MARGIN = 256 * 1024 * 1024

# Format limits: creation enforces them so it never writes an archive restore rejects.
MAX_MEMBERS = 10_000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_KEY_BYTES = 4096
MAX_STACK_FILE_BYTES = 16 * 1024 * 1024
MAX_DB_BYTES = 64 * 1024**3
MAX_TOTAL_BYTES = 64 * 1024**3
# Encrypted file cap: members plus tar, gzip and per-chunk GCM overhead.
MAX_ARCHIVE_BYTES = MAX_TOTAL_BYTES + MAX_TOTAL_BYTES // 64 + 64 * 1024 * 1024
MAX_STACK_BYTES_IN_MEMORY = 256 * 1024 * 1024


def create_backup(
    paths: BackupPaths,
    dest: BinaryIO,
    passphrase: str,
    include_stats: bool = True,
    kdf: KdfParams = DEFAULT_KDF,
) -> dict:
    """Write an encrypted backup to dest and return its manifest."""
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise ValueError(f"Passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters")
    if not paths.key_path.is_file():
        raise BackupError(f"Encryption key not found at {paths.key_path}")

    paths.backup_tmp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=paths.backup_tmp_dir))
    try:
        with disk_space_errors("Ran out of disk space while writing the backup"):
            stack_files = _collect_stack_files(paths.stacks_dir)
            _check_free_space(paths.db_path, work, _total_size(stack_files))
            snapshot = work / DB_NAME
            before = _stack_fingerprint(stack_files)
            _snapshot_database(paths.db_path, snapshot, include_stats)
            stacks = _read_stacks_consistently(paths.stacks_dir, before)
            key = paths.key_path.read_bytes()

            manifest = build_manifest(snapshot, key, stacks, include_stats)
            _check_format_limits(manifest)
            tar_path = work / "backup.tar.gz"
            _write_tar(tar_path, manifest, snapshot, key, stacks)
            with open(tar_path, "rb") as src:
                encrypt_stream(src, dest, passphrase, kdf=kdf)
            return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def utc_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def utc_now_iso() -> str:
    return utc_iso(datetime.now(timezone.utc))


def _check_format_limits(manifest: dict) -> None:
    files = manifest["files"]
    if len(files) + 1 > MAX_MEMBERS:
        raise BackupError(f"Backup would contain {len(files) + 1} files; the limit is {MAX_MEMBERS}")
    if files[DB_NAME]["size"] > MAX_DB_BYTES:
        raise BackupError(f"Database is larger than the {MAX_DB_BYTES} byte backup limit")
    if files[KEY_NAME]["size"] > MAX_KEY_BYTES:
        raise BackupError("Encryption key file is unexpectedly large")
    manifest_size = len(_manifest_bytes(manifest))
    if manifest_size > MAX_MANIFEST_BYTES:
        raise BackupError("Backup manifest would exceed its size limit")
    if manifest_size + sum(entry["size"] for entry in files.values()) > MAX_TOTAL_BYTES:
        raise BackupError(f"Backup would exceed the {MAX_TOTAL_BYTES} byte limit")


def _manifest_bytes(manifest: dict) -> bytes:
    return json.dumps(manifest, indent=2, sort_keys=True).encode()


def build_manifest(db_path: Path, key: bytes, stacks: Dict[str, bytes], include_stats: bool) -> dict:
    revision, summary = _describe_database(db_path)
    files = {DB_NAME: {"size": db_path.stat().st_size, "sha256": _sha256_file(db_path)}}
    files[KEY_NAME] = _entry(key)
    for name, data in stacks.items():
        files[name] = _entry(data)
    summary["stacks"] = sorted({name.split("/")[1] for name in stacks})
    return {
        "format_version": MANIFEST_FORMAT_VERSION,
        "app_version": get_app_version(),
        "alembic_revision": revision,
        "created_at": utc_now_iso(),
        "stats_history_included": include_stats,
        "files": files,
        "summary": summary,
    }


def _entry(data: bytes) -> dict:
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(IO_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def _live_database_bytes(db_path: Path) -> int:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
    finally:
        conn.close()
    return page_size * (page_count - free_pages)


def _total_size(files: List[Tuple[str, Path]]) -> int:
    total = 0
    for _name, path in files:
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total


def _check_free_space(db_path: Path, work: Path, stack_bytes: int) -> None:
    # snapshot, compressed tar and encrypted output can all sit on this filesystem at once
    needed = 3 * (_live_database_bytes(db_path) + stack_bytes) + FREE_SPACE_MARGIN
    free = shutil.disk_usage(work).free
    if free < needed:
        raise BackupSpaceError(
            f"Not enough free disk space for a backup: need {needed // (1024 * 1024)} MiB, "
            f"have {free // (1024 * 1024)} MiB"
        )


def _snapshot_database(db_path: Path, dest: Path, include_stats: bool) -> None:
    src = sqlite3.connect(db_path, timeout=30)
    try:
        src.execute("VACUUM INTO ?", (str(dest),))
    finally:
        src.close()
    os.chmod(dest, 0o600)
    if include_stats:
        return
    snap = sqlite3.connect(dest)
    try:
        existing = {r[0] for r in snap.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in STATS_HISTORY_TABLES:
            if table in existing:
                snap.execute(f'DELETE FROM "{table}"')
        snap.commit()
        snap.execute("VACUUM")
    finally:
        snap.close()


def _describe_database(db_path: Path) -> Tuple[str, dict]:
    conn = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "alembic_version" not in tables:
            raise BackupError("Database has no schema version; refusing to back it up")
        revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]

        def count(table: str) -> int:
            if table not in tables:
                return 0
            return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

        summary = {
            "hosts": count("docker_hosts"),
            "users": count("users"),
            "alert_rules": count("alert_rules_v2"),
        }
    finally:
        conn.close()
    return revision, summary


def _collect_stack_files(stacks_dir: Path) -> List[Tuple[str, Path]]:
    if not stacks_dir.is_dir():
        return []
    collected = []
    for stack_dir in sorted(stacks_dir.iterdir()):
        if stack_dir.is_symlink() or not stack_dir.is_dir():
            continue
        try:
            validate_stack_name(stack_dir.name)
        except ValueError:
            if not stack_dir.name.startswith("."):
                logger.warning(f"Skipping stack directory with an invalid name: {stack_dir.name!r}")
            continue
        for path in managed_stack_files(stack_dir):
            collected.append((f"{STACKS_PREFIX}/{stack_dir.name}/{path.name}", path))
    return collected


def _stack_fingerprint(files: List[Tuple[str, Path]]) -> tuple:
    fingerprint = []
    for name, path in files:
        try:
            st = path.stat()
            fingerprint.append((name, st.st_size, st.st_mtime_ns, st.st_ino))
        except FileNotFoundError:
            fingerprint.append((name, None))
    return tuple(fingerprint)


def _read_stacks_consistently(stacks_dir: Path, before: tuple) -> Dict[str, bytes]:
    """Read stack files, retrying while they change under us.

    `before` was taken ahead of the database snapshot, so an edit made during the
    snapshot also forces a re-read.
    """
    for _ in range(STACK_COPY_ATTEMPTS):
        files = _collect_stack_files(stacks_dir)
        contents = {}
        held = 0
        try:
            for name, path in files:
                size = path.stat().st_size
                if size > MAX_STACK_FILE_BYTES:
                    raise BackupError(f"{name} is larger than {MAX_STACK_FILE_BYTES} bytes")
                held += size
                if held > MAX_STACK_BYTES_IN_MEMORY:
                    raise BackupError(f"Managed stack files exceed {MAX_STACK_BYTES_IN_MEMORY} bytes in total")
                contents[name] = path.read_bytes()
        except FileNotFoundError:
            contents = None
        after = _stack_fingerprint(files)
        if contents is not None and after == before:
            return contents
        before = after
    raise BackupError("Stack files kept changing during the backup; try again")


def _tar_info(name: str, size: int, mtime: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o600
    info.mtime = mtime
    return info


def _write_tar(tar_path: Path, manifest: dict, snapshot: Path, key: bytes, stacks: Dict[str, bytes]) -> None:
    mtime = int(time.time())
    manifest_bytes = _manifest_bytes(manifest)
    # GNU, not USTAR: USTAR cannot encode members of 8 GiB or more, and PAX headers are refused on restore.
    with tarfile.open(tar_path, "w:gz", format=tarfile.GNU_FORMAT) as tf:
        tf.addfile(_tar_info(MANIFEST_NAME, len(manifest_bytes), mtime), io.BytesIO(manifest_bytes))
        with open(snapshot, "rb") as f:
            tf.addfile(_tar_info(DB_NAME, snapshot.stat().st_size, mtime), f)
        tf.addfile(_tar_info(KEY_NAME, len(key), mtime), io.BytesIO(key))
        for name, data in stacks.items():
            tf.addfile(_tar_info(name, len(data), mtime), io.BytesIO(data))

