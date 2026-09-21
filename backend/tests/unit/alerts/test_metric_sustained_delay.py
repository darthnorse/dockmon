"""alert_active_delay_seconds on a metric rule means the condition must hold,
without interruption, for that long in the source's own time before the alert
fires. Before this, the delay was only a window for `occurrences` breaches, so a
300 s / 3-occurrence rule fired ~30 s after CPU crossed the threshold; a rule
with delay 0 counted breaches over its whole lifetime; and a clear could not
start until the window had aged out."""

import json
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from alerts.capabilities import STATS_MAX_AGE_SECONDS
from alerts.engine import AlertEngine, EvaluationContext
from alerts.evaluation_service import AlertEvaluationService
from database import AlertRuleV2, AlertV2, RuleRuntime

T0 = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
HOST_ID = "b689ba69-f943-4287-9554-68375c37194f"
NEW_STATE_KEYS = {"breach_started_at", "breach_count", "clear_started_at", "last_sample_at"}


def at(seconds):
    return T0 + timedelta(seconds=seconds)


def _cpu_rule(db, active_delay=300, occurrences=3, clear_delay=60, clear_threshold=None):
    rule_id = str(uuid.uuid4())
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id=rule_id, name="Host High CPU", kind="cpu_high", scope="host", severity="warning",
            metric="cpu_percent", operator=">=", threshold=80.0, clear_threshold=clear_threshold,
            enabled=True, occurrences=occurrences, alert_active_delay_seconds=active_delay,
            alert_clear_delay_seconds=clear_delay, notification_cooldown_seconds=300,
            host_selector_json=json.dumps({"include_all": True}),
        ))
        session.commit()
    return rule_id


def _context():
    return EvaluationContext(scope_type="host", scope_id=HOST_ID, host_id=HOST_ID, host_name="mediadmz")


def _state(db, rule_id):
    with db.get_session() as session:
        runtime = session.query(RuleRuntime).filter(RuleRuntime.dedup_key.like(f"{rule_id}%")).one()
        return json.loads(runtime.state_json)


def _alert(db):
    with db.get_session() as session:
        alert = session.query(AlertV2).one()
        session.expunge(alert)
        return alert


def _expire_cooldown(db):
    with db.get_session() as session:
        session.query(AlertV2).one().notified_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        session.commit()


def _resolve(db, engine):
    with db.get_session() as session:
        engine._resolve_alert(session.query(AlertV2).one(), "manual", notify=False)


def _sustain(engine, value, start, end, step=10):
    """Evaluate `value` at every `step` from start up to and excluding end; none may fire."""
    for s in range(start, end, step):
        assert engine.evaluate_metric("cpu_percent", value, _context(), sampled_at=at(s)) == [], f"fired at t={s}"


def _open_alert(db, engine, value=95.0):
    """Drive a 300 s / 3-occurrence rule to its first fire at t=300."""
    _sustain(engine, value, 0, 300)
    fired = engine.evaluate_metric("cpu_percent", value, _context(), sampled_at=at(300))
    assert len(fired) == 1 and fired[0].state == "open"
    return fired[0]


# --- firing ---

def test_fires_only_after_the_delay_has_been_sustained(db):
    _cpu_rule(db)
    engine = AlertEngine(db)

    _sustain(engine, 95.0, 0, 300)
    fired = engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(300))

    assert len(fired) == 1 and fired[0].state == "open"
    assert fired[0].current_value == 95.0


def test_a_single_dip_restarts_the_run(db):
    rule_id = _cpu_rule(db)
    engine = AlertEngine(db)

    _sustain(engine, 95.0, 0, 150)
    assert engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(150)) == []
    assert _state(db, rule_id)["breach_started_at"] is None

    _sustain(engine, 95.0, 160, 460)
    assert len(engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(460))) == 1


def test_delay_zero_needs_consecutive_breaches(db):
    _cpu_rule(db, active_delay=0, occurrences=3)
    engine = AlertEngine(db)

    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(0)) == []
    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(10)) == []
    assert engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(20)) == []
    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(30)) == []
    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(40)) == []
    assert len(engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(50))) == 1


def test_delay_zero_without_occurrences_fires_on_the_first_breach(db):
    _cpu_rule(db, active_delay=0, occurrences=None)
    engine = AlertEngine(db)

    assert len(engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(0))) == 1


# --- continuity ---

def test_a_gap_between_samples_restarts_the_run(db):
    rule_id = _cpu_rule(db, occurrences=1)
    engine = AlertEngine(db)

    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(0)) == []
    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(300)) == []

    assert _state(db, rule_id)["breach_started_at"] == at(300).isoformat()


def test_gap_tolerance_follows_the_configured_max_gap(db):
    _cpu_rule(db, occurrences=1)
    engine = AlertEngine(db, max_gap_seconds=200)

    _sustain(engine, 95.0, 0, 300, step=100)
    assert len(engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(300))) == 1


def test_a_duplicate_sample_counts_once_and_cannot_create_or_reopen(db):
    rule_id = _cpu_rule(db, active_delay=0, occurrences=2)
    engine = AlertEngine(db)

    for _ in range(4):
        assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(0)) == []
    assert _state(db, rule_id)["breach_count"] == 1
    with db.get_session() as session:
        assert session.query(AlertV2).count() == 0

    assert len(engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(10))) == 1

    # Open and past cooldown: a frozen source must not silence the re-notify cadence
    _expire_cooldown(db)
    renotified = engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(10))
    assert len(renotified) == 1 and renotified[0].state == "open"

    # Resolved: a duplicate is not a new observation, so it cannot reopen
    _resolve(db, engine)
    _expire_cooldown(db)
    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(10)) == []
    assert _alert(db).state == "resolved"


def test_a_backward_timestamp_restarts_the_run(db):
    rule_id = _cpu_rule(db, occurrences=1)
    engine = AlertEngine(db)

    _sustain(engine, 95.0, 0, 300)
    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(100)) == []

    assert _state(db, rule_id)["breach_started_at"] == at(100).isoformat()


def test_unstamped_samples_fall_back_to_evaluation_time(db):
    """Degraded mode: without a source timestamp every evaluation is a new sample."""
    _cpu_rule(db, active_delay=0, occurrences=3)
    engine = AlertEngine(db)

    assert engine.evaluate_metric("cpu_percent", 95.0, _context()) == []
    assert engine.evaluate_metric("cpu_percent", 95.0, _context()) == []
    assert len(engine.evaluate_metric("cpu_percent", 95.0, _context())) == 1


def test_service_derives_max_gap_from_the_evaluation_interval(db):
    default = AlertEvaluationService(db=db)
    assert default.engine.max_gap_seconds == STATS_MAX_AGE_SECONDS

    slow = AlertEvaluationService(db=db, evaluation_interval=100)
    assert slow.engine.max_gap_seconds == 200


# --- clearing ---

def test_clear_starts_on_the_first_sample_under_threshold(db):
    rule_id = _cpu_rule(db)
    engine = AlertEngine(db)
    _open_alert(db, engine)

    assert engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(310)) == []
    assert _state(db, rule_id)["clear_started_at"] == at(310).isoformat()
    assert engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(360)) == []
    assert _alert(db).state == "open"

    resolved = engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(370))
    assert len(resolved) == 1 and resolved[0].state == "resolved"
    assert resolved[0].resolved_reason == "Clear condition met"


def test_clear_delay_zero_resolves_immediately(db):
    _cpu_rule(db, clear_delay=0)
    engine = AlertEngine(db)
    _open_alert(db, engine)

    resolved = engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(310))
    assert len(resolved) == 1 and resolved[0].state == "resolved"
    assert resolved[0].resolved_reason == "Clear condition met (immediate)"


def test_a_breach_interrupts_the_clear_run(db):
    rule_id = _cpu_rule(db)
    engine = AlertEngine(db)
    _open_alert(db, engine)

    engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(310))
    engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(340))
    engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(350))
    assert _state(db, rule_id)["clear_started_at"] is None

    engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(360))
    assert engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(370)) == []
    assert _alert(db).state == "open"

    resolved = engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(420))
    assert len(resolved) == 1 and resolved[0].state == "resolved"


def test_hysteresis_band_sample_resets_both_timers(db):
    rule_id = _cpu_rule(db, clear_threshold=70.0)
    engine = AlertEngine(db)
    _open_alert(db, engine)

    engine.evaluate_metric("cpu_percent", 65.0, _context(), sampled_at=at(310))
    assert _state(db, rule_id)["clear_started_at"] == at(310).isoformat()

    assert engine.evaluate_metric("cpu_percent", 75.0, _context(), sampled_at=at(320)) == []
    state = _state(db, rule_id)
    assert state["clear_started_at"] is None
    assert state["breach_started_at"] is None
    assert _alert(db).state == "open"


# --- message ---

def test_reopen_refreshes_the_message_with_the_new_value(db):
    _cpu_rule(db)
    engine = AlertEngine(db)
    _open_alert(db, engine, value=95.0)
    assert _alert(db).message == "cpu_percent is 95.0 (threshold: >= 80.0)"

    _resolve(db, engine)
    _expire_cooldown(db)
    assert engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=at(310)) == []
    _sustain(engine, 91.0, 320, 620)
    reopened = engine.evaluate_metric("cpu_percent", 91.0, _context(), sampled_at=at(620))

    assert len(reopened) == 1 and reopened[0].state == "open"
    assert reopened[0].message == "cpu_percent is 91.0 (threshold: >= 80.0)"


def test_update_without_a_message_leaves_it_alone(db):
    _cpu_rule(db)
    engine = AlertEngine(db)
    alert = _open_alert(db, engine)

    updated = engine._update_alert(alert, current_value=99.0)

    assert updated.current_value == 99.0
    assert updated.message == "cpu_percent is 95.0 (threshold: >= 80.0)"


# --- state migration ---

def _seed_runtime(db, rule_id, state_json):
    with db.get_session() as session:
        session.add(RuleRuntime(
            dedup_key=f"{rule_id}|host:{HOST_ID}", rule_id=rule_id,
            state_json=state_json, updated_at=datetime.now(timezone.utc),
        ))
        session.commit()


def test_old_window_state_cannot_fire_on_the_first_sample_after_upgrade(db):
    rule_id = _cpu_rule(db, occurrences=1)
    _seed_runtime(db, rule_id, json.dumps({
        "window_start": at(-3600).isoformat(),
        "samples": [{"ts": at(-20).isoformat(), "val": 95.0, "breached": True}],
        "breach_count": 1,
        "breach_started_at": at(-600).isoformat(),
        "clear_started_at": None,
        "last_notified_at": None,
        "last_occurrence_milestone": 0,
    }))
    engine = AlertEngine(db)

    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(0)) == []

    state = _state(db, rule_id)
    assert set(state) == NEW_STATE_KEYS
    assert state["breach_started_at"] == at(0).isoformat()


@pytest.mark.parametrize("state_json", ["null", "[]", "not json"])
def test_unusable_state_json_normalizes_to_defaults(db, state_json):
    rule_id = _cpu_rule(db, occurrences=1)
    _seed_runtime(db, rule_id, state_json)
    engine = AlertEngine(db)

    assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=at(0)) == []
    assert set(_state(db, rule_id)) == NEW_STATE_KEYS


# --- service contract ---

def _service(db, host_stats):
    host = types.SimpleNamespace(id=HOST_ID, name="mediadmz", connection_type="agent",
                                 status="online", url="agent://")
    monitor = types.SimpleNamespace(
        hosts={HOST_ID: host},
        get_last_containers=lambda: [],
        get_containers=AsyncMock(return_value=[]),
    )
    stats_client = types.SimpleNamespace(
        get_host_stats=AsyncMock(return_value=host_stats),
        get_container_stats=AsyncMock(return_value={}),
    )
    service = AlertEvaluationService(db=db, monitor=monitor, stats_client=stats_client)
    service._handle_alert_notification = AsyncMock()
    return service


def _rules_by_metric(db):
    with db.get_session() as session:
        rules = session.query(AlertRuleV2).filter(AlertRuleV2.enabled.is_(True)).all()
        session.expunge_all()
    grouped = {}
    for rule in rules:
        grouped.setdefault(rule.metric, []).append(rule)
    return grouped


async def test_service_passes_the_source_timestamp_to_the_engine(db):
    _cpu_rule(db)
    sampled = datetime.now(timezone.utc) - timedelta(seconds=5)
    service = _service(db, {HOST_ID: {"cpu_percent": 95.0, "last_update": sampled.isoformat()}})
    seen = []
    real = service.engine.evaluate_metric
    service.engine.evaluate_metric = lambda *a, **kw: (seen.append(kw.get("sampled_at")), real(*a, **kw))[1]

    await service._evaluate_host_metrics(_rules_by_metric(db))

    assert seen == [sampled]


async def test_service_notifies_both_the_opened_and_the_resolved_alert(db):
    _cpu_rule(db, active_delay=0, occurrences=None, clear_delay=0)
    stats = {HOST_ID: {"cpu_percent": 95.0, "last_update": datetime.now(timezone.utc).isoformat()}}
    service = _service(db, stats)

    await service._evaluate_host_metrics(_rules_by_metric(db))
    stats[HOST_ID] = {"cpu_percent": 2.5, "last_update": datetime.now(timezone.utc).isoformat()}
    await service._evaluate_host_metrics(_rules_by_metric(db))

    states = [call.args[0].state for call in service._handle_alert_notification.await_args_list]
    assert states == ["open", "resolved"]
