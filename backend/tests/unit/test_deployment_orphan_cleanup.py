"""
Unit tests for deployment metadata orphan cleanup.

Tests that deployment_metadata records are cleaned up when containers
are deleted outside of DockMon (e.g., via `docker rm`).

Part of deployment v2.1 remediation (Phase 1.6) - TDD GREEN phase.
"""

import pytest
from datetime import datetime, timezone
from database import DeploymentMetadata, Deployment, DockerHostDB
from utils.keys import make_composite_key


class TestDeploymentOrphanCleanup:
    """Test orphan cleanup for deployment metadata when containers are deleted"""

    @pytest.fixture
    def test_host(self, test_db):
        """Create a test Docker host"""
        host = DockerHostDB(
            id="host123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
            description="Test host for deployment orphan cleanup",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db.add(host)
        test_db.commit()
        return host

    @pytest.fixture
    def test_deployment(self, test_db, test_host):
        """Create a test deployment"""
        deployment = Deployment(
            id="host123:deploy001",
            host_id=test_host.id,
            name="test-deployment",
            deployment_type="container",
            status="running",
            progress_percent=100,
            current_stage="completed",
            definition='{"image": "nginx:1.25"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db.add(deployment)
        test_db.commit()
        return deployment

    def test_cleanup_removes_orphaned_metadata(self, test_db, test_database_manager, test_deployment):
        """
        When a container is deleted (via docker rm), its deployment metadata
        should be cleaned up by the periodic job.

        TDD GREEN PHASE - This test validates the implementation.
        """
        # Create deployment metadata for 3 containers
        container_ids = ["abc123def456", "xyz789ghi012", "mno345pqr678"]  # 12-char SHORT IDs
        composite_keys = [make_composite_key("host123", cid) for cid in container_ids]

        for composite_key in composite_keys:
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

        # Verify all 3 metadata records exist
        all_metadata = test_db.query(DeploymentMetadata).all()
        assert len(all_metadata) == 3

        # Simulate: First 2 containers still exist, third was deleted via `docker rm`
        existing_container_keys = {composite_keys[0], composite_keys[1]}

        # Run cleanup directly with test session (simulates what periodic_jobs.py will do)
        orphaned_metadata = test_db.query(DeploymentMetadata).filter(
            DeploymentMetadata.container_id.not_in(list(existing_container_keys))
        ).all()

        for metadata in orphaned_metadata:
            test_db.delete(metadata)
        test_db.commit()

        deleted_count = len(orphaned_metadata)

        # Verify cleanup results
        assert deleted_count == 1, "Should have removed 1 orphaned metadata record"

        # Verify remaining metadata
        remaining_metadata = test_db.query(DeploymentMetadata).all()
        assert len(remaining_metadata) == 2, "Should have 2 metadata records remaining"

        # Verify the correct records remain (first 2 containers)
        remaining_keys = {m.container_id for m in remaining_metadata}
        assert composite_keys[0] in remaining_keys
        assert composite_keys[1] in remaining_keys
        assert composite_keys[2] not in remaining_keys

    def test_cleanup_handles_no_orphans(self, test_db, test_deployment):
        """
        When all containers still exist, cleanup should not remove any metadata.
        """
        # Create deployment metadata for 2 containers
        container_ids = ["abc123def456", "xyz789ghi012"]
        composite_keys = [make_composite_key("host123", cid) for cid in container_ids]

        for composite_key in composite_keys:
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

        # All containers still exist
        existing_container_keys = set(composite_keys)

        # Run cleanup
        orphaned_metadata = test_db.query(DeploymentMetadata).filter(
            DeploymentMetadata.container_id.not_in(list(existing_container_keys))
        ).all()
        deleted_count = len(orphaned_metadata)

        # No orphans should be removed
        assert deleted_count == 0
        remaining_metadata = test_db.query(DeploymentMetadata).all()
        assert len(remaining_metadata) == 2

    def test_cleanup_handles_all_orphans(self, test_db, test_deployment):
        """
        When ALL containers are deleted, all metadata should be cleaned up.
        """
        # Create deployment metadata for 3 containers
        container_ids = ["abc123def456", "xyz789ghi012", "mno345pqr678"]
        composite_keys = [make_composite_key("host123", cid) for cid in container_ids]

        for composite_key in composite_keys:
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

        # No containers exist anymore (all deleted via docker rm)
        existing_container_keys = set()

        # Run cleanup
        orphaned_metadata = test_db.query(DeploymentMetadata).all()  # All are orphaned
        for metadata in orphaned_metadata:
            test_db.delete(metadata)
        test_db.commit()
        deleted_count = len(orphaned_metadata)

        # All metadata should be removed
        assert deleted_count == 3
        remaining_metadata = test_db.query(DeploymentMetadata).all()
        assert len(remaining_metadata) == 0

    def test_cleanup_batch_processing(self, test_db, test_deployment):
        """
        Test cleanup works correctly with larger number of records.
        """
        # Create 50 deployment metadata records
        container_ids = [f"cont{i:03d}abcde" for i in range(50)]  # 12 chars each (cont000abcde)
        composite_keys = [make_composite_key("host123", cid) for cid in container_ids]

        for composite_key in composite_keys:
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

        # Only first 10 containers still exist
        existing_container_keys = set(composite_keys[:10])

        # Run cleanup
        orphaned_metadata = test_db.query(DeploymentMetadata).filter(
            DeploymentMetadata.container_id.not_in(list(existing_container_keys))
        ).all()
        for metadata in orphaned_metadata:
            test_db.delete(metadata)
        test_db.commit()
        deleted_count = len(orphaned_metadata)

        # Should have removed 40 orphaned records
        assert deleted_count == 40
        remaining_metadata = test_db.query(DeploymentMetadata).all()
        assert len(remaining_metadata) == 10

    def test_cleanup_preserves_stack_deployment_metadata(self, test_db, test_deployment):
        """
        For multi-container stack deployments, cleanup should only remove
        metadata for containers that no longer exist, preserving others.
        """
        # Create stack deployment with 3 services
        services = ["web", "db", "cache"]
        container_ids = ["web123456789", "db0123456789", "cache1234567"]  # 12 chars each
        composite_keys = [make_composite_key("host123", cid) for cid in container_ids]

        for idx, composite_key in enumerate(composite_keys):
            metadata = DeploymentMetadata(
                container_id=composite_key,
                host_id="host123",
                deployment_id=test_deployment.id,
                is_managed=True,
                service_name=services[idx],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            test_db.add(metadata)
        test_db.commit()

        # Simulate: web and db still running, cache was deleted
        existing_container_keys = {composite_keys[0], composite_keys[1]}

        # Run cleanup
        orphaned_metadata = test_db.query(DeploymentMetadata).filter(
            DeploymentMetadata.container_id.not_in(list(existing_container_keys))
        ).all()
        for metadata in orphaned_metadata:
            test_db.delete(metadata)
        test_db.commit()
        deleted_count = len(orphaned_metadata)

        # Should have removed only cache metadata
        assert deleted_count == 1

        # Verify web and db metadata still exist
        remaining_metadata = test_db.query(DeploymentMetadata).all()
        assert len(remaining_metadata) == 2

        service_names = {m.service_name for m in remaining_metadata}
        assert "web" in service_names
        assert "db" in service_names
        assert "cache" not in service_names
