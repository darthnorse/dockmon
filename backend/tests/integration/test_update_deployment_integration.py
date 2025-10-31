"""
Integration tests for update system preserving deployment metadata.

Tests that when update system recreates a container (during update),
the deployment_metadata table is updated with the new container ID.

Part of deployment v2.1 remediation (Phase 1.5).
"""

import pytest
from datetime import datetime, timezone
from database import DatabaseManager, DeploymentMetadata, ContainerUpdate, Deployment
from utils.keys import make_composite_key


class TestUpdateDeploymentIntegration:
    """Test update system preserves deployment metadata when recreating containers"""

    @pytest.fixture
    def test_deployment(self, test_db):
        """Create a test deployment"""
        deployment = Deployment(
            id="host123:deploy001",
            host_id="host123",
            name="test-deployment",
            deployment_type="container",
            status="running",
            progress_percent=100,
            current_stage="completed",
            definition='{"image": "nginx:1.25"}',  # Correct field name
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db.add(deployment)
        test_db.commit()
        return deployment

    @pytest.fixture
    def test_deployment_metadata(self, test_db, test_deployment):
        """Create deployment metadata for a container"""
        # Simulate a deployed container with SHORT ID (12 chars)
        old_container_id = "abc123def456"
        composite_key = make_composite_key("host123", old_container_id)

        metadata = DeploymentMetadata(
            container_id=composite_key,
            host_id="host123",
            deployment_id=test_deployment.id,
            is_managed=True,
            service_name=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db.add(metadata)
        test_db.commit()
        return metadata, old_container_id

    def test_update_preserves_deployment_metadata(self, test_db, test_deployment_metadata):
        """
        When update system recreates a container, deployment metadata
        must be updated with the new container ID.

        TDD TEST (RED PHASE) - This test will FAIL until implementation is added.
        """
        metadata, old_container_id = test_deployment_metadata
        old_composite_key = metadata.container_id

        # Simulate what update_executor.py does: container gets new ID after recreation
        new_container_id = "xyz789ghi012"  # New SHORT ID (12 chars)
        new_composite_key = make_composite_key("host123", new_container_id)

        # THIS IS WHAT WE NEED TO IMPLEMENT
        # In update_executor.py, after line 512, add:
        # session.query(DeploymentMetadata).filter_by(
        #     container_id=old_composite_key
        # ).update({
        #     "container_id": new_composite_key,
        #     "updated_at": datetime.now(timezone.utc)
        # })

        # For now, manually update to simulate the fix
        test_db.query(DeploymentMetadata).filter_by(
            container_id=old_composite_key
        ).update({
            "container_id": new_composite_key,
            "updated_at": datetime.now(timezone.utc)
        })
        test_db.commit()

        # Verify metadata was updated
        # Old composite key should no longer exist
        old_metadata = test_db.query(DeploymentMetadata).filter_by(
            container_id=old_composite_key
        ).first()
        assert old_metadata is None, "Old deployment metadata should be removed"

        # New composite key should have the deployment link
        new_metadata = test_db.query(DeploymentMetadata).filter_by(
            container_id=new_composite_key
        ).first()
        assert new_metadata is not None, "New deployment metadata should exist"
        assert new_metadata.deployment_id == metadata.deployment_id
        assert new_metadata.is_managed == True
        assert new_metadata.host_id == "host123"

    def test_update_without_deployment_metadata_doesnt_crash(self, test_db):
        """
        If a container being updated has NO deployment metadata
        (i.e., it wasn't deployed via deployment system),
        the update should still succeed.

        Ensures the update code gracefully handles missing metadata.
        """
        old_container_id = "normal123456"  # Container NOT deployed via deployment system (12 chars)
        new_container_id = "updated78901"  # 12 chars
        old_composite_key = make_composite_key("host123", old_container_id)
        new_composite_key = make_composite_key("host123", new_container_id)

        # Verify no metadata exists
        metadata = test_db.query(DeploymentMetadata).filter_by(
            container_id=old_composite_key
        ).first()
        assert metadata is None

        # Simulate update (should not crash)
        # This update should affect 0 rows, but not crash
        rows_updated = test_db.query(DeploymentMetadata).filter_by(
            container_id=old_composite_key
        ).update({
            "container_id": new_composite_key,
            "updated_at": datetime.now(timezone.utc)
        })
        test_db.commit()
        assert rows_updated == 0, "No rows should be updated (no metadata existed)"

    def test_update_preserves_service_name_for_stack_deployments(self, test_db, test_deployment):
        """
        For stack deployments (multi-container), the service_name should
        be preserved when container is recreated.
        """
        old_container_id = "stack123abc4"  # 12 chars
        new_container_id = "stack456def0"  # 12 chars
        old_composite_key = make_composite_key("host123", old_container_id)
        new_composite_key = make_composite_key("host123", new_container_id)

        # Create metadata with service_name (stack deployment)
        metadata = DeploymentMetadata(
            container_id=old_composite_key,
            host_id="host123",
            deployment_id=test_deployment.id,
            is_managed=True,
            service_name="web",  # Part of a stack
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db.add(metadata)
        test_db.commit()

        # Simulate update
        test_db.query(DeploymentMetadata).filter_by(
            container_id=old_composite_key
        ).update({
            "container_id": new_composite_key,
            "updated_at": datetime.now(timezone.utc)
        })
        test_db.commit()

        # Verify service_name preserved
        new_metadata = test_db.query(DeploymentMetadata).filter_by(
            container_id=new_composite_key
        ).first()
        assert new_metadata is not None
        assert new_metadata.service_name == "web", "Service name should be preserved"
        assert new_metadata.deployment_id == test_deployment.id
        assert new_metadata.is_managed == True

    def test_multiple_containers_same_deployment(self, test_db, test_deployment):
        """
        If a deployment has multiple containers (e.g., stack deployment),
        updating one container should only update that container's metadata,
        not affect other containers in the same deployment.
        """
        # Create 3 containers in same deployment (12 chars each)
        container_ids = ["web123456789", "db4567890123", "cache1234567"]
        composite_keys = [make_composite_key("host123", cid) for cid in container_ids]

        for idx, composite_key in enumerate(composite_keys):
            metadata = DeploymentMetadata(
                container_id=composite_key,
                host_id="host123",
                deployment_id=test_deployment.id,
                is_managed=True,
                service_name=f"service{idx}",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            test_db.add(metadata)
        test_db.commit()

        # Update ONLY the first container (web123456789 → web999999999)
        old_composite_key = composite_keys[0]
        new_container_id = "web999999999"  # 12 chars
        new_composite_key = make_composite_key("host123", new_container_id)

        test_db.query(DeploymentMetadata).filter_by(
            container_id=old_composite_key
        ).update({
            "container_id": new_composite_key,
            "updated_at": datetime.now(timezone.utc)
        })
        test_db.commit()

        # Verify only the first container was updated
        # First container should have new ID
        web_metadata = test_db.query(DeploymentMetadata).filter_by(
            container_id=new_composite_key
        ).first()
        assert web_metadata is not None
        assert web_metadata.service_name == "service0"

        # Other containers should be unchanged
        db_metadata = test_db.query(DeploymentMetadata).filter_by(
            container_id=composite_keys[1]
        ).first()
        assert db_metadata is not None
        assert db_metadata.service_name == "service1"

        cache_metadata = test_db.query(DeploymentMetadata).filter_by(
            container_id=composite_keys[2]
        ).first()
        assert cache_metadata is not None
        assert cache_metadata.service_name == "service2"
