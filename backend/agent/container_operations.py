"""
Agent Container Operations for DockMon v2.2.0

High-level container operations that route through agents instead of direct Docker socket access.
This is a key component for remote Docker host management.

Usage:
    ops = AgentContainerOperations(command_executor, db, agent_manager)
    success = await ops.start_container("host-123", "container-abc")
"""

import logging
from typing import Optional
from fastapi import HTTPException

from agent.command_executor import AgentCommandExecutor, CommandStatus

logger = logging.getLogger(__name__)


class AgentContainerOperations:
    """
    Container operations via agents.

    Provides high-level container management methods that route operations
    through agents via the AgentCommandExecutor.
    """

    def __init__(self, command_executor: AgentCommandExecutor, db, agent_manager):
        """
        Initialize agent container operations.

        Args:
            command_executor: AgentCommandExecutor instance
            db: DatabaseManager instance
            agent_manager: AgentManager instance
        """
        self.command_executor = command_executor
        self.db = db
        self.agent_manager = agent_manager

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
            "action": "start",
            "container_id": container_id
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        # Handle result
        if result.status == CommandStatus.SUCCESS:
            self._log_event(
                action="start",
                host_id=host_id,
                container_id=container_id,
                success=True
            )
            return True
        elif result.status == CommandStatus.TIMEOUT:
            self._log_event(
                action="start",
                host_id=host_id,
                container_id=container_id,
                success=False,
                error="timeout"
            )
            raise HTTPException(
                status_code=504,
                detail=f"Container start command timed out: {result.error}"
            )
        else:
            self._log_event(
                action="start",
                host_id=host_id,
                container_id=container_id,
                success=False,
                error=result.error
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start container: {result.error}"
            )

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
            "action": "stop",
            "container_id": container_id,
            "timeout": timeout
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=float(timeout + 20)  # Command timeout > container timeout
        )

        # Handle result
        if result.status == CommandStatus.SUCCESS:
            self._log_event(
                action="stop",
                host_id=host_id,
                container_id=container_id,
                success=True
            )
            return True
        elif result.status == CommandStatus.TIMEOUT:
            self._log_event(
                action="stop",
                host_id=host_id,
                container_id=container_id,
                success=False,
                error="timeout"
            )
            raise HTTPException(
                status_code=504,
                detail=f"Container stop command timed out: {result.error}"
            )
        else:
            self._log_event(
                action="stop",
                host_id=host_id,
                container_id=container_id,
                success=False,
                error=result.error
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to stop container: {result.error}"
            )

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
            "action": "restart",
            "container_id": container_id
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        # Handle result
        if result.status == CommandStatus.SUCCESS:
            self._log_event(
                action="restart",
                host_id=host_id,
                container_id=container_id,
                success=True
            )
            return True
        elif result.status == CommandStatus.TIMEOUT:
            self._log_event(
                action="restart",
                host_id=host_id,
                container_id=container_id,
                success=False,
                error="timeout"
            )
            raise HTTPException(
                status_code=504,
                detail=f"Container restart command timed out: {result.error}"
            )
        else:
            self._log_event(
                action="restart",
                host_id=host_id,
                container_id=container_id,
                success=False,
                error=result.error
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to restart container: {result.error}"
            )

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
            "action": "remove",
            "container_id": container_id,
            "force": force
        }

        result = await self.command_executor.execute_command(
            agent_id,
            command,
            timeout=30.0
        )

        # Handle result
        if result.status == CommandStatus.SUCCESS:
            self._log_event(
                action="remove",
                host_id=host_id,
                container_id=container_id,
                success=True
            )
            return True
        elif result.status == CommandStatus.TIMEOUT:
            self._log_event(
                action="remove",
                host_id=host_id,
                container_id=container_id,
                success=False,
                error="timeout"
            )
            raise HTTPException(
                status_code=504,
                detail=f"Container remove command timed out: {result.error}"
            )
        else:
            self._log_event(
                action="remove",
                host_id=host_id,
                container_id=container_id,
                success=False,
                error=result.error
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to remove container: {result.error}"
            )

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
            "action": "get_logs",
            "container_id": container_id,
            "tail": tail
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
            "action": "inspect",
            "container_id": container_id
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

    def _log_event(self, action: str, host_id: str, container_id: str, success: bool, error: str = None):
        """
        Log container operation event.

        Args:
            action: Operation action (start, stop, restart, remove)
            host_id: Docker host ID
            container_id: Container ID
            success: Whether operation succeeded
            error: Error message if failed
        """
        if success:
            logger.info(
                f"Container operation '{action}' successful: "
                f"host={host_id}, container={container_id}"
            )
        else:
            logger.error(
                f"Container operation '{action}' failed: "
                f"host={host_id}, container={container_id}, error={error}"
            )
        # TODO: Store in event_logger for UI display
