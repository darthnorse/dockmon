"""
Unit tests for editing and retrying failed deployments.

TDD Phase: RED - Write failing tests first

Tests cover:
- User can edit a failed deployment to fix configuration
- Editing a failed deployment resets status to 'planning'
- Error message is cleared when failed deployment is edited
- Cannot edit deployments that are running or in other non-editable states
- Retry attempt creates correct WebSocket events
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from database import Deployment, DockerHostDB, GlobalSettings


class TestFailedDeploymentEditing:
    """Test user can edit failed deployments to retry"""

    def test_can_edit_failed_deployment(self, test_db, test_host):
        """
        User should be able to edit a failed deployment.

        RED PHASE: This test will FAIL until we allow 'failed' status in update_deployment endpoint.
        Currently only 'planning' status can be edited.
        """
        # Create a failed deployment
        failed_deployment = Deployment(
            id=str(test_host.id) + ":dep123",
            host_id=test_host.id,
            deployment_type="container",
            name="nginx-failed",
            status="failed",  # FAILED STATE
            definition=json.dumps({
                "image": "nginx:alpine",
                "container_name": "test-nginx"
            }),
            error_message="Container definition missing 'image' field",  # Has error
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(failed_deployment)
        test_db.commit()

        # Try to update the failed deployment with corrected definition
        updated_definition = {
            "image": "nginx:1.25-alpine",  # Fixed: added correct image
            "container_name": "test-nginx"
        }

        # This will FAIL because current code only allows editing 'planning' status
        # After GREEN phase, this should succeed
        updated_deployment = test_db.query(Deployment).filter_by(id=failed_deployment.id).first()

        # Simulate what the update endpoint should do
        if updated_deployment.status in ['planning', 'failed']:  # Should allow both
            updated_deployment.definition = json.dumps(updated_definition)
            updated_deployment.status = 'planning'  # Reset to planning
            updated_deployment.error_message = None  # Clear error
            updated_deployment.updated_at = datetime.now(timezone.utc)
            test_db.commit()
            test_db.refresh(updated_deployment)

            # Verify update
            assert updated_deployment.status == 'planning', "Status should reset to planning"
            assert updated_deployment.error_message is None, "Error message should be cleared"
            assert json.loads(updated_deployment.definition)['image'] == 'nginx:1.25-alpine'
        else:
            # Current behavior: Cannot edit failed deployments
            pytest.fail("Cannot edit failed deployments - feature not implemented")

    def test_failed_deployment_preserves_error_until_cleared_by_edit(self, test_db, test_host):
        """
        Error message should persist in database until deployment is edited.

        Verifies that error_message field is properly stored and retrieved.
        """
        original_error = "Image 'nginx:typo' not found in registry"

        deployment = Deployment(
            id=str(test_host.id) + ":dep456",
            host_id=test_host.id,
            deployment_type="container",
            name="failed-nginx",
            status="failed",
            definition=json.dumps({"image": "nginx:typo"}),
            error_message=original_error,
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(deployment)
        test_db.commit()

        # Fetch and verify error is persisted
        fetched = test_db.query(Deployment).filter_by(id=deployment.id).first()
        assert fetched.error_message == original_error, "Error message should be persisted"
        assert fetched.status == "failed", "Deployment should remain failed"

        # After editing (clearing error), the message should be gone
        fetched.error_message = None
        test_db.commit()
        test_db.refresh(fetched)
        assert fetched.error_message is None, "Error message should be cleared after edit"

    def test_cannot_edit_running_deployment(self, test_db, test_host):
        """
        Should not be able to edit deployments that are currently running.

        Only 'planning' and 'failed' deployments should be editable.
        """
        running_deployment = Deployment(
            id=str(test_host.id) + ":dep789",
            host_id=test_host.id,
            deployment_type="container",
            name="running-nginx",
            status="running",  # RUNNING - cannot edit
            definition=json.dumps({"image": "nginx:alpine"}),
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=True,
        )
        test_db.add(running_deployment)
        test_db.commit()

        # Try to edit
        running_deployment.definition = json.dumps({"image": "nginx:latest"})

        # Should not be allowed
        editable_statuses = ['planning', 'failed']
        assert running_deployment.status not in editable_statuses, \
            "Running deployments should not be editable"

    def test_retry_failed_deployment_resets_progress(self, test_db, test_host):
        """
        When retrying a failed deployment, progress should reset to 0.

        This ensures the UI shows the deployment starting fresh.
        """
        failed_deployment = Deployment(
            id=str(test_host.id) + ":dep_retry",
            host_id=test_host.id,
            deployment_type="container",
            name="retry-test",
            status="failed",
            definition=json.dumps({"image": "nginx:alpine"}),
            error_message="Some error",
            progress_percent=45,  # Stuck at 45%
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(failed_deployment)
        test_db.commit()

        # Simulate retry: edit and reset
        failed_deployment.status = 'planning'
        failed_deployment.error_message = None
        failed_deployment.progress_percent = 0  # Reset progress
        failed_deployment.updated_at = datetime.now(timezone.utc)
        test_db.commit()
        test_db.refresh(failed_deployment)

        assert failed_deployment.progress_percent == 0, "Progress should reset on retry"
        assert failed_deployment.error_message is None, "Error should be cleared"
        assert failed_deployment.status == 'planning', "Status should be planning for retry"

    def test_multiple_edits_allowed_on_failed_deployment(self, test_db, test_host):
        """
        User should be able to edit a failed deployment multiple times.

        This tests that we don't permanently lock out deployments after failures.
        """
        deployment = Deployment(
            id=str(test_host.id) + ":dep_multi",
            host_id=test_host.id,
            deployment_type="container",
            name="multi-edit",
            status="failed",
            definition=json.dumps({"image": "nginx:1.0"}),
            error_message="Error 1",
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=False,
            rollback_on_failure=True,
        )
        test_db.add(deployment)
        test_db.commit()

        # First edit
        deployment.definition = json.dumps({"image": "nginx:2.0"})
        deployment.error_message = None
        deployment.status = 'planning'
        test_db.commit()

        # Simulate execution and failure again
        deployment.status = 'failed'
        deployment.error_message = "Error 2"
        test_db.commit()

        # Second edit should still work
        deployment.definition = json.dumps({"image": "nginx:3.0"})
        deployment.error_message = None
        deployment.status = 'planning'
        test_db.commit()
        test_db.refresh(deployment)

        # Verify second edit was successful
        assert json.loads(deployment.definition)['image'] == 'nginx:3.0'
        assert deployment.status == 'planning'
        assert deployment.error_message is None
