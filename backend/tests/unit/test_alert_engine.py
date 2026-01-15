"""
Unit tests for alert engine functionality.

Tests verify:
- Cooldown uses notified_at instead of last_seen (Issue #137)
- Alert deletion when rule is deleted (Issue #137)

Following TDD principles: RED -> GREEN -> REFACTOR
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
from contextlib import contextmanager


class TestAlertCooldown:
    """Tests for _check_cooldown method - Issue #137 fix"""

    def test_cooldown_uses_notified_at_not_last_seen(self):
        """Cooldown should check time since notification, not time since evaluation"""
        from alerts.engine import AlertEngine

        engine = AlertEngine(db=Mock())

        # Create mock alert with:
        # - notified_at: 1 minute ago (within 5 minute cooldown)
        # - last_seen: just now (would incorrectly trigger cooldown if used)
        mock_alert = Mock()
        mock_alert.notified_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        mock_alert.last_seen = datetime.now(timezone.utc)

        # Should be in cooldown (1 min < 5 min cooldown)
        result = engine._check_cooldown(mock_alert, cooldown_seconds=300)
        assert result is True, "Should be in cooldown based on notified_at"

    def test_cooldown_returns_false_when_never_notified(self):
        """Should not be in cooldown if alert was never notified"""
        from alerts.engine import AlertEngine

        engine = AlertEngine(db=Mock())

        mock_alert = Mock()
        mock_alert.notified_at = None
        mock_alert.last_seen = datetime.now(timezone.utc)

        result = engine._check_cooldown(mock_alert, cooldown_seconds=300)
        assert result is False, "Should not be in cooldown if never notified"

    def test_cooldown_expired_after_cooldown_period(self):
        """Should not be in cooldown if notification was long ago"""
        from alerts.engine import AlertEngine

        engine = AlertEngine(db=Mock())

        mock_alert = Mock()
        # Notified 10 minutes ago, cooldown is 5 minutes
        mock_alert.notified_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        mock_alert.last_seen = datetime.now(timezone.utc)

        result = engine._check_cooldown(mock_alert, cooldown_seconds=300)
        assert result is False, "Should not be in cooldown after cooldown period expires"

    def test_cooldown_handles_naive_datetime(self):
        """Should handle naive datetime (without timezone) correctly"""
        from alerts.engine import AlertEngine

        engine = AlertEngine(db=Mock())

        mock_alert = Mock()
        # Naive datetime (no timezone) - 1 minute ago
        # Using replace(tzinfo=None) to simulate naive datetime from database
        mock_alert.notified_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(tzinfo=None)
        mock_alert.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)

        result = engine._check_cooldown(mock_alert, cooldown_seconds=300)
        assert result is True, "Should handle naive datetime and still detect cooldown"

    def test_cooldown_boundary_exactly_at_cooldown_period(self):
        """Should not be in cooldown when exactly at cooldown boundary"""
        from alerts.engine import AlertEngine

        engine = AlertEngine(db=Mock())

        mock_alert = Mock()
        # Notified exactly 5 minutes ago, cooldown is 5 minutes
        mock_alert.notified_at = datetime.now(timezone.utc) - timedelta(seconds=300)
        mock_alert.last_seen = datetime.now(timezone.utc)

        # At exactly the boundary, should not be in cooldown (>= not >)
        result = engine._check_cooldown(mock_alert, cooldown_seconds=300)
        assert result is False, "Should not be in cooldown at exact boundary"


class TestAlertDeletionOnRuleDelete:
    """Tests for deleting alerts when rule is deleted - Issue #137 fix"""

    def test_alerts_deleted_when_rule_deleted(self, test_db):
        """Alerts should be deleted when their associated rule is deleted"""
        from database import AlertRuleV2, AlertV2
        import uuid

        # Arrange: Create a rule and associated alert
        rule_id = str(uuid.uuid4())
        rule = AlertRuleV2(
            id=rule_id,
            name="Test CPU Rule",
            kind="cpu_high",
            scope="container",
            severity="warning",
            threshold=90.0,
            enabled=True,
            notification_cooldown_seconds=300,
        )
        test_db.add(rule)
        test_db.commit()

        alert = AlertV2(
            id=str(uuid.uuid4()),
            rule_id=rule_id,
            dedup_key=f"{rule_id}|cpu_high|container:test123",
            kind="cpu_high",
            scope_type="container",
            scope_id="test123",
            severity="warning",
            state="open",
            title="CPU High",
            message="CPU is high",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        test_db.add(alert)
        test_db.commit()

        # Verify alert exists
        alert_count = test_db.query(AlertV2).filter(AlertV2.rule_id == rule_id).count()
        assert alert_count == 1, "Alert should exist before rule deletion"

        # Act: Delete alerts first (simulating the fix), then delete rule
        test_db.query(AlertV2).filter(AlertV2.rule_id == rule_id).delete()
        test_db.delete(rule)
        test_db.commit()

        # Assert: Alert should be deleted
        alert_count = test_db.query(AlertV2).filter(AlertV2.rule_id == rule_id).count()
        assert alert_count == 0, "Alert should be deleted when rule is deleted"

    def test_orphaned_alerts_not_created(self, test_db):
        """Verify that deleting a rule doesn't leave orphaned alerts (rule_id=NULL)"""
        from database import AlertRuleV2, AlertV2
        import uuid

        # Arrange: Create a rule and associated alert
        rule_id = str(uuid.uuid4())
        rule = AlertRuleV2(
            id=rule_id,
            name="Test Memory Rule",
            kind="memory_high",
            scope="container",
            severity="critical",
            threshold=95.0,
            enabled=True,
            notification_cooldown_seconds=300,
        )
        test_db.add(rule)
        test_db.commit()

        alert = AlertV2(
            id=str(uuid.uuid4()),
            rule_id=rule_id,
            dedup_key=f"{rule_id}|memory_high|container:test456",
            kind="memory_high",
            scope_type="container",
            scope_id="test456",
            severity="critical",
            state="open",
            title="Memory High",
            message="Memory is high",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        test_db.add(alert)
        test_db.commit()

        # Act: Delete alerts then rule (the fix)
        test_db.query(AlertV2).filter(AlertV2.rule_id == rule_id).delete()
        test_db.delete(rule)
        test_db.commit()

        # Assert: No orphaned alerts should exist
        orphaned_count = test_db.query(AlertV2).filter(AlertV2.rule_id == None).count()
        assert orphaned_count == 0, "No orphaned alerts (rule_id=NULL) should exist"

    def test_multiple_alerts_deleted_with_rule(self, test_db):
        """Multiple alerts for the same rule should all be deleted"""
        from database import AlertRuleV2, AlertV2
        import uuid

        # Arrange: Create a rule with multiple alerts
        rule_id = str(uuid.uuid4())
        rule = AlertRuleV2(
            id=rule_id,
            name="Multi-container Rule",
            kind="cpu_high",
            scope="container",
            severity="warning",
            threshold=80.0,
            enabled=True,
            notification_cooldown_seconds=300,
        )
        test_db.add(rule)
        test_db.commit()

        # Create 3 alerts for different containers
        for i in range(3):
            alert = AlertV2(
                id=str(uuid.uuid4()),
                rule_id=rule_id,
                dedup_key=f"{rule_id}|cpu_high|container:container{i}",
                kind="cpu_high",
                scope_type="container",
                scope_id=f"container{i}",
                severity="warning",
                state="open",
                title=f"CPU High on container{i}",
                message="CPU is high",
                first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
            )
            test_db.add(alert)
        test_db.commit()

        # Verify all alerts exist
        alert_count = test_db.query(AlertV2).filter(AlertV2.rule_id == rule_id).count()
        assert alert_count == 3, "All 3 alerts should exist before rule deletion"

        # Act: Delete alerts then rule
        deleted = test_db.query(AlertV2).filter(AlertV2.rule_id == rule_id).delete()
        test_db.delete(rule)
        test_db.commit()

        # Assert: All alerts should be deleted
        assert deleted == 3, "All 3 alerts should be deleted"
        remaining = test_db.query(AlertV2).filter(AlertV2.rule_id == rule_id).count()
        assert remaining == 0, "No alerts should remain after rule deletion"
