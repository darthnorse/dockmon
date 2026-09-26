"""Record a restore applied at startup in the restored database's audit log.

The audit row is keyed by the restore id, so retries never produce a second row.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from audit.audit_logger import AuditAction, AuditEntityType, log_audit
from backup.paths import BackupPaths
from backup.restore import mark_completed_logged, read_completed_marker
from backup.schedule_store import reset_after_restore
from database import AuditLog
from event_logger import EventSeverity, EventType

logger = logging.getLogger(__name__)


def record_completed_restore(paths: BackupPaths, db) -> Optional[dict]:
    """Ensure the restore's audit row exists; return the marker until it is flagged as logged.

    The audit row is written once per restore id. The marker is only flagged
    after the event has been emitted, so the event is repeated rather than lost
    when a start is interrupted in between.
    """
    marker = read_completed_marker(paths)
    if not marker or marker.get("logged") or not isinstance(marker.get("restore_id"), str):
        return None
    restore_id = marker["restore_id"]
    initiator = marker.get("initiator") if isinstance(marker.get("initiator"), dict) else {}
    backup = marker.get("backup") if isinstance(marker.get("backup"), dict) else {}

    with db.get_session() as session:
        already = (
            session.query(AuditLog.id)
            .filter(
                AuditLog.action == AuditAction.RESTORE.value,
                AuditLog.entity_type == AuditEntityType.BACKUP.value,
                AuditLog.entity_id == restore_id,
            )
            .first()
        )
        if not already:
            # user ids from the replaced database do not map onto this one
            log_audit(
                session,
                user_id=None,
                username=str(initiator.get("username") or "unknown"),
                action=AuditAction.RESTORE,
                entity_type=AuditEntityType.BACKUP,
                entity_id=restore_id,
                entity_name=str(backup.get("created_at") or ""),
                details={
                    "restored_at": marker.get("restored_at"),
                    "backup_created_at": backup.get("created_at"),
                    "backup_app_version": backup.get("app_version"),
                    "api_key_name": initiator.get("api_key_name"),
                },
                ip_address=initiator.get("ip"),
            )
            session.commit()
    restored_at = marker.get("restored_at")
    if isinstance(restored_at, str):
        reset_after_restore(db, datetime.fromisoformat(restored_at.rstrip("Z")).replace(tzinfo=timezone.utc))
    return marker


async def announce_completed_restore(paths: BackupPaths, db, event_logger) -> None:
    try:
        marker = await asyncio.to_thread(record_completed_restore, paths, db)
        if marker is None:
            return
        backup = marker.get("backup") if isinstance(marker.get("backup"), dict) else {}
        event_logger.log_system_event(
            "DockMon was restored from a backup",
            f"Restored from a backup created {backup.get('created_at')} by DockMon {backup.get('app_version')}",
            EventSeverity.INFO,
            EventType.CONFIG_CHANGED,
        )
        await asyncio.to_thread(mark_completed_logged, paths)
    except Exception as e:
        logger.warning(f"Could not record the completed restore; retrying on the next start: {e}")
