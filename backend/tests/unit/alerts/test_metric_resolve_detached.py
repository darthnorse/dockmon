"""Resolved alerts returned by evaluate_metric must stay readable after the
engine's session closes; the evaluation service reads .state on them next."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import database as database_module
from alerts.engine import AlertEngine, EvaluationContext
from database import AlertRuleV2, DatabaseManager, RuleRuntime


@pytest.fixture
def db(tmp_path):
    database_module._database_manager_instance = None
    db_manager = DatabaseManager(db_path=str(tmp_path / "test.db"))
    try:
        yield db_manager
    finally:
        db_manager.engine.dispose()
        database_module._database_manager_instance = None


def _cpu_rule(db, clear_delay):
    rule_id = str(uuid.uuid4())
    rule = AlertRuleV2(
        id=rule_id, name="Host High CPU", kind="cpu_high", scope="host", severity="warning",
        metric="cpu_percent", operator=">=", threshold=80.0, enabled=True,
        alert_active_delay_seconds=0, alert_clear_delay_seconds=clear_delay,
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


def test_immediately_cleared_alert_is_readable_after_return(db):
    _cpu_rule(db, clear_delay=0)
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
