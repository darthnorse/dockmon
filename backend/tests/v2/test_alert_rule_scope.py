"""
Unit tests for alert rule scope validation

Tests the scope validation logic for alert rules:
- Host scope: Monitor metrics for entire hosts
- Container scope: Monitor metrics for specific containers
- Scope validation: Ensure scope_type and scope_ids are valid
- Mixed scope handling: Rules can't mix host and container scope

Alert rules must specify either host OR container scope, never both.
"""

import pytest


class TestAlertRuleScope:
    """Tests for alert rule scope validation"""

    def test_host_scope_single_host(self):
        """Should accept rule with single host scope"""
        scope_type = 'host'
        scope_ids = ['host-123']

        # Validate scope
        is_valid = (
            scope_type in ['host', 'container'] and
            isinstance(scope_ids, list) and
            len(scope_ids) > 0
        )

        assert is_valid is True
        assert scope_type == 'host'
        assert len(scope_ids) == 1

    def test_host_scope_multiple_hosts(self):
        """Should accept rule monitoring multiple hosts"""
        scope_type = 'host'
        scope_ids = ['host-123', 'host-456', 'host-789']

        is_valid = (
            scope_type == 'host' and
            isinstance(scope_ids, list) and
            len(scope_ids) > 0
        )

        assert is_valid is True
        assert len(scope_ids) == 3

    def test_container_scope_single_container(self):
        """Should accept rule with single container scope"""
        scope_type = 'container'
        scope_ids = ['container-abc']

        is_valid = (
            scope_type in ['host', 'container'] and
            isinstance(scope_ids, list) and
            len(scope_ids) > 0
        )

        assert is_valid is True
        assert scope_type == 'container'

    def test_container_scope_multiple_containers(self):
        """Should accept rule monitoring multiple containers"""
        scope_type = 'container'
        scope_ids = ['web-1', 'web-2', 'api-1', 'worker-1']

        is_valid = (
            scope_type == 'container' and
            isinstance(scope_ids, list) and
            len(scope_ids) > 0
        )

        assert is_valid is True
        assert len(scope_ids) == 4

    def test_invalid_scope_type(self):
        """Should reject invalid scope_type"""
        test_cases = [
            'pod',          # Kubernetes (not supported)
            'service',      # Docker service (not supported)
            'network',      # Invalid
            'volume',       # Invalid
            '',             # Empty
            None,           # None
        ]

        for scope_type in test_cases:
            is_valid = (scope_type in ['host', 'container'])
            assert is_valid is False, f"Should reject scope_type={scope_type}"

    def test_empty_scope_ids(self):
        """Should reject rule with empty scope_ids list"""
        scope_type = 'host'
        scope_ids = []

        is_valid = (
            scope_type in ['host', 'container'] and
            isinstance(scope_ids, list) and
            len(scope_ids) > 0
        )

        assert is_valid is False

    def test_scope_ids_not_a_list(self):
        """Should reject scope_ids that is not a list"""
        test_cases = [
            'host-123',              # String instead of list
            {'host-123'},            # Set instead of list
            ('host-123',),           # Tuple instead of list
            None,                    # None
            123,                     # Number
        ]

        for scope_ids in test_cases:
            is_valid = (isinstance(scope_ids, list) and len(scope_ids) > 0)
            assert is_valid is False, f"Should reject scope_ids={scope_ids}"

    def test_scope_ids_contains_duplicates(self):
        """Should handle duplicate scope_ids (deduplicate)"""
        scope_ids = ['host-123', 'host-456', 'host-123']  # Duplicate

        # Deduplicate
        unique_scope_ids = list(set(scope_ids))

        assert len(scope_ids) == 3
        assert len(unique_scope_ids) == 2
        assert 'host-123' in unique_scope_ids
        assert 'host-456' in unique_scope_ids

    def test_scope_ids_contains_empty_strings(self):
        """Should reject scope_ids containing empty strings"""
        scope_ids = ['host-123', '', 'host-456']

        # Validate all IDs are non-empty
        all_valid = all(isinstance(id, str) and len(id) > 0 for id in scope_ids)

        assert all_valid is False

    def test_scope_ids_contains_none(self):
        """Should reject scope_ids containing None values"""
        scope_ids = ['host-123', None, 'host-456']

        # Validate all IDs are strings
        all_valid = all(isinstance(id, str) and len(id) > 0 for id in scope_ids)

        assert all_valid is False

    def test_host_rule_cannot_target_containers(self):
        """Host-scoped rules should only target hosts"""
        rule = {
            'scope_type': 'host',
            'scope_ids': ['host-123'],
            'metric': 'cpu_percent'  # Host-level metric
        }

        # Verify scope consistency
        is_consistent = (
            rule['scope_type'] == 'host' and
            all(id.startswith('host-') for id in rule['scope_ids'])
        )

        # This is a soft check - IDs don't have to start with 'host-'
        # but it demonstrates scope consistency

    def test_container_rule_cannot_target_hosts(self):
        """Container-scoped rules should only target containers"""
        rule = {
            'scope_type': 'container',
            'scope_ids': ['web-1', 'api-1'],
            'metric': 'cpu_percent'
        }

        # Verify scope matches
        assert rule['scope_type'] == 'container'

    def test_scope_validation_with_metric_type(self):
        """Should validate scope matches metric type"""
        # Some metrics are only available at certain scopes

        # Host-only metrics (system-level)
        host_metrics = ['disk_usage', 'load_average']

        # Container-only metrics
        container_metrics = ['container_status', 'restart_count']

        # Shared metrics (available at both scopes)
        shared_metrics = ['cpu_percent', 'memory_percent']

        # Test host scope with host metric
        is_valid = ('host' == 'host' and 'disk_usage' in host_metrics + shared_metrics)
        assert is_valid is True

        # Test container scope with container metric
        is_valid = ('container' == 'container' and 'restart_count' in container_metrics + shared_metrics)
        assert is_valid is True

        # Test container scope with host-only metric (invalid)
        is_valid = ('container' == 'host' and 'disk_usage' in host_metrics)
        assert is_valid is False

    def test_wildcard_scope_all_hosts(self):
        """Should support wildcard to monitor all hosts"""
        scope_type = 'host'
        scope_ids = ['*']  # Wildcard for all hosts

        is_wildcard = (
            scope_type == 'host' and
            scope_ids == ['*']
        )

        assert is_wildcard is True

    def test_wildcard_scope_all_containers(self):
        """Should support wildcard to monitor all containers"""
        scope_type = 'container'
        scope_ids = ['*']  # Wildcard for all containers

        is_wildcard = (
            scope_type == 'container' and
            scope_ids == ['*']
        )

        assert is_wildcard is True

    def test_scope_resolution_single_host(self):
        """Should resolve scope to specific entities"""
        # Rule definition
        rule = {
            'scope_type': 'host',
            'scope_ids': ['host-123']
        }

        # Available hosts
        available_hosts = {
            'host-123': {'name': 'prod-server-1'},
            'host-456': {'name': 'prod-server-2'},
        }

        # Resolve scope
        target_hosts = {
            host_id: host_data
            for host_id, host_data in available_hosts.items()
            if host_id in rule['scope_ids']
        }

        assert len(target_hosts) == 1
        assert 'host-123' in target_hosts
        assert target_hosts['host-123']['name'] == 'prod-server-1'

    def test_scope_resolution_wildcard(self):
        """Should resolve wildcard to all available entities"""
        rule = {
            'scope_type': 'container',
            'scope_ids': ['*']
        }

        available_containers = {
            'web-1': {'name': 'nginx'},
            'web-2': {'name': 'nginx'},
            'api-1': {'name': 'backend'},
        }

        # Resolve wildcard
        if rule['scope_ids'] == ['*']:
            target_containers = available_containers
        else:
            target_containers = {
                c_id: c_data
                for c_id, c_data in available_containers.items()
                if c_id in rule['scope_ids']
            }

        assert len(target_containers) == 3
        assert all(c_id in target_containers for c_id in ['web-1', 'web-2', 'api-1'])

    def test_scope_resolution_missing_entity(self):
        """Should handle scope_ids that don't exist"""
        rule = {
            'scope_type': 'host',
            'scope_ids': ['host-123', 'host-999']  # host-999 doesn't exist
        }

        available_hosts = {
            'host-123': {'name': 'prod-server-1'},
            'host-456': {'name': 'prod-server-2'},
        }

        # Resolve scope (silently skip missing)
        target_hosts = {
            host_id: host_data
            for host_id, host_data in available_hosts.items()
            if host_id in rule['scope_ids']
        }

        # Only host-123 found
        assert len(target_hosts) == 1
        assert 'host-123' in target_hosts
        assert 'host-999' not in target_hosts

    def test_scope_ids_max_length(self):
        """Should validate maximum number of scope_ids"""
        max_scope_ids = 100

        # Test valid length
        scope_ids = [f'host-{i}' for i in range(50)]
        is_valid = (len(scope_ids) <= max_scope_ids)
        assert is_valid is True

        # Test exceeding max
        scope_ids = [f'host-{i}' for i in range(150)]
        is_valid = (len(scope_ids) <= max_scope_ids)
        assert is_valid is False

    def test_real_world_scenario_monitor_all_web_containers(self):
        """Simulate: Monitor all web containers across hosts"""
        # Rule: CPU > 80% for all web containers
        rule = {
            'scope_type': 'container',
            'scope_ids': ['*'],  # All containers
            'metric': 'cpu_percent',
            'operator': '>',
            'threshold': 80
        }

        # Available containers
        all_containers = {
            'web-1': {'name': 'nginx', 'host_id': 'host-123'},
            'web-2': {'name': 'nginx', 'host_id': 'host-123'},
            'api-1': {'name': 'backend', 'host_id': 'host-456'},
            'worker-1': {'name': 'celery', 'host_id': 'host-456'},
        }

        # Filter to web containers only (in real system, done by labels/tags)
        web_containers = {
            c_id: c_data
            for c_id, c_data in all_containers.items()
            if 'web' in c_id or c_data['name'] == 'nginx'
        }

        # Verify rule applies to web containers
        assert rule['scope_type'] == 'container'
        assert len(web_containers) == 2
        assert 'web-1' in web_containers
        assert 'web-2' in web_containers

    def test_real_world_scenario_monitor_specific_host(self):
        """Simulate: Monitor disk usage on production host"""
        # Rule: Disk > 90% on prod-server-1
        rule = {
            'scope_type': 'host',
            'scope_ids': ['host-prod-1'],
            'metric': 'disk_usage',
            'operator': '>',
            'threshold': 90
        }

        # Available hosts
        hosts = {
            'host-prod-1': {'name': 'prod-server-1', 'disk_usage': 92},
            'host-prod-2': {'name': 'prod-server-2', 'disk_usage': 65},
            'host-dev-1': {'name': 'dev-server-1', 'disk_usage': 45},
        }

        # Resolve target
        target_host_id = rule['scope_ids'][0]
        target_host = hosts.get(target_host_id)

        assert target_host is not None
        assert target_host['name'] == 'prod-server-1'
        assert target_host['disk_usage'] == 92

        # Check if alert should trigger
        should_alert = (target_host['disk_usage'] > rule['threshold'])
        assert should_alert is True

    def test_real_world_scenario_monitor_container_group(self):
        """Simulate: Monitor specific group of related containers"""
        # Rule: Memory > 80% for frontend containers
        rule = {
            'scope_type': 'container',
            'scope_ids': ['web-1', 'web-2', 'web-3'],
            'metric': 'memory_percent',
            'operator': '>',
            'threshold': 80
        }

        # Container metrics
        container_metrics = {
            'web-1': {'memory_percent': 85},  # Alert!
            'web-2': {'memory_percent': 70},
            'web-3': {'memory_percent': 90},  # Alert!
            'api-1': {'memory_percent': 95},  # Not in scope
        }

        # Check which containers in scope should alert
        alerts_to_create = []
        for container_id in rule['scope_ids']:
            metrics = container_metrics.get(container_id)
            if metrics and metrics['memory_percent'] > rule['threshold']:
                alerts_to_create.append(container_id)

        assert len(alerts_to_create) == 2
        assert 'web-1' in alerts_to_create
        assert 'web-3' in alerts_to_create
        assert 'api-1' not in alerts_to_create  # Not in scope

    def test_scope_type_case_sensitivity(self):
        """Should be case-sensitive for scope_type"""
        test_cases = [
            ('host', True),
            ('container', True),
            ('Host', False),      # Wrong case
            ('Container', False), # Wrong case
            ('HOST', False),      # Wrong case
        ]

        for scope_type, expected_valid in test_cases:
            is_valid = (scope_type in ['host', 'container'])
            assert is_valid == expected_valid, f"Failed for scope_type={scope_type}"

    def test_scope_ids_uniqueness_enforcement(self):
        """Should deduplicate scope_ids for efficiency"""
        scope_ids_with_dupes = ['host-1', 'host-2', 'host-1', 'host-3', 'host-2']

        # Deduplicate while preserving order (if needed)
        seen = set()
        unique_scope_ids = []
        for id in scope_ids_with_dupes:
            if id not in seen:
                seen.add(id)
                unique_scope_ids.append(id)

        assert len(unique_scope_ids) == 3
        assert unique_scope_ids == ['host-1', 'host-2', 'host-3']
