"""Evaluation failures must be visible, not swallowed (issue #243, Fix E).

Metric evaluation catches broadly at four sites so one bad sample cannot abort
the cycle. That isolation is correct; the silence was not. A swallowed failure
now produces one aggregated system alert per cycle, notified under the system
rule's own cooldown, while the alert row keeps updating every failing cycle.
"""
import logging
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

import database as database_module
from alerts.evaluation_service import AlertEvaluationService
from database import AlertRuleV2, AlertV2, DatabaseManager

HOST_A = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
HOST_B = "11111111-2222-3333-4444-555555555555"


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


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _host(host_id, name):
    return types.SimpleNamespace(
        id=host_id, name=name, connection_type="agent", status="online"
    )


class ExplodingStats(dict):
    """A stats payload that raises when the evaluator reads a metric."""

    def get(self, key, default=None):
        if key in ("cpu_percent", "memory_percent"):
            raise ValueError("secret-token-abc123 malformed sample")
        return super().get(key, default)


def _service(db, hosts, host_stats=None, container_stats=None, containers=None):
    monitor = types.SimpleNamespace(
        hosts={h.id: h for h in hosts},
        get_last_containers=lambda: containers or [],
        get_containers=AsyncMock(return_value=containers or []),
    )
    stats_client = types.SimpleNamespace(
        get_host_stats=AsyncMock(return_value=host_stats or {}),
        get_container_stats=AsyncMock(return_value=container_stats or {}),
    )
    service = AlertEvaluationService(db=db, monitor=monitor, stats_client=stats_client)
    service._handle_alert_notification = AsyncMock()

    # Spy rather than replace: the real _send_notification is what stamps
    # notified_at, which is what the cooldown reads. With no notification
    # service configured it takes the permanent-failure path and still stamps.
    real_send = service._send_notification
    service.notification_calls = []

    async def counting_send(alert):
        service.notification_calls.append(alert.id)
        return await real_send(alert)

    service._send_notification = counting_send
    return service


def _add_host_rule(db, metric="cpu_percent", threshold=80.0, rule_id="rule-e"):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id=rule_id, name=f"{metric} high", kind=f"{metric}_high", enabled=True,
            scope="host", metric=metric, operator=">=", threshold=threshold,
            occurrences=1, severity="warning",
        ))
        session.commit()


def _system_alerts(db):
    with db.get_session() as session:
        rows = session.query(AlertV2).filter(AlertV2.scope_type == "system").all()
        session.expunge_all()
        return rows


# --- isolation: a failure must not abort the rest of the cycle ---

async def test_one_bad_host_does_not_stop_another_host_alerting(db):
    _add_host_rule(db)
    service = _service(
        db,
        [_host(HOST_A, "broken"), _host(HOST_B, "healthy")],
        host_stats={
            HOST_A: ExplodingStats(last_update=_now_iso()),
            HOST_B: {"cpu_percent": 99.0, "last_update": _now_iso()},
        },
    )

    await service._evaluate_all_rules()

    assert service._handle_alert_notification.await_count == 1, (
        "the healthy host's rule must still fire when another host's sample explodes"
    )


async def test_one_bad_container_does_not_stop_another_container_alerting(db):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="rule-c", name="container cpu", kind="cpu_high", enabled=True,
            scope="container", metric="cpu_percent", operator=">=", threshold=50.0,
            occurrences=1, severity="warning",
        ))
        session.commit()

    def _container(cid, name):
        return types.SimpleNamespace(
            host_id=HOST_A, short_id=cid, name=name, host_name="h",
            desired_state="running", labels={}, tags=[],
        )

    service = _service(
        db, [_host(HOST_A, "h")],
        containers=[_container("aaaaaaaaaaaa", "broken"), _container("bbbbbbbbbbbb", "healthy")],
        container_stats={
            f"{HOST_A}:aaaaaaaaaaaa": ExplodingStats(last_update=_now_iso()),
            f"{HOST_A}:bbbbbbbbbbbb": {"cpu_percent": 99.0, "last_update": _now_iso()},
        },
    )

    await service._evaluate_all_rules()

    assert service._handle_alert_notification.await_count == 1


# --- visibility ---

async def test_swallowed_failure_raises_one_system_alert(db):
    _add_host_rule(db)
    service = _service(
        db, [_host(HOST_A, "broken")],
        host_stats={HOST_A: ExplodingStats(last_update=_now_iso())},
    )

    await service._evaluate_all_rules()

    alerts = _system_alerts(db)
    assert len(alerts) == 1, "a swallowed failure must not stay invisible"
    assert "broken" in alerts[0].message


async def test_several_failures_in_one_cycle_produce_one_alert(db):
    _add_host_rule(db)
    service = _service(
        db,
        [_host(HOST_A, "broken-a"), _host(HOST_B, "broken-b")],
        host_stats={
            HOST_A: ExplodingStats(last_update=_now_iso()),
            HOST_B: ExplodingStats(last_update=_now_iso()),
        },
    )

    await service._evaluate_all_rules()

    assert len(_system_alerts(db)) == 1
    assert len(service.notification_calls) == 1


async def test_collector_resets_between_cycles(db):
    _add_host_rule(db)
    service = _service(
        db, [_host(HOST_A, "broken")],
        host_stats={HOST_A: ExplodingStats(last_update=_now_iso())},
    )

    await service._evaluate_all_rules()
    assert service._cycle_failures

    # Same instance, now healthy.
    service.stats_client.get_host_stats = AsyncMock(
        return_value={HOST_A: {"cpu_percent": 1.0, "last_update": _now_iso()}}
    )
    await service._evaluate_all_rules()

    assert service._cycle_failures == [], "failures must not leak into the next cycle"
    assert len(_system_alerts(db)) == 1, "a clean cycle must not raise a second alert"


async def test_clean_cycle_raises_no_system_alert(db):
    _add_host_rule(db)
    service = _service(
        db, [_host(HOST_A, "healthy")],
        host_stats={HOST_A: {"cpu_percent": 1.0, "last_update": _now_iso()}},
    )

    await service._evaluate_all_rules()

    assert _system_alerts(db) == []


# --- cooldown: persistence every cycle, notification throttled ---

async def test_repeat_failure_updates_the_alert_but_does_not_renotify(db):
    _add_host_rule(db)
    service = _service(
        db, [_host(HOST_A, "broken")],
        host_stats={HOST_A: ExplodingStats(last_update=_now_iso())},
    )

    await service._evaluate_all_rules()
    first = _system_alerts(db)[0]
    assert len(service.notification_calls) == 1

    await service._evaluate_all_rules()

    second = _system_alerts(db)[0]
    assert len(_system_alerts(db)) == 1
    assert second.occurrences > first.occurrences, "the alert must keep recording occurrences"
    assert second.last_seen >= first.last_seen
    assert len(service.notification_calls) == 1, (
        "a continuing failure must not notify every 10s cycle"
    )


async def test_failure_after_cooldown_notifies_again(db):
    _add_host_rule(db)
    service = _service(
        db, [_host(HOST_A, "broken")],
        host_stats={HOST_A: ExplodingStats(last_update=_now_iso())},
    )

    await service._evaluate_all_rules()
    assert len(service.notification_calls) == 1

    # Age the notification past the system rule's cooldown (3600s).
    with db.get_session() as session:
        alert = session.query(AlertV2).filter(AlertV2.scope_type == "system").first()
        alert.notified_at = datetime.now(timezone.utc) - timedelta(seconds=7200)
        session.commit()

    await service._evaluate_all_rules()

    assert len(service.notification_calls) == 2


# --- message content ---

async def test_alert_message_carries_class_and_scope_but_not_raw_error(db, caplog):
    _add_host_rule(db)
    service = _service(
        db, [_host(HOST_A, "broken")],
        host_stats={HOST_A: ExplodingStats(last_update=_now_iso())},
    )

    with caplog.at_level(logging.ERROR):
        await service._evaluate_all_rules()

    message = _system_alerts(db)[0].message
    assert "ValueError" in message
    assert "broken" in message
    assert "secret-token-abc123" not in message, (
        "raw exception text must stay in the log, not reach notification channels"
    )
    assert any("secret-token-abc123" in r.message for r in caplog.records), (
        "the full error must still be logged for debugging"
    )


# --- bounds: the alert must survive a fleet-wide failure ---

async def test_message_is_bounded_when_every_container_fails(db):
    """An oversized body is rejected by notification channels, losing the alert
    exactly when the failure is widespread."""
    service = _service(db, [_host(HOST_A, "h")])
    for i in range(200):
        service._cycle_failures.append({
            "site": "container",
            "scope": f"{HOST_A}:{i:012d}",
            "error": "ValueError",
            "pass_level": False,
        })

    await service._report_cycle_failures()

    message = _system_alerts(db)[0].message
    assert len(message) <= 1000, f"message is {len(message)} chars; channels reject it"
    assert "more" in message, "the omitted scopes must still be accounted for"
    assert "200 evaluation failure(s)" in message


async def test_long_scope_names_are_clamped(db):
    """Container names are user-controlled, so one long name must not blow the body."""
    service = _service(db, [_host(HOST_A, "h")])
    service._cycle_failures.append({
        "site": "container metric cpu_percent",
        "scope": "x" * 5000,
        "error": "ValueError",
        "pass_level": False,
    })

    await service._report_cycle_failures()

    assert len(_system_alerts(db)[0].message) <= 1000


async def test_pass_level_count_comes_from_the_record_not_the_site_string(db):
    service = _service(db, [_host(HOST_A, "h")])
    service._cycle_failures = [
        {"site": "host pass", "scope": "all hosts", "error": "KeyError", "pass_level": True},
        {"site": "container", "scope": "c1", "error": "ValueError", "pass_level": False},
    ]

    await service._report_cycle_failures()

    assert "(1 pass-level)" in _system_alerts(db)[0].message


# --- recovery ---

async def test_clean_cycle_resolves_the_open_system_alert(db):
    """Nothing else resolves system-scope alerts, so a transient failure would
    otherwise leave an error alert open forever."""
    _add_host_rule(db)
    service = _service(
        db, [_host(HOST_A, "broken")],
        host_stats={HOST_A: ExplodingStats(last_update=_now_iso())},
    )

    await service._evaluate_all_rules()
    assert _system_alerts(db)[0].state == "open"

    service.stats_client.get_host_stats = AsyncMock(
        return_value={HOST_A: {"cpu_percent": 1.0, "last_update": _now_iso()}}
    )
    await service._evaluate_all_rules()

    assert _system_alerts(db)[0].state == "resolved"


async def test_alert_left_open_by_a_previous_process_is_resolved(db):
    """The in-memory flag starts unknown, so a restart still clears a stale alert."""
    _add_host_rule(db)
    failing = _service(
        db, [_host(HOST_A, "broken")],
        host_stats={HOST_A: ExplodingStats(last_update=_now_iso())},
    )
    await failing._evaluate_all_rules()
    assert _system_alerts(db)[0].state == "open"

    # Fresh service instance, as after a restart.
    restarted = _service(
        db, [_host(HOST_A, "healthy")],
        host_stats={HOST_A: {"cpu_percent": 1.0, "last_update": _now_iso()}},
    )
    await restarted._evaluate_all_rules()

    assert _system_alerts(db)[0].state == "resolved"


# --- cooldown of zero means notify every time ---

async def test_zero_cooldown_notifies_every_cycle(db):
    _add_host_rule(db)
    service = _service(
        db, [_host(HOST_A, "broken")],
        host_stats={HOST_A: ExplodingStats(last_update=_now_iso())},
    )
    rule = db.get_or_create_system_alert_rule()
    with db.get_session() as session:
        row = session.query(AlertRuleV2).filter(AlertRuleV2.id == rule.id).first()
        row.notification_cooldown_seconds = 0
        session.commit()

    await service._evaluate_all_rules()
    await service._evaluate_all_rules()

    assert len(service.notification_calls) == 2, (
        "a configured 0 means notify immediately, not fall back to an hour"
    )


async def test_failed_resolution_is_retried_on_the_next_clean_cycle(db):
    """Clearing the flag unconditionally would strand the alert open after a
    transient error, since later clean cycles would return before retrying."""
    _add_host_rule(db)
    service = _service(
        db, [_host(HOST_A, "broken")],
        host_stats={HOST_A: ExplodingStats(last_update=_now_iso())},
    )
    await service._evaluate_all_rules()
    assert _system_alerts(db)[0].state == "open"

    service.stats_client.get_host_stats = AsyncMock(
        return_value={HOST_A: {"cpu_percent": 1.0, "last_update": _now_iso()}}
    )

    real_resolve = service.engine._resolve_alert
    service.engine._resolve_alert = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("db locked"))
    await service._evaluate_all_rules()
    assert _system_alerts(db)[0].state == "open", "resolution failed, as staged"

    service.engine._resolve_alert = real_resolve
    await service._evaluate_all_rules()

    assert _system_alerts(db)[0].state == "resolved", "the retry must happen"
