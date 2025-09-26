"""
Tests for model validation with None trigger fields
Would have caught the validation error when loading alert rules
"""

import pytest
from pydantic import ValidationError
from datetime import datetime


class TestModelValidationWithNoneFields:
    """Test that models properly handle None values for optional fields"""

    def test_alert_rule_model_accepts_none_trigger_states(self):
        """Test that AlertRule model accepts None for trigger_states"""
        from models.settings_models import AlertRule

        # This should work with trigger_states = None
        rule = AlertRule(
            id="test-id",
            name="Test Rule",
            container_pattern=".*",
            trigger_states=None,  # This was failing before
            trigger_events=["oom"],
            notification_channels=[1],
            cooldown_minutes=15,
            enabled=True
        )

        assert rule.trigger_states is None
        assert rule.trigger_events == ["oom"]

    def test_alert_rule_model_accepts_none_trigger_events(self):
        """Test that AlertRule model accepts None for trigger_events"""
        from models.settings_models import AlertRule

        # This should work with trigger_events = None
        rule = AlertRule(
            id="test-id",
            name="Test Rule",
            container_pattern=".*",
            trigger_states=["exited", "dead"],
            trigger_events=None,  # Should be allowed
            notification_channels=[1],
            cooldown_minutes=15,
            enabled=True
        )

        assert rule.trigger_events is None
        assert rule.trigger_states == ["exited", "dead"]

    def test_alert_rule_model_accepts_both_none(self):
        """Test that AlertRule model accepts both fields as None"""
        from models.settings_models import AlertRule

        # In the settings model, we might load a rule with both None
        # (though creation/update models should prevent this)
        rule = AlertRule(
            id="test-id",
            name="Test Rule",
            container_pattern=".*",
            trigger_states=None,
            trigger_events=None,
            notification_channels=[1],
            cooldown_minutes=15,
            enabled=True
        )

        assert rule.trigger_states is None
        assert rule.trigger_events is None

    def test_alert_rule_create_requires_at_least_one_trigger(self):
        """Test that AlertRuleCreate requires at least one trigger type"""
        from models.request_models import AlertRuleCreate

        # Should fail with neither triggers
        with pytest.raises(ValueError, match="at least one trigger"):
            AlertRuleCreate(
                name="Test Rule",
                container_pattern=".*",
                trigger_states=None,
                trigger_events=None,
                notification_channels=[1]
            )

        # Should work with just states
        rule = AlertRuleCreate(
            name="Test Rule",
            container_pattern=".*",
            trigger_states=["exited"],
            trigger_events=None,
            notification_channels=[1]
        )
        assert rule.trigger_states == ["exited"]

        # Should work with just events
        rule = AlertRuleCreate(
            name="Test Rule",
            container_pattern=".*",
            trigger_states=None,
            trigger_events=["oom"],
            notification_channels=[1]
        )
        assert rule.trigger_events == ["oom"]

    def test_alert_rule_update_allows_partial_updates(self):
        """Test that AlertRuleUpdate allows partial updates"""
        from models.request_models import AlertRuleUpdate

        # Update only trigger_events
        update = AlertRuleUpdate(trigger_events=["die", "oom"])
        assert update.trigger_events == ["die", "oom"]
        assert update.trigger_states is None  # Not being updated

        # Update to clear trigger_events
        update = AlertRuleUpdate(trigger_events=[])
        assert update.trigger_events == []

        # Update nothing (all None)
        update = AlertRuleUpdate()
        assert update.trigger_events is None
        assert update.trigger_states is None

    def test_database_model_with_none_fields(self):
        """Test that database model handles None fields correctly"""
        from database import AlertRuleDB
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from database import Base

        # Create in-memory database
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Create rule with None trigger_states
        rule = AlertRuleDB(
            id="test-1",
            name="Events Only",
            container_pattern=".*",
            trigger_events=["oom", "die"],
            trigger_states=None,  # Stored as NULL in database
            notification_channels=[1],
            cooldown_minutes=15,
            enabled=True
        )

        session.add(rule)
        session.commit()

        # Retrieve and verify
        retrieved = session.query(AlertRuleDB).filter_by(id="test-1").first()
        assert retrieved.trigger_states is None
        assert retrieved.trigger_events == ["oom", "die"]

        # Create rule with None trigger_events
        rule2 = AlertRuleDB(
            id="test-2",
            name="States Only",
            container_pattern=".*",
            trigger_events=None,  # Stored as NULL
            trigger_states=["exited"],
            notification_channels=[1],
            cooldown_minutes=15,
            enabled=True
        )

        session.add(rule2)
        session.commit()

        retrieved2 = session.query(AlertRuleDB).filter_by(id="test-2").first()
        assert retrieved2.trigger_events is None
        assert retrieved2.trigger_states == ["exited"]

        session.close()

    def test_json_serialization_with_none_fields(self):
        """Test that None fields serialize correctly to JSON"""
        from models.settings_models import AlertRule
        import json

        rule = AlertRule(
            id="test-id",
            name="Test Rule",
            container_pattern=".*",
            trigger_states=None,
            trigger_events=["oom"],
            notification_channels=[1],
            cooldown_minutes=15,
            enabled=True
        )

        # Convert to dict (as done in API responses)
        rule_dict = {
            "id": rule.id,
            "name": rule.name,
            "container_pattern": rule.container_pattern,
            "trigger_states": rule.trigger_states,
            "trigger_events": rule.trigger_events,
            "notification_channels": rule.notification_channels,
            "cooldown_minutes": rule.cooldown_minutes,
            "enabled": rule.enabled,
        }

        # Should serialize with null values
        json_str = json.dumps(rule_dict)
        parsed = json.loads(json_str)

        assert parsed["trigger_states"] is None
        assert parsed["trigger_events"] == ["oom"]

    @pytest.mark.parametrize("states,events,should_be_valid", [
        (None, ["oom"], True),           # Events only - valid
        (["exited"], None, True),        # States only - valid
        (["exited"], ["oom"], True),     # Both - valid
        (None, None, True),              # Both None - valid for settings model
        ([], ["oom"], True),             # Empty states, has events - valid
        (["exited"], [], True),          # Has states, empty events - valid
        ([], [], True),                  # Both empty - valid for settings model
    ])
    def test_settings_model_validation(self, states, events, should_be_valid):
        """Test AlertRule (settings) model validation with various inputs"""
        from models.settings_models import AlertRule

        if should_be_valid:
            rule = AlertRule(
                id="test",
                name="Test",
                container_pattern=".*",
                trigger_states=states,
                trigger_events=events,
                notification_channels=[1],
                cooldown_minutes=15,
                enabled=True
            )
            assert rule is not None
        else:
            with pytest.raises(ValidationError):
                AlertRule(
                    id="test",
                    name="Test",
                    container_pattern=".*",
                    trigger_states=states,
                    trigger_events=events,
                    notification_channels=[1],
                    cooldown_minutes=15,
                    enabled=True
                )

    def test_backward_compatibility(self):
        """Test that old rules without trigger_events still work"""
        from models.settings_models import AlertRule

        # Simulate loading an old rule from database that doesn't have trigger_events
        old_rule_data = {
            "id": "old-rule",
            "name": "Old Rule",
            "container_pattern": ".*",
            "trigger_states": ["exited", "dead"],
            # trigger_events not present in old data
            "notification_channels": [1],
            "cooldown_minutes": 15,
            "enabled": True
        }

        # Should still load successfully with trigger_events defaulting to None
        rule = AlertRule(**old_rule_data)
        assert rule.trigger_states == ["exited", "dead"]
        assert rule.trigger_events is None