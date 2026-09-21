"""Alerts returned by evaluate_metric must stay readable after the engine's
session closes (the evaluation service reads .state on them next), and a
sample under the threshold must never page, create or reopen an alert."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from alerts.engine import AlertEngine, EvaluationContext
from database import AlertRuleV2, AlertV2, RuleRuntime

T0 = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _cpu_rule(db, clear_delay=0, active_delay=0, occurrences=None):
    rule_id = str(uuid.uuid4())
    rule = AlertRuleV2(
        id=rule_id, name="Host High CPU", kind="cpu_high", scope="host", severity="warning",
        metric="cpu_percent", operator=">=", threshold=80.0, enabled=True, occurrences=occurrences,
        alert_active_delay_seconds=active_delay, alert_clear_delay_seconds=clear_delay,
        notification_cooldown_seconds=300, host_selector_json=json.dumps({"include_all": True}),
    )
    with db.get_session() as session:
        session.add(rule)
        session.commit()
    return rule_id


def _context():
    return EvaluationContext(scope_type="host", scope_id="h1", host_id="h1", host_name="mediadmz")


def _open_alert(engine):
    alerts = engine.evaluate_metric("cpu_percent", 95.0, _context())
    assert len(alerts) == 1 and alerts[0].state == "open"


def _expire_cooldown(db):
    with db.get_session() as session:
        alert = session.query(AlertV2).one()
        alert.notified_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        session.commit()


def _alert_state(db):
    with db.get_session() as session:
        return session.query(AlertV2).one().state


def test_immediately_cleared_alert_is_readable_after_return(db):
    _cpu_rule(db)
    engine = AlertEngine(db=db)
    _open_alert(engine)

    resolved = engine.evaluate_metric("cpu_percent", 2.5, _context())

    assert len(resolved) == 1
    assert resolved[0].state == "resolved"
    assert resolved[0].resolved_reason == "Clear condition met (immediate)"


def test_sustained_clear_alert_is_readable_after_return(db):
    rule_id = _cpu_rule(db, clear_delay=60)
    engine = AlertEngine(db=db)
    _open_alert(engine)
    engine.evaluate_metric("cpu_percent", 2.5, _context())  # starts the clear timer

    with db.get_session() as session:
        runtime = session.query(RuleRuntime).filter(RuleRuntime.dedup_key.like(f"{rule_id}%")).one()
        state = json.loads(runtime.state_json)
        state["clear_started_at"] = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        runtime.state_json = json.dumps(state)
        session.commit()

    resolved = engine.evaluate_metric("cpu_percent", 2.5, _context())

    assert len(resolved) == 1
    assert resolved[0].state == "resolved"
    assert resolved[0].resolved_reason == "Clear condition met"


def _sustained_breach(engine, value=95.0, seconds=300):
    """Hold `value` for `seconds` at 10 s spacing; the last sample is the one that fires."""
    alerts = []
    for s in range(0, seconds + 1, 10):
        alerts = engine.evaluate_metric("cpu_percent", value, _context(), sampled_at=T0 + timedelta(seconds=s))
    return alerts


def test_open_alert_renotifies_only_on_a_breaching_sample(db):
    _cpu_rule(db, clear_delay=60, active_delay=300, occurrences=3)
    engine = AlertEngine(db)
    assert len(_sustained_breach(engine)) == 1

    _expire_cooldown(db)
    # Under threshold: stays open (clear delay not reached), does not page
    assert engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=T0 + timedelta(seconds=310)) == []
    assert _alert_state(db) == "open"

    # A breach past the cooldown re-notifies, but only once it is sustained again
    for s in range(320, 620, 10):
        assert engine.evaluate_metric("cpu_percent", 97.0, _context(), sampled_at=T0 + timedelta(seconds=s)) == []
    renotified = engine.evaluate_metric("cpu_percent", 97.0, _context(), sampled_at=T0 + timedelta(seconds=620))
    assert len(renotified) == 1 and renotified[0].state == "open"


def test_non_breaching_sample_does_not_reopen_a_resolved_alert(db):
    _cpu_rule(db, clear_delay=60, active_delay=300, occurrences=3)
    engine = AlertEngine(db)
    _sustained_breach(engine)
    with db.get_session() as session:
        engine._resolve_alert(session.query(AlertV2).one(), "manual", notify=False)
    _expire_cooldown(db)

    assert engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=T0 + timedelta(seconds=310)) == []
    assert _alert_state(db) == "resolved"

    for s in range(320, 620, 10):
        engine.evaluate_metric("cpu_percent", 97.0, _context(), sampled_at=T0 + timedelta(seconds=s))
    reopened = engine.evaluate_metric("cpu_percent", 97.0, _context(), sampled_at=T0 + timedelta(seconds=620))
    assert len(reopened) == 1 and reopened[0].state == "open"


def test_lowering_occurrences_mid_run_still_waits_for_a_breaching_sample(db):
    """A run that already satisfies the rule after an edit must wait for a breaching sample."""
    rule_id = _cpu_rule(db, clear_delay=60, active_delay=0, occurrences=5)
    engine = AlertEngine(db)
    for s in range(0, 30, 10):
        assert engine.evaluate_metric("cpu_percent", 95.0, _context(), sampled_at=T0 + timedelta(seconds=s)) == []

    with db.get_session() as session:
        session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).one().occurrences = 3
        session.commit()

    assert engine.evaluate_metric("cpu_percent", 2.5, _context(), sampled_at=T0 + timedelta(seconds=30)) == []
    with db.get_session() as session:
        assert session.query(AlertV2).count() == 0

    for s in range(40, 60, 10):
        assert engine.evaluate_metric("cpu_percent", 97.0, _context(), sampled_at=T0 + timedelta(seconds=s)) == []
    created = engine.evaluate_metric("cpu_percent", 97.0, _context(), sampled_at=T0 + timedelta(seconds=60))
    assert len(created) == 1 and created[0].current_value == 97.0
