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
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Optional, Any
import time

logger = logging.getLogger(__name__)


class CommandStatus(Enum):
    """Status of command execution"""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class CommandErrorCode(Enum):
    """
    Detailed error codes for command execution failures.

    Classification:
    - RETRYABLE: NETWORK_ERROR, AGENT_DISCONNECTED, AGENT_NOT_CONNECTED, TIMEOUT, UNKNOWN_ERROR
    - NON_RETRYABLE: PERMISSION_DENIED, DOCKER_ERROR, AGENT_ERROR, INVALID_RESPONSE, CIRCUIT_OPEN
    """

    # Network/Connection errors (RETRYABLE)
    NETWORK_ERROR = "network_error"              # Connection issues, send failures
    AGENT_DISCONNECTED = "agent_disconnected"    # Agent went offline during execution
    AGENT_NOT_CONNECTED = "agent_not_connected"  # Agent not connected when command sent

    # Timeout errors (RETRYABLE)
    TIMEOUT = "timeout"                          # Command timeout

    # Docker/Permission errors (NON-RETRYABLE)
    PERMISSION_DENIED = "permission_denied"      # Docker permission issues
    DOCKER_ERROR = "docker_error"                # Docker daemon errors

    # Agent errors (NON-RETRYABLE)
    AGENT_ERROR = "agent_error"                  # Agent-side execution error
    INVALID_RESPONSE = "invalid_response"        # Malformed response from agent

    # Circuit breaker (NON-RETRYABLE)
    CIRCUIT_OPEN = "circuit_open"                # Circuit breaker is open

    # Unknown (RETRYABLE with caution)
    UNKNOWN_ERROR = "unknown_error"              # Catch-all


@dataclass
class CommandResult:
    """
    Result of command execution with enhanced error context.

    Includes detailed error codes, retry tracking, and execution metrics.
    """
    status: CommandStatus
    success: bool
    response: Optional[Dict[str, Any]]
    error: Optional[str]
    error_code: Optional[CommandErrorCode] = None  # Machine-readable error code
    duration_seconds: float = 0.0
    attempt: int = 1                               # Which attempt succeeded/failed (1-based)
    total_attempts: int = 1                        # Total attempts made
    retried: bool = False                          # Whether command was retried


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
        self._circuit_breakers: Dict[str, 'CircuitBreaker'] = {}  # Per-agent circuit breakers

    async def execute_command(
        self,
        agent_id: str,
        command: dict,
        timeout: float = 30.0,
        retry_policy: Optional['RetryPolicy'] = None
    ) -> CommandResult:
        """
        Execute a command on an agent and wait for response.

        Supports automatic retry with exponential backoff for transient failures.
        Integrates circuit breaker pattern to fail fast when agent is unhealthy.

        Args:
            agent_id: Agent UUID
            command: Command dict (e.g., {"type": "container_operation", "action": "start"})
            timeout: Timeout in seconds (default: 30)
            retry_policy: Optional retry policy (if None, no retry)

        Returns:
            CommandResult with status, response, error information, and retry context
        """
        # Check circuit breaker FIRST (before any execution or retry)
        circuit = self.get_circuit_breaker(agent_id)

        if not circuit.should_allow_request():
            # Circuit is OPEN - fail immediately
            logger.debug(f"Circuit breaker OPEN for agent {agent_id}, rejecting command")
            return CommandResult(
                status=CommandStatus.ERROR,
                success=False,
                response=None,
                error=f"Circuit breaker is open for agent {agent_id}",
                error_code=CommandErrorCode.CIRCUIT_OPEN,
                duration_seconds=0.0,
                attempt=1,
                total_attempts=1,
                retried=False
            )

        # Execute command (with or without retry)
        if retry_policy is None:
            result = await self._execute_command_once(agent_id, command, timeout, attempt=1, total_attempts=1)
        else:
            result = await self._execute_command_with_retry(agent_id, command, timeout, retry_policy)

        # Update circuit breaker based on result
        if result.success:
            circuit.record_success()
        else:
            circuit.record_failure()

        return result

    async def _execute_command_with_retry(
        self,
        agent_id: str,
        command: dict,
        timeout: float,
        retry_policy: 'RetryPolicy'
    ) -> CommandResult:
        """
        Execute command with retry logic.

        Extracted from execute_command for clarity.

        Args:
            agent_id: Agent UUID
            command: Command dict
            timeout: Timeout in seconds
            retry_policy: Retry policy configuration

        Returns:
            CommandResult with execution result
        """

        # Retry loop with exponential backoff
        last_result = None
        actual_attempts = 0

        for attempt in range(1, retry_policy.max_attempts + 1):
            actual_attempts = attempt

            # Execute command
            result = await self._execute_command_once(
                agent_id,
                command,
                timeout,
                attempt=attempt,
                total_attempts=attempt  # Will update if we continue
            )

            # Success - return immediately with actual attempts
            if result.success:
                result.total_attempts = actual_attempts
                result.retried = (attempt > 1)
                return result

            # Store result for potential final return
            last_result = result

            # Check if we should retry
            should_retry = (
                result.error_code is not None and
                result.error_code in retry_policy.retryable_error_codes and
                attempt < retry_policy.max_attempts
            )

            if not should_retry:
                # Error is not retryable or max attempts reached
                result.total_attempts = actual_attempts
                result.retried = (attempt > 1)
                return result

            # Calculate backoff delay
            delay = min(
                retry_policy.initial_delay * (retry_policy.backoff_multiplier ** (attempt - 1)),
                retry_policy.max_delay
            )

            # Add jitter to prevent thundering herd
            if retry_policy.jitter:
                delay *= (0.5 + random.random())  # 0.5x - 1.5x jitter

            logger.info(
                f"Retrying command for agent {agent_id} after {delay:.2f}s "
                f"(attempt {attempt}/{retry_policy.max_attempts}, error: {result.error_code.value})"
            )

            # Wait before retry
            await asyncio.sleep(delay)

        # Should never reach here, but return last result just in case
        if last_result:
            last_result.total_attempts = actual_attempts
            last_result.retried = True
            return last_result

        # Fallback (should never happen)
        return CommandResult(
            status=CommandStatus.ERROR,
            success=False,
            response=None,
            error="Retry loop completed without result",
            error_code=CommandErrorCode.UNKNOWN_ERROR,
            attempt=actual_attempts,
            total_attempts=actual_attempts,
            retried=True
        )

    async def _execute_command_once(
        self,
        agent_id: str,
        command: dict,
        timeout: float,
        attempt: int = 1,
        total_attempts: int = 1
    ) -> CommandResult:
        """
        Execute a command once (single attempt, no retry).

        This is the core execution logic extracted for retry support.

        Args:
            agent_id: Agent UUID
            command: Command dict
            timeout: Timeout in seconds
            attempt: Current attempt number (1-based)
            total_attempts: Total attempts that will be made

        Returns:
            CommandResult with execution result
        """
        start_time = time.time()

        # Check if agent is connected
        if not self.connection_manager.is_connected(agent_id):
            error_msg = f"Agent {agent_id} is not connected"
            return CommandResult(
                status=CommandStatus.ERROR,
                success=False,
                response=None,
                error=error_msg,
                error_code=CommandErrorCode.AGENT_NOT_CONNECTED,
                duration_seconds=time.time() - start_time,
                attempt=attempt,
                total_attempts=total_attempts,
                retried=False
            )

        # Generate correlation ID for this command
        # Use the SAME UUID for both 'id' and 'correlation_id' fields
        # - 'id': Required by agent's legacy protocol (echoed back in response as 'id')
        # - 'correlation_id': Used internally for request/response matching
        # The agent echoes 'id' back in response, and websocket_handler normalizes it to 'correlation_id'
        correlation_id = str(uuid.uuid4())

        # Add both fields with same UUID value
        command_with_ids = {
            **command,
            "id": correlation_id,           # Agent will echo this back as 'id'
            "correlation_id": correlation_id # Used for internal tracking
        }

        # Create future for response
        response_future = asyncio.Future()

        # Register pending command
        async with self._lock:
            self._pending_commands[correlation_id] = {
                "future": response_future,
                "agent_id": agent_id,
                "started_at": datetime.now(timezone.utc)
            }

        # Send command to agent
        send_start = time.time()
        send_success = await self.connection_manager.send_command(
            agent_id,
            command_with_ids
        )
        send_time = time.time() - send_start
        logger.info(f"Command sent to agent in {send_time:.3f}s (correlation_id: {correlation_id[:8]}...)")

        if not send_success:
            # Clean up pending command
            async with self._lock:
                self._pending_commands.pop(correlation_id, None)

            error_msg = f"Failed to send command to agent {agent_id}"
            return CommandResult(
                status=CommandStatus.ERROR,
                success=False,
                response=None,
                error=error_msg,
                error_code=CommandErrorCode.NETWORK_ERROR,
                duration_seconds=time.time() - start_time,
                attempt=attempt,
                total_attempts=total_attempts,
                retried=False
            )

        # Wait for response with timeout
        try:
            response = await asyncio.wait_for(response_future, timeout=timeout)

            duration = time.time() - start_time

            # Parse response
            # Check for error field first (both legacy and new protocol use this)
            if "error" in response and response["error"]:
                # Agent returned error
                error_msg = response["error"]
                error_code = self._classify_error_code(error_msg, response=response)

                return CommandResult(
                    status=CommandStatus.ERROR,
                    success=False,
                    response=response,
                    error=error_msg,
                    error_code=error_code,
                    duration_seconds=duration,
                    attempt=attempt,
                    total_attempts=total_attempts,
                    retried=False
                )

            # Validate response has required 'success' field (for non-legacy responses)
            # Legacy responses have 'payload' field, new protocol has 'success' field
            # If neither 'success' nor 'payload' is present, it's an invalid response
            if "success" not in response and "payload" not in response:
                error_msg = "Invalid response: missing 'success' or 'payload' field"
                return CommandResult(
                    status=CommandStatus.ERROR,
                    success=False,
                    response=response,
                    error=error_msg,
                    error_code=CommandErrorCode.INVALID_RESPONSE,
                    duration_seconds=duration,
                    attempt=attempt,
                    total_attempts=total_attempts,
                    retried=False
                )

            # No error - command succeeded
            # Legacy protocol returns {"type": "response", "id": "...", "payload": ...}
            # New protocol returns {"success": true, "data": ...}
            # Extract the actual response data from either format
            if "payload" in response:
                # Legacy protocol - payload contains the actual data
                response_data = response["payload"]
            elif "data" in response:
                # New protocol - data contains the actual data
                response_data = response["data"]
            else:
                # Fallback - return whole response
                response_data = response

            return CommandResult(
                status=CommandStatus.SUCCESS,
                success=True,
                response=response_data,  # Return the actual data, not the wrapper
                error=None,
                error_code=None,  # No error on success
                duration_seconds=duration,
                attempt=attempt,
                total_attempts=total_attempts,
                retried=False
            )

        except asyncio.TimeoutError as e:
            # Clean up pending command
            async with self._lock:
                self._pending_commands.pop(correlation_id, None)

            error_msg = f"Command timeout after {timeout} seconds"
            logger.warning(
                f"Command timeout after {timeout}s for agent {agent_id}, "
                f"correlation_id: {correlation_id}"
            )

            return CommandResult(
                status=CommandStatus.TIMEOUT,
                success=False,
                response=None,
                error=error_msg,
                error_code=CommandErrorCode.TIMEOUT,
                duration_seconds=timeout,
                attempt=attempt,
                total_attempts=total_attempts,
                retried=False
            )

        except ConnectionError as e:
            # Agent disconnected during wait
            async with self._lock:
                self._pending_commands.pop(correlation_id, None)

            error_msg = f"Agent disconnected: {str(e)}"
            return CommandResult(
                status=CommandStatus.ERROR,
                success=False,
                response=None,
                error=error_msg,
                error_code=CommandErrorCode.AGENT_DISCONNECTED,
                duration_seconds=time.time() - start_time,
                attempt=attempt,
                total_attempts=total_attempts,
                retried=False
            )

        except Exception as e:
            # Unexpected error
            async with self._lock:
                self._pending_commands.pop(correlation_id, None)

            error_msg = f"Unexpected error: {str(e)}"
            error_code = self._classify_error_code(error_msg, exception=e)

            logger.error(f"Unexpected error executing command: {e}", exc_info=True)

            return CommandResult(
                status=CommandStatus.ERROR,
                success=False,
                response=None,
                error=error_msg,
                error_code=error_code,
                duration_seconds=time.time() - start_time,
                attempt=attempt,
                total_attempts=total_attempts,
                retried=False
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
            started_at = pending.get("started_at")
            if started_at:
                wait_time = (datetime.now(timezone.utc) - started_at).total_seconds()
                logger.info(f"Response received after {wait_time:.3f}s (correlation_id: {correlation_id[:8]}...)")
            future.set_result(response)

    async def cleanup_expired_pending_commands(self, max_age_seconds: int = 300):
        """
        Clean up pending commands that have exceeded max age.

        This prevents memory leaks if agents disconnect without responding.
        Should be called periodically (e.g., every minute).

        Args:
            max_age_seconds: Maximum age in seconds (default: 5 minutes)
        """
        now = datetime.now(timezone.utc)
        max_age = timedelta(seconds=max_age_seconds)

        expired_ids = []

        # Use lock to safely iterate and collect expired IDs
        async with self._lock:
            for correlation_id, pending in self._pending_commands.items():
                age = now - pending["started_at"]
                if age > max_age:
                    expired_ids.append(correlation_id)

        # Cancel and remove expired commands (outside iteration to avoid dict size change during iteration)
        for correlation_id in expired_ids:
            async with self._lock:
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

    def get_circuit_breaker(self, agent_id: str) -> 'CircuitBreaker':
        """
        Get or create circuit breaker for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            CircuitBreaker: Circuit breaker instance for this agent
        """
        if agent_id not in self._circuit_breakers:
            self._circuit_breakers[agent_id] = CircuitBreaker(agent_id=agent_id)

        return self._circuit_breakers[agent_id]

    def is_error_retryable(self, error_code: CommandErrorCode) -> bool:
        """
        Check if an error code is retryable.

        Retryable errors: transient failures that might succeed on retry
        Non-retryable errors: permanent failures (permission, validation, etc.)

        Args:
            error_code: CommandErrorCode to check

        Returns:
            bool: True if error is retryable, False otherwise
        """
        retryable_codes = {
            CommandErrorCode.NETWORK_ERROR,
            CommandErrorCode.AGENT_DISCONNECTED,
            CommandErrorCode.AGENT_NOT_CONNECTED,
            CommandErrorCode.TIMEOUT,
            CommandErrorCode.UNKNOWN_ERROR
        }

        return error_code in retryable_codes

    def _classify_error_from_response(self, response: dict) -> CommandErrorCode:
        """
        Classify error code from agent response.

        Agent can provide 'error_type' field to indicate specific error types.

        Args:
            response: Response dict from agent

        Returns:
            CommandErrorCode: Classified error code
        """
        # Check if agent provided error_type
        error_type = response.get("error_type")

        if error_type == "permission_denied":
            return CommandErrorCode.PERMISSION_DENIED
        elif error_type == "docker_error":
            return CommandErrorCode.DOCKER_ERROR
        elif error_type == "invalid_response":
            return CommandErrorCode.INVALID_RESPONSE

        # Check if response is malformed (missing 'success' field)
        if "success" not in response:
            return CommandErrorCode.INVALID_RESPONSE

        # Default to AGENT_ERROR for agent-side failures
        return CommandErrorCode.AGENT_ERROR

    def _classify_error_code(
        self,
        error_message: str,
        exception: Optional[Exception] = None,
        response: Optional[dict] = None
    ) -> CommandErrorCode:
        """
        Classify error into appropriate CommandErrorCode.

        Args:
            error_message: Error message string
            exception: Exception that was raised (if any)
            response: Response from agent (if any)

        Returns:
            CommandErrorCode: Classified error code
        """
        # If we have a response, classify from response
        if response is not None:
            return self._classify_error_from_response(response)

        # Classify from exception type
        if exception:
            if isinstance(exception, asyncio.TimeoutError):
                return CommandErrorCode.TIMEOUT
            elif isinstance(exception, ConnectionError):
                return CommandErrorCode.AGENT_DISCONNECTED

        # Classify from error message
        error_lower = error_message.lower()

        if "not connected" in error_lower:
            return CommandErrorCode.AGENT_NOT_CONNECTED
        elif "failed to send" in error_lower or "send failed" in error_lower:
            return CommandErrorCode.NETWORK_ERROR
        elif "disconnected" in error_lower:
            return CommandErrorCode.AGENT_DISCONNECTED
        elif "timeout" in error_lower:
            return CommandErrorCode.TIMEOUT
        elif "permission" in error_lower:
            return CommandErrorCode.PERMISSION_DENIED
        elif "docker" in error_lower:
            return CommandErrorCode.DOCKER_ERROR

        # Default to UNKNOWN_ERROR
        return CommandErrorCode.UNKNOWN_ERROR

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


# Global singleton instance (lazy-initialized when connection_manager is ready)
_agent_command_executor_instance: Optional[AgentCommandExecutor] = None


def get_agent_command_executor() -> AgentCommandExecutor:
    """
    Get the global AgentCommandExecutor singleton instance.

    Lazy-initializes on first call with the agent_connection_manager.

    Returns:
        AgentCommandExecutor: Global instance
    """
    global _agent_command_executor_instance

    if _agent_command_executor_instance is None:
        from agent.connection_manager import agent_connection_manager
        _agent_command_executor_instance = AgentCommandExecutor(agent_connection_manager)
        logger.info("AgentCommandExecutor singleton initialized")

    return _agent_command_executor_instance


# =============================================================================
# Retry Logic and Circuit Breaker Pattern
# =============================================================================

@dataclass
class RetryPolicy:
    """
    Policy for retrying failed commands.

    Controls retry behavior including max attempts, backoff strategy, and
    which error codes should trigger retry.
    """
    max_attempts: int = 3                   # Maximum retry attempts
    initial_delay: float = 1.0              # Initial delay in seconds
    max_delay: float = 30.0                 # Maximum delay in seconds
    backoff_multiplier: float = 2.0         # Exponential backoff multiplier
    jitter: bool = True                     # Add randomization to prevent thundering herd

    # Which error codes should trigger retry (set in __post_init__)
    retryable_error_codes: list = None

    def __post_init__(self):
        """Initialize retryable_error_codes if not provided"""
        if self.retryable_error_codes is None:
            self.retryable_error_codes = [
                CommandErrorCode.NETWORK_ERROR,
                CommandErrorCode.AGENT_DISCONNECTED,
                CommandErrorCode.TIMEOUT,
                CommandErrorCode.UNKNOWN_ERROR
            ]


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"        # Normal operation
    OPEN = "open"           # Failing - reject all commands
    HALF_OPEN = "half_open" # Testing recovery - allow probe commands


class CircuitBreaker:
    """
    Circuit breaker for agent command execution.

    Prevents cascade failures by failing fast when an agent is consistently failing.

    State Machine:
    CLOSED → OPEN: After failure_threshold failures in window
    OPEN → HALF_OPEN: After timeout_seconds
    HALF_OPEN → CLOSED: After success_threshold successes
    HALF_OPEN → OPEN: After any failure
    """

    def __init__(
        self,
        agent_id: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        failure_window_seconds: int = 60,
        timeout_seconds: int = 30
    ):
        """
        Initialize circuit breaker for an agent.

        Args:
            agent_id: Agent ID this circuit breaker tracks
            failure_threshold: Failures to trigger OPEN
            success_threshold: Successes to trigger CLOSED (from HALF_OPEN)
            failure_window_seconds: Time window for failure tracking
            timeout_seconds: Time in OPEN before HALF_OPEN
        """
        self.agent_id = agent_id
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.failure_window_seconds = failure_window_seconds
        self.timeout_seconds = timeout_seconds

        # State tracking
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.opened_at: Optional[datetime] = None
        self.failure_timestamps: list = []  # Track failure times for window

    def record_success(self):
        """
        Record successful command execution.

        Updates state based on current circuit state:
        - CLOSED: Reset failure count (agent is healthy)
        - HALF_OPEN: Increment success count, may close circuit
        - OPEN: Should not happen (requests rejected)
        """
        if self.state == CircuitState.CLOSED:
            # Reset failure tracking on success
            self.failure_count = 0
            self.failure_timestamps.clear()

        elif self.state == CircuitState.HALF_OPEN:
            # Increment success count
            self.success_count += 1

            # Check if we should close the circuit
            if self.success_count >= self.success_threshold:
                self._transition_to_closed()
                logger.info(f"Circuit breaker for agent {self.agent_id} closed after {self.success_count} successes")

    def record_failure(self):
        """
        Record failed command execution.

        Updates state based on current circuit state:
        - CLOSED: Increment failure count, may open circuit
        - HALF_OPEN: Immediately reopen circuit (recovery failed)
        - OPEN: Should not happen (requests rejected)
        """
        now = datetime.now(timezone.utc)

        if self.state == CircuitState.CLOSED:
            # Track failure with timestamp
            self.failure_timestamps.append(now)
            self.last_failure_time = now

            # Remove failures outside the time window
            cutoff_time = now - timedelta(seconds=self.failure_window_seconds)
            self.failure_timestamps = [
                ts for ts in self.failure_timestamps
                if ts > cutoff_time
            ]

            # Update failure count
            self.failure_count = len(self.failure_timestamps)

            # Check if we should open the circuit
            if self.failure_count >= self.failure_threshold:
                self._transition_to_open()
                logger.warning(
                    f"Circuit breaker for agent {self.agent_id} opened after "
                    f"{self.failure_count} failures in {self.failure_window_seconds}s window"
                )

        elif self.state == CircuitState.HALF_OPEN:
            # Probe failed, reopen circuit
            self._transition_to_open()
            logger.warning(
                f"Circuit breaker for agent {self.agent_id} reopened after "
                f"failed probe in HALF_OPEN state"
            )

    def should_allow_request(self) -> bool:
        """
        Check if a request should be allowed through the circuit.

        Returns:
            bool: True if request should proceed, False if circuit is open
        """
        if self.state == CircuitState.CLOSED:
            # Normal operation
            return True

        elif self.state == CircuitState.OPEN:
            # Check if timeout has expired
            if self.opened_at:
                now = datetime.now(timezone.utc)
                time_open = (now - self.opened_at).total_seconds()

                if time_open >= self.timeout_seconds:
                    # Timeout expired, transition to HALF_OPEN
                    self._transition_to_half_open()
                    logger.info(
                        f"Circuit breaker for agent {self.agent_id} transitioned to HALF_OPEN "
                        f"after {time_open:.1f}s timeout"
                    )
                    return True  # Allow probe request

            # Still open, reject request
            return False

        elif self.state == CircuitState.HALF_OPEN:
            # Allow the probe request
            return True

        return False

    def _transition_to_open(self):
        """Transition circuit to OPEN state"""
        self.state = CircuitState.OPEN
        self.opened_at = datetime.now(timezone.utc)
        self.success_count = 0

    def _transition_to_half_open(self):
        """Transition circuit to HALF_OPEN state"""
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.opened_at = None

    def _transition_to_closed(self):
        """Transition circuit to CLOSED state"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_timestamps.clear()
        self.success_count = 0
        self.opened_at = None
