"""Scheduled-backup failures raise their own system alert.

It must not share the evaluation-failure alert's dedup key (a clean evaluation
cycle would resolve it within seconds), and the generic 24h stale sweep must not
expire it: a weekly backup that keeps failing sees no update for days.
"""
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

import database as database_module
from alerts.evaluation_service import AlertEvaluationService
from database import AlertV2, DatabaseManager
from docker_monitor.periodic_jobs import PeriodicJobsManager


@pytest.fixture
def db(tmp_path):
    database_module._database_manager_instance = None
    manager = DatabaseManager(db_path=str(tmp_path / "test.db"))
    try:
        yield manager
    finally:
        manager.engine.dispose()
        database_module._database_manager_instance = None


def _service(db):
    monitor = types.SimpleNamespace(hosts={}, get_last_containers=lambda: [], get_containers=AsyncMock(return_value=[]))
    stats = types.SimpleNamespace(get_host_stats=AsyncMock(return_value={}), get_container_stats=AsyncMock(return_value={}))
    service = AlertEvaluationService(db=db, monitor=monitor, stats_client=stats)
    service._handle_alert_notification = AsyncMock()
    return service


def _system_alerts(db):
    with db.get_session() as session:
        rows = session.query(AlertV2).filter(AlertV2.scope_type == "system").all()
        session.expunge_all()
        return rows


async def test_backup_alert_has_its_own_identity_and_text(db):
    service = _service(db)
    await service.raise_backup_alert("Scheduled backup failed", "The backup destination does not exist")

    [alert] = _system_alerts(db)
    assert alert.scope_id == "backup"
    assert alert.dedup_key.endswith("|system_error|system:backup")
    assert alert.title == "Scheduled backup failed"
    assert alert.message == "The backup destination does not exist"
    assert alert.state == "open"


async def test_clean_evaluation_cycle_leaves_the_backup_alert_open(db):
    service = _service(db)
    await service.raise_backup_alert("Scheduled backup failed", "x")
    service._cycle_failures = []
    await service._report_cycle_failures()

    assert _system_alerts(db)[0].state == "open"


async def test_resolve_backup_alert(db):
    service = _service(db)
    await service.raise_backup_alert("Scheduled backup failed", "x")
    await service.resolve_backup_alert()

    assert _system_alerts(db)[0].state == "resolved"
    await service.resolve_backup_alert()


async def test_stale_sweep_does_not_expire_the_backup_alert(db):
    service = _service(db)
    await service.raise_backup_alert("Scheduled backup failed", "x")
    with db.get_session() as session:
        alert = session.query(AlertV2).one()
        alert.last_seen = datetime.now(timezone.utc) - timedelta(days=3)
        session.commit()

    jobs = PeriodicJobsManager(db, event_logger=types.SimpleNamespace())
    await jobs.auto_resolve_stale_alerts()

    assert _system_alerts(db)[0].state == "open"
