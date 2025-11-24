"""
Unit tests for Quick Wins features in stack orchestrator.

Tests the parsing of 4 new Docker Compose directives:
- network_mode (host, bridge, none, container:name)
- devices (hardware device mapping)
- extra_hosts (custom /etc/hosts entries)
- cap_add / cap_drop (Linux capabilities)
"""

import pytest
from deployment.stack_orchestrator import StackOrchestrator, StackOrchestrationError


class TestNetworkModeParsing:
    """Test network_mode directive parsing"""

    def test_parse_network_mode_host(self):
        """Test network_mode: host"""
        service_config = {
            'image': 'app:latest',
            'network_mode': 'host'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('network_mode') == 'host'

    def test_parse_network_mode_bridge(self):
        """Test network_mode: bridge"""
        service_config = {
            'image': 'app:latest',
            'network_mode': 'bridge'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('network_mode') == 'bridge'

    def test_parse_network_mode_none(self):
        """Test network_mode: none"""
        service_config = {
            'image': 'app:latest',
            'network_mode': 'none'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('network_mode') == 'none'

    def test_parse_network_mode_container_name(self):
        """Test network_mode: container:name parsing"""
        service_config = {
            'image': 'sidecar:latest',
            'network_mode': 'container:web-container'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='sidecar',
            service_config=service_config
        )

        assert config.get('network_mode') == 'container:web-container'

    def test_network_mode_and_networks_raises_error(self):
        """Test that using both network_mode and networks raises error"""
        service_config = {
            'image': 'app:latest',
            'network_mode': 'host',
            'networks': ['my-network']
        }

        orchestrator = StackOrchestrator()
        with pytest.raises(StackOrchestrationError, match="mutually exclusive"):
            orchestrator.map_service_to_container_config(
                service_name='app',
                service_config=service_config
            )

    def test_network_mode_empty_string_raises_error(self):
        """Test that empty network_mode raises error"""
        service_config = {
            'image': 'app:latest',
            'network_mode': ''
        }

        orchestrator = StackOrchestrator()
        with pytest.raises(StackOrchestrationError, match="cannot be empty"):
            orchestrator.map_service_to_container_config(
                service_name='app',
                service_config=service_config
            )


class TestDevicesParsing:
    """Test devices directive parsing"""

    def test_parse_devices_single(self):
        """Test single device mapping"""
        service_config = {
            'image': 'app:latest',
            'devices': ['/dev/sda:/dev/xvda:rwm']
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config['devices'] == ['/dev/sda:/dev/xvda:rwm']

    def test_parse_devices_multiple(self):
        """Test multiple device mappings"""
        service_config = {
            'image': 'app:latest',
            'devices': [
                '/dev/ttyUSB0:/dev/ttyUSB0',
                '/dev/snd:/dev/snd:rwm'
            ]
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert len(config['devices']) == 2
        assert '/dev/ttyUSB0:/dev/ttyUSB0' in config['devices']
        assert '/dev/snd:/dev/snd:rwm' in config['devices']

    def test_devices_empty_list_not_added_to_config(self):
        """Test that empty devices list is not added to config"""
        service_config = {
            'image': 'app:latest',
            'devices': []
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Empty list should NOT be in config
        assert 'devices' not in config

    def test_devices_null_not_added_to_config(self):
        """Test that null devices is not added to config"""
        service_config = {
            'image': 'app:latest',
            'devices': None
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'devices' not in config

    def test_devices_not_list_raises_error(self):
        """Test that non-list devices raises error"""
        service_config = {
            'image': 'app:latest',
            'devices': '/dev/sda:/dev/xvda'  # String instead of list
        }

        orchestrator = StackOrchestrator()
        with pytest.raises(StackOrchestrationError, match="must be a list"):
            orchestrator.map_service_to_container_config(
                service_name='app',
                service_config=service_config
            )


class TestExtraHostsParsing:
    """Test extra_hosts directive parsing"""

    def test_parse_extra_hosts_list_format(self):
        """Test extra_hosts as list"""
        service_config = {
            'image': 'app:latest',
            'extra_hosts': ['db:192.168.1.100', 'cache:192.168.1.101']
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config['extra_hosts'] == ['db:192.168.1.100', 'cache:192.168.1.101']

    def test_parse_extra_hosts_dict_format(self):
        """Test extra_hosts as dict (converts to list)"""
        service_config = {
            'image': 'app:latest',
            'extra_hosts': {
                'db': '192.168.1.100',
                'cache': '192.168.1.101'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Dict format should convert to list
        assert 'extra_hosts' in config
        assert 'cache:192.168.1.101' in config['extra_hosts']
        assert 'db:192.168.1.100' in config['extra_hosts']

    def test_extra_hosts_empty_list_not_added_to_config(self):
        """Test that empty extra_hosts list is not added to config"""
        service_config = {
            'image': 'app:latest',
            'extra_hosts': []
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'extra_hosts' not in config

    def test_extra_hosts_empty_dict_not_added_to_config(self):
        """Test that empty extra_hosts dict is not added to config"""
        service_config = {
            'image': 'app:latest',
            'extra_hosts': {}
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'extra_hosts' not in config

    def test_extra_hosts_null_not_added_to_config(self):
        """Test that null extra_hosts is not added to config"""
        service_config = {
            'image': 'app:latest',
            'extra_hosts': None
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'extra_hosts' not in config

    def test_extra_hosts_invalid_type_raises_error(self):
        """Test that invalid extra_hosts type raises error"""
        service_config = {
            'image': 'app:latest',
            'extra_hosts': 'db:192.168.1.100'  # String instead of list/dict
        }

        orchestrator = StackOrchestrator()
        with pytest.raises(StackOrchestrationError, match="must be a list or dict"):
            orchestrator.map_service_to_container_config(
                service_name='app',
                service_config=service_config
            )


class TestCapabilitiesParsing:
    """Test cap_add and cap_drop directives"""

    def test_parse_cap_add(self):
        """Test cap_add parsing"""
        service_config = {
            'image': 'app:latest',
            'cap_add': ['NET_ADMIN', 'SYS_TIME']
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config['cap_add'] == ['NET_ADMIN', 'SYS_TIME']

    def test_parse_cap_drop(self):
        """Test cap_drop parsing"""
        service_config = {
            'image': 'app:latest',
            'cap_drop': ['MKNOD', 'NET_RAW']
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config['cap_drop'] == ['MKNOD', 'NET_RAW']

    def test_cap_add_empty_list_not_added_to_config(self):
        """Test that empty cap_add list is not added to config"""
        service_config = {
            'image': 'app:latest',
            'cap_add': []
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'cap_add' not in config

    def test_cap_drop_empty_list_not_added_to_config(self):
        """Test that empty cap_drop list is not added to config"""
        service_config = {
            'image': 'app:latest',
            'cap_drop': []
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'cap_drop' not in config

    def test_cap_add_null_not_added_to_config(self):
        """Test that null cap_add is not added to config"""
        service_config = {
            'image': 'app:latest',
            'cap_add': None
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'cap_add' not in config

    def test_cap_add_not_list_raises_error(self):
        """Test that non-list cap_add raises error"""
        service_config = {
            'image': 'app:latest',
            'cap_add': 'NET_ADMIN'  # String instead of list
        }

        orchestrator = StackOrchestrator()
        with pytest.raises(StackOrchestrationError, match="must be a list"):
            orchestrator.map_service_to_container_config(
                service_name='app',
                service_config=service_config
            )

    def test_cap_drop_not_list_raises_error(self):
        """Test that non-list cap_drop raises error"""
        service_config = {
            'image': 'app:latest',
            'cap_drop': 'MKNOD'  # String instead of list
        }

        orchestrator = StackOrchestrator()
        with pytest.raises(StackOrchestrationError, match="must be a list"):
            orchestrator.map_service_to_container_config(
                service_name='app',
                service_config=service_config
            )
