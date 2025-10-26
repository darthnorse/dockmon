"""
Unit tests for DeploymentExecutor deployment_metadata tracking.

TDD Phase: RED - Write tests first for metadata creation during deployment

Tests cover:
- DeploymentExecutor._create_deployment_metadata() creates correct metadata record
- Metadata includes correct composite key, host_id, deployment_id, is_managed=True
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


class TestDeploymentExecutorMetadataCreation:
    """Test DeploymentExecutor creates deployment_metadata records"""

    def test_create_deployment_metadata_helper_creates_record(self, test_db, test_host):
        """
        _create_deployment_metadata() must create deployment_metadata record.

        This is a helper method that will be called from _execute_container_deployment()
        after container creation.
        """
        # This test will FAIL until we implement the helper method
        from deployment.executor import DeploymentExecutor

        # Mock dependencies
        mock_event_bus = MagicMock()
        mock_event_bus.emit = AsyncMock()
        mock_docker_monitor = MagicMock()
        mock_docker_monitor.manager = MagicMock()
        mock_docker_monitor.manager.broadcast = AsyncMock()

        executor = DeploymentExecutor(
            event_bus=mock_event_bus,
            docker_monitor=mock_docker_monitor,
            database_manager=test_db  # Pass session directly (test fixture pattern)
        )

        # Create a test deployment
        deployment = Deployment(
            id=f"{test_host.id}:test123",
            host_id=test_host.id,
            deployment_type="container",
            name="test-nginx",
            status="executing",
            definition='{"image": "nginx:alpine"}',
            progress_percent=50,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: Call _create_deployment_metadata (THIS METHOD DOESN'T EXIST YET - RED PHASE)
        container_short_id = "abc123def456"  # 12 chars
        service_name = None  # Single container (not stack)

        executor._create_deployment_metadata(
            session=test_db,
            deployment_id=deployment.id,
            host_id=test_host.id,
            container_short_id=container_short_id,
            service_name=service_name
        )

        # Assert: deployment_metadata record was created
        metadata = test_db.query(DeploymentMetadata).filter_by(
            container_id=f"{test_host.id}:{container_short_id}"
        ).first()

        assert metadata is not None, "DeploymentMetadata record must be created"
        assert metadata.container_id == f"{test_host.id}:{container_short_id}"
        assert metadata.host_id == test_host.id
        assert metadata.deployment_id == deployment.id
        assert metadata.is_managed is True
        assert metadata.service_name is None

    def test_create_deployment_metadata_uses_composite_key(self, test_db, test_host):
        """
        Metadata must use composite key {host_id}:{container_id} to prevent
        collisions when monitoring cloned VMs with duplicate container IDs.
        """
        from deployment.executor import DeploymentExecutor

        mock_event_bus = MagicMock()
        mock_event_bus.emit = AsyncMock()
        mock_docker_monitor = MagicMock()
        mock_docker_monitor.manager = MagicMock()
        mock_docker_monitor.manager.broadcast = AsyncMock()

        executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_db)

        deployment = Deployment(
            id=f"{test_host.id}:deploy456",
            host_id=test_host.id,
            deployment_type="container",
            name="redis-test",
            status="executing",
            definition='{"image": "redis:alpine"}',
            progress_percent=50,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: Create metadata with SHORT ID
        container_short_id = "xyz789abc012"  # 12 chars

        executor._create_deployment_metadata(
            session=test_db,
            deployment_id=deployment.id,
            host_id=test_host.id,
            container_short_id=container_short_id,
            service_name=None
        )

        # Assert: Composite key format is correct
        metadata = test_db.query(DeploymentMetadata).first()
        assert metadata is not None

        # Assert: Format is {host_id}:{container_id}
        parts = metadata.container_id.split(':')
        assert len(parts) == 2, "Composite key must be {host_id}:{container_id}"
        assert parts[0] == test_host.id, "First part must be host_id"
        assert parts[1] == container_short_id, "Second part must be SHORT container ID"

        # Assert: Container ID is SHORT (12 chars), not FULL (64 chars)
        assert len(parts[1]) == 12, f"Container ID must be SHORT (12 chars), got {len(parts[1])}"

    def test_create_deployment_metadata_with_service_name_for_stacks(self, test_db, test_host):
        """
        Stack deployments must include service_name in metadata.

        NOTE: Stack deployments not yet implemented (v2.1 scope reduction)
        This test serves as documentation for v2.2
        """
        pytest.skip("Stack deployments not implemented in v2.1 - future work for v2.2")
