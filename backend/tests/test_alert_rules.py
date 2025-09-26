"""
Tests for alert rule evaluation and triggering
Covers pattern matching, state/event detection, and cooldown logic
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import re


class TestAlertRuleEvaluation:
    """Test alert rule evaluation logic"""

    def test_container_pattern_matching(self):
        """Test container name pattern matching"""
        from alerts.evaluator import matches_pattern

        # Exact match
        assert matches_pattern("web-app", "web-app") is True

        # Wildcard patterns
        assert matches_pattern("web-app-1", "web-app-*") is True
        assert matches_pattern("prod-web-app", "*-web-app") is True
        assert matches_pattern("web-app", "*") is True

        # Regex patterns
        assert matches_pattern("web-app-123", r"web-app-\d+") is True
        assert matches_pattern("web-app-abc", r"web-app-\d+") is False

        # Multiple patterns
        assert matches_pattern("web-app", "web-app|db-app") is True
        assert matches_pattern("db-app", "web-app|db-app") is True
        assert matches_pattern("cache-app", "web-app|db-app") is False

    def test_state_trigger_evaluation(self):
        """Test state-based trigger evaluation"""
        from alerts.evaluator import should_trigger_on_state

        alert_rule = {
            "trigger_states": ["exited", "dead", "paused"],
            "trigger_events": []
        }

        # Should trigger
        assert should_trigger_on_state("exited", alert_rule) is True
        assert should_trigger_on_state("dead", alert_rule) is True
        assert should_trigger_on_state("paused", alert_rule) is True

        # Should not trigger
        assert should_trigger_on_state("running", alert_rule) is False
        assert should_trigger_on_state("created", alert_rule) is False

    def test_event_trigger_evaluation(self):
        """Test event-based trigger evaluation"""
        from alerts.evaluator import should_trigger_on_event

        alert_rule = {
            "trigger_states": [],
            "trigger_events": ["die", "oom", "kill"]
        }

        # Should trigger
        assert should_trigger_on_event("die", alert_rule) is True
        assert should_trigger_on_event("oom", alert_rule) is True
        assert should_trigger_on_event("kill", alert_rule) is True

        # Should not trigger
        assert should_trigger_on_event("start", alert_rule) is False
        assert should_trigger_on_event("pause", alert_rule) is False

    def test_combined_triggers(self):
        """Test alerts with both state and event triggers"""
        from alerts.evaluator import should_trigger

        alert_rule = {
            "trigger_states": ["exited"],
            "trigger_events": ["die", "oom"]
        }

        # Should trigger on state
        assert should_trigger(state="exited", event=None, alert_rule=alert_rule) is True

        # Should trigger on event
        assert should_trigger(state="running", event="oom", alert_rule=alert_rule) is True

        # Should not trigger
        assert should_trigger(state="running", event="start", alert_rule=alert_rule) is False

    def test_cooldown_period(self):
        """Test alert cooldown period"""
        from alerts.evaluator import AlertCooldownManager

        cooldown_manager = AlertCooldownManager()

        alert_id = 1
        container_id = "container123"
        cooldown_minutes = 5

        # First alert should trigger
        assert cooldown_manager.can_trigger(alert_id, container_id, cooldown_minutes) is True
        cooldown_manager.record_trigger(alert_id, container_id)

        # Immediate second alert should not trigger
        assert cooldown_manager.can_trigger(alert_id, container_id, cooldown_minutes) is False

        # After cooldown period, should trigger again
        cooldown_manager.last_triggered[(alert_id, container_id)] = \
            datetime.utcnow() - timedelta(minutes=6)
        assert cooldown_manager.can_trigger(alert_id, container_id, cooldown_minutes) is True

    def test_host_specific_alerts(self):
        """Test alerts specific to certain hosts"""
        from alerts.evaluator import evaluate_alert

        alert_rule = {
            "container_pattern": "web-app",
            "host_id": "host123",  # Specific host
            "trigger_states": ["exited"]
        }

        container1 = {
            "name": "web-app",
            "host_id": "host123",
            "state": "exited"
        }

        container2 = {
            "name": "web-app",
            "host_id": "host456",  # Different host
            "state": "exited"
        }

        # Should trigger for correct host
        assert evaluate_alert(container1, alert_rule) is True

        # Should not trigger for different host
        assert evaluate_alert(container2, alert_rule) is False

    def test_global_alerts(self):
        """Test alerts that apply to all hosts"""
        from alerts.evaluator import evaluate_alert

        alert_rule = {
            "container_pattern": "*",
            "host_id": None,  # All hosts
            "trigger_states": ["exited"]
        }

        container1 = {
            "name": "any-app",
            "host_id": "host123",
            "state": "exited"
        }

        container2 = {
            "name": "other-app",
            "host_id": "host456",
            "state": "exited"
        }

        # Should trigger for any host
        assert evaluate_alert(container1, alert_rule) is True
        assert evaluate_alert(container2, alert_rule) is True

    def test_health_status_event_trigger(self):
        """Test health status change event triggers"""
        from alerts.evaluator import should_trigger_on_health_event

        alert_rule = {
            "trigger_events": ["health_status:unhealthy"]
        }

        # Should trigger on unhealthy
        event = {
            "type": "health_status",
            "status": "unhealthy"
        }
        assert should_trigger_on_health_event(event, alert_rule) is True

        # Should not trigger on healthy
        event["status"] = "healthy"
        assert should_trigger_on_health_event(event, alert_rule) is False

    def test_exit_code_specific_triggers(self):
        """Test triggers based on specific exit codes"""
        from alerts.evaluator import should_trigger_on_exit_code

        alert_rule = {
            "trigger_events": ["die:137", "die:1"]  # OOM and error
        }

        # Should trigger on specified codes
        assert should_trigger_on_exit_code(137, alert_rule) is True
        assert should_trigger_on_exit_code(1, alert_rule) is True

        # Should not trigger on other codes
        assert should_trigger_on_exit_code(0, alert_rule) is False
        assert should_trigger_on_exit_code(2, alert_rule) is False

    def test_restart_loop_detection(self):
        """Test detection of container restart loops"""
        from alerts.evaluator import detect_restart_loop

        container_id = "container123"
        restart_history = []

        # Add restart events
        for i in range(5):
            restart_history.append({
                "container_id": container_id,
                "event": "restart",
                "timestamp": datetime.utcnow() - timedelta(minutes=i)
            })

        # Should detect restart loop (5 restarts in 5 minutes)
        assert detect_restart_loop(container_id, restart_history, threshold=3, window_minutes=10) is True

        # Older restarts should not count
        old_history = []
        for i in range(5):
            old_history.append({
                "container_id": container_id,
                "event": "restart",
                "timestamp": datetime.utcnow() - timedelta(hours=i)
            })

        assert detect_restart_loop(container_id, old_history, threshold=3, window_minutes=10) is False

    def test_alert_priority_calculation(self):
        """Test alert priority calculation based on severity"""
        from alerts.evaluator import calculate_alert_priority

        # Critical events
        assert calculate_alert_priority(event="oom") == "critical"
        assert calculate_alert_priority(event="die", exit_code=137) == "critical"

        # High priority
        assert calculate_alert_priority(state="dead") == "high"
        assert calculate_alert_priority(event="health_status:unhealthy") == "high"

        # Medium priority
        assert calculate_alert_priority(state="exited", exit_code=1) == "medium"
        assert calculate_alert_priority(event="kill") == "medium"

        # Low priority
        assert calculate_alert_priority(state="paused") == "low"
        assert calculate_alert_priority(event="stop") == "low"

    def test_alert_deduplication(self):
        """Test alert deduplication within time window"""
        from alerts.evaluator import AlertDeduplicator

        deduplicator = AlertDeduplicator()

        alert1 = {
            "alert_id": 1,
            "container_id": "container123",
            "event": "die",
            "timestamp": datetime.utcnow()
        }

        # First alert should not be duplicate
        assert deduplicator.is_duplicate(alert1) is False
        deduplicator.record(alert1)

        # Same alert immediately should be duplicate
        alert2 = alert1.copy()
        alert2["timestamp"] = datetime.utcnow()
        assert deduplicator.is_duplicate(alert2) is True

        # Different container should not be duplicate
        alert3 = alert1.copy()
        alert3["container_id"] = "container456"
        assert deduplicator.is_duplicate(alert3) is False

    def test_alert_grouping(self):
        """Test grouping multiple alerts for batch notification"""
        from alerts.evaluator import group_alerts

        alerts = [
            {"container": "web-1", "host": "host1", "event": "die"},
            {"container": "web-2", "host": "host1", "event": "die"},
            {"container": "web-3", "host": "host1", "event": "die"},
            {"container": "db-1", "host": "host2", "event": "stop"}
        ]

        groups = group_alerts(alerts, by="host")

        # Should group by host
        assert len(groups) == 2
        assert len(groups["host1"]) == 3
        assert len(groups["host2"]) == 1

    def test_alert_suppression_during_maintenance(self):
        """Test alert suppression during maintenance windows"""
        from alerts.evaluator import is_in_maintenance_window

        # Define maintenance window (every day 2-4 AM)
        maintenance_windows = [
            {"start_hour": 2, "end_hour": 4, "days": [0, 1, 2, 3, 4, 5, 6]}
        ]

        # Test time during maintenance
        test_time = datetime.utcnow().replace(hour=3, minute=0)
        assert is_in_maintenance_window(test_time, maintenance_windows) is True

        # Test time outside maintenance
        test_time = datetime.utcnow().replace(hour=10, minute=0)
        assert is_in_maintenance_window(test_time, maintenance_windows) is False

    def test_alert_rule_validation(self):
        """Test alert rule configuration validation"""
        from alerts.evaluator import validate_alert_rule

        # Valid rule
        valid_rule = {
            "name": "Test Alert",
            "container_pattern": "web-*",
            "trigger_states": ["exited"],
            "trigger_events": ["die"],
            "cooldown_minutes": 5,
            "enabled": True
        }
        assert validate_alert_rule(valid_rule) is True

        # Invalid - no triggers
        invalid_rule = {
            "name": "Test Alert",
            "container_pattern": "web-*",
            "trigger_states": [],
            "trigger_events": [],
            "cooldown_minutes": 5,
            "enabled": True
        }
        assert validate_alert_rule(invalid_rule) is False

        # Invalid - bad regex pattern
        invalid_rule2 = {
            "name": "Test Alert",
            "container_pattern": "[invalid(",
            "trigger_states": ["exited"],
            "cooldown_minutes": 5,
            "enabled": True
        }
        assert validate_alert_rule(invalid_rule2) is False