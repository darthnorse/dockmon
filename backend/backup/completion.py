"""Record a restore applied at startup in the restored database's audit log.

The audit row is keyed by the restore id, so a crash between writing it and
flagging the marker never produces a second row.
"""

import asyncio
import logging
from typing import Optional

from audit.audit_logger import AuditAction, AuditEntityType, log_audit
from backup.paths import BackupPaths
from backup.restore import mark_completed_logged, read_completed_marker
from database import AuditLog
from event_logger import EventSeverity, EventType

logger = logging.getLogger(__name__)


def record_completed_restore(paths: BackupPaths, db) -> Optional[dict]:
    """Return the marker until it is flagged as logged, else None.

    The audit row is written once per restore id; the event may repeat after a
    crash between the two, which beats losing it.
    """
    marker = read_completed_marker(paths)
    if not marker or marker.get("logged") or not isinstance(marker.get("restore_id"), str):
        return None
    restore_id = marker["restore_id"]
    initiator = marker.get("initiator") if isinstance(marker.get("initiator"), dict) else {}
    backup = marker.get("backup") if isinstance(marker.get("backup"), dict) else {}

    inserted = False
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
            inserted = True
    if not inserted:
        logger.info(f"Restore {restore_id} was already in the audit log; announcing it again")
    mark_completed_logged(paths)
    return marker


async def announce_completed_restore(paths: BackupPaths, db, event_logger) -> None:
    try:
        marker = await asyncio.to_thread(record_completed_restore, paths, db)
    except Exception as e:
        logger.warning(f"Could not record the completed restore: {e}")
        return
    if marker is None:
        return
    backup = marker.get("backup") if isinstance(marker.get("backup"), dict) else {}
    event_logger.log_system_event(
        "DockMon was restored from a backup",
        f"Restored from a backup created {backup.get('created_at')} by DockMon {backup.get('app_version')}",
        EventSeverity.INFO,
        EventType.CONFIG_CHANGED,
    )
