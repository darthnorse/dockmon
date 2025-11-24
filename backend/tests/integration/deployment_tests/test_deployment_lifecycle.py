"""
Integration tests for deployment lifecycle.

Tests verify:
- Deployment creation and validation
- Deployment state transitions
- Deployment-container relationships
- Template-based deployments
- Rollback scenarios
- Database consistency during deployments
"""

import pytest
from datetime import datetime, timezone
import uuid

from database import Deployment, DeploymentContainer, DeploymentTemplate, DeploymentMetadata
from tests.conftest import create_composite_key


# =============================================================================
# Deployment Creation Tests
# =============================================================================

@pytest.mark.integration
class TestDeploymentCreation:
    """Test deployment creation and database persistence"""

    def test_create_container_deployment(
        self,
        db_session,
        test_host
    ):
        """Test creating a single container deployment"""
        # Arrange
        deployment_short_id = "deploy123456"
        deployment_id = create_composite_key(test_host.id, deployment_short_id)

        # Act: Create deployment
        deployment = Deployment(
            id=deployment_id,
            host_id=test_host.id,
            user_id=1,
            deployment_type='container',
            name='nginx-deployment',
            status='planning',
            definition='{"image": "nginx:latest", "ports": {"80/tcp": 8080}}',
            progress_percent=0,
            committed=False,
            rollback_on_failure=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment)
        db_session.commit()

        # Assert: Deployment persisted
        retrieved = db_session.query(Deployment).filter_by(
            id=deployment_id
        ).first()

        assert retrieved is not None
        assert retrieved.deployment_type == 'container'
        assert retrieved.name == 'nginx-deployment'
        assert retrieved.status == 'planning'
        assert retrieved.committed is False


    def test_create_stack_deployment(
        self,
        db_session,
        test_host
    ):
        """Test creating a stack deployment"""
        # Arrange
        deployment_short_id = "stack123456"
        deployment_id = create_composite_key(test_host.id, deployment_short_id)

        # Act: Create stack deployment
        deployment = Deployment(
            id=deployment_id,
            host_id=test_host.id,
            user_id=1,
            deployment_type='stack',
            name='wordpress-stack',
            status='planning',
            definition='{"services": {"web": {"image": "wordpress"}, "db": {"image": "mysql"}}}',
            committed=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment)
        db_session.commit()

        # Assert: Stack deployment created
        retrieved = db_session.query(Deployment).filter_by(
            id=deployment_id
        ).first()

        assert retrieved is not None
        assert retrieved.deployment_type == 'stack'
        assert retrieved.name == 'wordpress-stack'


    def test_deployment_unique_name_per_host(
        self,
        db_session,
        test_host
    ):
        """Test that deployment names must be unique per host"""
        # Arrange: Create first deployment
        deployment1 = Deployment(
            id=create_composite_key(test_host.id, "deploy1"),
            host_id=test_host.id,
            user_id=1,
            deployment_type='container',
            name='my-app',
            status='planning',
            definition='{"image": "nginx"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment1)
        db_session.commit()

        # Act: Try to create second deployment with same name on same host
        deployment2 = Deployment(
            id=create_composite_key(test_host.id, "deploy2"),
            host_id=test_host.id,
            user_id=1,
            deployment_type='container',
            name='my-app',  # Same name!
            status='planning',
            definition='{"image": "redis"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment2)

        # Assert: Should raise IntegrityError
        with pytest.raises(Exception):  # UniqueConstraint violation
            db_session.commit()


# =============================================================================
# Deployment State Transition Tests
# =============================================================================

@pytest.mark.integration
class TestDeploymentStateTransitions:
    """Test deployment state transitions persist in database"""

    def test_deployment_state_progression(
        self,
        db_session,
        test_host
    ):
        """Test complete deployment state progression persists"""
        # Arrange: Create deployment
        deployment_id = create_composite_key(test_host.id, "deploy123")
        deployment = Deployment(
            id=deployment_id,
            host_id=test_host.id,
            user_id=1,
            deployment_type='container',
            name='test-deployment',
            status='planning',
            definition='{"image": "nginx"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment)
        db_session.commit()

        # Act: Progress through states
        deployment.status = 'validating'
        deployment.started_at = datetime.now(timezone.utc)
        db_session.commit()

        deployment.status = 'pulling_image'
        db_session.commit()

        deployment.status = 'creating'
        db_session.commit()

        deployment.status = 'starting'
        db_session.commit()

        deployment.status = 'running'
        deployment.completed_at = datetime.now(timezone.utc)
        db_session.commit()

        # Assert: Final state persisted
        db_session.refresh(deployment)
        assert deployment.status == 'running'
        assert deployment.started_at is not None
        assert deployment.completed_at is not None


    def test_deployment_failure_state_persists(
        self,
        db_session,
        test_host
    ):
        """Test deployment failure state and error message persist"""
        # Arrange
        deployment_id = create_composite_key(test_host.id, "deploy123")
        deployment = Deployment(
            id=deployment_id,
            host_id=test_host.id,
            user_id=1,
            deployment_type='container',
            name='failed-deployment',
            status='pulling_image',
            definition='{"image": "nginx"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment)
        db_session.commit()

        # Act: Mark as failed with error
        deployment.status = 'failed'
        deployment.error_message = "Failed to pull image: connection timeout"
        deployment.completed_at = datetime.now(timezone.utc)
        db_session.commit()

        # Assert: Failure state and message persisted
        db_session.refresh(deployment)
        assert deployment.status == 'failed'
        assert deployment.error_message == "Failed to pull image: connection timeout"
        assert deployment.completed_at is not None


# =============================================================================
# Deployment-Container Relationship Tests
# =============================================================================

@pytest.mark.integration
class TestDeploymentContainerRelationship:
    """Test deployment-container junction table"""

    def test_single_container_deployment_link(
        self,
        db_session,
        test_host
    ):
        """Test linking single container to deployment"""
        # Arrange: Create deployment
        deployment_id = create_composite_key(test_host.id, "deploy123")
        deployment = Deployment(
            id=deployment_id,
            host_id=test_host.id,
            user_id=1,
            deployment_type='container',
            name='nginx-deployment',
            status='running',
            definition='{"image": "nginx"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment)
        db_session.flush()

        # Act: Link container to deployment
        container_id = "abc123def456"  # Short ID
        dc_link = DeploymentContainer(
            deployment_id=deployment_id,
            container_id=container_id,
            service_name=None,  # NULL for single containers
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(dc_link)
        db_session.commit()

        # Assert: Link persisted
        links = db_session.query(DeploymentContainer).filter_by(
            deployment_id=deployment_id
        ).all()

        assert len(links) == 1
        assert links[0].container_id == container_id
        assert links[0].service_name is None


    def test_stack_deployment_multiple_containers(
        self,
        db_session,
        test_host
    ):
        """Test linking multiple containers to stack deployment"""
        # Arrange: Create stack deployment
        deployment_id = create_composite_key(test_host.id, "stack123")
        deployment = Deployment(
            id=deployment_id,
            host_id=test_host.id,
            user_id=1,
            deployment_type='stack',
            name='wordpress-stack',
            status='running',
            definition='{"services": {"web": {}, "db": {}}}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment)
        db_session.flush()

        # Act: Link multiple containers (web, db)
        web_container = DeploymentContainer(
            deployment_id=deployment_id,
            container_id="web123456789",
            service_name="web",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(web_container)

        db_container = DeploymentContainer(
            deployment_id=deployment_id,
            container_id="db987654321",
            service_name="db",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(db_container)
        db_session.commit()

        # Assert: Both containers linked
        links = db_session.query(DeploymentContainer).filter_by(
            deployment_id=deployment_id
        ).all()

        assert len(links) == 2
        service_names = {link.service_name for link in links}
        assert service_names == {"web", "db"}


    def test_deployment_deletion_cascades_to_containers(
        self,
        db_session,
        test_host
    ):
        """Test that deleting deployment cascades to DeploymentContainer links"""
        # Arrange: Create deployment with container link
        deployment_id = create_composite_key(test_host.id, "deploy123")
        deployment = Deployment(
            id=deployment_id,
            host_id=test_host.id,
            user_id=1,
            deployment_type='container',
            name='test-deployment',
            status='running',
            definition='{"image": "nginx"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment)
        db_session.flush()

        dc_link = DeploymentContainer(
            deployment_id=deployment_id,
            container_id="abc123",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(dc_link)
        db_session.commit()

        # Act: Delete deployment
        db_session.delete(deployment)
        db_session.commit()

        # Assert: DeploymentContainer link also deleted
        links = db_session.query(DeploymentContainer).filter_by(
            deployment_id=deployment_id
        ).all()

        assert len(links) == 0


# =============================================================================
# Deployment Template Tests
# =============================================================================

@pytest.mark.integration
class TestDeploymentTemplates:
    """Test deployment template CRUD and usage"""

    def test_create_deployment_template(
        self,
        db_session
    ):
        """Test creating a deployment template"""
        # Act: Create template
        template = DeploymentTemplate(
            id=str(uuid.uuid4()),
            name='nginx-template',
            category='web',
            description='Basic Nginx web server',
            deployment_type='container',
            template_definition='{"image": "nginx:latest", "ports": {"80/tcp": "${PORT}"}}',
            variables='{"PORT": {"default": 8080, "type": "integer"}}',
            is_builtin=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(template)
        db_session.commit()

        # Assert: Template persisted
        retrieved = db_session.query(DeploymentTemplate).filter_by(
            name='nginx-template'
        ).first()

        assert retrieved is not None
        assert retrieved.category == 'web'
        assert retrieved.deployment_type == 'container'
        assert '${PORT}' in retrieved.template_definition


    def test_template_unique_name_constraint(
        self,
        db_session
    ):
        """Test that template names must be unique"""
        # Arrange: Create first template
        template1 = DeploymentTemplate(
            id=str(uuid.uuid4()),
            name='unique-template',
            deployment_type='container',
            template_definition='{"image": "nginx"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(template1)
        db_session.commit()

        # Act: Try to create second template with same name
        template2 = DeploymentTemplate(
            id=str(uuid.uuid4()),
            name='unique-template',  # Same name!
            deployment_type='container',
            template_definition='{"image": "redis"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(template2)

        # Assert: Should raise IntegrityError
        with pytest.raises(Exception):  # UniqueConstraint violation
            db_session.commit()


    def test_builtin_vs_user_templates(
        self,
        db_session
    ):
        """Test distinguishing between builtin and user-created templates"""
        # Arrange: Create builtin template
        builtin = DeploymentTemplate(
            id=str(uuid.uuid4()),
            name='builtin-nginx',
            deployment_type='container',
            template_definition='{"image": "nginx"}',
            is_builtin=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(builtin)

        # Create user template
        user = DeploymentTemplate(
            id=str(uuid.uuid4()),
            name='user-custom',
            deployment_type='container',
            template_definition='{"image": "custom"}',
            is_builtin=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(user)
        db_session.commit()

        # Assert: Can filter by builtin flag
        builtin_templates = db_session.query(DeploymentTemplate).filter_by(
            is_builtin=True
        ).all()
        assert len(builtin_templates) == 1
        assert builtin_templates[0].name == 'builtin-nginx'

        user_templates = db_session.query(DeploymentTemplate).filter_by(
            is_builtin=False
        ).all()
        assert len(user_templates) == 1
        assert user_templates[0].name == 'user-custom'


# =============================================================================
# Deployment Metadata Tests
# =============================================================================

@pytest.mark.integration
class TestDeploymentMetadata:
    """Test deployment metadata for container tagging"""

    def test_create_deployment_metadata(
        self,
        db_session,
        test_host
    ):
        """Test creating deployment metadata for container"""
        # Arrange
        container_id = "abc123def456"
        composite_key = create_composite_key(test_host.id, container_id)
        deployment_id = "deploy-123"

        # Act: Create metadata
        metadata = DeploymentMetadata(
            container_id=composite_key,
            host_id=test_host.id,
            deployment_id=deployment_id,
            is_managed=True,
            service_name="web",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(metadata)
        db_session.commit()

        # Assert: Metadata persisted
        retrieved = db_session.query(DeploymentMetadata).filter_by(
            container_id=composite_key
        ).first()

        assert retrieved is not None
        assert retrieved.deployment_id == deployment_id
        assert retrieved.is_managed is True
        assert retrieved.service_name == "web"


    def test_deployment_metadata_identifies_managed_containers(
        self,
        db_session,
        test_host
    ):
        """Test metadata distinguishes managed vs unmanaged containers"""
        # Arrange: Create two containers
        managed_container = create_composite_key(test_host.id, "managed123")
        unmanaged_container = create_composite_key(test_host.id, "unmanaged456")

        # Mark first as managed
        managed_meta = DeploymentMetadata(
            container_id=managed_container,
            host_id=test_host.id,
            deployment_id="deploy-1",
            is_managed=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(managed_meta)
        db_session.commit()

        # Act: Query managed containers
        managed = db_session.query(DeploymentMetadata).filter_by(
            is_managed=True
        ).all()

        # Assert: Only managed container returned
        assert len(managed) == 1
        assert managed[0].container_id == managed_container


# =============================================================================
# Commitment Point Tests
# =============================================================================

@pytest.mark.integration
class TestDeploymentCommitmentPoint:
    """Test commitment point tracking in database"""

    def test_committed_flag_persists(
        self,
        db_session,
        test_host
    ):
        """Test that committed flag persists in database"""
        # Arrange: Create deployment
        deployment_id = create_composite_key(test_host.id, "deploy123")
        deployment = Deployment(
            id=deployment_id,
            host_id=test_host.id,
            user_id=1,
            deployment_type='container',
            name='test-deployment',
            status='creating',
            definition='{"image": "nginx"}',
            committed=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment)
        db_session.commit()

        # Act: Mark as committed
        deployment.committed = True
        db_session.commit()

        # Assert: Committed flag persisted
        db_session.refresh(deployment)
        assert deployment.committed is True


    def test_rollback_on_failure_flag_persists(
        self,
        db_session,
        test_host
    ):
        """Test that rollback_on_failure setting persists"""
        # Arrange: Create deployment with rollback disabled
        deployment_id = create_composite_key(test_host.id, "deploy123")
        deployment = Deployment(
            id=deployment_id,
            host_id=test_host.id,
            user_id=1,
            deployment_type='container',
            name='no-rollback-deployment',
            status='planning',
            definition='{"image": "nginx"}',
            rollback_on_failure=False,  # User disabled rollback
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(deployment)
        db_session.commit()

        # Assert: Setting persisted
        db_session.refresh(deployment)
        assert deployment.rollback_on_failure is False
