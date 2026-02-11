"""
Async wrappers for Docker SDK to prevent event loop blocking.

The official Docker SDK (docker-py) is synchronous. These wrappers use asyncio.to_thread()
to run blocking calls in a thread pool, keeping the asyncio event loop responsive.

This prevents UI lag and request queueing during Docker API operations.

Memory Safety:
- Uses Python's default thread pool (no custom pool to leak)
- No new connections created (uses existing DockerClient instances)
- All operations delegate to sync SDK (connection lifecycle unchanged)

Usage:
    from utils.async_docker import async_docker_call, async_containers_list

    # Generic wrapper
    info = await async_docker_call(client.info)

    # Convenience functions
    containers = await async_containers_list(client, all=True)
"""

import asyncio
from typing import Callable, TypeVar, Any, Dict, List

# Type variable for generic return types
T = TypeVar('T')


async def async_docker_call(sync_fn: Callable[..., T], *args, **kwargs) -> T:
    """
    Execute a synchronous Docker SDK call in a thread pool.

    This prevents blocking the asyncio event loop during Docker API calls.
    Uses asyncio.to_thread() which delegates to the default ThreadPoolExecutor.

    Memory Safety:
    - No new thread pool created (uses Python's default)
    - No new connections created (uses existing client)
    - Function completes when thread pool task completes
    - No lingering threads or stale state

    Args:
        sync_fn: Synchronous function to call (e.g., client.info, container.start)
        *args: Positional arguments to pass to sync_fn
        **kwargs: Keyword arguments to pass to sync_fn

    Returns:
        Result from the synchronous function

    Example:
        # Read operations
        containers = await async_docker_call(client.containers.list, all=True)
        info = await async_docker_call(client.info)

        # Write operations
        await async_docker_call(container.start)
        await async_docker_call(container.stop, timeout=10)
    """
    return await asyncio.to_thread(sync_fn, *args, **kwargs)


# Convenience functions for common operations
# These provide better IDE autocomplete and type hints

async def async_containers_list(client, **kwargs) -> List:
    """
    List containers asynchronously.

    Defaults ignore_removed=True to skip ghost containers that appear in
    Docker's list endpoint but 404 on inspect. Without this, a single ghost
    container crashes the entire list operation. (Issue #174)

    Pass ignore_removed=False to override if you need to detect ghost containers.

    Args:
        client: Docker client instance
        **kwargs: Arguments to pass to containers.list() (e.g., all=True)

    Returns:
        List of Container objects

    Example:
        all_containers = await async_containers_list(client, all=True)
        running = await async_containers_list(client, filters={'status': 'running'})
    """
    kwargs.setdefault('ignore_removed', True)
    return await async_docker_call(client.containers.list, **kwargs)


async def async_client_info(client) -> Dict[str, Any]:
    """
    Get Docker daemon information asynchronously.

    Args:
        client: Docker client instance

    Returns:
        Dictionary with system info (OSType, OperatingSystem, etc.)
    """
    return await async_docker_call(client.info)


async def async_client_version(client) -> Dict[str, Any]:
    """
    Get Docker version information asynchronously.

    Args:
        client: Docker client instance

    Returns:
        Dictionary with version info (Version, ApiVersion, etc.)
    """
    return await async_docker_call(client.version)


async def async_client_ping(client) -> bool:
    """
    Ping Docker daemon asynchronously.

    Args:
        client: Docker client instance

    Returns:
        True if ping successful

    Raises:
        docker.errors.APIError: If ping fails
    """
    return await async_docker_call(client.ping)


async def async_networks_list(client, **kwargs) -> List:
    """
    List networks asynchronously.

    Args:
        client: Docker client instance
        **kwargs: Arguments to pass to networks.list()

    Returns:
        List of Network objects
    """
    return await async_docker_call(client.networks.list, **kwargs)


async def async_container_start(container) -> None:
    """
    Start a container asynchronously.

    Args:
        container: Container object to start
    """
    await async_docker_call(container.start)


async def async_container_stop(container, timeout: int = 10) -> None:
    """
    Stop a container asynchronously.

    Args:
        container: Container object to stop
        timeout: Seconds to wait before killing (default: 10)
    """
    await async_docker_call(container.stop, timeout=timeout)


async def async_container_restart(container, timeout: int = 10) -> None:
    """
    Restart a container asynchronously.

    Args:
        container: Container object to restart
        timeout: Seconds to wait before killing (default: 10)
    """
    await async_docker_call(container.restart, timeout=timeout)
