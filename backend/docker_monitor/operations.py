"""
Container Operations Module for DockMon
Handles container start, stop, restart operations
"""

import logging
import time
from typing import Dict

from docker import DockerClient
from fastapi import HTTPException

from event_logger import EventLogger
from models.docker_models import DockerHost
from utils.keys import make_composite_key

logger = logging.getLogger(__name__)


class ContainerOperations:
    """Handles container start, stop, and restart operations"""

    def __init__(
        self,
        hosts: Dict[str, DockerHost],
        clients: Dict[str, DockerClient],
        event_logger: EventLogger,
        recent_user_actions: Dict[str, float]
    ):
        self.hosts = hosts
        self.clients = clients
        self.event_logger = event_logger
        self._recent_user_actions = recent_user_actions

    async def restart_container(self, host_id: str, container_id: str) -> bool:
        """
        Restart a specific container.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if restart successful

        Raises:
            HTTPException: If host not found or restart fails
        """
        from utils.async_docker import async_docker_call, async_container_restart

        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")

        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        start_time = time.time()
        container_name = container_id  # Fallback if we can't get name

        try:
            client = self.clients[host_id]
            container = await async_docker_call(client.containers.get, container_id)
            container_name = container.name

            await async_container_restart(container, timeout=10)
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(f"Restarted container '{container_name}' on host '{host_name}'")

            # Log the successful restart
            self.event_logger.log_container_action(
                action="restart",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=True,
                triggered_by="user",
                duration_ms=duration_ms
            )
            return True
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Failed to restart container '{container_name}' on host '{host_name}': {e}")

            # Log the failed restart
            self.event_logger.log_container_action(
                action="restart",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=False,
                triggered_by="user",
                error_message=str(e),
                duration_ms=duration_ms
            )
            raise HTTPException(status_code=500, detail=str(e))

    async def stop_container(self, host_id: str, container_id: str) -> bool:
        """
        Stop a specific container.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if stop successful

        Raises:
            HTTPException: If host not found or stop fails
        """
        from utils.async_docker import async_docker_call, async_container_stop

        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")

        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        start_time = time.time()
        container_name = container_id  # Fallback if we can't get name

        try:
            client = self.clients[host_id]
            container = await async_docker_call(client.containers.get, container_id)
            container_name = container.name

            await async_container_stop(container, timeout=10)
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(f"Stopped container '{container_name}' on host '{host_name}'")

            # Track this user action to suppress critical severity on expected state change
            container_key = make_composite_key(host_id, container_id)
            self._recent_user_actions[container_key] = time.time()
            logger.info(f"Tracked user stop action for {container_key}")

            # Log the successful stop
            self.event_logger.log_container_action(
                action="stop",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=True,
                triggered_by="user",
                duration_ms=duration_ms
            )
            return True
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Failed to stop container '{container_name}' on host '{host_name}': {e}")

            # Log the failed stop
            self.event_logger.log_container_action(
                action="stop",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=False,
                triggered_by="user",
                error_message=str(e),
                duration_ms=duration_ms
            )
            raise HTTPException(status_code=500, detail=str(e))

    async def start_container(self, host_id: str, container_id: str) -> bool:
        """
        Start a specific container.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if start successful

        Raises:
            HTTPException: If host not found or start fails
        """
        from utils.async_docker import async_docker_call, async_container_start

        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")

        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        start_time = time.time()
        container_name = container_id  # Fallback if we can't get name

        try:
            client = self.clients[host_id]
            container = await async_docker_call(client.containers.get, container_id)
            container_name = container.name

            await async_container_start(container)
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(f"Started container '{container_name}' on host '{host_name}'")

            # Track this user action to suppress critical severity on expected state change
            container_key = make_composite_key(host_id, container_id)
            self._recent_user_actions[container_key] = time.time()
            logger.info(f"Tracked user start action for {container_key}")

            # Log the successful start
            self.event_logger.log_container_action(
                action="start",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=True,
                triggered_by="user",
                duration_ms=duration_ms
            )
            return True
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Failed to start container '{container_name}' on host '{host_name}': {e}")

            # Log the failed start
            self.event_logger.log_container_action(
                action="start",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=False,
                triggered_by="user",
                error_message=str(e),
                duration_ms=duration_ms
            )
            raise HTTPException(status_code=500, detail=str(e))
