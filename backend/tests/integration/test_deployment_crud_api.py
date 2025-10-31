"""
Integration tests for deployment CRUD API endpoints.

TDD Phase: RED - Write tests first for deployment REST API

Tests cover all CRUD operations:
- POST /api/deployments (create deployment)
- GET /api/deployments (list deployments)
- GET /api/deployments/{id} (get single deployment)
- DELETE /api/deployments/{id} (delete deployment)

These are SIMPLE backend tests that should have caught the delete bug!
No Docker operations, no E2E complexity - just FastAPI endpoint testing.
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from database import (
    Deployment,
    DockerHostDB,
)


class TestDeploymentCreateAPI:
    """Test POST /api/deployments"""

    def test_create_deployment_returns_201(self, client, test_db):
        """POST /api/deployments should return 201 Created"""
        # Arrange: Create host
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
        )
        test_db.add(host)
        test_db.commit()

        # Act: Create deployment
        payload = {
            "host_id": "host-123",
            "name": "test-nginx",
            "deployment_type": "container",
            "definition": {
                "image": "nginx:latest",
                "ports": {"80/tcp": 8080}
            },
            "rollback_on_failure": True
        }
        response = client.post("/api/deployments", json=payload)

        # Assert: 201 Created
        assert response.status_code == 201

        # Assert: Response has deployment fields
        data = response.json()
        assert "id" in data
        assert data["host_id"] == "host-123"
        assert data["name"] == "test-nginx"
        assert data["deployment_type"] == "container"
        assert data["status"] == "planning"
        assert data["progress_percent"] == 0
        assert data["committed"] is False
        assert data["rollback_on_failure"] is True

    def test_create_deployment_duplicate_name_returns_400(self, client, test_db):
        """POST /api/deployments should reject duplicate names on same host"""
        # Arrange: Create host and deployment
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
        )
        test_db.add(host)

        existing = Deployment(
            id="host-123:dep_001",
            host_id="host-123",
            deployment_type="container",
            name="test-nginx",
            status="completed",
            definition='{"image": "nginx:latest"}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(existing)
        test_db.commit()

        # Act: Try to create deployment with same name
        payload = {
            "host_id": "host-123",
            "name": "test-nginx",  # Duplicate!
            "deployment_type": "container",
            "definition": {"image": "redis:latest"},
            "rollback_on_failure": True
        }
        response = client.post("/api/deployments", json=payload)

        # Assert: 400 Bad Request
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower() or "duplicate" in response.json()["detail"].lower()


class TestDeploymentListAPI:
    """Test GET /api/deployments"""

    def test_list_deployments_returns_200(self, client, test_db):
        """GET /api/deployments should return 200 OK"""
        # Act
        response = client.get("/api/deployments")

        # Assert
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_deployments_empty_when_no_records(self, client, test_db):
        """GET /api/deployments should return empty array when no deployments"""
        # Act
        response = client.get("/api/deployments")

        # Assert
        assert response.status_code == 200
        assert response.json() == []

    def test_list_deployments_returns_all_deployments(self, client, test_db):
        """GET /api/deployments should return all deployments"""
        # Arrange: Create host and deployments
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
        )
        test_db.add(host)

        deployments = [
            Deployment(
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
            ),
            Deployment(
                id="host-123:dep_002",
                host_id="host-123",
                deployment_type="container",
                name="redis-deployment",
                status="planning",
                definition='{"image": "redis:latest"}',
                progress_percent=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                committed=False,
                rollback_on_failure=True,
            ),
        ]
        for deployment in deployments:
            test_db.add(deployment)
        test_db.commit()

        # Act
        response = client.get("/api/deployments")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

        # Verify deployment names
        names = {d["name"] for d in data}
        assert "nginx-deployment" in names
        assert "redis-deployment" in names

    def test_list_deployments_filter_by_host(self, client, test_db):
        """GET /api/deployments?host_id=X should filter by host"""
        # Arrange: Create two hosts with deployments
        host1 = DockerHostDB(id="host-1", name="Host 1", url="tcp://192.168.1.1:2376")
        host2 = DockerHostDB(id="host-2", name="Host 2", url="tcp://192.168.1.2:2376")
        test_db.add(host1)
        test_db.add(host2)

        dep1 = Deployment(
            id="host-1:dep_001",
            host_id="host-1",
            deployment_type="container",
            name="nginx-1",
            status="completed",
            definition='{"image": "nginx:latest"}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        dep2 = Deployment(
            id="host-2:dep_002",
            host_id="host-2",
            deployment_type="container",
            name="nginx-2",
            status="completed",
            definition='{"image": "nginx:latest"}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(dep1)
        test_db.add(dep2)
        test_db.commit()

        # Act: Filter by host-1
        response = client.get("/api/deployments?host_id=host-1")

        # Assert: Only host-1 deployment returned
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["host_id"] == "host-1"
        assert data[0]["name"] == "nginx-1"

    def test_list_deployments_filter_by_status(self, client, test_db):
        """GET /api/deployments?status=X should filter by status"""
        # Arrange: Create host and deployments with different statuses
        host = DockerHostDB(id="host-123", name="Test Host", url="tcp://192.168.1.1:2376")
        test_db.add(host)

        deployments = [
            Deployment(
                id="host-123:dep_001",
                host_id="host-123",
                deployment_type="container",
                name="completed-deploy",
                status="completed",
                definition='{"image": "nginx:latest"}',
                progress_percent=100,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                committed=True,
                rollback_on_failure=False,
            ),
            Deployment(
                id="host-123:dep_002",
                host_id="host-123",
                deployment_type="container",
                name="planning-deploy",
                status="planning",
                definition='{"image": "redis:latest"}',
                progress_percent=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                committed=False,
                rollback_on_failure=True,
            ),
        ]
        for deployment in deployments:
            test_db.add(deployment)
        test_db.commit()

        # Act: Filter by status=completed
        response = client.get("/api/deployments?status=completed")

        # Assert: Only completed deployment returned
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "completed"
        assert data[0]["name"] == "completed-deploy"


class TestDeploymentGetAPI:
    """Test GET /api/deployments/{id}"""

    def test_get_deployment_returns_200(self, client, test_db):
        """GET /api/deployments/{id} should return 200 OK for existing deployment"""
        # Arrange: Create host and deployment
        host = DockerHostDB(id="host-123", name="Test Host", url="tcp://192.168.1.1:2376")
        test_db.add(host)

        deployment = Deployment(
            id="host-123:dep_abc123",
            host_id="host-123",
            deployment_type="container",
            name="test-nginx",
            status="completed",
            definition='{"image": "nginx:latest"}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: GET deployment by ID (URL-encoded composite key)
        response = client.get("/api/deployments/host-123:dep_abc123")

        # Assert: 200 OK
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "host-123:dep_abc123"
        assert data["name"] == "test-nginx"
        assert data["status"] == "completed"

    def test_get_deployment_404_when_not_found(self, client, test_db):
        """GET /api/deployments/{id} should return 404 for non-existent deployment"""
        # Act: GET non-existent deployment
        response = client.get("/api/deployments/host-123:nonexistent")

        # Assert: 404 Not Found
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestDeploymentDeleteAPI:
    """Test DELETE /api/deployments/{id}"""

    def test_delete_deployment_completed_returns_200(self, client, test_db):
        """
        DELETE /api/deployments/{id} should successfully delete COMPLETED deployment

        THIS TEST SHOULD HAVE CAUGHT THE BUG!
        """
        # Arrange: Create host and COMPLETED deployment
        host = DockerHostDB(id="host-123", name="Test Host", url="tcp://192.168.1.1:2376")
        test_db.add(host)

        deployment = Deployment(
            id="host-123:dep_abc123",
            host_id="host-123",
            deployment_type="container",
            name="test-nginx",
            status="completed",  # Terminal state - should be deletable
            definition='{"image": "nginx:latest"}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: DELETE deployment
        response = client.delete("/api/deployments/host-123:dep_abc123")

        # Assert: 200 OK
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Assert: Deployment deleted from database
        deleted = test_db.query(Deployment).filter_by(id="host-123:dep_abc123").first()
        assert deleted is None

    def test_delete_deployment_failed_returns_200(self, client, test_db):
        """DELETE /api/deployments/{id} should successfully delete FAILED deployment"""
        # Arrange: Create host and FAILED deployment
        host = DockerHostDB(id="host-123", name="Test Host", url="tcp://192.168.1.1:2376")
        test_db.add(host)

        deployment = Deployment(
            id="host-123:dep_abc123",
            host_id="host-123",
            deployment_type="container",
            name="test-nginx",
            status="failed",  # Terminal state - should be deletable
            definition='{"image": "nginx:latest"}',
            error_message="Image not found",
            progress_percent=50,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: DELETE deployment
        response = client.delete("/api/deployments/host-123:dep_abc123")

        # Assert: 200 OK
        assert response.status_code == 200

    def test_delete_deployment_rolled_back_returns_200(self, client, test_db):
        """DELETE /api/deployments/{id} should successfully delete ROLLED_BACK deployment"""
        # Arrange: Create host and ROLLED_BACK deployment
        host = DockerHostDB(id="host-123", name="Test Host", url="tcp://192.168.1.1:2376")
        test_db.add(host)

        deployment = Deployment(
            id="host-123:dep_abc123",
            host_id="host-123",
            deployment_type="container",
            name="test-nginx",
            status="rolled_back",  # Terminal state - should be deletable
            definition='{"image": "nginx:latest"}',
            error_message="Deployment failed, rolled back",
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: DELETE deployment
        response = client.delete("/api/deployments/host-123:dep_abc123")

        # Assert: 200 OK
        assert response.status_code == 200

    def test_delete_deployment_planning_returns_200(self, client, test_db):
        """
        DELETE /api/deployments/{id} should successfully delete PLANNING deployment

        FIX: Users should be able to delete deployments in 'planning' status
        since nothing has been executed yet. Only 'executing' should be blocked.
        """
        # Arrange: Create host and PLANNING deployment
        host = DockerHostDB(id="host-123", name="Test Host", url="tcp://192.168.1.1:2376")
        test_db.add(host)

        deployment = Deployment(
            id="host-123:dep_abc123",
            host_id="host-123",
            deployment_type="container",
            name="test-nginx",
            status="planning",  # Should be deletable - nothing executed yet
            definition='{"image": "nginx:latest"}',
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: DELETE deployment
        response = client.delete("/api/deployments/host-123:dep_abc123")

        # Assert: 200 OK (planning deployments can be deleted)
        assert response.status_code == 200
        assert response.json()["success"] is True

        # Assert: Deployment deleted from database
        deleted = test_db.query(Deployment).filter_by(id="host-123:dep_abc123").first()
        assert deleted is None

    def test_delete_deployment_executing_returns_400(self, client, test_db):
        """DELETE /api/deployments/{id} should return 400 for EXECUTING deployment"""
        # Arrange: Create host and EXECUTING deployment
        host = DockerHostDB(id="host-123", name="Test Host", url="tcp://192.168.1.1:2376")
        test_db.add(host)

        deployment = Deployment(
            id="host-123:dep_abc123",
            host_id="host-123",
            deployment_type="container",
            name="test-nginx",
            status="executing",  # NOT terminal state - should NOT be deletable
            definition='{"image": "nginx:latest"}',
            progress_percent=50,
            current_stage="Pulling image",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: DELETE deployment
        response = client.delete("/api/deployments/host-123:dep_abc123")

        # Assert: 400 Bad Request
        assert response.status_code == 400
        assert "cannot delete" in response.json()["detail"].lower()

    def test_delete_deployment_404_when_not_found(self, client, test_db):
        """DELETE /api/deployments/{id} should return 404 for non-existent deployment"""
        # Act: DELETE non-existent deployment
        response = client.delete("/api/deployments/host-123:nonexistent")

        # Assert: 404 Not Found
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
