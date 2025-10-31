"""
Unit tests for deployment_metadata table and model.

TDD Phase: RED - Write tests first to ensure deployment metadata tracking works correctly.

Tests cover:
- DeploymentMetadata model creation
- Database schema validation (table exists, columns correct, foreign keys)
- CRUD operations (create, read, update, delete)
- Composite key uniqueness
- Cascade deletion when host or deployment deleted
- Batch retrieval for performance
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

from database import (
    DeploymentMetadata,
    Deployment,
    DockerHostDB,
)


class TestDeploymentMetadataModel:
    """Test DeploymentMetadata database model"""

    def test_create_deployment_metadata(self, test_db):
        """Test creating deployment metadata record"""
        # Arrange: Create test host
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376"
        )
        test_db.add(host)
        test_db.commit()

        # Arrange: Create test deployment
        deployment = Deployment(
            id="host-123:dep_abc123",
            host_id="host-123",
            deployment_type="container",
            name="test-deployment",
            display_name="Test Deployment",
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

        # Act: Create deployment metadata
        metadata = DeploymentMetadata(
            container_id="host-123:abc123def456",
            host_id="host-123",
            deployment_id="host-123:dep_abc123",
            is_managed=True,
            service_name=None,
        )
        test_db.add(metadata)
        test_db.commit()

        # Assert: Record created successfully
        retrieved = test_db.query(DeploymentMetadata).filter_by(
            container_id="host-123:abc123def456"
        ).first()

        assert retrieved is not None
        assert retrieved.container_id == "host-123:abc123def456"
        assert retrieved.host_id == "host-123"
        assert retrieved.deployment_id == "host-123:dep_abc123"
        assert retrieved.is_managed is True
        assert retrieved.service_name is None
        assert retrieved.created_at is not None
        assert retrieved.updated_at is not None

    def test_composite_key_uniqueness(self, test_db):
        """Test that container_id is unique (composite key: host_id:container_id)"""
        # Arrange: Create test host
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376"
        )
        test_db.add(host)
        test_db.commit()

        # Act: Create first metadata record
        metadata1 = DeploymentMetadata(
            container_id="host-123:abc123def456",
            host_id="host-123",
            deployment_id=None,
            is_managed=False,
        )
        test_db.add(metadata1)
        test_db.commit()

        # Act: Try to create duplicate with same container_id
        metadata2 = DeploymentMetadata(
            container_id="host-123:abc123def456",  # Same composite key
            host_id="host-123",
            deployment_id=None,
            is_managed=True,
        )
        test_db.add(metadata2)

        # Assert: Should raise IntegrityError (primary key violation)
        with pytest.raises(IntegrityError):
            test_db.commit()

    def test_update_deployment_metadata(self, test_db):
        """Test updating deployment metadata (e.g., linking container to deployment)"""
        # Arrange: Create host, deployment, and initial metadata
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
            deployment_id=None,  # Not linked initially
            is_managed=False,
        )
        test_db.add(metadata)
        test_db.commit()

        # Act: Update metadata to link to deployment
        metadata.deployment_id = "host-123:dep_abc123"
        metadata.is_managed = True
        test_db.commit()

        # Assert: Changes persisted
        retrieved = test_db.query(DeploymentMetadata).filter_by(
            container_id="host-123:abc123def456"
        ).first()

        assert retrieved.deployment_id == "host-123:dep_abc123"
        assert retrieved.is_managed is True

    def test_cascade_delete_when_host_deleted(self, test_db):
        """Test that deployment metadata is deleted when host is deleted (CASCADE)"""
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

        # Act: Delete host
        test_db.delete(host)
        test_db.commit()

        # Assert: Metadata should be deleted via CASCADE
        retrieved = test_db.query(DeploymentMetadata).filter_by(
            container_id="host-123:abc123def456"
        ).first()

        assert retrieved is None

    def test_set_null_when_deployment_deleted(self, test_db):
        """Test that deployment_id is set to NULL when deployment is deleted (SET NULL)"""
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
        )
        test_db.add(metadata)
        test_db.commit()

        # Act: Delete deployment
        test_db.delete(deployment)
        test_db.commit()

        # Assert: Metadata still exists but deployment_id is NULL
        retrieved = test_db.query(DeploymentMetadata).filter_by(
            container_id="host-123:abc123def456"
        ).first()

        assert retrieved is not None
        assert retrieved.deployment_id is None
        assert retrieved.is_managed is True  # Flag remains

    def test_batch_retrieval(self, test_db):
        """Test batch retrieval of all deployment metadata (performance optimization)"""
        # Arrange: Create host and multiple metadata records
        host = DockerHostDB(
            id="host-123",
            name="Test Host",
            url="tcp://192.168.1.100:2376",
        )
        test_db.add(host)

        metadata_records = [
            DeploymentMetadata(
                container_id=f"host-123:container{i}",
                host_id="host-123",
                deployment_id=None,
                is_managed=False,
            )
            for i in range(5)
        ]
        for metadata in metadata_records:
            test_db.add(metadata)
        test_db.commit()

        # Act: Batch retrieve all metadata
        all_metadata = test_db.query(DeploymentMetadata).all()

        # Assert: All records retrieved
        assert len(all_metadata) == 5
        container_ids = {m.container_id for m in all_metadata}
        assert "host-123:container0" in container_ids
        assert "host-123:container4" in container_ids

    def test_stack_deployment_with_service_name(self, test_db):
        """Test deployment metadata for stack deployments with service names"""
        # Arrange: Create host and deployment
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
            definition='{"services": {...}}',
            progress_percent=100,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            committed=True,
            rollback_on_failure=False,
        )
        test_db.add(deployment)

        # Act: Create metadata for stack service containers
        metadata_web = DeploymentMetadata(
            container_id="host-123:web_container",
            host_id="host-123",
            deployment_id="host-123:dep_stack001",
            is_managed=True,
            service_name="web",  # Stack service name
        )
        metadata_db = DeploymentMetadata(
            container_id="host-123:db_container",
            host_id="host-123",
            deployment_id="host-123:dep_stack001",
            is_managed=True,
            service_name="database",  # Stack service name
        )
        test_db.add(metadata_web)
        test_db.add(metadata_db)
        test_db.commit()

        # Assert: Both containers linked to same deployment with different service names
        stack_containers = test_db.query(DeploymentMetadata).filter_by(
            deployment_id="host-123:dep_stack001"
        ).all()

        assert len(stack_containers) == 2
        service_names = {m.service_name for m in stack_containers}
        assert "web" in service_names
        assert "database" in service_names


class TestDeploymentMetadataSchemaValidation:
    """Test that deployment_metadata table schema matches specification"""

    def test_table_exists(self, test_db):
        """Test that deployment_metadata table exists in database"""
        # Act: Get table names
        from sqlalchemy import inspect
        inspector = inspect(test_db.bind)
        table_names = inspector.get_table_names()

        # Assert: deployment_metadata table exists
        assert "deployment_metadata" in table_names

    def test_table_columns(self, test_db):
        """Test that deployment_metadata has all required columns"""
        # Act: Get column info
        from sqlalchemy import inspect
        inspector = inspect(test_db.bind)
        columns = {col['name']: col for col in inspector.get_columns('deployment_metadata')}

        # Assert: All required columns exist
        assert 'container_id' in columns
        assert 'host_id' in columns
        assert 'deployment_id' in columns
        assert 'is_managed' in columns
        assert 'service_name' in columns
        assert 'created_at' in columns
        assert 'updated_at' in columns

        # Assert: Primary key
        pk_columns = inspector.get_pk_constraint('deployment_metadata')
        assert 'container_id' in pk_columns['constrained_columns']

    def test_foreign_keys(self, test_db):
        """Test that foreign key relationships are configured correctly"""
        # Act: Get foreign key info
        from sqlalchemy import inspect
        inspector = inspect(test_db.bind)
        foreign_keys = inspector.get_foreign_keys('deployment_metadata')

        # Assert: Two foreign keys exist (host_id and deployment_id)
        assert len(foreign_keys) >= 1  # At minimum, host_id FK

        # Find host_id foreign key
        host_fk = next((fk for fk in foreign_keys if 'host_id' in fk['constrained_columns']), None)
        assert host_fk is not None
        assert host_fk['referred_table'] == 'docker_hosts'
        assert 'CASCADE' in str(host_fk.get('options', {})).upper() or host_fk.get('ondelete') == 'CASCADE'

        # Find deployment_id foreign key
        deployment_fk = next((fk for fk in foreign_keys if 'deployment_id' in fk['constrained_columns']), None)
        assert deployment_fk is not None
        assert deployment_fk['referred_table'] == 'deployments'
        assert 'SET NULL' in str(deployment_fk.get('options', {})).upper() or deployment_fk.get('ondelete') == 'SET NULL'
