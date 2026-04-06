"""Tests for alert rule validator — CPU threshold validation for multi-core containers."""

import pytest
from alerts.validator import AlertRuleValidator, AlertRuleValidationError


def _make_rule(metric: str, threshold: float, operator: str = ">=") -> dict:
    """Build a minimal valid rule dict for threshold validation."""
    return {
        "name": "test-rule",
        "scope": "container",
        "kind": "cpu_high",
        "severity": "warning",
        "metric": metric,
        "threshold": threshold,
        "operator": operator,
    }


class TestCpuThresholdValidation:
    """CPU metrics can exceed 100% on multi-core systems (Issue #210)."""

    def setup_method(self):
        self.validator = AlertRuleValidator()

    def test_cpu_threshold_above_100_is_valid(self):
        """A 4-core container can hit 400% CPU — threshold of 200 must be accepted."""
        # Should NOT raise
        self.validator.validate_rule(
            _make_rule(metric="docker_cpu_workload_pct", threshold=200.0)
        )

    def test_cpu_threshold_at_800_is_valid(self):
        """8-core container ceiling is 800%."""
        self.validator.validate_rule(
            _make_rule(metric="docker_cpu_workload_pct", threshold=800.0)
        )

    def test_cpu_threshold_at_ceiling_is_valid(self):
        """64-core ceiling of 6400% must be accepted."""
        self.validator.validate_rule(
            _make_rule(metric="docker_cpu_workload_pct", threshold=6400.0)
        )

    def test_cpu_threshold_above_ceiling_is_invalid(self):
        """Threshold above 6400% must be rejected."""
        with pytest.raises(AlertRuleValidationError):
            self.validator.validate_rule(
                _make_rule(metric="docker_cpu_workload_pct", threshold=6401.0)
            )

    def test_cpu_clear_threshold_above_100_is_valid(self):
        """CPU clear_threshold can exceed 100% for multi-core containers."""
        rule = _make_rule(metric="docker_cpu_workload_pct", threshold=400.0)
        rule["clear_threshold"] = 200.0
        self.validator.validate_rule(rule)

    def test_cpu_clear_threshold_above_ceiling_is_invalid(self):
        """CPU clear_threshold above 6400% must be rejected."""
        rule = _make_rule(metric="docker_cpu_workload_pct", threshold=400.0)
        rule["clear_threshold"] = 6401.0
        with pytest.raises(AlertRuleValidationError):
            self.validator.validate_rule(rule)

    def test_cpu_threshold_negative_is_invalid(self):
        """CPU threshold cannot be negative."""
        with pytest.raises(AlertRuleValidationError):
            self.validator.validate_rule(
                _make_rule(metric="docker_cpu_workload_pct", threshold=-1.0)
            )

    def test_memory_threshold_above_100_is_invalid(self):
        """Memory is always 0-100%, so >100 must be rejected."""
        with pytest.raises(AlertRuleValidationError):
            self.validator.validate_rule(
                _make_rule(metric="docker_mem_workload_pct", threshold=101.0)
            )

    def test_disk_threshold_above_100_is_invalid(self):
        """Disk percentages are always 0-100%."""
        with pytest.raises(AlertRuleValidationError):
            self.validator.validate_rule(
                _make_rule(metric="disk_used_pct", threshold=101.0)
            )
