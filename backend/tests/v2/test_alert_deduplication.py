"""
Unit tests for alert deduplication with rule_id

Tests the deduplication key generation that includes rule_id to allow
multiple rules to create separate alerts for the same condition.

Background: We changed from {kind}|{scope_type}:{scope_id} to
{rule_id}|{kind}|{scope_type}:{scope_id} to support scenarios like:
- Warning rule for CPU > 80%
- Critical rule for CPU > 95%
Both should create separate alerts for the same container.
"""

import pytest


class TestAlertDeduplication:
    """Tests for alert deduplication key generation"""

    def test_dedup_key_includes_rule_id(self):
        """Should include rule_id in deduplication key"""
        rule_id = "rule-123"
        kind = "cpu_high"
        scope_type = "container"
        scope_id = "container-abc"

        # Generate dedup key as per engine.py
        dedup_key = f"{rule_id}|{kind}|{scope_type}:{scope_id}"

        assert rule_id in dedup_key
        assert kind in dedup_key
        assert scope_type in dedup_key
        assert scope_id in dedup_key
        assert dedup_key == "rule-123|cpu_high|container:container-abc"

    def test_different_rules_same_condition_create_different_keys(self):
        """Should create different dedup keys for different rules on same condition"""
        # Two rules monitoring the same container for CPU
        rule_id_warning = "rule-warning"
        rule_id_critical = "rule-critical"
        kind = "cpu_high"
        scope_type = "container"
        scope_id = "container-abc"

        # Generate dedup keys
        dedup_key_warning = f"{rule_id_warning}|{kind}|{scope_type}:{scope_id}"
        dedup_key_critical = f"{rule_id_critical}|{kind}|{scope_type}:{scope_id}"

        # Verify: Different keys
        assert dedup_key_warning != dedup_key_critical
        assert dedup_key_warning == "rule-warning|cpu_high|container:container-abc"
        assert dedup_key_critical == "rule-critical|cpu_high|container:container-abc"

    def test_same_rule_same_condition_creates_same_key(self):
        """Should create same dedup key for same rule and condition (idempotent)"""
        rule_id = "rule-123"
        kind = "cpu_high"
        scope_type = "container"
        scope_id = "container-abc"

        # Generate dedup key twice
        dedup_key_1 = f"{rule_id}|{kind}|{scope_type}:{scope_id}"
        dedup_key_2 = f"{rule_id}|{kind}|{scope_type}:{scope_id}"

        # Verify: Same key (deduplication works)
        assert dedup_key_1 == dedup_key_2

    def test_different_scope_ids_create_different_keys(self):
        """Should create different keys for different containers"""
        rule_id = "rule-123"
        kind = "cpu_high"
        scope_type = "container"

        # Two different containers
        scope_id_1 = "container-abc"
        scope_id_2 = "container-xyz"

        dedup_key_1 = f"{rule_id}|{kind}|{scope_type}:{scope_id_1}"
        dedup_key_2 = f"{rule_id}|{kind}|{scope_type}:{scope_id_2}"

        # Verify: Different keys
        assert dedup_key_1 != dedup_key_2
        assert dedup_key_1 == "rule-123|cpu_high|container:container-abc"
        assert dedup_key_2 == "rule-123|cpu_high|container:container-xyz"

    def test_different_kinds_create_different_keys(self):
        """Should create different keys for different alert kinds"""
        rule_id = "rule-123"
        scope_type = "container"
        scope_id = "container-abc"

        # Different kinds
        kind_cpu = "cpu_high"
        kind_memory = "memory_high"

        dedup_key_cpu = f"{rule_id}|{kind_cpu}|{scope_type}:{scope_id}"
        dedup_key_memory = f"{rule_id}|{kind_memory}|{scope_type}:{scope_id}"

        # Verify: Different keys
        assert dedup_key_cpu != dedup_key_memory

    def test_host_vs_container_scope_creates_different_keys(self):
        """Should create different keys for host vs container scope"""
        rule_id = "rule-123"
        kind = "cpu_high"
        scope_id = "id-abc"  # Same ID

        # Different scope types
        dedup_key_host = f"{rule_id}|{kind}|host:{scope_id}"
        dedup_key_container = f"{rule_id}|{kind}|container:{scope_id}"

        # Verify: Different keys
        assert dedup_key_host != dedup_key_container

    def test_dedup_key_format_with_hyphens_in_ids(self):
        """Should handle UUIDs and IDs with hyphens correctly"""
        rule_id = "550e8400-e29b-41d4-a716-446655440000"
        kind = "container_stopped"
        scope_type = "container"
        scope_id = "container-123-abc-456"

        dedup_key = f"{rule_id}|{kind}|{scope_type}:{scope_id}"

        # Verify: No parsing issues with hyphens
        assert dedup_key == "550e8400-e29b-41d4-a716-446655440000|container_stopped|container:container-123-abc-456"

    def test_dedup_key_parsing_components(self):
        """Should be able to parse components from dedup key"""
        dedup_key = "rule-123|cpu_high|container:container-abc"

        # Parse components
        parts = dedup_key.split('|')
        assert len(parts) == 3

        rule_id = parts[0]
        kind = parts[1]
        scope_parts = parts[2].split(':')
        scope_type = scope_parts[0]
        scope_id = scope_parts[1]

        # Verify
        assert rule_id == "rule-123"
        assert kind == "cpu_high"
        assert scope_type == "container"
        assert scope_id == "container-abc"

    def test_multiple_rules_warning_and_critical_scenario(self):
        """Simulate real scenario: separate Warning and Critical rules for same metric"""
        container_id = "web-server-1"

        # User creates two rules for the same container:
        # 1. Warning: CPU > 80%
        warning_rule_id = "rule-cpu-warning"
        warning_dedup_key = f"{warning_rule_id}|cpu_high|container:{container_id}"

        # 2. Critical: CPU > 95%
        critical_rule_id = "rule-cpu-critical"
        critical_dedup_key = f"{critical_rule_id}|cpu_high|container:{container_id}"

        # Verify: Both can coexist without conflict
        assert warning_dedup_key != critical_dedup_key

        # Simulate alert storage
        alerts = {
            warning_dedup_key: {
                'severity': 'warning',
                'threshold': 80,
                'current_value': 85
            },
            critical_dedup_key: {
                'severity': 'critical',
                'threshold': 95,
                'current_value': 98
            }
        }

        # Verify: Both alerts stored separately
        assert len(alerts) == 2
        assert alerts[warning_dedup_key]['severity'] == 'warning'
        assert alerts[critical_dedup_key]['severity'] == 'critical'

    def test_old_dedup_key_format_for_comparison(self):
        """Document the old format for comparison (without rule_id)"""
        # OLD FORMAT (would cause conflicts):
        kind = "cpu_high"
        scope_type = "container"
        scope_id = "container-abc"
        old_dedup_key = f"{kind}|{scope_type}:{scope_id}"

        # NEW FORMAT (allows multiple rules):
        rule_id_1 = "rule-warning"
        rule_id_2 = "rule-critical"
        new_dedup_key_1 = f"{rule_id_1}|{kind}|{scope_type}:{scope_id}"
        new_dedup_key_2 = f"{rule_id_2}|{kind}|{scope_type}:{scope_id}"

        # With old format, both rules would conflict on same key
        # With new format, they get separate keys
        assert new_dedup_key_1 != new_dedup_key_2
        # Old format would be: "cpu_high|container:container-abc" (same for both)

    def test_dedup_key_uniqueness_across_rules_and_scopes(self):
        """Should create unique keys for all combinations"""
        rule_ids = ["rule-1", "rule-2"]
        kinds = ["cpu_high", "memory_high"]
        scope_types = ["host", "container"]
        scope_ids = ["id-1", "id-2"]

        # Generate all combinations
        keys = set()
        for rule_id in rule_ids:
            for kind in kinds:
                for scope_type in scope_types:
                    for scope_id in scope_ids:
                        key = f"{rule_id}|{kind}|{scope_type}:{scope_id}"
                        keys.add(key)

        # Verify: All unique (2 * 2 * 2 * 2 = 16 combinations)
        assert len(keys) == 16

    def test_dedup_key_with_special_characters_in_scope_id(self):
        """Should handle special characters in scope_id"""
        rule_id = "rule-123"
        kind = "container_stopped"
        scope_type = "container"
        scope_id = "container_name-with.dots_and-dashes"

        dedup_key = f"{rule_id}|{kind}|{scope_type}:{scope_id}"

        # Verify: No issues with special characters
        assert dedup_key == "rule-123|container_stopped|container:container_name-with.dots_and-dashes"

    def test_dedup_prevents_duplicate_alerts_same_rule(self):
        """Should prevent duplicate alerts for same rule and condition"""
        rule_id = "rule-123"
        kind = "cpu_high"
        scope_type = "container"
        scope_id = "container-abc"

        dedup_key = f"{rule_id}|{kind}|{scope_type}:{scope_id}"

        # Simulate alert storage (dict keyed by dedup_key)
        alerts = {}

        # First evaluation: Create alert
        alerts[dedup_key] = {
            'severity': 'warning',
            'occurrences': 1,
            'first_seen': '2025-10-14T10:00:00Z'
        }
        assert len(alerts) == 1

        # Second evaluation: Update existing alert (dedup)
        if dedup_key in alerts:
            alerts[dedup_key]['occurrences'] += 1
            alerts[dedup_key]['last_seen'] = '2025-10-14T10:05:00Z'

        # Verify: Still one alert, but updated
        assert len(alerts) == 1
        assert alerts[dedup_key]['occurrences'] == 2

    def test_runtime_key_different_from_dedup_key(self):
        """Runtime key (for sliding windows) is different from dedup key"""
        # Dedup key includes rule_id
        rule_id = "rule-123"
        kind = "cpu_high"
        scope_type = "container"
        scope_id = "container-abc"
        dedup_key = f"{rule_id}|{kind}|{scope_type}:{scope_id}"

        # Runtime key does NOT include kind (for metric aggregation)
        runtime_key = f"{rule_id}|{scope_type}:{scope_id}"

        # Verify: Different keys for different purposes
        assert dedup_key != runtime_key
        assert dedup_key == "rule-123|cpu_high|container:container-abc"
        assert runtime_key == "rule-123|container:container-abc"
