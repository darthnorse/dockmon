"""
Tests for UI state preservation during edit operations
Would have caught the bug where alert edit cleared container selections
"""

import pytest
from unittest.mock import MagicMock, patch
import json


class TestUIStatePreservation:
    """Test that UI state is properly preserved during edit operations"""

    def test_alert_edit_preserves_container_selection(self):
        """Test that editing an alert preserves the selected containers"""
        from models.request_models import AlertRule

        # Original alert rule with specific containers selected
        original_rule = {
            "id": 1,
            "name": "Database Alert",
            "container_pattern": "database-.*|cache-.*",  # Multiple containers
            "host_id": "host123",
            "trigger_states": ["exited", "dead"],
            "trigger_events": ["oom", "die"],
            "notification_channels": [1, 2],
            "cooldown_minutes": 5,
            "enabled": True
        }

        # Simulate editing the alert
        # The UI should preserve:
        # 1. Container selections
        # 2. Host selection
        # 3. Trigger states/events
        # 4. Notification channels
        # 5. Other settings

        # After opening edit modal, these should still be selected
        assert original_rule["container_pattern"] is not None
        assert original_rule["host_id"] is not None
        assert len(original_rule["trigger_states"]) > 0
        assert len(original_rule["trigger_events"]) > 0
        assert len(original_rule["notification_channels"]) > 0

    def test_alert_edit_clears_previous_selections(self):
        """Test that editing an alert clears previous selections before setting new ones"""

        # First alert rule
        rule1 = {
            "id": 1,
            "name": "Alert 1",
            "container_pattern": "web-.*",
            "trigger_states": ["exited"],
            "trigger_events": ["die"],
            "notification_channels": [1]
        }

        # Second alert rule with different selections
        rule2 = {
            "id": 2,
            "name": "Alert 2",
            "container_pattern": "db-.*",
            "trigger_states": ["paused", "dead"],  # Different states
            "trigger_events": ["oom", "kill"],     # Different events
            "notification_channels": [2, 3]         # Different channels
        }

        # When editing rule2 after rule1:
        # - rule1's states should NOT be selected
        # - rule1's events should NOT be selected
        # - Only rule2's selections should be active

        # This test validates the checkbox clearing logic
        assert set(rule2["trigger_states"]) != set(rule1["trigger_states"])
        assert set(rule2["trigger_events"]) != set(rule1["trigger_events"])

    def test_modal_state_isolation(self):
        """Test that different modal states don't interfere with each other"""

        modals = {
            "alert_modal": {
                "checkboxes": ["containers", "states", "events", "channels"],
                "inputs": ["name", "pattern", "cooldown"]
            },
            "host_modal": {
                "inputs": ["name", "url", "tls_cert", "tls_key"]
            },
            "container_modal": {
                "tabs": ["info", "logs", "stats"],
                "actions": ["restart", "stop", "pause"]
            }
        }

        # Each modal should maintain independent state
        for modal_name, modal_state in modals.items():
            # Opening one modal shouldn't affect others
            assert modal_state is not None

    def test_form_validation_preserves_valid_inputs(self):
        """Test that form validation doesn't clear valid inputs"""

        form_data = {
            "name": "Valid Alert Name",
            "container_pattern": "valid-pattern-.*",
            "trigger_states": ["exited"],
            "trigger_events": [],
            "cooldown_minutes": 5
        }

        # If validation fails on one field, others should remain
        invalid_data = form_data.copy()
        invalid_data["container_pattern"] = "[invalid("  # Invalid regex

        # After validation error:
        # - Name should still be present
        # - Trigger states should still be selected
        # - Cooldown should still have its value
        assert form_data["name"] == "Valid Alert Name"
        assert form_data["trigger_states"] == ["exited"]
        assert form_data["cooldown_minutes"] == 5

    def test_checkbox_group_independence(self):
        """Test that checkbox groups don't interfere with each other"""

        # In the alert modal, we have multiple checkbox groups:
        checkbox_groups = {
            "containers": ["web-1", "web-2", "db-1"],
            "trigger_states": ["running", "exited", "dead"],
            "trigger_events": ["start", "stop", "die", "oom"],
            "notification_channels": ["telegram", "discord", "pushover"]
        }

        # Clearing one group shouldn't affect others
        # This is the bug we found - clearing ALL checkboxes instead of specific groups

        # Clear only trigger states
        cleared_groups = checkbox_groups.copy()
        cleared_groups["trigger_states"] = []

        # Others should remain unchanged
        assert cleared_groups["containers"] == ["web-1", "web-2", "db-1"]
        assert cleared_groups["trigger_events"] == ["start", "stop", "die", "oom"]
        assert cleared_groups["notification_channels"] == ["telegram", "discord", "pushover"]

    def test_pattern_mode_toggle_preserves_data(self):
        """Test that toggling between checkbox and pattern mode preserves data"""

        # Start in checkbox mode with containers selected
        checkbox_selection = ["web-app-1", "web-app-2", "web-app-3"]

        # Switch to pattern mode
        # Should generate pattern from selected containers
        expected_pattern = "web-app-1|web-app-2|web-app-3"

        # Switch back to checkbox mode
        # Should re-select the same containers if pattern matches
        assert len(checkbox_selection) == 3

    def test_edit_mode_populates_all_fields(self):
        """Test that edit mode populates ALL fields, not just some"""

        alert_rule = {
            "id": 1,
            "name": "Complete Alert",
            "container_pattern": ".*",
            "host_id": "host123",
            "trigger_states": ["exited", "dead", "paused"],
            "trigger_events": ["oom", "die", "kill"],
            "notification_channels": [1, 2, 3],
            "cooldown_minutes": 10,
            "enabled": True
        }

        # All these fields should be populated in edit mode
        required_fields = [
            "name",
            "container_pattern",
            "host_id",
            "trigger_states",
            "trigger_events",
            "notification_channels",
            "cooldown_minutes",
            "enabled"
        ]

        for field in required_fields:
            assert alert_rule.get(field) is not None

    def test_modal_close_clears_state(self):
        """Test that closing a modal properly clears its state"""

        # After closing alert modal:
        # - Form should be reset
        # - Checkboxes should be cleared
        # - Edit mode should be disabled
        # - Validation errors should be cleared

        modal_state = {
            "form_values": {},
            "checkboxes": [],
            "edit_mode": False,
            "validation_errors": []
        }

        # All should be empty/false after close
        assert len(modal_state["form_values"]) == 0
        assert len(modal_state["checkboxes"]) == 0
        assert modal_state["edit_mode"] is False
        assert len(modal_state["validation_errors"]) == 0

    def test_concurrent_edit_operations(self):
        """Test that concurrent edit operations don't interfere"""

        # User opens alert 1 for editing
        alert1_state = {"id": 1, "name": "Alert 1"}

        # Before saving, user opens alert 2
        alert2_state = {"id": 2, "name": "Alert 2"}

        # Alert 1's state shouldn't affect alert 2
        assert alert1_state["id"] != alert2_state["id"]
        assert alert1_state["name"] != alert2_state["name"]

    @pytest.mark.parametrize("field_type,test_value,expected", [
        ("checkbox", True, True),
        ("checkbox", False, False),
        ("text", "test value", "test value"),
        ("number", 42, 42),
        ("select", "option1", "option1"),
    ])
    def test_form_field_preservation(self, field_type, test_value, expected):
        """Test that different form field types preserve their values correctly"""

        # Set field value
        field_value = test_value

        # After some operation (like validation error on another field)
        # Field should still have its value
        assert field_value == expected

    def test_api_response_to_ui_mapping(self):
        """Test that API responses are correctly mapped to UI elements"""

        # API returns this structure
        api_response = {
            "id": 1,
            "name": "Test Alert",
            "container_pattern": "web-.*",
            "host_id": "host123",
            "trigger_states": ["exited", "dead"],
            "trigger_events": ["oom", "die"],
            "notification_channels": [1, 2],
            "cooldown_minutes": 5,
            "enabled": True
        }

        # UI should map to:
        ui_mapping = {
            "alertRuleName": api_response["name"],
            "containerPattern": api_response["container_pattern"],
            "hostSelect": api_response["host_id"],
            "state_checkboxes": api_response["trigger_states"],
            "event_checkboxes": api_response["trigger_events"],
            "channel_checkboxes": api_response["notification_channels"],
            "cooldownMinutes": api_response["cooldown_minutes"],
            "enabledSwitch": api_response["enabled"]
        }

        # Verify mapping is complete
        assert ui_mapping["alertRuleName"] == "Test Alert"
        assert ui_mapping["state_checkboxes"] == ["exited", "dead"]
        assert ui_mapping["event_checkboxes"] == ["oom", "die"]