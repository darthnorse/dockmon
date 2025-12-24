"""
Integration tests for IPAM configuration in deployment system.

Tests actual Docker network creation with IPAM config (subnet, gateway, static IPs).
"""

import pytest
import docker
from docker.types import IPAMConfig, IPAMPool, EndpointConfig
try:
    from docker.types.networks import NetworkingConfig
except ImportError:
    # Fallback for older docker-py versions
    NetworkingConfig = docker.types.networking.NetworkingConfig


@pytest.mark.integration
class TestIPAMIntegration:
    """Integration tests for IPAM configuration"""

    @pytest.fixture
    def docker_client(self):
        """Get Docker client"""
        return docker.from_env()

    @pytest.fixture
    def cleanup_networks(self, docker_client):
        """Cleanup test networks after test"""
        networks_to_cleanup = []
        yield networks_to_cleanup
        for network_name in networks_to_cleanup:
            try:
                network = docker_client.networks.get(network_name)
                # Remove any containers first
                for container in network.attrs.get('Containers', {}).values():
                    try:
                        c = docker_client.containers.get(container['Name'])
                        c.remove(force=True)
                    except:
                        pass
                network.remove()
            except docker.errors.NotFound:
                pass

    def test_network_with_ipam_config(self, docker_client, cleanup_networks):
        """Test creating network with IPAM configuration"""
        network_name = 'test-ipam-network'
        cleanup_networks.append(network_name)

        # Create IPAM config
        ipam = IPAMConfig(
            pool_configs=[
                IPAMPool(
                    subnet='172.30.0.0/16',
                    gateway='172.30.0.1'
                )
            ]
        )

        # Create network with IPAM
        network = docker_client.networks.create(
            name=network_name,
            driver='bridge',
            ipam=ipam
        )

        # Verify network created
        assert network.name == network_name

        # Get network details and verify IPAM
        network.reload()
        ipam_config = network.attrs['IPAM']
        assert ipam_config['Driver'] == 'default'
        assert len(ipam_config['Config']) == 1
        assert ipam_config['Config'][0]['Subnet'] == '172.30.0.0/16'
        assert ipam_config['Config'][0]['Gateway'] == '172.30.0.1'

    def test_compose_ipam_end_to_end(self, docker_client, cleanup_networks):
        """Test full compose IPAM parsing and network creation"""
        from deployment.executor import DeploymentExecutor
        from deployment.compose_parser import ComposeParser
        from unittest.mock import Mock

        network_name = 'test-compose-ipam-network'
        cleanup_networks.append(network_name)

        # Create executor and parser
        executor = DeploymentExecutor(Mock(), Mock(), Mock())
        parser = ComposeParser()

        # Compose YAML with IPAM
        compose_yaml = f"""
version: '3.8'

networks:
  {network_name}:
    driver: bridge
    ipam:
      config:
        - subnet: 172.35.0.0/16
          gateway: 172.35.0.1

services:
  dummy:
    image: alpine:latest
    command: sleep 1
"""

        # Parse compose
        compose_data = parser.parse(compose_yaml)
        network_config = compose_data['networks'][network_name]

        # Parse IPAM
        ipam_config = executor._parse_ipam_config(network_config['ipam'])

        # Verify parser output
        assert ipam_config is not None
        assert ipam_config['Config'][0]['Subnet'] == '172.35.0.0/16'
        assert ipam_config['Config'][0]['Gateway'] == '172.35.0.1'

        # Create network using parsed IPAM
        network = docker_client.networks.create(
            name=network_name,
            driver='bridge',
            ipam=ipam_config
        )

        # Verify network created correctly
        network.reload()
        assert network.attrs['IPAM']['Config'][0]['Subnet'] == '172.35.0.0/16'
        assert network.attrs['IPAM']['Config'][0]['Gateway'] == '172.35.0.1'

    def test_ipam_parser_with_compose_format(self, docker_client, cleanup_networks):
        """Test IPAM parser converts compose format to Docker SDK format correctly"""
        from deployment.executor import DeploymentExecutor
        from unittest.mock import Mock

        # Create executor to access _parse_ipam_config
        executor = DeploymentExecutor(Mock(), Mock(), Mock())

        # Compose-style IPAM config
        compose_ipam = {
            'driver': 'default',
            'config': [
                {
                    'subnet': '172.30.0.0/16',
                    'gateway': '172.30.0.1'
                }
            ]
        }

        # Parse it
        ipam_config = executor._parse_ipam_config(compose_ipam)

        # Verify it's a valid IPAMConfig
        assert isinstance(ipam_config, IPAMConfig)
        assert ipam_config['Driver'] == 'default'
        assert len(ipam_config['Config']) == 1
        assert ipam_config['Config'][0]['Subnet'] == '172.30.0.0/16'
        assert ipam_config['Config'][0]['Gateway'] == '172.30.0.1'

        # Now actually use it to create a network
        network_name = 'test-parsed-ipam-network'
        cleanup_networks.append(network_name)

        network = docker_client.networks.create(
            name=network_name,
            driver='bridge',
            ipam=ipam_config
        )

        # Verify network has correct IPAM
        network.reload()
        assert network.attrs['IPAM']['Config'][0]['Subnet'] == '172.30.0.0/16'
        assert network.attrs['IPAM']['Config'][0]['Gateway'] == '172.30.0.1'

    def test_ipam_with_ip_range_and_aux_addresses(self, docker_client, cleanup_networks):
        """Test IPAM with IP range and auxiliary addresses"""
        network_name = 'test-full-ipam-network'
        cleanup_networks.append(network_name)

        # Create IPAM with all fields
        ipam = IPAMConfig(
            driver='default',
            pool_configs=[
                IPAMPool(
                    subnet='172.32.0.0/16',
                    gateway='172.32.0.1',
                    iprange='172.32.240.0/20',
                    aux_addresses={
                        'reserved1': '172.32.0.5',
                        'reserved2': '172.32.0.6'
                    }
                )
            ]
        )

        # Create network
        network = docker_client.networks.create(
            name=network_name,
            driver='bridge',
            ipam=ipam
        )

        # Verify all IPAM fields
        network.reload()
        ipam_config = network.attrs['IPAM']
        config = ipam_config['Config'][0]
        assert config['Subnet'] == '172.32.0.0/16'
        assert config['Gateway'] == '172.32.0.1'
        assert config['IPRange'] == '172.32.240.0/20'
        assert config['AuxiliaryAddresses'] == {
            'reserved1': '172.32.0.5',
            'reserved2': '172.32.0.6'
        }

    def test_network_without_ipam_still_works(self, docker_client, cleanup_networks):
        """Test that networks without IPAM config still work (backwards compatibility)"""
        network_name = 'test-no-ipam-network'
        cleanup_networks.append(network_name)

        # Create network without IPAM (ipam=None)
        network = docker_client.networks.create(
            name=network_name,
            driver='bridge',
            ipam=None  # Explicit None should work
        )

        # Verify network created (Docker will auto-assign subnet)
        assert network.name == network_name
        network.reload()

        # Should have IPAM config auto-generated by Docker
        assert 'IPAM' in network.attrs
        assert len(network.attrs['IPAM']['Config']) > 0
        # Docker auto-assigns subnet in some range
        assert 'Subnet' in network.attrs['IPAM']['Config'][0]
