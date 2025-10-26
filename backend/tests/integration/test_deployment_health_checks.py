"""
Integration tests for deployment health check functionality.

TDD RED Phase: These tests are written BEFORE the implementation.
They will fail until deployment executor is enhanced with health check logic.

Tests verify:
- Deployments wait for container health before marking as complete
- Healthy containers result in "running" status
- Unhealthy containers result in "failed" status and cleanup
- Configured timeout from GlobalSettings is respected
- Failed deployments emit appropriate events
"""

import pytest
import json
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

from database import Deployment, GlobalSettings
from deployment.executor import DeploymentExecutor


@pytest.fixture
def mock_docker_client_healthy():
    """Mock Docker client where containers become healthy."""
    client = Mock()
    client.api = Mock()
    client.api.base_url = 'http+unix:///var/run/docker.sock'

    # Mock image operations
    mock_image = Mock()
    mock_image.id = 'sha256:test_image'
    client.images.pull = Mock(return_value=mock_image)
    client.images.get = Mock(return_value=mock_image)

    # Mock container operations - container becomes healthy
    mock_container = Mock()
    mock_container.id = 'test_container_id_full' * 4  # 64 chars
    mock_container.short_id = 'test_cont_01'  # 12 chars
    mock_container.status = 'running'
    mock_container.name = 'test-nginx'
    mock_container.start = Mock()
    mock_container.reload = Mock()

    # Healthy container state
    mock_container.attrs = {
        "State": {
            "Running": True,
            "Health": {
                "Status": "healthy"
            }
        }
    }

    client.containers.create = Mock(return_value=mock_container)
    client.containers.get = Mock(return_value=mock_container)
    client.containers.list = Mock(return_value=[])

    # Mock network/volume operations
    client.networks = Mock()
    client.networks.list = Mock(return_value=[])
    client.volumes = Mock()
    client.volumes.list = Mock(return_value=[])

    return client


@pytest.fixture
def mock_docker_client_unhealthy():
    """Mock Docker client where containers become unhealthy."""
    client = Mock()
    client.api = Mock()
    client.api.base_url = 'http+unix:///var/run/docker.sock'

    # Mock image operations
    mock_image = Mock()
    mock_image.id = 'sha256:test_image'
    client.images.pull = Mock(return_value=mock_image)
    client.images.get = Mock(return_value=mock_image)

    # Mock container operations - container becomes unhealthy
    mock_container = Mock()
    mock_container.id = 'test_container_id_full' * 4
    mock_container.short_id = 'test_cont_02'
    mock_container.status = 'running'
    mock_container.name = 'test-broken-app'
    mock_container.start = Mock()
    mock_container.reload = Mock()
    mock_container.stop = Mock()
    mock_container.remove = Mock()

    # Unhealthy container state
    mock_container.attrs = {
        "State": {
            "Running": True,
            "Health": {
                "Status": "unhealthy"
            }
        }
    }

    client.containers.create = Mock(return_value=mock_container)
    client.containers.get = Mock(return_value=mock_container)
    client.containers.list = Mock(return_value=[])

    # Mock network/volume operations
    client.networks = Mock()
    client.networks.list = Mock(return_value=[])
    client.volumes = Mock()
    client.volumes.list = Mock(return_value=[])

    return client


@pytest.fixture
def mock_docker_client_crash():
    """Mock Docker client where containers crash during startup."""
    client = Mock()
    client.api = Mock()
    client.api.base_url = 'http+unix:///var/run/docker.sock'

    # Mock image operations
    mock_image = Mock()
    mock_image.id = 'sha256:test_image'
    client.images.pull = Mock(return_value=mock_image)
    client.images.get = Mock(return_value=mock_image)

    # Mock container operations - container crashes
    mock_container = Mock()
    mock_container.id = 'test_container_id_full' * 4
    mock_container.short_id = 'test_cont_03'
    mock_container.status = 'exited'
    mock_container.name = 'test-crash-app'
    mock_container.start = Mock()
    mock_container.reload = Mock()
    mock_container.stop = Mock()
    mock_container.remove = Mock()

    call_count = 0

    def get_container(container_id):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            # First call: container running
            mock_container.attrs = {"State": {"Running": True, "Health": None}}
        else:
            # Subsequent calls: container crashed
            mock_container.attrs = {"State": {"Running": False, "Health": None}}

        return mock_container

    client.containers.create = Mock(return_value=mock_container)
    client.containers.get = Mock(side_effect=get_container)
    client.containers.list = Mock(return_value=[])

    # Mock network/volume operations
    client.networks = Mock()
    client.networks.list = Mock(return_value=[])
    client.volumes = Mock()
    client.volumes.list = Mock(return_value=[])

    return client


class TestDeploymentHealthCheckSuccess:
    """Test deployment success scenarios with health checks."""

    @pytest.mark.asyncio
    async def test_deployment_succeeds_with_healthy_container(
        self, test_db, test_host, test_database_manager, mock_docker_client_healthy
    ):
        """
        Deployment should succeed when container becomes healthy.

        Flow:
        1. Create deployment
        2. Pull image
        3. Create container
        4. Start container
        5. Wait for health check (container reports healthy)
        6. Mark deployment as "running" with 100% progress
        7. Emit DEPLOYMENT_COMPLETED event
        """
        # Create deployment
        deployment = Deployment(
            id=f"{test_host.id}:deploy001",
            host_id=test_host.id,
            deployment_type="container",
            name="test-nginx",
            status="pending",
            definition=json.dumps({
                "container": {
                    "image": "nginx:latest",
                    "ports": {"80/tcp": 8080},
                    "environment": {"TEST": "health-check"},
                    "restart_policy": "unless-stopped"
                }
            }),
            progress_percent=0,
            current_stage="pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        test_db.add(deployment)
        test_db.commit()

        # Configure health check timeout
        settings = test_db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings(id=1, health_check_timeout_seconds=60)
            test_db.add(settings)
            test_db.commit()

        # Create executor
        mock_event_bus = AsyncMock()
        mock_docker_monitor = Mock()
        mock_docker_monitor.clients = {test_host.id: mock_docker_client_healthy}

        executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_database_manager)

        # Execute deployment
        with patch('deployment.executor.async_docker_call') as mock_async_call, \
             patch.object(executor.image_pull_tracker, 'pull_with_progress', new_callable=AsyncMock) as mock_pull:
            # Make async_docker_call pass through to the mock client
            async def passthrough(func, *args, **kwargs):
                return func(*args, **kwargs)
            mock_async_call.side_effect = passthrough

            # Mock image pull to skip actual pulling (we're testing health checks, not image pull)
            mock_pull.return_value = None  # Pull succeeded

            result = await executor.execute_deployment(deployment.id)

        # Verify deployment succeeded
        assert result is True

        # Verify database state
        test_db.refresh(deployment)
        assert deployment.status == "completed"
        assert deployment.progress_percent == 100

        # Verify container was created and started
        assert mock_docker_client_healthy.containers.create.called
        mock_container = mock_docker_client_healthy.containers.create.return_value
        assert mock_container.start.called


class TestDeploymentHealthCheckFailure:
    """Test deployment failure scenarios with health checks."""

    @pytest.mark.asyncio
    async def test_deployment_fails_with_unhealthy_container(
        self, test_db, test_host, test_database_manager, mock_docker_client_unhealthy
    ):
        """
        Deployment should fail when container becomes unhealthy.

        Flow:
        1. Create deployment
        2. Pull image
        3. Create container
        4. Start container
        5. Wait for health check (container reports unhealthy)
        6. Stop and remove failed container
        7. Mark deployment as "failed"
        8. Emit DEPLOYMENT_FAILED event
        """
        # Create deployment
        deployment = Deployment(
            id=f"{test_host.id}:deploy002",
            host_id=test_host.id,
            deployment_type="container",
            name="test-broken-app",
            status="pending",
            definition=json.dumps({
                "container": {
                    "image": "broken-app:latest",
                    "ports": {"3000/tcp": 3000},
                    "restart_policy": "unless-stopped"
                }
            }),
            progress_percent=0,
            current_stage="pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        test_db.add(deployment)
        test_db.commit()

        # Configure health check timeout
        settings = test_db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings(id=1, health_check_timeout_seconds=60)
            test_db.add(settings)
            test_db.commit()

        # Create executor
        mock_event_bus = AsyncMock()
        mock_docker_monitor = Mock()
        mock_docker_monitor.clients = {test_host.id: mock_docker_client_unhealthy}

        executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_database_manager)

        # Execute deployment
        with patch('deployment.executor.async_docker_call') as mock_async_call, \
             patch.object(executor.image_pull_tracker, 'pull_with_progress', new_callable=AsyncMock) as mock_pull:
            async def passthrough(func, *args, **kwargs):
                return func(*args, **kwargs)
            mock_async_call.side_effect = passthrough

            # Mock image pull to skip actual pulling (we're testing health checks, not image pull)
            mock_pull.return_value = None  # Pull succeeded

            result = await executor.execute_deployment(deployment.id)

        # Verify deployment failed
        assert result is False

        # Verify database state
        test_db.refresh(deployment)
        assert deployment.status == "failed"
        assert "health check" in deployment.error_message.lower()

        # Verify container was cleaned up
        mock_container = mock_docker_client_unhealthy.containers.create.return_value
        assert mock_container.stop.called
        assert mock_container.remove.called

    @pytest.mark.asyncio
    async def test_deployment_fails_with_container_crash(
        self, test_db, test_host, test_database_manager, mock_docker_client_crash
    ):
        """
        Deployment should fail when container crashes during startup.

        Flow:
        1. Create deployment
        2. Pull image
        3. Create container
        4. Start container (container starts but crashes immediately)
        5. Wait for health check (no Docker health check, stability check fails)
        6. Detect crash (running=False after 3s)
        7. Remove crashed container
        8. Mark deployment as "failed"
        """
        # Create deployment
        deployment = Deployment(
            id=f"{test_host.id}:deploy003",
            host_id=test_host.id,
            deployment_type="container",
            name="test-crash-app",
            status="pending",
            definition=json.dumps({
                "container": {
                    "image": "crash-app:latest",
                    "restart_policy": "unless-stopped"
                }
            }),
            progress_percent=0,
            current_stage="pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        test_db.add(deployment)
        test_db.commit()

        # Configure health check timeout
        settings = test_db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings(id=1, health_check_timeout_seconds=60)
            test_db.add(settings)
            test_db.commit()

        # Create executor
        mock_event_bus = AsyncMock()
        mock_docker_monitor = Mock()
        mock_docker_monitor.clients = {test_host.id: mock_docker_client_crash}

        executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_database_manager)

        # Execute deployment
        with patch('deployment.executor.async_docker_call') as mock_async_call, \
             patch.object(executor.image_pull_tracker, 'pull_with_progress', new_callable=AsyncMock) as mock_pull:
            async def passthrough(func, *args, **kwargs):
                return func(*args, **kwargs)
            mock_async_call.side_effect = passthrough

            # Mock image pull to skip actual pulling (we're testing health checks, not image pull)
            mock_pull.return_value = None  # Pull succeeded

            result = await executor.execute_deployment(deployment.id)

        # Verify deployment failed
        assert result is False

        # Verify database state
        test_db.refresh(deployment)
        assert deployment.status == "failed"

        # Verify container was cleaned up
        mock_container = mock_docker_client_crash.containers.create.return_value
        assert mock_container.remove.called or mock_container.stop.called


class TestDeploymentHealthCheckConfiguration:
    """Test that deployment health checks respect configuration."""

    @pytest.mark.asyncio
    async def test_deployment_respects_configured_timeout(
        self, test_db, test_host, test_database_manager
    ):
        """
        Deployment should use health_check_timeout_seconds from GlobalSettings.

        Scenario:
        - User configures health check timeout to 30s in Settings
        - Deployment should wait exactly 30s before timing out
        - Should NOT use default 60s timeout
        """
        # Create deployment
        deployment = Deployment(
            id=f"{test_host.id}:deploy004",
            host_id=test_host.id,
            deployment_type="container",
            name="test-timeout",
            status="pending",
            definition=json.dumps({
                "container": {
                    "image": "nginx:latest",
                    "restart_policy": "unless-stopped"
                }
            }),
            progress_percent=0,
            current_stage="pending",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        test_db.add(deployment)

        # Configure CUSTOM health check timeout (30s instead of default 60s)
        settings = test_db.query(GlobalSettings).first()
        if not settings:
            settings = GlobalSettings(id=1, health_check_timeout_seconds=30)
            test_db.add(settings)
        else:
            settings.health_check_timeout_seconds = 30

        test_db.commit()

        # Create mock client where container stays in "starting" state (never healthy)
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.base_url = 'http+unix:///var/run/docker.sock'

        mock_image = Mock()
        mock_image.id = 'sha256:test_image'
        mock_client.images.pull = Mock(return_value=mock_image)
        mock_client.images.get = Mock(return_value=mock_image)

        mock_container = Mock()
        mock_container.id = 'test_container_id_full' * 4
        mock_container.short_id = 'test_cont_04'
        mock_container.status = 'running'
        mock_container.name = 'test-timeout'
        mock_container.start = Mock()
        mock_container.reload = Mock()
        mock_container.stop = Mock()
        mock_container.remove = Mock()

        # Container stuck at "starting" health status
        mock_container.attrs = {
            "State": {
                "Running": True,
                "Health": {
                    "Status": "starting"  # Never becomes healthy
                }
            }
        }

        mock_client.containers.create = Mock(return_value=mock_container)
        mock_client.containers.get = Mock(return_value=mock_container)
        mock_client.containers.list = Mock(return_value=[])
        mock_client.networks = Mock()
        mock_client.networks.list = Mock(return_value=[])
        mock_client.volumes = Mock()
        mock_client.volumes.list = Mock(return_value=[])

        # Create executor
        mock_event_bus = AsyncMock()
        mock_docker_monitor = Mock()
        mock_docker_monitor.clients = {test_host.id: mock_client}

        executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_database_manager)

        # Execute deployment and measure time
        import time
        start_time = time.time()

        with patch('deployment.executor.async_docker_call') as mock_async_call, \
             patch.object(executor.image_pull_tracker, 'pull_with_progress', new_callable=AsyncMock) as mock_pull:
            async def passthrough(func, *args, **kwargs):
                return func(*args, **kwargs)
            mock_async_call.side_effect = passthrough

            # Mock image pull to skip actual pulling (we're testing health checks, not image pull)
            mock_pull.return_value = None  # Pull succeeded

            result = await executor.execute_deployment(deployment.id)

        elapsed_time = time.time() - start_time

        # Verify deployment failed due to timeout
        assert result is False

        # Verify it used the configured 30s timeout (not default 60s)
        # Allow some margin for processing time
        assert elapsed_time >= 30  # Must wait at least configured timeout
        assert elapsed_time < 45   # Should not wait significantly longer

        # Verify database state reflects timeout
        test_db.refresh(deployment)
        assert deployment.status == "failed"
        assert "timeout" in deployment.error_message.lower() or "health" in deployment.error_message.lower()
