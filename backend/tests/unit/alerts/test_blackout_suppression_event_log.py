"""Blackout suppression must be recognized BEFORE event-logging / retry accounting.

Regression: a notification attempt during a blackout window logged an
'[ALERT] Alert triggered' event and ran the failure/retry/give-up accounting
before the blackout was recognized, because the blackout check lived only
inside send_alert_v2 and returned a bare False (indistinguishable from a real
send failure). The result was 'Alert triggered' entries (and spurious
'failed for 24+ hours - giving up' errors) cluttering the log DURING a blackout
even though nothing was sent.

The suppression is now recognized at the top of _send_notification: flag the
alert for blackout-end processing, with no event, no send, no retry.
"""
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from alerts.evaluation_service import AlertEvaluationService
from blackout_manager import BlackoutManager
from database import AlertRuleV2, AlertV2


def _seed_open_alert(db):
    now = datetime.now(timezone.utc)
    alert_id = str(uuid.uuid4())
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="r1", name="Update Available - All", scope="container",
            kind="update_available", severity="info", enabled=True,
            notify_channels_json="[1]",
        ))
        session.add(AlertV2(
            id=alert_id, dedup_key=f"update_available|container:h:c|{alert_id}",
            scope_type="container", scope_id="h:c", kind="update_available",
            severity="info", state="open", title="Update Available - All - x",
            message="Update available", first_seen=now, last_seen=now,
            occurrences=1, rule_id="r1", suppressed_by_blackout=False,
        ))
        session.commit()
    return alert_id


def _service(db, *, in_blackout):
    # Real BlackoutManager so suppress_alert actually writes; window state forced.
    blackout_manager = BlackoutManager(db)
    blackout_manager.is_in_blackout_window = lambda: (
        (True, "Daily Update Check") if in_blackout else (False, None)
    )
    notification_service = types.SimpleNamespace(
        blackout_manager=blackout_manager,
        send_alert_v2=AsyncMock(return_value=False),
    )
    event_logger = MagicMock()
    service = AlertEvaluationService(
        db=db, notification_service=notification_service, event_logger=event_logger,
    )
    return service, notification_service, event_logger


def _detached(db, alert_id):
    with db.get_session() as session:
        alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()
        session.expunge(alert)
    return alert


@pytest.mark.asyncio
async def test_blackout_suppresses_without_event_or_retry(db):
    alert_id = _seed_open_alert(db)
    service, notification_service, event_logger = _service(db, in_blackout=True)

    await service._send_notification(_detached(db, alert_id))

    # No "Alert triggered" event written, and no send attempted.
    event_logger.log_event.assert_not_called()
    notification_service.send_alert_v2.assert_not_called()

    with db.get_session() as session:
        refreshed = session.query(AlertV2).filter(AlertV2.id == alert_id).first()
        # Flagged for blackout-end processing...
        assert refreshed.suppressed_by_blackout is True
        # ...and the retry/attempt accounting did NOT run.
        assert refreshed.notified_at is None
        assert refreshed.next_retry_at is None
        assert (refreshed.notification_count or 0) == 0


@pytest.mark.asyncio
async def test_no_blackout_still_logs_and_sends(db):
    # Guard: the normal (non-blackout) path is unaffected by the early check.
    alert_id = _seed_open_alert(db)
    service, notification_service, event_logger = _service(db, in_blackout=False)

    await service._send_notification(_detached(db, alert_id))

    event_logger.log_event.assert_called_once()
    notification_service.send_alert_v2.assert_awaited_once()
