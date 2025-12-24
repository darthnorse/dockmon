"""
Tests for network configuration preservation during container updates.

Critical bug fix: Container updates must preserve static IP addresses,
network aliases, and other endpoint-specific configuration.

Bug Report: User reported static IPs were lost when updating containers.
Root Cause: update_executor.py only extracted network NAME, not endpoint config.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch


# =============================================================================
# v2.1.9 NOTICE: This file tests v1 extraction logic (REMOVED)
# =============================================================================
#
# This test file is DISABLED because it tests the old v1 extraction methods:
# - filter_podman_incompatible_params() - REMOVED (52 lines)
# - _extract_container_config() - REMOVED (327 lines)
# - _create_container() - REMOVED (115 lines)
#
# v2.1.9 uses PASSTHROUGH APPROACH instead of field-by-field extraction.
#
# These behaviors are now tested in:
# - test_passthrough_critical.py (7 critical tests)
#
# See: docs/UPDATE_EXECUTOR_PASSTHROUGH_REFACTOR.md
# =============================================================================

import pytest
pytestmark = pytest.mark.skip(reason="v2.1.9: Tests v1 extraction logic (removed)")

from updates.update_executor import UpdateExecutor


@pytest.mark.unit
class TestNetworkConfigExtraction:
    """Test that network configuration is extracted correctly"""

    @pytest.fixture
    def mock_container_with_static_ip(self):
        """Mock container with static IPv4 address"""
        container = Mock()
        container.attrs = {
            "Name": "/test-container",
            "Config": {
                "Hostname": "test-host",
                "User": "root",
                "Env": [],
                "Cmd": ["nginx"],
                "Labels": {},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
                "PortBindings": {},
                "Binds": [],
                "Privileged": False,
            },
            "NetworkSettings": {
                "Networks": {
                    "my-network": {
                        "IPAddress": "172.18.0.6",  # Static IP!
                        "IPPrefixLen": 16,
                        "Gateway": "172.18.0.1",
                        "NetworkID": "abc123",
                        "EndpointID": "def456",
                        "Aliases": ["test-alias", "abc123def456"],  # Container ID auto-added
                        "IPAMConfig": {  # Indicates user-configured IP (not auto-assigned)
                            "IPv4Address": "172.18.0.6"
                        }
                    }
                }
            }
        }
        return container

    @pytest.fixture
    def mock_container_with_ipv6(self):
        """Mock container with IPv6 address"""
        container = Mock()
        container.attrs = {
            "Name": "/test-ipv6",
            "Config": {
                "Hostname": "test-ipv6",
                "User": "root",
                "Env": [],
                "Cmd": ["nginx"],
                "Labels": {},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
                "PortBindings": {},
                "Binds": [],
                "Privileged": False,
            },
            "NetworkSettings": {
                "Networks": {
                    "ipv6-network": {
                        "IPAddress": "172.20.0.10",
                        "GlobalIPv6Address": "2001:db8::10",  # IPv6!
                        "IPPrefixLen": 16,
                        "GlobalIPv6PrefixLen": 64,
                        "Gateway": "172.20.0.1",
                        "IPAMConfig": {  # Indicates user-configured IPs
                            "IPv4Address": "172.20.0.10",
                            "IPv6Address": "2001:db8::10"
                        },
                        "IPv6Gateway": "2001:db8::1",
                    }
                }
            }
        }
        return container

    @pytest.fixture
    def update_executor(self):
        """Create UpdateExecutor instance for testing"""
        executor = UpdateExecutor(
            db=Mock(),
            monitor=Mock()
        )
        return executor

    async def test_extract_static_ipv4_address(
        self,
        update_executor,
        mock_container_with_static_ip
    ):
        """Test that static IPv4 addresses are extracted correctly"""
        config = await update_executor._extract_container_config(
            mock_container_with_static_ip
        )

        # Verify networking_config was created
        assert "_dockmon_manual_networking_config" in config
        assert "EndpointsConfig" in config["_dockmon_manual_networking_config"]

        # Verify static IP was preserved
        endpoints = config["_dockmon_manual_networking_config"]["EndpointsConfig"]
        assert "my-network" in endpoints
        assert "IPAMConfig" in endpoints["my-network"]
        assert endpoints["my-network"]["IPAMConfig"]["IPv4Address"] == "172.18.0.6"

    async def test_extract_ipv6_address(
        self,
        update_executor,
        mock_container_with_ipv6
    ):
        """Test that IPv6 addresses are extracted correctly"""
        config = await update_executor._extract_container_config(
            mock_container_with_ipv6
        )

        endpoints = config["_dockmon_manual_networking_config"]["EndpointsConfig"]
        assert "ipv6-network" in endpoints
        assert "IPAMConfig" in endpoints["ipv6-network"]

        ipam = endpoints["ipv6-network"]["IPAMConfig"]
        assert ipam["IPv4Address"] == "172.20.0.10"
        assert ipam["IPv6Address"] == "2001:db8::10"

    async def test_extract_network_aliases(
        self,
        update_executor,
        mock_container_with_static_ip
    ):
        """Test that network aliases are extracted (excluding auto-generated container ID)"""
        config = await update_executor._extract_container_config(
            mock_container_with_static_ip
        )

        endpoints = config["_dockmon_manual_networking_config"]["EndpointsConfig"]
        aliases = endpoints["my-network"]["Aliases"]

        # Should include user-defined alias
        assert "test-alias" in aliases

        # Should NOT include 12-char container ID (Docker adds this automatically)
        assert "abc123def456" not in aliases

    async def test_backward_compatibility_network_field(
        self,
        update_executor,
        mock_container_with_static_ip
    ):
        """Test that advanced network config uses manual connection format"""
        config = await update_executor._extract_container_config(
            mock_container_with_static_ip
        )

        # Advanced config (static IP) → manual networking_config
        assert "_dockmon_manual_networking_config" in config
        # Network field IS set (to avoid creating on bridge)
        assert config.get("network") == "my-network"


@pytest.mark.unit
class TestNetworkConfigCreation:
    """Test that containers are created with correct network configuration"""

    @pytest.fixture
    def update_executor(self):
        """Create UpdateExecutor instance for testing"""
        executor = UpdateExecutor(
            db=Mock(),
            monitor=Mock()
        )
        return executor

    @pytest.fixture
    def mock_docker_client(self):
        """Mock Docker client"""
        client = Mock()
        client.containers = Mock()
        return client

    async def test_create_container_with_networking_config(
        self,
        update_executor,
        mock_docker_client
    ):
        """Test that manual networking_config triggers manual connection"""
        config = {
            "name": "test-container",
            "_dockmon_manual_networking_config": {  # New format
                "EndpointsConfig": {
                    "my-network": {
                        "IPAMConfig": {
                            "IPv4Address": "172.18.0.6"
                        }
                    }
                }
            }
        }

        # Mock the create call and network.connect
        mock_docker_client.containers.create = AsyncMock()
        mock_docker_client.networks.get = AsyncMock()
        mock_network = Mock()
        mock_network.connect = AsyncMock()

        with patch('updates.update_executor.async_docker_call') as mock_async:
            # First call: containers.create
            # Then: networks.get, network.disconnect, network.connect
            mock_container = Mock(short_id="abc123def456")
            mock_async.side_effect = [
                mock_container,  # containers.create
                mock_network,     # networks.get
                None,             # network.disconnect
                None              # network.connect
            ]

            result = await update_executor._create_container(
                mock_docker_client,
                "nginx:latest",
                config
            )

            # Verify container was created
            assert result.short_id == "abc123def456"

            # Verify calls: create, networks.get, disconnect, connect
            assert mock_async.call_count == 4

    async def test_create_container_backward_compatibility(
        self,
        update_executor,
        mock_docker_client
    ):
        """Test that simple network name still works (no networking_config)"""
        config = {
            "name": "test-container",
            "network": "my-network"  # Old format
        }

        mock_docker_client.containers.create = AsyncMock()

        with patch('updates.update_executor.async_docker_call') as mock_async:
            mock_async.return_value = Mock(short_id="abc123def456")

            await update_executor._create_container(
                mock_docker_client,
                "nginx:latest",
                config
            )

            # Should fall back to network parameter
            call_kwargs = mock_async.call_args[1]
            assert "network" in call_kwargs
            assert call_kwargs["network"] == "my-network"

    async def test_networking_config_priority(
        self,
        update_executor,
        mock_docker_client
    ):
        """Test that manual networking_config takes priority over network parameter"""
        config = {
            "name": "test-container",
            "_dockmon_manual_networking_config": {  # New format
                "EndpointsConfig": {
                    "my-network": {
                        "IPAMConfig": {"IPv4Address": "172.18.0.6"}
                    }
                }
            },
            "network": "my-network"  # Should be ignored if manual config present
        }

        # Mock the create call and network.connect
        mock_docker_client.containers.create = AsyncMock()
        mock_docker_client.networks.get = AsyncMock()
        mock_network = Mock()
        mock_network.connect = AsyncMock()

        with patch('updates.update_executor.async_docker_call') as mock_async:
            # Manually connect takes priority over 'network' parameter
            mock_container = Mock(short_id="abc123def456")
            mock_async.side_effect = [
                mock_container,  # containers.create
                mock_network,     # networks.get
                None,             # network.disconnect
                None              # network.connect
            ]

            result = await update_executor._create_container(
                mock_docker_client,
                "nginx:latest",
                config
            )

            # Should have done manual connection with disconnect/reconnect
            assert mock_async.call_count == 4  # create, networks.get, disconnect, connect
