"""
Integration tests for Docker Compose stack deployment.

These tests actually execute stack deployments against a real Docker daemon
to verify the end-to-end functionality works correctly.
"""

import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from database import Deployment
from deployment import DeploymentExecutor
from deployment.compose_parser import ComposeParser
from deployment.compose_validator import ComposeValidator
from deployment.stack_orchestrator import StackOrchestrator
import docker


@pytest.fixture
def docker_client():
    """Get Docker client for cleanup."""
    return docker.from_env()


@pytest.fixture
def mock_event_bus():
    """Mock EventBus for integration tests."""
    bus = MagicMock()
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def mock_docker_monitor():
    """Mock DockerMonitor for integration tests."""
    monitor = MagicMock()
    monitor.manager = MagicMock()
    monitor.manager.broadcast = AsyncMock()
    return monitor


@pytest.fixture
def deployment_executor(mock_event_bus, mock_docker_monitor, test_database_manager):
    """Create deployment executor with test database."""
    return DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_database_manager)


@pytest.fixture(autouse=True)
def cleanup_test_containers(docker_client):
    """Clean up any test containers before and after each test."""
    def cleanup():
        try:
            # Remove test stack containers
            for container in docker_client.containers.list(all=True):
                if container.name.startswith('test-stack_'):
                    container.stop(timeout=1)
                    container.remove(force=True)

            # Remove test networks
            for network in docker_client.networks.list():
                if network.name.startswith('test-stack_'):
                    network.remove()

            # Remove test volumes
            for volume in docker_client.volumes.list():
                if volume.name.startswith('test-stack_'):
                    volume.remove(force=True)
        except Exception as e:
            print(f"Cleanup warning: {e}")

    cleanup()  # Before test
    yield
    cleanup()  # After test


class TestStackDeploymentIntegration:
    """Integration tests for full stack deployment workflow."""

    @pytest.mark.asyncio
    async def test_deploy_simple_two_service_stack(self, deployment_executor, test_database_manager, test_host, docker_client):
        """
        Test deploying a simple 2-service stack (web + redis).
        Verifies:
        - Both services are created
        - Containers are started
        - Metadata is created
        - Deployment status is 'completed'
        """
        # Compose file without version (modern format)
        compose_yaml = """
services:
  web:
    image: nginx:alpine
    ports:
      - "19080:80"
    restart: unless-stopped

  redis:
    image: redis:alpine
    restart: unless-stopped
"""

        # Create deployment
        deployment_id = await deployment_executor.create_deployment(
            host_id=test_host.id,
            name='test-stack',
            deployment_type='stack',
            definition={'compose_yaml': compose_yaml},
            rollback_on_failure=True
        )

        # Execute deployment
        await deployment_executor.execute_deployment(deployment_id)

        # Wait for deployment to complete (max 30 seconds)
        for _ in range(30):
            with test_database_manager.get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment status
        with test_database_manager.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed', f"Deployment failed: {deployment.error_message}"
            assert deployment.progress_percent == 100
            assert deployment.committed is True

        # Verify containers were created
        containers = docker_client.containers.list(filters={'name': 'test-stack_'})
        assert len(containers) == 2, f"Expected 2 containers, found {len(containers)}"

        container_names = {c.name for c in containers}
        assert 'test-stack_web' in container_names
        assert 'test-stack_redis' in container_names

        # Verify containers are running
        for container in containers:
            assert container.status == 'running', f"Container {container.name} not running"

        # Verify labels
        web_container = docker_client.containers.get('test-stack_web')
        assert web_container.labels.get('com.docker.compose.project') == 'test-stack'
        assert web_container.labels.get('com.docker.compose.service') == 'web'
        assert web_container.labels.get('dockmon.managed') == 'true'


    @pytest.mark.asyncio
    async def test_deploy_stack_with_dependencies(self, deployment_executor, test_db, docker_client):
        """
        Test stack with dependencies (web depends on api depends on db).
        Verifies services are created in correct order.
        """
        compose_yaml = """
services:
  web:
    image: nginx:alpine
    depends_on:
      - api
    restart: unless-stopped

  api:
    image: redis:alpine
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: alpine:latest
    command: sleep 300
    restart: unless-stopped
"""

        deployment_id = await deployment_executor.create_deployment(
            host_id=test_host.id,
            name='test-stack',
            deployment_type='stack',
            definition={'compose_yaml': compose_yaml},
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(30):
            with test_database_manager.get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment completed
        with test_database_manager.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed'

        # Verify all 3 containers were created
        containers = docker_client.containers.list(filters={'name': 'test-stack_'})
        assert len(containers) == 3


    @pytest.mark.asyncio
    async def test_stack_deployment_rollback_on_failure(self, deployment_executor, test_db, docker_client):
        """
        Test that rollback works when stack deployment fails.
        Uses invalid image to trigger failure.
        """
        compose_yaml = """
services:
  web:
    image: nginx:alpine
    restart: unless-stopped

  fail:
    image: this-image-does-not-exist-12345
    restart: unless-stopped
"""

        deployment_id = await deployment_executor.create_deployment(
            host_id=test_host.id,
            name='test-stack',
            deployment_type='stack',
            definition={'compose_yaml': compose_yaml},
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for rollback
        for _ in range(30):
            with test_database_manager.get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment was rolled back
        with test_database_manager.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'rolled_back'
            assert 'not-exist' in deployment.error_message or 'not found' in deployment.error_message.lower()

        # Verify no containers remain (rollback cleaned up)
        containers = docker_client.containers.list(all=True, filters={'name': 'test-stack_'})
        assert len(containers) == 0, f"Rollback should have removed all containers, found {len(containers)}"


    @pytest.mark.asyncio
    async def test_stack_with_networks_and_volumes(self, deployment_executor, test_db, docker_client):
        """
        Test stack with custom networks and volumes.
        Verifies resources are created correctly.
        """
        compose_yaml = """
services:
  db:
    image: alpine:latest
    command: sleep 300
    volumes:
      - db_data:/data
    networks:
      - backend
    restart: unless-stopped

networks:
  backend:
    driver: bridge

volumes:
  db_data:
    driver: local
"""

        deployment_id = await deployment_executor.create_deployment(
            host_id=test_host.id,
            name='test-stack',
            deployment_type='stack',
            definition={'compose_yaml': compose_yaml},
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(30):
            with test_database_manager.get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment completed
        with test_database_manager.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed'

        # Verify network was created
        networks = docker_client.networks.list(names=['test-stack_backend'])
        assert len(networks) == 1

        # Verify volume was created
        volumes = docker_client.volumes.list(filters={'name': 'test-stack_db_data'})
        assert len(volumes) == 1

        # Verify container is connected to network
        container = docker_client.containers.get('test-stack_db')
        assert 'test-stack_backend' in container.attrs['NetworkSettings']['Networks']


    @pytest.mark.asyncio
    async def test_stack_deployment_without_version_field(self, deployment_executor, test_db, docker_client):
        """
        Test that compose files without 'version' field work (modern Compose spec).
        This is a regression test for Bug #2.
        """
        # Modern compose format - no version field
        compose_yaml = """
services:
  web:
    image: nginx:alpine
    restart: unless-stopped
"""

        deployment_id = await deployment_executor.create_deployment(
            host_id=test_host.id,
            name='test-stack',
            deployment_type='stack',
            definition={'compose_yaml': compose_yaml},
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(30):
            with test_database_manager.get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Should succeed without version field
        with test_database_manager.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed'

        # Verify container was created
        containers = docker_client.containers.list(filters={'name': 'test-stack_web'})
        assert len(containers) == 1


    @pytest.mark.asyncio
    async def test_cannot_reexecute_completed_deployment(self, deployment_executor, test_db):
        """
        Test that completed deployments cannot be re-executed.
        This is a regression test for Bug #1.
        """
        compose_yaml = """
services:
  web:
    image: nginx:alpine
"""

        # Create and execute deployment
        deployment_id = await deployment_executor.create_deployment(
            host_id=test_host.id,
            name='test-stack',
            deployment_type='stack',
            definition={'compose_yaml': compose_yaml},
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(30):
            with test_database_manager.get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Try to re-execute - should fail
        with pytest.raises(ValueError, match="Cannot start deployment.*in status"):
            await deployment_executor.execute_deployment(deployment_id)
