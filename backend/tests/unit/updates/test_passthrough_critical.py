"""
Phase 1 Critical Tests for Passthrough Refactor (v2.2.0)

These are GO/NO-GO tests that MUST pass before proceeding to Phase 2.

Test Coverage:
1. Low-level API accepts raw dict (validate passthrough works)
2. GPU containers work (DeviceRequests preserved)
3. Volume passthrough works (no duplicate mount errors)
4. Podman compatibility (NanoCpus conversion with PascalCase)

If ANY test fails, we MUST stop and reassess the approach.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from updates.update_executor import UpdateExecutor


# Test helper for mocking async_docker_call
def make_async_docker_call_mock(mock_client, mock_new_container, track_calls=False):
    """
    Create a mock async_docker_call function for testing.

    Args:
        mock_client: Mocked Docker client
        mock_new_container: Mocked container object to return from containers.get()
        track_calls: If True, track create_container calls in a list

    Returns:
        Tuple of (mock_function, calls_list)  # calls_list is None if track_calls=False
    """
    calls_list = [] if track_calls else None

    async def mock_async_docker_call(func, *args, **kwargs):
        """Mock async_docker_call to intercept Docker API calls."""
        if func == mock_client.api.create_container:
            if track_calls:
                calls_list.append({'args': args, 'kwargs': kwargs})
            return {'Id': 'new123456789012'}
        elif func == mock_client.containers.get:
            return mock_new_container
        else:
            # For other calls, just execute
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return func(*args, **kwargs)

    return mock_async_docker_call, calls_list


class TestCritical1LowLevelAPI:
    """
    Critical Test 1: Verify low-level API accepts raw HostConfig dict.

    This is the foundational assumption of the passthrough approach.
    If this fails, the entire approach must be reconsidered.
    """

    @pytest.mark.asyncio
    async def test_low_level_api_accepts_raw_hostconfig_dict(self):
        """
        Verify client.api.create_container() accepts raw HostConfig dict.

        This tests that we can pass container.attrs['HostConfig'] directly
        to the low-level API without transformation.
        """
        # Create UpdateExecutor instance (event_bus is not a parameter)
        executor = UpdateExecutor(db=Mock(), monitor=Mock())

        # Mock container.get() return value
        mock_new_container = Mock()
        mock_new_container.short_id = 'new123456789'

        # Mock Docker client with low-level API
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.api_version = "1.51"
        mock_client.api.api_version = "1.51"  # Mock API version for version detection
        mock_client.api.api_version = "1.51"  # Mock API version for version detection
        mock_client.containers = Mock()
        mock_client.containers.get = Mock(return_value=mock_new_container)

        # Create async_docker_call mock with call tracking
        mock_async_call, create_container_calls = make_async_docker_call_mock(
            mock_client, mock_new_container, track_calls=True
        )

        # Raw HostConfig dict (PascalCase, straight from Docker API)
        raw_host_config = {
            'Binds': ['/host/path:/container/path:rw'],
            'Memory': 536870912,  # 512MB
            'NanoCpus': 1000000000,  # 1 CPU
            'RestartPolicy': {'Name': 'unless-stopped', 'MaximumRetryCount': 0},
            'Privileged': False,
            'NetworkMode': 'bridge',
            'PortBindings': {'80/tcp': [{'HostPort': '8080'}]},
            'Devices': [],
            'DeviceRequests': [  # GPU support - was missing in v1!
                {
                    'Driver': 'nvidia',
                    'Count': -1,
                    'Capabilities': [['gpu']]
                }
            ],
        }

        # Extracted config in v2 format (passthrough approach)
        extracted_config = {
            'config': {
                'Name': '/test-container',
                'Hostname': 'test-host',
                'User': 'root',
                'Env': ['ENV=production'],
                'Cmd': ['python', 'app.py'],
                'Entrypoint': None,
                'WorkingDir': '/app',
                'Healthcheck': None,
                'StopSignal': 'SIGTERM',
                'Domainname': '',
                'MacAddress': '',
                'Tty': False,
                'OpenStdin': False,
            },
            'host_config': raw_host_config,  # DIRECT PASSTHROUGH!
            'labels': {'version': '1.0.0'},
            'network': None,
            'network_mode_override': None,
        }

        # Mock manually_connect_networks and async_docker_call (in docker_executor after refactor)
        with patch('updates.docker_executor.manually_connect_networks', new_callable=AsyncMock):
            with patch('updates.docker_executor.async_docker_call', side_effect=mock_async_call):
                # Call _create_container_v2 with passthrough config
                new_container = await executor._create_container_v2(
                    mock_client,
                    'nginx:latest',
                    extracted_config,
                    is_podman=False
                )

                # CRITICAL ASSERTION: Low-level API was called with raw HostConfig
                assert len(create_container_calls) == 1
                call_kwargs = create_container_calls[0]['kwargs']

                # Verify HostConfig was passed directly without transformation
                assert 'host_config' in call_kwargs
                assert call_kwargs['host_config'] is raw_host_config  # Same object reference!

                # Verify all HostConfig fields are present (no stripping)
                passed_host_config = call_kwargs['host_config']
                assert 'Binds' in passed_host_config
                assert 'Memory' in passed_host_config
                assert 'NanoCpus' in passed_host_config
                assert 'DeviceRequests' in passed_host_config  # GPU support!

                # Verify container was returned
                assert new_container == mock_new_container


class TestCritical2GPUSupport:
    """
    Critical Test 2: Verify GPU containers preserve DeviceRequests.

    This was BROKEN in v1 (DeviceRequests not extracted).
    If this fails, GPU containers will lose GPU access after updates.
    """

    @pytest.mark.asyncio
    async def test_gpu_device_requests_preserved_through_passthrough(self):
        """
        Verify DeviceRequests (GPU support) is preserved in passthrough.

        v1 BUG: DeviceRequests was NOT in the extracted field list.
        v2 FIX: HostConfig passthrough preserves ALL fields automatically.
        """
        executor = UpdateExecutor(db=Mock(), monitor=Mock())

        # Mock Docker client
        mock_client = Mock()

        # Mock container with GPU configuration
        mock_container = Mock()
        mock_container.attrs = {
            'Config': {
                'Name': '/gpu-container',
                'Hostname': 'gpu-host',
                'User': 'root',
                'Env': ['CUDA_VISIBLE_DEVICES=0'],
                'Cmd': ['python', 'train.py'],
                'Labels': {},
                'Tty': False,
                'OpenStdin': False,
            },
            'HostConfig': {
                'Memory': 1073741824,  # 1GB
                'NetworkMode': 'bridge',
                # GPU configuration (NVIDIA runtime)
                'DeviceRequests': [
                    {
                        'Driver': 'nvidia',
                        'Count': -1,  # All GPUs
                        'DeviceIDs': [],
                        'Capabilities': [['gpu', 'compute', 'utility']],
                        'Options': {}
                    }
                ],
                'Runtime': 'nvidia',
            },
            'NetworkSettings': {'Networks': {}},
        }

        # Extract config using v2 passthrough approach
        extracted_config = await executor._extract_container_config_v2(
            mock_container,
            mock_client,
            new_image_labels=None,
            is_podman=False
        )

        # CRITICAL ASSERTION: DeviceRequests is preserved
        assert 'host_config' in extracted_config
        assert 'DeviceRequests' in extracted_config['host_config']

        device_requests = extracted_config['host_config']['DeviceRequests']
        assert len(device_requests) == 1
        assert device_requests[0]['Driver'] == 'nvidia'
        assert device_requests[0]['Count'] == -1
        assert 'gpu' in device_requests[0]['Capabilities'][0]

        # Verify Runtime is also preserved
        assert 'Runtime' in extracted_config['host_config']
        assert extracted_config['host_config']['Runtime'] == 'nvidia'


class TestCritical3VolumePassthrough:
    """
    Critical Test 3: Verify volume passthrough eliminates duplicate mounts.

    Issue #68: v1 had duplicate mount errors due to transformation.
    v2 FIX: Binds array passes through directly (no transformation).
    """

    @pytest.mark.asyncio
    async def test_volume_binds_passthrough_no_transformation(self):
        """
        Verify Binds array passes through without dict transformation.

        v1 BUG: Transformed Binds → volumes dict → Binds, causing duplicates.
        v2 FIX: Binds stays in HostConfig, passes through directly.
        """
        executor = UpdateExecutor(db=Mock(), monitor=Mock())

        # Mock Docker client
        mock_client = Mock()

        # Mock container with complex volume setup
        mock_container = Mock()
        mock_container.attrs = {
            'Config': {
                'Name': '/volume-test',
                'Labels': {},
                'Tty': False,
                'OpenStdin': False,
            },
            'HostConfig': {
                # Binds in Docker API format (array of strings)
                'Binds': [
                    '/host/data:/container/data:rw',
                    '/host/config:/container/config:ro',
                    'named-volume:/container/volume:rw',
                ],
                'NetworkMode': 'bridge',
            },
            'Mounts': [
                {
                    'Type': 'bind',
                    'Source': '/host/data',
                    'Destination': '/container/data',
                    'Mode': 'rw',
                    'RW': True,
                },
                {
                    'Type': 'bind',
                    'Source': '/host/config',
                    'Destination': '/container/config',
                    'Mode': 'ro',
                    'RW': False,
                },
                {
                    'Type': 'volume',
                    'Name': 'named-volume',
                    'Source': '/var/lib/docker/volumes/named-volume/_data',
                    'Destination': '/container/volume',
                    'Mode': 'rw',
                    'RW': True,
                },
            ],
            'NetworkSettings': {'Networks': {}},
        }

        # Extract config using v2 passthrough approach
        extracted_config = await executor._extract_container_config_v2(
            mock_container,
            mock_client,
            new_image_labels=None,
            is_podman=False
        )

        # CRITICAL ASSERTION: Binds array is preserved in HostConfig
        assert 'host_config' in extracted_config
        assert 'Binds' in extracted_config['host_config']

        binds = extracted_config['host_config']['Binds']

        # Verify it's still an array (not transformed to dict)
        assert isinstance(binds, list)
        assert len(binds) == 3

        # Verify exact format preserved
        assert '/host/data:/container/data:rw' in binds
        assert '/host/config:/container/config:ro' in binds
        assert 'named-volume:/container/volume:rw' in binds

        # Verify no duplicate entries (Issue #68 fix)
        assert len(binds) == len(set(binds))  # All unique


    @pytest.mark.asyncio
    async def test_volume_passthrough_no_duplicate_mount_errors(self):
        """
        Verify passthrough approach eliminates duplicate mount point errors.

        This is the root cause fix for Issue #68.
        """
        executor = UpdateExecutor(db=Mock(), monitor=Mock())

        # Mock setup
        mock_new_container = Mock(short_id='new123456789')
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.api_version = "1.51"
        mock_client.api.api_version = "1.51"  # Mock API version for version detection
        mock_client.containers = Mock()
        mock_async_call, calls = make_async_docker_call_mock(mock_client, mock_new_container, track_calls=True)

        # Config with Binds array (no transformation)
        extracted_config = {
            'config': {
                'Name': '/test',
                'Tty': False,
                'OpenStdin': False,
            },
            'host_config': {
                'Binds': [
                    '/host/path:/container/path:rw',
                    '/host/path:/container/path:rw',  # Duplicate (shouldn't happen, but test defensive handling)
                ],
                'NetworkMode': 'bridge',
            },
            'labels': {},
            'network': None,
            'network_mode_override': None,
        }

        # Mock manually_connect_networks and async_docker_call (in docker_executor after refactor)
        with patch('updates.docker_executor.manually_connect_networks', new_callable=AsyncMock):
            with patch('updates.docker_executor.async_docker_call', side_effect=mock_async_call):
                # Create container with v2 method
                await executor._create_container_v2(
                    mock_client,
                    'nginx:latest',
                    extracted_config,
                    is_podman=False
                )

                # Verify low-level API was called
                assert len(calls) == 1
                call_kwargs = calls[0]['kwargs']

                # CRITICAL ASSERTION: Binds passed directly (no transformation)
                passed_host_config = call_kwargs['host_config']
                assert 'Binds' in passed_host_config
                assert isinstance(passed_host_config['Binds'], list)

                # No volumes dict parameter (v1 had this, caused duplicates)
                assert 'volumes' not in call_kwargs


class TestCritical4PodmanCompatibility:
    """
    Critical Test 4: Verify Podman compatibility with PascalCase filtering.

    Issue #20: Podman doesn't support NanoCpus/MemorySwappiness.
    v2 must filter these fields AND use PascalCase (raw HostConfig format).
    """

    @pytest.mark.asyncio
    async def test_podman_nano_cpus_conversion_with_pascal_case(self):
        """
        Verify NanoCpus is converted to CpuPeriod/CpuQuota for Podman.

        CRITICAL: Must use PascalCase keys (raw HostConfig format).
        """
        executor = UpdateExecutor(db=Mock(), monitor=Mock())

        # Mock Docker client
        mock_client = Mock()

        # Mock container with NanoCpus (Docker format)
        mock_container = Mock()
        mock_container.attrs = {
            'Config': {
                'Name': '/podman-test',
                'Labels': {},
                'Tty': False,
                'OpenStdin': False,
            },
            'HostConfig': {
                'NanoCpus': 2000000000,  # 2 CPUs
                'Memory': 536870912,
                'NetworkMode': 'bridge',
            },
            'NetworkSettings': {'Networks': {}},
        }

        # Extract config with Podman flag
        extracted_config = await executor._extract_container_config_v2(
            mock_container,
            mock_client,
            new_image_labels=None,
            is_podman=True  # PODMAN MODE
        )

        # CRITICAL ASSERTION: NanoCpus removed, converted to CpuPeriod/CpuQuota
        host_config = extracted_config['host_config']

        # NanoCpus should be removed
        assert 'NanoCpus' not in host_config

        # Converted to CpuPeriod/CpuQuota (PascalCase!)
        assert 'CpuPeriod' in host_config
        assert 'CpuQuota' in host_config

        # Verify conversion math: 2 CPUs = 200000 quota
        assert host_config['CpuPeriod'] == 100000
        assert host_config['CpuQuota'] == 200000  # 2 CPUs


    @pytest.mark.asyncio
    async def test_podman_memory_swappiness_removed_with_pascal_case(self):
        """
        Verify MemorySwappiness is removed for Podman.

        CRITICAL: Must use PascalCase keys (raw HostConfig format).
        """
        executor = UpdateExecutor(db=Mock(), monitor=Mock())

        # Mock Docker client
        mock_client = Mock()

        # Mock container with MemorySwappiness
        mock_container = Mock()
        mock_container.attrs = {
            'Config': {
                'Name': '/podman-test',
                'Labels': {},
                'Tty': False,
                'OpenStdin': False,
            },
            'HostConfig': {
                'Memory': 536870912,
                'MemorySwappiness': 60,  # Podman doesn't support this
                'NetworkMode': 'bridge',
            },
            'NetworkSettings': {'Networks': {}},
        }

        # Extract config with Podman flag
        extracted_config = await executor._extract_container_config_v2(
            mock_container,
            mock_client,
            new_image_labels=None,
            is_podman=True  # PODMAN MODE
        )

        # CRITICAL ASSERTION: MemorySwappiness removed (PascalCase key)
        host_config = extracted_config['host_config']
        assert 'MemorySwappiness' not in host_config

        # Memory preserved
        assert 'Memory' in host_config
        assert host_config['Memory'] == 536870912


    @pytest.mark.asyncio
    async def test_podman_filters_applied_before_passthrough(self):
        """
        Verify Podman filters are applied BEFORE passthrough (not after).

        This ensures incompatible fields never reach Podman's API.
        """
        executor = UpdateExecutor(db=Mock(), monitor=Mock())

        # Mock setup
        mock_new_container = Mock(short_id='new123456789')
        mock_client = Mock()
        mock_client.api = Mock()
        mock_client.api.api_version = "1.51"
        mock_client.api.api_version = "1.51"  # Mock API version for version detection
        mock_client.containers = Mock()
        mock_async_call, calls = make_async_docker_call_mock(mock_client, mock_new_container, track_calls=True)

        # Extract config with Podman-incompatible fields
        mock_container = Mock()
        mock_container.attrs = {
            'Config': {
                'Name': '/podman-test',
                'Labels': {},
                'Tty': False,
                'OpenStdin': False,
            },
            'HostConfig': {
                'NanoCpus': 1000000000,  # Will be converted
                'MemorySwappiness': 60,  # Will be removed
                'Memory': 536870912,
                'NetworkMode': 'bridge',
            },
            'NetworkSettings': {'Networks': {}},
        }

        extracted_config = await executor._extract_container_config_v2(
            mock_container,
            mock_client,
            new_image_labels=None,
            is_podman=True
        )

        # Mock manually_connect_networks and async_docker_call (in docker_executor after refactor)
        with patch('updates.docker_executor.manually_connect_networks', new_callable=AsyncMock):
            with patch('updates.docker_executor.async_docker_call', side_effect=mock_async_call):
                # Create container with v2 method
                await executor._create_container_v2(
                    mock_client,
                    'nginx:latest',
                    extracted_config,
                    is_podman=True
                )

                # CRITICAL ASSERTION: Passed HostConfig has Podman filters applied
                assert len(calls) == 1
                call_kwargs = calls[0]['kwargs']
                passed_host_config = call_kwargs['host_config']

                # Incompatible fields removed
                assert 'NanoCpus' not in passed_host_config
                assert 'MemorySwappiness' not in passed_host_config

                # Converted fields present (PascalCase)
                assert 'CpuPeriod' in passed_host_config
                assert 'CpuQuota' in passed_host_config
