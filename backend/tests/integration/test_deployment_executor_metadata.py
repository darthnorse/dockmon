"""
Integration tests for DeploymentExecutor deployment_metadata tracking.

TDD Phase: RED - Write tests first for metadata creation during deployment

Tests cover:
- DeploymentExecutor creates deployment_metadata record after container creation
- Metadata includes correct composite key, host_id, deployment_id, is_managed=True
- Stack deployments track service_name in metadata
- Single container deployments have service_name=None
- Container ID uses SHORT format (12 chars) in composite key
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from database import (
    Deployment,
    DeploymentContainer,
    DeploymentMetadata,
    DockerHostDB,
    GlobalSettings,
)
from deployment.executor import DeploymentExecutor


class TestDeploymentExecutorMetadataTracking:
    """Test DeploymentExecutor creates deployment_metadata records"""

    @pytest.mark.asyncio
    async def test_executor_creates_metadata_for_container_deployment(
        self, test_db, mock_docker_client, mock_event_bus, mock_docker_monitor
    ):
        """
        DeploymentExecutor must create deployment_metadata record after container creation.

        Metadata should include:
        - container_id: composite key {host_id}:{short_id}
        - host_id: FULL UUID
        - deployment_id: deployment composite key
        - is_managed: True (created by deployment system)
        - service_name: None (single container, not stack)
        """
        # Arrange: Create host and global settings
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
        )
        test_db.add(host)

        settings = GlobalSettings(
            id=1,
            auth_enabled=False,
            pushover_enabled=False,
            app_version="2.1.1",
        )
        test_db.add(settings)
        test_db.commit()

        # Mock Docker client to return container with SHORT ID
        mock_container = MagicMock()
        mock_container.short_id = "abc123def456"  # SHORT ID (12 chars)
        mock_container.id = "abc123def456" + "0" * 52  # FULL ID (64 chars)
        mock_container.status = "running"
        mock_container.start = AsyncMock()
        mock_container.reload = AsyncMock()
        mock_container.logs = MagicMock(return_value=b"Container started")

        mock_docker_client.containers.create = AsyncMock(return_value=mock_container)
        mock_docker_client.images.pull = AsyncMock(return_value=MagicMock())
        mock_docker_client.networks.list = MagicMock(return_value=[])
        mock_docker_client.volumes.list = MagicMock(return_value=[])

        mock_docker_monitor.clients = {"host-123": mock_docker_client}

        # Create executor
        executor = DeploymentExecutor(
            event_bus=mock_event_bus,
            docker_monitor=mock_docker_monitor,
            database_manager=test_db
        )

        # Act: Create and execute deployment
        deployment_id = await executor.create_deployment(
            host_id="host-123",
            name="test-nginx",
            deployment_type="container",
            definition={"image": "nginx:alpine", "name": "test-nginx"},
        )

        # Mock image pull progress tracker to avoid threading issues in tests
        with patch.object(executor.image_pull_tracker, 'pull_with_progress', new=AsyncMock()):
            await executor.execute_deployment(deployment_id)

        # Assert: deployment_metadata record was created
        metadata = test_db.query(DeploymentMetadata).filter_by(
            container_id=f"host-123:{mock_container.short_id}"
        ).first()

        assert metadata is not None, "DeploymentMetadata record must be created"

        # Assert: Composite key format is correct
        assert metadata.container_id == "host-123:abc123def456"

        # Assert: Uses SHORT ID (12 chars) not FULL ID (64 chars)
        short_id = metadata.container_id.split(':')[1]
        assert len(short_id) == 12, f"Container ID must be SHORT (12 chars), got {len(short_id)}"

        # Assert: host_id is correct
        assert metadata.host_id == "host-123"

        # Assert: deployment_id links back to deployment
        assert metadata.deployment_id == deployment_id

        # Assert: is_managed is True (created by deployment system)
        assert metadata.is_managed is True

        # Assert: service_name is None for single containers
        assert metadata.service_name is None

        # Assert: timestamps are set
        assert metadata.created_at is not None
        assert metadata.updated_at is not None

    @pytest.mark.asyncio
    async def test_executor_metadata_uses_composite_key_not_short_id_alone(
        self, test_db, mock_docker_client, mock_event_bus, mock_docker_monitor
    ):
        """
        Metadata must use composite key {host_id}:{container_id} to prevent
        collisions when monitoring cloned VMs with duplicate container IDs.
        """
        # Arrange: Create host
        host = DockerHostDB(
            id="host-456",
            name="Clone Host",
            url="tcp://192.168.1.200:2376",
        )
        test_db.add(host)

        settings = GlobalSettings(
            id=1,
            auth_enabled=False,
            pushover_enabled=False,
            app_version="2.1.1",
        )
        test_db.add(settings)
        test_db.commit()

        # Mock container
        mock_container = MagicMock()
        mock_container.short_id = "xyz789abc012"
        mock_container.id = "xyz789abc012" + "0" * 52
        mock_container.status = "running"
        mock_container.start = AsyncMock()
        mock_container.reload = AsyncMock()
        mock_container.logs = MagicMock(return_value=b"Started")

        mock_docker_client.containers.create = AsyncMock(return_value=mock_container)
        mock_docker_client.images.pull = AsyncMock()
        mock_docker_client.networks.list = MagicMock(return_value=[])
        mock_docker_client.volumes.list = MagicMock(return_value=[])

        mock_docker_monitor.clients = {"host-456": mock_docker_client}

        executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_db)

        # Act: Execute deployment
        deployment_id = await executor.create_deployment(
            host_id="host-456",
            name="redis-test",
            deployment_type="container",
            definition={"image": "redis:alpine", "name": "redis-test"},
        )

        with patch.object(executor.image_pull_tracker, 'pull_with_progress', new=AsyncMock()):
            await executor.execute_deployment(deployment_id)

        # Assert: Metadata uses COMPOSITE KEY format
        metadata = test_db.query(DeploymentMetadata).first()
        assert metadata is not None

        # Assert: Format is {host_id}:{container_id}
        parts = metadata.container_id.split(':')
        assert len(parts) == 2, "Composite key must be {host_id}:{container_id}"
        assert parts[0] == "host-456", "First part must be host_id"
        assert parts[1] == "xyz789abc012", "Second part must be SHORT container ID"

        # Assert: NOT just container ID alone
        assert metadata.container_id != "xyz789abc012", "Must not use short_id alone (violates composite key standard)"

    @pytest.mark.asyncio
    async def test_executor_metadata_foreign_key_cascade_delete_on_host_removal(
        self, test_db, mock_docker_client, mock_event_bus, mock_docker_monitor
    ):
        """
        When host is deleted, deployment_metadata records should CASCADE delete
        (foreign key constraint: ondelete='CASCADE')
        """
        # Arrange: Create host and execute deployment
        host = DockerHostDB(
            id="host-789",
            name="Temp Host",
            url="tcp://192.168.1.50:2376",
        )
        test_db.add(host)

        settings = GlobalSettings(
            id=1,
            auth_enabled=False,
            pushover_enabled=False,
            app_version="2.1.1",
        )
        test_db.add(settings)
        test_db.commit()

        # Mock container
        mock_container = MagicMock()
        mock_container.short_id = "cascade12test"
        mock_container.id = "cascade12test" + "0" * 52
        mock_container.status = "running"
        mock_container.start = AsyncMock()
        mock_container.reload = AsyncMock()
        mock_container.logs = MagicMock(return_value=b"Running")

        mock_docker_client.containers.create = AsyncMock(return_value=mock_container)
        mock_docker_client.images.pull = AsyncMock()
        mock_docker_client.networks.list = MagicMock(return_value=[])
        mock_docker_client.volumes.list = MagicMock(return_value=[])

        mock_docker_monitor.clients = {"host-789": mock_docker_client}

        executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_db)

        deployment_id = await executor.create_deployment(
            host_id="host-789",
            name="cascade-test",
            deployment_type="container",
            definition={"image": "nginx:alpine", "name": "cascade-test"},
        )

        with patch.object(executor.image_pull_tracker, 'pull_with_progress', new=AsyncMock()):
            await executor.execute_deployment(deployment_id)

        # Verify metadata exists
        metadata_before = test_db.query(DeploymentMetadata).filter_by(
            host_id="host-789"
        ).first()
        assert metadata_before is not None

        # Act: Delete host
        test_db.delete(host)
        test_db.commit()

        # Assert: Metadata CASCADE deleted
        metadata_after = test_db.query(DeploymentMetadata).filter_by(
            host_id="host-789"
        ).first()
        assert metadata_after is None, "Metadata should CASCADE delete when host is deleted"

    @pytest.mark.asyncio
    async def test_executor_metadata_set_null_when_deployment_deleted(
        self, test_db, mock_docker_client, mock_event_bus, mock_docker_monitor
    ):
        """
        When deployment is deleted, deployment_metadata.deployment_id should SET NULL
        (foreign key constraint: ondelete='SET NULL')

        This allows containers to persist even if deployment record is removed.
        """
        # Arrange: Create host and execute deployment
        host = DockerHostDB(
            id="host-setnull",
            name="SetNull Host",
            url="tcp://192.168.1.60:2376",
        )
        test_db.add(host)

        settings = GlobalSettings(
            id=1,
            auth_enabled=False,
            pushover_enabled=False,
            app_version="2.1.1",
        )
        test_db.add(settings)
        test_db.commit()

        # Mock container
        mock_container = MagicMock()
        mock_container.short_id = "setnull12345"
        mock_container.id = "setnull12345" + "0" * 52
        mock_container.status = "running"
        mock_container.start = AsyncMock()
        mock_container.reload = AsyncMock()
        mock_container.logs = MagicMock(return_value=b"Active")

        mock_docker_client.containers.create = AsyncMock(return_value=mock_container)
        mock_docker_client.images.pull = AsyncMock()
        mock_docker_client.networks.list = MagicMock(return_value=[])
        mock_docker_client.volumes.list = MagicMock(return_value=[])

        mock_docker_monitor.clients = {"host-setnull": mock_docker_client}

        executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_db)

        deployment_id = await executor.create_deployment(
            host_id="host-setnull",
            name="setnull-deployment",
            deployment_type="container",
            definition={"image": "redis:alpine", "name": "setnull-test"},
        )

        with patch.object(executor.image_pull_tracker, 'pull_with_progress', new=AsyncMock()):
            await executor.execute_deployment(deployment_id)

        # Verify metadata links to deployment
        metadata_before = test_db.query(DeploymentMetadata).filter_by(
            container_id=f"host-setnull:setnull12345"
        ).first()
        assert metadata_before is not None
        assert metadata_before.deployment_id == deployment_id

        # Act: Delete deployment
        deployment = test_db.query(Deployment).filter_by(id=deployment_id).first()
        test_db.delete(deployment)
        test_db.commit()

        # Assert: Metadata still exists but deployment_id is NULL
        metadata_after = test_db.query(DeploymentMetadata).filter_by(
            container_id=f"host-setnull:setnull12345"
        ).first()
        assert metadata_after is not None, "Metadata should persist when deployment deleted"
        assert metadata_after.deployment_id is None, "deployment_id should be SET NULL"
        assert metadata_after.is_managed is True, "is_managed flag should remain True"

    @pytest.mark.asyncio
    async def test_executor_creates_metadata_for_each_stack_service(
        self, test_db, mock_docker_client, mock_event_bus, mock_docker_monitor
    ):
        """
        Stack deployments must create deployment_metadata for each service container
        with service_name populated.

        NOTE: Stack deployments not yet implemented (v2.1 scope reduction)
        This test will be skipped but serves as documentation for v2.2
        """
        pytest.skip("Stack deployments not implemented in v2.1 - future work for v2.2")
