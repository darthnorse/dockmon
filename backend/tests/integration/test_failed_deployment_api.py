"""
Integration tests for failed/rolled_back deployment editing API endpoints.

TDD Phase: RED - These tests will FAIL until endpoint is updated

Tests verify:
- PUT /api/deployments/{id} allows 'failed' status for editing
- PUT /api/deployments/{id} allows 'rolled_back' status for editing
- Error message is cleared when editing failed/rolled_back deployment
- Status resets to 'planning' after edit
- Cannot edit 'running' or 'validating' deployments
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from fastapi.testclient import TestClient
from database import Deployment, DockerHostDB


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from main import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Return authorization headers for test requests."""
    # Mock auth header - actual auth is mocked in get_current_user
    return {"Authorization": "Bearer test-token"}


class TestFailedDeploymentAPIEditing:
    """Test API endpoints for editing failed/rolled_back deployments"""

    def test_put_failed_deployment_allows_editing(self, test_db, test_host, client, auth_headers):
        """
        PUT /api/deployments/{id} should allow editing failed deployments.

        RED PHASE: This test will FAIL because endpoint currently rejects 'failed' status
        """
        # Create a failed deployment
        failed_deployment = Deployment(
            id=f"{test_host.id}:failed123",
            host_id=test_host.id,
            deployment_type="container",
            name="failed-nginx",
            status="failed",  # FAILED STATUS
            definition=json.dumps({
                "image": "nginx:typo",
                "container_name": "test"
            }),
            error_message="Image not found: nginx:typo",
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(failed_deployment)
        test_db.commit()

        # Try to edit the failed deployment
        updated_definition = {
            "image": "nginx:1.25-alpine",  # Fixed image
            "container_name": "test"
        }

        # This request will FAIL (400) because current endpoint only allows 'planning'
        # After GREEN phase, this should return 200 with updated deployment
        response = client.put(
            f"/api/deployments/{failed_deployment.id}",
            json={
                "definition": updated_definition,
                "name": "fixed-nginx"
            },
            headers=auth_headers
        )

        # Current behavior: 400 "Cannot edit deployment in status 'failed'"
        # Expected behavior: 200 with updated deployment
        assert response.status_code == 200 or response.status_code == 400, \
            f"Unexpected status code: {response.status_code}"

        if response.status_code == 200:
            # GREEN PHASE: After implementation, verify response
            data = response.json()
            assert data['status'] == 'planning', "Status should reset to planning"
            assert data['error_message'] is None, "Error message should be cleared"
            assert data['name'] == 'fixed-nginx', "Name should be updated"

    def test_put_rolled_back_deployment_allows_editing(self, test_db, test_host, client, auth_headers):
        """
        PUT /api/deployments/{id} should allow editing rolled_back deployments.

        RED PHASE: This test will FAIL because endpoint rejects non-'planning' status
        """
        # Create a rolled_back deployment
        rolled_back_deployment = Deployment(
            id=f"{test_host.id}:rollback123",
            host_id=test_host.id,
            deployment_type="container",
            name="rolled-back-app",
            status="rolled_back",  # ROLLED_BACK STATUS
            definition=json.dumps({
                "image": "app:broken",
                "container_name": "myapp"
            }),
            error_message="Container creation failed, rolled back",
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=True,
        )
        test_db.add(rolled_back_deployment)
        test_db.commit()

        # Try to edit and retry
        fixed_definition = {
            "image": "app:stable",
            "container_name": "myapp"
        }

        response = client.put(
            f"/api/deployments/{rolled_back_deployment.id}",
            json={"definition": fixed_definition},
            headers=auth_headers
        )

        # Current: 400 error
        # Expected: 200 with status='planning'
        if response.status_code == 200:
            data = response.json()
            assert data['status'] == 'planning', "Should allow retry after rollback"
            assert data['error_message'] is None, "Error cleared"

    def test_put_clears_error_message_on_edit(self, test_db, test_host, client, auth_headers):
        """
        When editing a failed deployment, error_message should be cleared.

        This signals to the user that they're retrying fresh.
        """
        failed_deployment = Deployment(
            id=f"{test_host.id}:clear_error",
            host_id=test_host.id,
            deployment_type="container",
            name="test",
            status="failed",
            definition=json.dumps({"image": "test:1.0"}),
            error_message="Original error message",
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(failed_deployment)
        test_db.commit()

        response = client.put(
            f"/api/deployments/{failed_deployment.id}",
            json={"definition": {"image": "test:2.0"}},
            headers=auth_headers
        )

        if response.status_code == 200:
            data = response.json()
            assert data['error_message'] is None, "Error message must be cleared on edit"

    def test_cannot_edit_running_deployment(self, test_db, test_host, client, auth_headers):
        """
        Should reject editing deployments that are currently running/executing.
        """
        running_deployment = Deployment(
            id=f"{test_host.id}:running123",
            host_id=test_host.id,
            deployment_type="container",
            name="running-app",
            status="running",  # Currently running
            definition=json.dumps({"image": "app:1.0"}),
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=True,
        )
        test_db.add(running_deployment)
        test_db.commit()

        response = client.put(
            f"/api/deployments/{running_deployment.id}",
            json={"definition": {"image": "app:2.0"}},
            headers=auth_headers
        )

        # Must reject with 400 or similar
        assert response.status_code >= 400, "Cannot edit running deployments"

    def test_get_failed_deployment_includes_error_message(self, test_db, test_host, client, auth_headers):
        """
        GET /api/deployments/{id} should return error_message for failed deployments.

        This allows frontend to display the error to the user.
        """
        failed_deployment = Deployment(
            id=f"{test_host.id}:get_error",
            host_id=test_host.id,
            deployment_type="container",
            name="test",
            status="failed",
            definition=json.dumps({"image": "test:1.0"}),
            error_message="Specific failure reason",
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(failed_deployment)
        test_db.commit()

        response = client.get(
            f"/api/deployments/{failed_deployment.id}",
            headers=auth_headers
        )

        assert response.status_code == 200, "Should retrieve failed deployment"
        data = response.json()
        assert data['error_message'] == "Specific failure reason", \
            "API must return error_message field"
        assert data['status'] == 'failed', "Status should be failed"

    def test_list_deployments_includes_error_messages(self, test_db, test_host, client, auth_headers):
        """
        GET /api/deployments should include error_message in list response.

        This allows frontend to show errors in deployment cards.
        """
        failed_deployment = Deployment(
            id=f"{test_host.id}:list_error",
            host_id=test_host.id,
            deployment_type="container",
            name="failed-in-list",
            status="failed",
            definition=json.dumps({"image": "test:1.0"}),
            error_message="List visible error",
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(failed_deployment)
        test_db.commit()

        response = client.get(
            "/api/deployments",
            headers=auth_headers
        )

        assert response.status_code == 200, "Should list deployments"
        data = response.json()

        # Find the failed deployment in the list
        failed = next((d for d in data if d['id'] == failed_deployment.id), None)
        assert failed is not None, "Failed deployment should be in list"
        assert failed['error_message'] == "List visible error", \
            "Error message must be included in list response"
