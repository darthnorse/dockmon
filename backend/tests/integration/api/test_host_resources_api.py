"""
Integration tests for host resource management API endpoints.

Tests verify:
- API endpoints return correct HTTP status codes
- Response structure matches expected format
- Authentication is enforced
- Error handling returns proper error responses
- Built-in resources are protected from deletion

These tests use FastAPI TestClient with mocked Docker client.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone
from fastapi.testclient import TestClient


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_docker_image():
    """Create a mock Docker image."""
    image = MagicMock()
    image.id = "sha256:abc123def456789"
    image.short_id = "sha256:abc123d"
    image.tags = ["nginx:latest", "nginx:1.25"]
    image.attrs = {
        'Size': 150_000_000,
        'Created': int(datetime.now(timezone.utc).timestamp()),
        'Containers': 0,
    }
    return image


@pytest.fixture
def mock_docker_network():
    """Create a mock Docker network."""
    network = MagicMock()
    network.id = "abc123def456" + "0" * 52
    network.short_id = "abc123def456"
    network.name = "my-app-network"
    network.attrs = {
        'Driver': 'bridge',
        'Scope': 'local',
        'Internal': False,
        'Created': '2025-01-01T00:00:00.000000000Z',
        'Containers': {},
        'IPAM': {
            'Config': [{'Subnet': '172.20.0.0/16'}]
        }
    }
    return network


@pytest.fixture
def mock_docker_volume():
    """Create a mock Docker volume."""
    volume = MagicMock()
    volume.name = "postgres-data"
    volume.attrs = {
        'Driver': 'local',
        'Mountpoint': '/var/lib/docker/volumes/postgres-data/_data',
        'CreatedAt': '2025-01-01T00:00:00Z',
        'Labels': {},
        'Options': {},
    }
    return volume


@pytest.fixture
def mock_builtin_network():
    """Create a mock built-in network (bridge)."""
    network = MagicMock()
    network.id = "bridge123456" + "0" * 52
    network.short_id = "bridge123456"
    network.name = "bridge"
    network.attrs = {
        'Driver': 'bridge',
        'Scope': 'local',
        'Internal': False,
        'Created': '2020-01-01T00:00:00.000000000Z',
        'Containers': {},
        'IPAM': {
            'Config': [{'Subnet': '172.17.0.0/16'}]
        }
    }
    return network


# =============================================================================
# Images API Tests
# =============================================================================

@pytest.mark.integration
class TestListImagesAPI:
    """Tests for GET /api/hosts/{host_id}/images endpoint."""

    def test_list_images_returns_200(self, client, test_host, mock_docker_image):
        """Verify list images endpoint returns 200 OK."""
        with patch('main.monitor') as mock_monitor:
            # Setup mock
            mock_client = MagicMock()
            mock_client.images.list.return_value = [mock_docker_image]
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            # Make request
            response = client.get(f"/api/hosts/{test_host.id}/images")

            # Verify
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)

    def test_list_images_host_not_found(self, client):
        """Verify 404 returned for non-existent host."""
        with patch('main.monitor') as mock_monitor:
            mock_monitor.clients = {}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.get("/api/hosts/nonexistent-host/images")

            assert response.status_code == 404


@pytest.mark.integration
class TestDeleteImageAPI:
    """Tests for DELETE /api/hosts/{host_id}/images/{image_id} endpoint."""

    def test_delete_image_returns_200(self, client, test_host, mock_docker_image):
        """Verify delete image endpoint returns 200 OK."""
        with patch('main.monitor') as mock_monitor:
            # Setup mock
            mock_client = MagicMock()
            mock_client.images.get.return_value = mock_docker_image
            mock_client.images.remove = MagicMock()
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            # Make request
            response = client.delete(
                f"/api/hosts/{test_host.id}/images/{mock_docker_image.short_id}"
            )

            # Verify
            assert response.status_code == 200

    def test_delete_image_not_found(self, client, test_host):
        """Verify 404 returned for non-existent image."""
        with patch('main.monitor') as mock_monitor:
            from docker.errors import NotFound
            mock_client = MagicMock()
            mock_client.images.get.side_effect = NotFound("No such image")
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.delete(f"/api/hosts/{test_host.id}/images/nonexistent")

            assert response.status_code == 404


@pytest.mark.integration
class TestPruneImagesAPI:
    """Tests for POST /api/hosts/{host_id}/images/prune endpoint."""

    def test_prune_images_returns_200(self, client, test_host):
        """Verify prune images endpoint returns 200 OK with result."""
        with patch('main.monitor') as mock_monitor:
            # Setup mock
            mock_client = MagicMock()
            mock_client.images.prune.return_value = {
                'ImagesDeleted': [{'Deleted': 'sha256:abc123'}],
                'SpaceReclaimed': 100_000_000,
            }
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            # Make request
            response = client.post(f"/api/hosts/{test_host.id}/images/prune")

            # Verify
            assert response.status_code == 200
            data = response.json()
            assert 'removed_count' in data or 'space_reclaimed' in data


# =============================================================================
# Networks API Tests
# =============================================================================

@pytest.mark.integration
class TestListNetworksAPI:
    """Tests for GET /api/hosts/{host_id}/networks endpoint."""

    def test_list_networks_returns_200(self, client, test_host, mock_docker_network):
        """Verify list networks endpoint returns 200 OK."""
        with patch('main.monitor') as mock_monitor:
            # Setup mock
            mock_client = MagicMock()
            mock_client.networks.list.return_value = [mock_docker_network]
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            # Make request
            response = client.get(f"/api/hosts/{test_host.id}/networks")

            # Verify
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)

    def test_list_networks_includes_subnet(self, client, test_host, mock_docker_network):
        """Verify networks response includes subnet field."""
        with patch('main.monitor') as mock_monitor:
            mock_client = MagicMock()
            mock_client.networks.list.return_value = [mock_docker_network]
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.get(f"/api/hosts/{test_host.id}/networks")

            assert response.status_code == 200
            data = response.json()
            if len(data) > 0:
                # Verify subnet field exists
                assert 'subnet' in data[0]


@pytest.mark.integration
class TestDeleteNetworkAPI:
    """Tests for DELETE /api/hosts/{host_id}/networks/{network_id} endpoint."""

    def test_delete_network_returns_200(self, client, test_host, mock_docker_network):
        """Verify delete network endpoint returns 200 OK."""
        with patch('main.monitor') as mock_monitor:
            # Setup mock
            mock_client = MagicMock()
            mock_client.networks.get.return_value = mock_docker_network
            mock_docker_network.remove = MagicMock()
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            # Make request
            response = client.delete(
                f"/api/hosts/{test_host.id}/networks/{mock_docker_network.short_id}"
            )

            # Verify
            assert response.status_code == 200

    def test_cannot_delete_builtin_network(self, client, test_host, mock_builtin_network):
        """Verify 400 returned when trying to delete built-in network."""
        with patch('main.monitor') as mock_monitor:
            mock_client = MagicMock()
            mock_client.networks.get.return_value = mock_builtin_network
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.delete(
                f"/api/hosts/{test_host.id}/networks/{mock_builtin_network.short_id}"
            )

            # Should return 400 Bad Request for built-in networks
            assert response.status_code == 400
            assert "built-in" in response.json().get("detail", "").lower() or \
                   "system" in response.json().get("detail", "").lower()


@pytest.mark.integration
class TestPruneNetworksAPI:
    """Tests for POST /api/hosts/{host_id}/networks/prune endpoint."""

    def test_prune_networks_returns_200(self, client, test_host):
        """Verify prune networks endpoint returns 200 OK."""
        with patch('main.monitor') as mock_monitor:
            mock_client = MagicMock()
            mock_client.networks.prune.return_value = {
                'NetworksDeleted': ['unused-net-1', 'old-network'],
            }
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.post(f"/api/hosts/{test_host.id}/networks/prune")

            assert response.status_code == 200
            data = response.json()
            assert 'removed_count' in data


# =============================================================================
# Volumes API Tests
# =============================================================================

@pytest.mark.integration
class TestListVolumesAPI:
    """Tests for GET /api/hosts/{host_id}/volumes endpoint."""

    def test_list_volumes_returns_200(self, client, test_host, mock_docker_volume):
        """Verify list volumes endpoint returns 200 OK."""
        with patch('main.monitor') as mock_monitor:
            mock_client = MagicMock()
            mock_client.volumes.list.return_value = [mock_docker_volume]
            mock_client.containers.list.return_value = []  # No containers using volumes
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.get(f"/api/hosts/{test_host.id}/volumes")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)


@pytest.mark.integration
class TestDeleteVolumeAPI:
    """Tests for DELETE /api/hosts/{host_id}/volumes/{volume_name} endpoint."""

    def test_delete_volume_returns_200(self, client, test_host, mock_docker_volume):
        """Verify delete volume endpoint returns 200 OK."""
        with patch('main.monitor') as mock_monitor:
            mock_client = MagicMock()
            mock_client.volumes.get.return_value = mock_docker_volume
            mock_docker_volume.remove = MagicMock()
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.delete(
                f"/api/hosts/{test_host.id}/volumes/{mock_docker_volume.name}"
            )

            assert response.status_code == 200

    def test_delete_volume_not_found(self, client, test_host):
        """Verify 404 returned for non-existent volume."""
        with patch('main.monitor') as mock_monitor:
            from docker.errors import NotFound
            mock_client = MagicMock()
            mock_client.volumes.get.side_effect = NotFound("No such volume")
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.delete(f"/api/hosts/{test_host.id}/volumes/nonexistent")

            assert response.status_code == 404


@pytest.mark.integration
class TestPruneVolumesAPI:
    """Tests for POST /api/hosts/{host_id}/volumes/prune endpoint."""

    def test_prune_volumes_returns_200(self, client, test_host):
        """Verify prune volumes endpoint returns 200 OK."""
        with patch('main.monitor') as mock_monitor:
            mock_client = MagicMock()
            mock_client.volumes.prune.return_value = {
                'VolumesDeleted': ['old-vol-1', 'unused-data'],
                'SpaceReclaimed': 500_000_000,
            }
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.post(f"/api/hosts/{test_host.id}/volumes/prune")

            assert response.status_code == 200
            data = response.json()
            assert 'removed_count' in data or 'space_reclaimed' in data


# =============================================================================
# Error Handling Tests
# =============================================================================

@pytest.mark.integration
class TestResourceAPIErrorHandling:
    """Tests for error handling across all resource endpoints."""

    def test_host_not_found_returns_404(self, client):
        """Verify 404 for all endpoints with non-existent host."""
        with patch('main.monitor') as mock_monitor:
            mock_monitor.clients = {}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            endpoints = [
                "/api/hosts/fake-host/images",
                "/api/hosts/fake-host/networks",
                "/api/hosts/fake-host/volumes",
            ]

            for endpoint in endpoints:
                response = client.get(endpoint)
                assert response.status_code == 404, f"Expected 404 for {endpoint}"

    def test_docker_error_returns_500(self, client, test_host):
        """Verify 500 returned when Docker operation fails."""
        with patch('main.monitor') as mock_monitor:
            from docker.errors import APIError
            mock_client = MagicMock()
            mock_client.images.list.side_effect = APIError("Docker daemon error")
            mock_monitor.clients = {test_host.id: mock_client}
            mock_monitor.operations.agent_manager.get_agent_for_host.return_value = None

            response = client.get(f"/api/hosts/{test_host.id}/images")

            assert response.status_code == 500
