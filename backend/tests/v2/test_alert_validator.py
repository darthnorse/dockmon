"""
Unit tests for Alert Rule Validator (validator.py)

Tests cover:
- Required field validation
- Threshold range validation
- Duration validation
- Occurrences validation
- Selector size limits
- ReDoS prevention
- Dependency validation
"""

import pytest
import json
from alerts.validator import AlertRuleValidator, AlertRuleValidationError

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture
def validator():
    """Create validator instance"""
    return AlertRuleValidator()


@pytest.fixture
def valid_metric_rule():
    """Valid metric-driven rule"""
    return {
        "name": "High CPU Alert",
        "description": "Alert when CPU is high",
        "scope": "container",
        "kind": "cpu_high",
        "severity": "warning",
        "metric": "cpu_percent",
        "operator": ">=",
        "threshold": 90.0,
        "duration_seconds": 300,
        "occurrences": 3,
        "grace_seconds": 60,
        "cooldown_seconds": 300
    }


@pytest.fixture
def valid_event_rule():
    """Valid event-driven rule"""
    return {
        "name": "Container Unhealthy",
        "description": "Alert when container becomes unhealthy",
        "scope": "container",
        "kind": "unhealthy",
        "severity": "critical",  # Changed from 'error' to 'critical'
        "grace_seconds": 30,
        "cooldown_seconds": 600
    }


# ==================== Required Fields Tests ====================

def test_valid_metric_rule_passes(validator, valid_metric_rule):
    """Test that valid metric rule passes validation"""
    # Should not raise exception
    validator.validate_rule(valid_metric_rule)


def test_valid_event_rule_passes(validator, valid_event_rule):
    """Test that valid event rule passes validation"""
    # Should not raise exception
    validator.validate_rule(valid_event_rule)


def test_missing_name_fails(validator, valid_metric_rule):
    """Test that missing name fails validation"""
    del valid_metric_rule["name"]

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "name" in str(exc_info.value).lower()


def test_missing_scope_fails(validator, valid_metric_rule):
    """Test that missing scope fails validation"""
    del valid_metric_rule["scope"]

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "scope" in str(exc_info.value).lower()


def test_missing_severity_fails(validator, valid_metric_rule):
    """Test that missing severity fails validation"""
    del valid_metric_rule["severity"]

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "severity" in str(exc_info.value).lower()


# ==================== Scope Validation Tests ====================

def test_valid_scopes_pass(validator, valid_metric_rule):
    """Test that valid scopes pass validation"""
    for scope in ["host", "container", "group"]:
        valid_metric_rule["scope"] = scope
        validator.validate_rule(valid_metric_rule)  # Should not raise


def test_invalid_scope_fails(validator, valid_metric_rule):
    """Test that invalid scope fails validation"""
    valid_metric_rule["scope"] = "invalid_scope"

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "scope" in str(exc_info.value).lower()


# ==================== Severity Validation Tests ====================

def test_valid_severities_pass(validator, valid_metric_rule):
    """Test that valid severities pass validation"""
    for severity in ["info", "warning", "critical"]:  # Removed 'error' - not in VALID_SEVERITIES
        valid_metric_rule["severity"] = severity
        validator.validate_rule(valid_metric_rule)  # Should not raise


def test_invalid_severity_fails(validator, valid_metric_rule):
    """Test that invalid severity fails validation"""
    valid_metric_rule["severity"] = "super_critical"

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "severity" in str(exc_info.value).lower()


# ==================== Threshold Validation Tests ====================

def test_threshold_must_be_number(validator, valid_metric_rule):
    """Test that threshold must be a number"""
    valid_metric_rule["threshold"] = "ninety"

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "threshold" in str(exc_info.value).lower()
    assert "number" in str(exc_info.value).lower()


def test_percentage_threshold_range(validator, valid_metric_rule):
    """Test percentage metric threshold range validation"""
    # Change metric to one that's actually in PERCENTAGE_METRICS
    valid_metric_rule["metric"] = "docker_cpu_workload_pct"

    # Valid percentages
    valid_metric_rule["threshold"] = 0.0
    validator.validate_rule(valid_metric_rule)

    valid_metric_rule["threshold"] = 100.0
    validator.validate_rule(valid_metric_rule)

    valid_metric_rule["threshold"] = 50.5
    validator.validate_rule(valid_metric_rule)

    # Invalid percentages
    valid_metric_rule["threshold"] = -10.0
    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)
    assert "percentage" in str(exc_info.value).lower()

    valid_metric_rule["threshold"] = 150.0
    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)
    assert "percentage" in str(exc_info.value).lower()


def test_clear_threshold_sanity_check(validator, valid_metric_rule):
    """Test clear threshold sanity checks"""
    # For >= operator, clear_threshold must be < threshold
    valid_metric_rule["operator"] = ">="
    valid_metric_rule["threshold"] = 90.0
    valid_metric_rule["clear_threshold"] = 80.0
    validator.validate_rule(valid_metric_rule)  # Valid

    valid_metric_rule["clear_threshold"] = 95.0
    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)
    assert "clear threshold" in str(exc_info.value).lower()

    # For <= operator, clear_threshold must be > threshold
    valid_metric_rule["operator"] = "<="
    valid_metric_rule["threshold"] = 10.0
    valid_metric_rule["clear_threshold"] = 15.0
    validator.validate_rule(valid_metric_rule)  # Valid

    valid_metric_rule["clear_threshold"] = 5.0
    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)
    assert "clear threshold" in str(exc_info.value).lower()


# ==================== Operator Validation Tests ====================

def test_valid_operators_pass(validator, valid_metric_rule):
    """Test that valid operators pass validation"""
    for op in [">=", "<=", "==", ">", "<"]:
        valid_metric_rule["operator"] = op
        validator.validate_rule(valid_metric_rule)  # Should not raise


def test_invalid_operator_fails(validator, valid_metric_rule):
    """Test that invalid operator fails validation"""
    valid_metric_rule["operator"] = "~="  # Changed from '!=' which is actually valid

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "operator" in str(exc_info.value).lower()


def test_metric_requires_operator(validator, valid_metric_rule):
    """Test that metric rules require operator"""
    del valid_metric_rule["operator"]

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "operator" in str(exc_info.value).lower()


# ==================== Duration Validation Tests ====================

def test_duration_range_validation(validator, valid_metric_rule):
    """Test duration range validation"""
    # Valid durations
    valid_metric_rule["duration_seconds"] = 1
    validator.validate_rule(valid_metric_rule)

    valid_metric_rule["duration_seconds"] = 86400  # 24 hours
    validator.validate_rule(valid_metric_rule)

    # Too short
    valid_metric_rule["duration_seconds"] = 0
    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)
    assert "duration" in str(exc_info.value).lower()

    # Too long
    valid_metric_rule["duration_seconds"] = 90000
    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)
    assert "duration" in str(exc_info.value).lower()


def test_clear_duration_range_validation(validator, valid_metric_rule):
    """Test clear duration range validation"""
    valid_metric_rule["clear_duration_seconds"] = 1
    validator.validate_rule(valid_metric_rule)

    valid_metric_rule["clear_duration_seconds"] = 86400
    validator.validate_rule(valid_metric_rule)

    # Note: clear_duration_seconds = 0 is actually valid (allows immediate clear)
    # Test with negative value instead
    valid_metric_rule["clear_duration_seconds"] = -1
    with pytest.raises(AlertRuleValidationError):
        validator.validate_rule(valid_metric_rule)


# ==================== Occurrences Validation Tests ====================

def test_occurrences_range_validation(validator, valid_metric_rule):
    """Test occurrences range validation"""
    # Valid occurrences
    valid_metric_rule["occurrences"] = 1
    validator.validate_rule(valid_metric_rule)

    valid_metric_rule["occurrences"] = 100
    validator.validate_rule(valid_metric_rule)

    # Too low
    valid_metric_rule["occurrences"] = 0
    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)
    assert "occurrences" in str(exc_info.value).lower()

    # Too high
    valid_metric_rule["occurrences"] = 101
    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)
    assert "occurrences" in str(exc_info.value).lower()


# ==================== Selector Size Validation Tests ====================

def test_selector_size_limits(validator, valid_metric_rule):
    """Test selector size limits to prevent DoS"""
    # Create oversized selector (> 10KB)
    huge_selector = {f"key_{i}": "x" * 1000 for i in range(20)}

    # Use correct field name with _json suffix
    valid_metric_rule["host_selector_json"] = huge_selector

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "selector" in str(exc_info.value).lower()
    assert ("size" in str(exc_info.value).lower() or "large" in str(exc_info.value).lower())


def test_labels_size_limits(validator, valid_metric_rule):
    """Test labels size limits"""
    # Create oversized labels (> 5KB)
    huge_labels = {f"label_{i}": "x" * 500 for i in range(20)}

    # Use correct field name with _json suffix
    valid_metric_rule["labels_json"] = huge_labels

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "labels" in str(exc_info.value).lower()
    assert ("size" in str(exc_info.value).lower() or "large" in str(exc_info.value).lower())


# ==================== ReDoS Prevention Tests ====================

def test_safe_regex_patterns_pass(validator, valid_metric_rule):
    """Test that safe regex patterns pass validation"""
    safe_patterns = [
        "^production-.*",
        "web-[0-9]+",
        "app-(backend|frontend)",
        "[a-z]{3,10}"
    ]

    # Use correct field name with _json suffix
    valid_metric_rule["container_selector_json"] = {"regex": "test"}

    for pattern in safe_patterns:
        valid_metric_rule["container_selector_json"]["regex"] = pattern
        validator.validate_rule(valid_metric_rule)  # Should not raise


def test_dangerous_regex_patterns_fail(validator, valid_metric_rule):
    """Test that dangerous regex patterns fail validation (ReDoS prevention)"""
    dangerous_patterns = [
        ".*.*.*",  # Nested quantifiers
        ".+.+.+",
        "(.*)*",   # Nested groups with quantifiers
        "(.+)+"
    ]

    # Use correct field name with _json suffix
    valid_metric_rule["container_selector_json"] = {"regex": "test"}

    for pattern in dangerous_patterns:
        valid_metric_rule["container_selector_json"]["regex"] = pattern

        with pytest.raises(AlertRuleValidationError) as exc_info:
            validator.validate_rule(valid_metric_rule)

        assert "regex" in str(exc_info.value).lower() or "redos" in str(exc_info.value).lower()


# ==================== Dependency Validation Tests ====================

def test_dependency_limit(validator, valid_metric_rule):
    """Test dependency count limit"""
    # Valid number of dependencies - use correct field name with _json suffix
    valid_metric_rule["depends_on_json"] = ["rule_1", "rule_2", "rule_3"]
    validator.validate_rule(valid_metric_rule)

    # Too many dependencies (> 5)
    valid_metric_rule["depends_on_json"] = [f"rule_{i}" for i in range(10)]

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "dependencies" in str(exc_info.value).lower()


def test_no_self_dependency(validator, valid_metric_rule):
    """Test that rules cannot depend on themselves"""
    valid_metric_rule["id"] = "rule_123"
    # Use correct field name with _json suffix
    valid_metric_rule["depends_on_json"] = ["rule_123"]  # Self-reference

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "depend on itself" in str(exc_info.value).lower() or "self" in str(exc_info.value).lower()


# ==================== Notification Validation Tests ====================

def test_notification_channel_limit(validator, valid_metric_rule):
    """Test notification channel count limit"""
    # Valid number of channels - use correct field name with _json suffix
    valid_metric_rule["notify_channels_json"] = ["slack", "email"]
    validator.validate_rule(valid_metric_rule)

    # Too many channels (> 10)
    # Use valid channel names that are in VALID_NOTIFICATION_CHANNELS
    valid_channels = ["slack", "discord", "telegram", "pushover", "email", "gotify"]
    valid_metric_rule["notify_channels_json"] = (valid_channels * 3)[:15]  # 15 channels

    with pytest.raises(AlertRuleValidationError) as exc_info:
        validator.validate_rule(valid_metric_rule)

    assert "notification" in str(exc_info.value).lower() or "channels" in str(exc_info.value).lower()


# ==================== Grace and Cooldown Validation Tests ====================

def test_grace_seconds_range(validator, valid_metric_rule):
    """Test grace_seconds range validation"""
    # Valid values
    valid_metric_rule["grace_seconds"] = 0
    validator.validate_rule(valid_metric_rule)

    # Max is actually 86400 (24 hours), not 3600
    valid_metric_rule["grace_seconds"] = 86400
    validator.validate_rule(valid_metric_rule)

    # Too high (exceeds 86400)
    valid_metric_rule["grace_seconds"] = 86401
    with pytest.raises(AlertRuleValidationError):
        validator.validate_rule(valid_metric_rule)


def test_cooldown_seconds_range(validator, valid_metric_rule):
    """Test cooldown_seconds range validation"""
    # Valid values
    valid_metric_rule["cooldown_seconds"] = 0
    validator.validate_rule(valid_metric_rule)

    valid_metric_rule["cooldown_seconds"] = 86400
    validator.validate_rule(valid_metric_rule)

    # Too high
    valid_metric_rule["cooldown_seconds"] = 90000
    with pytest.raises(AlertRuleValidationError):
        validator.validate_rule(valid_metric_rule)


# ==================== Edge Cases ====================

def test_empty_rule_dict_fails(validator):
    """Test that empty rule dict fails validation"""
    with pytest.raises(AlertRuleValidationError):
        validator.validate_rule({})


def test_none_values_handled(validator, valid_metric_rule):
    """Test that None values are handled properly"""
    # Optional fields can be None
    valid_metric_rule["description"] = None
    valid_metric_rule["clear_threshold"] = None
    valid_metric_rule["clear_duration_seconds"] = None

    validator.validate_rule(valid_metric_rule)  # Should not raise


def test_event_rule_without_metric_is_valid(validator, valid_event_rule):
    """Test that event-driven rules don't need metric fields"""
    # Event rule with no metric fields should be valid
    assert "metric" not in valid_event_rule
    assert "threshold" not in valid_event_rule
    assert "operator" not in valid_event_rule

    validator.validate_rule(valid_event_rule)  # Should not raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
