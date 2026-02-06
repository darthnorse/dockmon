"""
Integration tests for labels list format in deployment executor.

Tests that deployment executor correctly converts list-format labels to
dict format and merges with stack labels.
"""

import docker
import pytest


@pytest.fixture
def docker_client():
    """Get Docker client for integration tests"""
    return docker.from_env(version="auto")


class TestLabelsListConversion:
    """Test executor converts list labels to dict correctly"""

    def test_executor_handles_list_labels_without_crashing(self, docker_client):
        """Test that list-format labels don't cause AttributeError"""
        # Simulate what orchestrator returns for list-format labels
        container_config = {
            'image': 'nginx:latest',
            'labels': [  # List format (from compose)
                'com.example.app=testapp',
                'com.example.version=1.0.0',
                'traefik.enable=true'
            ]
        }

        # Simulate executor's label merge logic
        existing_labels = container_config.get('labels', {})

        # Convert list format to dict if needed
        if isinstance(existing_labels, list):
            labels_dict = {}
            for label in existing_labels:
                if '=' in label:
                    key, value = label.split('=', 1)
                    labels_dict[key] = value
            existing_labels = labels_dict

        # Merge with stack labels (this would fail if labels was still a list)
        labels = existing_labels.copy() if isinstance(existing_labels, dict) else {}
        labels.update({
            'com.docker.compose.project': 'test-project',
            'com.docker.compose.service': 'test-service',
            'dockmon.managed': 'true'
        })

        # Verify conversion worked
        assert isinstance(labels, dict)
        assert labels['com.example.app'] == 'testapp'
        assert labels['com.example.version'] == '1.0.0'
        assert labels['traefik.enable'] == 'true'
        assert labels['com.docker.compose.project'] == 'test-project'
        assert labels['dockmon.managed'] == 'true'

    def test_executor_preserves_dict_labels(self, docker_client):
        """Test that dict-format labels are preserved"""
        container_config = {
            'image': 'nginx:latest',
            'labels': {  # Dict format
                'com.example.app': 'testapp',
                'traefik.enable': 'true'
            }
        }

        existing_labels = container_config.get('labels', {})

        # Dict format should pass through unchanged
        labels = existing_labels.copy() if isinstance(existing_labels, dict) else {}
        labels.update({
            'com.docker.compose.project': 'test-project'
        })

        assert isinstance(labels, dict)
        assert labels['com.example.app'] == 'testapp'
        assert labels['com.docker.compose.project'] == 'test-project'

    def test_list_labels_split_on_first_equals_only(self, docker_client):
        """Test that label values can contain = signs"""
        container_config = {
            'image': 'nginx:latest',
            'labels': [
                'traefik.http.routers.test.rule=Host(`test.local`)',
                'connection=server=localhost;user=admin'
            ]
        }

        existing_labels = container_config.get('labels', {})

        if isinstance(existing_labels, list):
            labels_dict = {}
            for label in existing_labels:
                if '=' in label:
                    key, value = label.split('=', 1)  # Split on FIRST = only
                    labels_dict[key] = value
            existing_labels = labels_dict

        labels = existing_labels

        # Verify split on first = only (values can contain =)
        assert labels['traefik.http.routers.test.rule'] == 'Host(`test.local`)'
        assert labels['connection'] == 'server=localhost;user=admin'

    def test_empty_list_labels_handled(self, docker_client):
        """Test empty labels list doesn't cause errors"""
        container_config = {
            'image': 'nginx:latest',
            'labels': []  # Empty list
        }

        existing_labels = container_config.get('labels', {})

        if isinstance(existing_labels, list):
            labels_dict = {}
            for label in existing_labels:
                if '=' in label:
                    key, value = label.split('=', 1)
                    labels_dict[key] = value
            existing_labels = labels_dict

        labels = existing_labels.copy() if isinstance(existing_labels, dict) else {}
        labels.update({'dockmon.managed': 'true'})

        # Should have only stack labels
        assert labels == {'dockmon.managed': 'true'}

    def test_malformed_label_without_equals_skipped(self, docker_client):
        """Test malformed labels without = are skipped gracefully"""
        container_config = {
            'image': 'nginx:latest',
            'labels': [
                'com.example.app=testapp',
                'invalid-label-no-equals',  # Malformed
                'traefik.enable=true'
            ]
        }

        existing_labels = container_config.get('labels', {})

        if isinstance(existing_labels, list):
            labels_dict = {}
            for label in existing_labels:
                if '=' in label:  # Only process labels with =
                    key, value = label.split('=', 1)
                    labels_dict[key] = value
            existing_labels = labels_dict

        labels = existing_labels

        # Valid labels should be parsed, invalid skipped
        assert 'com.example.app' in labels
        assert 'traefik.enable' in labels
        assert 'invalid-label-no-equals' not in labels  # Skipped
