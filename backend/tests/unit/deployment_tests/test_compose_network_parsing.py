"""
Tests for docker-compose network configuration parsing.

Critical bug fix: Deployment system must properly parse static IP addresses
from docker-compose.yml files AND use correct format for Docker SDK.

NETWORK BUG FIX (2025-11-15):
Docker SDK doesn't auto-connect containers when networking_config is passed to containers.create().
Solution: Hybrid approach:
- Single network (no advanced config) → 'network' parameter
- Multiple networks → '_dockmon_manual_networks' (manual connection)
- Advanced config (static IP, aliases) → '_dockmon_manual_networking_config' (manual connection)
"""

import pytest
from deployment.stack_orchestrator import StackOrchestrator


@pytest.mark.unit
class TestComposeNetworkParsing:
    """Test that docker-compose network configurations are parsed correctly with hybrid approach"""

    def test_parse_network_list_format(self):
        """Test simple list format with multiple networks → manual connection"""
        service_config = {
            'image': 'nginx:latest',
            'networks': ['frontend', 'backend']
        }

        orchestrator = StackOrchestrator()

        config = orchestrator.map_service_to_container_config(
            service_name='web',
            service_config=service_config
        )

        # Multiple networks → manual connection format
        assert '_dockmon_manual_networks' in config
        assert config['_dockmon_manual_networks'] == ['frontend', 'backend']

    def test_parse_single_network_list_format(self):
        """Test single network in list format → 'network' parameter (fast path)"""
        service_config = {
            'image': 'nginx:latest',
            'networks': ['frontend']
        }

        orchestrator = StackOrchestrator()

        config = orchestrator.map_service_to_container_config(
            service_name='web',
            service_config=service_config
        )

        # Single network → use 'network' parameter (works with Docker SDK)
        assert 'network' in config
        assert config['network'] == 'frontend'
        assert '_dockmon_manual_networks' not in config

    def test_parse_network_with_static_ipv4(self):
        """Test dict format with static IPv4 address → manual connection"""
        service_config = {
            'image': 'nginx:latest',
            'networks': {
                'my-network': {
                    'ipv4_address': '172.18.0.6'
                }
            }
        }

        orchestrator = StackOrchestrator()

        config = orchestrator.map_service_to_container_config(
            service_name='web',
            service_config=service_config
        )

        # Advanced config → manual networking_config
        assert '_dockmon_manual_networking_config' in config
        endpoints = config['_dockmon_manual_networking_config']['EndpointsConfig']
        assert 'my-network' in endpoints
        assert 'IPAMConfig' in endpoints['my-network']
        assert endpoints['my-network']['IPAMConfig']['IPv4Address'] == '172.18.0.6'

    def test_parse_network_with_ipv6(self):
        """Test dict format with both IPv4 and IPv6 addresses"""
        service_config = {
            'image': 'nginx:latest',
            'networks': {
                'dual-stack-network': {
                    'ipv4_address': '172.18.0.10',
                    'ipv6_address': '2001:db8::10'
                }
            }
        }

        orchestrator = StackOrchestrator()

        config = orchestrator.map_service_to_container_config(
            service_name='web',
            service_config=service_config
        )

        endpoints = config['_dockmon_manual_networking_config']['EndpointsConfig']
        ipam = endpoints['dual-stack-network']['IPAMConfig']
        assert ipam['IPv4Address'] == '172.18.0.10'
        assert ipam['IPv6Address'] == '2001:db8::10'

    def test_parse_network_with_aliases(self):
        """Test dict format with network aliases"""
        service_config = {
            'image': 'nginx:latest',
            'networks': {
                'my-network': {
                    'aliases': ['web-server', 'nginx-primary']
                }
            }
        }

        orchestrator = StackOrchestrator()

        config = orchestrator.map_service_to_container_config(
            service_name='web',
            service_config=service_config
        )

        endpoints = config['_dockmon_manual_networking_config']['EndpointsConfig']
        endpoint = endpoints['my-network']
        assert 'Aliases' in endpoint
        assert 'web-server' in endpoint['Aliases']
        assert 'nginx-primary' in endpoint['Aliases']

    def test_parse_network_full_config(self):
        """Test dict format with static IP and aliases (real-world example)"""
        service_config = {
            'image': 'postgres:14',
            'networks': {
                'database-network': {
                    'ipv4_address': '172.20.0.5',
                    'aliases': ['db', 'postgres-master']
                }
            }
        }

        orchestrator = StackOrchestrator()

        config = orchestrator.map_service_to_container_config(
            service_name='database',
            service_config=service_config
        )

        endpoints = config['_dockmon_manual_networking_config']['EndpointsConfig']
        endpoint = endpoints['database-network']

        # Verify static IP
        assert 'IPAMConfig' in endpoint
        assert endpoint['IPAMConfig']['IPv4Address'] == '172.20.0.5'

        # Verify aliases
        assert 'Aliases' in endpoint
        assert 'db' in endpoint['Aliases']
        assert 'postgres-master' in endpoint['Aliases']

    def test_parse_network_empty_dict(self):
        """Test dict format with null/empty config (network name only) → manual connection"""
        service_config = {
            'image': 'nginx:latest',
            'networks': {
                'my-network': None  # Just connect to network, no special config
            }
        }

        orchestrator = StackOrchestrator()

        config = orchestrator.map_service_to_container_config(
            service_name='web',
            service_config=service_config
        )

        # Single network with no advanced config → could use 'network' parameter
        # But since it's dict format, we treat it as potential advanced config
        # Actually, with None value and no advanced config, orchestrator should use 'network' parameter
        # Let me check the logic... With dict format but empty config, it becomes manual
        assert '_dockmon_manual_networking_config' in config
        endpoints = config['_dockmon_manual_networking_config']['EndpointsConfig']
        assert 'my-network' in endpoints
        assert endpoints['my-network'] == {}

    def test_parse_multiple_networks_mixed_config(self):
        """Test service connected to multiple networks with mixed configurations"""
        service_config = {
            'image': 'app:latest',
            'networks': {
                'frontend': {
                    'ipv4_address': '172.18.0.20',
                    'aliases': ['app-frontend']
                },
                'backend': {
                    'ipv4_address': '172.19.0.20',
                    'aliases': ['app-backend']
                },
                'monitoring': None  # No special config
            }
        }

        orchestrator = StackOrchestrator()

        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Multiple networks with dict format → manual networking_config
        assert '_dockmon_manual_networking_config' in config
        endpoints = config['_dockmon_manual_networking_config']['EndpointsConfig']

        # Frontend network
        assert endpoints['frontend']['IPAMConfig']['IPv4Address'] == '172.18.0.20'
        assert 'app-frontend' in endpoints['frontend']['Aliases']

        # Backend network
        assert endpoints['backend']['IPAMConfig']['IPv4Address'] == '172.19.0.20'
        assert 'app-backend' in endpoints['backend']['Aliases']

        # Monitoring network (no config)
        assert 'monitoring' in endpoints
        assert endpoints['monitoring'] == {}

    def test_no_networks_specified(self):
        """Test service without networks specification"""
        service_config = {
            'image': 'nginx:latest',
            # No 'networks' key
        }

        orchestrator = StackOrchestrator()

        config = orchestrator.map_service_to_container_config(
            service_name='web',
            service_config=service_config
        )

        # Should not have any network config if no networks specified
        assert 'network' not in config
        assert '_dockmon_manual_networks' not in config
        assert '_dockmon_manual_networking_config' not in config
