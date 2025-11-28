"""
Tests for dependent container handling during updates.

When a container is updated and recreated with a new ID, any containers
using network_mode: container:that_container must also be recreated to
point to the new ID.

Use cases:
- VPN sidecars (Gluetun + qBittorrent)
- Log forwarders
- Network proxies
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from updates.update_executor import UpdateExecutor


@pytest.mark.unit
class TestDependentContainerDetection:
    """Test detection of dependent containers"""

    @pytest.fixture
    def mock_container(self):
        """Mock main container"""
        container = Mock()
        container.id = "abc123def456"  # Full ID
        container.short_id = "abc123def456"[:12]
        container.name = "gluetun"
        return container

    @pytest.fixture
    def mock_dependent_by_name(self):
        """Mock dependent container using network_mode: container:name"""
        dep = Mock()
        dep.id = "def456ghi789"
        dep.short_id = "def456ghi789"[:12]
        dep.name = "qbittorrent"
        dep.attrs = {
            'HostConfig': {
                'NetworkMode': 'container:gluetun'
            },
            'Config': {
                'Image': 'linuxserver/qbittorrent:latest'
            }
        }
        dep.image = Mock()
        dep.image.tags = ['linuxserver/qbittorrent:latest']
        return dep

    @pytest.fixture
    def mock_dependent_by_id(self):
        """Mock dependent container using network_mode: container:id"""
        dep = Mock()
        dep.id = "ghi789jkl012"
        dep.short_id = "ghi789jkl012"[:12]
        dep.name = "transmission"
        dep.attrs = {
            'HostConfig': {
                'NetworkMode': 'container:abc123def456'  # Using full ID
            },
            'Config': {
                'Image': 'linuxserver/transmission:latest'
            }
        }
        dep.image = Mock()
        dep.image.tags = ['linuxserver/transmission:latest']
        return dep

    @pytest.fixture
    def mock_independent_container(self):
        """Mock independent container (not using network_mode)"""
        indep = Mock()
        indep.id = "xyz987uvw654"
        indep.short_id = "xyz987uvw654"[:12]
        indep.name = "nginx"
        indep.attrs = {
            'HostConfig': {
                'NetworkMode': 'bridge'  # Regular network mode
            }
        }
        return indep

    @pytest.fixture
    def update_executor(self):
        """Create UpdateExecutor instance for testing"""
        executor = UpdateExecutor(
            db=Mock(),
            monitor=Mock()
        )
        return executor

    @pytest.mark.asyncio
    async def test_find_dependent_by_name(
        self,
        update_executor,
        mock_container,
        mock_dependent_by_name,
        mock_independent_container
    ):
        """Test finding dependent container by container name"""
        mock_client = Mock()

        # Mock containers.list to return all containers
        # Patch in docker_executor where async_docker_call is actually used
        with patch('updates.docker_executor.async_docker_call') as mock_async:
            mock_async.return_value = [
                mock_container,
                mock_dependent_by_name,
                mock_independent_container
            ]

            dependents = await update_executor._get_dependent_containers(
                mock_client,
                mock_container,
                "gluetun",
                "abc123def456"
            )

            # Should find qbittorrent (network_mode: container:gluetun)
            # Should NOT find nginx (network_mode: bridge)
            assert len(dependents) == 1
            assert dependents[0]['name'] == 'qbittorrent'
            assert dependents[0]['old_network_mode'] == 'container:gluetun'

    @pytest.mark.asyncio
    async def test_find_dependent_by_id(
        self,
        update_executor,
        mock_container,
        mock_dependent_by_id,
        mock_independent_container
    ):
        """Test finding dependent container by container ID"""
        mock_client = Mock()

        with patch('updates.docker_executor.async_docker_call') as mock_async:
            mock_async.return_value = [
                mock_container,
                mock_dependent_by_id,
                mock_independent_container
            ]

            dependents = await update_executor._get_dependent_containers(
                mock_client,
                mock_container,
                "gluetun",
                "abc123def456"
            )

            # Should find transmission (network_mode: container:abc123def456)
            assert len(dependents) == 1
            assert dependents[0]['name'] == 'transmission'
            assert dependents[0]['old_network_mode'] == 'container:abc123def456'

    @pytest.mark.asyncio
    async def test_find_multiple_dependents(
        self,
        update_executor,
        mock_container,
        mock_dependent_by_name,
        mock_dependent_by_id
    ):
        """Test finding multiple dependent containers"""
        mock_client = Mock()

        with patch('updates.docker_executor.async_docker_call') as mock_async:
            mock_async.return_value = [
                mock_container,
                mock_dependent_by_name,
                mock_dependent_by_id
            ]

            dependents = await update_executor._get_dependent_containers(
                mock_client,
                mock_container,
                "gluetun",
                "abc123def456"
            )

            # Should find both qbittorrent and transmission
            assert len(dependents) == 2
            names = [d['name'] for d in dependents]
            assert 'qbittorrent' in names
            assert 'transmission' in names

    @pytest.mark.asyncio
    async def test_no_dependents(
        self,
        update_executor,
        mock_container,
        mock_independent_container
    ):
        """Test container with no dependents"""
        mock_client = Mock()

        with patch('updates.docker_executor.async_docker_call') as mock_async:
            mock_async.return_value = [
                mock_container,
                mock_independent_container
            ]

            dependents = await update_executor._get_dependent_containers(
                mock_client,
                mock_container,
                "gluetun",
                "abc123def456"
            )

            # Should find no dependents
            assert len(dependents) == 0

    @pytest.mark.asyncio
    async def test_graceful_error_handling(
        self,
        update_executor,
        mock_container
    ):
        """Test graceful handling of Docker API errors"""
        mock_client = Mock()

        # Mock Docker API failure
        with patch('updates.docker_executor.async_docker_call') as mock_async:
            mock_async.side_effect = Exception("Docker API error")

            dependents = await update_executor._get_dependent_containers(
                mock_client,
                mock_container,
                "gluetun",
                "abc123def456"
            )

            # Should return empty list on error (non-fatal)
            assert len(dependents) == 0


@pytest.mark.unit
class TestDependentContainerRecreation:
    """Test recreation of dependent containers"""

    @pytest.fixture
    def update_executor(self):
        """Create UpdateExecutor instance for testing"""
        executor = UpdateExecutor(
            db=Mock(),
            monitor=Mock()
        )
        return executor

    @pytest.mark.asyncio
    async def test_network_mode_updated_correctly(self, update_executor):
        """Test that network_mode is updated to new parent container ID"""
        mock_client = Mock()

        # Mock container with proper attrs structure
        mock_dep_container = Mock()
        mock_dep_container.name = 'qbittorrent'
        mock_dep_container.short_id = 'def456ghi789'
        mock_dep_container.stop = Mock()
        mock_dep_container.remove = Mock()

        dep_info = {
            'container': mock_dep_container,
            'name': 'qbittorrent',
            'id': 'def456',
            'image': 'linuxserver/qbittorrent:latest',
            'old_network_mode': 'container:abc123'
        }

        # v2.2.0: Config format changed to passthrough approach
        mock_config = {
            'config': {},
            'host_config': {
                'NetworkMode': 'container:abc123',  # Old ID (PascalCase)
            },
            'labels': {},
            'network': None,
            'network_mode_override': None,
        }

        new_container = Mock()
        new_container.status = 'running'
        new_container.start = Mock()

        captured_config = {}

        async def capture_create_call(client, image, config, is_podman=False):
            captured_config.update(config)
            return new_container

        # Get the docker_executor that UpdateExecutor delegates to
        docker_executor = update_executor.docker_executor

        # v2.2.0: Mock v2 methods on docker_executor (where delegation goes)
        with patch.object(docker_executor, '_extract_container_config_v2', return_value=mock_config):
            with patch('updates.docker_executor.async_docker_call'):
                with patch.object(docker_executor, '_create_container_v2', side_effect=capture_create_call):
                    with patch('asyncio.sleep'):
                        await update_executor._recreate_dependent_container(
                            mock_client,
                            dep_info,
                            'xyz789_new_full_id',  # New parent full ID
                            is_podman=False
                        )

                        # v2.2.0: Verify network_mode was updated in HostConfig (PascalCase)
                        assert captured_config['host_config']['NetworkMode'] == 'container:xyz789_new_full_id'
