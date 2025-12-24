"""
Integration tests for label subtraction during container updates.

Tests the complete update flow with label handling:
1. Create container with labels from old image
2. Execute update to new image (with different labels)
3. Verify label subtraction preserves user labels and removes stale image labels
"""
import pytest
import asyncio
import docker
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from updates.update_executor import UpdateExecutor
from database import DatabaseManager, ContainerUpdate
from event_bus import Event, EventType


class TestLabelSubtractionIntegration:
    """Integration tests for label subtraction during container updates"""

    @pytest.fixture
    def mock_docker_client(self):
        """Mock Docker client with all required methods"""
        client = Mock(spec=docker.DockerClient)

        # Mock containers attribute
        client.containers = Mock()

        # Mock images attribute
        client.images = Mock()

        # Mock networks attribute
        client.networks = Mock()
        client.networks.get = Mock(return_value=Mock())

        # Mock api attribute for inspect
        client.api = Mock()

        return client

    @pytest.fixture
    def mock_old_container(self):
        """Mock old container with labels from old image + user labels"""
        container = Mock()
        container.id = "abc123def456" * 5 + "abcd"  # 64 chars
        container.short_id = "abc123def456"
        container.name = "test-container"
        container.status = "running"

        # Container has image labels + user labels
        container.labels = {
            "org.opencontainers.image.version": "1.0",
            "immich.migration_version": "5.0",  # Stale label (will be removed in new image)
            "com.docker.compose.service": "immich",  # User/compose label
            "environment": "production"  # User label
        }

        # Image mock
        container.image = Mock()
        container.image.id = "sha256:oldimage123"
        container.image.tags = ["immich:v1.0"]

        # Attrs for full config
        container.attrs = {
            "Config": {
                "Labels": container.labels,
                "Env": ["PATH=/usr/bin"],
                "Cmd": ["/start.sh"],
                "WorkingDir": "/app",
                "User": "",
                "Hostname": "test-container",
                "Domainname": "",
                "AttachStdin": False,
                "AttachStdout": False,
                "AttachStderr": False,
                "Tty": False,
                "OpenStdin": False,
                "StdinOnce": False,
            },
            "HostConfig": {
                "Binds": ["/data:/data"],
                "NetworkMode": "bridge",
                "RestartPolicy": {"Name": "unless-stopped"},
                "PortBindings": {},
                "Privileged": False,
                "PublishAllPorts": False,
            },
            "NetworkSettings": {
                "Networks": {
                    "bridge": {
                        "NetworkID": "net123",
                        "EndpointID": "ep123",
                        "Gateway": "172.17.0.1",
                        "IPAddress": "172.17.0.2",
                    }
                }
            },
            "Mounts": []
        }

        return container

    @pytest.fixture
    def mock_old_image(self):
        """Mock old image with labels"""
        image = Mock()
        image.id = "sha256:oldimage123"
        image.tags = ["immich:v1.0"]

        # Old image labels
        image.attrs = {
            "Config": {
                "Labels": {
                    "org.opencontainers.image.version": "1.0",
                    "immich.migration_version": "5.0"  # This will be removed in new image
                }
            }
        }

        return image

    @pytest.fixture
    def mock_new_image(self):
        """Mock new image with updated labels (migration_version removed)"""
        image = Mock()
        image.id = "sha256:newimage456"
        image.tags = ["immich:v2.0"]

        # New image labels - migration_version intentionally removed
        image.attrs = {
            "Config": {
                "Labels": {
                    "org.opencontainers.image.version": "2.0"
                    # immich.migration_version removed - no longer needed
                }
            }
        }

        return image

    @pytest.fixture
    def mock_new_container(self):
        """Mock new container created after update"""
        container = Mock()
        container.id = "xyz789uvw012" * 5 + "xyzu"  # Different 64 char ID
        container.short_id = "xyz789uvw012"
        container.name = "test-container"
        container.status = "running"

        # New container should have: new image labels + user labels (no stale labels)
        container.labels = {
            "org.opencontainers.image.version": "2.0",  # From new image
            "com.docker.compose.service": "immich",  # User/compose preserved
            "environment": "production"  # User preserved
            # immich.migration_version NOT present (correctly removed)
        }

        container.attrs = {
            "Config": {
                "Labels": container.labels,
            },
            "State": {
                "Status": "running",
                "Running": True,
                "ExitCode": 0,
            }
        }

        return container

    @pytest.fixture
    def mock_db(self):
        """Mock database"""
        db = Mock(spec=DatabaseManager)
        return db

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus"""
        return Mock()

    @pytest.fixture
    def executor(self, mock_db, mock_event_bus):
        """Create UpdateExecutor with mocked dependencies"""
        monitor = Mock()
        monitor.manager = Mock()
        monitor.manager.send_to_host = AsyncMock()

        executor = UpdateExecutor(db=mock_db, monitor=monitor)
        return executor

    @pytest.mark.asyncio
    async def test_label_subtraction_removes_stale_labels(
        self,
        executor,
        mock_docker_client,
        mock_old_container,
        mock_old_image,
        mock_new_image,
        mock_new_container,
        test_host
    ):
        """Test that label subtraction removes stale image labels during update"""

        # Setup: Mock Docker client methods
        mock_docker_client.containers.get = Mock(return_value=mock_old_container)
        mock_docker_client.images.get = Mock(side_effect=[
            mock_old_image,  # First call: old image
            mock_new_image   # Second call: new image
        ])
        mock_docker_client.images.pull = Mock(return_value=mock_new_image)
        mock_docker_client.containers.create = Mock(return_value=mock_new_container)

        # Mock the async_docker_call to use our mocked methods
        with patch('updates.update_executor.async_docker_call', side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            # Extract container config (this calls _extract_user_labels internally)
            config = await executor._extract_container_config_v2(
                mock_old_container,
                mock_docker_client,
                old_image_labels=mock_old_image.attrs["Config"]["Labels"],
                new_image_labels=mock_new_image.attrs["Config"]["Labels"],
                is_podman=False
            )

        # Verify: Labels passed to container create should be user labels only
        # Should NOT include stale immich.migration_version
        # Should NOT include org.opencontainers.image.version (Docker will merge from new image)
        expected_labels = {
            "com.docker.compose.service": "immich",
            "environment": "production"
        }

        assert config["labels"] == expected_labels
        assert "immich.migration_version" not in config["labels"]
        assert "org.opencontainers.image.version" not in config["labels"]

    @pytest.mark.asyncio
    async def test_label_extraction_preserves_traefik_labels(
        self,
        executor,
        mock_docker_client,
        mock_old_container,
        mock_old_image,
        mock_new_image
    ):
        """Test that Traefik reverse proxy labels are preserved during update"""

        # Setup: Container with Traefik labels
        traefik_labels = {
            "traefik.enable": "true",
            "traefik.http.routers.app.rule": "Host(`example.com`)",
            "traefik.http.services.app.loadbalancer.server.port": "80",
            "org.opencontainers.image.version": "1.0"
        }
        mock_old_container.labels = traefik_labels
        mock_old_container.attrs["Config"]["Labels"] = traefik_labels

        # Old image only has version label
        old_image_labels = {"org.opencontainers.image.version": "1.0"}
        mock_old_image.attrs["Config"]["Labels"] = old_image_labels

        # New image has updated version
        new_image_labels = {"org.opencontainers.image.version": "2.0"}
        mock_new_image.attrs["Config"]["Labels"] = new_image_labels

        with patch('updates.update_executor.async_docker_call', side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            config = await executor._extract_container_config_v2(
                mock_old_container,
                mock_docker_client,
                old_image_labels=old_image_labels,
                new_image_labels=new_image_labels,
                is_podman=False
            )

        # Verify: All Traefik labels preserved (infrastructure labels)
        assert config["labels"]["traefik.enable"] == "true"
        assert "Host(`example.com`)" in config["labels"]["traefik.http.routers.app.rule"]
        assert config["labels"]["traefik.http.services.app.loadbalancer.server.port"] == "80"

        # Version label removed (will come from new image)
        assert "org.opencontainers.image.version" not in config["labels"]

    @pytest.mark.asyncio
    async def test_label_extraction_preserves_compose_labels(
        self,
        executor,
        mock_docker_client,
        mock_old_container,
        mock_old_image,
        mock_new_image
    ):
        """Test that Docker Compose labels are preserved during update"""

        # Setup: Container with Compose labels
        compose_labels = {
            "com.docker.compose.project": "myapp",
            "com.docker.compose.service": "web",
            "com.docker.compose.version": "2.20.0",
            "com.docker.compose.container-number": "1",
            "org.opencontainers.image.version": "latest"
        }
        mock_old_container.labels = compose_labels
        mock_old_container.attrs["Config"]["Labels"] = compose_labels

        old_image_labels = {"org.opencontainers.image.version": "latest"}
        mock_old_image.attrs["Config"]["Labels"] = old_image_labels

        new_image_labels = {"org.opencontainers.image.version": "v2.0"}
        mock_new_image.attrs["Config"]["Labels"] = new_image_labels

        with patch('updates.update_executor.async_docker_call', side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            config = await executor._extract_container_config_v2(
                mock_old_container,
                mock_docker_client,
                old_image_labels=old_image_labels,
                new_image_labels=new_image_labels,
                is_podman=False
            )

        # Verify: All Compose labels preserved
        assert config["labels"]["com.docker.compose.project"] == "myapp"
        assert config["labels"]["com.docker.compose.service"] == "web"
        assert config["labels"]["com.docker.compose.version"] == "2.20.0"
        assert config["labels"]["com.docker.compose.container-number"] == "1"

        # Image label removed
        assert "org.opencontainers.image.version" not in config["labels"]

    @pytest.mark.asyncio
    async def test_label_extraction_handles_user_customized_labels(
        self,
        executor,
        mock_docker_client,
        mock_old_container,
        mock_old_image,
        mock_new_image
    ):
        """Test that user customizations to image labels are preserved"""

        # Setup: User customized an image label
        custom_labels = {
            "version": "custom-build",  # User customized this
            "author": "official"  # User kept default
        }
        mock_old_container.labels = custom_labels
        mock_old_container.attrs["Config"]["Labels"] = custom_labels

        old_image_labels = {
            "version": "1.0",
            "author": "official"
        }
        mock_old_image.attrs["Config"]["Labels"] = old_image_labels

        new_image_labels = {
            "version": "2.0",
            "author": "new-author"
        }
        mock_new_image.attrs["Config"]["Labels"] = new_image_labels

        with patch('updates.update_executor.async_docker_call', side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            config = await executor._extract_container_config_v2(
                mock_old_container,
                mock_docker_client,
                old_image_labels=old_image_labels,
                new_image_labels=new_image_labels,
                is_podman=False
            )

        # Verify: Customized label preserved, default removed
        assert config["labels"]["version"] == "custom-build"
        assert "author" not in config["labels"]  # User didn't customize, let new image provide it

    @pytest.mark.asyncio
    async def test_label_extraction_fallback_on_old_image_failure(
        self,
        executor,
        mock_docker_client,
        mock_old_container,
        mock_new_image
    ):
        """Test fallback behavior when old image inspection fails"""

        # Setup: Container with labels
        fallback_labels = {
            "version": "1.0",
            "custom": "value"
        }
        mock_old_container.labels = fallback_labels
        mock_old_container.attrs["Config"]["Labels"] = fallback_labels

        # Old image inspection will fail
        mock_docker_client.images.get = Mock(side_effect=Exception("Image not found"))

        # Should still work with defensive fallback (treat all labels as user labels)
        with patch('updates.update_executor.async_docker_call', side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            config = await executor._extract_container_config_v2(
                mock_old_container,
                mock_docker_client,
                old_image_labels={},  # Empty fallback
                new_image_labels=mock_new_image.attrs["Config"]["Labels"],
                is_podman=False
            )

        # Verify: All container labels preserved (safer fallback)
        assert config["labels"]["version"] == "1.0"
        assert config["labels"]["custom"] == "value"

    @pytest.mark.asyncio
    async def test_label_extraction_empty_labels(
        self,
        executor,
        mock_docker_client,
        mock_old_container,
        mock_old_image,
        mock_new_image
    ):
        """Test handling of containers and images with no labels"""

        # Setup: No labels anywhere
        mock_old_container.labels = {}
        mock_old_container.attrs["Config"]["Labels"] = {}
        mock_old_image.attrs["Config"]["Labels"] = {}
        mock_new_image.attrs["Config"]["Labels"] = {}

        with patch('updates.update_executor.async_docker_call', side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            config = await executor._extract_container_config_v2(
                mock_old_container,
                mock_docker_client,
                old_image_labels={},
                new_image_labels={},
                is_podman=False
            )

        # Verify: Empty labels dict
        assert config["labels"] == {}

    @pytest.mark.asyncio
    async def test_label_extraction_all_labels_match_image(
        self,
        executor,
        mock_docker_client,
        mock_old_container,
        mock_old_image,
        mock_new_image
    ):
        """Test case where all container labels came from image (no user labels)"""

        # Setup: All container labels match image
        labels = {
            "version": "1.0",
            "author": "official",
            "maintainer": "team"
        }
        mock_old_container.labels = labels.copy()
        mock_old_container.attrs["Config"]["Labels"] = labels.copy()
        old_image_labels = labels.copy()
        mock_old_image.attrs["Config"]["Labels"] = old_image_labels
        new_image_labels = {"version": "2.0"}
        mock_new_image.attrs["Config"]["Labels"] = new_image_labels

        with patch('updates.update_executor.async_docker_call', side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            config = await executor._extract_container_config_v2(
                mock_old_container,
                mock_docker_client,
                old_image_labels=old_image_labels,
                new_image_labels=new_image_labels,
                is_podman=False
            )

        # Verify: All labels removed (all were from image)
        assert config["labels"] == {}
