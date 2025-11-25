"""
Unit tests for Agent Self-Update functionality.

Tests the agent self-update detection and execution in UpdateExecutor.
This ensures agents can update themselves without recreating containers.

TDD RED Phase: These tests define expected behavior.
All tests should FAIL initially since feature doesn't exist yet.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, call
from datetime import datetime

from updates.update_executor import UpdateExecutor
from database import DatabaseManager, ContainerUpdate
from agent.manager import AgentManager
from agent.command_executor import CommandStatus, CommandResult


@pytest.fixture
def mock_db():
    """Mock DatabaseManager"""
    db = MagicMock(spec=DatabaseManager)
    db.get_session = MagicMock()
    return db


@pytest.fixture
def mock_monitor():
    """Mock DockerMonitor"""
    monitor = MagicMock()
    monitor.manager = None
    # Mock alert_evaluation_service with async methods
    monitor.alert_evaluation_service = MagicMock()
    monitor.alert_evaluation_service.handle_container_event = AsyncMock()
    return monitor


@pytest.fixture
def executor(mock_db, mock_monitor):
    """Create UpdateExecutor with mocked dependencies"""
    with patch('updates.update_executor.ImagePullProgress'):
        executor = UpdateExecutor(mock_db, mock_monitor)
        # Mock agent manager
        executor.agent_manager = MagicMock(spec=AgentManager)
        # Mock agent command executor
        executor.agent_command_executor = MagicMock()
        executor.agent_command_executor.execute_command = AsyncMock()
        return executor


@pytest.fixture
def agent_update_record():
    """Create a ContainerUpdate record for agent"""
    return ContainerUpdate(
        container_id="host-123:abc123def456",
        current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
        latest_image="ghcr.io/darthnorse/dockmon-agent:2.2.1",
        update_available=True
    )


@pytest.fixture
def normal_update_record():
    """Create a ContainerUpdate record for normal container"""
    return ContainerUpdate(
        container_id="host-123:def456abc123",
        current_image="nginx:1.24",
        latest_image="nginx:1.25",
        update_available=True
    )


class TestAgentSelfUpdateDetection:
    """Test agent container detection logic"""

    @pytest.mark.asyncio
    async def test_detects_agent_container_by_official_image(self, executor, agent_update_record):
        """Should detect agent by official image name"""
        # Setup
        host_id = "host-123"
        container_id = "abc123def456"
        executor.agent_manager.get_agent_for_host.return_value = "agent-456"

        # Mock _execute_agent_self_update to verify it's called
        executor._execute_agent_self_update = AsyncMock(return_value=True)

        # Create a mock container with proper name attribute
        mock_container = MagicMock()
        mock_container.name = "dockmon-agent"
        mock_container.labels = {}

        # Mock _get_docker_client to return a mock client
        mock_client = MagicMock()
        executor._get_docker_client = AsyncMock(return_value=mock_client)

        # Mock async_docker_call to return the mock container
        with patch('updates.update_executor.async_docker_call', AsyncMock(return_value=mock_container)):
            # Execute
            result = await executor.update_container(
                host_id, container_id, agent_update_record, force=False
            )

        # Verify: Should route to agent self-update
        executor._execute_agent_self_update.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_detects_agent_container_by_custom_image(self, executor):
        """Should detect agent even with custom registry"""
        # Setup
        custom_agent_record = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="registry.example.com/my-dockmon-agent:v1",
            latest_image="registry.example.com/my-dockmon-agent:v2",
            update_available=True
        )
        executor.agent_manager.get_agent_for_host.return_value = "agent-456"
        executor._execute_agent_self_update = AsyncMock(return_value=True)

        # Create a mock container with proper name attribute
        mock_container = MagicMock()
        mock_container.name = "custom-agent"
        mock_container.labels = {}

        # Mock _get_docker_client to return a mock client
        mock_client = MagicMock()
        executor._get_docker_client = AsyncMock(return_value=mock_client)

        # Mock async_docker_call to return the mock container
        with patch('updates.update_executor.async_docker_call', AsyncMock(return_value=mock_container)):
            # Execute
            result = await executor.update_container(
                "host-123", "abc123def456", custom_agent_record, force=False
            )

        # Verify
        executor._execute_agent_self_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_non_agent_containers(self, executor, normal_update_record):
        """Should NOT route non-agent containers to self-update"""
        # Setup
        executor._execute_agent_self_update = AsyncMock(return_value=True)
        executor._get_docker_client = AsyncMock(return_value=MagicMock())
        executor._get_container_info = AsyncMock(return_value={
            "name": "nginx",
            "id": "def456abc123"
        })

        # Mock the normal update flow to avoid errors
        with patch.object(executor, '_emit_update_started_event', AsyncMock()):
            with patch.object(executor, '_emit_update_failed_event', AsyncMock()):
                # This will fail in normal flow, but that's OK for this test
                try:
                    await executor.update_container(
                        "host-123", "def456abc123", normal_update_record, force=False
                    )
                except:
                    pass

        # Verify: Should NOT call agent self-update
        executor._execute_agent_self_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_requires_agent_for_host_to_route_to_self_update(self, executor, agent_update_record):
        """Should only route to self-update if agent exists for host"""
        # Setup: No agent for this host
        executor.agent_manager.get_agent_for_host.return_value = None
        executor._execute_agent_self_update = AsyncMock(return_value=True)
        executor._get_docker_client = AsyncMock(return_value=MagicMock())
        executor._get_container_info = AsyncMock(return_value={
            "name": "dockmon-agent",
            "id": "abc123def456"
        })

        # Mock normal flow
        with patch.object(executor, '_emit_update_started_event', AsyncMock()):
            with patch.object(executor, '_emit_update_failed_event', AsyncMock()):
                try:
                    await executor.update_container(
                        "host-123", "abc123def456", agent_update_record, force=False
                    )
                except:
                    pass

        # Verify: Should NOT route to self-update if no agent
        executor._execute_agent_self_update.assert_not_called()


class TestAgentSelfUpdateExecution:
    """Test agent self-update execution logic"""

    @pytest.mark.asyncio
    async def test_sends_self_update_command_to_agent(self, executor):
        """Should send self_update command with correct parameters"""
        # Setup
        agent_id = "agent-456"
        host_id = "host-123"
        container_id = "abc123def456"
        container_name = "dockmon-agent"
        update_record = ContainerUpdate(
            container_id=f"{host_id}:{container_id}",
            current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
            latest_image="ghcr.io/darthnorse/dockmon-agent:2.2.1",
            update_available=True
        )

        # Mock successful command execution
        executor.agent_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"message": "Update initiated"},
            error=None,
            duration_seconds=1.5
        )

        # Mock event emission
        executor._emit_update_started_event = AsyncMock()
        executor._emit_update_completed_event = AsyncMock()

        # Mock agent reconnection check
        with patch.object(executor, '_wait_for_agent_reconnection', AsyncMock(return_value=True)):
            # Execute
            result = await executor._execute_agent_self_update(
                agent_id, host_id, container_id, container_name, update_record
            )

        # Verify command was sent
        executor.agent_command_executor.execute_command.assert_called_once()
        call_args = executor.agent_command_executor.execute_command.call_args

        # Verify command structure
        assert call_args[0][0] == agent_id  # First arg: agent_id
        command = call_args[0][1]  # Second arg: command dict
        assert command["type"] == "command"
        assert command["payload"]["action"] == "self_update"
        assert "ghcr.io/darthnorse/dockmon-agent:2.2.1" in command["payload"]["params"]["image"]

        assert result is True

    @pytest.mark.asyncio
    async def test_waits_for_agent_reconnection_after_update(self, executor):
        """Should wait for agent to reconnect with new version"""
        # This test verifies the waiting logic exists
        agent_id = "agent-456"

        # Mock command execution
        executor.agent_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None,
            duration_seconds=1.0
        )

        executor._emit_update_started_event = AsyncMock()
        executor._emit_update_completed_event = AsyncMock()

        # Mock reconnection
        executor._wait_for_agent_reconnection = AsyncMock(return_value=True)

        update_record = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
            latest_image="ghcr.io/darthnorse/dockmon-agent:2.2.1"
        )

        # Execute
        await executor._execute_agent_self_update(
            agent_id, "host-123", "abc123def456", "dockmon-agent", update_record
        )

        # Verify reconnection check was called
        executor._wait_for_agent_reconnection.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_command_send_failure(self, executor):
        """Should handle failure to send command to agent"""
        # Setup
        agent_id = "agent-456"
        executor.agent_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.ERROR,
            success=False,
            response=None,
            error="Agent not connected",
            duration_seconds=0.1
        )

        executor._emit_update_started_event = AsyncMock()
        executor._emit_update_failed_event = AsyncMock()

        update_record = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
            latest_image="ghcr.io/darthnorse/dockmon-agent:2.2.1"
        )

        # Execute
        result = await executor._execute_agent_self_update(
            agent_id, "host-123", "abc123def456", "dockmon-agent", update_record
        )

        # Verify
        assert result is False
        executor._emit_update_failed_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_if_agent_never_reconnects(self, executor):
        """Should timeout if agent doesn't reconnect within timeframe"""
        # Setup
        agent_id = "agent-456"
        executor.agent_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None,
            duration_seconds=1.0
        )

        executor._emit_update_started_event = AsyncMock()
        executor._emit_update_failed_event = AsyncMock()

        # Mock timeout on reconnection
        executor._wait_for_agent_reconnection = AsyncMock(return_value=False)

        update_record = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
            latest_image="ghcr.io/darthnorse/dockmon-agent:2.2.1"
        )

        # Execute
        result = await executor._execute_agent_self_update(
            agent_id, "host-123", "abc123def456", "dockmon-agent", update_record
        )

        # Verify
        assert result is False
        executor._emit_update_failed_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_validates_new_version_on_reconnection(self, executor):
        """Should verify agent reconnects with expected new version"""
        # This test ensures version validation logic exists
        agent_id = "agent-456"
        executor.agent_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None,
            duration_seconds=1.0
        )

        executor._emit_update_started_event = AsyncMock()
        executor._emit_update_completed_event = AsyncMock()
        executor._wait_for_agent_reconnection = AsyncMock(return_value=True)

        # Mock getting agent version after reconnection
        executor._get_agent_version = AsyncMock(return_value="2.2.1")

        update_record = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
            latest_image="ghcr.io/darthnorse/dockmon-agent:2.2.1"
        )

        # Execute
        result = await executor._execute_agent_self_update(
            agent_id, "host-123", "abc123def456", "dockmon-agent", update_record
        )

        # Verify version check was called
        executor._get_agent_version.assert_called_once_with(agent_id)
        assert result is True


class TestAgentSelfUpdateEvents:
    """Test event emission during agent self-update"""

    @pytest.mark.asyncio
    async def test_emits_update_started_event(self, executor):
        """Should emit UPDATE_STARTED event at beginning"""
        agent_id = "agent-456"
        executor.agent_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None,
            duration_seconds=1.0
        )

        executor._emit_update_started_event = AsyncMock()
        executor._emit_update_completed_event = AsyncMock()
        executor._wait_for_agent_reconnection = AsyncMock(return_value=True)

        update_record = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
            latest_image="ghcr.io/darthnorse/dockmon-agent:2.2.1"
        )

        # Execute
        await executor._execute_agent_self_update(
            agent_id, "host-123", "abc123def456", "dockmon-agent", update_record
        )

        # Verify
        executor._emit_update_started_event.assert_called_once_with(
            "host-123", "abc123def456", "dockmon-agent", "ghcr.io/darthnorse/dockmon-agent:2.2.0", "ghcr.io/darthnorse/dockmon-agent:2.2.1"
        )

    @pytest.mark.asyncio
    async def test_emits_update_completed_on_success(self, executor):
        """Should emit UPDATE_COMPLETED event when successful"""
        agent_id = "agent-456"
        executor.agent_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None,
            duration_seconds=1.0
        )

        executor._emit_update_started_event = AsyncMock()
        executor._emit_update_completed_event = AsyncMock()
        executor._wait_for_agent_reconnection = AsyncMock(return_value=True)

        update_record = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
            latest_image="ghcr.io/darthnorse/dockmon-agent:2.2.1"
        )

        # Execute
        await executor._execute_agent_self_update(
            agent_id, "host-123", "abc123def456", "dockmon-agent", update_record
        )

        # Verify
        executor._emit_update_completed_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_emits_update_failed_on_error(self, executor):
        """Should emit UPDATE_FAILED event on failure"""
        agent_id = "agent-456"
        executor.agent_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.ERROR,
            success=False,
            response=None,
            error="Connection lost",
            duration_seconds=0.1
        )

        executor._emit_update_started_event = AsyncMock()
        executor._emit_update_failed_event = AsyncMock()

        update_record = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
            latest_image="ghcr.io/darthnorse/dockmon-agent:2.2.1"
        )

        # Execute
        await executor._execute_agent_self_update(
            agent_id, "host-123", "abc123def456", "dockmon-agent", update_record
        )

        # Verify
        executor._emit_update_failed_event.assert_called_once()


class TestAgentSelfUpdateDockMonProtection:
    """Test that DockMon self-protection happens before agent check"""

    @pytest.mark.asyncio
    async def test_blocks_dockmon_self_update_before_agent_check(self, executor):
        """Should block DockMon update before checking for agent"""
        # Setup: DockMon container with agent-like image (shouldn't happen, but test anyway)
        dockmon_update = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="dockmon:2.1.0",  # Not agent image
            latest_image="dockmon:2.2.0",
            update_available=True
        )

        executor._get_docker_client = AsyncMock(return_value=MagicMock())
        executor._get_container_info = AsyncMock(return_value={
            "name": "dockmon",  # DockMon container
            "id": "abc123def456"
        })
        executor._emit_update_failed_event = AsyncMock()
        executor._execute_agent_self_update = AsyncMock()

        # Mock getting container
        mock_container = MagicMock()
        mock_container.name = "dockmon"
        mock_container.labels = {}
        with patch('updates.update_executor.async_docker_call', AsyncMock(return_value=mock_container)):
            # Execute
            result = await executor.update_container(
                "host-123", "abc123def456", dockmon_update, force=False
            )

        # Verify: Should block and NOT route to agent self-update
        assert result is False
        executor._execute_agent_self_update.assert_not_called()
        executor._emit_update_failed_event.assert_called_once()
