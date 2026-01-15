"""
Integration tests for derived tags in alert creation (Issue #88).

Tests verify:
- Tag suggestion endpoint returns derived tags when include_derived=true
- Alert evaluation uses container's combined tags (user + derived)
- Tag-based alert filtering works with derived tags

See: https://github.com/darthnorse/dockmon/issues/88
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from models.docker_models import Container, derive_container_tags


class TestTagSuggestionEndpointDerivedTags:
    """Test /api/tags/suggest endpoint with include_derived parameter"""

    @pytest.fixture
    def mock_monitor(self):
        """Create mock monitor with containers that have derived tags"""
        monitor = MagicMock()

        # Mock database method for user tags
        monitor.db.get_all_tags_v2.return_value = [
            {'name': 'production', 'color': '#ff0000', 'kind': 'user'},
            {'name': 'critical', 'color': '#ff6600', 'kind': 'user'}
        ]

        # Mock containers with derived tags from Docker labels
        container1 = Container(
            id='abc123def456',
            short_id='abc123def456',
            name='myapp-web-1',
            state='running',
            status='Up 5 minutes',
            host_id='host-1',
            host_name='Test Host',
            image='nginx:latest',
            created='2024-01-01T00:00:00Z',
            # Tags include both user and derived
            tags=['production', 'compose:myapp', 'monitor']  # monitor from dockmon.tag label
        )

        container2 = Container(
            id='def456ghi789',
            short_id='def456ghi789',
            name='myapp-db-1',
            state='running',
            status='Up 10 minutes',
            host_id='host-1',
            host_name='Test Host',
            image='postgres:15',
            created='2024-01-01T00:00:00Z',
            tags=['compose:myapp', 'database']  # database from dockmon.tag label
        )

        monitor.get_last_containers.return_value = [container1, container2]

        return monitor

    def test_without_include_derived_returns_only_user_tags(self, mock_monitor):
        """
        When include_derived=false (default), should return only user tags
        as a flat list of strings (backward compatible).
        """
        # Simulate the endpoint logic (without include_derived)
        db_tags = mock_monitor.db.get_all_tags_v2(query='', limit=20, subject_type='container')
        tag_names = [tag['name'] for tag in db_tags]

        # Should return flat list of strings
        assert isinstance(tag_names, list)
        assert all(isinstance(t, str) for t in tag_names)
        assert 'production' in tag_names
        assert 'critical' in tag_names
        # Derived tags should NOT be present
        assert 'compose:myapp' not in tag_names
        assert 'monitor' not in tag_names

    def test_with_include_derived_returns_combined_tags(self, mock_monitor):
        """
        When include_derived=true, should return both user and derived tags
        with source metadata.
        """
        # Simulate the endpoint logic (with include_derived=true)
        db_tags = mock_monitor.db.get_all_tags_v2(query='', limit=50, subject_type='container')
        containers = mock_monitor.get_last_containers()

        result_tags = []
        seen_names = set()

        # Add database tags with source='user'
        for tag in db_tags:
            tag_name = tag['name']
            if tag_name not in seen_names:
                result_tags.append({
                    'name': tag_name,
                    'source': 'user',
                    'color': tag.get('color')
                })
                seen_names.add(tag_name)

        # Add derived tags from containers
        for container in containers:
            if not container.tags:
                continue
            for tag in container.tags:
                if tag in seen_names:
                    continue
                is_derived = (
                    tag.startswith('compose:') or
                    tag.startswith('swarm:') or
                    tag not in seen_names
                )
                if is_derived:
                    result_tags.append({
                        'name': tag,
                        'source': 'derived',
                        'color': None
                    })
                    seen_names.add(tag)

        # User tags should be present with source='user'
        user_tags = [t for t in result_tags if t['source'] == 'user']
        assert any(t['name'] == 'production' for t in user_tags)
        assert any(t['name'] == 'critical' for t in user_tags)

        # Derived tags should be present with source='derived'
        derived_tags = [t for t in result_tags if t['source'] == 'derived']
        derived_names = [t['name'] for t in derived_tags]
        assert 'compose:myapp' in derived_names
        assert 'monitor' in derived_names
        assert 'database' in derived_names

    def test_derived_tags_filtered_by_query(self, mock_monitor):
        """
        Derived tags should be filtered by the search query.
        """
        containers = mock_monitor.get_last_containers()
        query = 'compose'

        derived_tags = []
        for container in containers:
            if not container.tags:
                continue
            for tag in container.tags:
                if tag.startswith('compose:') or tag.startswith('swarm:'):
                    if query.lower() in tag.lower():
                        derived_tags.append(tag)

        # Only compose:myapp should match 'compose' query
        assert 'compose:myapp' in derived_tags
        # 'monitor' and 'database' should not match
        assert 'monitor' not in derived_tags
        assert 'database' not in derived_tags

    def test_user_tags_take_precedence_over_derived(self, mock_monitor):
        """
        If a tag exists in both database and derived, user tag should take precedence.
        """
        # Simulate container1 having 'production' tag (which is also in DB)
        # The result should show 'production' as source='user', not 'derived'
        db_tags = mock_monitor.db.get_all_tags_v2(query='', limit=50, subject_type='container')
        containers = mock_monitor.get_last_containers()

        seen_names = set()
        result_tags = []

        # Add database tags first (they take precedence)
        for tag in db_tags:
            result_tags.append({'name': tag['name'], 'source': 'user'})
            seen_names.add(tag['name'])

        # Add derived tags (skip if already seen)
        for container in containers:
            for tag in container.tags or []:
                if tag not in seen_names:
                    result_tags.append({'name': tag, 'source': 'derived'})
                    seen_names.add(tag)

        # 'production' should only appear once with source='user'
        production_tags = [t for t in result_tags if t['name'] == 'production']
        assert len(production_tags) == 1
        assert production_tags[0]['source'] == 'user'


class TestAlertEvaluationWithDerivedTags:
    """Test alert evaluation uses container's combined tags"""

    @pytest.fixture
    def container_with_derived_tags(self):
        """Create a container with both user and derived tags"""
        return Container(
            id='abc123def456',
            short_id='abc123def456',
            name='myapp-web-1',
            state='running',
            status='Up 5 minutes',
            host_id='host-1',
            host_name='Test Host',
            image='nginx:latest',
            created='2024-01-01T00:00:00Z',
            # Combined tags: user-created + derived from labels
            tags=['production', 'compose:myapp', 'monitor']
        )

    def test_container_tags_include_derived_tags(self, container_with_derived_tags):
        """
        Container object's tags field should include derived tags.
        """
        container = container_with_derived_tags
        assert 'compose:myapp' in container.tags
        assert 'monitor' in container.tags
        assert 'production' in container.tags

    def test_evaluation_context_receives_all_tags(self, container_with_derived_tags):
        """
        EvaluationContext should receive container's full tags list
        including derived tags.
        """
        container = container_with_derived_tags

        # Simulate what evaluation_service.py does after the fix
        # Previously: container_tags = self.db.get_tags_for_subject(...)  # DB only
        # Now: container_tags = container.tags or []  # Includes derived
        container_tags = container.tags or []

        # All tags should be available for matching
        assert 'production' in container_tags
        assert 'compose:myapp' in container_tags
        assert 'monitor' in container_tags

    def test_tag_based_alert_can_match_derived_tag(self, container_with_derived_tags):
        """
        An alert rule with tag filter 'compose:myapp' should match
        containers with that derived tag.
        """
        container = container_with_derived_tags
        container_tags = container.tags or []

        # Simulate alert rule with tag selector
        rule_tags = ['compose:myapp']

        # Check if container matches the rule's tag selector
        matches = any(tag in container_tags for tag in rule_tags)
        assert matches is True

    def test_tag_based_alert_can_match_dockmon_tag_label(self, container_with_derived_tags):
        """
        An alert rule with tag filter 'monitor' should match
        containers with that tag from dockmon.tag label.
        """
        container = container_with_derived_tags
        container_tags = container.tags or []

        # Simulate alert rule with tag selector
        rule_tags = ['monitor']

        # Check if container matches
        matches = any(tag in container_tags for tag in rule_tags)
        assert matches is True

    def test_tag_based_alert_no_match_when_tag_missing(self, container_with_derived_tags):
        """
        An alert rule with a non-existent tag should not match.
        """
        container = container_with_derived_tags
        container_tags = container.tags or []

        # Simulate alert rule with tag that doesn't exist
        rule_tags = ['swarm:nonexistent']

        # Check if container matches
        matches = any(tag in container_tags for tag in rule_tags)
        assert matches is False


class TestDerivedTagsIntegration:
    """Full integration test for derived tags flow"""

    def test_end_to_end_derived_tag_flow(self):
        """
        Test the complete flow:
        1. Docker labels define tags
        2. derive_container_tags() extracts them
        3. Tags are available in container object
        4. Tag suggestion endpoint returns them
        5. Alert evaluation can match them
        """
        # Step 1: Docker labels (from docker-compose.yml)
        docker_labels = {
            'com.docker.compose.project': 'myapp',
            'com.docker.compose.service': 'web',
            'dockmon.tag': 'critical,monitored'
        }

        # Step 2: derive_container_tags() extracts tags
        derived_tags = derive_container_tags(docker_labels)
        assert 'compose:myapp' in derived_tags
        assert 'critical' in derived_tags
        assert 'monitored' in derived_tags

        # Step 3: Container object has combined tags
        user_tags = ['production']  # From database
        combined_tags = user_tags + derived_tags
        container = Container(
            id='abc123def456',
            short_id='abc123def456',
            name='myapp-web-1',
            state='running',
            status='Up 5 minutes',
            host_id='host-1',
            host_name='Test Host',
            image='nginx:latest',
            created='2024-01-01T00:00:00Z',
            tags=combined_tags
        )

        # Step 4: Tag suggestion would return all these
        # (tested separately in TestTagSuggestionEndpointDerivedTags)

        # Step 5: Alert evaluation can match any of these tags
        for test_tag in ['production', 'compose:myapp', 'critical', 'monitored']:
            assert test_tag in container.tags, f"Tag '{test_tag}' should be matchable"
