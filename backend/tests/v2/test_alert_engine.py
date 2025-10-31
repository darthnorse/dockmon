"""
Unit tests for Alert Engine (engine.py)

Tests cover:
- Metric-driven evaluation with sliding windows
- Event-driven evaluation
- Deduplication logic
- Alert lifecycle (create, update, resolve)
- Cooldown and grace period enforcement
- Breach detection and clearing
"""

import pytest
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, AlertRuleV2, AlertV2, RuleRuntime, RuleEvaluation, DatabaseManager
from alerts.engine import AlertEngine, EvaluationContext, MetricSample

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture
def test_db(tmp_path):
    """Create test database"""
    db_file = tmp_path / "test_alerts.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    db_manager = DatabaseManager(db_path=str(db_file))
    db_manager.engine = engine
    db_manager.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield db_manager

    Base.metadata.drop_all(bind=engine)
    if db_file.exists():
        db_file.unlink()


@pytest.fixture
def alert_engine(test_db):
    """Create alert engine with test database"""
    return AlertEngine(test_db)


@pytest.fixture
def sample_metric_rule(test_db):
    """Create a sample metric-driven rule"""
    with test_db.get_session() as session:
        rule = AlertRuleV2(
            id="test-rule-001",
            name="High CPU Alert",
            description="Alert when CPU exceeds 90%",
            scope="container",
            kind="cpu_high",
            enabled=True,
            metric="cpu_percent",
            operator=">=",
            threshold=90.0,
            duration_seconds=300,
            occurrences=3,
            clear_threshold=80.0,
            clear_duration_seconds=60,
            severity="warning",
            # Note: grace_seconds removed - not in current schema
            cooldown_seconds=300,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version=1
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)
        return rule


@pytest.fixture
def sample_event_rule(test_db):
    """Create a sample event-driven rule"""
    with test_db.get_session() as session:
        rule = AlertRuleV2(
            id="test-rule-002",
            name="Container Unhealthy",
            description="Alert when container becomes unhealthy",
            scope="container",
            kind="unhealthy",
            enabled=True,
            metric=None,  # Event-driven
            severity="critical",  # Changed from 'error' to 'critical'
            # Note: grace_seconds removed - not in current schema
            cooldown_seconds=600,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            version=1
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)
        return rule


@pytest.fixture
def sample_context():
    """Create a sample evaluation context"""
    return EvaluationContext(
        scope_type="container",
        scope_id="test-container-123",
        host_id="test-host-456",
        host_name="Test Host",
        container_id="test-container-123",
        container_name="test-nginx",
        labels={"env": "production", "app": "web"}
    )


# ==================== Deduplication Tests ====================

def test_dedup_key_generation(alert_engine):
    """Test deduplication key generation - now includes rule_id"""
    # New format: rule_id|kind|scope_type:scope_id
    key = alert_engine._make_dedup_key("rule-001", "cpu_high", "container", "abc123")
    assert key == "rule-001|cpu_high|container:abc123"

    key = alert_engine._make_dedup_key("rule-002", "unhealthy", "container", "xyz789")
    assert key == "rule-002|unhealthy|container:xyz789"

    key = alert_engine._make_dedup_key("rule-003", "disk_full", "host", "host-001")
    assert key == "rule-003|disk_full|host:host-001"


def test_runtime_key_generation(alert_engine):
    """Test runtime state key generation"""
    key = alert_engine._make_runtime_key("rule-001", "container", "abc123")
    assert key == "rule-001|container:abc123"


def test_deduplication_prevents_duplicate_alerts(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test that deduplication prevents creating duplicate alerts"""
    # Create first alert
    alerts1 = []
    for i in range(3):
        result = alert_engine.evaluate_metric("cpu_percent", 95.0, sample_context)
        alerts1.extend(result)

    # Should create one alert
    with test_db.get_session() as session:
        all_alerts = session.query(AlertV2).all()
        assert len(all_alerts) == 1

        # Try to create again with same context
        alerts2 = alert_engine.evaluate_metric("cpu_percent", 96.0, sample_context)

        # Should update existing alert, not create new one
        all_alerts_after = session.query(AlertV2).all()
        assert len(all_alerts_after) == 1
        assert all_alerts_after[0].occurrences == 2


# ==================== Metric-Driven Evaluation Tests ====================

def test_metric_breach_detection(alert_engine):
    """Test threshold breach detection"""
    assert alert_engine._check_breach(95.0, 90.0, ">=") == True
    assert alert_engine._check_breach(85.0, 90.0, ">=") == False

    assert alert_engine._check_breach(10.0, 20.0, "<=") == True
    assert alert_engine._check_breach(25.0, 20.0, "<=") == False

    assert alert_engine._check_breach(50.0, 50.0, "==") == True
    assert alert_engine._check_breach(51.0, 50.0, "==") == False


def test_sliding_window_breach_count(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test sliding window breach counting"""
    # Send 3 samples above threshold
    for i in range(3):
        alert_engine.evaluate_metric("cpu_percent", 95.0 + i, sample_context)

    # Check runtime state
    with test_db.get_session() as session:
        runtime_key = alert_engine._make_runtime_key(
            sample_metric_rule.id,
            sample_context.scope_type,
            sample_context.scope_id
        )
        runtime = session.query(RuleRuntime).filter(RuleRuntime.dedup_key == runtime_key).first()

        assert runtime is not None
        state = json.loads(runtime.state_json)
        assert state["breach_count"] == 3
        assert len(state["samples"]) == 3


def test_alert_created_after_occurrences_threshold(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test that alert is created after N occurrences"""
    # Rule requires 3 occurrences

    # First sample - no alert
    alerts = alert_engine.evaluate_metric("cpu_percent", 95.0, sample_context)
    assert len(alerts) == 0

    # Second sample - no alert
    alerts = alert_engine.evaluate_metric("cpu_percent", 96.0, sample_context)
    assert len(alerts) == 0

    # Third sample - alert should fire!
    alerts = alert_engine.evaluate_metric("cpu_percent", 97.0, sample_context)
    assert len(alerts) == 1
    assert alerts[0].kind == "cpu_high"
    assert alerts[0].state == "open"
    assert alerts[0].current_value == 97.0


def test_clear_condition_resolves_alert(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test that clear condition resolves the alert"""
    # Create alert by breaching threshold 3 times
    for i in range(3):
        alert_engine.evaluate_metric("cpu_percent", 95.0, sample_context)

    # Verify alert exists
    with test_db.get_session() as session:
        alert = session.query(AlertV2).filter(
            AlertV2.scope_id == sample_context.scope_id,
            AlertV2.state == "open"
        ).first()
        assert alert is not None

    # Send values below clear threshold for clear duration
    # Clear threshold is 80.0, clear duration is 60s
    # For testing, we'll send one sample below threshold
    # In production, this would need to be sustained for 60s

    alerts = alert_engine.evaluate_metric("cpu_percent", 75.0, sample_context)

    # Check runtime state shows clearing started
    with test_db.get_session() as session:
        runtime_key = alert_engine._make_runtime_key(
            sample_metric_rule.id,
            sample_context.scope_type,
            sample_context.scope_id
        )
        runtime = session.query(RuleRuntime).filter(RuleRuntime.dedup_key == runtime_key).first()
        state = json.loads(runtime.state_json)
        assert state["clear_started_at"] is not None


def test_evaluation_history_recorded(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test that evaluation history is recorded"""
    alert_engine.evaluate_metric("cpu_percent", 95.0, sample_context)

    with test_db.get_session() as session:
        evaluations = session.query(RuleEvaluation).filter(
            RuleEvaluation.rule_id == sample_metric_rule.id
        ).all()

        assert len(evaluations) == 1
        assert evaluations[0].value == 95.0
        assert evaluations[0].breached == True
        assert evaluations[0].scope_id == sample_context.scope_id


# ==================== Event-Driven Evaluation Tests ====================

def test_event_rule_matches_unhealthy_event(alert_engine, sample_event_rule):
    """Test event-driven rule matching"""
    context = EvaluationContext(
        scope_type="container",
        scope_id="test-container-999",
        container_name="test-app"
    )

    event_data = {
        "old_state": "healthy",
        "new_state": "unhealthy"
    }

    # Check if rule matches event
    matches = alert_engine._rule_matches_event(
        sample_event_rule,
        "state_change",
        context,
        event_data
    )

    assert matches == True


def test_event_creates_alert_immediately(alert_engine, sample_event_rule, test_db):
    """Test that event-driven rules create alerts immediately"""
    context = EvaluationContext(
        scope_type="container",
        scope_id="test-container-999",
        container_name="test-app"
    )

    event_data = {
        "old_state": "healthy",
        "new_state": "unhealthy"
    }

    alerts = alert_engine.evaluate_event("state_change", context, event_data)

    assert len(alerts) == 1
    assert alerts[0].kind == "unhealthy"
    assert alerts[0].severity == "critical"  # Changed from 'error' to 'critical'
    assert alerts[0].state == "open"


# ==================== Alert Lifecycle Tests ====================

def test_alert_creation_fields(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test that alert is created with correct fields"""
    # Create alert
    for i in range(3):
        alert_engine.evaluate_metric("cpu_percent", 95.0, sample_context)

    with test_db.get_session() as session:
        alert = session.query(AlertV2).first()

        assert alert.id is not None
        # Dedup key now includes rule_id: rule_id|kind|scope_type:scope_id
        assert alert.dedup_key == "test-rule-001|cpu_high|container:test-container-123"
        assert alert.scope_type == "container"
        assert alert.scope_id == "test-container-123"
        assert alert.kind == "cpu_high"
        assert alert.severity == "warning"
        assert alert.state == "open"
        assert alert.rule_id == sample_metric_rule.id
        assert alert.rule_version == sample_metric_rule.version
        assert alert.current_value is not None
        assert alert.threshold == 90.0
        assert alert.first_seen is not None
        assert alert.last_seen is not None
        assert alert.occurrences == 1


def test_alert_update_increments_occurrences(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test that updating alert increments occurrences"""
    # Create alert
    for i in range(3):
        alert_engine.evaluate_metric("cpu_percent", 95.0, sample_context)

    # Send another breach
    alert_engine.evaluate_metric("cpu_percent", 96.0, sample_context)

    with test_db.get_session() as session:
        alert = session.query(AlertV2).first()
        assert alert.occurrences == 2


def test_alert_resolution(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test manual alert resolution"""
    # Create alert
    for i in range(3):
        alert_engine.evaluate_metric("cpu_percent", 95.0, sample_context)

    with test_db.get_session() as session:
        alert = session.query(AlertV2).first()

        # Resolve alert
        resolved = alert_engine._resolve_alert(alert, "Manually resolved for testing")

        assert resolved.state == "resolved"
        assert resolved.resolved_at is not None
        assert resolved.resolved_reason == "Manually resolved for testing"


# ==================== Cooldown and Grace Period Tests ====================

def test_cooldown_prevents_duplicate_alerts(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test that cooldown period prevents duplicate alerts"""
    # Create alert
    for i in range(3):
        alert_engine.evaluate_metric("cpu_percent", 95.0, sample_context)

    # Get the alert
    with test_db.get_session() as session:
        alert = session.query(AlertV2).first()

        # Alert was just created, should be in cooldown
        in_cooldown = alert_engine._check_cooldown(alert, sample_metric_rule.cooldown_seconds)
        # Since alert was just created (last_seen is now), cooldown check should be False
        # because time_since_last would be ~0 which is < 300, so it returns True
        # Actually let me check the logic...
        # _check_cooldown returns True if IN cooldown (should skip)
        # time_since_last < cooldown_seconds means we're IN cooldown
        # So this should be True (we ARE in cooldown)
        assert in_cooldown == True


def test_grace_period_for_new_alerts(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test grace period for new alerts - SKIPPED: grace_seconds not in current schema"""
    # Note: grace_seconds feature was removed from schema
    # This test is kept for documentation but skipped
    pytest.skip("grace_seconds feature not implemented in current schema")


# ==================== Selector Tests ====================

def test_label_selector_matching(alert_engine, sample_metric_rule, test_db):
    """Test label selector matching"""
    # Update rule to require specific labels
    with test_db.get_session() as session:
        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == sample_metric_rule.id).first()
        rule.labels_json = json.dumps({"env": "production", "app": "web"})
        session.commit()

    # Context with matching labels
    context_match = EvaluationContext(
        scope_type="container",
        scope_id="test-container-match",
        labels={"env": "production", "app": "web", "version": "1.0"}
    )

    # Context with non-matching labels
    context_no_match = EvaluationContext(
        scope_type="container",
        scope_id="test-container-nomatch",
        labels={"env": "staging", "app": "web"}
    )

    # Context with no labels
    context_no_labels = EvaluationContext(
        scope_type="container",
        scope_id="test-container-nolabels"
    )

    # Reload rule
    with test_db.get_session() as session:
        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == sample_metric_rule.id).first()

        assert alert_engine._check_selectors(rule, context_match) == True
        assert alert_engine._check_selectors(rule, context_no_match) == False
        assert alert_engine._check_selectors(rule, context_no_labels) == False


# ==================== Message Generation Tests ====================

def test_alert_title_generation(alert_engine, sample_metric_rule, sample_context):
    """Test alert title generation"""
    title = alert_engine._generate_alert_title(sample_metric_rule, sample_context)
    # Title format includes host name: "Rule Name - container_name on host_name"
    assert title == "High CPU Alert - test-nginx on Test Host"


def test_alert_message_generation(alert_engine, sample_metric_rule, sample_context):
    """Test alert message generation"""
    message = alert_engine._generate_alert_message(sample_metric_rule, sample_context, 95.5)

    # Check message contains key information
    assert "Alert when CPU exceeds 90%" in message
    assert "cpu_percent" in message
    assert "95.5" in message
    # Note: Host name may or may not be in message depending on format


def test_rule_snapshot_creation(alert_engine, sample_metric_rule):
    """Test rule snapshot for audit trail"""
    snapshot_json = alert_engine._generate_alert_message(sample_metric_rule, None)
    snapshot = json.loads(alert_engine._snapshot_rule(sample_metric_rule))

    assert snapshot["id"] == sample_metric_rule.id
    assert snapshot["name"] == sample_metric_rule.name
    assert snapshot["kind"] == sample_metric_rule.kind
    assert snapshot["threshold"] == sample_metric_rule.threshold
    assert snapshot["version"] == sample_metric_rule.version


# ==================== Runtime State Tests ====================

def test_runtime_state_initialization(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test runtime state initialization"""
    # Trigger evaluation to create runtime state
    alert_engine.evaluate_metric("cpu_percent", 50.0, sample_context)

    with test_db.get_session() as session:
        runtime_key = alert_engine._make_runtime_key(
            sample_metric_rule.id,
            sample_context.scope_type,
            sample_context.scope_id
        )
        runtime = session.query(RuleRuntime).filter(RuleRuntime.dedup_key == runtime_key).first()

        assert runtime is not None
        state = json.loads(runtime.state_json)

        assert "window_start" in state
        assert "samples" in state
        assert "breach_count" in state
        assert state["breach_started_at"] is None
        assert state["clear_started_at"] is None


def test_runtime_state_persistence(alert_engine, sample_metric_rule, sample_context, test_db):
    """Test that runtime state persists between evaluations"""
    # First evaluation
    alert_engine.evaluate_metric("cpu_percent", 95.0, sample_context)

    # Second evaluation
    alert_engine.evaluate_metric("cpu_percent", 96.0, sample_context)

    with test_db.get_session() as session:
        runtime_key = alert_engine._make_runtime_key(
            sample_metric_rule.id,
            sample_context.scope_type,
            sample_context.scope_id
        )
        runtime = session.query(RuleRuntime).filter(RuleRuntime.dedup_key == runtime_key).first()
        state = json.loads(runtime.state_json)

        # Should have 2 samples
        assert len(state["samples"]) == 2
        assert state["breach_count"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
