"""
Unit tests for network_mode extraction during container updates.

Tests that network_mode is correctly extracted from existing containers
and preserved when creating new containers during updates.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from updates.update_executor import UpdateExecutor


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


class TestNetworkModeExtraction:
    """Test network_mode extraction during container updates"""

    @pytest.fixture
    def update_executor(self):
        """Create update executor for testing"""
        db_mock = Mock()
        monitor_mock = Mock()
        return UpdateExecutor(db=db_mock, monitor=monitor_mock)

    @pytest.mark.asyncio
    async def test_extract_network_mode_host(self, update_executor):
        """Test that network_mode: host is preserved"""
        container = Mock()
        container.attrs = {
            "Name": "/app",
            "Config": {
                "Hostname": "app",
                "User": "root",
                "Env": [],
                "Cmd": [],
                "Labels": {},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
                "NetworkMode": "host",
                "PortBindings": {},
                "Binds": [],
                "Privileged": False,
            },
            "NetworkSettings": {"Networks": {}}
        }

        config = await update_executor._extract_container_config(container)

        assert "network_mode" in config
        assert config["network_mode"] == "host"

    @pytest.mark.asyncio
    async def test_extract_network_mode_bridge(self, update_executor):
        """Test that network_mode: bridge is preserved (could be user-set)"""
        container = Mock()
        container.attrs = {
            "Name": "/app",
            "Config": {
                "Hostname": "app",
                "User": "root",
                "Env": [],
                "Cmd": [],
                "Labels": {},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
                "NetworkMode": "bridge",  # Could be explicit user setting
                "PortBindings": {},
                "Binds": [],
                "Privileged": False,
            },
            "NetworkSettings": {
                "Networks": {}  # No custom network config - just using default bridge
            }
        }

        config = await update_executor._extract_container_config(container)

        # Should preserve "bridge" (we can't tell if it's user-set or default)
        assert "network_mode" in config
        assert config["network_mode"] == "bridge"

    @pytest.mark.asyncio
    async def test_extract_network_mode_default_filtered(self, update_executor):
        """Test that network_mode: default is NOT preserved"""
        container = Mock()
        container.attrs = {
            "Name": "/app",
            "Config": {
                "Hostname": "app",
                "User": "root",
                "Env": [],
                "Cmd": [],
                "Labels": {},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
                "NetworkMode": "default",  # Docker's automatic default
                "PortBindings": {},
                "Binds": [],
                "Privileged": False,
            },
            "NetworkSettings": {"Networks": {}}
        }

        config = await update_executor._extract_container_config(container)

        # "default" should be filtered out
        assert "network_mode" not in config

    @pytest.mark.asyncio
    async def test_extract_network_mode_none(self, update_executor):
        """Test that network_mode: none is preserved"""
        container = Mock()
        container.attrs = {
            "Name": "/app",
            "Config": {
                "Hostname": "app",
                "User": "root",
                "Env": [],
                "Cmd": [],
                "Labels": {},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
                "NetworkMode": "none",
                "PortBindings": {},
                "Binds": [],
                "Privileged": False,
            },
            "NetworkSettings": {"Networks": {}}
        }

        config = await update_executor._extract_container_config(container)

        assert "network_mode" in config
        assert config["network_mode"] == "none"

    @pytest.mark.asyncio
    async def test_extract_network_mode_skipped_when_networking_config_present(
        self,
        update_executor
    ):
        """
        CRITICAL TEST (FLAW 3 fix): Test that network_mode is NOT extracted
        when networking_config exists.

        This tests the ELSE branch of the conflict detection logic:
        if "networking_config" not in container_config:
            container_config["network_mode"] = network_mode
        else:
            # THIS BRANCH - tested here
            logger.debug("skipping network_mode (mutually exclusive)")
        """
        container = Mock()
        container.attrs = {
            "Name": "/app",
            "Config": {
                "Hostname": "app",
                "User": "root",
                "Env": [],
                "Cmd": [],
                "Labels": {},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "always"},
                "NetworkMode": "bridge",  # Has network_mode in Docker
                "PortBindings": {},
                "Binds": [],
                "Privileged": False,
            },
            "NetworkSettings": {
                "Networks": {
                    "my-network": {
                        "IPAddress": "172.18.0.6",  # Static IP
                        "Aliases": ["app-alias"]
                    }
                }
            }
        }

        config = await update_executor._extract_container_config(container)

        # networking_config should be extracted (static IP)
        assert "_dockmon_manual_networking_config" in config
        assert "my-network" in config["_dockmon_manual_networking_config"]["EndpointsConfig"]

        # network_mode should NOT be extracted (conflict with networking_config)
        assert "network_mode" not in config
