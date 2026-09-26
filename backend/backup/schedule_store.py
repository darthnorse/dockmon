"""The scheduled-backup columns of GlobalSettings.

Written directly rather than through DatabaseManager.update_settings, which
drops keys outside its whitelist.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from alerts.evaluation_service import BACKUP_ALERT_SCOPE
from backup.errors import BackupConflictError, BackupDecryptError
from backup.scheduled import MAX_RETENTION, MIN_RETENTION, ScheduledRun
from database import AlertV2, GlobalSettings
from utils.encryption import decrypt_password, encrypt_password


@dataclass
class ScheduleSettings:
    enabled: bool
    schedule: str
    retention: int
    include_stats: bool
    passphrase_set: bool
    last_run_at: Optional[datetime]
    last_status: Optional[str]
    last_error: Optional[str]
    last_file: Optional[str]


def _row(session) -> GlobalSettings:
    settings = session.query(GlobalSettings).first()
    if settings is None:
        settings = GlobalSettings()
        session.add(settings)
        session.flush()
    return settings


def _aware(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is None:
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def read_schedule(db) -> ScheduleSettings:
    with db.get_session() as session:
        row = _row(session)
        return ScheduleSettings(
            enabled=bool(row.backup_schedule_enabled),
            schedule=row.backup_schedule or "03:00",
            retention=row.backup_retention or 7,
            include_stats=bool(row.backup_include_stats),
            passphrase_set=bool(row.backup_passphrase_encrypted),
            last_run_at=_aware(row.backup_last_run_at),
            last_status=row.backup_last_status,
            last_error=row.backup_last_error,
            last_file=row.backup_last_file,
        )


def update_schedule(
    db,
    *,
    enabled: Optional[bool] = None,
    schedule: Optional[str] = None,
    retention: Optional[int] = None,
    include_stats: Optional[bool] = None,
    passphrase: Optional[str] = None,
    clear_passphrase: bool = False,
    forget_last_file: Optional[str] = None,
) -> None:
    """Apply a partial update. The caller has validated schedule, retention and passphrase length."""
    with db.get_session() as session:
        row = _row(session)
        if retention is not None:
            if not MIN_RETENTION <= retention <= MAX_RETENTION:
                raise ValueError(f"Retention must be between {MIN_RETENTION} and {MAX_RETENTION}")
            row.backup_retention = retention
        if schedule is not None:
            row.backup_schedule = schedule.strip()
        if include_stats is not None:
            row.backup_include_stats = include_stats
        if passphrase is not None:
            row.backup_passphrase_encrypted = encrypt_password(passphrase)
        if enabled is not None:
            row.backup_schedule_enabled = enabled
        if clear_passphrase:
            if row.backup_schedule_enabled:
                raise BackupConflictError("Disable scheduled backups before removing the stored passphrase")
            row.backup_passphrase_encrypted = None
        if row.backup_schedule_enabled and not row.backup_passphrase_encrypted:
            raise BackupConflictError("Set a backup passphrase before enabling scheduled backups")
        if forget_last_file is not None and row.backup_last_file == forget_last_file:
            row.backup_last_file = None
        session.commit()


def stored_passphrase(db) -> str:
    with db.get_session() as session:
        encrypted = _row(session).backup_passphrase_encrypted
    if not encrypted:
        raise BackupConflictError("No backup passphrase is set")
    try:
        return decrypt_password(encrypted)
    except (ValueError, IOError):
        raise BackupDecryptError("The stored backup passphrase could not be decrypted; set it again") from None


def record_run(db, result: ScheduledRun, at: datetime) -> None:
    with db.get_session() as session:
        row = _row(session)
        row.backup_last_run_at = _naive_utc(at)
        row.backup_last_status = result.status
        row.backup_last_error = result.error
        if result.file:
            row.backup_last_file = result.file
        session.commit()


def reset_after_restore(db, restored_at: datetime) -> None:
    """The restored columns describe the source install's runs; start this install's history clean.

    last_run_at is set to the restore time so no pre-restore occurrence is caught up,
    and a restored open backup alert (the source's old failure) is closed.
    """
    with db.get_session() as session:
        row = _row(session)
        row.backup_last_run_at = _naive_utc(restored_at)
        row.backup_last_status = None
        row.backup_last_error = None
        row.backup_last_file = None
        for alert in session.query(AlertV2).filter(
            AlertV2.scope_type == "system",
            AlertV2.scope_id == BACKUP_ALERT_SCOPE,
            AlertV2.state != "resolved",
        ):
            alert.state = "resolved"
            alert.resolved_at = _naive_utc(restored_at)
            alert.resolved_reason = "restored"
        session.commit()
