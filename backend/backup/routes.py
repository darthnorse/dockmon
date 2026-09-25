"""Backup and restore API.

Every route needs backup.manage and access to every host: a backup holds all
hosts and every stored credential, so a tag-scoped admin must not get one.
"""

import asyncio
import logging
import os
import shutil
import time
import uuid
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
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
from backup.archive import FREE_SPACE_MARGIN, MAX_ARCHIVE_BYTES
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
