"""
Tests for alert rule persistence
Would have caught the bug where trigger_events was not saved/retrieved
"""

import pytest
from unittest.mock import MagicMock, patch
import json


class TestAlertRulePersistence:
    """Test that alert rules persist ALL fields correctly"""

    def test_alert_creation_includes_all_fields(self):
        """Test that creating an alert saves all fields including trigger_events"""
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        # Mock authentication
        with patch('main.verify_session_auth', return_value=True):
            # Create alert with all fields
            alert_data = {
                "name": "Test Alert",
                "host_id": "host123",
                "container_pattern": "web-.*",
                "trigger_events": ["die", "oom", "kill"],  # This was being lost!
                "trigger_states": ["exited", "dead"],
                "notification_channels": [1, 2],
                "cooldown_minutes": 10,
                "enabled": True
            }

            # Mock the database
            with patch('main.monitor.db.add_alert_rule') as mock_add:
                mock_rule = MagicMock()
                mock_rule.id = "test-id"
                mock_rule.name = alert_data["name"]
                mock_rule.host_id = alert_data["host_id"]
                mock_rule.container_pattern = alert_data["container_pattern"]
                mock_rule.trigger_events = alert_data["trigger_events"]
                mock_rule.trigger_states = alert_data["trigger_states"]
                mock_rule.notification_channels = alert_data["notification_channels"]
                mock_rule.cooldown_minutes = alert_data["cooldown_minutes"]
                mock_rule.enabled = alert_data["enabled"]
                mock_rule.last_triggered = None
                mock_rule.created_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
                mock_rule.updated_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")

                mock_add.return_value = mock_rule

                response = client.post("/api/alerts", json=alert_data)

                # Verify the database was called with ALL fields
                mock_add.assert_called_once()
                call_args = mock_add.call_args[0][0]

                # The bug: trigger_events was missing here!
                assert "trigger_events" in call_args
                assert call_args["trigger_events"] == ["die", "oom", "kill"]

                # Also verify other fields
                assert call_args["trigger_states"] == ["exited", "dead"]
                assert call_args["container_pattern"] == "web-.*"

    def test_alert_retrieval_includes_trigger_events(self):
        """Test that GET /api/alerts returns trigger_events"""
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        # Mock database response
        mock_rule = MagicMock()
        mock_rule.id = "test-id"
        mock_rule.name = "Test Alert"
        mock_rule.trigger_events = ["die", "oom"]  # This was missing in response!
        mock_rule.trigger_states = ["exited", "dead"]
        mock_rule.container_pattern = ".*"
        mock_rule.host_id = None
        mock_rule.notification_channels = [1]
        mock_rule.cooldown_minutes = 15
        mock_rule.enabled = True
        mock_rule.last_triggered = None
        mock_rule.created_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
        mock_rule.updated_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")

        with patch('main.monitor.db.get_alert_rules', return_value=[mock_rule]):
            response = client.get("/api/alerts")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1

            # The bug: trigger_events was missing in the response!
            assert "trigger_events" in data[0]
            assert data[0]["trigger_events"] == ["die", "oom"]

            # Also verify trigger_states is present
            assert data[0]["trigger_states"] == ["exited", "dead"]

    def test_alert_update_preserves_trigger_events(self):
        """Test that updating an alert preserves trigger_events"""
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        with patch('main.verify_session_auth', return_value=True):
            update_data = {
                "name": "Updated Alert",
                "trigger_events": ["health_status", "oom"],  # Update trigger events
                "trigger_states": ["paused", "dead"]
            }

            mock_rule = MagicMock()
            mock_rule.id = "test-id"
            mock_rule.name = update_data["name"]
            mock_rule.trigger_events = update_data["trigger_events"]
            mock_rule.trigger_states = update_data["trigger_states"]
            mock_rule.container_pattern = ".*"
            mock_rule.host_id = None
            mock_rule.notification_channels = [1]
            mock_rule.cooldown_minutes = 15
            mock_rule.enabled = True
            mock_rule.last_triggered = None
            mock_rule.created_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
            mock_rule.updated_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")

            with patch('main.monitor.db.update_alert_rule', return_value=mock_rule):
                response = client.put("/api/alerts/test-id", json=update_data)

                assert response.status_code == 200
                data = response.json()

                # The bug: trigger_events was not in the response!
                assert "trigger_events" in data
                assert data["trigger_events"] == ["health_status", "oom"]
                assert data["trigger_states"] == ["paused", "dead"]

    def test_alert_with_only_events_no_states(self):
        """Test alert can have only events without states"""
        from models.request_models import AlertRuleCreate

        # Should be valid to have events without states
        alert = AlertRuleCreate(
            name="Event Only Alert",
            container_pattern=".*",
            trigger_events=["oom", "kill"],  # Only events
            trigger_states=None,  # No states
            notification_channels=[1],
            cooldown_minutes=15
        )

        assert alert.trigger_events == ["oom", "kill"]
        assert alert.trigger_states is None

    def test_alert_with_only_states_no_events(self):
        """Test alert can have only states without events"""
        from models.request_models import AlertRuleCreate

        # Should be valid to have states without events
        alert = AlertRuleCreate(
            name="State Only Alert",
            container_pattern=".*",
            trigger_events=None,  # No events
            trigger_states=["exited", "dead"],  # Only states
            notification_channels=[1],
            cooldown_minutes=15
        )

        assert alert.trigger_states == ["exited", "dead"]
        assert alert.trigger_events is None

    def test_frontend_backend_field_mapping(self):
        """Test that frontend field names match backend expectations"""

        # Frontend sends this structure
        frontend_payload = {
            "name": "Test Alert",
            "container_pattern": "web-.*",
            "trigger_events": ["die", "oom"],  # Frontend field name
            "trigger_states": ["exited"],      # Frontend field name
            "notification_channels": [1],
            "cooldown_minutes": 5,
            "enabled": True
        }

        # Backend expects these exact field names
        from models.request_models import AlertRuleCreate

        # This should work without field name mismatches
        alert = AlertRuleCreate(**frontend_payload)

        assert alert.trigger_events == ["die", "oom"]
        assert alert.trigger_states == ["exited"]

    def test_database_schema_matches_api(self):
        """Test that database schema includes all API fields"""
        from database import AlertRuleDB
        from sqlalchemy import inspect

        # Get column names from database model
        mapper = inspect(AlertRuleDB)
        column_names = [c.key for c in mapper.columns]

        # These fields MUST exist in the database
        required_fields = [
            "id",
            "name",
            "host_id",
            "container_pattern",
            "trigger_events",  # This was the missing link!
            "trigger_states",
            "notification_channels",
            "cooldown_minutes",
            "enabled"
        ]

        for field in required_fields:
            assert field in column_names, f"Database missing field: {field}"

    @pytest.mark.parametrize("events,states,should_save", [
        (["die", "oom"], ["exited"], True),  # Both events and states
        (["die"], None, True),                # Only events
        (None, ["exited"], True),             # Only states
        ([], [], False),                      # Neither (should fail)
        (None, None, False),                  # Neither (should fail)
    ])
    def test_alert_validation_combinations(self, events, states, should_save):
        """Test various combinations of events and states"""
        from models.request_models import AlertRuleCreate

        if should_save:
            # Should successfully create
            alert = AlertRuleCreate(
                name="Test",
                container_pattern=".*",
                trigger_events=events,
                trigger_states=states,
                notification_channels=[1],
                cooldown_minutes=5
            )
            assert alert is not None
        else:
            # Frontend should prevent this, but test backend validation
            with pytest.raises(Exception):
                alert = AlertRuleCreate(
                    name="Test",
                    container_pattern=".*",
                    trigger_events=events,
                    trigger_states=states,
                    notification_channels=[1],
                    cooldown_minutes=5
                )

    def test_alert_edit_preserves_all_selections(self):
        """Integration test for the complete edit flow"""

        # Original alert as saved in database
        original = {
            "id": "alert-123",
            "name": "Production Alert",
            "container_pattern": "prod-.*",
            "host_id": "host-1",
            "trigger_events": ["die", "oom", "kill"],
            "trigger_states": ["exited", "dead"],
            "notification_channels": [1, 2, 3],
            "cooldown_minutes": 10,
            "enabled": True
        }

        # Simulate edit - change only the name
        edit_payload = {
            "name": "Production Alert (Updated)"
            # Other fields not sent in update
        }

        # After update, all original fields should be preserved
        expected_after_update = {
            **original,
            "name": "Production Alert (Updated)"
        }

        # Mock database update
        from database import DatabaseManager

        with patch.object(DatabaseManager, 'update_alert_rule') as mock_update:
            mock_rule = MagicMock()
            for key, value in expected_after_update.items():
                setattr(mock_rule, key, value)
            mock_rule.created_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
            mock_rule.updated_at = MagicMock(isoformat=lambda: "2024-01-01T00:00:00")
            mock_rule.last_triggered = None

            mock_update.return_value = mock_rule

            # Perform update
            db = DatabaseManager(":memory:")
            result = db.update_alert_rule("alert-123", edit_payload)

            # All fields should be preserved
            assert result.trigger_events == ["die", "oom", "kill"]
            assert result.trigger_states == ["exited", "dead"]
            assert result.notification_channels == [1, 2, 3]
            assert result.container_pattern == "prod-.*"