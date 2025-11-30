"""
Unit tests for Docker Mounts API extraction during container updates.

Tests the extraction of volumes from the modern Docker Mounts array format,
which is used by Docker Compose and newer Docker versions.

Issue: #64
"""

import pytest
from unittest.mock import Mock
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


class TestMountsExtraction:
    """Test extraction of volumes from Docker Mounts API"""

    @pytest.fixture
    def update_executor(self):
        """Create update executor for testing"""
        db_mock = Mock()
        monitor_mock = Mock()
        return UpdateExecutor(db=db_mock, monitor=monitor_mock)

    @pytest.fixture
    def base_container_attrs(self):
        """Create base container attrs structure"""
        return {
            "Name": "/test-container",
            "Config": {
                "Hostname": "test",
                "User": "",
                "Env": [],
                "Cmd": [],
                "Labels": {},
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "no"},
                "Privileged": False,
                "PortBindings": {},
                "Binds": [],
            },
            "NetworkSettings": {
                "Networks": {}
            },
            "Mounts": []
        }

    @pytest.mark.asyncio
    async def test_extract_bind_mount_from_mounts_array(self, update_executor, base_container_attrs):
        """Test extraction of bind mount from Mounts array when Binds is empty"""
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/data",
                "Destination": "/container/data",
                "Mode": "rw",
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        assert "/host/data" in config["volumes"]
        assert config["volumes"]["/host/data"]["bind"] == "/container/data"
        assert config["volumes"]["/host/data"]["mode"] == "rw"

    @pytest.mark.asyncio
    async def test_extract_named_volume_from_mounts_array(self, update_executor, base_container_attrs):
        """Test extraction of named volume uses Name field not Source path"""
        base_container_attrs["Mounts"] = [
            {
                "Type": "volume",
                "Name": "my-volume",
                "Source": "/var/lib/docker/volumes/my-volume/_data",
                "Destination": "/app/data",
                "Mode": "rw",
                "Driver": "local",
                "RW": True
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should use volume name, not full source path
        assert "my-volume" in config["volumes"]
        assert "/var/lib/docker/volumes/my-volume/_data" not in config["volumes"]
        assert config["volumes"]["my-volume"]["bind"] == "/app/data"
        assert config["volumes"]["my-volume"]["mode"] == "rw"

    @pytest.mark.asyncio
    async def test_skip_duplicate_from_binds(self, update_executor, base_container_attrs):
        """Test that mounts already in Binds are not duplicated"""
        # Same volume in both Binds and Mounts
        base_container_attrs["HostConfig"]["Binds"] = ["/host/data:/container/data:ro"]
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/data",
                "Destination": "/container/data",
                "Mode": "ro",
                "RW": False,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should only have one entry, from Binds (processed first)
        assert "/host/data" in config["volumes"]
        assert config["volumes"]["/host/data"]["bind"] == "/container/data"
        assert config["volumes"]["/host/data"]["mode"] == "ro"
        # Verify no duplicate by counting keys
        assert len(config["volumes"]) == 1

    @pytest.mark.asyncio
    async def test_mode_defaults_to_rw_when_empty(self, update_executor, base_container_attrs):
        """Test that empty Mode defaults to 'rw'"""
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/data",
                "Destination": "/container/data",
                "Mode": "",  # Empty string
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        assert config["volumes"]["/host/data"]["mode"] == "rw"

    @pytest.mark.asyncio
    async def test_mode_defaults_to_rw_when_missing(self, update_executor, base_container_attrs):
        """Test that missing Mode defaults to 'rw'"""
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/data",
                "Destination": "/container/data",
                # No Mode field
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        assert config["volumes"]["/host/data"]["mode"] == "rw"

    @pytest.mark.asyncio
    async def test_multiple_mounts_extraction(self, update_executor, base_container_attrs):
        """Test extraction of multiple mounts of different types"""
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/config",
                "Destination": "/app/config",
                "Mode": "ro",
                "RW": False,
                "Propagation": "rprivate"
            },
            {
                "Type": "volume",
                "Name": "app-data",
                "Source": "/var/lib/docker/volumes/app-data/_data",
                "Destination": "/app/data",
                "Mode": "rw",
                "Driver": "local",
                "RW": True
            },
            {
                "Type": "bind",
                "Source": "/host/logs",
                "Destination": "/app/logs",
                "Mode": "rw",
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Check all three mounts
        assert "/host/config" in config["volumes"]
        assert config["volumes"]["/host/config"]["bind"] == "/app/config"
        assert config["volumes"]["/host/config"]["mode"] == "ro"

        assert "app-data" in config["volumes"]
        assert config["volumes"]["app-data"]["bind"] == "/app/data"
        assert config["volumes"]["app-data"]["mode"] == "rw"

        assert "/host/logs" in config["volumes"]
        assert config["volumes"]["/host/logs"]["bind"] == "/app/logs"
        assert config["volumes"]["/host/logs"]["mode"] == "rw"

    @pytest.mark.asyncio
    async def test_named_volume_without_name_field_skipped(self, update_executor, base_container_attrs):
        """Test that named volume without Name field is skipped"""
        base_container_attrs["Mounts"] = [
            {
                "Type": "volume",
                # No Name field
                "Source": "/var/lib/docker/volumes/unnamed/_data",
                "Destination": "/app/data",
                "Mode": "rw",
                "RW": True
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should be empty - no valid volumes
        assert len(config["volumes"]) == 0

    @pytest.mark.asyncio
    async def test_bind_mount_without_source_skipped(self, update_executor, base_container_attrs):
        """Test that bind mount without Source is skipped"""
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "",  # Empty source
                "Destination": "/app/data",
                "Mode": "rw",
                "RW": True
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should be empty - invalid bind mount
        assert len(config["volumes"]) == 0

    @pytest.mark.asyncio
    async def test_bind_mount_without_destination_skipped(self, update_executor, base_container_attrs):
        """Test that bind mount without Destination is skipped"""
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/data",
                "Destination": "",  # Empty destination
                "Mode": "rw",
                "RW": True
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should be empty - invalid bind mount
        assert len(config["volumes"]) == 0

    @pytest.mark.asyncio
    async def test_empty_mounts_array(self, update_executor, base_container_attrs):
        """Test handling of empty Mounts array"""
        base_container_attrs["Mounts"] = []

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        assert config["volumes"] == {}

    @pytest.mark.asyncio
    async def test_missing_mounts_key(self, update_executor, base_container_attrs):
        """Test handling when Mounts key is missing from attrs"""
        del base_container_attrs["Mounts"]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        assert config["volumes"] == {}

    @pytest.mark.asyncio
    async def test_binds_and_mounts_combined(self, update_executor, base_container_attrs):
        """Test that both Binds and Mounts are extracted correctly"""
        # Binds has one mount
        base_container_attrs["HostConfig"]["Binds"] = ["/host/config:/app/config:ro"]

        # Mounts has additional mount not in Binds
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/config",
                "Destination": "/app/config",
                "Mode": "ro",
                "RW": False,
                "Propagation": "rprivate"
            },
            {
                "Type": "volume",
                "Name": "app-data",
                "Source": "/var/lib/docker/volumes/app-data/_data",
                "Destination": "/app/data",
                "Mode": "rw",
                "Driver": "local",
                "RW": True
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should have both: one from Binds, one from Mounts (deduplicated)
        assert len(config["volumes"]) == 2
        assert "/host/config" in config["volumes"]
        assert "app-data" in config["volumes"]

    # =========================================================================
    # Issue #68: Destination-based deduplication tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_deduplicate_by_destination_with_trailing_slash(self, update_executor, base_container_attrs):
        """
        Test that mounts with different sources but same destination are deduplicated.

        Issue #68: Docker can represent the same mount with slightly different source paths
        (e.g., with/without trailing slash). We should deduplicate by destination to avoid
        "Duplicate mount point" errors.
        """
        # Binds has path WITHOUT trailing slash
        base_container_attrs["HostConfig"]["Binds"] = ["/host/config:/config:rw"]

        # Mounts has the SAME mount but source has trailing slash
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/config/",  # Trailing slash - different string!
                "Destination": "/config",
                "Mode": "rw",
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should only have ONE entry for /config destination (Issue #68)
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations.count("/config") == 1, \
            f"Expected 1 mount to /config, got {destinations.count('/config')}: {config['volumes']}"

    @pytest.mark.asyncio
    async def test_deduplicate_by_destination_symlink_resolved(self, update_executor, base_container_attrs):
        """
        Test deduplication when Docker resolves symlinks differently in Binds vs Mounts.

        Issue #68: Docker may show symlink path in Binds but resolved path in Mounts.
        Both point to the same destination and should be deduplicated.
        """
        # Binds has symlink path
        base_container_attrs["HostConfig"]["Binds"] = ["/home/user/config:/config:rw"]

        # Mounts has resolved real path
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/actual/path/config",  # Resolved path - different string!
                "Destination": "/config",
                "Mode": "rw",
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should only have ONE entry for /config destination
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations.count("/config") == 1, \
            f"Expected 1 mount to /config, got {destinations.count('/config')}: {config['volumes']}"

    @pytest.mark.asyncio
    async def test_deduplicate_multiple_same_destinations(self, update_executor, base_container_attrs):
        """
        Test that all three potential sources of same-destination mounts are deduplicated.

        Issue #68: Edge case where Binds and multiple Mounts entries all target same destination.
        """
        # Binds entry
        base_container_attrs["HostConfig"]["Binds"] = ["/path1:/config:rw"]

        # Two Mounts entries with different sources but same destination
        base_container_attrs["Mounts"] = [
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
                "Destination": "/config",  # Same destination again!
                "Mode": "rw",
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should only have ONE entry for /config destination
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations.count("/config") == 1, \
            f"Expected 1 mount to /config, got {destinations.count('/config')}: {config['volumes']}"

    @pytest.mark.asyncio
    async def test_deduplicate_preserves_binds_over_mounts(self, update_executor, base_container_attrs):
        """
        Test that Binds extraction takes precedence over Mounts for same destination.

        Issue #68: When deduplicating, the Binds entry should be preserved since it's
        processed first and is the canonical format.
        """
        # Binds has specific path
        base_container_attrs["HostConfig"]["Binds"] = ["/canonical/path:/config:ro"]

        # Mounts has different source with same destination
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/alternative/path",
                "Destination": "/config",
                "Mode": "rw",  # Different mode
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should preserve the Binds entry (canonical path and mode)
        assert "/canonical/path" in config["volumes"]
        assert config["volumes"]["/canonical/path"]["bind"] == "/config"
        assert config["volumes"]["/canonical/path"]["mode"] == "ro"
        # Should NOT have the alternative path
        assert "/alternative/path" not in config["volumes"]

    @pytest.mark.asyncio
    async def test_deduplicate_different_destinations_both_preserved(self, update_executor, base_container_attrs):
        """
        Test that mounts with different destinations are NOT deduplicated.

        Issue #68: Sanity check - only same-destination mounts should be deduplicated.
        """
        # Multiple mounts to DIFFERENT destinations
        base_container_attrs["HostConfig"]["Binds"] = ["/host/config:/config:rw"]
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/config",  # Same source
                "Destination": "/config",
                "Mode": "rw",
                "RW": True,
                "Propagation": "rprivate"
            },
            {
                "Type": "bind",
                "Source": "/host/data",  # Different source
                "Destination": "/data",   # Different destination
                "Mode": "rw",
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should have both mounts (different destinations)
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert "/config" in destinations
        assert "/data" in destinations

    @pytest.mark.asyncio
    async def test_deduplicate_volume_and_bind_same_destination(self, update_executor, base_container_attrs):
        """
        Test deduplication when a named volume and bind mount target same destination.

        Issue #68: This is an edge case where both types target same path.
        Binds should take precedence.
        """
        # Bind mount in Binds
        base_container_attrs["HostConfig"]["Binds"] = ["/host/config:/config:rw"]

        # Named volume also targeting /config (unusual but possible)
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/config",
                "Destination": "/config",
                "Mode": "rw",
                "RW": True,
                "Propagation": "rprivate"
            },
            {
                "Type": "volume",
                "Name": "config-volume",
                "Source": "/var/lib/docker/volumes/config-volume/_data",
                "Destination": "/config",  # Same destination as bind!
                "Mode": "rw",
                "RW": True,
                "Driver": "local"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should only have ONE entry for /config destination
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations.count("/config") == 1, \
            f"Expected 1 mount to /config, got {destinations.count('/config')}: {config['volumes']}"
        # The bind mount from Binds should be preserved
        assert "/host/config" in config["volumes"]

    @pytest.mark.asyncio
    async def test_normalize_source_path_trailing_slash(self, update_executor, base_container_attrs):
        """
        Test that source paths are normalized (trailing slashes removed) for deduplication.

        Issue #68: Paths like '/path/' and '/path' should be considered the same source.
        """
        # Same mount in both, but Mounts has trailing slash
        base_container_attrs["HostConfig"]["Binds"] = ["/host/config:/config:rw"]
        base_container_attrs["Mounts"] = [
            {
                "Type": "bind",
                "Source": "/host/config/",  # Trailing slash
                "Destination": "/config",
                "Mode": "rw",
                "RW": True,
                "Propagation": "rprivate"
            }
        ]

        container = Mock()
        container.attrs = base_container_attrs

        config = await update_executor._extract_container_config(container)

        # Should only have one entry (either source format is acceptable)
        assert len(config["volumes"]) == 1

        # The destination should be /config
        destinations = [v["bind"] for v in config["volumes"].values()]
        assert destinations == ["/config"]
