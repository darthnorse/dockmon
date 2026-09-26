import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import database as database_module
from backup import scheduler as scheduler_module
from backup.errors import BackupBusyError
from backup.schedule_store import read_schedule, record_run, update_schedule
from backup.scheduled import ScheduledRun
from backup.scheduler import BackupScheduler
from database import DatabaseManager
from event_logger import EventSeverity

UTC = timezone.utc


@pytest.fixture
def db(tmp_path):
    database_module._database_manager_instance = None
    manager = DatabaseManager(db_path=str(tmp_path / "test.db"))
    try:
        yield manager
    finally:
        manager.engine.dispose()
        database_module._database_manager_instance = None


@pytest.fixture
def harness(db, install, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    alerts = MagicMock(raise_backup_alert=AsyncMock(), resolve_backup_alert=AsyncMock())
    events = MagicMock()
    runs = []

    def fake_run(paths, dest, passphrase, include_stats, retention, **_kwargs):
        runs.append({"passphrase": passphrase, "retention": retention})
        return harness_state["result"]

    harness_state = {"result": ScheduledRun(status="ok", file="f.dmbak")}
    monkeypatch.setattr(scheduler_module, "run_scheduled_backup", fake_run)
    scheduler = BackupScheduler(install, db, alerts, events)
    update_schedule(db, passphrase="nas-backup-passphrase", enabled=True, schedule="03:00", retention=5)
    return scheduler, alerts, events, runs, harness_state


def _at(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


async def test_runs_when_an_occurrence_passed_since_the_last_run(harness, db):
    scheduler, alerts, events, runs, _ = harness
    record_run(db, ScheduledRun(status="ok"), _at(24, 3))

    assert await scheduler.run_if_due(_at(25, 3, 0)) is True

    assert runs == [{"passphrase": "nas-backup-passphrase", "retention": 5}]
    assert read_schedule(db).last_status == "ok"
    assert read_schedule(db).last_run_at == _at(25, 3, 0)
    alerts.resolve_backup_alert.assert_awaited_once()
    title, _message, severity, _type = events.log_system_event.call_args.args
    assert title == "Scheduled backup completed" and severity == EventSeverity.INFO


async def test_not_due_when_the_last_run_is_after_the_occurrence(harness, db):
    scheduler, _alerts, _events, runs, _ = harness
    record_run(db, ScheduledRun(status="ok"), _at(25, 3, 1))
    assert await scheduler.run_if_due(_at(25, 9)) is False
    assert runs == []


async def test_catches_up_a_run_missed_by_a_restart_within_six_hours(harness, db):
    scheduler, _alerts, _events, runs, _ = harness
    record_run(db, ScheduledRun(status="ok"), _at(24, 3))
    assert await scheduler.run_if_due(_at(25, 8, 59)) is True
    assert len(runs) == 1


async def test_skips_an_occurrence_missed_by_more_than_six_hours(harness, db):
    scheduler, _alerts, _events, runs, _ = harness
    record_run(db, ScheduledRun(status="ok"), _at(24, 3))
    assert await scheduler.run_if_due(_at(25, 9, 1)) is False
    assert runs == []


async def test_disabled_never_runs(harness, db):
    scheduler, _alerts, _events, runs, _ = harness
    update_schedule(db, enabled=False)
    assert await scheduler.run_if_due(_at(25, 3)) is False
    assert runs == []


async def test_a_schedule_change_does_not_catch_up_the_occurrence_just_before_it(harness, db):
    scheduler, _alerts, _events, runs, _ = harness
    record_run(db, ScheduledRun(status="ok"), _at(20, 3))
    scheduler.schedule_changed(now=_at(25, 3, 5))
    assert await scheduler.run_if_due(_at(25, 3, 6)) is False
    assert runs == []


async def test_failure_is_recorded_alerted_and_announced_to_admins_only(harness, db):
    scheduler, alerts, events, _runs, state = harness
    state["result"] = ScheduledRun(status="failed", error="The backup destination does not exist")
    record_run(db, ScheduledRun(status="ok"), _at(24, 3))

    await scheduler.run_if_due(_at(25, 3))

    assert read_schedule(db).last_status == "failed"
    alerts.raise_backup_alert.assert_awaited_once_with(
        "Scheduled backup failed", "The backup destination does not exist"
    )
    title, message, severity, event_type = events.log_system_event.call_args.args
    assert severity == EventSeverity.ERROR and event_type.value == "backup"
    assert message == "The backup destination does not exist"


async def test_retention_warning_resolves_the_alert_and_warns(harness, db):
    scheduler, alerts, events, _runs, state = harness
    state["result"] = ScheduledRun(status="warning", file="f.dmbak", error="retention failed")
    record_run(db, ScheduledRun(status="ok"), _at(24, 3))

    await scheduler.run_if_due(_at(25, 3))

    alerts.resolve_backup_alert.assert_awaited_once()
    assert events.log_system_event.call_args.args[2] == EventSeverity.WARNING


async def test_busy_lock_is_retried_then_recorded_as_skipped(harness, db, monkeypatch):
    scheduler, alerts, _events, runs, _ = harness
    monkeypatch.setattr(scheduler_module, "LOCK_RETRY_SECONDS", 0)
    monkeypatch.setattr(scheduler_module, "LOCK_RETRY_ATTEMPTS", 3)
    attempts = []

    def always_busy(*_args, **_kwargs):
        attempts.append(1)
        raise BackupBusyError("Another backup or restore operation is running")

    monkeypatch.setattr(scheduler, "_run_locked", always_busy)
    record_run(db, ScheduledRun(status="ok"), _at(24, 3))

    await scheduler.run_if_due(_at(25, 3))

    assert len(attempts) == 3
    assert read_schedule(db).last_status == "failed"
    assert "another operation" in read_schedule(db).last_error.lower()
    alerts.raise_backup_alert.assert_awaited_once()


async def test_start_and_stop(harness):
    scheduler, *_ = harness
    scheduler.start()
    await asyncio.sleep(0)
    await asyncio.wait_for(scheduler.stop(), timeout=5)
