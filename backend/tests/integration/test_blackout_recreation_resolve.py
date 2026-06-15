"""Blackout-end recreation regression (issue #229).

A container stopped during a blackout window, then recreated (new ID, same name,
running) before the window ends, must be auto-resolved WITHOUT a notification when
the window closes.
"""
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

import database as database_module
from alerts.evaluation_service import AlertEvaluationService
from database import AlertV2, DatabaseManager

HOST = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
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


async def test_blackout_end_resolves_recreated_container_without_notifying(db):
    alert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with db.get_session() as session:
        session.add(AlertV2(
            id=alert_id,
            dedup_key=f"container_stopped|container:{HOST}:{OLD_ID}",
            scope_type="container",
            scope_id=f"{HOST}:{OLD_ID}",
            kind="container_stopped",
            severity="warning",
            state="open",
            title="Container Stopped/Died - nextcloud",
            message="Container nextcloud stopped",
            first_seen=now,
            last_seen=now,
            host_id=HOST,
            container_name="nextcloud",
            suppressed_by_blackout=True,
        ))
        session.commit()

    # Monitor reports the recreated container: same name + host, NEW id, running.
    monitor = types.SimpleNamespace(
        get_containers=AsyncMock(return_value=[
            types.SimpleNamespace(short_id=NEW_ID, name="nextcloud", state="running", host_id=HOST)
        ])
    )
    # Blackout has just ended (is_in_blackout_window takes no args in production).
    blackout_manager = types.SimpleNamespace(is_in_blackout_window=lambda: (False, None))
    notification_service = types.SimpleNamespace(blackout_manager=blackout_manager)

    service = AlertEvaluationService(
        db=db, monitor=monitor, notification_service=notification_service
    )
    service._last_blackout_state = True  # was in blackout, now ended
    service._send_notification = AsyncMock()

    await service._check_blackout_transitions()

    # No trigger notification fired for the recreated-and-running container.
    service._send_notification.assert_not_called()

    # Alert is resolved and the suppression flag is cleared.
    with db.get_session() as session:
        refreshed = session.query(AlertV2).filter(AlertV2.id == alert_id).first()
        assert refreshed.state == "resolved"
        assert refreshed.suppressed_by_blackout is False
