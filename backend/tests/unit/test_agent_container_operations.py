"""
Unit tests for AgentContainerOperations.

Tests the routing of container operations through agents instead of direct Docker socket access.
This is a key component of v2.2.0 that enables remote container management.

TDD RED Phase: These tests define the interface and expected behavior.
All tests should FAIL initially since AgentContainerOperations doesn't exist yet.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import HTTPException

from agent.container_operations import AgentContainerOperations
from agent.command_executor import CommandResult, CommandStatus


@pytest.fixture
def mock_command_executor():
    """Mock AgentCommandExecutor"""
    executor = MagicMock()
    executor.execute_command = AsyncMock()
    return executor


@pytest.fixture
def mock_db():
    """Mock DatabaseManager"""
    db = MagicMock()
    return db


@pytest.fixture
def mock_agent_manager():
    """Mock AgentManager"""
    manager = MagicMock()
    # Mock get_agent_for_host to return agent_id
    manager.get_agent_for_host = MagicMock(return_value="agent-123")
    return manager


@pytest.fixture
def container_ops(mock_command_executor, mock_db, mock_agent_manager):
    """Create AgentContainerOperations instance"""
    return AgentContainerOperations(
        command_executor=mock_command_executor,
        db=mock_db,
        agent_manager=mock_agent_manager
    )


class TestStartContainer:
    """Test container start operations via agent"""

    @pytest.mark.asyncio
    async def test_start_container_success(self, container_ops, mock_command_executor, mock_agent_manager):
        """Should send start command to agent and return success"""
        host_id = "host-123"
        container_id = "abc123"

        # Mock successful command execution
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"container_id": container_id, "status": "running"},
            error=None
        )

        result = await container_ops.start_container(host_id, container_id)

        assert result is True

        # Verify correct command sent with payload wrapper
        mock_command_executor.execute_command.assert_called_once()
        call_args = mock_command_executor.execute_command.call_args
        assert call_args[0][0] == "agent-123"  # agent_id
        command = call_args[0][1]
        assert command["type"] == "container_operation"
        # Parameters are inside payload (v2.2.0 agent protocol)
        assert command["payload"]["action"] == "start"
        assert command["payload"]["container_id"] == container_id

    @pytest.mark.asyncio
    async def test_start_container_agent_error(self, container_ops, mock_command_executor):
        """Should raise HTTPException if agent returns error"""
        host_id = "host-123"
        container_id = "abc123"

        # Mock agent error response
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.ERROR,
            success=False,
            response=None,
            error="Container not found"
        )

        with pytest.raises(HTTPException) as exc_info:
            await container_ops.start_container(host_id, container_id)

        assert exc_info.value.status_code == 500
        assert "Container not found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_start_container_timeout(self, container_ops, mock_command_executor):
        """Should raise HTTPException on command timeout"""
        host_id = "host-123"
        container_id = "abc123"

        # Mock timeout
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.TIMEOUT,
            success=False,
            response=None,
            error="Command timed out after 30 seconds"
        )

        with pytest.raises(HTTPException) as exc_info:
            await container_ops.start_container(host_id, container_id)

        assert exc_info.value.status_code == 504  # Gateway Timeout
        assert "timed out" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    async def test_start_container_no_agent_for_host(self, container_ops, mock_agent_manager):
        """Should raise HTTPException if no agent registered for host"""
        host_id = "host-without-agent"
        container_id = "abc123"

        # Mock no agent found
        mock_agent_manager.get_agent_for_host.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await container_ops.start_container(host_id, container_id)

        assert exc_info.value.status_code == 404
        assert "no agent" in str(exc_info.value.detail).lower()


class TestStopContainer:
    """Test container stop operations via agent"""

    @pytest.mark.asyncio
    async def test_stop_container_success(self, container_ops, mock_command_executor):
        """Should send stop command to agent and return success"""
        host_id = "host-123"
        container_id = "abc123"

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"container_id": container_id, "status": "stopped"},
            error=None
        )

        result = await container_ops.stop_container(host_id, container_id)

        assert result is True

        # Verify command includes timeout (inside payload)
        command = mock_command_executor.execute_command.call_args[0][1]
        assert command["payload"]["action"] == "stop"
        assert "timeout" in command["payload"]

    @pytest.mark.asyncio
    async def test_stop_container_custom_timeout(self, container_ops, mock_command_executor):
        """Should pass custom timeout to agent"""
        host_id = "host-123"
        container_id = "abc123"

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None
        )

        await container_ops.stop_container(host_id, container_id, timeout=30)

        # Verify custom timeout in command (inside payload)
        command = mock_command_executor.execute_command.call_args[0][1]
        assert command["payload"]["timeout"] == 30

    @pytest.mark.asyncio
    async def test_stop_container_safety_check_dockmon(self, container_ops, mock_command_executor):
        """Should prevent stopping DockMon itself"""
        host_id = "host-123"

        # Mock getting container info to check if it's DockMon
        with patch.object(container_ops, '_is_dockmon_container', return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                await container_ops.stop_container(host_id, "dockmon-container")

            assert exc_info.value.status_code == 403
            assert "cannot stop dockmon" in str(exc_info.value.detail).lower()

        # Should not have sent command to agent
        mock_command_executor.execute_command.assert_not_called()


class TestRestartContainer:
    """Test container restart operations via agent"""

    @pytest.mark.asyncio
    async def test_restart_container_success(self, container_ops, mock_command_executor):
        """Should send restart command to agent"""
        host_id = "host-123"
        container_id = "abc123"

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"container_id": container_id, "status": "running"},
            error=None
        )

        result = await container_ops.restart_container(host_id, container_id)

        assert result is True

        command = mock_command_executor.execute_command.call_args[0][1]
        assert command["payload"]["action"] == "restart"

    @pytest.mark.asyncio
    async def test_restart_container_safety_check_dockmon(self, container_ops):
        """Should prevent restarting DockMon itself"""
        host_id = "host-123"

        with patch.object(container_ops, '_is_dockmon_container', return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                await container_ops.restart_container(host_id, "dockmon-container")

            assert exc_info.value.status_code == 403
            assert "cannot restart dockmon" in str(exc_info.value.detail).lower()


class TestRemoveContainer:
    """Test container removal via agent"""

    @pytest.mark.asyncio
    async def test_remove_container_success(self, container_ops, mock_command_executor):
        """Should send remove command to agent"""
        host_id = "host-123"
        container_id = "abc123"

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"container_id": container_id, "removed": True},
            error=None
        )

        result = await container_ops.remove_container(host_id, container_id, force=False)

        assert result is True

        command = mock_command_executor.execute_command.call_args[0][1]
        assert command["payload"]["action"] == "remove"
        assert command["payload"]["force"] is False

    @pytest.mark.asyncio
    async def test_remove_container_with_force(self, container_ops, mock_command_executor):
        """Should pass force flag to agent"""
        host_id = "host-123"
        container_id = "abc123"

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None
        )

        await container_ops.remove_container(host_id, container_id, force=True)

        command = mock_command_executor.execute_command.call_args[0][1]
        assert command["payload"]["force"] is True

    @pytest.mark.asyncio
    async def test_remove_container_safety_check_dockmon(self, container_ops):
        """Should prevent removing DockMon itself"""
        host_id = "host-123"

        with patch.object(container_ops, '_is_dockmon_container', return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                await container_ops.remove_container(host_id, "dockmon-container")

            assert exc_info.value.status_code == 403


class TestGetContainerLogs:
    """Test container log retrieval via agent"""

    @pytest.mark.asyncio
    async def test_get_logs_success(self, container_ops, mock_command_executor):
        """Should retrieve container logs via agent"""
        host_id = "host-123"
        container_id = "abc123"
        expected_logs = "Container log line 1\nContainer log line 2\n"

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"logs": expected_logs},
            error=None
        )

        logs = await container_ops.get_container_logs(host_id, container_id, tail=100)

        assert logs == expected_logs

        command = mock_command_executor.execute_command.call_args[0][1]
        assert command["payload"]["action"] == "get_logs"
        assert command["payload"]["tail"] == 100

    @pytest.mark.asyncio
    async def test_get_logs_custom_tail(self, container_ops, mock_command_executor):
        """Should pass custom tail parameter"""
        host_id = "host-123"
        container_id = "abc123"

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"logs": ""},
            error=None
        )

        await container_ops.get_container_logs(host_id, container_id, tail=500)

        command = mock_command_executor.execute_command.call_args[0][1]
        assert command["payload"]["tail"] == 500


class TestInspectContainer:
    """Test container inspection via agent"""

    @pytest.mark.asyncio
    async def test_inspect_container_success(self, container_ops, mock_command_executor):
        """Should retrieve container details via agent"""
        host_id = "host-123"
        container_id = "abc123"
        expected_details = {
            "Id": container_id,
            "Name": "/my-container",
            "State": {"Status": "running"},
            "Config": {"Image": "nginx:latest"}
        }

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"container": expected_details},
            error=None
        )

        details = await container_ops.inspect_container(host_id, container_id)

        assert details == expected_details

        command = mock_command_executor.execute_command.call_args[0][1]
        assert command["payload"]["action"] == "inspect"


class TestHostToAgentMapping:
    """Test mapping between hosts and agents"""

    def test_get_agent_for_host_found(self, container_ops, mock_agent_manager):
        """Should retrieve agent_id for host"""
        host_id = "host-123"

        agent_id = container_ops._get_agent_for_host(host_id)

        assert agent_id == "agent-123"
        mock_agent_manager.get_agent_for_host.assert_called_once_with(host_id)

    def test_get_agent_for_host_not_found(self, container_ops, mock_agent_manager):
        """Should return None if no agent for host"""
        host_id = "host-without-agent"
        mock_agent_manager.get_agent_for_host.return_value = None

        agent_id = container_ops._get_agent_for_host(host_id)

        assert agent_id is None


class TestDockMonSafetyChecks:
    """Test safety checks to prevent operations on DockMon itself"""

    @pytest.mark.asyncio
    async def test_is_dockmon_container_by_name(self, container_ops, mock_command_executor):
        """Should detect DockMon by container name"""
        # Mock inspect command response
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"container": {"Name": "/dockmon"}},
            error=None
        )

        is_dockmon = await container_ops._is_dockmon_container("host-123", "some-container-id")

        assert is_dockmon is True

    @pytest.mark.asyncio
    async def test_is_dockmon_container_by_label(self, container_ops, mock_command_executor):
        """Should detect DockMon by label"""
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={
                "container": {
                    "Name": "/my-app",
                    "Config": {
                        "Labels": {"app": "dockmon"}
                    }
                }
            },
            error=None
        )

        is_dockmon = await container_ops._is_dockmon_container("host-123", "some-id")

        assert is_dockmon is True

    @pytest.mark.asyncio
    async def test_is_dockmon_container_negative(self, container_ops, mock_command_executor):
        """Should return False for non-DockMon containers"""
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={
                "container": {
                    "Name": "/nginx",
                    "Config": {"Labels": {}}
                }
            },
            error=None
        )

        is_dockmon = await container_ops._is_dockmon_container("host-123", "nginx-id")

        assert is_dockmon is False


class TestEventLogging:
    """Test event logging for container operations"""

    @pytest.mark.asyncio
    async def test_logs_successful_operation(self, container_ops, mock_command_executor, mock_db):
        """Should log successful container operations"""
        host_id = "host-123"
        container_id = "abc123"

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"container_id": container_id},
            error=None
        )

        # Mock event logger
        with patch.object(container_ops, '_log_event') as mock_log:
            await container_ops.start_container(host_id, container_id)

            mock_log.assert_called_once()
            call_args = mock_log.call_args[1]
            assert call_args["action"] == "start"
            assert call_args["success"] is True

    @pytest.mark.asyncio
    async def test_logs_failed_operation(self, container_ops, mock_command_executor):
        """Should log failed container operations"""
        host_id = "host-123"
        container_id = "abc123"

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.ERROR,
            success=False,
            response=None,
            error="Container not found"
        )

        with patch.object(container_ops, '_log_event') as mock_log:
            try:
                await container_ops.start_container(host_id, container_id)
            except HTTPException:
                pass

            mock_log.assert_called_once()
            call_args = mock_log.call_args[1]
            assert call_args["success"] is False
            assert "error" in call_args


class TestTimeoutConfiguration:
    """Test timeout configuration for different operations"""

    @pytest.mark.asyncio
    async def test_start_uses_default_timeout(self, container_ops, mock_command_executor):
        """Should use appropriate timeout for start operations"""
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None
        )

        await container_ops.start_container("host-123", "abc123")

        # Check timeout parameter in execute_command call
        call_kwargs = mock_command_executor.execute_command.call_args[1]
        assert "timeout" in call_kwargs
        assert call_kwargs["timeout"] == 30.0  # Default start timeout

    @pytest.mark.asyncio
    async def test_stop_uses_configurable_timeout(self, container_ops, mock_command_executor):
        """Should use configurable timeout for stop operations"""
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None
        )

        await container_ops.stop_container("host-123", "abc123", timeout=60)

        # Timeout should be passed through (inside payload)
        command = mock_command_executor.execute_command.call_args[0][1]
        assert command["payload"]["timeout"] == 60
