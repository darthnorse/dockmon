"""The rule-metric registry is the single source of truth (issue #243, Fix C).

Four container metric keys were read by the evaluator under names no producer
ever emitted, so any rule using them was accepted and then never evaluated.
They are dropped rather than mapped: the underlying fields are cumulative
counters, so a rule on them would breach once and never clear.

The registry exists so evaluator mappings and rule validation cannot drift into
that state again - both derive from it.
"""
import pytest

from alerts.capabilities import HOST_METRIC_FIELDS
from alerts.metrics import (
    BREACH_OPERATORS,
    METRIC_RANGES,
    PENDING_METRICS_BY_SCOPE,
    PRODUCED_METRICS_BY_SCOPE,
    validate_metric_fields,
)

DROPPED_METRICS = (
    "network_rx_bytes",
    "network_tx_bytes",
    "block_read_bytes",
    "block_write_bytes",
)


class TestRegistryShape:
    def test_scopes_match_the_rule_scope_enum(self):
        assert set(PRODUCED_METRICS_BY_SCOPE) == {"host", "container", "group"}
        assert set(PENDING_METRICS_BY_SCOPE) == {"host", "container", "group"}

    def test_produced_and_pending_are_disjoint_per_scope(self):
        for scope in PRODUCED_METRICS_BY_SCOPE:
            overlap = PRODUCED_METRICS_BY_SCOPE[scope] & PENDING_METRICS_BY_SCOPE[scope]
            assert not overlap, f"{scope}: {overlap} is both produced and pending"

    def test_dropped_metrics_are_absent_everywhere(self):
        for scope in PRODUCED_METRICS_BY_SCOPE:
            known = PRODUCED_METRICS_BY_SCOPE[scope] | PENDING_METRICS_BY_SCOPE[scope]
            for metric in DROPPED_METRICS:
                assert metric not in known, f"{metric} still declared for {scope}"

    def test_group_scope_serves_nothing(self):
        # No group-scope evaluator exists; the registry says so rather than
        # accepting rules nothing will ever read.
        assert PRODUCED_METRICS_BY_SCOPE["group"] == frozenset()

    def test_every_range_key_is_a_declared_metric_and_vice_versa(self):
        declared = {
            (scope, metric)
            for mapping in (PRODUCED_METRICS_BY_SCOPE, PENDING_METRICS_BY_SCOPE)
            for scope, metrics in mapping.items()
            for metric in metrics
        }
        assert set(METRIC_RANGES) == declared

    def test_breach_operators_exclude_not_equal(self):
        # engine._check_breach has no != branch: it logs "Unknown operator" and
        # returns False, so a != rule can never fire.
        assert "!=" not in BREACH_OPERATORS
        assert BREACH_OPERATORS == {">=", "<=", ">", "<", "=="}


class TestHostCapabilityDerivation:
    def test_host_metric_fields_derive_from_the_registry(self):
        assert set(HOST_METRIC_FIELDS) == PRODUCED_METRICS_BY_SCOPE["host"]

    def test_host_metric_fields_order_is_stable(self):
        # Serialised into the capabilities API response and consumed by the UI;
        # frozenset iteration order is not guaranteed across runs.
        assert HOST_METRIC_FIELDS == tuple(sorted(HOST_METRIC_FIELDS))
        assert isinstance(HOST_METRIC_FIELDS, tuple)


class TestValidateMetricFields:
    def test_event_rules_need_no_metric_fields(self):
        validate_metric_fields("container", None, None, None, None)

    def test_scope_is_checked_before_the_metric_null_shortcut(self):
        # AlertRuleV2Update.scope accepts an explicit null, which would reach a
        # NOT NULL column and surface as a 500.
        with pytest.raises(ValueError, match="scope"):
            validate_metric_fields(None, None, None, None, None)
        with pytest.raises(ValueError, match="scope"):
            validate_metric_fields("nonsense", None, None, None, None)

    @pytest.mark.parametrize("metric", DROPPED_METRICS)
    def test_dropped_metrics_are_rejected(self, metric):
        with pytest.raises(ValueError, match=metric):
            validate_metric_fields("container", metric, 1000.0, None, ">=")

    def test_unknown_metric_is_rejected(self):
        with pytest.raises(ValueError, match="banana"):
            validate_metric_fields("container", "banana", 90.0, None, ">=")

    def test_metric_is_validated_against_its_scope(self):
        validate_metric_fields("container", "memory_usage", 1024.0, None, ">=")
        with pytest.raises(ValueError):
            validate_metric_fields("host", "memory_usage", 1024.0, None, ">=")

        validate_metric_fields("host", "disk_percent", 85.0, None, ">=")
        with pytest.raises(ValueError):
            validate_metric_fields("container", "disk_percent", 85.0, None, ">=")

    def test_threshold_and_operator_are_required_with_a_metric(self):
        with pytest.raises(ValueError, match="threshold"):
            validate_metric_fields("host", "cpu_percent", None, None, ">=")
        with pytest.raises(ValueError, match="operator"):
            validate_metric_fields("host", "cpu_percent", 90.0, None, None)

    @pytest.mark.parametrize("operator", [">=", "<=", ">", "<", "=="])
    def test_supported_operators_pass(self, operator):
        validate_metric_fields("host", "cpu_percent", 90.0, None, operator)

    def test_not_equal_operator_is_rejected(self):
        with pytest.raises(ValueError, match="!="):
            validate_metric_fields("host", "cpu_percent", 90.0, None, "!=")

    def test_cpu_range_is_scope_aware(self):
        validate_metric_fields("container", "cpu_percent", 200.0, None, ">=")
        with pytest.raises(ValueError):
            validate_metric_fields("host", "cpu_percent", 200.0, None, ">=")

    def test_percentage_metrics_are_capped_at_100(self):
        with pytest.raises(ValueError):
            validate_metric_fields("host", "memory_percent", 5000.0, None, ">=")
        with pytest.raises(ValueError):
            validate_metric_fields("container", "memory_percent", 5000.0, None, ">=")

    def test_byte_metrics_have_no_upper_bound(self):
        validate_metric_fields("container", "memory_usage", 8 * 1024**3, None, ">=")

    def test_negative_thresholds_are_rejected(self):
        with pytest.raises(ValueError):
            validate_metric_fields("host", "cpu_percent", -1.0, None, ">=")

    @pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
    def test_non_finite_thresholds_are_rejected(self, bad):
        # Python's json module accepts Infinity/NaN, so a >= 0 check alone
        # would admit them.
        with pytest.raises(ValueError):
            validate_metric_fields("host", "cpu_percent", bad, None, ">=")

    @pytest.mark.parametrize("bad", [float("inf"), float("nan")])
    def test_non_finite_clear_thresholds_are_rejected(self, bad):
        with pytest.raises(ValueError):
            validate_metric_fields("host", "cpu_percent", 90.0, bad, ">=")

    def test_clear_threshold_obeys_the_metric_range(self):
        with pytest.raises(ValueError):
            validate_metric_fields("host", "memory_percent", 90.0, 5000.0, ">=")

    def test_clear_threshold_direction_for_rising_operators(self):
        # Clearing evaluates _check_breach(value, clear_threshold, operator) and
        # clears on not-breached, so a clear above the alert threshold clears
        # while still breaching and re-fires next cycle.
        validate_metric_fields("host", "cpu_percent", 90.0, 80.0, ">=")
        validate_metric_fields("host", "cpu_percent", 90.0, 90.0, ">=")
        with pytest.raises(ValueError, match="clear"):
            validate_metric_fields("host", "cpu_percent", 90.0, 95.0, ">=")
        with pytest.raises(ValueError, match="clear"):
            validate_metric_fields("host", "cpu_percent", 90.0, 95.0, ">")

    def test_clear_threshold_direction_for_falling_operators(self):
        validate_metric_fields("host", "memory_percent", 20.0, 30.0, "<=")
        with pytest.raises(ValueError, match="clear"):
            validate_metric_fields("host", "memory_percent", 20.0, 10.0, "<=")
        with pytest.raises(ValueError, match="clear"):
            validate_metric_fields("host", "memory_percent", 20.0, 10.0, "<")

    def test_equality_requires_a_matching_clear_threshold(self):
        # There is no "less strict" side of ==: any other clear threshold means
        # the alert cannot clear at the very value that raised it.
        validate_metric_fields("host", "cpu_percent", 50.0, 50.0, "==")
        with pytest.raises(ValueError, match="clear"):
            validate_metric_fields("host", "cpu_percent", 50.0, 60.0, "==")
        with pytest.raises(ValueError, match="clear"):
            validate_metric_fields("host", "cpu_percent", 50.0, 40.0, "==")

    def test_system_scope_is_storable_but_serves_no_metric(self):
        # The self-diagnostic rule carries scope="system" and no metric; an
        # update touching its threshold must not be refused as an invalid scope.
        validate_metric_fields("system", None, None, None, None)
        with pytest.raises(ValueError):
            validate_metric_fields("system", "cpu_percent", 90.0, None, ">=")


# The evaluator's remedy tables are indexed directly by produced host metric, so
# a metric added to the registry without a mount entry must fail here, not as a
# KeyError in the evaluation loop.
def test_remedy_tables_cover_every_produced_host_metric():
    from alerts.evaluation_service import AlertEvaluationService

    assert set(AlertEvaluationService._AGENT_METRIC_MOUNTS) == PRODUCED_METRICS_BY_SCOPE["host"]
    assert set(AlertEvaluationService._LOCAL_METRIC_MOUNTS) == PRODUCED_METRICS_BY_SCOPE["host"]
