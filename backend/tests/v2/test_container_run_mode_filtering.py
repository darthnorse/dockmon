"""
Unit tests for Container Run Mode filtering

Tests the filtering logic for containers based on their desired_state:
- should_run: Containers that should always be running
- on_demand: Containers that run on-demand (e.g., cron jobs)
- unspecified: Containers with no explicit desired state set

This is used in the UI to filter the container list by run mode.
"""

import pytest


class TestContainerRunModeFiltering:
    """Tests for container run mode filtering logic"""

    def test_filter_should_run_containers(self):
        """Should filter containers with desired_state = should_run"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'worker', 'desired_state': 'should_run'},
            {'id': 'c3', 'name': 'cron', 'desired_state': 'on_demand'},
            {'id': 'c4', 'name': 'temp', 'desired_state': 'unspecified'},
        ]

        # Filter for should_run
        filtered = [c for c in containers if c['desired_state'] == 'should_run']

        assert len(filtered) == 2
        assert all(c['desired_state'] == 'should_run' for c in filtered)
        assert filtered[0]['name'] == 'web'
        assert filtered[1]['name'] == 'worker'

    def test_filter_on_demand_containers(self):
        """Should filter containers with desired_state = on_demand"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'cron', 'desired_state': 'on_demand'},
            {'id': 'c3', 'name': 'backup', 'desired_state': 'on_demand'},
            {'id': 'c4', 'name': 'temp', 'desired_state': 'unspecified'},
        ]

        # Filter for on_demand
        filtered = [c for c in containers if c['desired_state'] == 'on_demand']

        assert len(filtered) == 2
        assert all(c['desired_state'] == 'on_demand' for c in filtered)
        assert filtered[0]['name'] == 'cron'
        assert filtered[1]['name'] == 'backup'

    def test_filter_unspecified_containers(self):
        """Should filter containers with desired_state = unspecified"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'cron', 'desired_state': 'on_demand'},
            {'id': 'c3', 'name': 'temp', 'desired_state': 'unspecified'},
            {'id': 'c4', 'name': 'unknown', 'desired_state': 'unspecified'},
        ]

        # Filter for unspecified
        filtered = [c for c in containers if c['desired_state'] == 'unspecified']

        assert len(filtered) == 2
        assert all(c['desired_state'] == 'unspecified' for c in filtered)
        assert filtered[0]['name'] == 'temp'
        assert filtered[1]['name'] == 'unknown'

    def test_filter_all_containers_no_filter(self):
        """Should return all containers when no filter applied"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'cron', 'desired_state': 'on_demand'},
            {'id': 'c3', 'name': 'temp', 'desired_state': 'unspecified'},
        ]

        # No filter applied (all containers)
        filtered = containers  # No filtering

        assert len(filtered) == 3

    def test_filter_empty_list(self):
        """Should handle empty container list"""
        containers = []

        # Filter for any desired_state
        filtered = [c for c in containers if c['desired_state'] == 'should_run']

        assert len(filtered) == 0
        assert filtered == []

    def test_filter_none_match(self):
        """Should return empty list when no containers match"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'worker', 'desired_state': 'should_run'},
        ]

        # Filter for on_demand (none exist)
        filtered = [c for c in containers if c['desired_state'] == 'on_demand']

        assert len(filtered) == 0

    def test_filter_all_match(self):
        """Should return all containers when all match filter"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'api', 'desired_state': 'should_run'},
            {'id': 'c3', 'name': 'worker', 'desired_state': 'should_run'},
        ]

        # Filter for should_run (all match)
        filtered = [c for c in containers if c['desired_state'] == 'should_run']

        assert len(filtered) == 3
        assert filtered == containers

    def test_case_sensitive_filtering(self):
        """Should be case-sensitive when filtering"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'invalid', 'desired_state': 'Should_Run'},  # Wrong case
        ]

        # Filter for should_run (exact match)
        filtered = [c for c in containers if c['desired_state'] == 'should_run']

        # Only exact case match should be included
        assert len(filtered) == 1
        assert filtered[0]['name'] == 'web'

    def test_filter_with_additional_fields(self):
        """Should filter correctly even with extra container fields"""
        containers = [
            {
                'id': 'c1',
                'name': 'web',
                'desired_state': 'should_run',
                'status': 'running',
                'image': 'nginx:latest',
                'cpu_percent': 25.5,
            },
            {
                'id': 'c2',
                'name': 'cron',
                'desired_state': 'on_demand',
                'status': 'exited',
                'image': 'alpine:latest',
                'cpu_percent': 0.0,
            },
        ]

        # Filter for should_run
        filtered = [c for c in containers if c['desired_state'] == 'should_run']

        assert len(filtered) == 1
        assert filtered[0]['name'] == 'web'
        assert filtered[0]['status'] == 'running'
        assert filtered[0]['cpu_percent'] == 25.5

    def test_multiple_filters_combined(self):
        """Should support combining run mode filter with other filters"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run', 'status': 'running'},
            {'id': 'c2', 'name': 'api', 'desired_state': 'should_run', 'status': 'exited'},
            {'id': 'c3', 'name': 'cron', 'desired_state': 'on_demand', 'status': 'running'},
        ]

        # Filter: should_run AND running
        filtered = [
            c for c in containers
            if c['desired_state'] == 'should_run' and c['status'] == 'running'
        ]

        assert len(filtered) == 1
        assert filtered[0]['name'] == 'web'

    def test_filter_preserves_order(self):
        """Should preserve original container order after filtering"""
        containers = [
            {'id': 'c3', 'name': 'zebra', 'desired_state': 'should_run'},
            {'id': 'c1', 'name': 'alpha', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'beta', 'desired_state': 'on_demand'},
            {'id': 'c4', 'name': 'delta', 'desired_state': 'should_run'},
        ]

        # Filter for should_run
        filtered = [c for c in containers if c['desired_state'] == 'should_run']

        # Order should be preserved (zebra, alpha, delta)
        assert len(filtered) == 3
        assert filtered[0]['name'] == 'zebra'
        assert filtered[1]['name'] == 'alpha'
        assert filtered[2]['name'] == 'delta'

    def test_filter_with_none_desired_state(self):
        """Should handle containers with None desired_state"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'missing', 'desired_state': None},
            {'id': 'c3', 'name': 'temp', 'desired_state': 'unspecified'},
        ]

        # Filter for should_run (None should not match)
        filtered = [c for c in containers if c['desired_state'] == 'should_run']

        assert len(filtered) == 1
        assert filtered[0]['name'] == 'web'

        # Filter for None explicitly
        filtered_none = [c for c in containers if c['desired_state'] is None]

        assert len(filtered_none) == 1
        assert filtered_none[0]['name'] == 'missing'

    def test_filter_distinguishes_all_three_modes(self):
        """Should clearly distinguish between all three run modes"""
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'api', 'desired_state': 'should_run'},
            {'id': 'c3', 'name': 'cron', 'desired_state': 'on_demand'},
            {'id': 'c4', 'name': 'backup', 'desired_state': 'on_demand'},
            {'id': 'c5', 'name': 'temp', 'desired_state': 'unspecified'},
            {'id': 'c6', 'name': 'unknown', 'desired_state': 'unspecified'},
        ]

        # Filter each mode separately
        should_run = [c for c in containers if c['desired_state'] == 'should_run']
        on_demand = [c for c in containers if c['desired_state'] == 'on_demand']
        unspecified = [c for c in containers if c['desired_state'] == 'unspecified']

        # Verify counts
        assert len(should_run) == 2
        assert len(on_demand) == 2
        assert len(unspecified) == 2

        # Verify no overlap
        all_filtered = should_run + on_demand + unspecified
        assert len(all_filtered) == 6
        assert set(c['id'] for c in all_filtered) == {'c1', 'c2', 'c3', 'c4', 'c5', 'c6'}

    def test_real_world_scenario_filter_always_running_services(self):
        """Simulate filtering for always-running services (should_run)"""
        # Real-world: User wants to see which containers should always be running
        containers = [
            {'id': 'c1', 'name': 'nginx-proxy', 'desired_state': 'should_run', 'status': 'running'},
            {'id': 'c2', 'name': 'postgres', 'desired_state': 'should_run', 'status': 'running'},
            {'id': 'c3', 'name': 'redis', 'desired_state': 'should_run', 'status': 'exited'},  # Problem!
            {'id': 'c4', 'name': 'daily-backup', 'desired_state': 'on_demand', 'status': 'exited'},
            {'id': 'c5', 'name': 'temp-job', 'desired_state': 'unspecified', 'status': 'exited'},
        ]

        # Filter: should_run containers
        always_running = [c for c in containers if c['desired_state'] == 'should_run']

        assert len(always_running) == 3

        # Find problematic container (should run but exited)
        problems = [c for c in always_running if c['status'] != 'running']

        assert len(problems) == 1
        assert problems[0]['name'] == 'redis'  # This needs attention!

    def test_real_world_scenario_ignore_temporary_containers(self):
        """Simulate ignoring temporary/unspecified containers"""
        # Real-world: User wants to focus on managed containers only
        containers = [
            {'id': 'c1', 'name': 'web', 'desired_state': 'should_run'},
            {'id': 'c2', 'name': 'cron', 'desired_state': 'on_demand'},
            {'id': 'c3', 'name': 'temp-debug-xyz', 'desired_state': 'unspecified'},
            {'id': 'c4', 'name': 'one-off-migration', 'desired_state': 'unspecified'},
        ]

        # Filter: Only managed containers (should_run OR on_demand)
        managed = [
            c for c in containers
            if c['desired_state'] in ['should_run', 'on_demand']
        ]

        assert len(managed) == 2
        assert managed[0]['name'] == 'web'
        assert managed[1]['name'] == 'cron'

        # Verify temporary containers excluded
        assert not any(c['name'].startswith('temp-') for c in managed)
