"""Alerts returned by evaluate_metric must stay readable after the engine's
session closes (the evaluation service reads .state on them next), and a
sample under the threshold must not page while the occurrence window fires."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from alerts.engine import AlertEngine, EvaluationContext
from database import AlertRuleV2, AlertV2, RuleRuntime


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


def test_window_keeps_alert_open_but_only_a_breaching_sample_renotifies(db):
    _cpu_rule(db, clear_delay=60, active_delay=300, occurrences=3)
    engine = AlertEngine(db=db)
    for _ in range(2):
        assert engine.evaluate_metric("cpu_percent", 95.0, _context()) == []
    assert len(engine.evaluate_metric("cpu_percent", 95.0, _context())) == 1  # third breach in window

    _expire_cooldown(db)
    # Window still holds the three breaches, but this sample is under threshold: stay open, do not page
    assert engine.evaluate_metric("cpu_percent", 2.5, _context()) == []
    assert _alert_state(db) == "open"

    # A sample that breaches again, past the cooldown, does re-notify
    renotified = engine.evaluate_metric("cpu_percent", 97.0, _context())
    assert len(renotified) == 1 and renotified[0].state == "open"


def test_non_breaching_sample_does_not_reopen_a_resolved_alert(db):
    _cpu_rule(db, clear_delay=60, active_delay=300, occurrences=3)
    engine = AlertEngine(db=db)
    for _ in range(3):
        engine.evaluate_metric("cpu_percent", 95.0, _context())
    with db.get_session() as session:
        engine._resolve_alert(session.query(AlertV2).one(), "manual", notify=False)
    _expire_cooldown(db)

    assert engine.evaluate_metric("cpu_percent", 2.5, _context()) == []
    assert _alert_state(db) == "resolved"

    reopened = engine.evaluate_metric("cpu_percent", 97.0, _context())
    assert len(reopened) == 1 and reopened[0].state == "open"


def test_window_alone_does_not_create_an_alert_from_a_non_breaching_sample(db):
    """A window that already fires (e.g. after lowering occurrences) must wait for a breaching sample."""
    rule_id = _cpu_rule(db, clear_delay=60, active_delay=300, occurrences=5)
    engine = AlertEngine(db=db)
    for _ in range(3):
        assert engine.evaluate_metric("cpu_percent", 95.0, _context()) == []

    with db.get_session() as session:
        session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).one().occurrences = 3
        session.commit()

    assert engine.evaluate_metric("cpu_percent", 2.5, _context()) == []
    with db.get_session() as session:
        assert session.query(AlertV2).count() == 0

    created = engine.evaluate_metric("cpu_percent", 97.0, _context())
    assert len(created) == 1 and created[0].current_value == 97.0
