"""Stage a backup for restore, and apply it on the next start.

`manage_backup.py apply-staged` runs from startup.sh before migrations and
before supervisord, so nothing holds the database while it runs.

The swap is journaled so that power loss at any point ends fully old or fully
new. Every move is an os.rename within one filesystem (staging and rollback
copies live in a `.dockmon-restore` directory next to each target, and the
device is checked before the journal is written). The journal, listing every
move, is fsynced before the first one, and each move is idempotent. A boot that
finds the journal in phase "swapping" rolls every move back; one in phase
"committed" only finishes cleanup.
"""

import enum
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from backup.archive import (
    DB_NAME,
    FREE_SPACE_MARGIN,
    KEY_NAME,
    MANIFEST_NAME,
    STACKS_PREFIX,
    build_manifest,
    utc_now_iso,
)
from backup.crypto import decrypt_stream
from backup.downloads import sweep as sweep_downloads
from backup.errors import (
    BackupConflictError,
    BackupError,
    BackupNotFoundError,
    BackupSpaceError,
    RestoreStateError,
    disk_space_errors,
)
from backup.fsutil import copy_new_file, fsync_dir
from backup.paths import RESTORE_DIRNAME, BackupPaths
from backup.validate import check_database, check_member_name, extract_archive
from utils.stack_files import managed_stack_files

logger = logging.getLogger(__name__)

ROLLBACK_PREFIX = "rollback-"
FAILED_PREFIX = "failed-"
ROLLBACK_INFO = "rollback.json"
INITIATOR_NAME = "initiator.json"
CANDIDATE_NAME = "candidate.db"
STAGED_DIRNAME = "staged"
DB_SIDECARS = ("-wal", "-shm")
_TIMESTAMP_ID = re.compile(r"^\d{8}T\d{12}Z$")

MigrateFn = Callable[[Path], bool]


class ApplyOutcome(enum.Enum):
    NONE = "none"
    APPLIED = "applied"
    FAILED = "failed"


# The tests simulate power loss after each call to these three.


def _move(src: Path, dst: Path) -> None:
    """Atomically rename src to dst; a no-op once src is gone."""
    if not os.path.lexists(src):
        return
    if os.path.lexists(dst):
        raise RestoreStateError(f"Refusing to overwrite {dst}")
    os.rename(src, dst)
    fsync_dir(dst.parent)
    if src.parent != dst.parent:
        fsync_dir(src.parent)


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        return
    fsync_dir(path.parent)


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def _device_of(path: Path) -> int:
    return os.stat(path).st_dev


def _utc_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _work_root(anchor: Path) -> Path:
    return anchor / RESTORE_DIRNAME


def _rollback_dir(root: Path, rollback_id: str) -> Path:
    return root / f"{ROLLBACK_PREFIX}{rollback_id}"


def _roots(paths: BackupPaths) -> List[Path]:
    roots = []
    for anchor in (paths.db_path.parent, paths.key_path.parent, paths.stacks_dir):
        root = _work_root(anchor)
        if root not in roots:
            roots.append(root)
    return roots


def _validate_rollback_id(rollback_id: str) -> None:
    if not isinstance(rollback_id, str) or not _TIMESTAMP_ID.match(rollback_id):
        raise BackupNotFoundError(f"No rollback copy {rollback_id!r}")


def _checkpoint_and_close(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError(f"{db_path.name} failed its integrity check")
    finally:
        conn.close()
    for suffix in DB_SIDECARS:
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _best_effort(action: Callable, *args) -> bool:
    try:
        action(*args)
        return True
    except Exception as e:
        logger.warning(f"Restore cleanup step failed, continuing: {e}")
        return False


def _guard_can_stage(paths: BackupPaths, replace: bool) -> None:
    if paths.journal_path.exists():
        raise BackupConflictError("A restore is being applied; restart DockMon to finish it first")
    if paths.pending_dir.exists() and not replace:
        raise BackupConflictError("A restore is already staged; cancel it first")


def _new_upload_workspace(paths: BackupPaths) -> Path:
    _ensure_private_dir(paths.restore_dir)
    _ensure_private_dir(paths.upload_dir)
    return Path(tempfile.mkdtemp(dir=paths.upload_dir))


def _promote_to_pending(paths: BackupPaths, extracted: Path, replace: bool, initiator: Optional[dict]) -> None:
    _write_json_atomic(extracted / INITIATOR_NAME, initiator or {})
    if paths.pending_dir.exists():
        if not replace:
            raise BackupConflictError("A restore is already staged; cancel it first")
        shutil.rmtree(paths.pending_dir)
    os.rename(extracted, paths.pending_dir)
    fsync_dir(paths.restore_dir)


def _unpack(archive_path: Path, passphrase: str, work: Path) -> tuple:
    if shutil.disk_usage(work).free < archive_path.stat().st_size + FREE_SPACE_MARGIN:
        raise BackupSpaceError("Not enough free disk space to unpack the backup")
    with disk_space_errors("Ran out of disk space while unpacking the backup"):
        tar_path = work / "backup.tar.gz"
        fd = os.open(tar_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with open(archive_path, "rb") as src, os.fdopen(fd, "wb") as dst:
            decrypt_stream(src, dst, passphrase)
        extracted = work / "extracted"
        manifest = extract_archive(tar_path, extracted)
        tar_path.unlink()
        check_database(extracted / DB_NAME, (extracted / KEY_NAME).read_bytes(), manifest["alembic_revision"])
        return extracted, manifest


def verify_archive(paths: BackupPaths, archive_path: Path, passphrase: str) -> dict:
    """Run every staging check without staging anything."""
    work = _new_upload_workspace(paths)
    try:
        return _unpack(archive_path, passphrase, work)[1]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def stage_archive(
    paths: BackupPaths,
    archive_path: Path,
    passphrase: str,
    replace: bool = False,
    initiator: Optional[dict] = None,
) -> dict:
    """Decrypt, validate and stage an archive. Nothing live changes.

    `initiator` (who asked, no secrets) is kept beside the staged files because
    the audit log it would go to is part of the database being replaced.
    """
    _guard_can_stage(paths, replace)
    work = _new_upload_workspace(paths)
    try:
        extracted, manifest = _unpack(archive_path, passphrase, work)
        _promote_to_pending(paths, extracted, replace, initiator)
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def pending_manifest(paths: BackupPaths) -> Optional[dict]:
    return _read_json_or_none(paths.pending_dir / MANIFEST_NAME)


def _read_json_or_none(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_completed_marker(paths: BackupPaths) -> Optional[dict]:
    return _read_json_or_none(paths.completed_marker)


def mark_completed_logged(paths: BackupPaths) -> None:
    marker = read_completed_marker(paths)
    if marker is not None:
        _write_json_atomic(paths.completed_marker, dict(marker, logged=True))


def cancel_staged(paths: BackupPaths) -> bool:
    if paths.journal_path.exists():
        raise BackupConflictError("A restore is being applied; it can no longer be cancelled")
    if not paths.pending_dir.exists():
        return False
    shutil.rmtree(paths.pending_dir)
    return True


def apply_staged(paths: BackupPaths, migrate: MigrateFn) -> ApplyOutcome:
    """Apply a staged restore, or finish/roll back one interrupted by a crash."""
    if paths.journal_path.exists():
        return _recover(paths)
    _clean_work_dirs(paths)
    if not paths.pending_dir.exists():
        return ApplyOutcome.NONE

    try:
        plan = _prepare(paths, migrate)
    except Exception as e:
        logger.error(f"Restore cancelled before any live change: {e}")
        _abandon(paths)
        return ApplyOutcome.FAILED

    try:
        _write_json_atomic(paths.journal_path, plan)
    except Exception as e:
        if paths.journal_path.exists():
            return _rollback(paths, plan)
        logger.error(f"Restore cancelled before any live change; its journal could not be written: {e}")
        _abandon(paths)
        return ApplyOutcome.FAILED

    try:
        _swap(plan)
        plan = dict(plan, phase="committed")
        _write_json_atomic(paths.journal_path, plan)
    except Exception as e:
        logger.error(f"Restore failed while swapping files, rolling back: {e}")
        return _rollback(paths, plan)

    _finish(paths, plan)
    logger.info("Restore applied")
    return ApplyOutcome.APPLIED


def _recover(paths: BackupPaths) -> ApplyOutcome:
    try:
        plan = json.loads(paths.journal_path.read_text())
    except (OSError, ValueError) as e:
        raise RestoreStateError(f"Restore journal is unreadable: {e}") from e
    if plan.get("phase") == "committed":
        logger.warning("Finishing a restore interrupted after it was committed")
        _finish(paths, plan)
        return ApplyOutcome.APPLIED
    if plan.get("phase") == "rolled_back":
        logger.warning("Finishing cleanup of a restore that was rolled back")
        _close_out_rollback(paths)
        return ApplyOutcome.FAILED
    logger.warning("Rolling back a restore interrupted before it was committed")
    return _rollback(paths, plan)


def _item(live: Path, staged: Optional[Path], parked: Optional[Path]) -> Dict[str, Optional[str]]:
    return {
        "live": str(live),
        "staged": str(staged) if staged else None,
        "parked": str(parked) if parked else None,
    }


def _archived_stacks(manifest: dict) -> Dict[str, List[str]]:
    stacks: Dict[str, List[str]] = {}
    for name in manifest["files"]:
        if name.startswith(f"{STACKS_PREFIX}/"):
            _, stack, filename = name.split("/")
            stacks.setdefault(stack, []).append(filename)
    return {stack: sorted(files) for stack, files in sorted(stacks.items())}


def _prepare(paths: BackupPaths, migrate: MigrateFn) -> dict:
    """Migrate a candidate and stage every file next to its target.

    Idempotent and touches nothing live; a crash here just reruns it.
    """
    pending = paths.pending_dir
    manifest = json.loads((pending / MANIFEST_NAME).read_text())

    candidate = pending / CANDIDATE_NAME
    for suffix in ("", *DB_SIDECARS):
        Path(f"{candidate}{suffix}").unlink(missing_ok=True)
    copy_new_file(pending / DB_NAME, candidate)
    if not migrate(candidate):
        raise BackupError("Migrating the backup's database failed")
    _checkpoint_and_close(candidate)

    rollback_id = _utc_id()
    db_root = _work_root(paths.db_path.parent)
    key_root = _work_root(paths.key_path.parent)
    stacks_root = _work_root(paths.stacks_dir)
    for root in _roots(paths):
        _ensure_private_dir(root)
        _ensure_private_dir(root / STAGED_DIRNAME)
        _ensure_private_dir(_rollback_dir(root, rollback_id))

    def staged(root: Path, *parts: str) -> Path:
        return root.joinpath(STAGED_DIRNAME, *parts)

    def parked(root: Path, *parts: str) -> Path:
        return _rollback_dir(root, rollback_id).joinpath(*parts)

    items = []
    for suffix in DB_SIDECARS:
        live_sidecar = Path(f"{paths.db_path}{suffix}")
        if os.path.lexists(live_sidecar):
            items.append(_item(live_sidecar, None, parked(db_root, DB_NAME + suffix)))
    copy_new_file(candidate, staged(db_root, DB_NAME))
    items.append(_item(
        paths.db_path,
        staged(db_root, DB_NAME),
        parked(db_root, DB_NAME) if os.path.lexists(paths.db_path) else None,
    ))
    copy_new_file(pending / KEY_NAME, staged(key_root, KEY_NAME))
    items.append(_item(
        paths.key_path,
        staged(key_root, KEY_NAME),
        parked(key_root, KEY_NAME) if os.path.lexists(paths.key_path) else None,
    ))

    created_dirs = []
    for stack, filenames in _archived_stacks(manifest).items():
        live_dir = paths.stacks_dir / stack
        extras = []
        if os.path.lexists(live_dir):
            if live_dir.is_symlink() or not live_dir.is_dir():
                raise BackupError(f"{live_dir} is not a plain directory; refusing to restore into it")
            extras = [p for p in managed_stack_files(live_dir) if p.name not in filenames]
        else:
            created_dirs.append(str(live_dir))
        for directory in (staged(stacks_root, stack), parked(stacks_root, stack)):
            directory.mkdir(mode=0o700, exist_ok=True)
        for filename in filenames:
            live = live_dir / filename
            if os.path.lexists(live) and (live.is_symlink() or not live.is_file()):
                raise BackupError(f"{live} is not a regular file; refusing to replace it")
            copy_new_file(pending / STACKS_PREFIX / stack / filename, staged(stacks_root, stack, filename))
            items.append(_item(
                live,
                staged(stacks_root, stack, filename),
                parked(stacks_root, stack, filename) if os.path.lexists(live) else None,
            ))
        for extra in extras:
            items.append(_item(extra, None, parked(stacks_root, stack, extra.name)))

    for entry in items:
        live_parent = Path(entry["live"]).parent
        if not live_parent.exists():
            live_parent = paths.stacks_dir
        work_path = Path(entry["staged"] or entry["parked"])
        if _device_of(live_parent) != _device_of(work_path.parent):
            raise BackupError(f"{live_parent} is on a different filesystem than its restore workspace")

    _write_json_atomic(
        parked(db_root, ROLLBACK_INFO),
        {
            "id": rollback_id,
            "created_at": utc_now_iso(),
            "replaced_by_backup_created_at": manifest.get("created_at"),
        },
    )
    _fsync_work_dirs(paths)
    return {
        "phase": "swapping",
        "rollback_id": rollback_id,
        "created_dirs": created_dirs,
        "items": items,
        "backup": {
            "created_at": manifest.get("created_at"),
            "app_version": manifest.get("app_version"),
            "summary": manifest.get("summary"),
        },
    }


def _fsync_work_dirs(paths: BackupPaths) -> None:
    """Make every staged and parked directory entry durable before the journal names it."""
    for root in _roots(paths):
        for directory, _, _ in os.walk(root):
            fsync_dir(Path(directory))
        fsync_dir(root.parent)


def _swap(plan: dict) -> None:
    for directory in plan["created_dirs"]:
        Path(directory).mkdir(exist_ok=True)
        fsync_dir(Path(directory).parent)
    for entry in plan["items"]:
        live = Path(entry["live"])
        if entry["parked"]:
            _move(live, Path(entry["parked"]))
        if entry["staged"]:
            _move(Path(entry["staged"]), live)


def _undo_item(entry: dict) -> None:
    live = Path(entry["live"])
    staged = Path(entry["staged"]) if entry["staged"] else None
    parked = Path(entry["parked"]) if entry["parked"] else None
    # Whether the original was parked decides what `live` holds; a lost staged
    # entry must never make an original look like the swapped-in file.
    original_moved = parked is None or os.path.lexists(parked)
    if staged is not None and original_moved and os.path.lexists(live):
        staged.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _move(live, staged)
    if parked is not None and os.path.lexists(parked) and not os.path.lexists(live):
        _move(parked, live)


def _rollback(paths: BackupPaths, plan: dict) -> ApplyOutcome:
    try:
        plan = dict(plan, phase="swapping")
        _write_json_atomic(paths.journal_path, plan)
        for entry in reversed(plan["items"]):
            _undo_item(entry)
        for directory in reversed(plan["created_dirs"]):
            path = Path(directory)
            if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
                path.rmdir()
                fsync_dir(path.parent)
        _write_json_atomic(paths.journal_path, dict(plan, phase="rolled_back"))
    except Exception as e:
        raise RestoreStateError(
            f"Restore could not be rolled back ({e}); the journal at {paths.journal_path} "
            "was kept and the rollback will be retried on the next start"
        ) from e
    logger.error("Restore rolled back; DockMon is running on its previous data")
    _close_out_rollback(paths)
    return ApplyOutcome.FAILED


def _close_out_rollback(paths: BackupPaths) -> None:
    """Live state is fully old; cleanup failures are retried on the next start."""
    # A step can change the directory and then fail its fsync: only a step that
    # returned cleanly is durable enough to let the journal go.
    if _best_effort(_fail_pending, paths) and not paths.pending_dir.exists():
        _best_effort(_remove, paths.journal_path)
    _best_effort(_clean_work_dirs, paths)


def _finish(paths: BackupPaths, plan: dict) -> None:
    """Post-commit cleanup; live state is fully new. The committed journal is kept
    until pending is gone, so a leftover pending dir is never applied twice."""
    _best_effort(_remove, paths.certs_dir)
    _best_effort(_remove, paths.session_secret_path)
    existing = read_completed_marker(paths)
    already_recorded = existing is not None and existing.get("restore_id") == plan["rollback_id"]
    if paths.pending_dir.exists() and not already_recorded:
        marker = {
            "restore_id": plan["rollback_id"],
            "restored_at": utc_now_iso(),
            "backup": plan.get("backup"),
            "initiator": _read_json_or_none(paths.pending_dir / INITIATOR_NAME) or {},
            "logged": False,
        }
        try:
            _write_json_atomic(paths.completed_marker, marker)
        except Exception as e:
            logger.error(f"Restore applied, but its completion record could not be written ({e}); retrying on the next start")
            return
    pending_removed = _best_effort(_remove, paths.pending_dir)
    for root in _roots(paths):
        _best_effort(_remove, root / STAGED_DIRNAME)
        current = _rollback_dir(root, plan["rollback_id"])
        for old in sorted(root.glob(f"{ROLLBACK_PREFIX}*")):
            if old != current:
                _best_effort(_remove, old)
    if not pending_removed or paths.pending_dir.exists():
        logger.error("Restore applied, but its staging area could not be removed; retrying on the next start")
        return
    _best_effort(_remove, paths.journal_path)


def _fail_pending(paths: BackupPaths) -> None:
    if not paths.pending_dir.exists():
        return
    for old in paths.restore_dir.glob(f"{FAILED_PREFIX}*"):
        _remove(old)
    _move(paths.pending_dir, paths.restore_dir / f"{FAILED_PREFIX}{_utc_id()}")


def _abandon(paths: BackupPaths) -> None:
    _best_effort(_fail_pending, paths)
    _best_effort(_clean_work_dirs, paths)


def _clean_work_dirs(paths: BackupPaths) -> None:
    """Remove upload, backup-temp, download, staging and journal leftovers, and rollback dirs that hold no parked database.

    Only safe while nothing else can be staging, i.e. from apply at startup.
    """
    shutil.rmtree(paths.upload_dir, ignore_errors=True)
    shutil.rmtree(paths.incoming_dir, ignore_errors=True)
    shutil.rmtree(paths.backup_tmp_dir, ignore_errors=True)
    sweep_downloads(paths, locked=True)
    paths.journal_path.with_name(paths.journal_path.name + ".tmp").unlink(missing_ok=True)
    db_root = _work_root(paths.db_path.parent)
    complete = {
        d.name for d in db_root.glob(f"{ROLLBACK_PREFIX}*") if (d / DB_NAME).exists()
    }
    for root in _roots(paths):
        if not root.exists():
            continue
        shutil.rmtree(root / STAGED_DIRNAME, ignore_errors=True)
        for d in root.glob(f"{ROLLBACK_PREFIX}*"):
            if d.name not in complete:
                shutil.rmtree(d, ignore_errors=True)


def list_rollbacks(paths: BackupPaths) -> List[dict]:
    db_root = _work_root(paths.db_path.parent)
    found = []
    for d in db_root.glob(f"{ROLLBACK_PREFIX}*"):
        info = _read_json_or_none(d / ROLLBACK_INFO)
        if info is None or not isinstance(info.get("id"), str) or not (d / DB_NAME).exists():
            continue
        found.append(info)
    return sorted(found, key=lambda r: r["id"], reverse=True)


def delete_rollback(paths: BackupPaths, rollback_id: str) -> None:
    _validate_rollback_id(rollback_id)
    if not _rollback_dir(_work_root(paths.db_path.parent), rollback_id).exists():
        raise BackupNotFoundError(f"No rollback copy {rollback_id}")
    for root in _roots(paths):
        _remove(_rollback_dir(root, rollback_id))


def stage_rollback(
    paths: BackupPaths,
    rollback_id: str,
    replace: bool = False,
    initiator: Optional[dict] = None,
) -> dict:
    """Stage a rollback copy like an uploaded backup.

    It restores the database, key and stack files the earlier restore replaced;
    stacks that restore created are left in place.
    """
    _validate_rollback_id(rollback_id)
    db_dir = _rollback_dir(_work_root(paths.db_path.parent), rollback_id)
    key_file = _rollback_dir(_work_root(paths.key_path.parent), rollback_id) / KEY_NAME
    stacks_dir = _rollback_dir(_work_root(paths.stacks_dir), rollback_id)
    if not (db_dir / DB_NAME).exists() or not key_file.exists():
        raise BackupNotFoundError(f"No complete rollback copy {rollback_id}")
    _guard_can_stage(paths, replace)

    work = _new_upload_workspace(paths)
    try:
        extracted = work / "extracted"
        extracted.mkdir(mode=0o700)
        for suffix in ("", *DB_SIDECARS):
            source = Path(f"{db_dir / DB_NAME}{suffix}")
            if source.exists():
                copy_new_file(source, Path(f"{extracted / DB_NAME}{suffix}"))
        _checkpoint_and_close(extracted / DB_NAME)
        copy_new_file(key_file, extracted / KEY_NAME)

        stacks: Dict[str, bytes] = {}
        for path in sorted(stacks_dir.glob("*/*")) if stacks_dir.exists() else []:
            if path.is_symlink() or not path.is_file():
                continue
            name = f"{STACKS_PREFIX}/{path.parent.name}/{path.name}"
            check_member_name(name)
            target = extracted / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            copy_new_file(path, target)
            stacks[name] = target.read_bytes()

        key = (extracted / KEY_NAME).read_bytes()
        manifest = build_manifest(extracted / DB_NAME, key, stacks, include_stats=True)
        _write_json_atomic(extracted / MANIFEST_NAME, manifest)
        check_database(extracted / DB_NAME, key, manifest["alembic_revision"])
        _promote_to_pending(paths, extracted, replace, initiator)
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)
