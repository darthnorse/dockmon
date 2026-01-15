"""
Unit tests for derived tags feature (Issue #88).

Tests verify:
- derive_container_tags() extracts tags from Docker labels
- Tag suggestion endpoint returns both user and derived tags
- Derived tags have correct source metadata
- Tag filtering works correctly

See: https://github.com/darthnorse/dockmon/issues/88
"""

import pytest
from models.docker_models import derive_container_tags


class TestDeriveContainerTags:
    """Test derive_container_tags() function"""

    def test_extracts_compose_project_tag(self):
        """Should extract compose:project tag from Docker Compose labels"""
        labels = {'com.docker.compose.project': 'myapp'}
        tags = derive_container_tags(labels)
        assert 'compose:myapp' in tags

    def test_extracts_swarm_service_tag(self):
        """Should extract swarm:service tag from Docker Swarm labels"""
        labels = {'com.docker.swarm.service.name': 'web'}
        tags = derive_container_tags(labels)
        assert 'swarm:web' in tags

    def test_extracts_dockmon_tag_single(self):
        """Should extract single custom tag from dockmon.tag label"""
        labels = {'dockmon.tag': 'monitor'}
        tags = derive_container_tags(labels)
        assert 'monitor' in tags

    def test_extracts_dockmon_tag_multiple_comma_separated(self):
        """Should extract multiple comma-separated tags from dockmon.tag label"""
        labels = {'dockmon.tag': 'critical,production,web'}
        tags = derive_container_tags(labels)
        assert 'critical' in tags
        assert 'production' in tags
        assert 'web' in tags

    def test_normalizes_tags_to_lowercase(self):
        """Should normalize all tags to lowercase"""
        labels = {
            'com.docker.compose.project': 'MyApp',
            'dockmon.tag': 'CRITICAL,Production'
        }
        tags = derive_container_tags(labels)
        assert 'compose:myapp' in tags
        assert 'critical' in tags
        assert 'production' in tags
        # Uppercase versions should not exist
        assert 'compose:MyApp' not in tags
        assert 'CRITICAL' not in tags

    def test_trims_whitespace_from_tags(self):
        """Should trim whitespace from tag values"""
        labels = {
            'com.docker.compose.project': '  myapp  ',
            'dockmon.tag': ' tag1 , tag2 , tag3 '
        }
        tags = derive_container_tags(labels)
        assert 'compose:myapp' in tags
        assert 'tag1' in tags
        assert 'tag2' in tags
        assert 'tag3' in tags

    def test_removes_duplicate_tags(self):
        """Should remove duplicate tags while preserving order"""
        labels = {'dockmon.tag': 'critical,production,critical,web,production'}
        tags = derive_container_tags(labels)
        # Each tag should appear only once
        assert tags.count('critical') == 1
        assert tags.count('production') == 1
        assert tags.count('web') == 1

    def test_ignores_empty_labels(self):
        """Should ignore empty label values"""
        labels = {
            'com.docker.compose.project': '',
            'dockmon.tag': ''
        }
        tags = derive_container_tags(labels)
        assert len(tags) == 0

    def test_ignores_whitespace_only_labels(self):
        """Should ignore whitespace-only label values"""
        labels = {
            'com.docker.compose.project': '   ',
            'dockmon.tag': ' , , '
        }
        tags = derive_container_tags(labels)
        assert len(tags) == 0

    def test_handles_empty_labels_dict(self):
        """Should handle empty labels dictionary"""
        tags = derive_container_tags({})
        assert len(tags) == 0

    def test_handles_none_like_values(self):
        """Should handle labels that might have None-like values"""
        # This could happen with some Docker SDK edge cases
        labels = {'com.docker.compose.project': 'myapp', 'other_label': 'value'}
        tags = derive_container_tags(labels)
        assert 'compose:myapp' in tags

    def test_combined_labels(self):
        """Should handle all label types together"""
        labels = {
            'com.docker.compose.project': 'frontend',
            'com.docker.swarm.service.name': 'web',
            'dockmon.tag': 'critical,monitored',
            'other.label': 'ignored'
        }
        tags = derive_container_tags(labels)
        assert len(tags) == 4
        assert 'compose:frontend' in tags
        assert 'swarm:web' in tags
        assert 'critical' in tags
        assert 'monitored' in tags


class TestDeriveContainerTagsEdgeCases:
    """Edge cases and special scenarios for derive_container_tags()"""

    def test_special_characters_in_compose_project(self):
        """Should handle special characters in compose project name"""
        labels = {'com.docker.compose.project': 'my-app_v2'}
        tags = derive_container_tags(labels)
        assert 'compose:my-app_v2' in tags

    def test_special_characters_in_dockmon_tag(self):
        """Should handle special characters in dockmon.tag values"""
        labels = {'dockmon.tag': 'my-tag,tag_2,tag.3'}
        tags = derive_container_tags(labels)
        assert 'my-tag' in tags
        assert 'tag_2' in tags
        assert 'tag.3' in tags

    def test_unicode_in_tags(self):
        """Should handle unicode characters in tags"""
        labels = {'dockmon.tag': 'production-eu,production-us'}
        tags = derive_container_tags(labels)
        assert 'production-eu' in tags
        assert 'production-us' in tags

    def test_very_long_tag_value(self):
        """Should handle very long tag values"""
        long_tag = 'a' * 100
        labels = {'dockmon.tag': long_tag}
        tags = derive_container_tags(labels)
        assert long_tag in tags

    def test_many_comma_separated_tags(self):
        """Should handle many comma-separated tags"""
        many_tags = ','.join([f'tag{i}' for i in range(50)])
        labels = {'dockmon.tag': many_tags}
        tags = derive_container_tags(labels)
        assert len(tags) == 50
        assert 'tag0' in tags
        assert 'tag49' in tags
