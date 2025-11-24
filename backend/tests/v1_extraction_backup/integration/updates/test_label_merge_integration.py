"""
Integration tests for label merging during container updates.

Verifies end-to-end label merge behavior:
1. Image labels are updated from new image
2. Compose labels are preserved
3. DockMon tracking labels are preserved
4. User custom labels are preserved
5. Error handling when image inspection fails

Issue: #57
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from updates.update_executor import UpdateExecutor
from database import DatabaseManager, ContainerUpdate


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


class TestLabelMergeIntegration:
    """Integration tests for label merge during container updates"""

    @pytest.fixture
    async def executor(self, db_session, mock_event_bus):
        """Create UpdateExecutor with mocked dependencies"""
        executor = UpdateExecutor(db=db_session, monitor=None)
        executor.event_bus = mock_event_bus
        return executor

    @pytest.fixture
    def old_container_with_labels(self):
        """Mock old container with various label types"""
        container = Mock()
        container.short_id = "abc123456789"
        container.name = "test-app"
        container.attrs = {
            "Name": "/test-app",
            "Config": {
                "Hostname": "test-app",
                "User": "",
                "OpenStdin": False,
                "Tty": False,
                "Env": ["ENV=production"],
                "Cmd": ["/app/start.sh"],
                "Entrypoint": None,
                "WorkingDir": "/app",
                "Labels": {
                    # Stale image label (should be updated)
                    "org.opencontainers.image.version": "1.0.0",
                    "org.opencontainers.image.created": "2025-01-01T00:00:00Z",

                    # Compose labels (must be preserved)
                    "com.docker.compose.project": "mystack",
                    "com.docker.compose.service": "web",
                    "com.docker.compose.version": "2.20.0",

                    # DockMon labels (must be preserved)
                    "dockmon.deployment_id": "550e8400-e29b-41d4-a716-446655440000",
                    "dockmon.managed": "true",

                    # User custom labels (must be preserved)
                    "custom.environment": "production",
                    "traefik.enable": "true",
                    "traefik.http.routers.web.rule": "Host(`example.com`)"
                }
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "unless-stopped"},
                "Privileged": False,
                "PortBindings": {},
                "Binds": []
            },
            "NetworkSettings": {
                "Networks": {
                    "bridge": {
                        "IPAMConfig": None,
                        "IPAddress": "172.17.0.2"
                    }
                }
            }
        }
        return container

    @pytest.fixture
    def new_image_with_labels(self):
        """Mock new image with updated labels"""
        image = Mock()
        image.attrs = {
            "Config": {
                "Labels": {
                    # Fresh image labels (should override old)
                    "org.opencontainers.image.version": "2.0.0",
                    "org.opencontainers.image.created": "2025-11-17T10:30:00Z",
                    "org.opencontainers.image.revision": "abc123def456",

                    # New label added in v2.0.0
                    "org.opencontainers.image.source": "https://github.com/example/app"
                }
            }
        }
        return image

    @pytest.mark.integration
    async def test_extract_config_merges_labels_correctly(
        self,
        executor,
        old_container_with_labels,
        new_image_with_labels
    ):
        """
        Test that _extract_container_config merges labels correctly.

        This is the core integration test verifying all label types
        are handled correctly during the config extraction phase.
        """
        # Extract new image labels
        new_image_labels = new_image_with_labels.attrs["Config"]["Labels"]

        # Execute: Extract config with label merge
        config = await executor._extract_container_config(
            old_container_with_labels,
            new_image_labels=new_image_labels
        )

        # Verify: Labels merged correctly
        labels = config["labels"]

        # 1. Image labels should be UPDATED (new image wins)
        assert labels["org.opencontainers.image.version"] == "2.0.0"
        assert labels["org.opencontainers.image.created"] == "2025-11-17T10:30:00Z"
        assert labels["org.opencontainers.image.revision"] == "abc123def456"
        assert labels["org.opencontainers.image.source"] == "https://github.com/example/app"

        # 2. Compose labels should be PRESERVED
        assert labels["com.docker.compose.project"] == "mystack"
        assert labels["com.docker.compose.service"] == "web"
        assert labels["com.docker.compose.version"] == "2.20.0"

        # 3. DockMon labels should be PRESERVED
        assert labels["dockmon.deployment_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert labels["dockmon.managed"] == "true"

        # 4. User custom labels should be PRESERVED
        assert labels["custom.environment"] == "production"
        assert labels["traefik.enable"] == "true"
        assert labels["traefik.http.routers.web.rule"] == "Host(`example.com`)"

        # 5. Verify total label count (old preserved + new added)
        # Old: 9 labels (version, created, compose x3, dockmon x2, custom x2)
        # New: 4 labels (version, created, revision, source)
        # Overlap: 2 labels (version, created)
        # Total: 9 + 4 - 2 = 11... but let's verify by counting unique keys
        expected_labels = {
            # Image labels (4 total, 2 override old)
            "org.opencontainers.image.version",  # NEW (overrides old)
            "org.opencontainers.image.created",  # NEW (overrides old)
            "org.opencontainers.image.revision",  # NEW
            "org.opencontainers.image.source",   # NEW
            # Compose labels (3 total)
            "com.docker.compose.project",
            "com.docker.compose.service",
            "com.docker.compose.version",
            # DockMon labels (2 total)
            "dockmon.deployment_id",
            "dockmon.managed",
            # Custom labels (3 total)
            "custom.environment",
            "traefik.enable",
            "traefik.http.routers.web.rule"
        }
        assert len(labels) == len(expected_labels)  # Should be 12
        assert set(labels.keys()) == expected_labels

    @pytest.mark.integration
    async def test_extract_config_without_new_labels_preserves_old(
        self,
        executor,
        old_container_with_labels
    ):
        """
        Test that when new_image_labels=None, old labels are preserved.

        This tests backward compatibility and defensive coding.
        """
        # Execute: Extract config without new image labels
        config = await executor._extract_container_config(
            old_container_with_labels,
            new_image_labels=None
        )

        # Verify: All old labels preserved exactly
        labels = config["labels"]
        old_labels = old_container_with_labels.attrs["Config"]["Labels"]

        assert labels == old_labels
        assert labels["org.opencontainers.image.version"] == "1.0.0"  # Stale, but preserved

    @pytest.mark.integration
    async def test_extract_config_with_empty_new_labels(
        self,
        executor,
        old_container_with_labels
    ):
        """
        Test that when new image has no labels, old labels are preserved.

        Handles edge case of minimal base images with no labels.
        """
        # Execute: Extract config with empty new image labels
        config = await executor._extract_container_config(
            old_container_with_labels,
            new_image_labels={}
        )

        # Verify: All old labels preserved
        labels = config["labels"]
        old_labels = old_container_with_labels.attrs["Config"]["Labels"]

        assert labels == old_labels

    @pytest.mark.integration
    async def test_extract_config_with_conflicting_labels(
        self,
        executor,
        old_container_with_labels
    ):
        """
        Test that when same label exists in both old and new, new image wins.

        This tests the merge priority: image is source of truth.
        """
        # Setup: New image with conflicting label
        new_image_labels = {
            "custom.environment": "staging",  # Conflicts with old "production"
            "org.opencontainers.image.version": "3.0.0"
        }

        # Execute: Extract config
        config = await executor._extract_container_config(
            old_container_with_labels,
            new_image_labels=new_image_labels
        )

        # Verify: New image labels win conflicts
        labels = config["labels"]
        assert labels["custom.environment"] == "staging"  # NEW wins
        assert labels["org.opencontainers.image.version"] == "3.0.0"  # NEW wins

        # But non-conflicting old labels are preserved
        assert labels["traefik.enable"] == "true"
        assert labels["com.docker.compose.project"] == "mystack"

    @pytest.mark.integration
    async def test_extract_config_preserves_other_config_fields(
        self,
        executor,
        old_container_with_labels,
        new_image_with_labels
    ):
        """
        Test that label merge doesn't affect other config fields.

        Ensures we're only changing labels, not breaking other config.
        """
        # Extract new image labels
        new_image_labels = new_image_with_labels.attrs["Config"]["Labels"]

        # Execute: Extract config
        config = await executor._extract_container_config(
            old_container_with_labels,
            new_image_labels=new_image_labels
        )

        # Verify: Other config fields unchanged
        assert config["name"] == "test-app"
        assert config["hostname"] == "test-app"
        assert config["environment"] == ["ENV=production"]
        assert config["command"] == ["/app/start.sh"]
        assert config["working_dir"] == "/app"
        assert config["restart_policy"] == {"Name": "unless-stopped"}
        assert config["privileged"] is False

    @pytest.mark.integration
    async def test_container_with_no_labels_gets_image_labels(
        self,
        executor,
        new_image_with_labels
    ):
        """
        Test that container with no labels gets image labels.

        Handles minimal containers (e.g., scratch-based images).
        """
        # Setup: Container with no labels
        container = Mock()
        container.short_id = "xyz987654321"
        container.name = "minimal-app"
        container.attrs = {
            "Name": "/minimal-app",
            "Config": {
                "Labels": None,  # No labels at all
                "Env": []
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "RestartPolicy": {}
            },
            "NetworkSettings": {"Networks": {}}
        }

        # Extract new image labels
        new_image_labels = new_image_with_labels.attrs["Config"]["Labels"]

        # Execute: Extract config
        config = await executor._extract_container_config(
            container,
            new_image_labels=new_image_labels
        )

        # Verify: Only image labels present
        labels = config["labels"]
        assert labels == new_image_labels
        assert labels["org.opencontainers.image.version"] == "2.0.0"

    @pytest.mark.integration
    async def test_both_container_and_image_have_no_labels(
        self,
        executor
    ):
        """
        Test edge case: neither container nor image have labels.

        Should result in empty labels dict.
        """
        # Setup: Container with no labels
        container = Mock()
        container.short_id = "empty12345678"
        container.name = "empty-app"
        container.attrs = {
            "Name": "/empty-app",
            "Config": {"Labels": None},
            "HostConfig": {"NetworkMode": "bridge"},
            "NetworkSettings": {"Networks": {}}
        }

        # Execute: Extract config with no new labels
        config = await executor._extract_container_config(
            container,
            new_image_labels={}
        )

        # Verify: Empty labels
        labels = config["labels"]
        assert labels == {}


class TestLabelMergeErrorHandling:
    """Test error handling during label merge"""

    @pytest.fixture
    async def executor(self, db_session, mock_event_bus):
        """Create UpdateExecutor with mocked dependencies"""
        executor = UpdateExecutor(db=db_session, monitor=None)
        executor.event_bus = mock_event_bus
        return executor

    @pytest.mark.integration
    async def test_merge_labels_handles_none_gracefully(self, executor):
        """
        Test that _merge_labels handles None inputs gracefully.

        Defensive programming test.
        """
        old_labels = {"custom.key": "value"}

        # Test with None new_image_labels
        merged = executor._merge_labels(old_labels, None)

        # Should return copy of old labels
        assert merged == old_labels
        assert merged is not old_labels  # Verify it's a copy

    @pytest.mark.integration
    async def test_merge_labels_with_none_old_labels(self, executor):
        """
        Test merge when old_labels is None/empty.

        Edge case: container created with no labels.
        """
        new_labels = {"org.opencontainers.image.version": "1.0.0"}

        # Test with empty old labels
        merged = executor._merge_labels({}, new_labels)

        assert merged == new_labels

    @pytest.mark.integration
    async def test_label_values_with_special_characters(self, executor):
        """
        Test that labels with special characters are preserved.

        Real-world labels can contain JSON, URLs, etc.
        """
        old_labels = {
            "traefik.http.routers.web.rule": "Host(`example.com`) && PathPrefix(`/api`)",
            "app.config": '{"key": "value", "nested": {"foo": "bar"}}'
        }
        new_labels = {
            "org.opencontainers.image.version": "2.0.0"
        }

        merged = executor._merge_labels(old_labels, new_labels)

        # Verify special characters preserved
        assert merged["traefik.http.routers.web.rule"] == "Host(`example.com`) && PathPrefix(`/api`)"
        assert merged["app.config"] == '{"key": "value", "nested": {"foo": "bar"}}'
        assert merged["org.opencontainers.image.version"] == "2.0.0"
