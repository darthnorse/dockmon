"""
Container Operations Module for DockMon
Handles container start, stop, restart operations
"""

import asyncio
import logging
import time
from typing import Dict

from docker import DockerClient
from fastapi import HTTPException

from event_logger import EventLogger
from models.docker_models import DockerHost
from utils.keys import make_composite_key
from agent.manager import AgentManager
from agent.connection_manager import agent_connection_manager
from agent.command_executor import AgentCommandExecutor
from agent.container_operations import AgentContainerOperations

logger = logging.getLogger(__name__)


class ContainerOperations:
    """Handles container start, stop, restart, and delete operations"""

    def __init__(
        self,
        hosts: Dict[str, DockerHost],
        clients: Dict[str, DockerClient],
        event_logger: EventLogger,
        recent_user_actions: Dict[str, float],
        db,  # DatabaseManager
        monitor  # DockerMonitor (for event bus access)
    ):
        self.hosts = hosts
        self.clients = clients
        self.event_logger = event_logger
        self._recent_user_actions = recent_user_actions
        self.db = db
        self.monitor = monitor

        # Initialize agent operations (v2.2.0)
        self.agent_manager = AgentManager()
        self.agent_command_executor = AgentCommandExecutor(agent_connection_manager)
        self.agent_operations = AgentContainerOperations(
            command_executor=self.agent_command_executor,
            db=db,
            agent_manager=self.agent_manager
        )

    async def restart_container(self, host_id: str, container_id: str) -> bool:
        """
        Restart a specific container.

        Routes through agent if available, otherwise uses direct Docker client.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if restart successful

        Raises:
            HTTPException: If host not found or restart fails
        """
        # Check if host has an agent - route through agent if available (v2.2.0)
        agent_id = self.agent_manager.get_agent_for_host(host_id)
        if agent_id:
            logger.info(f"Routing restart_container for host {host_id} through agent {agent_id}")
            return await self.agent_operations.restart_container(host_id, container_id)

        # Legacy path: Direct Docker socket access
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

            # CRITICAL SAFETY CHECK: Prevent restarting DockMon itself
            container_name_lower = container_name.lower().lstrip('/')
            if container_name_lower == 'dockmon' or container_name_lower.startswith('dockmon-'):
                logger.warning(
                    f"Blocked attempt to restart DockMon container '{container_name}'. "
                    f"DockMon cannot restart itself."
                )
                raise HTTPException(
                    status_code=403,
                    detail="Cannot restart DockMon itself. Please restart manually via Docker CLI or another tool."
                )

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

        Routes through agent if available, otherwise uses direct Docker client.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if stop successful

        Raises:
            HTTPException: If host not found or stop fails
        """
        # Check if host has an agent - route through agent if available (v2.2.0)
        agent_id = self.agent_manager.get_agent_for_host(host_id)
        if agent_id:
            logger.info(f"Routing stop_container for host {host_id} through agent {agent_id}")
            return await self.agent_operations.stop_container(host_id, container_id)

        # Legacy path: Direct Docker socket access
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

            # CRITICAL SAFETY CHECK: Prevent stopping DockMon itself
            container_name_lower = container_name.lower().lstrip('/')
            if container_name_lower == 'dockmon' or container_name_lower.startswith('dockmon-'):
                logger.warning(
                    f"Blocked attempt to stop DockMon container '{container_name}'. "
                    f"DockMon cannot stop itself."
                )
                raise HTTPException(
                    status_code=403,
                    detail="Cannot stop DockMon itself. Please stop manually via Docker CLI or another tool."
                )

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

        Routes through agent if available, otherwise uses direct Docker client.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if start successful

        Raises:
            HTTPException: If host not found or start fails
        """
        # Check if host has an agent - route through agent if available (v2.2.0)
        agent_id = self.agent_manager.get_agent_for_host(host_id)
        if agent_id:
            logger.info(f"Routing start_container for host {host_id} through agent {agent_id}")
            return await self.agent_operations.start_container(host_id, container_id)

        # Legacy path: Direct Docker socket access
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

            # Wait briefly and verify container is actually running
            # (containers can crash immediately after start)
            await asyncio.sleep(0.5)
            await async_docker_call(container.reload)

            if container.status != 'running':
                # Container started but crashed immediately
                error_msg = f"Container started but exited with status '{container.status}'"
                if container.status in ['exited', 'dead']:
                    # Try to get exit code
                    try:
                        exit_code = container.attrs.get('State', {}).get('ExitCode', 'unknown')
                        error_msg += f" (exit code {exit_code})"
                    except:
                        pass
                raise Exception(error_msg)

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

    async def delete_container(self, host_id: str, container_id: str, container_name: str, remove_volumes: bool = False) -> dict:
        """
        Delete a container permanently.

        Args:
            host_id: Docker host ID
            container_id: Container SHORT ID (12 chars)
            container_name: Container name (for safety check)
            remove_volumes: If True, also remove anonymous/non-persistent volumes

        Returns:
            {"success": True, "message": "Container deleted successfully"}

        Raises:
            HTTPException: If host not found, container not found, or deletion fails
        """
        from utils.async_docker import async_docker_call
        from event_bus import Event, EventType, get_event_bus
        from database import (
            ContainerUpdate, ContainerDesiredState, ContainerHttpHealthCheck,
            DeploymentMetadata, TagAssignment, AutoRestartConfig,
            BatchJobItem, DeploymentContainer
        )

        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")

        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        start_time = time.time()

        try:
            client = self.clients[host_id]

            # Get container info before deletion
            try:
                container = await async_docker_call(client.containers.get, container_id)
                actual_container_name = container.name.lstrip('/')
                image_name = container.attrs.get('Config', {}).get('Image', 'unknown')
            except Exception as e:
                logger.error(f"Container {container_id} not found on host {host_name}: {e}")
                raise HTTPException(status_code=404, detail=f"Container not found: {str(e)}")

            # CRITICAL SAFETY CHECK: Prevent deleting DockMon itself
            container_name_lower = actual_container_name.lower()
            if container_name_lower == 'dockmon' or container_name_lower.startswith('dockmon-'):
                logger.warning(
                    f"Blocked attempt to delete DockMon container '{actual_container_name}'. "
                    f"DockMon cannot delete itself."
                )
                raise HTTPException(
                    status_code=403,
                    detail="Cannot delete DockMon itself. Please delete manually by stopping the container and removing it via Docker CLI or another tool."
                )

            # Delete container from Docker
            logger.info(f"Deleting container {actual_container_name} ({container_id}) on host {host_name}, removeVolumes={remove_volumes}")
            await async_docker_call(container.remove, v=remove_volumes, force=True)

            # Clean up all related database records
            with self.db.get_session() as session:
                composite_key = make_composite_key(host_id, container_id)

                # Delete from container_updates
                deleted_updates = session.query(ContainerUpdate).filter_by(container_id=composite_key).delete()

                # Delete from container_desired_states
                deleted_states = session.query(ContainerDesiredState).filter_by(container_id=composite_key).delete()

                # Delete from auto_restart_configs
                deleted_restart = session.query(AutoRestartConfig).filter(
                    AutoRestartConfig.host_id == host_id,
                    AutoRestartConfig.container_id == container_id
                ).delete()

                # Delete from container_http_health_checks
                deleted_health = session.query(ContainerHttpHealthCheck).filter_by(container_id=composite_key).delete()

                # Delete tag assignments for this container
                deleted_tags = session.query(TagAssignment).filter(
                    TagAssignment.subject_type == 'container',
                    TagAssignment.subject_id == composite_key
                ).delete()

                # Delete deployment metadata for this container
                deleted_metadata = session.query(DeploymentMetadata).filter_by(container_id=composite_key).delete()

                # NOTE: We do NOT delete batch_job_items - they are audit records and should be preserved
                # even after the container is deleted

                # Delete from deployment_containers junction table
                deleted_deploy_containers = session.query(DeploymentContainer).filter_by(container_id=container_id).delete()

                session.commit()

                logger.info(
                    f"Cleaned up database records for container {actual_container_name} ({composite_key}): "
                    f"updates={deleted_updates}, states={deleted_states}, restart={deleted_restart}, "
                    f"health={deleted_health}, tags={deleted_tags}, metadata={deleted_metadata}, "
                    f"deployment_containers={deleted_deploy_containers}"
                )

            # Emit CONTAINER_DELETED event to event bus
            event = Event(
                event_type=EventType.CONTAINER_DELETED,
                scope_type='container',
                scope_id=composite_key,  # Use composite key for event bus
                scope_name=actual_container_name,
                host_id=host_id,
                host_name=host_name,
                data={'removed_volumes': remove_volumes}
            )
            await get_event_bus(self.monitor).emit(event)

            duration_ms = int((time.time() - start_time) * 1000)

            # Log the successful delete
            self.event_logger.log_container_action(
                action="delete",
                container_name=actual_container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=True,
                triggered_by="user",
                duration_ms=duration_ms
            )

            logger.info(f"Successfully deleted container {actual_container_name} ({container_id}) from host {host_name}")
            return {"success": True, "message": f"Container {actual_container_name} deleted successfully"}

        except HTTPException:
            raise
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Failed to delete container {container_name} on host {host_name}: {e}")

            # Log the failed delete
            self.event_logger.log_container_action(
                action="delete",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=False,
                triggered_by="user",
                error_message=str(e),
                duration_ms=duration_ms
            )
            raise HTTPException(status_code=500, detail=f"Failed to delete container: {str(e)}")
