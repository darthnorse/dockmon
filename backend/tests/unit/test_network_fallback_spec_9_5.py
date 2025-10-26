"""
Unit tests for network fallback behavior per spec Section 9.5.

Spec requirement (deployment_v2_1_implementation_spec.md, Section 9.5):
- When requested network doesn't exist → fallback to 'bridge'
- Log warning about missing network
- DO NOT auto-create networks

This is the correct behavior per approved spec.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

from database import Deployment, DeploymentContainer
from deployment.executor import DeploymentExecutor


@pytest.fixture
def mock_connector():
    """Mock HostConnector for testing."""
    connector = Mock()
    connector.list_networks = AsyncMock()
    connector.create_network = AsyncMock()
    connector.pull_image = AsyncMock()
    connector.create_container = AsyncMock(return_value='abc123456789')
    connector.start_container = AsyncMock()
    connector.verify_container_running = AsyncMock(return_value=True)
    connector.stop_container = AsyncMock()
    connector.remove_container = AsyncMock()
    return connector


@pytest.fixture
def executor(test_db, mock_connector):
    """Create DeploymentExecutor with mocked connector."""
    mock_event_bus = Mock()
    mock_docker_monitor = Mock()

    executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_db)
    return executor


class TestNetworkFallbackSpecSection9_5:
    """
    Test network fallback behavior per spec Section 9.5.

    Spec: "Pre-deployment validation warns user, falls back to 'bridge'"
    """

    @pytest.mark.asyncio
    async def test_missing_network_falls_back_to_bridge(
        self, executor, test_db, test_host, mock_connector
    ):
        """
        When network doesn't exist, should fallback to 'bridge' (NOT create).

        Spec Section 9.5, lines 3087-3099:
        - Validate networks exist
        - If missing → use 'bridge' instead
        - Log warning
        """
        # Setup: Network 'app_network' does not exist
        mock_connector.list_networks.return_value = [
            {'name': 'bridge'},
            {'name': 'host'},
            {'name': 'none'}
        ]

        definition = {
            'image': 'nginx:latest',
            'name': 'test-nginx',
            'networks': ['app_network']  # Doesn't exist
        }

        with patch('deployment.executor.get_host_connector', return_value=mock_connector):
            # Execute deployment
            with test_db.get_session() as session:
                deployment = Deployment(
                    id=f"{test_host.id}:test123",
                    host_id=test_host.id,
                    name='test-deployment',
                    deployment_type='container',
                    definition=definition,
                    status='pending',
                    progress_percent=0,
                    current_stage='pending',
                    stage_percent=0,
                    committed=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(deployment)
                session.commit()
                deployment_id = deployment.id

            # This should process the deployment
            await executor._execute_deployment_internal(deployment_id)

        # VERIFY: Network was NOT created
        mock_connector.create_network.assert_not_called()

        # VERIFY: Container was created with 'bridge' network instead
        # The definition should have been modified to use 'bridge'
        create_call_args = mock_connector.create_container.call_args
        if create_call_args:
            # Check that 'bridge' is in the container config, not 'app_network'
            container_config = create_call_args[1]  # kwargs
            # NetworkingConfig should reference 'bridge', not 'app_network'
            assert 'app_network' not in str(container_config)

    @pytest.mark.asyncio
    async def test_existing_network_is_used(
        self, executor, test_db, test_host, mock_connector
    ):
        """
        When network exists, should use it (no fallback needed).

        Spec Section 9.5: Only fallback if network doesn't exist.
        """
        # Setup: Network 'app_network' EXISTS
        mock_connector.list_networks.return_value = [
            {'name': 'bridge'},
            {'name': 'app_network'},  # Exists!
            {'name': 'host'}
        ]

        definition = {
            'image': 'nginx:latest',
            'name': 'test-nginx',
            'networks': ['app_network']
        }

        with patch('deployment.executor.get_host_connector', return_value=mock_connector):
            with test_db.get_session() as session:
                deployment = Deployment(
                    id=f"{test_host.id}:test456",
                    host_id=test_host.id,
                    name='test-deployment-2',
                    deployment_type='container',
                    definition=definition,
                    status='pending',
                    progress_percent=0,
                    current_stage='pending',
                    stage_percent=0,
                    committed=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(deployment)
                session.commit()
                deployment_id = deployment.id

            await executor._execute_deployment_internal(deployment_id)

        # VERIFY: Network was NOT created (already exists)
        mock_connector.create_network.assert_not_called()

        # Container should use 'app_network' (no fallback)
        # Definition should remain unchanged

    @pytest.mark.asyncio
    async def test_multiple_networks_with_fallback(
        self, executor, test_db, test_host, mock_connector
    ):
        """
        Mix of existing and missing networks → fallback missing ones to 'bridge'.

        Spec Section 9.5: Validate each network independently.
        """
        # Setup: Only 'traefik_network' exists, 'app_network' does not
        mock_connector.list_networks.return_value = [
            {'name': 'bridge'},
            {'name': 'traefik_network'}  # Only this exists
        ]

        definition = {
            'image': 'nginx:latest',
            'name': 'test-nginx',
            'networks': ['traefik_network', 'app_network']  # Second one missing
        }

        with patch('deployment.executor.get_host_connector', return_value=mock_connector):
            with test_db.get_session() as session:
                deployment = Deployment(
                    id=f"{test_host.id}:test789",
                    host_id=test_host.id,
                    name='test-deployment-3',
                    deployment_type='container',
                    definition=definition,
                    status='pending',
                    progress_percent=0,
                    current_stage='pending',
                    stage_percent=0,
                    committed=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(deployment)
                session.commit()
                deployment_id = deployment.id

            await executor._execute_deployment_internal(deployment_id)

        # VERIFY: No networks created
        mock_connector.create_network.assert_not_called()

        # Result should be: ['traefik_network', 'bridge']
        # (traefik exists → keep it, app_network missing → fallback to bridge)

    @pytest.mark.asyncio
    async def test_bridge_network_always_exists(
        self, executor, test_db, test_host, mock_connector
    ):
        """
        'bridge' network is built-in, should never need fallback.

        Spec Section 9.5: 'bridge' is the fallback target.
        """
        mock_connector.list_networks.return_value = [
            {'name': 'bridge'}  # Only bridge
        ]

        definition = {
            'image': 'nginx:latest',
            'name': 'test-nginx',
            'networks': ['bridge']  # Explicitly use bridge
        }

        with patch('deployment.executor.get_host_connector', return_value=mock_connector):
            with test_db.get_session() as session:
                deployment = Deployment(
                    id=f"{test_host.id}:test999",
                    host_id=test_host.id,
                    name='test-deployment-4',
                    deployment_type='container',
                    definition=definition,
                    status='pending',
                    progress_percent=0,
                    current_stage='pending',
                    stage_percent=0,
                    committed=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(deployment)
                session.commit()
                deployment_id = deployment.id

            await executor._execute_deployment_internal(deployment_id)

        # VERIFY: 'bridge' was used directly, no creation needed
        mock_connector.create_network.assert_not_called()


class TestNetworkValidationLogging:
    """Test that warnings are logged when networks don't exist."""

    @pytest.mark.asyncio
    async def test_warning_logged_for_missing_network(
        self, executor, test_db, test_host, mock_connector, caplog
    ):
        """
        Should log warning when network doesn't exist.

        Spec Section 9.5, line 3098:
        logger.warning(f"Network '{network}' not found, using 'bridge'")
        """
        mock_connector.list_networks.return_value = [{'name': 'bridge'}]

        definition = {
            'image': 'nginx:latest',
            'name': 'test-nginx',
            'networks': ['missing_network']
        }

        with patch('deployment.executor.get_host_connector', return_value=mock_connector):
            with test_db.get_session() as session:
                deployment = Deployment(
                    id=f"{test_host.id}:logtest",
                    host_id=test_host.id,
                    name='test-deployment-log',
                    deployment_type='container',
                    definition=definition,
                    status='pending',
                    progress_percent=0,
                    current_stage='pending',
                    stage_percent=0,
                    committed=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                session.add(deployment)
                session.commit()
                deployment_id = deployment.id

            await executor._execute_deployment_internal(deployment_id)

        # VERIFY: Warning was logged
        # Check caplog for warning message
        warning_found = any(
            "not found" in record.message and "bridge" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )
        assert warning_found, "Should log warning about missing network"
