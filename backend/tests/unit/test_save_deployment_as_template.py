"""
Unit tests for "Save as Template" API endpoint.

TDD Phase: RED - Write tests first for POST /api/deployments/{id}/save-as-template

Tests cover:
- Successfully creating template from deployment
- 404 when deployment not found
- 409 when template name already exists
- Validation of deployment state before saving (optional)
- Created template appears in database with correct fields
- Template inherits deployment configuration
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from database import Deployment, DeploymentTemplate, DockerHostDB


class TestSaveDeploymentAsTemplate:
    """Test POST /api/deployments/{deployment_id}/save-as-template endpoint"""

    def test_save_deployment_as_template_creates_template(self, test_db, test_host):
        """
        POST /api/deployments/{id}/save-as-template must create a new template.

        This is the core "Save as Template" functionality that allows users to
        convert successful deployments into reusable templates.

        THIS TEST WILL FAIL - endpoint doesn't exist yet (RED phase)
        """
        # Arrange: Create a successful deployment
        deployment = Deployment(
            id=f"{test_host.id}:deploy123",
            host_id=test_host.id,
            deployment_type="container",
            name="my-nginx-deployment",
            status="running",
            definition=json.dumps({
                "image": "nginx:alpine",
                "ports": ["80:80", "443:443"],
                "environment": {"ENV": "production"},
                "restart": "unless-stopped"
            }),
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: Save deployment as template
        # (This endpoint doesn't exist yet - will fail)
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        response = client.post(
            f"/api/deployments/{deployment.id}/save-as-template",
            json={
                "name": "nginx-web-server",
                "category": "web-servers",
                "description": "Production-ready nginx template"
            }
        )

        # Assert: Template was created
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        result = response.json()
        assert "id" in result
        assert result["name"] == "nginx-web-server"
        assert result["category"] == "web-servers"
        assert result["deployment_type"] == "container"

        # Verify template in database
        template = test_db.query(DeploymentTemplate).filter_by(
            name="nginx-web-server"
        ).first()

        assert template is not None, "Template must be created in database"
        assert template.name == "nginx-web-server"
        assert template.category == "web-servers"
        assert template.description == "Production-ready nginx template"
        assert template.deployment_type == "container"

        # Template should have same definition as deployment
        template_def = json.loads(template.template_definition)
        deployment_def = json.loads(deployment.definition)
        assert template_def == deployment_def

        assert template.is_builtin is False
        assert template.created_at is not None
        assert template.updated_at is not None

    def test_save_deployment_as_template_returns_404_for_nonexistent_deployment(self, test_db, test_host):
        """
        POST /api/deployments/{id}/save-as-template must return 404 if deployment not found.

        THIS TEST WILL FAIL - endpoint doesn't exist yet (RED phase)
        """
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        # Act: Try to save nonexistent deployment
        response = client.post(
            f"/api/deployments/{test_host.id}:nonexistent/save-as-template",
            json={
                "name": "test-template",
                "category": "web"
            }
        )

        # Assert: 404 returned
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_save_deployment_as_template_returns_409_for_duplicate_name(self, test_db, test_host):
        """
        POST /api/deployments/{id}/save-as-template must return 409 if template name exists.

        This prevents accidentally overwriting existing templates.

        THIS TEST WILL FAIL - endpoint doesn't exist yet (RED phase)
        """
        # Arrange: Create a deployment
        deployment = Deployment(
            id=f"{test_host.id}:deploy456",
            host_id=test_host.id,
            deployment_type="container",
            name="my-postgres",
            status="running",
            definition=json.dumps({"image": "postgres:15"}),
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment)

        # Create an existing template with same name
        existing_template = DeploymentTemplate(
            id="tpl_existing",
            name="postgres-db",
            deployment_type="container",
            template_definition=json.dumps({"image": "postgres:14"}),
            is_builtin=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db.add(existing_template)
        test_db.commit()

        # Act: Try to save deployment with duplicate name
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        response = client.post(
            f"/api/deployments/{deployment.id}/save-as-template",
            json={
                "name": "postgres-db",  # Duplicate!
                "category": "databases"
            }
        )

        # Assert: 409 Conflict
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    def test_save_deployment_as_template_uses_deployment_description_as_fallback(self, test_db, test_host):
        """
        If no description provided, use "Template created from deployment '{name}'"

        THIS TEST WILL FAIL - endpoint doesn't exist yet (RED phase)
        """
        # Arrange: Create deployment
        deployment = Deployment(
            id=f"{test_host.id}:deploy789",
            host_id=test_host.id,
            deployment_type="stack",
            name="my-wordpress-stack",
            status="running",
            definition=json.dumps({
                "services": {
                    "wordpress": {"image": "wordpress:latest"},
                    "mysql": {"image": "mysql:8"}
                }
            }),
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: Save without description
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        response = client.post(
            f"/api/deployments/{deployment.id}/save-as-template",
            json={
                "name": "wordpress-stack"
                # No description provided
            }
        )

        # Assert: Uses default description
        assert response.status_code == 200

        template = test_db.query(DeploymentTemplate).filter_by(
            name="wordpress-stack"
        ).first()

        assert template is not None
        assert "Template created from deployment 'my-wordpress-stack'" in template.description

    def test_save_deployment_as_template_validates_deployment_state(self, test_db, test_host):
        """
        Optional: Endpoint may validate deployment is in terminal state before saving.

        This test documents expected behavior if validation is implemented.
        If validation is NOT implemented, this test should be skipped/removed.

        THIS TEST WILL FAIL - endpoint doesn't exist yet (RED phase)
        """
        pytest.skip("Optional feature - only enable if deployment state validation is required")

        # Arrange: Create in-progress deployment
        deployment = Deployment(
            id=f"{test_host.id}:deploying",
            host_id=test_host.id,
            deployment_type="container",
            name="in-progress-deployment",
            status="executing",  # Not terminal!
            definition=json.dumps({"image": "nginx:alpine"}),
            progress_percent=50,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: Try to save in-progress deployment
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        response = client.post(
            f"/api/deployments/{deployment.id}/save-as-template",
            json={
                "name": "in-progress-template"
            }
        )

        # Assert: 400 Bad Request (if validation implemented)
        assert response.status_code == 400
        assert "Cannot save template" in response.json()["detail"]
        assert "executing" in response.json()["detail"]

    def test_save_deployment_as_template_generates_unique_id(self, test_db, test_host):
        """
        Each template must have a unique ID (not just relying on name uniqueness).

        THIS TEST WILL FAIL - endpoint doesn't exist yet (RED phase)
        """
        # Arrange: Create deployment
        deployment = Deployment(
            id=f"{test_host.id}:deploy_unique",
            host_id=test_host.id,
            deployment_type="container",
            name="unique-deployment",
            status="running",
            definition=json.dumps({"image": "redis:alpine"}),
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment)
        test_db.commit()

        # Act: Save as template
        from main import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        response = client.post(
            f"/api/deployments/{deployment.id}/save-as-template",
            json={"name": "redis-cache"}
        )

        # Assert: Template has unique ID
        assert response.status_code == 200
        result = response.json()
        assert "id" in result
        assert result["id"] is not None
        assert len(result["id"]) > 0

        # Verify ID in database
        template = test_db.query(DeploymentTemplate).filter_by(
            name="redis-cache"
        ).first()
        assert template.id == result["id"]
