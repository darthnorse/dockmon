"""Recreation-aware alert verification tests (issue #229).

When a container is recreated (update / compose redeploy / backup) it keeps its
name but gets a new Docker ID. _verify_alert_condition must treat a running
same-name, same-host replacement as 'condition cleared' instead of firing a false
'container down' notification.
"""
import types
from unittest.mock import AsyncMock

import pytest

import database as database_module
from alerts.evaluation_service import AlertEvaluationService
from database import DatabaseManager

HOST = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
OTHER_HOST = "11111111-2222-3333-4444-555555555555"
OLD_ID = "aaaaaaaaaaaa"
NEW_ID = "bbbbbbbbbbbb"


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database_module._database_manager_instance = None
    db_manager = DatabaseManager(db_path=db_path)
    try:
        yield db_manager
    finally:
        if hasattr(db_manager, "engine"):
            db_manager.engine.dispose()
        database_module._database_manager_instance = None


def _container(short_id, name, state, host_id=HOST):
    return types.SimpleNamespace(short_id=short_id, name=name, state=state, host_id=host_id)


def _alert(kind="container_stopped", name="nextcloud", host_id=HOST, old_id=OLD_ID):
    return types.SimpleNamespace(
        id="alert-1",
        kind=kind,
        scope_type="container",
        scope_id=f"{host_id}:{old_id}",
        host_id=host_id,
        container_name=name,
    )


def _service(db, containers):
    monitor = types.SimpleNamespace(get_containers=AsyncMock(return_value=containers))
    return AlertEvaluationService(db=db, monitor=monitor)


# --- container_stopped: a recovered container clears the alert ---

async def test_recreated_running_clears_condition(db):
    service = _service(db, [_container(NEW_ID, "nextcloud", "running")])
    assert await service._verify_alert_condition(_alert()) is False


# --- container_stopped: regression guards ---

async def test_recreated_restarting_keeps_alert(db):
    # 'restarting' at verification time is a crash loop, not recovery - keep alerting.
    service = _service(db, [_container(NEW_ID, "nextcloud", "restarting")])
    assert await service._verify_alert_condition(_alert()) is True


async def test_original_present_and_restarting_keeps_alert(db):
    # Original container still present but stuck restarting (crash loop) - keep.
    service = _service(db, [_container(OLD_ID, "nextcloud", "restarting")])
    assert await service._verify_alert_condition(_alert()) is True


async def test_recreated_but_replacement_exited_keeps_alert(db):
    service = _service(db, [_container(NEW_ID, "nextcloud", "exited")])
    assert await service._verify_alert_condition(_alert()) is True


async def test_gone_without_replacement_keeps_alert(db):
    service = _service(db, [_container("cccccccccccc", "other", "running")])
    assert await service._verify_alert_condition(_alert()) is True


async def test_same_name_on_different_host_keeps_alert(db):
    service = _service(db, [_container(NEW_ID, "nextcloud", "running", host_id=OTHER_HOST)])
    assert await service._verify_alert_condition(_alert()) is True


async def test_original_still_present_and_exited_keeps_alert(db):
    service = _service(db, [_container(OLD_ID, "nextcloud", "exited")])
    assert await service._verify_alert_condition(_alert()) is True


async def test_original_present_and_running_clears_condition(db):
    service = _service(db, [_container(OLD_ID, "nextcloud", "running")])
    assert await service._verify_alert_condition(_alert()) is False


async def test_missing_container_name_keeps_alert(db):
    alert = _alert()
    alert.container_name = None
    service = _service(db, [_container(NEW_ID, "nextcloud", "running")])
    assert await service._verify_alert_condition(alert) is True


# --- unhealthy ---
# state carries no health value, so recovery is event-driven; a recreated replacement
# clears the stale old-ID alert only when it is back up.

async def test_unhealthy_recreated_replacement_clears_condition(db):
    service = _service(db, [_container(NEW_ID, "nextcloud", "running")])
    assert await service._verify_alert_condition(_alert(kind="unhealthy")) is False


async def test_unhealthy_recreated_replacement_not_running_keeps_alert(db):
    # Recreated but the replacement is exited/dead - no health event will re-alert,
    # so keep the unhealthy alert (mirrors the container_stopped branch).
    service = _service(db, [_container(NEW_ID, "nextcloud", "exited")])
    assert await service._verify_alert_condition(_alert(kind="unhealthy")) is True


async def test_unhealthy_gone_without_replacement_keeps_alert(db):
    service = _service(db, [_container("cccccccccccc", "other", "running")])
    assert await service._verify_alert_condition(_alert(kind="unhealthy")) is True


async def test_unhealthy_present_container_keeps_alert(db):
    # Present container: state can never read 'unhealthy', so keep the alert (recovery
    # is event-driven) rather than silently resolving.
    service = _service(db, [_container(OLD_ID, "nextcloud", "running")])
    assert await service._verify_alert_condition(_alert(kind="unhealthy")) is True
