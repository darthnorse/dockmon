"""
Shared container health check utility.

This module provides reusable health check logic for both:
- Container updates (updates/update_executor.py)
- Container deployments (deployment/executor.py)

Health check logic respects user-configured timeout from Settings -> Container Updates.
"""

import asyncio
import time
import logging
import docker
from typing import Optional

from utils.async_docker import async_docker_call

logger = logging.getLogger(__name__)


async def wait_for_container_health(
    client: docker.DockerClient,
    container_id: str,
    timeout: int = 60
) -> bool:
    """
    Wait for container to become healthy or stable.

    This function implements DockMon's proven health check logic:
    1. Wait for container to reach "running" state (up to timeout)
    2. If container has Docker HEALTHCHECK: Poll for "healthy" status (up to timeout)
       - Short-circuits immediately when "healthy" detected
       - Returns False immediately if "unhealthy" detected
    3. If no health check: Wait 3s for stability, verify still running
       - Short-circuits as soon as container is running + stable

    Args:
        client: Docker SDK client instance
        container_id: Container ID (12-char short ID recommended)
        timeout: Maximum time to wait in seconds (from GlobalSettings.health_check_timeout_seconds)

    Returns:
        True if container is healthy/stable
        False if container is unhealthy, crashed, or timeout reached

    Examples:
        >>> # Container with Docker health check
        >>> is_healthy = await wait_for_container_health(client, "abc123def456", timeout=60)
        >>> # True if health status becomes "healthy", False if "unhealthy" or timeout

        >>> # Container without health check
        >>> is_healthy = await wait_for_container_health(client, "abc123def456", timeout=60)
        >>> # True if container running + stable for 3s, False if crashes or timeout
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            # Use async wrapper to prevent event loop blocking
            container = await async_docker_call(client.containers.get, container_id)
            state = container.attrs["State"]

            # Check if container is running
            if not state.get("Running", False):
                # Not running YET - wait and retry (don't fail immediately!)
                # Container might still be starting up
                await asyncio.sleep(1)
                continue

            # Container IS running - now check health status
            health = state.get("Health")
            if health:
                # Has Docker HEALTHCHECK configured - poll for healthy status
                status = health.get("Status")
                if status == "healthy":
                    logger.info(f"Container {container_id} is healthy")
                    return True
                elif status == "unhealthy":
                    logger.error(f"Container {container_id} is unhealthy")
                    return False
                # Status is "starting", continue waiting
                logger.debug(f"Container {container_id} health status: {status}, waiting...")
                await asyncio.sleep(2)
            else:
                # No health check configured - container is running (verified above)
                # Wait 3s for stability, then verify still running
                logger.info(f"Container {container_id} has no health check, waiting 3s for stability")
                await asyncio.sleep(3)

                # Check if STILL running (catch quick crashes)
                container = await async_docker_call(client.containers.get, container_id)
                state = container.attrs["State"]
                if state.get("Running", False):
                    logger.info(f"Container {container_id} stable after 3s, considering healthy")
                    return True
                else:
                    logger.error(f"Container {container_id} crashed within 3s of starting")
                    return False

        except docker.errors.NotFound:
            logger.error(f"Container {container_id} not found during health check")
            return False
        except Exception as e:
            logger.error(f"Error checking container health: {e}")
            return False

    logger.error(f"Health check timeout after {timeout}s for container {container_id}")
    return False
