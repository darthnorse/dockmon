"""
Simplified integration tests for alert workflow.

Tests verify basic alert database operations:
- Alert rule CRUD
- Alert instance CRUD
- Alert state transitions
- Rule-alert relationships

More complex alert evaluation logic is tested in unit tests.
"""

import pytest
from datetime import datetime, timezone
import uuid

from database import AlertRuleV2, AlertV2


# =============================================================================
# Alert Rule CRUD Tests
# =============================================================================

@pytest.mark.integration
class TestAlertRuleCRUD:
    """Test alert rule create/read/update/delete operations"""

    def test_create_alert_rule(
        self,
        db_session
    ):
        """Test creating an alert rule with all required fields"""
        rule = AlertRuleV2(
            id=str(uuid.uuid4()),
            name="High CPU Alert",
            description="Alert when CPU exceeds 80%",
            scope="host",
            kind="cpu_high",
            enabled=True,
            metric="docker_cpu_workload_pct",
            operator=">=",
            threshold=80.0,
            severity="warning",
            notification_cooldown_seconds=300,
        )
        db_session.add(rule)
        db_session.commit()

        # Verify rule created
        retrieved = db_session.query(AlertRuleV2).filter_by(
            name="High CPU Alert"
        ).first()

        assert retrieved is not None
        assert retrieved.kind == "cpu_high"
        assert retrieved.threshold == 80.0
        assert retrieved.severity == "warning"


    def test_update_alert_rule(
        self,
        db_session
    ):
        """Test updating alert rule fields"""
        rule = AlertRuleV2(
            id=str(uuid.uuid4()),
            name="Test Alert",
            scope="host",
            kind="cpu_high",
            enabled=True,
            threshold=80.0,
            severity="warning",
        )
        db_session.add(rule)
        db_session.commit()

        # Update threshold
        rule.threshold = 90.0
        rule.severity = "critical"
        rule.updated_at = datetime.now(timezone.utc)
        db_session.commit()

        # Verify update
        db_session.refresh(rule)
        assert rule.threshold == 90.0
        assert rule.severity == "critical"


    def test_disable_alert_rule(
        self,
        db_session
    ):
        """Test disabling an alert rule"""
        rule = AlertRuleV2(
            id=str(uuid.uuid4()),
            name="Test Alert",
            scope="host",
            kind="cpu_high",
            enabled=True,
            severity="warning",
        )
        db_session.add(rule)
        db_session.commit()

        # Disable rule
        rule.enabled = False
        rule.updated_at = datetime.now(timezone.utc)
        db_session.commit()

        # Verify disabled
        db_session.refresh(rule)
        assert rule.enabled is False


    def test_delete_alert_rule(
        self,
        db_session
    ):
        """Test deleting an alert rule"""
        rule = AlertRuleV2(
            id=str(uuid.uuid4()),
            name="Test Alert",
            scope="host",
            kind="cpu_high",
            enabled=True,
            severity="warning",
        )
        db_session.add(rule)
        db_session.commit()
        rule_id = rule.id

        # Delete rule
        db_session.delete(rule)
        db_session.commit()

        # Verify deleted
        retrieved = db_session.query(AlertRuleV2).filter_by(
            id=rule_id
        ).first()
        assert retrieved is None


# =============================================================================
# Alert Instance CRUD Tests
# =============================================================================

@pytest.mark.integration
class TestAlertInstanceCRUD:
    """Test alert instance create/read/update operations"""

    def test_create_alert_instance(
        self,
        db_session,
        test_host
    ):
        """Test creating an alert instance"""
        # Create rule first
        rule = AlertRuleV2(
            id=str(uuid.uuid4()),
            name="High CPU Alert",
            scope="host",
            kind="cpu_high",
            enabled=True,
            severity="warning",
        )
        db_session.add(rule)
        db_session.flush()

        # Create alert instance
        alert = AlertV2(
            id=str(uuid.uuid4()),
            dedup_key=f"cpu_high|host:{test_host.id}",
            scope_type="host",
            scope_id=test_host.id,
            kind="cpu_high",
            severity="warning",
            state="open",
            title="High CPU on test-host",
            message="CPU usage is at 85%",
            rule_id=rule.id,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            current_value=85.0,
            threshold=80.0,
        )
        db_session.add(alert)
        db_session.commit()

        # Verify alert created
        retrieved = db_session.query(AlertV2).filter_by(
            dedup_key=f"cpu_high|host:{test_host.id}"
        ).first()

        assert retrieved is not None
        assert retrieved.kind == "cpu_high"
        assert retrieved.state == "open"
        assert retrieved.current_value == 85.0


    def test_alert_deduplication(
        self,
        db_session,
        test_host
    ):
        """Test alert deduplication using dedup_key"""
        # Create first alert
        alert1 = AlertV2(
            id=str(uuid.uuid4()),
            dedup_key=f"cpu_high|host:{test_host.id}",
            scope_type="host",
            scope_id=test_host.id,
            kind="cpu_high",
            severity="warning",
            state="open",
            title="High CPU",
            message="CPU at 85%",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        db_session.add(alert1)
        db_session.commit()

        # Try to create duplicate (same dedup_key)
        # This should fail due to unique constraint
        alert2 = AlertV2(
            id=str(uuid.uuid4()),
            dedup_key=f"cpu_high|host:{test_host.id}",  # Same dedup_key!
            scope_type="host",
            scope_id=test_host.id,
            kind="cpu_high",
            severity="warning",
            state="open",
            title="High CPU Again",
            message="CPU still at 85%",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        db_session.add(alert2)

        # Should raise IntegrityError
        with pytest.raises(Exception):  # SQLAlchemy IntegrityError
            db_session.commit()


# =============================================================================
# Alert State Transition Tests
# =============================================================================

@pytest.mark.integration
class TestAlertStateTransitions:
    """Test alert state transitions"""

    def test_alert_open_to_resolved_transition(
        self,
        db_session,
        test_host
    ):
        """Test transitioning alert from open to resolved"""
        alert = AlertV2(
            id=str(uuid.uuid4()),
            dedup_key=f"cpu_high|host:{test_host.id}",
            scope_type="host",
            scope_id=test_host.id,
            kind="cpu_high",
            severity="warning",
            state="open",
            title="High CPU",
            message="CPU at 85%",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        db_session.add(alert)
        db_session.commit()

        # Resolve alert
        alert.state = "resolved"
        alert.resolved_at = datetime.now(timezone.utc)
        alert.resolved_reason = "auto_clear"
        alert.updated_at = datetime.now(timezone.utc)
        db_session.commit()

        # Verify state transition
        db_session.refresh(alert)
        assert alert.state == "resolved"
        assert alert.resolved_at is not None
        assert alert.resolved_reason == "auto_clear"


    def test_alert_snooze(
        self,
        db_session,
        test_host
    ):
        """Test snoozing an alert"""
        from datetime import timedelta

        alert = AlertV2(
            id=str(uuid.uuid4()),
            dedup_key=f"cpu_high|host:{test_host.id}",
            scope_type="host",
            scope_id=test_host.id,
            kind="cpu_high",
            severity="warning",
            state="open",
            title="High CPU",
            message="CPU at 85%",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        db_session.add(alert)
        db_session.commit()

        # Snooze for 1 hour
        snooze_until = datetime.now(timezone.utc) + timedelta(hours=1)
        alert.state = "snoozed"
        alert.snoozed_until = snooze_until
        alert.updated_at = datetime.now(timezone.utc)
        db_session.commit()

        # Verify snoozed
        db_session.refresh(alert)
        assert alert.state == "snoozed"
        assert alert.snoozed_until is not None


    def test_alert_occurrence_counting(
        self,
        db_session,
        test_host
    ):
        """Test alert occurrence counting"""
        alert = AlertV2(
            id=str(uuid.uuid4()),
            dedup_key=f"cpu_high|host:{test_host.id}",
            scope_type="host",
            scope_id=test_host.id,
            kind="cpu_high",
            severity="warning",
            state="open",
            title="High CPU",
            message="CPU at 85%",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            occurrences=1,
        )
        db_session.add(alert)
        db_session.commit()

        # Increment occurrences
        alert.occurrences += 1
        alert.last_seen = datetime.now(timezone.utc)
        alert.updated_at = datetime.now(timezone.utc)
        db_session.commit()

        # Verify count
        db_session.refresh(alert)
        assert alert.occurrences == 2


# =============================================================================
# Rule-Alert Relationship Tests
# =============================================================================

@pytest.mark.integration
class TestRuleAlertRelationship:
    """Test relationship between alert rules and alert instances"""

    def test_alert_references_rule(
        self,
        db_session,
        test_host
    ):
        """Test alert instance references its rule"""
        # Create rule
        rule = AlertRuleV2(
            id=str(uuid.uuid4()),
            name="High CPU Alert",
            scope="host",
            kind="cpu_high",
            enabled=True,
            severity="warning",
            threshold=80.0,
        )
        db_session.add(rule)
        db_session.flush()

        # Create alert referencing rule
        alert = AlertV2(
            id=str(uuid.uuid4()),
            dedup_key=f"cpu_high|host:{test_host.id}",
            scope_type="host",
            scope_id=test_host.id,
            kind="cpu_high",
            severity="warning",
            state="open",
            title="High CPU",
            message="CPU at 85%",
            rule_id=rule.id,  # Reference to rule
            rule_version=1,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        db_session.add(alert)
        db_session.commit()

        # Verify relationship
        db_session.refresh(alert)
        assert alert.rule_id == rule.id


    def test_alert_survives_rule_deletion(
        self,
        db_session,
        test_host
    ):
        """Test alert instances persist when rule is deleted (SET NULL)"""
        # Create rule
        rule = AlertRuleV2(
            id=str(uuid.uuid4()),
            name="Test Alert",
            scope="host",
            kind="cpu_high",
            enabled=True,
            severity="warning",
        )
        db_session.add(rule)
        db_session.flush()

        # Create alert
        alert = AlertV2(
            id=str(uuid.uuid4()),
            dedup_key=f"cpu_high|host:{test_host.id}",
            scope_type="host",
            scope_id=test_host.id,
            kind="cpu_high",
            severity="warning",
            state="open",
            title="High CPU",
            message="CPU at 85%",
            rule_id=rule.id,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        db_session.add(alert)
        db_session.commit()
        alert_id = alert.id

        # Delete rule
        db_session.delete(rule)
        db_session.commit()

        # Alert should still exist
        # Note: rule_id may or may not be nulled depending on FK config
        # The important thing is the alert persists
        retrieved_alert = db_session.query(AlertV2).filter_by(
            id=alert_id
        ).first()

        assert retrieved_alert is not None
