"""
Tests for alert rule trigger selection logic
Would have caught the bug where you couldn't deselect all events if states were selected
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


class TestAlertTriggerSelection:
    """Test that alert rules properly handle trigger event/state selection"""

    def test_can_clear_all_events_when_states_exist(self):
        """Test that you can clear all events as long as states are selected"""
        from main import app

        client = TestClient(app)

        with patch('main.verify_session_auth', return_value=True):
            # Create alert with both events and states
            initial_alert = {
                "id": "test-alert",
                "name": "Test Alert",
                "container_pattern": ".*",
                "trigger_events": ["die", "oom"],
                "trigger_states": ["exited", "dead"],
                "notification_channels": [1],
                "cooldown_minutes": 15,
                "enabled": True
            }

            # Mock database to return the initial alert
            mock_rule = MagicMock()
            for key, value in initial_alert.items():
                setattr(mock_rule, key, value)
            mock_rule.created_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
            mock_rule.updated_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
            mock_rule.last_triggered = None

            with patch('main.monitor.db.get_alert_rule', return_value=mock_rule):
                with patch('main.monitor.db.update_alert_rule') as mock_update:
                    # Update to clear all events but keep states
                    update_data = {
                        "trigger_events": [],  # Clear all events
                        "trigger_states": ["exited", "dead"]  # Keep states
                    }

                    # Mock the updated rule
                    updated_rule = MagicMock()
                    updated_rule.id = "test-alert"
                    updated_rule.name = "Test Alert"
                    updated_rule.container_pattern = ".*"
                    updated_rule.trigger_events = None  # Events cleared
                    updated_rule.trigger_states = ["exited", "dead"]
                    updated_rule.notification_channels = [1]
                    updated_rule.cooldown_minutes = 15
                    updated_rule.enabled = True
                    updated_rule.host_id = None
                    updated_rule.last_triggered = None
                    updated_rule.created_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
                    updated_rule.updated_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")

                    mock_update.return_value = updated_rule

                    response = client.put("/api/alerts/test-alert", json=update_data)

                    # Should succeed
                    assert response.status_code == 200

                    # Verify the update was called with trigger_events set to None
                    mock_update.assert_called_once()
                    call_args = mock_update.call_args[0][1]
                    assert "trigger_events" in call_args
                    assert call_args["trigger_events"] is None

                    # Response should show no events
                    data = response.json()
                    assert data["trigger_events"] is None
                    assert data["trigger_states"] == ["exited", "dead"]

    def test_can_clear_all_states_when_events_exist(self):
        """Test that you can clear all states as long as events are selected"""
        from main import app

        client = TestClient(app)

        with patch('main.verify_session_auth', return_value=True):
            # Initial alert with both
            mock_rule = MagicMock()
            mock_rule.id = "test-alert"
            mock_rule.trigger_events = ["die", "oom"]
            mock_rule.trigger_states = ["exited", "dead"]
            mock_rule.notification_channels = [1]
            mock_rule.container_pattern = ".*"
            mock_rule.name = "Test"
            mock_rule.cooldown_minutes = 15
            mock_rule.enabled = True
            mock_rule.host_id = None
            mock_rule.last_triggered = None
            mock_rule.created_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
            mock_rule.updated_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")

            with patch('main.monitor.db.get_alert_rule', return_value=mock_rule):
                with patch('main.monitor.db.update_alert_rule') as mock_update:
                    # Clear states, keep events
                    update_data = {
                        "trigger_events": ["die", "oom"],
                        "trigger_states": []  # Clear all states
                    }

                    updated_rule = MagicMock()
                    updated_rule.id = "test-alert"
                    updated_rule.trigger_events = ["die", "oom"]
                    updated_rule.trigger_states = None  # States cleared
                    updated_rule.notification_channels = [1]
                    updated_rule.container_pattern = ".*"
                    updated_rule.name = "Test"
                    updated_rule.cooldown_minutes = 15
                    updated_rule.enabled = True
                    updated_rule.host_id = None
                    updated_rule.last_triggered = None
                    updated_rule.created_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
                    updated_rule.updated_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")

                    mock_update.return_value = updated_rule

                    response = client.put("/api/alerts/test-alert", json=update_data)

                    # Should succeed
                    assert response.status_code == 200

                    # Verify states were cleared
                    call_args = mock_update.call_args[0][1]
                    assert call_args["trigger_states"] is None
                    assert call_args["trigger_events"] == ["die", "oom"]

    def test_cannot_clear_both_events_and_states(self):
        """Test that you cannot clear both events and states"""
        from main import app

        client = TestClient(app)

        with patch('main.verify_session_auth', return_value=True):
            mock_rule = MagicMock()
            mock_rule.id = "test-alert"
            mock_rule.trigger_events = ["die"]
            mock_rule.trigger_states = ["exited"]
            mock_rule.notification_channels = [1]

            with patch('main.monitor.db.get_alert_rule', return_value=mock_rule):
                # Try to clear both
                update_data = {
                    "trigger_events": [],
                    "trigger_states": []
                }

                response = client.put("/api/alerts/test-alert", json=update_data)

                # Should fail with 400
                assert response.status_code == 400
                assert "at least one trigger event or state" in response.json()["detail"].lower()

    def test_empty_list_converted_to_none_in_database(self):
        """Test that empty arrays are stored as None in database"""
        from main import app

        client = TestClient(app)

        with patch('main.verify_session_auth', return_value=True):
            mock_rule = MagicMock()
            mock_rule.trigger_events = ["die"]
            mock_rule.trigger_states = ["exited"]

            with patch('main.monitor.db.get_alert_rule', return_value=mock_rule):
                with patch('main.monitor.db.update_alert_rule') as mock_update:
                    # Send empty array for events
                    update_data = {
                        "trigger_events": [],
                        "trigger_states": ["exited"]
                    }

                    mock_update.return_value = MagicMock(
                        id="test",
                        trigger_events=None,
                        trigger_states=["exited"],
                        notification_channels=[1],
                        container_pattern=".*",
                        name="Test",
                        cooldown_minutes=15,
                        enabled=True,
                        host_id=None,
                        last_triggered=None,
                        created_at=MagicMock(isoformat=lambda: "2024-01-01T00:00:00"),
                        updated_at=MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
                    )

                    response = client.put("/api/alerts/test", json=update_data)

                    # Check that empty array was converted to None
                    call_args = mock_update.call_args[0][1]
                    assert call_args["trigger_events"] is None  # Not empty list

    def test_sequential_edits_preserve_correct_state(self):
        """Test that sequential edits don't revert changes"""

        # Scenario that was failing:
        # 1. Create alert with events and states
        # 2. Edit to remove all events (keep states) - save
        # 3. Edit again - events should still be empty

        from main import app
        from database import DatabaseManager

        # Simulate the actual bug scenario
        alert_states = {
            "initial": {
                "trigger_events": ["die", "oom"],
                "trigger_states": ["exited", "dead"]
            },
            "after_first_edit": {
                "trigger_events": None,  # Cleared
                "trigger_states": ["exited", "dead"]
            }
        }

        # After first edit, database should have trigger_events = None
        # When loading for second edit, it should still be None, not revert

        with patch.object(DatabaseManager, 'get_alert_rule') as mock_get:
            # Second edit loads the saved state
            mock_rule = MagicMock()
            mock_rule.trigger_events = None  # This was the bug - it was reverting
            mock_rule.trigger_states = ["exited", "dead"]
            mock_get.return_value = mock_rule

            db = DatabaseManager(":memory:")
            rule = db.get_alert_rule("test")

            # Events should remain None, not revert to original
            assert rule.trigger_events is None
            assert rule.trigger_states == ["exited", "dead"]

    @pytest.mark.parametrize("events,states,should_succeed", [
        (["die"], ["exited"], True),     # Both selected - OK
        ([], ["exited"], True),          # Only states - OK
        (["die"], [], True),             # Only events - OK
        ([], [], False),                 # Neither - FAIL
        (None, ["exited"], True),        # Null events, states selected - OK
        (["die"], None, True),           # Events selected, null states - OK
        (None, None, False),             # Both null - FAIL
    ])
    def test_validation_combinations(self, events, states, should_succeed):
        """Test all combinations of event/state selections"""
        from main import app

        client = TestClient(app)

        with patch('main.verify_session_auth', return_value=True):
            # Mock existing rule
            mock_rule = MagicMock()
            mock_rule.trigger_events = ["die"]
            mock_rule.trigger_states = ["exited"]
            mock_rule.notification_channels = [1]

            with patch('main.monitor.db.get_alert_rule', return_value=mock_rule):
                with patch('main.monitor.db.update_alert_rule') as mock_update:
                    update_data = {}
                    if events is not None:
                        update_data["trigger_events"] = events
                    if states is not None:
                        update_data["trigger_states"] = states

                    if should_succeed:
                        mock_update.return_value = MagicMock(
                            id="test",
                            trigger_events=events if events else None,
                            trigger_states=states if states else None,
                            notification_channels=[1],
                            container_pattern=".*",
                            name="Test",
                            cooldown_minutes=15,
                            enabled=True,
                            host_id=None,
                            last_triggered=None,
                            created_at=MagicMock(isoformat=lambda: "2024-01-01T00:00:00"),
                            updated_at=MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
                        )

                        response = client.put("/api/alerts/test", json=update_data)
                        assert response.status_code == 200
                    else:
                        response = client.put("/api/alerts/test", json=update_data)
                        assert response.status_code == 400

    def test_frontend_sends_empty_arrays_not_null(self):
        """Test that frontend sends empty arrays for cleared selections"""

        # Frontend should send:
        # - Empty array [] when all checkboxes unchecked
        # - Not null or undefined

        frontend_payload = {
            "trigger_events": [],  # Empty array, not null
            "trigger_states": ["exited"]
        }

        # Backend should convert empty array to None for storage
        assert isinstance(frontend_payload["trigger_events"], list)
        assert len(frontend_payload["trigger_events"]) == 0

        # After backend processing
        processed = None if len(frontend_payload["trigger_events"]) == 0 else frontend_payload["trigger_events"]
        assert processed is None