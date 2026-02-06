"""
Integration test for network_mode preservation during actual container updates.

This tests the REAL update flow through UpdateExecutor, not just the Docker SDK.
Critical for catching bugs like network_mode not being passed to containers.create().
"""

import pytest
import docker
from unittest.mock import Mock, AsyncMock, MagicMock
from updates.update_executor import UpdateExecutor
from database import DatabaseManager


# =============================================================================
# v2.1.9 NOTICE: This file tests v1 extraction logic (REMOVED)
# =============================================================================
#
# This test file is DISABLED because it tests workflows using removed v1 methods:
# - _extract_container_config() - REMOVED in v2.1.9 passthrough refactor
# - _create_container() - REMOVED in v2.1.9 passthrough refactor
#
# v2.1.9 uses PASSTHROUGH APPROACH instead of field-by-field extraction.
#
# These behaviors need to be retested with v2 methods or real containers.
#
# See: docs/UPDATE_EXECUTOR_PASSTHROUGH_REFACTOR.md
# =============================================================================

import pytest
pytestmark = pytest.mark.skip(reason="v2.1.9: Tests v1 extraction workflow (removed)")


@pytest.mark.integration
class TestNetworkModeUpdateFlow:
    """Test network_mode is preserved through actual update flow"""

    @pytest.fixture
    def docker_client(self):
        """Get Docker client"""
        try:
            return docker.from_env(version="auto")
        except Exception as e:
            pytest.skip(f"Docker not available: {e}")

    @pytest.fixture
    def mock_db(self):
        """Mock database manager"""
        db = Mock(spec=DatabaseManager)
        db.get_session = Mock(return_value=MagicMock())
        return db

    @pytest.fixture
    def mock_monitor(self):
        """Mock docker monitor"""
        monitor = Mock()
        monitor.get_docker_client = Mock()
        return monitor

    @pytest.mark.asyncio
    async def test_network_mode_host_preserved_through_update(
        self,
        docker_client,
        mock_db,
        mock_monitor
    ):
        """
        Test that network_mode: host is preserved through UpdateExecutor update flow.

        This is the CRITICAL test that would have caught Bug #1.
        Tests the actual code path: extract config → create container → verify network_mode.
        """
        # Create initial container with network_mode: host
        container_v1 = None
        container_v2 = None

        try:
            # Step 1: Create initial container with network_mode
            container_v1 = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-networkmode-update-v1',
                command=['sleep', '60'],
                network_mode='host',
                detach=True
            )
            container_v1.start()

            # Step 2: Create UpdateExecutor instance
            executor = UpdateExecutor(db=mock_db, monitor=mock_monitor)

            # Step 3: Extract config from v1 container (simulates update flow)
            container_v1.reload()
            extracted_config = await executor._extract_container_config(container_v1)

            # Verify network_mode was extracted
            assert "network_mode" in extracted_config, "network_mode should be extracted from container"
            assert extracted_config["network_mode"] == "host", f"Expected network_mode='host', got {extracted_config.get('network_mode')}"

            # Step 4: Create new container using UpdateExecutor's create method
            # This is the REAL code path that was broken in Bug #1
            new_name = 'dockmon-test-networkmode-update-v2'
            extracted_config['name'] = new_name

            container_v2 = await executor._create_container(
                client=docker_client,
                image='alpine:latest',
                config=extracted_config
            )

            # Step 5: Verify network_mode was preserved in new container
            container_v2.reload()
            v2_attrs = container_v2.attrs
            v2_network_mode = v2_attrs['HostConfig']['NetworkMode']

            assert v2_network_mode == 'host', (
                f"CRITICAL BUG: network_mode not preserved! "
                f"Expected 'host', got '{v2_network_mode}'. "
                f"This means network_mode was extracted but not passed to containers.create()."
            )

            print("\n✓ network_mode: host preserved through UpdateExecutor flow")

        finally:
            # Cleanup
            if container_v1:
                try:
                    container_v1.stop(timeout=1)
                except:
                    pass
                container_v1.remove(force=True)

            if container_v2:
                try:
                    container_v2.stop(timeout=1)
                except:
                    pass
                container_v2.remove(force=True)

    @pytest.mark.asyncio
    async def test_network_mode_bridge_preserved_through_update(
        self,
        docker_client,
        mock_db,
        mock_monitor
    ):
        """
        Test that network_mode: bridge is preserved through update.

        Bridge is a special case - it's both a default and a valid user setting.
        """
        container_v1 = None
        container_v2 = None

        try:
            # Create container with explicit network_mode: bridge
            container_v1 = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-networkmode-bridge-v1',
                command=['sleep', '60'],
                network_mode='bridge',
                detach=True
            )

            # Extract and recreate via UpdateExecutor
            executor = UpdateExecutor(db=mock_db, monitor=mock_monitor)
            container_v1.reload()
            extracted_config = await executor._extract_container_config(container_v1)

            # Should preserve bridge (we can't distinguish user-set from default)
            assert "network_mode" in extracted_config
            assert extracted_config["network_mode"] == "bridge"

            # Create new container
            extracted_config['name'] = 'dockmon-test-networkmode-bridge-v2'
            container_v2 = await executor._create_container(
                client=docker_client,
                image='alpine:latest',
                config=extracted_config
            )

            # Verify preserved
            container_v2.reload()
            v2_network_mode = container_v2.attrs['HostConfig']['NetworkMode']
            assert v2_network_mode == 'bridge'

            print("\n✓ network_mode: bridge preserved through UpdateExecutor flow")

        finally:
            if container_v1:
                container_v1.remove(force=True)
            if container_v2:
                container_v2.remove(force=True)

    @pytest.mark.asyncio
    async def test_network_mode_none_preserved_through_update(
        self,
        docker_client,
        mock_db,
        mock_monitor
    ):
        """
        Test that network_mode: none is preserved through update.

        'none' = no networking at all (useful for isolated containers).
        """
        container_v1 = None
        container_v2 = None

        try:
            # Create container with network_mode: none
            container_v1 = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-networkmode-none-v1',
                command=['sleep', '60'],
                network_mode='none',
                detach=True
            )

            # Extract and recreate
            executor = UpdateExecutor(db=mock_db, monitor=mock_monitor)
            container_v1.reload()
            extracted_config = await executor._extract_container_config(container_v1)

            assert "network_mode" in extracted_config
            assert extracted_config["network_mode"] == "none"

            extracted_config['name'] = 'dockmon-test-networkmode-none-v2'
            container_v2 = await executor._create_container(
                client=docker_client,
                image='alpine:latest',
                config=extracted_config
            )

            # Verify preserved
            container_v2.reload()
            v2_network_mode = container_v2.attrs['HostConfig']['NetworkMode']
            assert v2_network_mode == 'none'

            print("\n✓ network_mode: none preserved through UpdateExecutor flow")

        finally:
            if container_v1:
                container_v1.remove(force=True)
            if container_v2:
                container_v2.remove(force=True)

    @pytest.mark.asyncio
    async def test_network_mode_not_set_when_custom_network_present(
        self,
        docker_client,
        mock_db,
        mock_monitor
    ):
        """
        Test that network_mode is NOT extracted when container has custom network config.

        This verifies the conflict detection logic works correctly.
        """
        network = None
        container_v1 = None

        try:
            # Clean up any leftover network from previous test runs
            try:
                existing_network = docker_client.networks.get('test-network-mode-conflict')
                existing_network.remove()
            except:
                pass  # Network doesn't exist, that's fine

            # Create a custom network with a unique subnet (required for static IPs)
            # Use 172.28.x.x to avoid conflicts with common Docker network ranges
            network = docker_client.networks.create(
                'test-network-mode-conflict',
                driver='bridge',
                ipam={'Config': [{'Subnet': '172.28.0.0/16'}]}
            )

            # Create container on custom network with static IP
            container_v1 = docker_client.containers.create(
                image='alpine:latest',
                name='dockmon-test-network-conflict-v1',
                command=['sleep', '60'],
                detach=True
            )
            # Manually connect with static IP
            network.connect(container_v1, ipv4_address='172.28.0.10')

            # Extract config
            executor = UpdateExecutor(db=mock_db, monitor=mock_monitor)
            container_v1.reload()
            extracted_config = await executor._extract_container_config(container_v1)

            # Should have either manual networking config OR simple network parameter
            has_network_config = (
                "_dockmon_manual_networking_config" in extracted_config or
                extracted_config.get("network") is not None
            )
            assert has_network_config, "Should have network configuration"

            # Should NOT have network_mode (conflict prevention)
            assert "network_mode" not in extracted_config, (
                "network_mode should not be extracted when custom network config exists"
            )

            print("\n✓ network_mode correctly skipped when custom network config present")

        finally:
            if container_v1:
                container_v1.remove(force=True)
            if network:
                network.remove()
