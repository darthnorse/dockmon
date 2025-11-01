"""
Unit tests for AgentCommandExecutor.

Tests the command execution framework for sending commands to agents and
handling responses, timeouts, and errors.

TDD RED Phase: These tests define the interface and expected behavior.
All tests should FAIL initially since AgentCommandExecutor doesn't exist yet.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from agent.command_executor import AgentCommandExecutor, CommandResult, CommandStatus


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


class TestCommandExecution:
    """Test basic command execution"""

    @pytest.mark.asyncio
    async def test_execute_command_success(self, executor, mock_connection_manager):
        """Should execute command and return success result"""
        agent_id = "agent-123"
        command = {
            "type": "container_operation",
            "action": "start",
            "container_id": "abc123"
        }

        # Simulate agent responding after command is sent
        async def simulate_agent_response():
            await asyncio.sleep(0.05)  # Small delay
            # Get the correlation_id from the sent command
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            correlation_id = sent_command["correlation_id"]
            # Simulate agent response
            executor.handle_agent_response({
                "correlation_id": correlation_id,
                "success": True,
                "container_id": "abc123",
                "status": "running"
            })

        # Start response simulation in background
        asyncio.create_task(simulate_agent_response())

        result = await executor.execute_command(agent_id, command, timeout=5.0)

        assert result.status == CommandStatus.SUCCESS
        assert result.success is True
        assert result.response["container_id"] == "abc123"
        assert result.error is None

        # Verify command was sent with correlation ID
        mock_connection_manager.send_command.assert_called_once()
        sent_command = mock_connection_manager.send_command.call_args[0][1]
        assert "correlation_id" in sent_command
        assert sent_command["type"] == "container_operation"

    @pytest.mark.asyncio
    async def test_execute_command_with_correlation_id(self, executor, mock_connection_manager):
        """Should add correlation_id to commands for response tracking"""
        agent_id = "agent-123"
        command = {"type": "collect_stats"}

        # Simulate agent response
        async def simulate_response():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": True
            })

        asyncio.create_task(simulate_response())
        await executor.execute_command(agent_id, command)

        sent_command = mock_connection_manager.send_command.call_args[0][1]
        assert "correlation_id" in sent_command
        # Correlation ID should be UUID format (36 chars with hyphens)
        assert len(sent_command["correlation_id"]) == 36

    @pytest.mark.asyncio
    async def test_execute_multiple_commands_different_correlation_ids(self, executor, mock_connection_manager):
        """Should use different correlation IDs for concurrent commands"""
        agent_id = "agent-123"

        # Simulate responses for both commands
        async def simulate_responses():
            await asyncio.sleep(0.05)
            calls = mock_connection_manager.send_command.call_args_list
            for call in calls:
                sent_command = call[0][1]
                executor.handle_agent_response({
                    "correlation_id": sent_command["correlation_id"],
                    "success": True
                })

        asyncio.create_task(simulate_responses())

        # Send two commands concurrently
        results = await asyncio.gather(
            executor.execute_command(agent_id, {"type": "cmd1"}),
            executor.execute_command(agent_id, {"type": "cmd2"})
        )

        # Extract correlation IDs from the two calls
        calls = mock_connection_manager.send_command.call_args_list
        correlation_id_1 = calls[0][0][1]["correlation_id"]
        correlation_id_2 = calls[1][0][1]["correlation_id"]

        assert correlation_id_1 != correlation_id_2

    @pytest.mark.asyncio
    async def test_execute_command_agent_error_response(self, executor, mock_connection_manager):
        """Should handle error response from agent"""
        agent_id = "agent-123"
        command = {"type": "start", "container_id": "abc123"}

        # Simulate error response from agent
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
        assert result.error == "Container not found"
        assert result.response["success"] is False


class TestCommandTimeout:
    """Test command timeout handling"""

    @pytest.mark.asyncio
    async def test_execute_command_timeout(self, executor, mock_connection_manager):
        """Should timeout if agent doesn't respond within timeout period"""
        agent_id = "agent-123"
        command = {"type": "slow_operation"}

        # Don't send any response - will timeout naturally
        result = await executor.execute_command(agent_id, command, timeout=0.5)

        assert result.status == CommandStatus.TIMEOUT
        assert result.success is False
        assert "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_command_custom_timeout(self, executor):
        """Should respect custom timeout values"""
        agent_id = "agent-123"

        # This test verifies timeout parameter is passed correctly
        # Don't send responses - both will timeout naturally
        result_short = await executor.execute_command(agent_id, {"type": "cmd"}, timeout=0.1)
        result_long = await executor.execute_command(agent_id, {"type": "cmd"}, timeout=0.2)

        # Both should timeout
        assert result_short.status == CommandStatus.TIMEOUT
        assert result_long.status == CommandStatus.TIMEOUT


class TestAgentDisconnection:
    """Test handling of agent disconnection during command execution"""

    @pytest.mark.asyncio
    async def test_execute_command_agent_not_connected(self, executor, mock_connection_manager):
        """Should return error if agent is not connected"""
        agent_id = "agent-offline"
        command = {"type": "start"}

        # Mock agent not connected
        mock_connection_manager.is_connected.return_value = False

        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert "not connected" in result.error.lower()
        # Should not attempt to send command
        mock_connection_manager.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_command_send_fails(self, executor, mock_connection_manager):
        """Should handle WebSocket send failure"""
        agent_id = "agent-123"
        command = {"type": "start"}

        # Mock send_command returning False (send failed)
        mock_connection_manager.send_command.return_value = False

        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert "failed to send" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_command_agent_disconnects_during_wait(self, executor, mock_connection_manager):
        """Should handle agent disconnection while waiting for response"""
        agent_id = "agent-123"
        command = {"type": "long_operation"}

        # Simulate agent disconnecting (cancel the future)
        async def simulate_disconnect():
            await asyncio.sleep(0.05)
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            correlation_id = sent_command["correlation_id"]
            # Cancel the pending command's future
            pending = executor._pending_commands.get(correlation_id)
            if pending:
                pending["future"].set_exception(ConnectionError("Agent disconnected"))

        asyncio.create_task(simulate_disconnect())
        result = await executor.execute_command(agent_id, command)

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert "disconnected" in result.error.lower()


class TestResponseHandling:
    """Test response handling and correlation"""

    @pytest.mark.asyncio
    async def test_handle_agent_response_matches_correlation_id(self, executor):
        """Should match agent response to pending command by correlation_id"""
        correlation_id = "test-correlation-123"
        agent_id = "agent-123"

        # Create a pending command
        future = asyncio.Future()
        executor._pending_commands[correlation_id] = {
            "future": future,
            "agent_id": agent_id,
            "started_at": datetime.utcnow()
        }

        # Simulate agent response
        response = {
            "correlation_id": correlation_id,
            "success": True,
            "data": "test data"
        }

        executor.handle_agent_response(response)

        # Future should be resolved with response
        assert future.done()
        result = await future
        assert result["success"] is True
        assert result["data"] == "test data"

    def test_handle_agent_response_no_correlation_id(self, executor):
        """Should ignore responses without correlation_id"""
        response = {
            "success": True,
            "data": "unsolicited message"
        }

        # Should not raise exception
        executor.handle_agent_response(response)

    def test_handle_agent_response_unknown_correlation_id(self, executor):
        """Should ignore responses with unknown correlation_id"""
        response = {
            "correlation_id": "unknown-id",
            "success": True
        }

        # Should not raise exception (just log warning)
        executor.handle_agent_response(response)

    @pytest.mark.asyncio
    async def test_cleanup_expired_pending_commands(self, executor):
        """Should clean up pending commands that have exceeded max timeout"""
        # Create expired pending command (started 2 minutes ago)
        expired_correlation_id = "expired-123"
        expired_future = asyncio.Future()
        executor._pending_commands[expired_correlation_id] = {
            "future": expired_future,
            "agent_id": "agent-123",
            "started_at": datetime.utcnow() - timedelta(minutes=2)
        }

        # Create recent pending command (started 5 seconds ago)
        recent_correlation_id = "recent-456"
        recent_future = asyncio.Future()
        executor._pending_commands[recent_correlation_id] = {
            "future": recent_future,
            "agent_id": "agent-456",
            "started_at": datetime.utcnow() - timedelta(seconds=5)
        }

        # Cleanup with max_age of 60 seconds
        executor.cleanup_expired_pending_commands(max_age_seconds=60)

        # Expired command should be removed
        assert expired_correlation_id not in executor._pending_commands
        # Expired future should be cancelled
        assert expired_future.cancelled()

        # Recent command should still exist
        assert recent_correlation_id in executor._pending_commands
        assert not recent_future.cancelled()


class TestCommandResult:
    """Test CommandResult data class"""

    def test_command_result_success(self):
        """Should create success result"""
        result = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"container_id": "abc123", "status": "running"},
            error=None
        )

        assert result.status == CommandStatus.SUCCESS
        assert result.success is True
        assert result.error is None
        assert result.response["container_id"] == "abc123"

    def test_command_result_error(self):
        """Should create error result"""
        result = CommandResult(
            status=CommandStatus.ERROR,
            success=False,
            response=None,
            error="Container not found"
        )

        assert result.status == CommandStatus.ERROR
        assert result.success is False
        assert result.error == "Container not found"
        assert result.response is None

    def test_command_result_timeout(self):
        """Should create timeout result"""
        result = CommandResult(
            status=CommandStatus.TIMEOUT,
            success=False,
            response=None,
            error="Command timed out after 30 seconds"
        )

        assert result.status == CommandStatus.TIMEOUT
        assert result.success is False


class TestConcurrentCommands:
    """Test concurrent command execution to multiple agents"""

    @pytest.mark.asyncio
    async def test_execute_concurrent_commands_to_different_agents(self, executor, mock_connection_manager):
        """Should handle concurrent commands to different agents"""
        # Simulate responses for all commands
        async def simulate_all_responses():
            await asyncio.sleep(0.1)
            calls = mock_connection_manager.send_command.call_args_list
            for call in calls:
                sent_command = call[0][1]
                executor.handle_agent_response({
                    "correlation_id": sent_command["correlation_id"],
                    "success": True
                })

        asyncio.create_task(simulate_all_responses())

        # Execute commands to 3 different agents concurrently
        results = await asyncio.gather(
            executor.execute_command("agent-1", {"type": "cmd"}),
            executor.execute_command("agent-2", {"type": "cmd"}),
            executor.execute_command("agent-3", {"type": "cmd"})
        )

        # All should succeed
        assert all(r.status == CommandStatus.SUCCESS for r in results)
        assert mock_connection_manager.send_command.call_count == 3

    @pytest.mark.asyncio
    async def test_execute_concurrent_commands_to_same_agent(self, executor, mock_connection_manager):
        """Should handle concurrent commands to same agent"""
        agent_id = "agent-123"

        # Simulate responses for all commands
        async def simulate_all_responses():
            await asyncio.sleep(0.1)
            calls = mock_connection_manager.send_command.call_args_list
            for call in calls:
                sent_command = call[0][1]
                executor.handle_agent_response({
                    "correlation_id": sent_command["correlation_id"],
                    "success": True
                })

        asyncio.create_task(simulate_all_responses())

        # Execute multiple commands to same agent concurrently
        results = await asyncio.gather(
            executor.execute_command(agent_id, {"type": "start", "container": "c1"}),
            executor.execute_command(agent_id, {"type": "stop", "container": "c2"}),
            executor.execute_command(agent_id, {"type": "restart", "container": "c3"})
        )

        # All should succeed with unique correlation IDs
        assert all(r.status == CommandStatus.SUCCESS for r in results)
        assert mock_connection_manager.send_command.call_count == 3

        # Verify each command had unique correlation ID
        calls = mock_connection_manager.send_command.call_args_list
        correlation_ids = [call[0][1]["correlation_id"] for call in calls]
        assert len(set(correlation_ids)) == 3  # All unique


class TestCommandMetrics:
    """Test command execution metrics and monitoring"""

    @pytest.mark.asyncio
    async def test_command_result_includes_duration(self, executor, mock_connection_manager):
        """Should track command execution duration"""
        agent_id = "agent-123"

        # Simulate delayed response
        async def simulate_delayed_response():
            await asyncio.sleep(0.2)  # 200ms delay
            sent_command = mock_connection_manager.send_command.call_args[0][1]
            executor.handle_agent_response({
                "correlation_id": sent_command["correlation_id"],
                "success": True
            })

        asyncio.create_task(simulate_delayed_response())
        result = await executor.execute_command(agent_id, {"type": "cmd"})

        # Result should include execution duration
        assert hasattr(result, 'duration_seconds')
        assert result.duration_seconds >= 0.2  # At least 200ms
        assert result.duration_seconds < 1.0   # But not too long

    def test_get_pending_command_count(self, executor):
        """Should return count of pending commands"""
        # Initially zero
        assert executor.get_pending_command_count() == 0

        # Add pending commands
        executor._pending_commands["cmd-1"] = {
            "future": asyncio.Future(),
            "agent_id": "agent-1",
            "started_at": datetime.utcnow()
        }
        executor._pending_commands["cmd-2"] = {
            "future": asyncio.Future(),
            "agent_id": "agent-2",
            "started_at": datetime.utcnow()
        }

        assert executor.get_pending_command_count() == 2
