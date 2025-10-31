"""
Integration tests for deployment metadata API endpoints.

TDD Phase: RED - Write tests first for batch endpoint /api/deployment-metadata

Tests cover:
- GET /api/deployment-metadata returns all metadata as dictionary
- Response format matches {container_id: {host_id, deployment_id, is_managed, service_name}}
- Empty result when no metadata exists
- Performance with multiple records
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from database import (
    DeploymentMetadata,
    Deployment,
    DockerHostDB,
)


class TestDeploymentMetadataAPIEndpoint:
    """Test GET /api/deployment-metadata batch endpoint"""

    def test_get_all_deployment_metadata_returns_dictionary(self, client, test_db):
        """
        GET /api/deployment-metadata should return all metadata as dictionary
        Format: {container_id: {host_id, deployment_id, is_managed, service_name, ...}}
        """
        # Arrange: Create host, deployment, and metadata
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
        )
        test_db.add(host)

        deployment = Deployment(
            id="host-123:dep_abc123",
            host_id="host-123",
            deployment_type="container",
            name="test-deployment",
            status="completed",
            definition='{"image": "nginx:latest"}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment)

        metadata = DeploymentMetadata(
            container_id="host-123:abc123def456",
            host_id="host-123",
            deployment_id="host-123:dep_abc123",
            is_managed=True,
            service_name=None,
        )
        test_db.add(metadata)
        test_db.commit()

        # Act: GET /api/deployment-metadata
        response = client.get("/api/deployment-metadata")

        # Assert: Response is 200 OK
        assert response.status_code == 200

        # Assert: Response is a dictionary
        data = response.json()
        assert isinstance(data, dict)

        # Assert: Container ID is key
        assert "host-123:abc123def456" in data

        # Assert: Metadata fields are present
        container_metadata = data["host-123:abc123def456"]
        assert container_metadata["host_id"] == "host-123"
        assert container_metadata["deployment_id"] == "host-123:dep_abc123"
        assert container_metadata["is_managed"] is True
        assert container_metadata["service_name"] is None
        assert "created_at" in container_metadata
        assert "updated_at" in container_metadata

    def test_get_all_deployment_metadata_empty_when_no_records(self, client, test_db):
        """GET /api/deployment-metadata should return empty dict when no metadata exists"""
        # Act: GET /api/deployment-metadata (no records in DB)
        response = client.get("/api/deployment-metadata")

        # Assert: Response is 200 OK with empty dict
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert len(data) == 0

    def test_get_all_deployment_metadata_multiple_records(self, client, test_db):
        """GET /api/deployment-metadata should return all metadata records"""
        # Arrange: Create host and multiple metadata records
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
        )
        test_db.add(host)

        deployment1 = Deployment(
            id="host-123:dep_001",
            host_id="host-123",
            deployment_type="container",
            name="nginx-deployment",
            status="completed",
            definition='{"image": "nginx:latest"}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment1)

        deployment2 = Deployment(
            id="host-123:dep_002",
            host_id="host-123",
            deployment_type="container",
            name="redis-deployment",
            status="completed",
            definition='{"image": "redis:latest"}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment2)

        # Create 3 metadata records
        metadata_records = [
            DeploymentMetadata(
                container_id="host-123:container_001",
                host_id="host-123",
                deployment_id="host-123:dep_001",
                is_managed=True,
            ),
            DeploymentMetadata(
                container_id="host-123:container_002",
                host_id="host-123",
                deployment_id="host-123:dep_002",
                is_managed=True,
            ),
            DeploymentMetadata(
                container_id="host-123:container_003",
                host_id="host-123",
                deployment_id=None,  # Not linked to deployment
                is_managed=False,
            ),
        ]
        for metadata in metadata_records:
            test_db.add(metadata)
        test_db.commit()

        # Act: GET /api/deployment-metadata
        response = client.get("/api/deployment-metadata")

        # Assert: All 3 records returned
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

        # Assert: All container IDs present
        assert "host-123:container_001" in data
        assert "host-123:container_002" in data
        assert "host-123:container_003" in data

        # Assert: Deployment IDs correct
        assert data["host-123:container_001"]["deployment_id"] == "host-123:dep_001"
        assert data["host-123:container_002"]["deployment_id"] == "host-123:dep_002"
        assert data["host-123:container_003"]["deployment_id"] is None

    def test_get_all_deployment_metadata_includes_stack_service_names(self, client, test_db):
        """GET /api/deployment-metadata should include service_name for stack deployments"""
        # Arrange: Create host and stack deployment
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
        )
        test_db.add(host)

        deployment = Deployment(
            id="host-123:dep_stack001",
            host_id="host-123",
            deployment_type="stack",
            name="wordpress-stack",
            status="completed",
            definition='{"services": {}}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment)

        # Create metadata for stack services
        metadata_web = DeploymentMetadata(
            container_id="host-123:web_container",
            host_id="host-123",
            deployment_id="host-123:dep_stack001",
            is_managed=True,
            service_name="web",
        )
        metadata_db = DeploymentMetadata(
            container_id="host-123:db_container",
            host_id="host-123",
            deployment_id="host-123:dep_stack001",
            is_managed=True,
            service_name="database",
        )
        test_db.add(metadata_web)
        test_db.add(metadata_db)
        test_db.commit()

        # Act: GET /api/deployment-metadata
        response = client.get("/api/deployment-metadata")

        # Assert: Service names included
        assert response.status_code == 200
        data = response.json()
        assert data["host-123:web_container"]["service_name"] == "web"
        assert data["host-123:db_container"]["service_name"] == "database"

    def test_get_all_deployment_metadata_timestamps_have_z_suffix(self, client, test_db):
        """GET /api/deployment-metadata timestamps must have 'Z' suffix for frontend"""
        # Arrange: Create host and metadata
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
        )
        test_db.add(host)

        metadata = DeploymentMetadata(
            container_id="host-123:abc123def456",
            host_id="host-123",
            deployment_id=None,
            is_managed=False,
        )
        test_db.add(metadata)
        test_db.commit()

        # Act: GET /api/deployment-metadata
        response = client.get("/api/deployment-metadata")

        # Assert: Timestamps have 'Z' suffix
        assert response.status_code == 200
        data = response.json()
        container_data = data["host-123:abc123def456"]

        # Assert: created_at ends with 'Z'
        assert container_data["created_at"].endswith("Z")

        # Assert: updated_at ends with 'Z'
        assert container_data["updated_at"].endswith("Z")
