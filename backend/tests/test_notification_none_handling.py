"""
Tests for notification service handling of None trigger fields
Would have caught the "NoneType is not iterable" error
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime
import asyncio


class TestNotificationNoneHandling:
    """Test that notification service properly handles None trigger_states and trigger_events"""

    @pytest.mark.asyncio
    async def test_alert_matching_with_none_trigger_states(self):
        """Test that rules with None trigger_states don't crash"""
        from notifications import NotificationService, AlertEvent
        from database import AlertRuleDB

        # Create a mock database
        mock_db = MagicMock()

        # Create a rule with only trigger_events (no trigger_states)
        mock_rule = MagicMock(spec=AlertRuleDB)
        mock_rule.id = "test-rule"
        mock_rule.name = "Events Only Rule"
        mock_rule.container_pattern = "test-container"
        mock_rule.trigger_events = ["oom", "die"]
        mock_rule.trigger_states = None  # This was causing the crash!
        mock_rule.host_id = None
        mock_rule.notification_channels = [1]
        mock_rule.cooldown_minutes = 15
        mock_rule.enabled = True

        mock_db.get_alert_rules.return_value = [mock_rule]

        # Create notification service
        service = NotificationService(mock_db)

        # Create an alert event for a state change
        event = AlertEvent(
            host_id="host-1",
            container_id="container-1",
            container_name="test-container",
            old_state="running",
            new_state="exited",
            triggered_by="monitor"
        )

        # This should NOT crash even though trigger_states is None
        matching_rules = await service._get_matching_rules(event)

        # Should return empty list since this rule has no state triggers
        assert len(matching_rules) == 0

    @pytest.mark.asyncio
    async def test_alert_matching_with_none_trigger_events(self):
        """Test that rules with None trigger_events work correctly"""
        from notifications import NotificationService, AlertEvent
        from database import AlertRuleDB

        mock_db = MagicMock()

        # Create a rule with only trigger_states (no trigger_events)
        mock_rule = MagicMock(spec=AlertRuleDB)
        mock_rule.id = "test-rule"
        mock_rule.name = "States Only Rule"
        mock_rule.container_pattern = "test-container"
        mock_rule.trigger_events = None  # Only states, no events
        mock_rule.trigger_states = ["exited", "dead"]
        mock_rule.host_id = None
        mock_rule.notification_channels = [1]
        mock_rule.cooldown_minutes = 15
        mock_rule.enabled = True

        mock_db.get_alert_rules.return_value = [mock_rule]

        service = NotificationService(mock_db)

        # Create an alert event for a state change
        event = AlertEvent(
            host_id="host-1",
            container_id="container-1",
            container_name="test-container",
            old_state="running",
            new_state="exited",
            triggered_by="monitor"
        )

        # Should match since state is "exited" and that's in trigger_states
        matching_rules = await service._get_matching_rules(event)

        assert len(matching_rules) == 1
        assert matching_rules[0].id == "test-rule"

    @pytest.mark.asyncio
    async def test_cooldown_check_with_none_trigger_states(self):
        """Test that cooldown checking doesn't crash with None trigger_states"""
        from notifications import NotificationService, AlertEvent
        from database import AlertRuleDB

        mock_db = MagicMock()
        service = NotificationService(mock_db)

        # Rule with None trigger_states
        mock_rule = MagicMock(spec=AlertRuleDB)
        mock_rule.id = "test-rule"
        mock_rule.trigger_states = None  # This was causing issues in _should_send_alert
        mock_rule.trigger_events = ["oom"]
        mock_rule.cooldown_minutes = 15

        event = AlertEvent(
            host_id="host-1",
            container_id="container-1",
            container_name="test-container",
            old_state="running",
            new_state="exited",
            triggered_by="monitor"
        )

        # This should not crash
        should_send = await service._should_send_alert(mock_rule, event)

        # Should return True (no cooldown active)
        assert should_send is True

    @pytest.mark.asyncio
    async def test_mixed_rules_some_with_none_fields(self):
        """Test processing multiple rules where some have None fields"""
        from notifications import NotificationService, AlertEvent
        from database import AlertRuleDB

        mock_db = MagicMock()

        # Mix of rules with different None fields
        rules = [
            # Rule 1: Both triggers
            MagicMock(
                spec=AlertRuleDB,
                id="rule-1",
                container_pattern=".*",
                trigger_states=["exited"],
                trigger_events=["die"],
                host_id=None,
                notification_channels=[1],
                enabled=True
            ),
            # Rule 2: States only (events is None)
            MagicMock(
                spec=AlertRuleDB,
                id="rule-2",
                container_pattern=".*",
                trigger_states=["dead"],
                trigger_events=None,
                host_id=None,
                notification_channels=[1],
                enabled=True
            ),
            # Rule 3: Events only (states is None)
            MagicMock(
                spec=AlertRuleDB,
                id="rule-3",
                container_pattern=".*",
                trigger_states=None,
                trigger_events=["oom"],
                host_id=None,
                notification_channels=[1],
                enabled=True
            ),
        ]

        mock_db.get_alert_rules.return_value = rules
        service = NotificationService(mock_db)

        # Test state change event
        event = AlertEvent(
            host_id="host-1",
            container_id="container-1",
            container_name="test-container",
            old_state="running",
            new_state="dead",
            triggered_by="monitor"
        )

        matching_rules = await service._get_matching_rules(event)

        # Only rule-2 should match (it has "dead" in trigger_states)
        assert len(matching_rules) == 1
        assert matching_rules[0].id == "rule-2"

    def test_in_operator_with_none(self):
        """Test the specific Python error: 'in' operator with None"""

        # This is what was causing the error
        trigger_states = None
        state = "exited"

        # This would raise: TypeError: argument of type 'NoneType' is not iterable
        with pytest.raises(TypeError, match="NoneType.*not iterable"):
            result = state in trigger_states

        # The fix: check for None first
        if trigger_states and state in trigger_states:
            result = True
        else:
            result = False

        assert result is False

    @pytest.mark.asyncio
    async def test_alert_event_processing_with_none_fields(self):
        """Test full alert event processing with None trigger fields"""
        from notifications import NotificationService, AlertEvent

        mock_db = MagicMock()
        mock_db.get_alert_rules.return_value = []
        mock_db.add_container_event = MagicMock()

        service = NotificationService(mock_db)
        service._get_matching_rules = AsyncMock(return_value=[])

        event = AlertEvent(
            host_id="host-1",
            container_id="container-1",
            container_name="test-container",
            old_state="running",
            new_state="exited",
            triggered_by="monitor"
        )

        # Should complete without errors
        result = await service.send_alert(event)

        # Should return False (no matching rules)
        assert result is False

        # Should have logged the event
        mock_db.add_container_event.assert_called_once()

    @pytest.mark.parametrize("trigger_states,trigger_events,new_state,should_match", [
        (["exited"], None, "exited", True),        # States match, events is None
        (None, ["die"], "exited", False),          # States is None, state change doesn't match
        (["exited"], ["die"], "exited", True),     # Both defined, state matches
        (None, None, "exited", False),             # Both None - should not match
        (["running"], None, "exited", False),      # State doesn't match
        ([], ["die"], "exited", False),            # Empty states list
        (["exited", "dead"], None, "dead", True),  # Multiple states, one matches
    ])
    @pytest.mark.asyncio
    async def test_rule_matching_combinations(self, trigger_states, trigger_events, new_state, should_match):
        """Test various combinations of None/empty trigger fields"""
        from notifications import NotificationService, AlertEvent
        from database import AlertRuleDB

        mock_db = MagicMock()

        mock_rule = MagicMock(spec=AlertRuleDB)
        mock_rule.id = "test-rule"
        mock_rule.container_pattern = ".*"
        mock_rule.trigger_states = trigger_states
        mock_rule.trigger_events = trigger_events
        mock_rule.host_id = None
        mock_rule.notification_channels = [1]
        mock_rule.enabled = True

        mock_db.get_alert_rules.return_value = [mock_rule]
        service = NotificationService(mock_db)

        event = AlertEvent(
            host_id="host-1",
            container_id="container-1",
            container_name="test-container",
            old_state="running",
            new_state=new_state,
            triggered_by="monitor"
        )

        matching_rules = await service._get_matching_rules(event)

        if should_match:
            assert len(matching_rules) == 1
            assert matching_rules[0].id == "test-rule"
        else:
            assert len(matching_rules) == 0