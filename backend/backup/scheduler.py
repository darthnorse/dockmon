"""Runs scheduled backups: sleeps until the next occurrence, catches up one run a restart missed.

Backups run on a dedicated single-thread executor, so a hung network share never
holds a thread of the default pool that Docker calls share. Events and alerts
are emitted here, on the event loop.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from backup.crypto import DEFAULT_KDF, KdfParams
from backup.errors import BackupBusyError, BackupError
from backup.oplock import operation_lock
from backup.paths import BackupPaths
from backup.schedule import InvalidSchedule, next_occurrence, previous_occurrence, resolve_timezone
from backup.schedule_store import ScheduleSettings, read_schedule, record_run, stored_passphrase
from backup.scheduled import (
    ScheduledRun,
    backup_dir,
    public_error,
    read_armed_at,
    run_scheduled_backup,
    sweep_partials,
    write_armed_at,
    writer_id,
)
from event_logger import EventSeverity, EventType

logger = logging.getLogger(__name__)

CATCH_UP_WINDOW = timedelta(hours=6)
MAX_SLEEP_SECONDS = 15 * 60
LOCK_RETRY_SECONDS = 30
LOCK_RETRY_ATTEMPTS = 20
STOP_GRACE_SECONDS = 30
SKIPPED_BUSY = "Skipped because another operation was running (a manual backup or restore)"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BackupScheduler:
    def __init__(self, paths: BackupPaths, db, alert_service, event_logger,
                 dest: Optional[Path] = None, kdf: KdfParams = DEFAULT_KDF):
        self.paths = paths
        self.db = db
        self.alert_service = alert_service
        self.event_logger = event_logger
        self.dest = dest or backup_dir()
        self.kdf = kdf
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backup-run")
        self._armed_at: Optional[datetime] = read_armed_at(paths)
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._run_lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Let an in-flight run finish and report (bounded) before the loop is cancelled."""
        self._stopping.set()
        if self._run_lock.locked():
            try:
                await asyncio.wait_for(self._wait_idle(), STOP_GRACE_SECONDS)
            except asyncio.TimeoutError:
                logger.warning("Scheduled backup still running at shutdown; its partial file is removed on the next start")
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._executor.shutdown(wait=False)

    async def _wait_idle(self) -> None:
        async with self._run_lock:
            return

    def schedule_changed(self, now: Optional[datetime] = None) -> None:
        """Settings changed: never catch up an occurrence from before the change, even after a restart."""
        self._armed_at = now or _utcnow()
        write_armed_at(self.paths, self._armed_at)
        self._wake.set()

    async def _loop(self) -> None:
        try:
            await self._in_executor(self._sweep_partials)
        except Exception as e:
            logger.warning(f"Could not sweep partial scheduled backups: {e}")
        while True:
            try:
                await self.run_if_due(_utcnow())
            except Exception as e:
                logger.error(f"Backup scheduler error: {e}", exc_info=True)
            await self._sleep(await self._seconds_until_next(_utcnow()))

    def _sweep_partials(self) -> None:
        with operation_lock(self.paths):
            sweep_partials(self.dest, writer_id(self.paths))

    async def _in_executor(self, func, *args):
        # Shielded: cancelling the loop must not orphan the run it is waiting on.
        return await asyncio.shield(asyncio.get_running_loop().run_in_executor(self._executor, func, *args))

    async def _sleep(self, seconds: float) -> None:
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _seconds_until_next(self, now: datetime) -> float:
        settings = await asyncio.to_thread(read_schedule, self.db)
        if not settings.enabled:
            return MAX_SLEEP_SECONDS
        tz, _error = resolve_timezone()
        try:
            upcoming = next_occurrence(settings.schedule, now, tz)
        except InvalidSchedule:
            return MAX_SLEEP_SECONDS
        return max(1.0, min((upcoming - now).total_seconds(), MAX_SLEEP_SECONDS))

    def _is_due(self, settings: ScheduleSettings, now: datetime) -> bool:
        tz, _error = resolve_timezone()
        try:
            latest = previous_occurrence(settings.schedule, now, tz)
        except InvalidSchedule:
            return False
        baselines = [moment for moment in (settings.last_run_at, self._armed_at) if moment]
        if baselines and latest <= max(baselines):
            return False
        return now - latest <= CATCH_UP_WINDOW

    async def run_if_due(self, now: datetime) -> bool:
        if self._stopping.is_set():
            return False
        settings = await asyncio.to_thread(read_schedule, self.db)
        if not settings.enabled or not self._is_due(settings, now):
            return False
        await self.run(now, retry_busy=True)
        return True

    def _run_locked(self, passphrase: str, settings: ScheduleSettings) -> ScheduledRun:
        with operation_lock(self.paths):
            return run_scheduled_backup(
                self.paths, self.dest, passphrase, settings.include_stats, settings.retention, kdf=self.kdf
            )

    async def run(self, now: Optional[datetime] = None, retry_busy: bool = False) -> ScheduledRun:
        """Run one scheduled backup. Without retry_busy, a run already in progress or a held
        operation lock raises BackupBusyError and nothing is recorded."""
        if not retry_busy and self._run_lock.locked():
            raise BackupBusyError("A scheduled backup is already running")
        async with self._run_lock:
            now = now or _utcnow()
            settings = await asyncio.to_thread(read_schedule, self.db)
            try:
                passphrase = await asyncio.to_thread(stored_passphrase, self.db)
            except BackupError as e:
                result = ScheduledRun(status="failed", error=public_error(e))
            else:
                result = await self._run_with_retries(passphrase, settings, retry_busy)
            await self._report(result, now)
            return result

    async def _run_with_retries(self, passphrase: str, settings: ScheduleSettings, retry_busy: bool) -> ScheduledRun:
        attempts = LOCK_RETRY_ATTEMPTS if retry_busy else 1
        for attempt in range(attempts):
            try:
                return await self._in_executor(self._run_locked, passphrase, settings)
            except BackupBusyError:
                if not retry_busy:
                    raise
                if attempt < attempts - 1:
                    await self._sleep_unless_stopping(LOCK_RETRY_SECONDS)
            except Exception as e:
                logger.error(f"Scheduled backup failed: {e}", exc_info=True)
                return ScheduledRun(status="failed", error=public_error(e))
        return ScheduledRun(status="failed", error=SKIPPED_BUSY)

    async def _sleep_unless_stopping(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            return
        raise asyncio.CancelledError()

    async def _report(self, result: ScheduledRun, at: datetime) -> None:
        await asyncio.to_thread(record_run, self.db, result, at)
        if result.status == "failed":
            self.event_logger.log_system_event(
                "Scheduled backup failed", result.error or "", EventSeverity.ERROR, EventType.BACKUP
            )
            await self.alert_service.raise_backup_alert("Scheduled backup failed", result.error or "")
            return
        if result.status == "warning":
            self.event_logger.log_system_event(
                "Scheduled backup completed with a warning", result.error or "", EventSeverity.WARNING, EventType.BACKUP
            )
        else:
            self.event_logger.log_system_event(
                "Scheduled backup completed", f"Wrote {result.file}", EventSeverity.INFO, EventType.BACKUP
            )
        await self.alert_service.resolve_backup_alert()
