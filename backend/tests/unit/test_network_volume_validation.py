"""
Unit tests for network and volume validation in deployment executor.

Tests cover:
- Network existence checking
- Network auto-creation
- Named volume existence checking
- Named volume auto-creation
- Bind mount validation
- Edge cases and error handling
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from docker.errors import NotFound, APIError

from database import Deployment
from deployment.executor import DeploymentExecutor


@pytest.fixture
def mock_docker_client():
    """Mock Docker SDK client with network and volume management."""
    client = Mock()

    # Network management
    client.networks = Mock()
    client.networks.list = Mock(return_value=[])
    client.networks.create = Mock()
    client.networks.get = Mock()

    # Volume management
    client.volumes = Mock()
    client.volumes.list = Mock(return_value=[])
    client.volumes.create = Mock()
    client.volumes.get = Mock()

    # Container management (for executor)
    client.containers = Mock()
    client.images = Mock()

    return client


@pytest.fixture
def executor(test_db, test_host, mock_docker_client):
    """Create DeploymentExecutor with mocked dependencies."""
    # Mock the dependencies
    mock_event_bus = Mock()
    mock_docker_monitor = Mock()
    mock_docker_monitor.clients = {test_host.id: mock_docker_client}

    # Create executor with mocked dependencies
    executor = DeploymentExecutor(mock_event_bus, mock_docker_monitor, test_db)
    return executor


class TestNetworkValidation:
    """Test network existence checking and validation."""

    def test_network_exists_bridge_mode(self, executor, mock_docker_client):
        """Bridge network should always exist (built-in)."""
        mock_network = Mock()
        mock_network.name = 'bridge'
        mock_docker_client.networks.list.return_value = [mock_network]

        # Network 'bridge' should be found
        result = executor._network_exists(mock_docker_client, 'bridge')
        assert result is True
        mock_docker_client.networks.list.assert_called_once()

    def test_network_exists_custom_network(self, executor, mock_docker_client):
        """Custom network should be found if it exists."""
        mock_network = Mock()
        mock_network.name = 'myapp_network'
        mock_docker_client.networks.list.return_value = [mock_network]

        result = executor._network_exists(mock_docker_client, 'myapp_network')
        assert result is True

    def test_network_not_exists(self, executor, mock_docker_client):
        """Should return False for non-existent network."""
        mock_docker_client.networks.list.return_value = []

        result = executor._network_exists(mock_docker_client, 'nonexistent_network')
        assert result is False

    def test_network_list_error_handling(self, executor, mock_docker_client):
        """Should handle Docker API errors gracefully."""
        mock_docker_client.networks.list.side_effect = APIError('Network API failed')

        with pytest.raises(RuntimeError, match='Failed to check network'):
            executor._network_exists(mock_docker_client, 'mynetwork')


class TestNetworkAutoCreation:
    """Test automatic network creation for deployments."""

    def test_create_network_success(self, executor, mock_docker_client):
        """Should create network with correct parameters."""
        mock_network = Mock()
        mock_network.name = 'myapp_network'
        mock_network.id = 'net123456789abc'
        mock_docker_client.networks.create.return_value = mock_network

        result = executor._ensure_network(mock_docker_client, 'myapp_network')

        assert result == mock_network
        mock_docker_client.networks.create.assert_called_once_with(
            'myapp_network',
            driver='bridge',
            check_duplicate=True
        )

    def test_create_network_custom_driver(self, executor, mock_docker_client):
        """Should support custom network drivers."""
        mock_network = Mock()
        mock_docker_client.networks.create.return_value = mock_network

        result = executor._ensure_network(
            mock_docker_client,
            'overlay_net',
            driver='overlay'
        )

        mock_docker_client.networks.create.assert_called_once_with(
            'overlay_net',
            driver='overlay',
            check_duplicate=True
        )

    def test_create_network_already_exists(self, executor, mock_docker_client):
        """Should return existing network if it already exists."""
        existing_network = Mock()
        existing_network.name = 'existing_net'
        mock_docker_client.networks.list.return_value = [existing_network]
        mock_docker_client.networks.get.return_value = existing_network

        # Should not create, just return existing
        result = executor._ensure_network(mock_docker_client, 'existing_net')

        assert result == existing_network
        mock_docker_client.networks.create.assert_not_called()

    def test_create_network_api_error(self, executor, mock_docker_client):
        """Should handle network creation failures."""
        mock_docker_client.networks.list.return_value = []
        mock_docker_client.networks.create.side_effect = APIError('Insufficient permissions')

        with pytest.raises(RuntimeError, match='Failed to create network'):
            executor._ensure_network(mock_docker_client, 'mynetwork')


class TestVolumeValidation:
    """Test volume existence checking and validation."""

    def test_volume_exists(self, executor, mock_docker_client):
        """Named volume should be found if it exists."""
        mock_volume = Mock()
        mock_volume.name = 'myapp_data'
        mock_docker_client.volumes.list.return_value = [mock_volume]

        result = executor._volume_exists(mock_docker_client, 'myapp_data')
        assert result is True

    def test_volume_not_exists(self, executor, mock_docker_client):
        """Should return False for non-existent volume."""
        mock_docker_client.volumes.list.return_value = []

        result = executor._volume_exists(mock_docker_client, 'nonexistent_volume')
        assert result is False

    def test_volume_list_error_handling(self, executor, mock_docker_client):
        """Should handle Docker API errors gracefully."""
        mock_docker_client.volumes.list.side_effect = APIError('Volume API failed')

        with pytest.raises(RuntimeError, match='Failed to check volume'):
            executor._volume_exists(mock_docker_client, 'myvolume')

    def test_bind_mount_not_volume(self, executor):
        """Bind mounts (absolute paths) should not be checked as volumes."""
        # Bind mounts start with '/' - these are not named volumes
        assert executor._is_named_volume('/host/path') is False
        assert executor._is_named_volume('/var/lib/data') is False

        # Named volumes don't start with '/'
        assert executor._is_named_volume('myapp_data') is True
        assert executor._is_named_volume('postgres_data') is True


class TestVolumeAutoCreation:
    """Test automatic volume creation for deployments."""

    def test_create_volume_success(self, executor, mock_docker_client):
        """Should create named volume with correct parameters."""
        mock_volume = Mock()
        mock_volume.name = 'myapp_data'
        mock_volume.id = 'vol123456789abc'
        mock_docker_client.volumes.create.return_value = mock_volume

        result = executor._ensure_volume(mock_docker_client, 'myapp_data')

        assert result == mock_volume
        mock_docker_client.volumes.create.assert_called_once_with(
            name='myapp_data',
            driver='local'
        )

    def test_create_volume_custom_driver(self, executor, mock_docker_client):
        """Should support custom volume drivers."""
        mock_volume = Mock()
        mock_docker_client.volumes.create.return_value = mock_volume

        result = executor._ensure_volume(
            mock_docker_client,
            'nfs_data',
            driver='nfs'
        )

        mock_docker_client.volumes.create.assert_called_once_with(
            name='nfs_data',
            driver='nfs'
        )

    def test_create_volume_already_exists(self, executor, mock_docker_client):
        """Should return existing volume if it already exists."""
        existing_volume = Mock()
        existing_volume.name = 'existing_vol'
        mock_docker_client.volumes.list.return_value = [existing_volume]
        mock_docker_client.volumes.get.return_value = existing_volume

        # Should not create, just return existing
        result = executor._ensure_volume(mock_docker_client, 'existing_vol')

        assert result == existing_volume
        mock_docker_client.volumes.create.assert_not_called()

    def test_create_volume_api_error(self, executor, mock_docker_client):
        """Should handle volume creation failures."""
        mock_docker_client.volumes.list.return_value = []
        mock_docker_client.volumes.create.side_effect = APIError('Disk full')

        with pytest.raises(RuntimeError, match='Failed to create volume'):
            executor._ensure_volume(mock_docker_client, 'myvolume')

    def test_bind_mount_not_created(self, executor, mock_docker_client):
        """Bind mounts should not attempt volume creation."""
        # Bind mount (starts with '/') should not trigger volume creation
        result = executor._ensure_volume(mock_docker_client, '/host/path')

        assert result is None  # Not a named volume, returns None
        mock_docker_client.volumes.create.assert_not_called()


class TestEdgeCases:
    """Test edge cases and error scenarios."""

    def test_network_name_validation(self, executor, mock_docker_client):
        """Should validate network name format."""
        # Valid network names
        assert executor._validate_network_name('myapp_network') is True
        assert executor._validate_network_name('app-network-1') is True
        assert executor._validate_network_name('bridge') is True

        # Invalid network names
        assert executor._validate_network_name('') is False
        assert executor._validate_network_name('my network') is False  # No spaces
        assert executor._validate_network_name('UPPERCASE') is False  # Lowercase only

    def test_volume_name_validation(self, executor, mock_docker_client):
        """Should validate volume name format."""
        # Valid volume names
        assert executor._validate_volume_name('myapp_data') is True
        assert executor._validate_volume_name('pg-data-v2') is True

        # Invalid volume names
        assert executor._validate_volume_name('') is False
        assert executor._validate_volume_name('my volume') is False  # No spaces
        assert executor._validate_volume_name('/absolute/path') is False  # Not a bind mount

    def test_concurrent_network_creation(self, executor, mock_docker_client):
        """Should handle race condition where network created by another process."""
        # First call: network doesn't exist
        mock_docker_client.networks.list.return_value = []

        # Creation fails because another process created it
        mock_docker_client.networks.create.side_effect = APIError('network already exists')

        # But now it exists, so get() succeeds
        existing_network = Mock()
        existing_network.name = 'rac_network'
        mock_docker_client.networks.get.return_value = existing_network

        # Should handle gracefully and return the existing network
        result = executor._ensure_network(mock_docker_client, 'race_network')
        assert result is not None
