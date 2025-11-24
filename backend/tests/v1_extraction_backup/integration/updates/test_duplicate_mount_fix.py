"""
Integration tests for duplicate mount point fix during container updates.

Tests the end-to-end behavior when Docker reports mounts in both Binds
and Mounts arrays with different source path representations.

Issue: #68
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from updates.update_executor import UpdateExecutor


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


class TestDuplicateMountFix:
    """Integration tests for Issue #68: Duplicate mount point prevention"""

    @pytest.fixture
    async def executor(self, db_session, mock_event_bus):
        """Create UpdateExecutor with mocked dependencies"""
        executor = UpdateExecutor(db=db_session, monitor=None)
        executor.event_bus = mock_event_bus
        return executor

    @pytest.fixture
    def container_with_trailing_slash_mismatch(self):
        """
        Mock container where Binds and Mounts have different source paths.

        This simulates the real-world scenario where Docker reports:
        - Binds: /host/config:/config:rw
        - Mounts: Source=/host/config/ (with trailing slash)

        This was causing "Duplicate mount point: /config" errors.
        """
        container = Mock()
        container.short_id = "abc123456789"
        container.name = "unifi-controller"
        container.attrs = {
            "Name": "/unifi-controller",
            "Config": {
                "Hostname": "unifi",
                "User": "",
                "OpenStdin": False,
                "Tty": False,
                "Env": ["TZ=UTC"],
                "Cmd": None,
                "Entrypoint": ["/entrypoint.sh"],
                "WorkingDir": "",
                "Labels": {}
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "unless-stopped"},
                "Privileged": False,
                "PortBindings": {
                    "8080/tcp": [{"HostIp": "", "HostPort": "8080"}],
                    "8443/tcp": [{"HostIp": "", "HostPort": "8443"}]
                },
                # Binds without trailing slash
                "Binds": ["/mnt/user/appdata/unifi:/config:rw"]
            },
            "NetworkSettings": {
                "Networks": {
                    "bridge": {
                        "IPAMConfig": None,
                        "IPAddress": "172.17.0.5"
                    }
                }
            },
            # Mounts with trailing slash on source
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/mnt/user/appdata/unifi/",  # Trailing slash!
                    "Destination": "/config",
                    "Mode": "rw",
                    "RW": True,
                    "Propagation": "rprivate"
                }
            ]
        }
        return container

    @pytest.fixture
    def container_with_symlink_resolution(self):
        """
        Mock container where Docker resolves symlinks differently.

        - Binds: /data/unifi:/config:rw (symlink path)
        - Mounts: Source=/mnt/disk1/data/unifi (resolved path)
        """
        container = Mock()
        container.short_id = "def456789012"
        container.name = "app-with-symlink"
        container.attrs = {
            "Name": "/app-with-symlink",
            "Config": {
                "Hostname": "app",
                "User": "",
                "OpenStdin": False,
                "Tty": False,
                "Env": [],
                "Cmd": ["/start.sh"],
                "Entrypoint": None,
                "WorkingDir": "/app",
                "Labels": {}
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "no"},
                "Privileged": False,
                "PortBindings": {},
                # Binds with symlink path
                "Binds": ["/data/unifi:/config:rw"]
            },
            "NetworkSettings": {
                "Networks": {}
            },
            # Mounts with resolved real path
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/mnt/disk1/data/unifi",  # Resolved path!
                    "Destination": "/config",
                    "Mode": "rw",
                    "RW": True,
                    "Propagation": "rprivate"
                }
            ]
        }
        return container

    @pytest.fixture
    def container_with_multiple_mounts_same_destination(self):
        """
        Mock container where multiple Mounts entries target same destination.

        This is an edge case but can happen with Docker configuration issues.
        """
        container = Mock()
        container.short_id = "ghi789012345"
        container.name = "multi-mount-container"
        container.attrs = {
            "Name": "/multi-mount-container",
            "Config": {
                "Hostname": "multi",
                "User": "",
                "OpenStdin": False,
                "Tty": False,
                "Env": [],
                "Cmd": None,
                "Entrypoint": None,
                "WorkingDir": "",
                "Labels": {}
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "no"},
                "Privileged": False,
                "PortBindings": {},
                "Binds": ["/path1:/config:rw"]
            },
            "NetworkSettings": {
                "Networks": {}
            },
            # Multiple Mounts entries targeting /config
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/path2",
                    "Destination": "/config",
                    "Mode": "rw",
                    "RW": True,
                    "Propagation": "rprivate"
                },
                {
                    "Type": "bind",
                    "Source": "/path3",
                    "Destination": "/config",
                    "Mode": "rw",
                    "RW": True,
                    "Propagation": "rprivate"
                }
            ]
        }
        return container

    @pytest.fixture
    def container_with_volume_and_bind_same_destination(self):
        """
        Mock container with both named volume and bind mount to same path.

        This tests the edge case where a bind mount in Binds and a named
        volume in Mounts both target the same container path.
        """
        container = Mock()
        container.short_id = "jkl012345678"
        container.name = "mixed-mount-container"
        container.attrs = {
            "Name": "/mixed-mount-container",
            "Config": {
                "Hostname": "mixed",
                "User": "",
                "OpenStdin": False,
                "Tty": False,
                "Env": [],
                "Cmd": None,
                "Entrypoint": None,
                "WorkingDir": "",
                "Labels": {}
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "no"},
                "Privileged": False,
                "PortBindings": {},
                # Bind mount to /config
                "Binds": ["/host/config:/config:rw"]
            },
            "NetworkSettings": {
                "Networks": {}
            },
            "Mounts": [
                # Bind mount (same as Binds)
                {
                    "Type": "bind",
                    "Source": "/host/config",
                    "Destination": "/config",
                    "Mode": "rw",
                    "RW": True,
                    "Propagation": "rprivate"
                },
                # Named volume also targeting /config (unusual but possible)
                {
                    "Type": "volume",
                    "Name": "config-volume",
                    "Source": "/var/lib/docker/volumes/config-volume/_data",
                    "Destination": "/config",
                    "Mode": "rw",
                    "RW": True,
                    "Driver": "local"
                }
            ]
        }
        return container

    @pytest.fixture
    def mock_docker_client(self):
        """Create mock Docker client for update simulation"""
        client = Mock()
        client.containers = Mock()
        client.images = Mock()
        client.networks = Mock()
        client.api = Mock()
        return client

    # =========================================================================
    # Integration Tests
    # =========================================================================

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_container_with_trailing_slash_mismatch(
        self, executor, container_with_trailing_slash_mismatch, mock_docker_client
    ):
        """
        Test that container update succeeds when Binds and Mounts have
        trailing slash differences in source paths.

        Issue #68: This was causing "Duplicate mount point: /config" errors.
        """
        # Extract config from problematic container
        config = await executor._extract_container_config(
            container_with_trailing_slash_mismatch
        )

        # Verify only one mount to /config
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations.count("/config") == 1, (
            f"Expected exactly 1 mount to /config, got {destinations.count('/config')}. "
            f"Volumes: {config['volumes']}"
        )

        # Verify the Binds entry was preserved (processed first)
        assert "/mnt/user/appdata/unifi" in config["volumes"]
        assert config["volumes"]["/mnt/user/appdata/unifi"]["bind"] == "/config"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_container_with_symlink_resolution(
        self, executor, container_with_symlink_resolution, mock_docker_client
    ):
        """
        Test that container update succeeds when Docker resolves symlinks
        differently in Binds vs Mounts.

        Issue #68: Symlink in Binds, resolved path in Mounts.
        """
        config = await executor._extract_container_config(
            container_with_symlink_resolution
        )

        # Verify only one mount to /config
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations.count("/config") == 1, (
            f"Expected exactly 1 mount to /config, got {destinations.count('/config')}. "
            f"Volumes: {config['volumes']}"
        )

        # Verify the Binds entry (symlink path) was preserved
        assert "/data/unifi" in config["volumes"]
        # The resolved path should NOT be present
        assert "/mnt/disk1/data/unifi" not in config["volumes"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_container_with_multiple_mounts_same_destination(
        self, executor, container_with_multiple_mounts_same_destination
    ):
        """
        Test that multiple Mounts entries targeting same destination are
        deduplicated to prevent Docker errors.

        Issue #68: Edge case with multiple Mounts + Binds all to /config.
        """
        config = await executor._extract_container_config(
            container_with_multiple_mounts_same_destination
        )

        # Verify only one mount to /config (from Binds)
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations.count("/config") == 1, (
            f"Expected exactly 1 mount to /config, got {destinations.count('/config')}. "
            f"Volumes: {config['volumes']}"
        )

        # Verify Binds entry was preserved
        assert "/path1" in config["volumes"]
        # Other paths should NOT be present
        assert "/path2" not in config["volumes"]
        assert "/path3" not in config["volumes"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_update_container_with_volume_and_bind_same_destination(
        self, executor, container_with_volume_and_bind_same_destination
    ):
        """
        Test that named volume and bind mount to same destination are
        properly deduplicated.

        Issue #68: Bind mount in Binds + named volume in Mounts both to /config.
        """
        config = await executor._extract_container_config(
            container_with_volume_and_bind_same_destination
        )

        # Verify only one mount to /config
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations.count("/config") == 1, (
            f"Expected exactly 1 mount to /config, got {destinations.count('/config')}. "
            f"Volumes: {config['volumes']}"
        )

        # Verify bind mount from Binds was preserved (not the named volume)
        assert "/host/config" in config["volumes"]
        # Named volume should NOT be present
        assert "config-volume" not in config["volumes"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_full_update_flow_with_problematic_mounts(
        self, executor, container_with_trailing_slash_mismatch, mock_docker_client, db_session
    ):
        """
        Test the complete update flow with a container that would have
        caused duplicate mount errors before the fix.

        This simulates what happens when a user clicks "Update" on a
        container like Olen's unifi-controller.
        """
        old_container = container_with_trailing_slash_mismatch

        # Create a new container mock that would be returned after creation
        new_container = Mock()
        new_container.short_id = "new123456789"
        new_container.name = "unifi-controller"
        new_container.start = Mock()
        new_container.status = "running"
        new_container.attrs = {
            "State": {"Health": {"Status": "healthy"}},
            "Config": {"Labels": {}}
        }
        new_container.reload = Mock()

        # Mock the image
        new_image = Mock()
        new_image.id = "sha256:newimage123"
        new_image.attrs = {"Config": {"Labels": {}}}

        # Setup Docker client mocks
        mock_docker_client.images.pull.return_value = new_image
        mock_docker_client.images.get.return_value = new_image
        mock_docker_client.containers.create.return_value = new_container
        mock_docker_client.containers.get.return_value = old_container

        # Extract config (this is where the bug would manifest)
        config = await executor._extract_container_config(old_container)

        # Verify extraction didn't create duplicates
        destinations = [v["bind"] for v in config["volumes"].values()]
        config_destination_count = destinations.count("/config")

        assert config_destination_count == 1, (
            f"Config extraction created duplicate mount points! "
            f"Found {config_destination_count} mounts to /config. "
            f"This would cause 'Duplicate mount point: /config' error. "
            f"Volumes: {config['volumes']}"
        )

        # Verify the volumes dict can be passed to Docker without error
        # (In real scenario, this would be passed to client.containers.create)
        assert len(config["volumes"]) == 1
        volume_key = list(config["volumes"].keys())[0]
        assert config["volumes"][volume_key]["bind"] == "/config"
        assert config["volumes"][volume_key]["mode"] == "rw"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_different_destinations_not_deduplicated(
        self, executor, db_session
    ):
        """
        Sanity check: Mounts with different destinations should NOT be
        deduplicated - only same-destination mounts should be.
        """
        container = Mock()
        container.short_id = "sanity123456"
        container.name = "multi-volume-container"
        container.attrs = {
            "Name": "/multi-volume-container",
            "Config": {
                "Hostname": "multi",
                "User": "",
                "OpenStdin": False,
                "Tty": False,
                "Env": [],
                "Cmd": None,
                "Entrypoint": None,
                "WorkingDir": "",
                "Labels": {}
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "no"},
                "Privileged": False,
                "PortBindings": {},
                "Binds": [
                    "/host/config:/config:rw",
                    "/host/data:/data:rw",
                    "/host/logs:/logs:ro"
                ]
            },
            "NetworkSettings": {
                "Networks": {}
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/host/config",
                    "Destination": "/config",
                    "Mode": "rw",
                    "RW": True,
                    "Propagation": "rprivate"
                },
                {
                    "Type": "bind",
                    "Source": "/host/data",
                    "Destination": "/data",
                    "Mode": "rw",
                    "RW": True,
                    "Propagation": "rprivate"
                },
                {
                    "Type": "bind",
                    "Source": "/host/logs",
                    "Destination": "/logs",
                    "Mode": "ro",
                    "RW": False,
                    "Propagation": "rprivate"
                }
            ]
        }

        config = await executor._extract_container_config(container)

        # Should have all 3 mounts (different destinations)
        assert len(config["volumes"]) == 3
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert "/config" in destinations
        assert "/data" in destinations
        assert "/logs" in destinations

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_real_world_unifi_controller_scenario(
        self, executor, db_session
    ):
        """
        Test with realistic UniFi Controller container configuration.

        This replicates Olen's actual Issue #68 scenario as closely as
        possible based on the error message and typical UniFi setups.
        """
        container = Mock()
        container.short_id = "unifi1234567"
        container.name = "unifi-controller"
        container.attrs = {
            "Name": "/unifi-controller",
            "Config": {
                "Hostname": "unifi-controller",
                "User": "",
                "OpenStdin": False,
                "Tty": False,
                "Env": [
                    "PUID=1000",
                    "PGID=1000",
                    "TZ=America/New_York",
                    "MEM_LIMIT=1024"
                ],
                "Cmd": None,
                "Entrypoint": ["/init"],
                "WorkingDir": "",
                "Labels": {
                    "com.docker.compose.project": "unifi",
                    "com.docker.compose.service": "controller"
                },
                "Image": "lscr.io/linuxserver/unifi-controller:latest"
            },
            "HostConfig": {
                "NetworkMode": "host",
                "RestartPolicy": {"Name": "unless-stopped"},
                "Privileged": False,
                "PortBindings": None,  # Host mode
                "Binds": ["/mnt/user/appdata/unifi:/config:rw"]
            },
            "NetworkSettings": {
                "Networks": {
                    "host": {
                        "IPAMConfig": None,
                        "IPAddress": ""
                    }
                }
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/mnt/user/appdata/unifi/",  # Trailing slash
                    "Destination": "/config",
                    "Mode": "rw",
                    "RW": True,
                    "Propagation": "rprivate"
                }
            ]
        }

        config = await executor._extract_container_config(container)

        # This is the critical check - only one /config mount
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations.count("/config") == 1, (
            f"Issue #68 regression! UniFi controller update would fail with "
            f"'Duplicate mount point: /config'. Found {destinations.count('/config')} "
            f"mounts to /config. Volumes: {config['volumes']}"
        )

        # Verify correct source was preserved
        assert "/mnt/user/appdata/unifi" in config["volumes"]

        # Verify network mode preserved
        assert config.get("network_mode") == "host"
