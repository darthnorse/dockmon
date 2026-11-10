"""Batch resolve/snooze endpoints and idempotent single resolve."""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.routing import Match

from alerts.api import (
    router,
    BatchResolveRequest,
    BatchSnoozeRequest,
    MAX_BATCH_ALERTS,
    ResolveAlertRequest,
    batch_resolve_alerts,
    batch_snooze_alerts,
    resolve_alert,
)
from database import AlertV2

CALLER = {"auth_type": "api_key", "group_id": 1, "api_key_name": "test"}


def _make_alert(db_session, state="open", scope_id="test-host") -> str:
    alert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db_session.add(AlertV2(
        id=alert_id,
        dedup_key=f"cpu_high|host:{alert_id}",
        scope_type="host",
        scope_id=scope_id,
        host_id=scope_id,
        kind="cpu_high",
        severity="warning",
        state=state,
        title="Test alert",
        message="Test alert body",
        first_seen=now,
        last_seen=now,
        resolved_at=now if state == "resolved" else None,
    ))
    db_session.commit()
    return alert_id


def _state(db_session, alert_id):
    db_session.expire_all()
    return db_session.query(AlertV2).filter_by(id=alert_id).one()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_batch_resolve_mixed(db_session, test_database_manager):
    open_a = _make_alert(db_session)
    open_b = _make_alert(db_session, state="snoozed")
    done = _make_alert(db_session, state="resolved")
    hidden = _make_alert(db_session, scope_id="hidden-host")
    unknown = str(uuid.uuid4())

    with patch("alerts.api.get_visible_host_ids_for_auth", return_value={"test-host"}), \
         patch("alerts.api.security_audit") as audit:
        result = await batch_resolve_alerts(
            request=BatchResolveRequest(alert_ids=[open_a, open_b, done, hidden, unknown]),
            db=test_database_manager,
            current_user=CALLER,
        )

    assert sorted(result.resolved) == sorted([open_a, open_b])
    assert [(s.id, s.reason) for s in result.skipped] == [(done, "already_resolved")]
    assert sorted(result.not_found) == sorted([hidden, unknown])
    for alert_id in (open_a, open_b):
        row = _state(db_session, alert_id)
        assert row.state == "resolved"
        assert row.resolved_reason == "Manually resolved"
        assert row.resolve_notified_at is not None
    assert _state(db_session, hidden).state == "open"
    assert audit.log_event.call_count == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_batch_resolve_commit_failure_changes_nothing(db_session, test_database_manager):
    alert_id = _make_alert(db_session)

    with patch("sqlalchemy.orm.Session.commit", side_effect=RuntimeError("disk full")), \
         patch("alerts.api.security_audit") as audit:
        with pytest.raises(RuntimeError):
            await batch_resolve_alerts(
                request=BatchResolveRequest(alert_ids=[alert_id]),
                db=test_database_manager,
                current_user=CALLER,
            )

    assert _state(db_session, alert_id).state == "open"
    audit.log_event.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_batch_snooze_mixed(db_session, test_database_manager):
    open_a = _make_alert(db_session)
    done = _make_alert(db_session, state="resolved")
    hidden = _make_alert(db_session, scope_id="hidden-host")

    with patch("alerts.api.get_visible_host_ids_for_auth", return_value={"test-host"}), \
         patch("alerts.api.security_audit") as audit:
        result = await batch_snooze_alerts(
            request=BatchSnoozeRequest(alert_ids=[open_a, done, hidden], duration_minutes=60),
            db=test_database_manager,
            current_user=CALLER,
        )

    assert result.snoozed == [open_a]
    assert [(s.id, s.reason) for s in result.skipped] == [(done, "already_resolved")]
    assert result.not_found == [hidden]
    row = _state(db_session, open_a)
    assert row.state == "snoozed"
    assert row.snoozed_until is not None
    assert audit.log_event.call_count == 1


@pytest.mark.parametrize("ids", [[], [str(i) for i in range(MAX_BATCH_ALERTS + 1)]])
def test_batch_request_size_bounds(ids):
    with pytest.raises(ValidationError):
        BatchResolveRequest(alert_ids=ids)
    with pytest.raises(ValidationError):
        BatchSnoozeRequest(alert_ids=ids, duration_minutes=5)


def test_reason_and_id_lengths_are_bounded():
    with pytest.raises(ValidationError):
        BatchResolveRequest(alert_ids=["a"], reason="x" * 501)
    with pytest.raises(ValidationError):
        ResolveAlertRequest(reason="x" * 501)
    with pytest.raises(ValidationError):
        BatchResolveRequest(alert_ids=["a" * 65])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_resolve_of_open_alert(db_session, test_database_manager):
    alert_id = _make_alert(db_session)
    with patch("alerts.api.security_audit") as audit:
        result = await resolve_alert(
            alert_id=alert_id,
            request=ResolveAlertRequest(),
            db=test_database_manager,
            current_user=CALLER,
        )
    assert result.state == "resolved"
    row = _state(db_session, alert_id)
    assert row.state == "resolved"
    assert row.resolve_notified_at is not None
    audit.log_event.assert_called_once()


def test_batch_request_dedupes_ids():
    assert BatchResolveRequest(alert_ids=["a", "b", "a"]).alert_ids == ["a", "b"]


@pytest.mark.parametrize("path,endpoint", [
    ("/api/alerts/batch/resolve", batch_resolve_alerts),
    ("/api/alerts/batch/snooze", batch_snooze_alerts),
])
def test_batch_routes_are_not_captured_by_alert_id_routes(path, endpoint):
    scope = {"type": "http", "path": path, "method": "POST"}
    first = next(r for r in router.routes if r.matches(scope)[0] == Match.FULL)
    assert first.endpoint is endpoint


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_resolve_of_resolved_alert_is_idempotent(db_session, test_database_manager):
    alert_id = _make_alert(db_session, state="resolved")
    before = _state(db_session, alert_id).resolved_at

    with patch("alerts.api.security_audit") as audit:
        result = await resolve_alert(
            alert_id=alert_id,
            request=ResolveAlertRequest(),
            db=test_database_manager,
            current_user=CALLER,
        )

    assert result.state == "resolved"
    assert _state(db_session, alert_id).resolved_at == before
    audit.log_event.assert_not_called()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_resolve_of_hidden_alert_still_404(db_session, test_database_manager):
    alert_id = _make_alert(db_session, state="resolved", scope_id="hidden-host")
    with patch("alerts.api.get_visible_host_ids_for_auth", return_value={"test-host"}):
        with pytest.raises(HTTPException) as exc:
            await resolve_alert(
                alert_id=alert_id,
                request=ResolveAlertRequest(),
                db=test_database_manager,
                    current_user=CALLER,
            )
    assert exc.value.status_code == 404
