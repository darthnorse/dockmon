"""Backup and restore API.

Every route needs backup.manage and access to every host: a backup holds all
hosts and every stored credential, so a tag-scoped admin must not get one.
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone
import shutil
import time
import uuid
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from audit.audit_logger import AuditAction, AuditEntityType, get_client_info, log_audit
from auth.api_key_auth import (
    Capabilities,
    get_current_user_or_api_key,
    get_visible_host_ids_for_auth,
    require_capability,
)
from auth.shared import db
from auth.utils import get_auditable_user_info
from backup.archive import FREE_SPACE_MARGIN, MAX_ARCHIVE_BYTES, utc_iso
from backup.crypto import DEFAULT_KDF, MIN_PASSPHRASE_LENGTH
from backup.downloads import create_download, current_download, open_download
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
from backup.oplock import async_operation_lock, is_busy, operation_lock
from backup.paths import BackupPaths
from backup.schedule import MAX_SCHEDULE_LENGTH, InvalidSchedule, next_occurrence, resolve_timezone, validate_schedule
from backup.schedule_store import read_schedule, update_schedule
from backup.scheduled import (
    MAX_RETENTION,
    MIN_RETENTION,
    delete_file,
    destination_status,
    list_files,
    open_file,
    writer_id,
)
from backup.scheduler import BackupScheduler
from backup.restore import (
    cancel_staged,
    delete_rollback,
    list_rollbacks,
    pending_manifest,
    read_completed_marker,
    stage_archive,
    stage_rollback,
)
from security.rate_limiting import get_rate_limit_dependency
from utils.client_ip import get_request_host

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/backup", tags=["backup"])

BACKUP_KDF = DEFAULT_KDF
MAX_PASSPHRASE_LENGTH = 1024
UPLOAD_ID_PATTERN = r"^[0-9a-f]{32}$"
UPLOAD_TTL_SECONDS = 3600


def get_backup_paths() -> BackupPaths:
    return BackupPaths.from_environment()


def get_backup_scheduler(request: Request) -> BackupScheduler:
    scheduler = getattr(request.app.state, "backup_scheduler", None)
    if scheduler is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Scheduled backups are not running")
    return scheduler


# Share I/O (a possibly hung NFS/SMB mount) never runs on the default pool that Docker calls use.
_share_io = ThreadPoolExecutor(max_workers=2, thread_name_prefix="backup-io")
DESTINATION_CACHE_SECONDS = 30
DESTINATION_PROBE_TIMEOUT = 5
FILE_CHUNK = 1024 * 1024
_destination_cache: dict = {}
_destination_probes: dict = {}


def clear_destination_cache() -> None:
    _destination_cache.clear()


async def _on_share(func, *args):
    return await asyncio.get_running_loop().run_in_executor(_share_io, func, *args)


async def _destination(dest, data_dir) -> dict:
    """Destination status, cached and single-flight: a hung mount costs one thread and
    a bounded wait, never a request that hangs."""
    key = str(dest)
    now = asyncio.get_running_loop().time()
    cached = _destination_cache.get(key)
    if cached and now - cached[0] < DESTINATION_CACHE_SECONDS:
        return cached[1]
    probe = _destination_probes.get(key)
    if probe is None or probe.done():
        probe = asyncio.ensure_future(_on_share(destination_status, dest, data_dir))
        _destination_probes[key] = probe
    try:
        status_ = dict(await asyncio.wait_for(asyncio.shield(probe), DESTINATION_PROBE_TIMEOUT), responding=True)
    except asyncio.TimeoutError:
        return {"path": key, "responding": False, "exists": False, "is_mountpoint": False, "writable": False,
                "same_filesystem_as_data": False, "free_bytes": None}
    _destination_cache[key] = (now, status_)
    return status_


async def require_unrestricted_hosts(current_user: dict = Depends(get_current_user_or_api_key)) -> dict:
    if get_visible_host_ids_for_auth(current_user) is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Backup and restore require access to all hosts")
    return current_user


async def require_same_origin(request: Request, current_user: dict = Depends(get_current_user_or_api_key)) -> None:
    """Refuse cookie-authenticated writes from another site; API keys carry no ambient credentials."""
    if current_user.get("auth_type") == "api_key":
        return
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source or urlparse(source).netloc.lower() != get_request_host(request).lower():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-site request refused")


READ_GUARDS = [Depends(require_capability(Capabilities.BACKUP_MANAGE)), Depends(require_unrestricted_hosts)]
WRITE_GUARDS = READ_GUARDS + [Depends(require_same_origin), Depends(get_rate_limit_dependency("backup"))]


class CreateBackupRequest(BaseModel):
    passphrase: str = Field(min_length=MIN_PASSPHRASE_LENGTH, max_length=MAX_PASSPHRASE_LENGTH)
    include_stats: bool = True


class StageUploadRequest(BaseModel):
    upload_id: str = Field(pattern=UPLOAD_ID_PATTERN)
    passphrase: str = Field(min_length=1, max_length=MAX_PASSPHRASE_LENGTH)
    replace: bool = False


class StageRollbackRequest(BaseModel):
    replace: bool = False


class ScheduleUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    schedule: Optional[str] = Field(None, max_length=MAX_SCHEDULE_LENGTH)
    retention: Optional[int] = Field(None, ge=MIN_RETENTION, le=MAX_RETENTION)
    include_stats: Optional[bool] = None
    passphrase: Optional[str] = Field(None, min_length=MIN_PASSPHRASE_LENGTH, max_length=MAX_PASSPHRASE_LENGTH)
    clear_passphrase: bool = False


class StageFileRequest(BaseModel):
    passphrase: str = Field(min_length=1, max_length=MAX_PASSPHRASE_LENGTH)
    replace: bool = False


def _to_http(error: BackupError) -> HTTPException:
    if isinstance(error, (BackupBusyError, BackupConflictError)):
        return HTTPException(status.HTTP_409_CONFLICT, str(error))
    if isinstance(error, BackupNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(error))
    if isinstance(error, BackupSpaceError):
        return HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(error))
    if isinstance(error, (BackupDecryptError, BackupValidationError)):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(error))
    logger.error(f"Backup operation failed: {error}")
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Backup operation failed; see the DockMon log")


def _audit(request: Request, current_user: dict, action: AuditAction, entity_id: Optional[str] = None,
           entity_name: Optional[str] = None, details: Optional[dict] = None) -> None:
    user_id, display_name = get_auditable_user_info(current_user)
    try:
        with db.get_session() as session:
            log_audit(
                session, user_id=user_id, username=display_name, action=action,
                entity_type=AuditEntityType.BACKUP, entity_id=entity_id, entity_name=entity_name,
                details=details, **get_client_info(request),
            )
            session.commit()
    except Exception as e:
        logger.warning(f"Could not write backup audit entry: {e}")


def _initiator(request: Request, current_user: dict) -> dict:
    user_id, display_name = get_auditable_user_info(current_user)
    return {
        "username": display_name,
        "user_id": user_id,
        "api_key_name": current_user.get("api_key_name"),
        "ip": get_client_info(request)["ip_address"],
    }


def _manifest_summary(manifest: dict) -> dict:
    return {
        "created_at": manifest.get("created_at"),
        "app_version": manifest.get("app_version"),
        "alembic_revision": manifest.get("alembic_revision"),
        "stats_history_included": manifest.get("stats_history_included"),
        "summary": manifest.get("summary"),
    }


def _download_summary(meta: Optional[dict]) -> Optional[dict]:
    if meta is None:
        return None
    return {key: meta.get(key) for key in ("download_id", "filename", "size", "created_at", "expires_at")}


def _last_restore(marker: Optional[dict]) -> Optional[dict]:
    if marker is None:
        return None
    initiator = marker.get("initiator") if isinstance(marker.get("initiator"), dict) else {}
    return {
        "restored_at": marker.get("restored_at"),
        "backup": marker.get("backup"),
        "initiated_by": initiator.get("username"),
    }


async def _locked(paths: BackupPaths, work, *args):
    """Run work in a thread that holds the operation lock for its whole duration."""
    def run():
        with operation_lock(paths):
            return work(*args)
    try:
        return await asyncio.to_thread(run)
    except BackupError as e:
        raise _to_http(e) from e


@router.get("/status", dependencies=READ_GUARDS)
async def backup_status(paths: BackupPaths = Depends(get_backup_paths)):
    def collect() -> dict:
        pending = pending_manifest(paths)
        return {
            "busy": is_busy(paths),
            "pending": _manifest_summary(pending) if pending else None,
            "rollbacks": [
                {
                    "id": r["id"],
                    "created_at": r.get("created_at"),
                    "replaced_by_backup_created_at": r.get("replaced_by_backup_created_at"),
                }
                for r in list_rollbacks(paths)
            ],
            "last_restore": _last_restore(read_completed_marker(paths)),
            "download": _download_summary(current_download(paths)),
        }
    return await asyncio.to_thread(collect)


@router.post("", dependencies=WRITE_GUARDS)
async def create_backup_download(
    body: CreateBackupRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
    paths: BackupPaths = Depends(get_backup_paths),
):
    meta = await _locked(paths, create_download, paths, body.passphrase, body.include_stats, BACKUP_KDF)
    _audit(request, current_user, AuditAction.CREATE, entity_id=meta["download_id"], entity_name=meta["filename"],
           details={"include_stats": body.include_stats, "size": meta["size"],
                    "alembic_revision": meta["alembic_revision"]})
    return _download_summary(meta)


@router.get("/downloads/{download_id}", dependencies=READ_GUARDS)
async def download_backup(download_id: str, paths: BackupPaths = Depends(get_backup_paths)):
    try:
        file_path, meta = await asyncio.to_thread(open_download, paths, download_id)
    except BackupError as e:
        raise _to_http(e) from e
    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=meta["filename"],
        headers={"Cache-Control": "no-store"},
    )


async def _receive_upload(request: Request, paths: BackupPaths, declared: Optional[int]) -> dict:
    incoming = paths.incoming_dir
    incoming.mkdir(mode=0o700, parents=True, exist_ok=True)
    cutoff = time.time() - UPLOAD_TTL_SECONDS
    for stale in incoming.iterdir():
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
    if declared is not None and shutil.disk_usage(incoming).free < declared + FREE_SPACE_MARGIN:
        raise BackupSpaceError("Not enough free disk space for this upload")

    upload_id = uuid.uuid4().hex
    target = incoming / f"{upload_id}.dmbak"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    size = 0
    try:
        with disk_space_errors("Ran out of disk space while receiving the upload"), os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Backup file is too large")
                await asyncio.to_thread(f.write, chunk)
            await asyncio.to_thread(f.flush)
            await asyncio.to_thread(os.fsync, f.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"upload_id": upload_id, "size": size}


@router.post("/uploads", dependencies=WRITE_GUARDS)
async def upload_backup(request: Request, paths: BackupPaths = Depends(get_backup_paths)):
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/octet-stream":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload the backup file as application/octet-stream")
    declared_header = request.headers.get("content-length")
    declared = None
    if declared_header is not None:
        if not declared_header.isdigit():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Content-Length")
        declared = int(declared_header)
        if declared > MAX_ARCHIVE_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Backup file is too large")
    try:
        async with async_operation_lock(paths):
            return await _receive_upload(request, paths, declared)
    except BackupError as e:
        raise _to_http(e) from e


def _stage_upload(paths: BackupPaths, body: StageUploadRequest, initiator: dict) -> dict:
    archive = paths.incoming_dir / f"{body.upload_id}.dmbak"
    if not archive.is_file():
        raise BackupNotFoundError("No such upload; upload the backup file again")
    if archive.stat().st_mtime < time.time() - UPLOAD_TTL_SECONDS:
        archive.unlink(missing_ok=True)
        raise BackupNotFoundError("The upload has expired; upload the backup file again")
    try:
        return stage_archive(paths, archive, body.passphrase, replace=body.replace, initiator=initiator)
    finally:
        archive.unlink(missing_ok=True)


@router.post("/restore", dependencies=WRITE_GUARDS)
async def stage_uploaded_backup(
    body: StageUploadRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
    paths: BackupPaths = Depends(get_backup_paths),
):
    manifest = await _locked(paths, _stage_upload, paths, body, _initiator(request, current_user))
    _audit(request, current_user, AuditAction.RESTORE, entity_name=manifest.get("created_at"),
           details={"stage": "staged", "backup_created_at": manifest.get("created_at"),
                    "backup_app_version": manifest.get("app_version")})
    return _manifest_summary(manifest)


@router.delete("/restore/pending", dependencies=WRITE_GUARDS)
async def cancel_staged_restore(
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
    paths: BackupPaths = Depends(get_backup_paths),
):
    cancelled = await _locked(paths, cancel_staged, paths)
    if cancelled:
        _audit(request, current_user, AuditAction.DELETE, details={"stage": "cancelled"})
    return {"cancelled": cancelled}


@router.post("/rollbacks/{rollback_id}/stage", dependencies=WRITE_GUARDS)
async def stage_rollback_copy(
    rollback_id: str,
    request: Request,
    body: Optional[StageRollbackRequest] = None,
    current_user: dict = Depends(get_current_user_or_api_key),
    paths: BackupPaths = Depends(get_backup_paths),
):
    replace = body.replace if body else False
    manifest = await _locked(paths, stage_rollback, paths, rollback_id, replace, _initiator(request, current_user))
    _audit(request, current_user, AuditAction.RESTORE, entity_id=rollback_id,
           details={"stage": "staged", "source": "rollback"})
    return _manifest_summary(manifest)


@router.delete("/rollbacks/{rollback_id}", dependencies=WRITE_GUARDS, status_code=status.HTTP_204_NO_CONTENT)
async def delete_rollback_copy(
    rollback_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
    paths: BackupPaths = Depends(get_backup_paths),
):
    await _locked(paths, delete_rollback, paths, rollback_id)
    _audit(request, current_user, AuditAction.DELETE, entity_id=rollback_id, details={"rollback_copy": True})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _schedule_payload(paths: BackupPaths, scheduler: BackupScheduler) -> dict:
    schedule = await asyncio.to_thread(read_schedule, db)
    tz, tz_error = resolve_timezone()
    next_run = None
    if schedule.enabled:
        try:
            next_run = utc_iso(next_occurrence(schedule.schedule, datetime.now(timezone.utc), tz))
        except InvalidSchedule:
            pass
    return {
        "enabled": schedule.enabled,
        "schedule": schedule.schedule,
        "retention": schedule.retention,
        "include_stats": schedule.include_stats,
        "passphrase_set": schedule.passphrase_set,
        "last_run_at": utc_iso(schedule.last_run_at) if schedule.last_run_at else None,
        "last_status": schedule.last_status,
        "last_error": schedule.last_error,
        "last_file": schedule.last_file,
        "next_run_at": next_run,
        "timezone": str(tz),
        "timezone_error": tz_error,
        "destination": await _destination(scheduler.dest, paths.data_dir),
    }


@router.get("/settings", dependencies=READ_GUARDS)
async def get_schedule(
    paths: BackupPaths = Depends(get_backup_paths),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
):
    return await _schedule_payload(paths, scheduler)


@router.put("/settings", dependencies=WRITE_GUARDS)
async def put_schedule(
    body: ScheduleUpdateRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
    paths: BackupPaths = Depends(get_backup_paths),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
):
    if body.schedule is not None:
        try:
            validate_schedule(body.schedule, resolve_timezone()[0])
        except InvalidSchedule as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    try:
        await asyncio.to_thread(
            update_schedule, db, enabled=body.enabled, schedule=body.schedule, retention=body.retention,
            include_stats=body.include_stats, passphrase=body.passphrase, clear_passphrase=body.clear_passphrase,
        )
    except BackupConflictError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    if body.enabled is not None or body.schedule is not None:
        scheduler.schedule_changed()
    changed = body.model_dump(exclude_unset=True, exclude={"passphrase"})
    changed["passphrase_changed"] = body.passphrase is not None
    _audit(request, current_user, AuditAction.SETTINGS_CHANGE, entity_name="scheduled backups", details=changed)
    return await _schedule_payload(paths, scheduler)


@router.post("/run", dependencies=WRITE_GUARDS)
async def run_scheduled_now(
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
):
    try:
        result = await scheduler.run()
    except BackupError as e:
        raise _to_http(e) from e
    clear_destination_cache()
    _audit(request, current_user, AuditAction.CREATE, entity_name=result.file,
           details={"scheduled": True, "status": result.status})
    return {"status": result.status, "file": result.file, "error": result.error}


@router.get("/files", dependencies=READ_GUARDS)
async def list_scheduled_files(
    paths: BackupPaths = Depends(get_backup_paths),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
):
    return await _on_share(list_files, scheduler.dest, writer_id(paths))


class _FileDescriptorResponse(StreamingResponse):
    """Streams an already-open descriptor and closes it however the response ends."""

    def __init__(self, fd: int, size: int, filename: str):
        self._fd = fd
        super().__init__(
            self._chunks(),
            media_type="application/octet-stream",
            headers={
                "Content-Length": str(size),
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    async def _chunks(self):
        while True:
            chunk = await _on_share(os.read, self._fd, FILE_CHUNK)
            if not chunk:
                return
            yield chunk

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            os.close(self._fd)


@router.get("/files/{name}", dependencies=READ_GUARDS)
async def download_scheduled_file(
    name: str,
    paths: BackupPaths = Depends(get_backup_paths),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
):
    try:
        fd, size = await _on_share(open_file, scheduler.dest, writer_id(paths), name)
    except BackupError as e:
        raise _to_http(e) from e
    return _FileDescriptorResponse(fd, size, name)


@router.delete("/files/{name}", dependencies=WRITE_GUARDS, status_code=status.HTTP_204_NO_CONTENT)
async def delete_scheduled_file(
    name: str,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
    paths: BackupPaths = Depends(get_backup_paths),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
):
    try:
        await _on_share(delete_file, scheduler.dest, writer_id(paths), name)
    except BackupError as e:
        raise _to_http(e) from e
    await asyncio.to_thread(update_schedule, db, forget_last_file=name)
    clear_destination_cache()
    _audit(request, current_user, AuditAction.DELETE, entity_name=name, details={"scheduled_file": True})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _stage_scheduled_file(paths: BackupPaths, dest, name: str, body: StageFileRequest, initiator: dict) -> dict:
    with operation_lock(paths):
        fd, _size = open_file(dest, writer_id(paths), name)
        try:
            # Staging reopens by path: go through the verified descriptor so a
            # swap on the share after the check cannot substitute another file.
            return stage_archive(paths, Path(f"/proc/self/fd/{fd}"), body.passphrase, replace=body.replace,
                                 initiator=initiator)
        finally:
            os.close(fd)


@router.post("/files/{name}/stage", dependencies=WRITE_GUARDS)
async def stage_scheduled_file(
    name: str,
    body: StageFileRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
    paths: BackupPaths = Depends(get_backup_paths),
    scheduler: BackupScheduler = Depends(get_backup_scheduler),
):
    try:
        manifest = await _on_share(
            _stage_scheduled_file, paths, scheduler.dest, name, body, _initiator(request, current_user)
        )
    except BackupError as e:
        raise _to_http(e) from e
    _audit(request, current_user, AuditAction.RESTORE, entity_name=name,
           details={"stage": "staged", "source": "scheduled", "backup_created_at": manifest.get("created_at")})
    return _manifest_summary(manifest)
