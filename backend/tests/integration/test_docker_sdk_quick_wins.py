"""
Integration tests: Docker SDK format verification + round-trip
CRITICAL: Tests actual Docker SDK behavior, not mocks

These tests verify that:
1. Docker SDK accepts the formats we're using
2. Full round-trip cycle works (create → extract → recreate)
"""

import pytest
import docker
from deployment.stack_orchestrator import StackOrchestrator


@pytest.mark.integration
class TestDockerSDKQuickWins:
    """Integration tests with real Docker SDK"""

    @pytest.fixture
    def docker_client(self):
        """Get Docker client"""
        try:
            return docker.from_env()
        except Exception as e:
            pytest.skip(f"Docker not available: {e}")

    def test_docker_sdk_format_verification(self, docker_client):
        """
        FLAW 5 FIX: Verify Docker SDK accepts the formats we're using

        This test verifies Docker SDK accepts:
        - devices as string list: ['/dev/null:/dev/null:rwm']
        - network_mode as string: 'bridge'
        - extra_hosts as string list: ['test:192.168.1.1']
        - cap_add/cap_drop as string lists
        """
        container = None

        try:
            # Test format compatibility by creating actual container
            container = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-format-verification',
                command=['sleep', '10'],
                detach=True,
                # Test all Quick Wins formats
                devices=['/dev/null:/dev/null:rwm'],  # String format
                network_mode='bridge',  # String format
                extra_hosts=['test:192.168.1.1'],  # List of strings
                cap_add=['NET_ADMIN'],  # List of strings
                cap_drop=['MKNOD'],  # List of strings
            )

            # If we get here, Docker SDK accepted all formats
            assert container is not None

            # Verify formats were preserved
            container.reload()
            attrs = container.attrs
            host_config = attrs['HostConfig']

            # Verify devices stored correctly
            assert 'Devices' in host_config
            assert len(host_config['Devices']) == 1
            # Docker converts string to dict internally
            assert host_config['Devices'][0]['PathOnHost'] == '/dev/null'

            # Verify network_mode stored correctly
            assert host_config['NetworkMode'] == 'bridge'

            # Verify extra_hosts stored correctly
            assert 'test:192.168.1.1' in host_config['ExtraHosts']

            # Verify capabilities stored correctly
            assert 'NET_ADMIN' in host_config['CapAdd']
            assert 'MKNOD' in host_config['CapDrop']

            print("\n✓ Docker SDK format verification PASSED")
            print("✓ All Quick Wins formats accepted by Docker SDK")

        finally:
            if container:
                container.remove(force=True)

    def test_quick_wins_round_trip(self, docker_client):
        """
        FLAW 1 FIX: Test full round-trip cycle (create → extract → recreate)

        This tests the ACTUAL update flow:
        1. Create container with all Quick Wins features
        2. Extract config (like update_executor does)
        3. Create new container from extracted config
        4. Verify new container has same features
        """
        # Step 1: Generate config using orchestrator
        orchestrator = StackOrchestrator()

        service_config = {
            'image': 'alpine:latest',
            'devices': ['/dev/null:/dev/null:rwm'],
            'network_mode': 'bridge',
            'extra_hosts': ['test:192.168.1.1', 'db:192.168.1.2'],
            'cap_add': ['NET_ADMIN'],
            'cap_drop': ['MKNOD'],
        }

        config = orchestrator.map_service_to_container_config(
            service_name='test-quick-wins',
            service_config=service_config
        )

        # Step 2: Create first container
        create_params_v1 = {
            'image': 'alpine:latest',
            'name': 'dockmon-test-quick-wins-v1',
            'command': ['sleep', '60'],
            'detach': True,
            'devices': config.get('devices'),
            'network_mode': config.get('network_mode'),
            'extra_hosts': config.get('extra_hosts'),
            'cap_add': config.get('cap_add'),
            'cap_drop': config.get('cap_drop'),
        }

        container_v1 = None
        container_v2 = None

        try:
            # Create v1
            container_v1 = docker_client.containers.create(**create_params_v1)
            container_v1.start()

            # Step 3: Extract config (simulate update_executor)
            # FLAW 1 FIX: Match ACTUAL update_executor.py behavior
            container_v1.reload()
            attrs = container_v1.attrs
            host_config = attrs['HostConfig']

            # Extract using EXACT same logic as update_executor.py:818-820, 825
            extracted_devices = host_config.get('Devices')  # Raw dict format
            extracted_extra_hosts = host_config.get('ExtraHosts')
            extracted_cap_add = host_config.get('CapAdd')
            extracted_cap_drop = host_config.get('CapDrop')

            # Extract network_mode (new in v2.1.8)
            extracted_network_mode = None
            if host_config.get('NetworkMode'):
                mode = host_config['NetworkMode']
                if mode not in ['default']:
                    extracted_network_mode = mode

            # Step 4: Create v2 container from extracted config
            create_params_v2 = {
                'image': 'alpine:latest',
                'name': 'dockmon-test-quick-wins-v2',
                'command': ['sleep', '60'],
                'detach': True,
                # Use extracted values EXACTLY as update_executor would
                'devices': extracted_devices,
                'network_mode': extracted_network_mode,
                'extra_hosts': extracted_extra_hosts,
                'cap_add': extracted_cap_add,
                'cap_drop': extracted_cap_drop,
            }

            container_v2 = docker_client.containers.create(**create_params_v2)

            # Step 5: Verify v2 has same config as v1
            container_v2.reload()
            v2_attrs = container_v2.attrs
            v2_host_config = v2_attrs['HostConfig']

            # Verify devices preserved
            assert len(v2_host_config['Devices']) == 1
            assert v2_host_config['Devices'][0]['PathOnHost'] == '/dev/null'
            assert v2_host_config['Devices'][0]['PathInContainer'] == '/dev/null'

            # Verify network_mode preserved
            assert v2_host_config['NetworkMode'] == 'bridge'

            # Verify extra_hosts preserved
            assert 'test:192.168.1.1' in v2_host_config['ExtraHosts']
            assert 'db:192.168.1.2' in v2_host_config['ExtraHosts']

            # Verify capabilities preserved
            assert 'NET_ADMIN' in v2_host_config['CapAdd']
            assert 'MKNOD' in v2_host_config['CapDrop']

            print("\n✓ Round-trip test PASSED")
            print("✓ All Quick Wins features preserved through extract→recreate cycle")

        finally:
            # Cleanup
            if container_v1:
                try:
                    container_v1.stop(timeout=1)
                except:
                    pass
                container_v1.remove(force=True)

            if container_v2:
                container_v2.remove(force=True)
