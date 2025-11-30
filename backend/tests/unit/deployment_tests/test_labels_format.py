"""
Unit tests for labels format handling in stack orchestrator.

Tests that both Docker Compose label formats (list and dict) are correctly
parsed and converted to Docker SDK dict format.
"""

import pytest
from deployment.stack_orchestrator import StackOrchestrator


class TestLabelsListFormat:
    """Test labels in list format (key=value strings)"""

    def test_parse_labels_list_format(self):
        """Test labels as list of key=value strings"""
        service_config = {
            'image': 'nginx:latest',
            'labels': [
                'com.example.app=myapp',
                'com.example.version=1.0.0',
                'traefik.enable=true'
            ]
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        labels = config.get('labels')
        assert labels == [
            'com.example.app=myapp',
            'com.example.version=1.0.0',
            'traefik.enable=true'
        ]

    def test_parse_labels_with_values_containing_equals(self):
        """Test label values that contain = signs"""
        service_config = {
            'image': 'nginx:latest',
            'labels': [
                'traefik.http.routers.test.rule=Host(`test.local`)',
                'connection.string=server=localhost;user=admin'
            ]
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        labels = config.get('labels')
        # Should preserve = in values (split on first = only)
        assert 'traefik.http.routers.test.rule=Host(`test.local`)' in labels
        assert 'connection.string=server=localhost;user=admin' in labels

    def test_parse_empty_labels_list(self):
        """Test empty labels list"""
        service_config = {
            'image': 'nginx:latest',
            'labels': []
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        labels = config.get('labels')
        assert labels == []


class TestLabelsDictFormat:
    """Test labels in dict format (key: value pairs)"""

    def test_parse_labels_dict_format(self):
        """Test labels as dict (key: value)"""
        service_config = {
            'image': 'nginx:latest',
            'labels': {
                'com.example.app': 'myapp',
                'com.example.version': '1.0.0',
                'traefik.enable': 'true'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        labels = config.get('labels')
        assert labels == {
            'com.example.app': 'myapp',
            'com.example.version': '1.0.0',
            'traefik.enable': 'true'
        }

    def test_parse_labels_dict_with_special_characters(self):
        """Test labels dict with special characters in values"""
        service_config = {
            'image': 'nginx:latest',
            'labels': {
                'traefik.http.routers.test.rule': 'Host(`test.local`)',
                'description': 'My app with "quotes" and special chars'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        labels = config.get('labels')
        assert labels['traefik.http.routers.test.rule'] == 'Host(`test.local`)'
        assert 'quotes' in labels['description']

    def test_parse_empty_labels_dict(self):
        """Test empty labels dict"""
        service_config = {
            'image': 'nginx:latest',
            'labels': {}
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        labels = config.get('labels')
        assert labels == {}


class TestLabelsEdgeCases:
    """Test edge cases in labels parsing"""

    def test_no_labels_directive(self):
        """Test service without labels"""
        service_config = {
            'image': 'nginx:latest'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # No labels key should be present
        assert 'labels' not in config

    def test_labels_with_numeric_values(self):
        """Test labels with numeric values in dict format"""
        service_config = {
            'image': 'nginx:latest',
            'labels': {
                'version': 1.0,  # Numeric, not string
                'port': 8080
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        labels = config.get('labels')
        # Numeric values should be preserved (Docker SDK converts to strings)
        assert 'version' in labels
        assert 'port' in labels


class TestRealWorldLabels:
    """Test real-world label configurations"""

    def test_traefik_labels_list_format(self):
        """Test typical Traefik configuration with list labels"""
        service_config = {
            'image': 'nginx:latest',
            'labels': [
                'traefik.enable=true',
                'traefik.http.routers.myapp.rule=Host(`myapp.example.com`)',
                'traefik.http.routers.myapp.entrypoints=websecure',
                'traefik.http.routers.myapp.tls.certresolver=letsencrypt'
            ]
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='myapp',
            service_config=service_config
        )

        labels = config.get('labels')
        assert len(labels) == 4
        assert 'traefik.enable=true' in labels

    def test_mixed_infrastructure_labels_dict_format(self):
        """Test labels from multiple infrastructure tools (dict format)"""
        service_config = {
            'image': 'nginx:latest',
            'labels': {
                'traefik.enable': 'true',
                'prometheus.scrape': 'true',
                'prometheus.port': '9090',
                'com.example.team': 'platform',
                'com.example.environment': 'production'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        labels = config.get('labels')
        assert labels['traefik.enable'] == 'true'
        assert labels['prometheus.scrape'] == 'true'
        assert labels['com.example.team'] == 'platform'
