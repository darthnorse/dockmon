"""
Unit tests for deployment layer-by-layer image pull progress.

Tests verify that DirectDockerConnector.pull_image() uses ImagePullProgress
to broadcast real-time layer progress via WebSocket events.

TDD Phase: RED - These tests will fail until implementation is complete.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch, call
from datetime import datetime
import sys
from pathlib import Path
import importlib.util

# Load host_connector module directly without importing deployment package
# This avoids the deployment/__init__.py imports that trigger audit logger
backend_path = Path(__file__).parent.parent.parent
host_connector_path = backend_path / "deployment" / "host_connector.py"

spec = importlib.util.spec_from_file_location("host_connector", host_connector_path)
host_connector_module = importlib.util.module_from_spec(spec)
sys.modules["host_connector"] = host_connector_module
spec.loader.exec_module(host_connector_module)

# Import from loaded module
DirectDockerConnector = host_connector_module.DirectDockerConnector
get_host_connector = host_connector_module.get_host_connector


class TestDeploymentLayerProgress:
    """Test layer-by-layer progress tracking during image pulls"""

    @pytest.fixture
    def mock_docker_client(self):
        """Mock Docker client for testing"""
        client = Mock()
        client.api = Mock()  # Low-level API client for streaming
        return client

    @pytest.fixture
    def mock_connection_manager(self):
        """Mock WebSocket connection manager"""
        manager = Mock()
        manager.broadcast = AsyncMock()
        return manager

    @pytest.fixture
    def mock_image_pull_tracker(self):
        """Mock ImagePullProgress tracker"""
        tracker = Mock()
        tracker.pull_with_progress = AsyncMock()
        return tracker

    @pytest.fixture
    def connector(self, mock_docker_client, mock_connection_manager):
        """Create DirectDockerConnector with mocked dependencies"""
        with patch('host_connector.docker.from_env', return_value=mock_docker_client):
            connector = DirectDockerConnector(
                host_id="test-host-123",
                connection_manager=mock_connection_manager
            )
            return connector

    @pytest.mark.asyncio
    async def test_pull_image_uses_layer_progress_tracker(
        self,
        connector,
        mock_connection_manager,
        mock_image_pull_tracker
    ):
        """
        Test that pull_image() uses ImagePullProgress tracker for layer-by-layer progress.

        EXPECTED BEHAVIOR:
        - Should call ImagePullProgress.pull_with_progress()
        - Should NOT use simple client.images.pull() (old behavior)
        - Should pass correct parameters (image, host_id, entity_id, event_type)
        """
        image = "nginx:1.25-alpine"
        deployment_id = "test-host-123:abc123def456"

        with patch('host_connector.ImagePullProgress', return_value=mock_image_pull_tracker):
            # Execute
            await connector.pull_image(image, deployment_id=deployment_id)

            # Verify ImagePullProgress.pull_with_progress was called
            mock_image_pull_tracker.pull_with_progress.assert_called_once()

            # Verify correct parameters
            call_kwargs = mock_image_pull_tracker.pull_with_progress.call_args.kwargs
            assert call_kwargs['image'] == image
            assert call_kwargs['host_id'] == "test-host-123"
            assert call_kwargs['entity_id'] == deployment_id
            assert call_kwargs['event_type'] == "deployment_layer_progress"

    @pytest.mark.asyncio
    async def test_layer_progress_broadcasts_deployment_events(
        self,
        connector,
        mock_connection_manager
    ):
        """
        Test that layer progress broadcasts WebSocket events with correct structure.

        EXPECTED EVENT STRUCTURE:
        {
            "type": "deployment_layer_progress",
            "data": {
                "host_id": "test-host-123",
                "entity_id": "test-host-123:abc123def456",
                "overall_progress": 45,
                "layers": [...],
                "total_layers": 8,
                "remaining_layers": 0,
                "summary": "Downloading 3 of 8 layers (45%) @ 12.5 MB/s",
                "speed_mbps": 12.5
            }
        }
        """
        # This test verifies the integration between pull_image and ImagePullProgress
        # The actual broadcasting is tested in test_image_pull_progress.py
        # Here we just verify the event_type is correct

        image = "nginx:1.25-alpine"
        deployment_id = "test-host-123:abc123def456"

        # Mock ImagePullProgress to capture the event_type
        captured_event_type = None

        async def mock_pull_with_progress(*args, **kwargs):
            nonlocal captured_event_type
            captured_event_type = kwargs.get('event_type')

        with patch('host_connector.ImagePullProgress') as MockTracker:
            mock_tracker = Mock()
            mock_tracker.pull_with_progress = mock_pull_with_progress
            MockTracker.return_value = mock_tracker

            await connector.pull_image(image, deployment_id=deployment_id)

            # Verify event type is for deployments (not container updates)
            assert captured_event_type == "deployment_layer_progress"

    @pytest.mark.asyncio
    async def test_pull_with_cached_image_layers(
        self,
        connector,
        mock_connection_manager
    ):
        """
        Test image pull with cached layers (Already exists).

        EXPECTED BEHAVIOR:
        - Cached layers should show "Already exists" status
        - Progress should still reach 100%
        - No actual download occurs for cached layers
        """
        image = "nginx:latest"  # Likely cached
        deployment_id = "test-host-123:xyz789"

        # ImagePullProgress handles cached layers internally
        # This test just verifies the call goes through correctly
        with patch('host_connector.ImagePullProgress') as MockTracker:
            mock_tracker = Mock()
            mock_tracker.pull_with_progress = AsyncMock()
            MockTracker.return_value = mock_tracker

            await connector.pull_image(image, deployment_id=deployment_id)

            # Verify call succeeded (ImagePullProgress handles cached layers)
            mock_tracker.pull_with_progress.assert_called_once()

    @pytest.mark.asyncio
    async def test_pull_timeout_handling(
        self,
        connector,
        mock_connection_manager
    ):
        """
        Test that image pull respects timeout setting.

        EXPECTED BEHAVIOR:
        - Should pass timeout to ImagePullProgress
        - Should raise TimeoutError if pull exceeds timeout
        """
        image = "large-image:latest"
        deployment_id = "test-host-123:timeout123"

        with patch('host_connector.ImagePullProgress') as MockTracker:
            mock_tracker = Mock()
            # Simulate timeout
            mock_tracker.pull_with_progress = AsyncMock(side_effect=TimeoutError("Pull exceeded 1800s"))
            MockTracker.return_value = mock_tracker

            # Execute and expect timeout
            with pytest.raises(TimeoutError, match="Pull exceeded 1800s"):
                await connector.pull_image(image, deployment_id=deployment_id)

    @pytest.mark.asyncio
    async def test_pull_image_requires_deployment_id(self, connector):
        """
        Test that pull_image requires deployment_id for entity tracking.

        EXPECTED BEHAVIOR:
        - Should raise error if deployment_id not provided
        - Ensures WebSocket events can be associated with specific deployment
        """
        image = "nginx:latest"

        # Try calling without deployment_id
        with pytest.raises((TypeError, ValueError)) as exc_info:
            await connector.pull_image(image)

        # Should fail because deployment_id is required
        assert "deployment_id" in str(exc_info.value).lower() or "missing" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_connection_manager_injection(self):
        """
        Test that connection_manager is properly injected into DirectDockerConnector.

        EXPECTED BEHAVIOR:
        - DirectDockerConnector should accept connection_manager parameter
        - connection_manager should be passed to ImagePullProgress
        - Enables WebSocket broadcasting
        """
        mock_client = Mock()
        mock_manager = Mock()
        mock_manager.broadcast = AsyncMock()

        with patch('host_connector.docker.from_env', return_value=mock_client):
            connector = DirectDockerConnector(
                host_id="test-host-456",
                connection_manager=mock_manager
            )

            # Verify connection_manager was stored
            assert connector.connection_manager == mock_manager

    @pytest.mark.asyncio
    async def test_get_host_connector_factory_passes_connection_manager(self):
        """
        Test that get_host_connector() factory passes connection_manager.

        EXPECTED BEHAVIOR:
        - get_host_connector(host_id, connection_manager) should pass manager through
        - Enables DeploymentExecutor to inject its connection_manager
        """
        mock_client = Mock()
        mock_manager = Mock()

        with patch('host_connector.docker.from_env', return_value=mock_client):
            with patch('host_connector.docker.DockerClient', return_value=mock_client):
                connector = get_host_connector(
                    host_id="test-host-789",
                    connection_manager=mock_manager
                )

                # Verify connector has connection_manager
                assert hasattr(connector, 'connection_manager')
                assert connector.connection_manager == mock_manager

    @pytest.mark.asyncio
    async def test_layer_progress_integration_with_executor(self):
        """
        Test full integration: DeploymentExecutor -> DirectDockerConnector -> ImagePullProgress.

        EXPECTED FLOW:
        1. DeploymentExecutor calls connector.pull_image(image, deployment_id)
        2. DirectDockerConnector creates ImagePullProgress with connection_manager
        3. ImagePullProgress broadcasts layer progress events
        4. Frontend receives events and updates LayerProgressDisplay component

        This is an integration test verifying the full chain works.
        """
        # This will be tested in integration tests
        # For now, just verify the contract is correct
        pass


class TestImagePullProgressIntegration:
    """Test ImagePullProgress integration with deployment system"""

    @pytest.mark.asyncio
    async def test_image_pull_progress_uses_correct_event_type(self):
        """
        Test that ImagePullProgress broadcasts deployment-specific events.

        DIFFERENCE from container updates:
        - Container updates: event_type = "container_update_layer_progress"
        - Deployments: event_type = "deployment_layer_progress"

        This ensures frontend can distinguish between update progress and deployment progress.
        """
        from utils.image_pull_progress import ImagePullProgress

        mock_manager = Mock()
        mock_manager.broadcast = AsyncMock()

        tracker = ImagePullProgress(
            loop=asyncio.get_event_loop(),
            connection_manager=mock_manager
        )

        # Simulate layer progress broadcast
        await tracker._broadcast_layer_progress(
            host_id="test-host-123",
            entity_id="test-host-123:deploy456",
            event_type="deployment_layer_progress",  # Deployment-specific
            layer_status={
                "abc123": {"status": "Downloading", "current": 50000, "total": 100000},
                "def456": {"status": "Already exists", "current": 0, "total": 0},
            },
            overall_percent=50,
            speed_mbps=10.5
        )

        # Verify broadcast was called
        mock_manager.broadcast.assert_called_once()

        # Verify event structure
        call_args = mock_manager.broadcast.call_args[0][0]
        assert call_args['type'] == "deployment_layer_progress"
        assert call_args['data']['host_id'] == "test-host-123"
        assert call_args['data']['entity_id'] == "test-host-123:deploy456"
        assert call_args['data']['overall_progress'] == 50
        assert 'layers' in call_args['data']
        assert 'summary' in call_args['data']

    @pytest.mark.asyncio
    async def test_deployment_executor_injects_connection_manager(self):
        """
        Test that DeploymentExecutor properly injects connection_manager into connectors.

        EXPECTED BEHAVIOR:
        - DeploymentExecutor has access to connection_manager (via docker_monitor.manager)
        - When getting connector, passes connection_manager
        - Enables layer progress broadcasting
        """
        # This requires refactoring DeploymentExecutor to pass connection_manager
        # to get_host_connector() - will be implemented in GREEN phase
        pass
