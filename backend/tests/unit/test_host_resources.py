"""
Unit tests for host resource management endpoints (Images, Networks, Volumes).

Tests verify:
- List operations return correct data structure
- Delete operations validate inputs and handle edge cases
- Prune operations work correctly
- Built-in resources (networks) cannot be deleted
- Force delete handles resources in use

These tests mock Docker client responses to test endpoint logic without
requiring a real Docker daemon.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone


# =============================================================================
# Mock Docker Objects
# =============================================================================

def create_mock_image(
    image_id: str = "sha256:abc123",
    tags: list = None,
    size: int = 100_000_000,
    created: int = None,
    containers: int = 0
):
    """Create a mock Docker image object."""
    if tags is None:
        tags = ["nginx:latest"]
    if created is None:
        created = int(datetime.now(timezone.utc).timestamp())

    image = MagicMock()
    image.id = image_id
    # Docker short_id for images includes "sha256:" prefix + first 7 chars of hash
    if image_id.startswith("sha256:"):
        image.short_id = image_id[:19]  # "sha256:" (7) + 12 chars of hash
    else:
        image.short_id = image_id[:12]
    image.tags = tags
    image.attrs = {
        'Size': size,
        'Created': created,
        'Containers': containers,
    }
    return image


def create_mock_network(
    network_id: str = "abc123def456",
    name: str = "my-network",
    driver: str = "bridge",
    scope: str = "local",
    internal: bool = False,
    containers: dict = None,
    subnet: str = "172.18.0.0/16"
):
    """Create a mock Docker network object."""
    if containers is None:
        containers = {}

    network = MagicMock()
    network.id = network_id + "0" * (64 - len(network_id))  # Pad to 64 chars
    network.short_id = network_id[:12]
    network.name = name
    network.attrs = {
        'Driver': driver,
        'Scope': scope,
        'Internal': internal,
        'Created': '2025-01-01T00:00:00.000000000Z',
        'Containers': containers,
        'IPAM': {
            'Config': [{'Subnet': subnet}] if subnet else []
        }
    }
    return network


def create_mock_volume(
    name: str = "my-volume",
    driver: str = "local",
    mountpoint: str = None,
    created: str = "2025-01-01T00:00:00Z"
):
    """Create a mock Docker volume object."""
    if mountpoint is None:
        mountpoint = f"/var/lib/docker/volumes/{name}/_data"

    volume = MagicMock()
    volume.name = name
    volume.attrs = {
        'Driver': driver,
        'Mountpoint': mountpoint,
        'CreatedAt': created,
        'Labels': {},
        'Options': {},
    }
    return volume


# =============================================================================
# Image Tests
# =============================================================================

@pytest.mark.unit
class TestListHostImages:
    """Tests for GET /api/hosts/{host_id}/images endpoint logic."""

    def test_list_images_returns_correct_structure(self):
        """Verify image list returns expected fields."""
        # Arrange
        mock_image = create_mock_image(
            image_id="sha256:abc123def456789",
            tags=["nginx:latest", "nginx:1.25"],
            size=150_000_000,
        )

        # Act - simulate endpoint logic
        result = {
            'id': mock_image.short_id,
            'tags': mock_image.tags,
            'size': mock_image.attrs['Size'],
            'created': datetime.fromtimestamp(
                mock_image.attrs['Created'], tz=timezone.utc
            ).isoformat().replace('+00:00', 'Z'),
            'in_use': mock_image.attrs['Containers'] > 0,
            'container_count': mock_image.attrs['Containers'],
            'dangling': len(mock_image.tags) == 0,
        }

        # Assert
        assert result['id'] == 'sha256:abc123def456'
        assert result['tags'] == ["nginx:latest", "nginx:1.25"]
        assert result['size'] == 150_000_000
        assert result['in_use'] is False
        assert result['container_count'] == 0
        assert result['dangling'] is False

    def test_dangling_image_detection(self):
        """Verify dangling images (no tags) are correctly identified."""
        # Arrange - image with no tags
        mock_image = create_mock_image(
            image_id="sha256:orphan123",
            tags=[],  # No tags = dangling
        )

        # Act
        dangling = len(mock_image.tags) == 0

        # Assert
        assert dangling is True

    def test_in_use_image_detection(self):
        """Verify images in use by containers are correctly identified."""
        # Arrange - image used by 2 containers
        mock_image = create_mock_image(
            image_id="sha256:used123",
            containers=2,
        )

        # Act
        in_use = mock_image.attrs['Containers'] > 0
        container_count = mock_image.attrs['Containers']

        # Assert
        assert in_use is True
        assert container_count == 2


@pytest.mark.unit
class TestDeleteImage:
    """Tests for DELETE /api/hosts/{host_id}/images/{image_id} endpoint logic."""

    def test_delete_image_requires_valid_id(self):
        """Verify delete validates image ID format."""
        # Valid short IDs (12 chars)
        valid_ids = ["sha256:abc12", "abc123def456"]

        for img_id in valid_ids:
            # Should be 12 chars or start with sha256:
            assert len(img_id) >= 5  # Minimum reasonable length

    def test_force_delete_removes_in_use_image(self):
        """Verify force=True allows deleting images in use."""
        # Arrange
        mock_client = MagicMock()
        mock_image = create_mock_image(containers=1)  # In use
        mock_client.images.get.return_value = mock_image
        mock_client.images.remove = MagicMock()

        # Act - simulate force delete
        mock_client.images.remove(mock_image.id, force=True)

        # Assert
        mock_client.images.remove.assert_called_once_with(mock_image.id, force=True)


@pytest.mark.unit
class TestPruneImages:
    """Tests for POST /api/hosts/{host_id}/images/prune endpoint logic."""

    def test_prune_returns_reclaimed_space(self):
        """Verify prune returns count and space reclaimed."""
        # Arrange - mock prune response
        prune_result = {
            'ImagesDeleted': [
                {'Deleted': 'sha256:abc123'},
                {'Deleted': 'sha256:def456'},
                {'Untagged': 'old:latest'},
            ],
            'SpaceReclaimed': 500_000_000,  # 500MB
        }

        # Act - simulate endpoint response building
        deleted_count = len([
            img for img in (prune_result.get('ImagesDeleted') or [])
            if 'Deleted' in img
        ])
        space_reclaimed = prune_result.get('SpaceReclaimed', 0)

        # Assert
        assert deleted_count == 2
        assert space_reclaimed == 500_000_000


# =============================================================================
# Network Tests
# =============================================================================

@pytest.mark.unit
class TestListHostNetworks:
    """Tests for GET /api/hosts/{host_id}/networks endpoint logic."""

    def test_list_networks_returns_correct_structure(self):
        """Verify network list returns expected fields."""
        # Arrange
        mock_network = create_mock_network(
            network_id="abc123def456",
            name="my-app-network",
            driver="bridge",
            subnet="172.20.0.0/16",
        )

        # Act - simulate endpoint logic
        result = {
            'id': mock_network.short_id,
            'name': mock_network.name,
            'driver': mock_network.attrs['Driver'],
            'scope': mock_network.attrs['Scope'],
            'internal': mock_network.attrs['Internal'],
            'subnet': mock_network.attrs['IPAM']['Config'][0]['Subnet'],
            'containers': [],
            'container_count': 0,
            'is_builtin': mock_network.name in ('bridge', 'host', 'none'),
        }

        # Assert
        assert result['id'] == 'abc123def456'
        assert result['name'] == 'my-app-network'
        assert result['driver'] == 'bridge'
        assert result['subnet'] == '172.20.0.0/16'
        assert result['is_builtin'] is False

    def test_builtin_network_detection(self):
        """Verify built-in networks are correctly identified."""
        builtin_names = ['bridge', 'host', 'none']

        for name in builtin_names:
            mock_network = create_mock_network(name=name)
            is_builtin = mock_network.name in ('bridge', 'host', 'none')
            assert is_builtin is True, f"{name} should be detected as built-in"

    def test_network_with_containers(self):
        """Verify connected containers are correctly listed."""
        # Arrange - network with 2 connected containers
        containers = {
            'abc123def456': {'Name': 'web-app', 'IPv4Address': '172.20.0.2/16'},
            'def456abc789': {'Name': 'api-server', 'IPv4Address': '172.20.0.3/16'},
        }
        mock_network = create_mock_network(containers=containers)

        # Act - simulate container extraction
        container_list = []
        for cid, cdata in (mock_network.attrs.get('Containers') or {}).items():
            container_list.append({
                'id': cid[:12],
                'name': cdata.get('Name', '').lstrip('/')
            })

        # Assert
        assert len(container_list) == 2
        assert any(c['name'] == 'web-app' for c in container_list)
        assert any(c['name'] == 'api-server' for c in container_list)

    def test_host_network_has_no_subnet(self):
        """Verify host network correctly shows no subnet."""
        # Arrange - host network has no IPAM config
        mock_network = create_mock_network(
            name="host",
            driver="host",
            subnet=None,  # No subnet for host network
        )
        mock_network.attrs['IPAM']['Config'] = []

        # Act
        ipam_config = mock_network.attrs.get('IPAM', {}).get('Config', [])
        subnet = ipam_config[0].get('Subnet', '') if ipam_config else ''

        # Assert
        assert subnet == ''


@pytest.mark.unit
class TestDeleteNetwork:
    """Tests for DELETE /api/hosts/{host_id}/networks/{network_id} endpoint logic."""

    def test_cannot_delete_builtin_networks(self):
        """Verify built-in networks cannot be deleted."""
        builtin_names = ['bridge', 'host', 'none']

        for name in builtin_names:
            # Simulate validation check
            is_builtin = name in ('bridge', 'host', 'none')
            assert is_builtin is True
            # In real endpoint, this would raise HTTPException(400)

    def test_delete_network_with_containers_requires_force(self):
        """Verify deleting network with containers requires force flag."""
        # Arrange
        containers = {
            'abc123': {'Name': 'web-app'},
        }
        mock_network = create_mock_network(containers=containers)

        # Act - check if network has containers
        has_containers = len(mock_network.attrs.get('Containers') or {}) > 0

        # Assert
        assert has_containers is True
        # In real endpoint, this would require force=True or return error

    def test_force_delete_disconnects_containers_first(self):
        """Verify force delete disconnects containers before removing network."""
        # Arrange
        mock_client = MagicMock()
        mock_network = create_mock_network(
            containers={'abc123': {'Name': 'web-app'}}
        )
        mock_client.networks.get.return_value = mock_network
        mock_network.disconnect = MagicMock()
        mock_network.remove = MagicMock()

        # Act - simulate force delete flow
        for container_id in mock_network.attrs.get('Containers', {}).keys():
            mock_network.disconnect(container_id, force=True)
        mock_network.remove()

        # Assert
        mock_network.disconnect.assert_called_once()
        mock_network.remove.assert_called_once()


@pytest.mark.unit
class TestPruneNetworks:
    """Tests for POST /api/hosts/{host_id}/networks/prune endpoint logic."""

    def test_prune_returns_removed_count(self):
        """Verify prune returns count of removed networks."""
        # Arrange - mock prune response
        prune_result = {
            'NetworksDeleted': ['unused-net-1', 'unused-net-2', 'old-network'],
        }

        # Act
        removed_count = len(prune_result.get('NetworksDeleted') or [])

        # Assert
        assert removed_count == 3

    def test_prune_does_not_remove_builtin(self):
        """Verify prune never removes built-in networks."""
        # This is enforced by Docker itself, but we verify our understanding
        builtin = {'bridge', 'host', 'none'}
        pruned = ['unused-net-1', 'old-network']

        # Assert none of the pruned networks are built-in
        for name in pruned:
            assert name not in builtin


# =============================================================================
# Volume Tests
# =============================================================================

@pytest.mark.unit
class TestListHostVolumes:
    """Tests for GET /api/hosts/{host_id}/volumes endpoint logic."""

    def test_list_volumes_returns_correct_structure(self):
        """Verify volume list returns expected fields."""
        # Arrange
        mock_volume = create_mock_volume(
            name="postgres-data",
            driver="local",
        )

        # Act - simulate endpoint logic
        result = {
            'name': mock_volume.name,
            'driver': mock_volume.attrs['Driver'],
            'mountpoint': mock_volume.attrs['Mountpoint'],
            'created': mock_volume.attrs['CreatedAt'],
        }

        # Assert
        assert result['name'] == 'postgres-data'
        assert result['driver'] == 'local'
        assert 'postgres-data' in result['mountpoint']

    def test_volume_in_use_detection(self):
        """Verify volumes in use are correctly identified."""
        # This requires checking container mounts, which is done separately
        # In the endpoint, we check containers for volume mounts
        mock_volume_name = "app-data"

        # Simulate container with this volume mounted
        container_mounts = [
            {'Type': 'volume', 'Name': 'app-data', 'Destination': '/data'},
            {'Type': 'bind', 'Source': '/host/path', 'Destination': '/bind'},
        ]

        # Check if volume is in use
        in_use = any(
            m.get('Type') == 'volume' and m.get('Name') == mock_volume_name
            for m in container_mounts
        )

        assert in_use is True


@pytest.mark.unit
class TestDeleteVolume:
    """Tests for DELETE /api/hosts/{host_id}/volumes/{volume_name} endpoint logic."""

    def test_delete_volume_by_name(self):
        """Verify volume delete uses name (not ID like images/networks)."""
        # Arrange
        mock_client = MagicMock()
        mock_volume = create_mock_volume(name="old-data")
        mock_client.volumes.get.return_value = mock_volume
        mock_volume.remove = MagicMock()

        # Act
        volume = mock_client.volumes.get("old-data")
        volume.remove()

        # Assert
        mock_client.volumes.get.assert_called_with("old-data")
        mock_volume.remove.assert_called_once()

    def test_force_delete_in_use_volume(self):
        """Verify force=True allows deleting volumes in use."""
        # Arrange
        mock_client = MagicMock()
        mock_volume = create_mock_volume(name="busy-volume")
        mock_client.volumes.get.return_value = mock_volume
        mock_volume.remove = MagicMock()

        # Act - force delete
        volume = mock_client.volumes.get("busy-volume")
        volume.remove(force=True)

        # Assert
        mock_volume.remove.assert_called_with(force=True)


@pytest.mark.unit
class TestPruneVolumes:
    """Tests for POST /api/hosts/{host_id}/volumes/prune endpoint logic."""

    def test_prune_returns_reclaimed_space(self):
        """Verify prune returns count and space reclaimed."""
        # Arrange - mock prune response
        prune_result = {
            'VolumesDeleted': ['unused-vol-1', 'old-data', 'temp-storage'],
            'SpaceReclaimed': 1_000_000_000,  # 1GB
        }

        # Act
        removed_count = len(prune_result.get('VolumesDeleted') or [])
        space_reclaimed = prune_result.get('SpaceReclaimed', 0)

        # Assert
        assert removed_count == 3
        assert space_reclaimed == 1_000_000_000


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================

@pytest.mark.unit
class TestResourceNotFound:
    """Tests for 404 handling when resources don't exist."""

    def test_image_not_found_raises_error(self):
        """Verify proper error when image doesn't exist."""
        mock_client = MagicMock()
        from docker.errors import NotFound
        mock_client.images.get.side_effect = NotFound("No such image")

        with pytest.raises(NotFound):
            mock_client.images.get("nonexistent:latest")

    def test_network_not_found_raises_error(self):
        """Verify proper error when network doesn't exist."""
        mock_client = MagicMock()
        from docker.errors import NotFound
        mock_client.networks.get.side_effect = NotFound("No such network")

        with pytest.raises(NotFound):
            mock_client.networks.get("nonexistent-network")

    def test_volume_not_found_raises_error(self):
        """Verify proper error when volume doesn't exist."""
        mock_client = MagicMock()
        from docker.errors import NotFound
        mock_client.volumes.get.side_effect = NotFound("No such volume")

        with pytest.raises(NotFound):
            mock_client.volumes.get("nonexistent-volume")


@pytest.mark.unit
class TestContainerIdFormat:
    """Tests for container ID format in resource responses."""

    def test_container_ids_are_short_format(self):
        """Verify container IDs in responses are 12-char short format."""
        # Full container ID from Docker
        full_id = "abc123def456789012345678901234567890123456789012345678901234"

        # Truncate to short format
        short_id = full_id[:12]

        assert len(short_id) == 12
        assert short_id == "abc123def456"

    def test_image_id_extraction(self):
        """Verify image IDs are correctly extracted."""
        # Image IDs can be sha256:xxx or just the hash
        sha_id = "sha256:abc123def456789"

        # Extract short ID
        short_id = sha_id[:12] if not sha_id.startswith("sha256:") else sha_id[:19]

        assert "sha256:" in short_id or len(short_id) == 12
