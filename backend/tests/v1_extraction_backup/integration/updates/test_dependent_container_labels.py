"""
Integration tests for label handling in dependent containers.

When updating containers with dependents (network_mode: container:parent),
verify that dependent containers don't incorrectly merge labels (they should
preserve their own labels since they're not being updated to new images).

Issue: #57
"""

import pytest
from unittest.mock import Mock, AsyncMock
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


class TestDependentContainerLabels:
    """Test label handling for dependent containers during parent updates"""

    @pytest.fixture
    async def executor(self, db_session, mock_event_bus):
        """Create UpdateExecutor with mocked dependencies"""
        executor = UpdateExecutor(db=db_session, monitor=None)
        executor.event_bus = mock_event_bus
        return executor

    @pytest.fixture
    def dependent_container_with_labels(self):
        """
        Mock dependent container (e.g., app depends on gluetun VPN).

        This container is NOT being updated to a new image - just being
        recreated to point to the new parent container ID.
        """
        container = Mock()
        container.short_id = "dep123456789"
        container.name = "app-depends-on-vpn"
        container.attrs = {
            "Name": "/app-depends-on-vpn",
            "Config": {
                "Hostname": "app-depends-on-vpn",
                "User": "",
                "OpenStdin": False,
                "Tty": False,
                "Env": ["APP_ENV=production"],
                "Cmd": ["/app/run.sh"],
                "Entrypoint": None,
                "WorkingDir": "/app",
                "Labels": {
                    # This container's own image labels
                    "org.opencontainers.image.version": "1.5.0",
                    "org.opencontainers.image.created": "2025-10-01T00:00:00Z",

                    # Compose labels (common for dependents)
                    "com.docker.compose.project": "mystack",
                    "com.docker.compose.service": "app",

                    # Custom labels specific to this app
                    "custom.app": "myapp",
                    "custom.tier": "backend"
                }
            },
            "HostConfig": {
                "NetworkMode": "container:gluetun",  # Depends on parent
                "RestartPolicy": {"Name": "unless-stopped"},
                "Privileged": False,
                "PortBindings": {},
                "Binds": ["/data:/app/data:rw"]
            },
            "NetworkSettings": {
                "Networks": {}  # Uses parent's network
            }
        }
        return container

    @pytest.mark.integration
    async def test_dependent_container_preserves_own_labels(
        self,
        executor,
        dependent_container_with_labels
    ):
        """
        Test that dependent containers preserve their own labels.

        When parent is updated, dependent is recreated with SAME image
        (just updating network_mode reference). Labels should NOT change.
        """
        # Execute: Extract config WITHOUT new image labels
        # (dependent containers don't get new images, just network_mode update)
        config = await executor._extract_container_config(
            dependent_container_with_labels,
            new_image_labels=None  # No new image - same image recreation
        )

        # Verify: All original labels preserved exactly
        labels = config["labels"]
        original_labels = dependent_container_with_labels.attrs["Config"]["Labels"]

        assert labels == original_labels

        # Verify specific labels unchanged
        assert labels["org.opencontainers.image.version"] == "1.5.0"  # Original version
        assert labels["custom.app"] == "myapp"
        assert labels["com.docker.compose.service"] == "app"

    @pytest.mark.integration
    async def test_dependent_container_with_minimal_labels(
        self,
        executor
    ):
        """
        Test dependent container with minimal/no labels.

        Some dependents may have very few labels.
        """
        # Setup: Minimal dependent container
        container = Mock()
        container.short_id = "minimal123456"
        container.name = "minimal-dependent"
        container.attrs = {
            "Name": "/minimal-dependent",
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "stack"  # Only compose label
                }
            },
            "HostConfig": {
                "NetworkMode": "container:parent123",
                "RestartPolicy": {}
            },
            "NetworkSettings": {"Networks": {}}
        }

        # Execute: Extract config
        config = await executor._extract_container_config(
            container,
            new_image_labels=None
        )

        # Verify: Single label preserved
        labels = config["labels"]
        assert len(labels) == 1
        assert labels["com.docker.compose.project"] == "stack"

    @pytest.mark.integration
    async def test_dependent_vs_parent_label_isolation(
        self,
        executor,
        dependent_container_with_labels
    ):
        """
        Test that dependent's labels are isolated from parent's labels.

        Even if parent gets new labels during update, dependent should
        keep its own labels (different containers, different images).
        """
        # Setup: Simulate parent's new image labels
        parent_new_labels = {
            "org.opencontainers.image.version": "3.0.0",  # Parent's new version
            "org.opencontainers.image.source": "https://github.com/gluetun/gluetun"
        }

        # Execute: Extract dependent config WITHOUT parent's labels
        # (we should never pass parent's labels to dependent)
        config = await executor._extract_container_config(
            dependent_container_with_labels,
            new_image_labels=None  # Correct: dependent keeps own labels
        )

        # Verify: Dependent has its own labels, NOT parent's labels
        labels = config["labels"]

        # Dependent's version unchanged (not parent's 3.0.0)
        assert labels["org.opencontainers.image.version"] == "1.5.0"

        # Parent's new label NOT in dependent
        assert "org.opencontainers.image.source" not in labels

        # Dependent's custom labels preserved
        assert labels["custom.app"] == "myapp"

    @pytest.mark.integration
    async def test_multiple_dependents_keep_separate_labels(
        self,
        executor
    ):
        """
        Test that multiple dependents each keep their own labels.

        Real-world scenario: gluetun VPN with multiple app containers
        depending on it. Each app has different labels.
        """
        # Setup: First dependent (app1)
        dep1 = Mock()
        dep1.short_id = "app1_1234567"
        dep1.name = "app1"
        dep1.attrs = {
            "Name": "/app1",
            "Config": {
                "Labels": {
                    "org.opencontainers.image.version": "1.0.0",
                    "custom.app": "app1",
                    "custom.tier": "frontend"
                }
            },
            "HostConfig": {"NetworkMode": "container:gluetun"},
            "NetworkSettings": {"Networks": {}}
        }

        # Setup: Second dependent (app2)
        dep2 = Mock()
        dep2.short_id = "app2_7654321"
        dep2.name = "app2"
        dep2.attrs = {
            "Name": "/app2",
            "Config": {
                "Labels": {
                    "org.opencontainers.image.version": "2.5.0",
                    "custom.app": "app2",
                    "custom.tier": "backend"
                }
            },
            "HostConfig": {"NetworkMode": "container:gluetun"},
            "NetworkSettings": {"Networks": {}}
        }

        # Execute: Extract configs for both dependents
        config1 = await executor._extract_container_config(dep1, new_image_labels=None)
        config2 = await executor._extract_container_config(dep2, new_image_labels=None)

        # Verify: Each dependent keeps its own labels
        labels1 = config1["labels"]
        labels2 = config2["labels"]

        # App1 labels
        assert labels1["org.opencontainers.image.version"] == "1.0.0"
        assert labels1["custom.app"] == "app1"
        assert labels1["custom.tier"] == "frontend"

        # App2 labels (completely different)
        assert labels2["org.opencontainers.image.version"] == "2.5.0"
        assert labels2["custom.app"] == "app2"
        assert labels2["custom.tier"] == "backend"

        # No label leakage between containers
        assert labels1 != labels2

    @pytest.mark.integration
    async def test_dependent_network_mode_updated_separately(
        self,
        executor,
        dependent_container_with_labels
    ):
        """
        Test that network_mode is updated independently of labels.

        Labels preserve old values, but network_mode gets new parent ID.
        This verifies labels and network_mode are handled separately.
        """
        # Execute: Extract config
        config = await executor._extract_container_config(
            dependent_container_with_labels,
            new_image_labels=None
        )

        # Verify: Labels preserved
        labels = config["labels"]
        assert labels["org.opencontainers.image.version"] == "1.5.0"

        # Note: network_mode update happens AFTER _extract_container_config
        # in _recreate_dependent_container (line ~1814), not during extraction.
        # This test just verifies labels aren't affected by that later update.


class TestDependentContainerEdgeCases:
    """Test edge cases for dependent container label handling"""

    @pytest.fixture
    async def executor(self, db_session, mock_event_bus):
        """Create UpdateExecutor"""
        executor = UpdateExecutor(db=db_session, monitor=None)
        executor.event_bus = mock_event_bus
        return executor

    @pytest.mark.integration
    async def test_dependent_with_dockmon_deployment_labels(
        self,
        executor
    ):
        """
        Test dependent created by DockMon deployment system.

        These have dockmon.* labels that must survive recreation.
        """
        container = Mock()
        container.short_id = "deploy123456"
        container.name = "deployed-dependent"
        container.attrs = {
            "Name": "/deployed-dependent",
            "Config": {
                "Labels": {
                    "dockmon.deployment_id": "uuid-789",
                    "dockmon.managed": "true",
                    "org.opencontainers.image.version": "1.0.0"
                }
            },
            "HostConfig": {"NetworkMode": "container:parent"},
            "NetworkSettings": {"Networks": {}}
        }

        # Execute
        config = await executor._extract_container_config(container, new_image_labels=None)

        # Verify: DockMon labels preserved
        labels = config["labels"]
        assert labels["dockmon.deployment_id"] == "uuid-789"
        assert labels["dockmon.managed"] == "true"

    @pytest.mark.integration
    async def test_dependent_with_traefik_labels(
        self,
        executor
    ):
        """
        Test dependent with complex Traefik routing labels.

        Common real-world scenario: app behind Traefik proxy.
        """
        container = Mock()
        container.short_id = "traefik12345"
        container.name = "web-with-routing"
        container.attrs = {
            "Name": "/web-with-routing",
            "Config": {
                "Labels": {
                    "traefik.enable": "true",
                    "traefik.http.routers.web.rule": "Host(`example.com`)",
                    "traefik.http.routers.web.entrypoints": "websecure",
                    "traefik.http.routers.web.tls": "true",
                    "traefik.http.services.web.loadbalancer.server.port": "8080"
                }
            },
            "HostConfig": {"NetworkMode": "container:vpn"},
            "NetworkSettings": {"Networks": {}}
        }

        # Execute
        config = await executor._extract_container_config(container, new_image_labels=None)

        # Verify: All Traefik labels preserved exactly
        labels = config["labels"]
        assert labels["traefik.enable"] == "true"
        assert labels["traefik.http.routers.web.rule"] == "Host(`example.com`)"
        assert labels["traefik.http.routers.web.entrypoints"] == "websecure"
        assert labels["traefik.http.routers.web.tls"] == "true"
        assert labels["traefik.http.services.web.loadbalancer.server.port"] == "8080"

        # No labels lost
        assert len(labels) == 5
