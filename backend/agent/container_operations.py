"""
Agent Container Operations for DockMon v2.2.0

High-level container operations that route through agents instead of direct Docker socket access.
This is a key component for remote Docker host management.

Usage:
    ops = AgentContainerOperations(command_executor, db, agent_manager, event_logger)
    success = await ops.start_container("host-123", "container-abc")
"""

import logging
from typing import Optional, Dict, Any, List
from fastapi import HTTPException

from agent.command_executor import AgentCommandExecutor, CommandStatus, CommandResult
from event_logger import EventLogger

logger = logging.getLogger(__name__)


class AgentContainerOperations:
    """
    Container operations via agents.

    Provides high-level container management methods that route operations
    through agents via the AgentCommandExecutor.
    """

    def __init__(self, command_executor: AgentCommandExecutor, db, agent_manager, event_logger=None, monitor=None):
        """
        Initialize agent container operations.

        Args:
            command_executor: AgentCommandExecutor instance
            db: DatabaseManager instance
            agent_manager: AgentManager instance
            event_logger: EventLogger instance (for logging user actions to database)
            monitor: DockerMonitor instance (for container name lookup)
        """
        self.command_executor = command_executor
        self.db = db
        self.agent_manager = agent_manager
        self.event_logger = event_logger
        self.monitor = monitor

    def _handle_operation_result(
        self,
        result: CommandResult,
        action: str,
        host_id: str,
        container_id: str
    ) -> bool:
        """
        Handle command execution result with consistent error handling.

        Args:
            result: CommandResult from command execution
            action: Operation action (start, stop, restart, remove)
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if operation succeeded

        Raises:
            HTTPException: 504 on timeout, 500 on other failures
        """
        if result.status == CommandStatus.SUCCESS:
            self._log_event(
                action=action,
                host_id=host_id,
                container_id=container_id,
                success=True
            )
            return True
        elif result.status == CommandStatus.TIMEOUT:
            self._log_event(
                action=action,
                host_id=host_id,
                container_id=container_id,
                success=False,
                error="timeout"
            )
            raise HTTPException(
                status_code=504,
                detail=f"Container {action} command timed out: {result.error}"
            )
        else:
            self._log_event(
                action=action,
                host_id=host_id,
                container_id=container_id,
                success=False,
                error=result.error
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to {action} container: {result.error}"
            )

    async def start_container(self, host_id: str, container_id: str) -> bool:
        """
        Start a container via agent.

        Args:
            host_id: Docker host ID
            container_id: Container ID (short or full)

        Returns:
            True if started successfully

        Raises:
            HTTPException: If agent not found, command fails, or timeout
        """
        # Get agent for this host
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        # Send start command
        command = {
            "type": "container_operation",
            "payload": {
                "action": "start",
                "container_id": container_id
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        return self._handle_operation_result(result, "start", host_id, container_id)

    async def stop_container(self, host_id: str, container_id: str, timeout: int = 10) -> bool:
        """
        Stop a container via agent.

        Args:
            host_id: Docker host ID
            container_id: Container ID
            timeout: Timeout in seconds for container to stop gracefully

        Returns:
            True if stopped successfully

        Raises:
            HTTPException: If safety check fails, agent not found, or command fails
        """
        # Safety check: prevent stopping DockMon itself
        if await self._is_dockmon_container(host_id, container_id):
            raise HTTPException(
                status_code=403,
                detail="Cannot stop DockMon itself. Please stop manually via Docker CLI."
            )

        # Get agent for this host
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        # Send stop command
        command = {
            "type": "container_operation",
            "payload": {
                "action": "stop",
                "container_id": container_id,
                "timeout": timeout
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=float(timeout + 20)  # Command timeout > container timeout
        )

        return self._handle_operation_result(result, "stop", host_id, container_id)

    async def restart_container(self, host_id: str, container_id: str) -> bool:
        """
        Restart a container via agent.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if restarted successfully

        Raises:
            HTTPException: If safety check fails, agent not found, or command fails
        """
        # Safety check: prevent restarting DockMon itself
        if await self._is_dockmon_container(host_id, container_id):
            raise HTTPException(
                status_code=403,
                detail="Cannot restart DockMon itself. Please restart manually via Docker CLI."
            )

        # Get agent for this host
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        # Send restart command
        command = {
            "type": "container_operation",
            "payload": {
                "action": "restart",
                "container_id": container_id
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        return self._handle_operation_result(result, "restart", host_id, container_id)

    async def remove_container(self, host_id: str, container_id: str, force: bool = False) -> bool:
        """
        Remove a container via agent.

        Args:
            host_id: Docker host ID
            container_id: Container ID
            force: Force removal (kill if running)

        Returns:
            True if removed successfully

        Raises:
            HTTPException: If safety check fails, agent not found, or command fails
        """
        # Safety check: prevent removing DockMon itself
        if await self._is_dockmon_container(host_id, container_id):
            raise HTTPException(
                status_code=403,
                detail="Cannot remove DockMon itself."
            )

        # Get agent for this host
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        # Send remove command
        command = {
            "type": "container_operation",
            "payload": {
                "action": "remove",
                "container_id": container_id,
                "force": force
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        return self._handle_operation_result(result, "remove", host_id, container_id)

    async def get_container_logs(self, host_id: str, container_id: str, tail: int = 100) -> str:
        """
        Get container logs via agent.

        Args:
            host_id: Docker host ID
            container_id: Container ID
            tail: Number of lines to retrieve (default: 100)

        Returns:
            Container logs as string

        Raises:
            HTTPException: If agent not found or command fails
        """
        # Get agent for this host
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        # Send get_logs command
        command = {
            "type": "container_operation",
            "payload": {
                "action": "get_logs",
                "container_id": container_id,
                "tail": tail
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        # Handle result
        if result.status == CommandStatus.SUCCESS:
            return result.response.get("logs", "")
        elif result.status == CommandStatus.TIMEOUT:
            raise HTTPException(
                status_code=504,
                detail=f"Get logs command timed out: {result.error}"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get logs: {result.error}"
            )

    async def inspect_container(self, host_id: str, container_id: str) -> dict:
        """
        Inspect a container via agent.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            Container details dict

        Raises:
            HTTPException: If agent not found or command fails
        """
        # Get agent for this host
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        # Send inspect command
        command = {
            "type": "container_operation",
            "payload": {
                "action": "inspect",
                "container_id": container_id
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=15.0
        )

        # Handle result
        if result.status == CommandStatus.SUCCESS:
            return result.response.get("container", {})
        elif result.status == CommandStatus.TIMEOUT:
            raise HTTPException(
                status_code=504,
                detail=f"Inspect command timed out: {result.error}"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to inspect container: {result.error}"
            )

    async def pull_image(
        self,
        host_id: str,
        image: str,
        deployment_id: Optional[str] = None
    ) -> bool:
        """
        Pull container image via agent.

        Args:
            host_id: Docker host ID
            image: Image name (e.g., "nginx:latest")
            deployment_id: Optional deployment ID for progress tracking

        Returns:
            True if pulled successfully

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        payload = {
            "action": "pull_image",
            "image": image
        }
        if deployment_id:
            payload["deployment_id"] = deployment_id

        command = {
            "type": "container_operation",
            "payload": payload
        }

        # Image pulls can take 30+ minutes
        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=1800.0
        )

        return self._handle_operation_result(result, "pull_image", host_id, image)

    async def create_container(
        self,
        host_id: str,
        config: Dict[str, Any]
    ) -> str:
        """
        Create container via agent.

        Args:
            host_id: Docker host ID
            config: Container configuration dict (Docker SDK format)

        Returns:
            Container SHORT ID (12 chars)

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "container_operation",
            "payload": {
                "action": "create",
                "config": config
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=60.0
        )

        if result.status == CommandStatus.SUCCESS:
            container_id = result.response.get("container_id")
            if not container_id:
                raise HTTPException(
                    status_code=500,
                    detail="Agent did not return container_id"
                )
            # Ensure SHORT ID
            return container_id[:12] if len(container_id) > 12 else container_id
        elif result.status == CommandStatus.TIMEOUT:
            raise HTTPException(
                status_code=504,
                detail=f"Create container command timed out: {result.error}"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create container: {result.error}"
            )

    async def list_networks(self, host_id: str) -> List[Dict[str, Any]]:
        """
        List Docker networks via agent.

        Args:
            host_id: Docker host ID

        Returns:
            List of network dicts

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "container_operation",
            "payload": {
                "action": "list_networks"
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=15.0
        )

        if result.status == CommandStatus.SUCCESS:
            return result.response.get("networks", [])
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list networks: {result.error}"
            )

    async def create_network(
        self,
        host_id: str,
        name: str,
        driver: str = "bridge"
    ) -> str:
        """
        Create Docker network via agent.

        Args:
            host_id: Docker host ID
            name: Network name
            driver: Network driver (default: bridge)

        Returns:
            Network ID

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "container_operation",
            "payload": {
                "action": "create_network",
                "name": name,
                "driver": driver
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        if result.status == CommandStatus.SUCCESS:
            return result.response.get("network_id", "")
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create network: {result.error}"
            )

    async def list_volumes(self, host_id: str) -> List[Dict[str, Any]]:
        """
        List Docker volumes via agent.

        Args:
            host_id: Docker host ID

        Returns:
            List of volume dicts

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "container_operation",
            "payload": {
                "action": "list_volumes"
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=15.0
        )

        if result.status == CommandStatus.SUCCESS:
            return result.response.get("volumes", [])
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list volumes: {result.error}"
            )

    async def create_volume(self, host_id: str, name: str) -> str:
        """
        Create Docker volume via agent.

        Args:
            host_id: Docker host ID
            name: Volume name

        Returns:
            Volume name

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "container_operation",
            "payload": {
                "action": "create_volume",
                "name": name
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        if result.status == CommandStatus.SUCCESS:
            return result.response.get("volume_name", name)
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create volume: {result.error}"
            )

    async def get_container_status(self, host_id: str, container_id: str) -> str:
        """
        Get container status via agent.

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            Status string ('running', 'exited', etc.)

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "container_operation",
            "payload": {
                "action": "get_status",
                "container_id": container_id
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=15.0
        )

        if result.status == CommandStatus.SUCCESS:
            return result.response.get("status", "unknown")
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get container status: {result.error}"
            )

    async def verify_container_running(
        self,
        host_id: str,
        container_id: str,
        max_wait_seconds: int = 60
    ) -> bool:
        """
        Verify container is healthy and running via agent.

        Args:
            host_id: Docker host ID
            container_id: Container ID
            max_wait_seconds: Maximum wait time for health check

        Returns:
            True if healthy/running, False otherwise

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "container_operation",
            "payload": {
                "action": "verify_running",
                "container_id": container_id,
                "max_wait_seconds": max_wait_seconds
            }
        }

        try:
            result = await self.command_executor.execute_command(
                agent_id,
                command,
                timeout=float(max_wait_seconds + 10)
            )

            if result.status == CommandStatus.SUCCESS:
                return result.response.get("is_healthy", False)
            else:
                return False
        except Exception as e:
            logger.error(f"Error verifying container health: {e}")
            return False

    def _get_agent_for_host(self, host_id: str) -> Optional[str]:
        """
        Get agent_id for a given host_id.

        Args:
            host_id: Docker host ID

        Returns:
            Agent ID or None if no agent registered
        """
        return self.agent_manager.get_agent_for_host(host_id)

    async def _is_dockmon_container(self, host_id: str, container_id: str) -> bool:
        """
        Check if container is DockMon itself (safety check).

        Args:
            host_id: Docker host ID
            container_id: Container ID

        Returns:
            True if container is DockMon
        """
        try:
            # Inspect container to get details
            details = await self.inspect_container(host_id, container_id)

            # Check container name
            name = details.get("Name", "").lower().lstrip("/")
            if name == "dockmon" or name.startswith("dockmon-"):
                return True

            # Check labels
            labels = details.get("Config", {}).get("Labels", {})
            if labels.get("app") == "dockmon":
                return True

            return False

        except Exception as e:
            logger.warning(f"Could not check if container is DockMon: {e}")
            # Fail safe: if we can't check, assume it might be DockMon
            return False

    def _log_event(self, action: str, host_id: str, container_id: str, success: bool, error: str = None, container_name: str = None):
        """
        Log container operation event (TODO #6).

        Logs to console AND database via EventLogger for audit trail + UI display.

        Args:
            action: Operation action (start, stop, restart, remove)
            host_id: Docker host ID
            container_id: Container ID
            success: Whether operation succeeded
            error: Error message if failed
            container_name: Container name (optional, looked up from monitor if not provided)
        """
        # Look up friendly names
        host_name = host_id  # Fallback
        if self.db:
            try:
                host = self.db.get_host(host_id)
                if host:
                    host_name = host.name
            except Exception as e:
                logger.debug(f"Could not look up host name for {host_id}: {e}")

        # Look up container name from monitor's in-memory cache
        if not container_name and self.monitor:
            try:
                for c in self.monitor.get_last_containers():
                    if c.host_id == host_id and c.short_id == container_id[:12]:
                        container_name = c.name
                        break
            except Exception as e:
                logger.debug(f"Could not look up container name from monitor for {container_id}: {e}")

        # Use provided container_name or fall back to ID
        resolved_container_name = container_name or container_id

        # Console logging (keep existing)
        if success:
            logger.info(
                f"Container operation '{action}' successful: "
                f"host={host_name}, container={resolved_container_name}"
            )
        else:
            logger.error(
                f"Container operation '{action}' failed: "
                f"host={host_name}, container={resolved_container_name}, error={error}"
            )

        # Database logging + UI broadcast (via EventLogger)
        if self.event_logger:
            try:
                self.event_logger.log_container_action(
                    action=action,
                    container_name=resolved_container_name,
                    container_id=container_id,
                    host_name=host_name,
                    host_id=host_id,
                    success=success,
                    error_message=error,
                    triggered_by='user'
                )

            except Exception as e:
                logger.error(f"Error logging container action to database: {e}", exc_info=True)

    # ==================== Image Operations ====================
    #
    # Note: Image operations use a different message format than container operations:
    #
    # Container operations:
    #   {"type": "container_operation", "payload": {"action": "start", "container_id": "..."}}
    #
    # Image operations:
    #   {"type": "command", "command": "list_images", "payload": {...}}
    #
    # This difference exists because image operations were added later using the
    # generic command infrastructure, while container operations predate it.

    async def list_images(self, host_id: str) -> List[Dict[str, Any]]:
        """
        List all images on a host via agent.

        Args:
            host_id: Docker host ID

        Returns:
            List of image info dicts with keys: id, tags, size, created, in_use, container_count, dangling

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "command",
            "command": "list_images",
            "payload": {}
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        if result.status == CommandStatus.SUCCESS:
            return result.response if result.response else []
        elif result.status == CommandStatus.TIMEOUT:
            raise HTTPException(
                status_code=504,
                detail=f"Timeout listing images on host {host_id}"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list images: {result.error}"
            )

    async def remove_image(self, host_id: str, image_id: str, force: bool = False) -> bool:
        """
        Remove an image via agent.

        Args:
            host_id: Docker host ID
            image_id: Image ID (short or full)
            force: Force remove even if in use

        Returns:
            True if removed successfully

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "command",
            "command": "remove_image",
            "payload": {
                "image_id": image_id,
                "force": force
            }
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=60.0
        )

        if result.status == CommandStatus.SUCCESS:
            logger.info(f"Removed image {image_id} from agent host {host_id}")
            return True
        elif result.status == CommandStatus.TIMEOUT:
            raise HTTPException(
                status_code=504,
                detail=f"Timeout removing image {image_id} on host {host_id}"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to remove image: {result.error}"
            )

    async def prune_images(self, host_id: str) -> Dict[str, Any]:
        """
        Prune unused images via agent.

        Args:
            host_id: Docker host ID

        Returns:
            Dict with removed_count and space_reclaimed

        Raises:
            HTTPException: If agent not found or command fails
        """
        agent_id = self._get_agent_for_host(host_id)
        if not agent_id:
            raise HTTPException(
                status_code=404,
                detail=f"No agent registered for host {host_id}"
            )

        command = {
            "type": "command",
            "command": "prune_images",
            "payload": {}
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=120.0  # Pruning can take a while
        )

        if result.status == CommandStatus.SUCCESS:
            data = result.response or {}
            removed_count = data.get('removed_count', 0)
            space_reclaimed = data.get('space_reclaimed', 0)
            logger.info(f"Pruned {removed_count} images from agent host {host_id}, reclaimed {space_reclaimed} bytes")
            return {
                'removed_count': removed_count,
                'space_reclaimed': space_reclaimed
            }
        elif result.status == CommandStatus.TIMEOUT:
            raise HTTPException(
                status_code=504,
                detail=f"Timeout pruning images on host {host_id}"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to prune images: {result.error}"
            )
