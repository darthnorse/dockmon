"""
Agent Command Executor for DockMon v2.2.0

Handles command execution to agents with request/response tracking, timeouts, and error handling.

Architecture:
- Sends commands to agents via AgentConnectionManager
- Tracks pending commands with correlation IDs
- Waits for responses with configurable timeouts
- Provides clean interface for container operations
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional, Any
import time

logger = logging.getLogger(__name__)


class CommandStatus(Enum):
    """Status of command execution"""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class CommandResult:
    """Result of command execution"""
    status: CommandStatus
    success: bool
    response: Optional[Dict[str, Any]]
    error: Optional[str]
    duration_seconds: float = 0.0


class AgentCommandExecutor:
    """
    Executes commands on agents and tracks responses.

    Provides request/response pattern on top of WebSocket connections:
    1. Generate correlation ID for command
    2. Register pending command (future)
    3. Send command to agent
    4. Wait for response with timeout
    5. Clean up pending command
    """

    def __init__(self, connection_manager):
        """
        Initialize command executor.

        Args:
            connection_manager: AgentConnectionManager instance
        """
        self.connection_manager = connection_manager
        self._pending_commands: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def execute_command(
        self,
        agent_id: str,
        command: dict,
        timeout: float = 30.0
    ) -> CommandResult:
        """
        Execute a command on an agent and wait for response.

        Args:
            agent_id: Agent UUID
            command: Command dict (e.g., {"type": "container_operation", "action": "start"})
            timeout: Timeout in seconds (default: 30)

        Returns:
            CommandResult with status, response, and error information
        """
        start_time = time.time()

        # Check if agent is connected
        if not self.connection_manager.is_connected(agent_id):
            return CommandResult(
                status=CommandStatus.ERROR,
                success=False,
                response=None,
                error=f"Agent {agent_id} is not connected",
                duration_seconds=time.time() - start_time
            )

        # Generate correlation ID for this command
        correlation_id = str(uuid.uuid4())

        # Add correlation_id to command
        command_with_correlation = {
            **command,
            "correlation_id": correlation_id
        }

        # Create future for response
        response_future = asyncio.Future()

        # Register pending command
        async with self._lock:
            self._pending_commands[correlation_id] = {
                "future": response_future,
                "agent_id": agent_id,
                "started_at": datetime.utcnow()
            }

        # Send command to agent
        send_success = await self.connection_manager.send_command(
            agent_id,
            command_with_correlation
        )

        if not send_success:
            # Clean up pending command
            async with self._lock:
                self._pending_commands.pop(correlation_id, None)

            return CommandResult(
                status=CommandStatus.ERROR,
                success=False,
                response=None,
                error=f"Failed to send command to agent {agent_id}",
                duration_seconds=time.time() - start_time
            )

        # Wait for response with timeout
        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)

            duration = time.time() - start_time

            # Parse response
            if response.get("success"):
                return CommandResult(
                    status=CommandStatus.SUCCESS,
                    success=True,
                    response=response,
                    error=None,
                    duration_seconds=duration
                )
            else:
                return CommandResult(
                    status=CommandStatus.ERROR,
                    success=False,
                    response=response,
                    error=response.get("error", "Unknown error"),
                    duration_seconds=duration
                )

        except asyncio.TimeoutError:
            # Clean up pending command
            async with self._lock:
                self._pending_commands.pop(correlation_id, None)

            logger.warning(
                f"Command timeout after {timeout}s for agent {agent_id}, "
                f"correlation_id: {correlation_id}"
            )

            return CommandResult(
                status=CommandStatus.TIMEOUT,
                success=False,
                response=None,
                error=f"Command timeout after {timeout} seconds",
                duration_seconds=timeout
            )

        except ConnectionError as e:
            # Agent disconnected during wait
            async with self._lock:
                self._pending_commands.pop(correlation_id, None)

            return CommandResult(
                status=CommandStatus.ERROR,
                success=False,
                response=None,
                error=f"Agent disconnected: {str(e)}",
                duration_seconds=time.time() - start_time
            )

        except Exception as e:
            # Unexpected error
            async with self._lock:
                self._pending_commands.pop(correlation_id, None)

            logger.error(f"Unexpected error executing command: {e}", exc_info=True)

            return CommandResult(
                status=CommandStatus.ERROR,
                success=False,
                response=None,
                error=f"Unexpected error: {str(e)}",
                duration_seconds=time.time() - start_time
            )

        finally:
            # Always clean up pending command
            async with self._lock:
                self._pending_commands.pop(correlation_id, None)

    def handle_agent_response(self, response: dict):
        """
        Handle a response from an agent.

        Should be called by WebSocket handler when agent sends a response.
        Matches response to pending command by correlation_id and resolves future.

        Args:
            response: Response dict from agent (must have 'correlation_id')
        """
        correlation_id = response.get("correlation_id")

        if not correlation_id:
            # Response without correlation_id (unsolicited message, heartbeat, etc.)
            logger.debug("Received agent message without correlation_id, ignoring")
            return

        # Find pending command
        pending = self._pending_commands.get(correlation_id)

        if not pending:
            logger.warning(f"Received response for unknown correlation_id: {correlation_id}")
            return

        # Resolve future with response
        future = pending["future"]
        if not future.done():
            future.set_result(response)
            logger.debug(f"Resolved command response for correlation_id: {correlation_id}")

    def cleanup_expired_pending_commands(self, max_age_seconds: int = 300):
        """
        Clean up pending commands that have exceeded max age.

        This prevents memory leaks if agents disconnect without responding.
        Should be called periodically (e.g., every minute).

        Args:
            max_age_seconds: Maximum age in seconds (default: 5 minutes)
        """
        now = datetime.utcnow()
        max_age = timedelta(seconds=max_age_seconds)

        expired_ids = []

        for correlation_id, pending in self._pending_commands.items():
            age = now - pending["started_at"]
            if age > max_age:
                expired_ids.append(correlation_id)

        # Cancel and remove expired commands
        for correlation_id in expired_ids:
            pending = self._pending_commands.pop(correlation_id, None)
            if pending:
                future = pending["future"]
                if not future.done():
                    future.cancel()

                logger.warning(
                    f"Cancelled expired pending command: {correlation_id} "
                    f"(age: {(now - pending['started_at']).total_seconds()}s)"
                )

    def get_pending_command_count(self) -> int:
        """Get count of pending commands"""
        return len(self._pending_commands)

    async def _wait_for_response(self, correlation_id: str, timeout: float) -> dict:
        """
        Wait for response for a specific correlation ID.

        Note: This method is primarily for testing purposes.
        The actual waiting is done in execute_command using the future.

        Args:
            correlation_id: Correlation ID to wait for
            timeout: Timeout in seconds

        Returns:
            Response dict from agent

        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        pending = self._pending_commands.get(correlation_id)
        if not pending:
            raise ValueError(f"No pending command for correlation_id: {correlation_id}")

        return await asyncio.wait_for(pending["future"], timeout=timeout)
