"""
Audit Log API Routes (v2.3.0 Phase 6)

Provides admin-only endpoints for viewing, filtering, exporting, and managing
the audit log. Includes retention settings for automatic cleanup.
"""
import csv
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, and_, or_, func

from auth.api_key_auth import require_scope, get_current_user_or_api_key
from auth.shared import db
from database import AuditLog, GlobalSettings
from audit.audit_logger import AuditAction, AuditEntityType, log_audit, get_client_info

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/audit-log", tags=["audit"])


# =============================================================================
# Constants
# =============================================================================

VALID_RETENTION_DAYS = [30, 60, 90, 180, 365, 0]  # 0 = unlimited
DEFAULT_RETENTION_DAYS = 90
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
MAX_EXPORT_ENTRIES = 100000


# =============================================================================
# Request/Response Models
# =============================================================================

class AuditLogEntry(BaseModel):
    """Single audit log entry"""
    id: int
    user_id: Optional[int]
    username: str
    action: str
    entity_type: str
    entity_id: Optional[str]
    entity_name: Optional[str]
    host_id: Optional[str]
    details: Optional[dict]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: str


class AuditLogListResponse(BaseModel):
    """Paginated list of audit entries"""
    entries: List[AuditLogEntry]
    total: int
    page: int
    page_size: int
    total_pages: int


class RetentionSettingsResponse(BaseModel):
    """Audit log retention settings"""
    retention_days: int
    valid_options: List[int]
    oldest_entry_date: Optional[str]
    total_entries: int


class UpdateRetentionRequest(BaseModel):
    """Update retention settings"""
    retention_days: int = Field(..., description="Retention period in days (0 = unlimited)")


class RetentionUpdateResponse(BaseModel):
    """Response after updating retention"""
    retention_days: int
    message: str
    entries_to_delete: int


class AuditLogStatsResponse(BaseModel):
    """Statistics about the audit log"""
    total_entries: int
    entries_by_action: dict
    entries_by_entity_type: dict
    entries_by_user: dict
    oldest_entry_date: Optional[str]
    newest_entry_date: Optional[str]


# =============================================================================
# Filter Parameters (shared between list and export)
# =============================================================================

@dataclass
class AuditFilterParams:
    """Common filter parameters for audit log queries"""
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    search: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


# =============================================================================
# Helper Functions
# =============================================================================

def _escape_like_pattern(value: str) -> str:
    """Escape special characters for SQL LIKE patterns."""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Format datetime as UTC with 'Z' suffix per DockMon standards."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + 'Z'


def _parse_iso_date(date_str: str, field_name: str) -> datetime:
    """Parse ISO date string, raising HTTPException on failure."""
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format")


def _parse_details(details_str: Optional[str]) -> Optional[dict]:
    """Parse JSON details field."""
    if details_str is None:
        return None
    try:
        return json.loads(details_str)
    except (json.JSONDecodeError, TypeError):
        return None


def _entry_to_response(entry: AuditLog) -> AuditLogEntry:
    """Convert database entry to API response."""
    return AuditLogEntry(
        id=entry.id,
        user_id=entry.user_id,
        username=entry.username,
        action=entry.action,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        entity_name=entry.entity_name,
        host_id=entry.host_id,
        details=_parse_details(entry.details),
        ip_address=entry.ip_address,
        user_agent=entry.user_agent,
        created_at=_format_datetime(entry.created_at),
    )


def _build_audit_filters(params: AuditFilterParams) -> list:
    """Build SQLAlchemy filter conditions from filter parameters."""
    filters = []

    if params.user_id is not None:
        filters.append(AuditLog.user_id == params.user_id)

    if params.username:
        escaped = _escape_like_pattern(params.username)
        filters.append(AuditLog.username.ilike(f"%{escaped}%", escape='\\'))

    if params.action:
        filters.append(AuditLog.action == params.action)

    if params.entity_type:
        filters.append(AuditLog.entity_type == params.entity_type)

    if params.entity_id:
        filters.append(AuditLog.entity_id == params.entity_id)

    if params.search:
        escaped = _escape_like_pattern(params.search)
        pattern = f"%{escaped}%"
        filters.append(or_(
            AuditLog.username.ilike(pattern, escape='\\'),
            AuditLog.entity_name.ilike(pattern, escape='\\'),
            AuditLog.entity_id.ilike(pattern, escape='\\'),
        ))

    if params.start_date:
        filters.append(AuditLog.created_at >= _parse_iso_date(params.start_date, 'start_date'))

    if params.end_date:
        filters.append(AuditLog.created_at <= _parse_iso_date(params.end_date, 'end_date'))

    return filters


def _get_retention_days(settings: Optional[GlobalSettings]) -> int:
    """Get retention days from settings with default fallback."""
    if settings is None:
        return DEFAULT_RETENTION_DAYS
    return getattr(settings, 'audit_log_retention_days', DEFAULT_RETENTION_DAYS)


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("", response_model=AuditLogListResponse, dependencies=[Depends(require_scope("admin"))])
async def list_audit_log(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    username: Optional[str] = Query(None, description="Filter by username (partial match)"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    search: Optional[str] = Query(None, description="Search in username, entity_name, entity_id"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
):
    """List audit log entries with filtering and pagination. Admin only."""
    params = AuditFilterParams(
        user_id=user_id, username=username, action=action, entity_type=entity_type,
        entity_id=entity_id, search=search, start_date=start_date, end_date=end_date,
    )

    with db.get_session() as session:
        query = session.query(AuditLog)
        filters = _build_audit_filters(params)
        if filters:
            query = query.filter(and_(*filters))

        total = query.count()
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        offset = (page - 1) * page_size

        entries = (
            query.order_by(desc(AuditLog.created_at))
            .offset(offset)
            .limit(page_size)
            .all()
        )

        return AuditLogListResponse(
            entries=[_entry_to_response(e) for e in entries],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


@router.get("/actions", response_model=List[str], dependencies=[Depends(require_scope("admin"))])
async def list_audit_actions():
    """List all available audit action types. Admin only."""
    return [action.value for action in AuditAction]


@router.get("/entity-types", response_model=List[str], dependencies=[Depends(require_scope("admin"))])
async def list_audit_entity_types():
    """List all available audit entity types. Admin only."""
    return [entity.value for entity in AuditEntityType]


@router.get("/users", response_model=List[dict], dependencies=[Depends(require_scope("admin"))])
async def list_audit_users():
    """List all users who have entries in the audit log. Admin only."""
    with db.get_session() as session:
        result = (
            session.query(AuditLog.user_id, AuditLog.username)
            .filter(AuditLog.user_id.isnot(None))
            .distinct()
            .order_by(AuditLog.username)
            .all()
        )
        return [{"user_id": r.user_id, "username": r.username} for r in result]


@router.get("/stats", response_model=AuditLogStatsResponse, dependencies=[Depends(require_scope("admin"))])
async def get_audit_stats():
    """Get audit log statistics. Admin only."""
    with db.get_session() as session:
        total = session.query(AuditLog).count()

        oldest = session.query(AuditLog).order_by(AuditLog.created_at).first()
        newest = session.query(AuditLog).order_by(desc(AuditLog.created_at)).first()

        # Efficient GROUP BY queries instead of N+1
        action_results = (
            session.query(AuditLog.action, func.count(AuditLog.id))
            .group_by(AuditLog.action)
            .all()
        )
        action_counts = {action: count for action, count in action_results}

        entity_results = (
            session.query(AuditLog.entity_type, func.count(AuditLog.id))
            .group_by(AuditLog.entity_type)
            .all()
        )
        entity_counts = {entity_type: count for entity_type, count in entity_results}

        user_results = (
            session.query(AuditLog.username, func.count(AuditLog.id))
            .group_by(AuditLog.username)
            .order_by(desc(func.count(AuditLog.id)))
            .limit(10)
            .all()
        )
        user_counts = {username: count for username, count in user_results}

        return AuditLogStatsResponse(
            total_entries=total,
            entries_by_action=action_counts,
            entries_by_entity_type=entity_counts,
            entries_by_user=user_counts,
            oldest_entry_date=_format_datetime(oldest.created_at) if oldest else None,
            newest_entry_date=_format_datetime(newest.created_at) if newest else None,
        )


@router.get("/export", dependencies=[Depends(require_scope("admin"))])
async def export_audit_log(
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    username: Optional[str] = Query(None, description="Filter by username (partial match)"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
):
    """Export audit log to CSV. Admin only. Limited to 100,000 entries."""
    params = AuditFilterParams(
        user_id=user_id, username=username, action=action,
        entity_type=entity_type, start_date=start_date, end_date=end_date,
    )

    with db.get_session() as session:
        query = session.query(AuditLog)
        filters = _build_audit_filters(params)
        if filters:
            query = query.filter(and_(*filters))

        total_matching = query.count()
        is_truncated = total_matching > MAX_EXPORT_ENTRIES

        entries = (
            query.order_by(desc(AuditLog.created_at))
            .limit(MAX_EXPORT_ENTRIES)
            .all()
        )

        # Build CSV
        output = io.StringIO()
        writer = csv.writer(output)

        if is_truncated:
            writer.writerow([
                f'# WARNING: Export truncated. Showing {MAX_EXPORT_ENTRIES:,} of '
                f'{total_matching:,} matching entries. Apply date filters to export specific ranges.'
            ])
            writer.writerow([])

        writer.writerow([
            'ID', 'Timestamp', 'Username', 'User ID', 'Action', 'Entity Type',
            'Entity ID', 'Entity Name', 'Host ID', 'IP Address', 'User Agent', 'Details',
        ])

        for entry in entries:
            writer.writerow([
                entry.id,
                _format_datetime(entry.created_at),
                entry.username,
                entry.user_id or '',
                entry.action,
                entry.entity_type,
                entry.entity_id or '',
                entry.entity_name or '',
                entry.host_id or '',
                entry.ip_address or '',
                entry.user_agent or '',
                entry.details or '',
            ])

        output.seek(0)
        filename = f"audit_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

        headers = {"Content-Disposition": f"attachment; filename={filename}"}
        if is_truncated:
            headers["X-Export-Truncated"] = "true"
            headers["X-Export-Total-Matching"] = str(total_matching)
            headers["X-Export-Included"] = str(MAX_EXPORT_ENTRIES)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers=headers,
        )


@router.get("/retention", response_model=RetentionSettingsResponse, dependencies=[Depends(require_scope("admin"))])
async def get_retention_settings():
    """Get audit log retention settings. Admin only."""
    with db.get_session() as session:
        settings = session.query(GlobalSettings).first()
        retention_days = _get_retention_days(settings)
        total = session.query(AuditLog).count()
        oldest = session.query(AuditLog).order_by(AuditLog.created_at).first()

        return RetentionSettingsResponse(
            retention_days=retention_days,
            valid_options=VALID_RETENTION_DAYS,
            oldest_entry_date=_format_datetime(oldest.created_at) if oldest else None,
            total_entries=total,
        )


@router.put("/retention", response_model=RetentionUpdateResponse, dependencies=[Depends(require_scope("admin"))])
async def update_retention_settings(
    request: UpdateRetentionRequest,
    req: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
):
    """Update audit log retention settings. Admin only."""
    if request.retention_days not in VALID_RETENTION_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid retention_days. Must be one of: {VALID_RETENTION_DAYS}"
        )

    with db.get_session() as session:
        settings = session.query(GlobalSettings).first()
        if not settings:
            raise HTTPException(status_code=500, detail="Settings not found")

        old_retention = _get_retention_days(settings)
        settings.audit_log_retention_days = request.retention_days

        entries_to_delete = 0
        if request.retention_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=request.retention_days)
            entries_to_delete = session.query(AuditLog).filter(AuditLog.created_at < cutoff).count()

        client_info = get_client_info(req)
        log_audit(
            db=session,
            user_id=current_user.get('user_id'),
            username=current_user.get('username', 'unknown'),
            action=AuditAction.SETTINGS_CHANGE,
            entity_type=AuditEntityType.SETTINGS,
            entity_name='audit_log_retention_days',
            details={
                'old_value': old_retention,
                'new_value': request.retention_days,
                'entries_affected': entries_to_delete,
            },
            **client_info,
        )

        session.commit()

        message = (
            "Retention set to unlimited - entries will not be automatically deleted"
            if request.retention_days == 0
            else f"Retention set to {request.retention_days} days"
        )
        if entries_to_delete > 0:
            message += f". {entries_to_delete} entries older than {request.retention_days} days will be cleaned up."

        logger.info(f"Audit log retention updated to {request.retention_days} days by {current_user['username']}")

        return RetentionUpdateResponse(
            retention_days=request.retention_days,
            message=message,
            entries_to_delete=entries_to_delete,
        )


@router.post("/cleanup", response_model=dict, dependencies=[Depends(require_scope("admin"))])
async def cleanup_old_entries(
    req: Request,
    current_user: dict = Depends(get_current_user_or_api_key),
):
    """Manually trigger cleanup of old audit log entries. Admin only."""
    with db.get_session() as session:
        settings = session.query(GlobalSettings).first()
        retention_days = _get_retention_days(settings)

        if retention_days == 0:
            return {"message": "Retention is set to unlimited. No entries deleted.", "deleted_count": 0}

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        entries_to_delete = session.query(AuditLog).filter(AuditLog.created_at < cutoff).count()

        client_info = get_client_info(req)
        log_audit(
            db=session,
            user_id=current_user.get('user_id'),
            username=current_user.get('username', 'unknown'),
            action=AuditAction.DELETE,
            entity_type=AuditEntityType.SETTINGS,
            entity_name='audit_log_cleanup',
            details={
                'retention_days': retention_days,
                'cutoff_date': _format_datetime(cutoff),
                'entries_deleted': entries_to_delete,
            },
            **client_info,
        )

        deleted_count = session.query(AuditLog).filter(AuditLog.created_at < cutoff).delete()
        session.commit()

        logger.info(f"Manual audit log cleanup: {deleted_count} entries deleted by {current_user['username']}")

        return {
            "message": f"Cleanup complete. Deleted {deleted_count} entries older than {retention_days} days.",
            "deleted_count": deleted_count,
        }
