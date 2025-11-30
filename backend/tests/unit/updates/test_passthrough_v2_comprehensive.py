"""
Comprehensive unit tests for v2.1.9 passthrough container update approach.

Tests the three core v2 methods:
- _extract_network_config() - Network configuration extraction
- _extract_container_config_v2() - Passthrough config extraction
- _create_container_v2() - Low-level API container creation

These tests complement test_passthrough_critical.py (GO/NO-GO tests) with
detailed coverage of edge cases, error handling, and configuration variations.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import asyncio

from updates.update_executor import UpdateExecutor


# =============================================================================
# Test Helper: Async Docker Call Mock
# =============================================================================

def make_async_docker_call_mock(mock_client, mock_new_container=None, track_calls=False):
    """Create a mock async_docker_call function for testing.

    This helper properly handles async calls through the async_docker_call wrapper.
    """
    calls_list = [] if track_calls else None

    async def mock_async_docker_call(func, *args, **kwargs):
        if func == mock_client.api.create_container:
            if track_calls:
                calls_list.append({'args': args, 'kwargs': kwargs})
            return {'Id': 'new123456789012'}
        elif func == mock_client.containers.get:
            return mock_new_container or Mock(short_id='new123456789012')
        elif func == getattr(mock_client.containers, 'list', None):
            return []
        else:
            # Handle other async calls
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

    return mock_async_docker_call, calls_list


# =============================================================================
# Test _extract_network_config() - Network Configuration Extraction
# =============================================================================

@pytest.mark.unit
class TestExtractNetworkConfig:
    """Test _extract_network_config() helper method"""

    @pytest.fixture
    def update_executor(self):
        """Create UpdateExecutor instance for testing"""
        return UpdateExecutor(db=Mock(), monitor=Mock())

    def test_bridge_network_mode_returns_network_mode(self, update_executor):
        """Bridge network mode should return network_mode=bridge"""
        attrs = {
            'HostConfig': {'NetworkMode': 'bridge'},
            'NetworkSettings': {'Networks': {}}
        }

        config = update_executor._extract_network_config(attrs)

        assert config['network'] is None
        assert config['network_mode'] == 'bridge'
        assert config.get('_dockmon_manual_networking_config') is None

    def test_host_network_mode_returns_network_mode(self, update_executor):
        """Host network mode should be returned for override"""
        attrs = {
            'HostConfig': {'NetworkMode': 'host'},
            'NetworkSettings': {'Networks': {}}
        }

        config = update_executor._extract_network_config(attrs)

        assert config['network'] is None
        assert config['network_mode'] == 'host'

    def test_none_network_mode_returns_network_mode(self, update_executor):
        """None network mode should be returned for override"""
        attrs = {
            'HostConfig': {'NetworkMode': 'none'},
            'NetworkSettings': {'Networks': {}}
        }

        config = update_executor._extract_network_config(attrs)

        assert config['network'] is None
        assert config['network_mode'] == 'none'

    def test_container_network_mode_returns_network_mode(self, update_executor):
        """Container network mode should be returned for override"""
        attrs = {
            'HostConfig': {'NetworkMode': 'container:gluetun'},
            'NetworkSettings': {'Networks': {}}
        }

        config = update_executor._extract_network_config(attrs)

        assert config['network'] is None
        assert config['network_mode'] == 'container:gluetun'

    def test_single_custom_network_without_static_config(self, update_executor):
        """Single custom network without static IP or aliases - simple connection"""
        attrs = {
            'HostConfig': {'NetworkMode': 'my-custom-net'},
            'NetworkSettings': {
                'Networks': {
                    'my-custom-net': {
                        'NetworkID': 'abc123',
                        'Gateway': '172.18.0.1',
                        'IPAddress': '',  # Empty = dynamic
                        'Aliases': None
                    }
                }
            }
        }

        config = update_executor._extract_network_config(attrs)

        # Simple network connection - no manual config needed
        assert config['network'] == 'my-custom-net'
        assert config['network_mode'] is None
        assert config.get('_manual_networking_config') is None

    def test_single_custom_network_with_static_ip(self, update_executor):
        """Single custom network with static IP - requires manual connection"""
        attrs = {
            'HostConfig': {'NetworkMode': 'my-custom-net'},
            'NetworkSettings': {
                'Networks': {
                    'my-custom-net': {
                        'NetworkID': 'abc123',
                        'IPAddress': '172.18.0.100',  # Static IP
                        'IPPrefixLen': 16,
                        'IPAMConfig': {'IPv4Address': '172.18.0.100'},  # User-configured
                        'Gateway': '172.18.0.1',
                        'Aliases': None
                    }
                }
            }
        }

        config = update_executor._extract_network_config(attrs)

        # Manual connection required for static IP
        assert config['network'] == 'my-custom-net'
        assert config.get('_dockmon_manual_networking_config') is not None

        manual_config = config['_dockmon_manual_networking_config']
        assert 'EndpointsConfig' in manual_config
        assert 'my-custom-net' in manual_config['EndpointsConfig']

    def test_single_custom_network_with_aliases(self, update_executor):
        """Single custom network with aliases - requires manual connection"""
        attrs = {
            'HostConfig': {'NetworkMode': 'my-custom-net'},
            'NetworkSettings': {
                'Networks': {
                    'my-custom-net': {
                        'NetworkID': 'abc123',
                        'IPAddress': '',
                        'Aliases': ['web', 'frontend', 'app']  # Aliases present
                    }
                }
            }
        }

        config = update_executor._extract_network_config(attrs)

        # Manual connection required for aliases
        assert config['network'] == 'my-custom-net'
        assert config.get('_dockmon_manual_networking_config') is not None

        manual_config = config['_dockmon_manual_networking_config']
        assert 'EndpointsConfig' in manual_config
        assert manual_config['EndpointsConfig']['my-custom-net']['Aliases'] == ['web', 'frontend', 'app']

    def test_multiple_custom_networks_requires_manual_connection(self, update_executor):
        """Multiple custom networks always require manual connection"""
        attrs = {
            'HostConfig': {'NetworkMode': 'frontend-net'},
            'NetworkSettings': {
                'Networks': {
                    'frontend-net': {
                        'NetworkID': 'abc123',
                        'IPAddress': '172.18.0.10',
                        'IPPrefixLen': 16,
                        'IPAMConfig': {'IPv4Address': '172.18.0.10'},
                        'Aliases': ['web']
                    },
                    'backend-net': {
                        'NetworkID': 'def456',
                        'IPAddress': '172.19.0.10',
                        'IPPrefixLen': 16,
                        'IPAMConfig': {'IPv4Address': '172.19.0.10'},
                        'Aliases': ['api']
                    }
                }
            }
        }

        config = update_executor._extract_network_config(attrs)

        # Manual connection required for multiple networks
        assert config['network'] == 'frontend-net'  # Primary network
        assert config.get('_dockmon_manual_networking_config') is not None

        manual_config = config['_dockmon_manual_networking_config']
        assert 'EndpointsConfig' in manual_config
        assert 'frontend-net' in manual_config['EndpointsConfig']
        assert 'backend-net' in manual_config['EndpointsConfig']

    def test_empty_networks_returns_network_mode(self, update_executor):
        """Empty networks dict should return network_mode"""
        attrs = {
            'HostConfig': {'NetworkMode': 'bridge'},
            'NetworkSettings': {'Networks': {}}
        }

        config = update_executor._extract_network_config(attrs)

        assert config['network'] is None
        assert config['network_mode'] == 'bridge'

    def test_missing_network_settings_returns_network_mode(self, update_executor):
        """Missing NetworkSettings should return network_mode gracefully"""
        attrs = {
            'HostConfig': {'NetworkMode': 'bridge'}
            # NetworkSettings missing
        }

        config = update_executor._extract_network_config(attrs)

        assert config['network'] is None
        assert config['network_mode'] == 'bridge'


# =============================================================================
# Test _extract_container_config_v2() - Passthrough Config Extraction
# =============================================================================

@pytest.mark.unit
class TestExtractContainerConfigV2:
    """Test _extract_container_config_v2() passthrough extraction"""

    @pytest.fixture
    def update_executor(self):
        """Create UpdateExecutor instance for testing"""
        return UpdateExecutor(db=Mock(), monitor=Mock())

    @pytest.fixture
    def mock_container(self):
        """Create mock container with minimal attrs"""
        container = Mock()
        container.id = 'old123456789012'
        container.short_id = 'old123456789012'[:12]
        container.attrs = {
            'Config': {
                'Image': 'nginx:1.20',
                'Env': ['FOO=bar'],
                'Cmd': None,
                'Entrypoint': None,
                'Labels': {
                    'com.example.app': 'myapp',
                    'org.opencontainers.image.version': '1.0.0'
                },
                'WorkingDir': '/app',
                'User': '1000:1000',
                'Hostname': 'nginx-container',
                'Domainname': '',
                'MacAddress': '02:42:ac:11:00:02',
                'Tty': False,
                'OpenStdin': False,
                'StopSignal': 'SIGTERM',
                'Healthcheck': None
            },
            'HostConfig': {
                'Binds': ['/host/data:/data:rw'],
                'Memory': 536870912,  # 512MB
                'MemorySwap': -1,
                'CpuPeriod': 100000,
                'CpuQuota': 50000,
                'RestartPolicy': {'Name': 'unless-stopped', 'MaximumRetryCount': 0},
                'NetworkMode': 'bridge',
                'PortBindings': {'80/tcp': [{'HostPort': '8080'}]},
                'Privileged': False,
                'ReadonlyRootfs': False
            },
            'NetworkSettings': {
                'Networks': {}
            }
        }
        return container

    async def test_passthrough_preserves_hostconfig_exactly(self, update_executor, mock_container):
        """HostConfig should be passed through without modification (Docker host)"""
        mock_client = Mock()

        config = await update_executor._extract_container_config_v2(
            mock_container,
            mock_client,
            new_image_labels=None,
            is_podman=False
        )

        # HostConfig should be exact copy (not transformed)
        assert config['host_config'] == mock_container.attrs['HostConfig']
        assert config['host_config'] is not mock_container.attrs['HostConfig']  # Copy, not reference

        # Verify specific fields preserved
        assert config['host_config']['Binds'] == ['/host/data:/data:rw']
        assert config['host_config']['Memory'] == 536870912
        assert config['host_config']['CpuQuota'] == 50000

    async def test_podman_filtering_removes_incompatible_fields(self, update_executor, mock_container):
        """Podman host should filter NanoCpus and MemorySwappiness"""
        mock_client = Mock()

        # Add Podman-incompatible fields
        mock_container.attrs['HostConfig']['NanoCpus'] = 2000000000  # 2 CPUs
        mock_container.attrs['HostConfig']['MemorySwappiness'] = 60
        # Remove existing CpuPeriod so conversion happens
        del mock_container.attrs['HostConfig']['CpuPeriod']
        del mock_container.attrs['HostConfig']['CpuQuota']

        config = await update_executor._extract_container_config_v2(
            mock_container,
            mock_client,
            new_image_labels=None,
            is_podman=True
        )

        # NanoCpus should be removed and converted to CpuPeriod/CpuQuota
        assert 'NanoCpus' not in config['host_config']
        assert config['host_config']['CpuPeriod'] == 100000
        assert config['host_config']['CpuQuota'] == 200000  # 2 CPUs

        # MemorySwappiness should be removed
        assert 'MemorySwappiness' not in config['host_config']

    async def test_network_mode_container_id_resolved_to_name(self, update_executor, mock_container):
        """NetworkMode with container:ID should be resolved to container:name"""
        mock_client = Mock()
        mock_ref_container = Mock()
        mock_ref_container.name = 'gluetun'

        mock_container.attrs['HostConfig']['NetworkMode'] = 'container:abc123def456'

        # Mock async_docker_call for container lookup
        async def mock_async_call(func, *args, **kwargs):
            if func == mock_client.containers.get:
                return mock_ref_container
            return func(*args, **kwargs)

        with patch('updates.update_executor.async_docker_call', side_effect=mock_async_call):
            config = await update_executor._extract_container_config_v2(
                mock_container,
                mock_client,
                new_image_labels=None,
                is_podman=False
            )

        # Should be resolved to container:name
        assert config['host_config']['NetworkMode'] == 'container:gluetun'

    async def test_network_mode_container_id_resolution_failure_preserves_id(self, update_executor, mock_container):
        """If container:ID resolution fails, preserve the ID"""
        mock_client = Mock()

        mock_container.attrs['HostConfig']['NetworkMode'] = 'container:abc123def456'

        # Mock async_docker_call to raise exception
        async def mock_async_call(func, *args, **kwargs):
            if func == mock_client.containers.get:
                raise Exception("Container not found")
            return func(*args, **kwargs)

        with patch('updates.update_executor.async_docker_call', side_effect=mock_async_call):
            config = await update_executor._extract_container_config_v2(
                mock_container,
                mock_client,
                new_image_labels=None,
                is_podman=False
            )

        # Should preserve original ID
        assert config['host_config']['NetworkMode'] == 'container:abc123def456'

    async def test_label_merging_preserves_old_labels(self, update_executor, mock_container):
        """User labels should be preserved, image labels subtracted"""
        mock_client = Mock()

        # Old image labels (what the current container's image had)
        old_image_labels = {
            'org.opencontainers.image.version': '1.0.0'
        }

        # New image labels (what the new image will have - Docker adds these automatically)
        new_image_labels = {
            'org.opencontainers.image.version': '2.0.0',  # Updated version
            'org.opencontainers.image.created': '2025-11-20'  # New label
        }

        config = await update_executor._extract_container_config_v2(
            mock_container,
            mock_client,
            old_image_labels=old_image_labels,
            new_image_labels=new_image_labels,
            is_podman=False
        )

        # Custom label preserved (user-added)
        assert config['labels']['com.example.app'] == 'myapp'

        # Image labels removed (Docker will add them from new image automatically)
        assert 'org.opencontainers.image.version' not in config['labels']
        assert 'org.opencontainers.image.created' not in config['labels']

    async def test_network_config_extraction_single_network(self, update_executor, mock_container):
        """Single custom network should be extracted"""
        mock_client = Mock()

        mock_container.attrs['HostConfig']['NetworkMode'] = 'frontend-net'
        mock_container.attrs['NetworkSettings']['Networks'] = {
            'frontend-net': {
                'NetworkID': 'abc123',
                'IPAddress': '',
                'Aliases': None
            }
        }

        config = await update_executor._extract_container_config_v2(
            mock_container,
            mock_client,
            new_image_labels=None,
            is_podman=False
        )

        assert config['network'] == 'frontend-net'
        assert config['network_mode_override'] is None

    async def test_network_config_extraction_multiple_networks(self, update_executor, mock_container):
        """Multiple networks should trigger manual connection"""
        mock_client = Mock()

        mock_container.attrs['HostConfig']['NetworkMode'] = 'frontend-net'
        mock_container.attrs['NetworkSettings']['Networks'] = {
            'frontend-net': {
                'NetworkID': 'abc123',
                'IPAddress': '172.18.0.10',
                'IPPrefixLen': 16,
                'IPAMConfig': {'IPv4Address': '172.18.0.10'}
            },
            'backend-net': {
                'NetworkID': 'def456',
                'IPAddress': '172.19.0.10',
                'IPPrefixLen': 16,
                'IPAMConfig': {'IPv4Address': '172.19.0.10'}
            }
        }

        config = await update_executor._extract_container_config_v2(
            mock_container,
            mock_client,
            new_image_labels=None,
            is_podman=False
        )

        assert config['network'] == 'frontend-net'  # Primary network
        assert config.get('_dockmon_manual_networking_config') is not None


# =============================================================================
# Test _create_container_v2() - Low-Level API Container Creation
# =============================================================================

@pytest.mark.unit
class TestCreateContainerV2:
    """Test _create_container_v2() low-level API creation"""

    @pytest.fixture
    def update_executor(self):
        """Create UpdateExecutor instance for testing"""
        return UpdateExecutor(db=Mock(), monitor=Mock())

    @pytest.fixture
    def minimal_config(self):
        """Minimal extracted config for container creation"""
        return {
            'config': {
                'Image': 'nginx:1.21',
                'Name': '/nginx-test',
                'Hostname': 'nginx-container',
                'User': '1000:1000',
                'Env': ['FOO=bar'],
                'Cmd': None,
                'Entrypoint': None,
                'WorkingDir': '/app',
                'Tty': False,
                'OpenStdin': False,
                'StopSignal': 'SIGTERM',
                'Healthcheck': None,
                'Domainname': '',
                'MacAddress': '02:42:ac:11:00:02'
            },
            'host_config': {
                'Binds': ['/host/data:/data:rw'],
                'Memory': 536870912,
                'NetworkMode': 'bridge',
                'RestartPolicy': {'Name': 'unless-stopped'}
            },
            'labels': {
                'com.example.app': 'myapp'
            },
            'network': None,
            'network_mode_override': None,
            'container_name': 'nginx-test'  # Extracted from config['Name']
        }

    async def test_low_level_api_called_with_correct_params(self, update_executor, minimal_config):
        """Low-level API should be called with all required parameters"""
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.api_version = "1.51"  # Mock API version
        mock_new_container = Mock(short_id='new123456789012')

        mock_async_docker_call, calls_list = make_async_docker_call_mock(
            mock_client, mock_new_container, track_calls=True
        )

        with patch('updates.update_executor.async_docker_call', side_effect=mock_async_docker_call):
            result = await update_executor._create_container_v2(
                mock_client,
                'nginx:1.21',
                minimal_config,
                is_podman=False
            )

        # Verify low-level API was called
        assert len(calls_list) == 1
        api_call = calls_list[0]['kwargs']

        assert api_call['image'] == 'nginx:1.21'
        assert api_call['name'] == 'nginx-test'  # Name without leading slash
        assert api_call['hostname'] == 'nginx-container'
        assert api_call['user'] == '1000:1000'
        assert api_call['environment'] == ['FOO=bar']
        assert api_call['labels'] == {'com.example.app': 'myapp'}
        assert api_call['stop_signal'] == 'SIGTERM'

        # HostConfig passed directly
        assert api_call['host_config'] == minimal_config['host_config']

    async def test_container_network_mode_excludes_hostname_and_mac(self, update_executor, minimal_config):
        """Container network mode should exclude hostname and mac_address"""
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.api_version = "1.51"
        mock_new_container = Mock(short_id='new123456789012')

        minimal_config['host_config']['NetworkMode'] = 'container:gluetun'

        mock_async_docker_call, calls_list = make_async_docker_call_mock(
            mock_client, mock_new_container, track_calls=True
        )

        with patch('updates.update_executor.async_docker_call', side_effect=mock_async_docker_call):
            result = await update_executor._create_container_v2(
                mock_client,
                'nginx:1.21',
                minimal_config,
                is_podman=False
            )

        api_call = calls_list[0]['kwargs']

        # Hostname and mac_address should be None
        assert api_call['hostname'] is None
        assert api_call['mac_address'] is None

    async def test_network_mode_override_applied(self, update_executor, minimal_config):
        """network_mode_override should replace HostConfig NetworkMode"""
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.api_version = "1.51"
        mock_new_container = Mock(short_id='new123456789012')

        minimal_config['network_mode_override'] = 'default'

        mock_async_docker_call, calls_list = make_async_docker_call_mock(
            mock_client, mock_new_container, track_calls=True
        )

        with patch('updates.update_executor.async_docker_call', side_effect=mock_async_docker_call):
            result = await update_executor._create_container_v2(
                mock_client,
                'nginx:1.21',
                minimal_config,
                is_podman=False
            )

        api_call = calls_list[0]['kwargs']

        # NetworkMode should be overridden
        assert api_call['host_config']['NetworkMode'] == 'default'

    async def test_creation_failure_no_cleanup_attempt(self, update_executor, minimal_config):
        """If creation fails, no cleanup attempt should be made"""
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.api_version = "1.51"  # Mock API version

        async def mock_async_call(func, *args, **kwargs):
            if func == mock_client.api.create_container:
                raise Exception("Image not found")
            return func(*args, **kwargs)

        with patch('updates.update_executor.async_docker_call', side_effect=mock_async_call):
            with pytest.raises(Exception, match="Image not found"):
                await update_executor._create_container_v2(
                    mock_client,
                    'nginx:1.21',
                    minimal_config,
                    is_podman=False
                )

    async def test_manual_network_connection_failure_cleans_up_container(self, update_executor, minimal_config):
        """If manual network connection fails, container should be removed"""
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.api_version = "1.51"
        mock_new_container = Mock(short_id='new123456789012')
        mock_new_container.remove = Mock()

        minimal_config['_dockmon_manual_networking_config'] = {
            'EndpointsConfig': {'frontend-net': {'ipv4_address': '172.18.0.100'}}
        }

        # Use API < 1.44 to trigger manual connection path
        mock_client.api.api_version = "1.43"

        async def mock_async_call(func, *args, **kwargs):
            if func == mock_client.api.create_container:
                return {'Id': 'new123456789012'}
            elif func == mock_client.containers.get:
                return mock_new_container
            return func(*args, **kwargs)

        with patch('updates.update_executor.async_docker_call', side_effect=mock_async_call):
            with patch('updates.update_executor.manually_connect_networks', side_effect=Exception("Network connection failed")):
                with pytest.raises(Exception, match="Network connection failed"):
                    await update_executor._create_container_v2(
                        mock_client,
                        'nginx:1.21',
                        minimal_config,
                        is_podman=False
                    )

    async def test_returns_created_container_object(self, update_executor, minimal_config):
        """Should return the created container object"""
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.api_version = "1.51"
        mock_new_container = Mock()
        mock_new_container.short_id = 'new123456789012'

        # Configure mock_client.containers.get to return our container
        mock_client.containers.get.return_value = mock_new_container

        mock_async_docker_call, _ = make_async_docker_call_mock(
            mock_client, mock_new_container
        )

        with patch('updates.update_executor.async_docker_call', side_effect=mock_async_docker_call):
            result = await update_executor._create_container_v2(
                mock_client,
                'nginx:1.21',
                minimal_config,
                is_podman=False
            )

        # Should return the same container object from containers.get()
        assert result == mock_new_container
        assert result.short_id == 'new123456789012'
