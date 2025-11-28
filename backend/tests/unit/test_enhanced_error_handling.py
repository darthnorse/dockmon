"""
Unit tests for Enhanced Error Handling in AgentCommandExecutor.

Tests error codes, retry logic, and circuit breaker pattern.

TDD RED Phase: These tests define the interface for enhanced error handling.
All tests in Phase 1 (Error Codes) should FAIL initially since CommandErrorCode doesn't exist yet.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from agent.command_executor import (
    AgentCommandExecutor,
    CommandResult,
    CommandStatus,
    CommandErrorCode,  # NEW - will fail until implemented
    RetryPolicy,       # NEW - will fail until implemented
    CircuitBreaker,    # NEW - will fail until implemented
    CircuitState       # NEW - will fail until implemented
)


@pytest.fixture
def mock_connection_manager():
    """Mock AgentConnectionManager"""
    manager = MagicMock()
    manager.send_command = AsyncMock(return_value=True)
    manager.is_connected = MagicMock(return_value=True)
    return manager


@pytest.fixture
def executor(mock_connection_manager):
    """Create AgentCommandExecutor with mocked connection manager"""
    return AgentCommandExecutor(mock_connection_manager)


# =============================================================================
# PHASE 1: Enhanced Error Codes Tests
# =============================================================================

class TestCommandErrorCode:
    """Test CommandErrorCode enum and classification"""

    def test_error_code_enum_exists(self):
        """Should have CommandErrorCode enum with all required codes"""
        # Test that enum exists and has expected values
        assert hasattr(CommandErrorCode, 'NETWORK_ERROR')
        assert hasattr(CommandErrorCode, 'AGENT_DISCONNECTED')
        assert hasattr(CommandErrorCode, 'AGENT_NOT_CONNECTED')
        assert hasattr(CommandErrorCode, 'TIMEOUT')
        assert hasattr(CommandErrorCode, 'PERMISSION_DENIED')
        assert hasattr(CommandErrorCode, 'DOCKER_ERROR')
        assert hasattr(CommandErrorCode, 'AGENT_ERROR')
        assert hasattr(CommandErrorCode, 'INVALID_RESPONSE')
        assert hasattr(CommandErrorCode, 'CIRCUIT_OPEN')
        assert hasattr(CommandErrorCode, 'UNKNOWN_ERROR')

    def test_error_code_values(self):
        """Should have correct string values for error codes"""
        assert CommandErrorCode.NETWORK_ERROR.value == "network_error"
        assert CommandErrorCode.AGENT_DISCONNECTED.value == "agent_disconnected"
        assert CommandErrorCode.AGENT_NOT_CONNECTED.value == "agent_not_connected"
        assert CommandErrorCode.TIMEOUT.value == "timeout"
        assert CommandErrorCode.PERMISSION_DENIED.value == "permission_denied"
        assert CommandErrorCode.DOCKER_ERROR.value == "docker_error"
        assert CommandErrorCode.AGENT_ERROR.value == "agent_error"
        assert CommandErrorCode.INVALID_RESPONSE.value == "invalid_response"
        assert CommandErrorCode.CIRCUIT_OPEN.value == "circuit_open"
        assert CommandErrorCode.UNKNOWN_ERROR.value == "unknown_error"


class TestEnhancedCommandResult:
    """Test enhanced CommandResult with error_code field"""

    def test_command_result_has_error_code_field(self):
        """Should have error_code field in CommandResult"""
        result = CommandResult(
            status=CommandStatus.ERROR,
            success=False,
            response=None,
            error="Test error",
            error_code=CommandErrorCode.NETWORK_ERROR
        )

        assert hasattr(result, 'error_code')
        assert result.error_code == CommandErrorCode.NETWORK_ERROR

    def test_command_result_has_attempt_fields(self):
        """Should have attempt tracking fields"""
        result = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"data": "test"},
            error=None,
            error_code=None,
            attempt=2,
            total_attempts=3,
            retried=True
        )

        assert hasattr(result, 'attempt')
        assert hasattr(result, 'total_attempts')
        assert hasattr(result, 'retried')
        assert result.attempt == 2
        assert result.total_attempts == 3
        assert result.retried is True

    def test_command_result_error_code_optional(self):
        """Should allow error_code to be None (backwards compatibility)"""
        result = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"data": "test"},
            error=None
        )

        # error_code should default to None
        assert result.error_code is None


class TestErrorCodeClassification:
    """Test error code assignment in various failure scenarios"""

    @pytest.mark.asyncio
    async def test_agent_not_connected_error_code(self, executor, mock_connection_manager):
        """Should set AGENT_NOT_CONNECTED error code when agent is not connected"""
        agent_id = "agent-offline"
        command = {"type": "test"}

        # Mock agent not connected
        mock_connection_manager.is_connected.return_value = False

        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert result.error_code == CommandErrorCode.AGENT_NOT_CONNECTED
        assert "not connected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_network_error_code_on_send_failure(self, executor, mock_connection_manager):
        """Should set NETWORK_ERROR error code when send_command fails"""
        agent_id = "agent-123"
        command = {"type": "test"}

        # Mock send_command returning False (send failed)
        mock_connection_manager.send_command.return_value = False

        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert result.error_code == CommandErrorCode.NETWORK_ERROR
        assert "failed to send" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout_error_code(self, executor, mock_connection_manager):
        """Should set TIMEOUT error code when command times out"""
        agent_id = "agent-123"
        command = {"type": "slow_operation"}

        # Don't send any response - will timeout
        result = await executor.execute_command(agent_id, command, timeout=0.1)

        assert result.status == CommandStatus.TIMEOUT
        assert result.success is False
        assert result.error_code == CommandErrorCode.TIMEOUT
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_agent_disconnected_error_code(self, executor, mock_connection_manager):
        """Should set AGENT_DISCONNECTED error code when agent disconnects during wait"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Simulate agent disconnecting (raise ConnectionError)
        async def simulate_disconnect():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            correlation_id = sent_command["correlation_id"]
            pending = executor._pending_commands.get(correlation_id)
            if pending:
                pending["future"].set_exception(ConnectionError("Agent disconnected"))

        asyncio.create_task(simulate_disconnect())
        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert result.error_code == CommandErrorCode.AGENT_DISCONNECTED
        assert "disconnected" in result.error.lower()

    @pytest.mark.asyncio
    async def test_agent_error_code_on_agent_failure(self, executor, mock_connection_manager):
        """Should set AGENT_ERROR error code when agent returns error response"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Simulate agent returning error
        async def simulate_error_response():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": False,
                "error": "Container not found"
            })

        asyncio.create_task(simulate_error_response())
        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert result.error_code == CommandErrorCode.AGENT_ERROR
        assert result.error == "Container not found"

    @pytest.mark.asyncio
    async def test_permission_denied_error_code(self, executor, mock_connection_manager):
        """Should set PERMISSION_DENIED error code for permission errors"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Simulate permission denied error from agent
        async def simulate_permission_error():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": False,
                "error": "Permission denied: cannot access Docker socket",
                "error_type": "permission_denied"
            })

        asyncio.create_task(simulate_permission_error())
        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert result.error_code == CommandErrorCode.PERMISSION_DENIED

    @pytest.mark.asyncio
    async def test_docker_error_code(self, executor, mock_connection_manager):
        """Should set DOCKER_ERROR error code for Docker daemon errors"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Simulate Docker error from agent
        async def simulate_docker_error():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": False,
                "error": "Docker daemon error: cannot connect to /var/run/docker.sock",
                "error_type": "docker_error"
            })

        asyncio.create_task(simulate_docker_error())
        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert result.error_code == CommandErrorCode.DOCKER_ERROR

    @pytest.mark.asyncio
    async def test_invalid_response_error_code(self, executor, mock_connection_manager):
        """Should set INVALID_RESPONSE error code for malformed agent responses"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Simulate malformed response (missing success field)
        async def simulate_invalid_response():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                # Missing 'success' field - invalid response
                "data": "incomplete"
            })

        asyncio.create_task(simulate_invalid_response())
        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert result.error_code == CommandErrorCode.INVALID_RESPONSE

    @pytest.mark.asyncio
    async def test_success_has_no_error_code(self, executor, mock_connection_manager):
        """Should have error_code=None on successful command"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Simulate successful response
        async def simulate_success_response():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": True,
                "data": "operation completed"
            })

        asyncio.create_task(simulate_success_response())
        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.SUCCESS
        assert result.success is True
        assert result.error_code is None
        assert result.error is None


class TestErrorCodeRetryability:
    """Test classification of errors as retryable vs non-retryable"""

    def test_is_retryable_for_network_errors(self, executor):
        """Should classify network errors as retryable"""
        assert executor.is_error_retryable(CommandErrorCode.NETWORK_ERROR) is True
        assert executor.is_error_retryable(CommandErrorCode.AGENT_DISCONNECTED) is True
        assert executor.is_error_retryable(CommandErrorCode.AGENT_NOT_CONNECTED) is True

    def test_is_retryable_for_timeout(self, executor):
        """Should classify timeout as retryable"""
        assert executor.is_error_retryable(CommandErrorCode.TIMEOUT) is True

    def test_is_not_retryable_for_permission_errors(self, executor):
        """Should classify permission errors as non-retryable"""
        assert executor.is_error_retryable(CommandErrorCode.PERMISSION_DENIED) is False

    def test_is_not_retryable_for_docker_errors(self, executor):
        """Should classify Docker errors as non-retryable"""
        assert executor.is_error_retryable(CommandErrorCode.DOCKER_ERROR) is False

    def test_is_not_retryable_for_agent_errors(self, executor):
        """Should classify agent errors as non-retryable"""
        assert executor.is_error_retryable(CommandErrorCode.AGENT_ERROR) is False

    def test_is_not_retryable_for_invalid_response(self, executor):
        """Should classify invalid response as non-retryable"""
        assert executor.is_error_retryable(CommandErrorCode.INVALID_RESPONSE) is False

    def test_is_not_retryable_for_circuit_open(self, executor):
        """Should classify circuit open as non-retryable"""
        assert executor.is_error_retryable(CommandErrorCode.CIRCUIT_OPEN) is False

    def test_is_retryable_for_unknown_error(self, executor):
        """Should classify unknown error as retryable (with caution)"""
        assert executor.is_error_retryable(CommandErrorCode.UNKNOWN_ERROR) is True


# =============================================================================
# PHASE 2: Retry Logic Tests (will be implemented after Phase 1)
# =============================================================================

class TestRetryPolicy:
    """Test RetryPolicy configuration"""

    def test_retry_policy_defaults(self):
        """Should have sensible default values"""
        policy = RetryPolicy()

        assert policy.max_attempts == 3
        assert policy.initial_delay == 1.0
        assert policy.max_delay == 30.0
        assert policy.backoff_multiplier == 2.0
        assert policy.jitter is True

    def test_retry_policy_custom_values(self):
        """Should allow custom configuration"""
        policy = RetryPolicy(
            max_attempts=5,
            initial_delay=2.0,
            max_delay=60.0,
            backoff_multiplier=3.0,
            jitter=False
        )

        assert policy.max_attempts == 5
        assert policy.initial_delay == 2.0
        assert policy.max_delay == 60.0
        assert policy.backoff_multiplier == 3.0
        assert policy.jitter is False

    def test_retry_policy_retryable_error_codes(self):
        """Should have default retryable error codes"""
        policy = RetryPolicy()

        assert CommandErrorCode.NETWORK_ERROR in policy.retryable_error_codes
        assert CommandErrorCode.AGENT_DISCONNECTED in policy.retryable_error_codes
        assert CommandErrorCode.TIMEOUT in policy.retryable_error_codes
        assert CommandErrorCode.UNKNOWN_ERROR in policy.retryable_error_codes

        # Non-retryable should not be in list
        assert CommandErrorCode.PERMISSION_DENIED not in policy.retryable_error_codes
        assert CommandErrorCode.AGENT_ERROR not in policy.retryable_error_codes


class TestRetryLogic:
    """Test command retry with exponential backoff"""

    @pytest.mark.asyncio
    async def test_retry_transient_failure(self, executor, mock_connection_manager):
        """Should retry command after transient failure"""
        agent_id = "agent-123"
        command = {"type": "operation"}
        retry_policy = RetryPolicy(max_attempts=3, initial_delay=0.1, jitter=False)

        call_count = 0

        # First attempt fails, second succeeds
        async def mock_send_with_retry(agent_id, cmd):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First attempt - send succeeds but agent doesn't respond (timeout)
                return True
            else:
                # Second attempt - send succeeds and agent responds
                asyncio.create_task(send_success_response())
                return True

        async def send_success_response():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": True,
                "data": "completed"
            })

        mock_connection_manager.send_command = AsyncMock(side_effect=mock_send_with_retry)

        result = await executor.execute_command(
            agent_id,
            command,
            timeout=0.2,
            retry_policy=retry_policy
        )

        # Should succeed on second attempt
        assert result.status == CommandStatus.SUCCESS
        assert result.success is True
        assert result.attempt == 2
        assert result.total_attempts == 2
        assert result.retried is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_exponential_backoff(self, executor, mock_connection_manager):
        """Should use exponential backoff between retries"""
        agent_id = "agent-123"
        command = {"type": "operation"}
        retry_policy = RetryPolicy(
            max_attempts=4,
            initial_delay=0.1,
            backoff_multiplier=2.0,
            jitter=False
        )

        retry_delays = []
        last_attempt_time = None

        async def mock_send_always_fail(agent_id, cmd):
            nonlocal last_attempt_time
            now = asyncio.get_running_loop().time()

            if last_attempt_time is not None:
                retry_delays.append(now - last_attempt_time)

            last_attempt_time = now
            return False  # Always fail

        mock_connection_manager.send_command = AsyncMock(side_effect=mock_send_always_fail)

        result = await executor.execute_command(
            agent_id,
            command,
            retry_policy=retry_policy
        )

        # Should have tried 4 times (initial + 3 retries)
        assert result.total_attempts == 4

        # Check exponential backoff delays
        # Attempt 1: immediate
        # Attempt 2: 0.1s delay
        # Attempt 3: 0.2s delay
        # Attempt 4: 0.4s delay
        assert len(retry_delays) == 3
        assert 0.08 <= retry_delays[0] <= 0.12  # ~0.1s with tolerance
        assert 0.18 <= retry_delays[1] <= 0.22  # ~0.2s with tolerance
        assert 0.38 <= retry_delays[2] <= 0.42  # ~0.4s with tolerance

    @pytest.mark.asyncio
    async def test_no_retry_for_non_retryable_error(self, executor, mock_connection_manager):
        """Should not retry for non-retryable errors"""
        agent_id = "agent-123"
        command = {"type": "operation"}
        retry_policy = RetryPolicy(max_attempts=3)

        # Simulate permission denied error (non-retryable)
        async def simulate_permission_error():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": False,
                "error": "Permission denied",
                "error_type": "permission_denied"
            })

        asyncio.create_task(simulate_permission_error())

        result = await executor.execute_command(
            agent_id,
            command,
            retry_policy=retry_policy
        )

        # Should fail immediately without retry
        assert result.status == CommandStatus.ERROR
        assert result.error_code == CommandErrorCode.PERMISSION_DENIED
        assert result.attempt == 1
        assert result.total_attempts == 1
        assert result.retried is False
        # send_command should be called only once
        assert mock_connection_manager.send_command.call_count == 1

    @pytest.mark.asyncio
    async def test_max_attempts_enforced(self, executor, mock_connection_manager):
        """Should not exceed max_attempts"""
        agent_id = "agent-123"
        command = {"type": "operation"}
        retry_policy = RetryPolicy(max_attempts=2, initial_delay=0.05, jitter=False)

        # Always return network error (retryable)
        mock_connection_manager.send_command.return_value = False

        result = await executor.execute_command(
            agent_id,
            command,
            retry_policy=retry_policy
        )

        # Should try exactly 2 times
        assert result.total_attempts == 2
        assert result.retried is True
        assert mock_connection_manager.send_command.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_without_policy_no_retry(self, executor, mock_connection_manager):
        """Should not retry if retry_policy is None"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Send fails (retryable error)
        mock_connection_manager.send_command.return_value = False

        result = await executor.execute_command(
            agent_id,
            command,
            retry_policy=None  # No retry policy
        )

        # Should fail immediately without retry
        assert result.status == CommandStatus.ERROR
        assert result.attempt == 1
        assert result.total_attempts == 1
        assert result.retried is False
        assert mock_connection_manager.send_command.call_count == 1


# =============================================================================
# PHASE 3: Circuit Breaker Tests (will be implemented after Phase 2)
# =============================================================================

class TestCircuitBreakerStates:
    """Test circuit breaker state machine"""

    def test_circuit_breaker_initial_state(self):
        """Should start in CLOSED state"""
        cb = CircuitBreaker(agent_id="agent-123")

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0

    def test_circuit_breaker_closed_to_open(self):
        """Should transition from CLOSED to OPEN after failure threshold"""
        cb = CircuitBreaker(agent_id="agent-123", failure_threshold=3)

        # Record 3 failures
        for _ in range(3):
            cb.record_failure()

        # Should now be OPEN
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3
        assert cb.opened_at is not None

    def test_circuit_breaker_open_to_half_open(self):
        """Should transition from OPEN to HALF_OPEN after timeout"""
        cb = CircuitBreaker(agent_id="agent-123", timeout_seconds=0.1)

        # Force OPEN state
        cb.state = CircuitState.OPEN
        cb.opened_at = datetime.now(timezone.utc)

        # Wait for timeout
        import time
        time.sleep(0.15)

        # Check if should transition (should_allow_request transitions to HALF_OPEN internally)
        assert cb.should_allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_circuit_breaker_half_open_to_closed(self):
        """Should transition from HALF_OPEN to CLOSED after success threshold"""
        cb = CircuitBreaker(agent_id="agent-123", success_threshold=2)

        # Force HALF_OPEN state
        cb.state = CircuitState.HALF_OPEN
        cb.success_count = 0

        # Record 2 successes
        cb.record_success()
        cb.record_success()

        # Should now be CLOSED
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_circuit_breaker_half_open_to_open(self):
        """Should transition from HALF_OPEN to OPEN on any failure"""
        cb = CircuitBreaker(agent_id="agent-123")

        # Force HALF_OPEN state
        cb.state = CircuitState.HALF_OPEN

        # Single failure should reopen circuit
        cb.record_failure()

        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration with AgentCommandExecutor"""

    @pytest.mark.asyncio
    async def test_circuit_open_rejects_commands(self, executor, mock_connection_manager):
        """Should reject commands immediately when circuit is OPEN"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Force circuit to OPEN state
        circuit = executor.get_circuit_breaker(agent_id)
        circuit.state = CircuitState.OPEN
        circuit.opened_at = datetime.now(timezone.utc)

        result = await executor.execute_command(agent_id, command)

        # Should fail immediately with CIRCUIT_OPEN error
        assert result.status == CommandStatus.ERROR
        assert result.error_code == CommandErrorCode.CIRCUIT_OPEN
        assert result.success is False
        # Should NOT attempt to send command
        mock_connection_manager.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_repeated_failures_open_circuit(self, executor, mock_connection_manager):
        """Should open circuit after repeated failures"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Configure circuit with low threshold
        circuit = executor.get_circuit_breaker(agent_id)
        circuit.failure_threshold = 3

        # All commands fail (send returns False = network error)
        mock_connection_manager.send_command.return_value = False

        # Send 3 failing commands
        for _ in range(3):
            await executor.execute_command(agent_id, command)

        # Circuit should now be OPEN
        assert circuit.state == CircuitState.OPEN

        # Next command should fail immediately
        result = await executor.execute_command(agent_id, command)
        assert result.error_code == CommandErrorCode.CIRCUIT_OPEN

    @pytest.mark.asyncio
    async def test_circuit_half_open_allows_probe(self, executor, mock_connection_manager):
        """Should allow probe request in HALF_OPEN state"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Force circuit to HALF_OPEN
        circuit = executor.get_circuit_breaker(agent_id)
        circuit.state = CircuitState.HALF_OPEN

        # Simulate successful response
        async def simulate_success():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": True,
                "data": "probe successful"
            })

        asyncio.create_task(simulate_success())

        result = await executor.execute_command(agent_id, command)

        # Should succeed
        assert result.status == CommandStatus.SUCCESS
        # Command should have been sent
        mock_connection_manager.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_recovery_after_successes(self, executor, mock_connection_manager):
        """Should recover (OPEN → HALF_OPEN → CLOSED) after successes"""
        agent_id = "agent-123"
        command = {"type": "operation"}

        # Configure circuit
        circuit = executor.get_circuit_breaker(agent_id)
        circuit.failure_threshold = 2
        circuit.success_threshold = 2
        circuit.timeout_seconds = 0.1

        # Cause circuit to open (2 failures)
        mock_connection_manager.send_command.return_value = False
        await executor.execute_command(agent_id, command)
        await executor.execute_command(agent_id, command)

        assert circuit.state == CircuitState.OPEN

        # Wait for timeout to transition to HALF_OPEN
        import time
        time.sleep(0.15)

        # Next request should transition to HALF_OPEN
        # Send 2 successful commands
        async def simulate_success():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": True,
                "data": "success"
            })

        mock_connection_manager.send_command.return_value = True

        asyncio.create_task(simulate_success())
        result1 = await executor.execute_command(agent_id, command)

        asyncio.create_task(simulate_success())
        result2 = await executor.execute_command(agent_id, command)

        # Circuit should now be CLOSED
        assert circuit.state == CircuitState.CLOSED
        assert result1.status == CommandStatus.SUCCESS
        assert result2.status == CommandStatus.SUCCESS

    def test_circuit_breaker_per_agent(self, executor):
        """Should maintain separate circuit breaker per agent"""
        agent1_circuit = executor.get_circuit_breaker("agent-1")
        agent2_circuit = executor.get_circuit_breaker("agent-2")

        # Should be different instances
        assert agent1_circuit is not agent2_circuit

        # Modify one, other should be unaffected
        agent1_circuit.state = CircuitState.OPEN
        assert agent2_circuit.state == CircuitState.CLOSED
