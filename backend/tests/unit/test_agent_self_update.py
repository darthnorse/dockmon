"""
Unit tests for Agent Self-Update functionality.

Tests the agent self-update detection and execution in AgentUpdateExecutor.
This ensures agents can update themselves without recreating containers.

Architecture (v2.2.0+):
- UpdateExecutor routes to AgentUpdateExecutor for agent-based hosts
- AgentUpdateExecutor.execute() detects agent containers and routes to execute_self_update()
- Self-update uses binary swap instead of container recreation
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from updates.agent_executor import AgentUpdateExecutor
from updates.types import UpdateContext, UpdateResult
from database import DatabaseManager, ContainerUpdate, Agent
from agent.manager import AgentManager
from agent.command_executor import CommandStatus, CommandResult


@pytest.fixture
def mock_db():
    """Mock DatabaseManager"""
    db = MagicMock(spec=DatabaseManager)
    db.get_session = MagicMock()
    return db


@pytest.fixture
def mock_agent_manager():
    """Mock AgentManager"""
    manager = MagicMock(spec=AgentManager)
    manager.get_agent_for_host = MagicMock(return_value="agent-456")
    return manager


@pytest.fixture
def mock_command_executor():
    """Mock AgentCommandExecutor"""
    executor = MagicMock()
    executor.execute_command = AsyncMock()
    return executor


@pytest.fixture
def mock_monitor():
    """Mock DockerMonitor"""
    monitor = MagicMock()
    monitor.manager = None
    return monitor


@pytest.fixture
def agent_executor(mock_db, mock_agent_manager, mock_command_executor, mock_monitor):
    """Create AgentUpdateExecutor with mocked dependencies"""
    return AgentUpdateExecutor(
        db=mock_db,
        agent_manager=mock_agent_manager,
        agent_command_executor=mock_command_executor,
        monitor=mock_monitor,
    )


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


@pytest.fixture
def agent_context():
    """Create UpdateContext for agent container"""
    return UpdateContext(
        host_id="host-123",
        container_id="abc123def456",
        container_name="dockmon-agent",
        current_image="ghcr.io/darthnorse/dockmon-agent:2.2.0",
        new_image="ghcr.io/darthnorse/dockmon-agent:2.2.1",
        update_record_id=1,
    )


@pytest.fixture
def normal_context():
    """Create UpdateContext for normal container"""
    return UpdateContext(
        host_id="host-123",
        container_id="def456abc123",
        container_name="nginx",
        current_image="nginx:1.24",
        new_image="nginx:1.25",
        update_record_id=2,
    )


class TestAgentSelfUpdateDetection:
    """Test agent container detection logic in AgentUpdateExecutor"""

    @pytest.mark.asyncio
    async def test_detects_agent_container_by_official_image(
        self, agent_executor, agent_update_record, agent_context, mock_command_executor
    ):
        """Should detect agent by image name and route to self-update"""
        # Setup: Mock execute_self_update to verify it's called
        agent_executor.execute_self_update = AsyncMock(
            return_value=UpdateResult.success_result("abc123def456")
        )

        async def progress_callback(stage, percent, message):
            pass

        # Execute
        result = await agent_executor.execute(
            context=agent_context,
            progress_callback=progress_callback,
            update_record=agent_update_record,
        )

        # Verify: Should route to self-update
        agent_executor.execute_self_update.assert_called_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_detects_agent_container_by_custom_image(
        self, agent_executor, mock_command_executor
    ):
        """Should detect agent even with custom registry"""
        # Setup
        custom_context = UpdateContext(
            host_id="host-123",
            container_id="abc123def456",
            container_name="custom-agent",
            current_image="registry.example.com/my-dockmon-agent:v1",
            new_image="registry.example.com/my-dockmon-agent:v2",
            update_record_id=1,
        )
        custom_record = ContainerUpdate(
            container_id="host-123:abc123def456",
            current_image="registry.example.com/my-dockmon-agent:v1",
            latest_image="registry.example.com/my-dockmon-agent:v2",
            update_available=True
        )

        agent_executor.execute_self_update = AsyncMock(
            return_value=UpdateResult.success_result("abc123def456")
        )

        async def progress_callback(stage, percent, message):
            pass

        # Execute
        result = await agent_executor.execute(
            context=custom_context,
            progress_callback=progress_callback,
            update_record=custom_record,
        )

        # Verify: Should route to self-update
        agent_executor.execute_self_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_non_agent_containers(
        self, agent_executor, normal_update_record, normal_context, mock_command_executor
    ):
        """Should NOT route non-agent containers to self-update"""
        # Setup: Mock normal update flow
        agent_executor.execute_self_update = AsyncMock()

        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None
        )

        # Mock _wait_for_agent_update_completion
        agent_executor._wait_for_agent_update_completion = AsyncMock(return_value=True)
        agent_executor._get_container_info_by_name = AsyncMock(return_value={
            "id": "def456abc123",
            "state": "running"
        })
        agent_executor._update_database = AsyncMock()

        async def progress_callback(stage, percent, message):
            pass

        # Execute
        await agent_executor.execute(
            context=normal_context,
            progress_callback=progress_callback,
            update_record=normal_update_record,
        )

        # Verify: Should NOT call self-update
        agent_executor.execute_self_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_agent_for_host_returns_failure(
        self, agent_executor, agent_update_record, agent_context, mock_agent_manager
    ):
        """Should return failure if no agent for host"""
        # Setup: No agent for this host
        mock_agent_manager.get_agent_for_host.return_value = None

        async def progress_callback(stage, percent, message):
            pass

        # Execute
        result = await agent_executor.execute(
            context=agent_context,
            progress_callback=progress_callback,
            update_record=agent_update_record,
        )

        # Verify: Should fail
        assert result.success is False
        assert "No agent" in result.error_message


class TestAgentSelfUpdateExecution:
    """Test agent self-update execution logic"""

    @pytest.mark.asyncio
    async def test_sends_self_update_command_to_agent(
        self, agent_executor, agent_update_record, agent_context, mock_command_executor
    ):
        """Should send self_update command with correct parameters"""
        # Setup
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"status": "updating"},
            error=None
        )

        # Mock reconnection and version check
        agent_executor._wait_for_agent_reconnection = AsyncMock(return_value=True)
        agent_executor._get_agent_version = AsyncMock(return_value="2.2.1")

        # Mock database session for the update
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        agent_executor.db.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        agent_executor.db.get_session.return_value.__exit__ = MagicMock(return_value=False)

        async def progress_callback(stage, percent, message):
            pass

        # Execute
        result = await agent_executor.execute_self_update(
            context=agent_context,
            progress_callback=progress_callback,
            update_record=agent_update_record,
            agent_id="agent-456",
        )

        # Verify command was sent with correct format
        mock_command_executor.execute_command.assert_called_once()
        call_args = mock_command_executor.execute_command.call_args
        command = call_args[0][1]

        assert command["type"] == "command"
        assert command["command"] == "self_update"
        assert "payload" in command
        assert command["payload"]["image"] == "ghcr.io/darthnorse/dockmon-agent:2.2.1"
        assert command["payload"]["version"] == "2.2.1"

    @pytest.mark.asyncio
    async def test_waits_for_agent_reconnection_after_update(
        self, agent_executor, agent_update_record, agent_context, mock_command_executor
    ):
        """Should wait for agent to reconnect after self-update"""
        # Setup
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None
        )

        reconnection_called = False

        async def mock_wait_reconnection(agent_id, timeout):
            nonlocal reconnection_called
            reconnection_called = True
            return True

        agent_executor._wait_for_agent_reconnection = mock_wait_reconnection
        agent_executor._get_agent_version = AsyncMock(return_value="2.2.1")

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        agent_executor.db.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        agent_executor.db.get_session.return_value.__exit__ = MagicMock(return_value=False)

        async def progress_callback(stage, percent, message):
            pass

        # Execute
        await agent_executor.execute_self_update(
            context=agent_context,
            progress_callback=progress_callback,
            update_record=agent_update_record,
            agent_id="agent-456",
        )

        # Verify
        assert reconnection_called is True

    @pytest.mark.asyncio
    async def test_handles_command_send_failure(
        self, agent_executor, agent_update_record, agent_context, mock_command_executor
    ):
        """Should return failure if command send fails"""
        # Setup: Command fails
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.ERROR,
            success=False,
            response=None,
            error="Connection refused"
        )

        async def progress_callback(stage, percent, message):
            pass

        # Execute
        result = await agent_executor.execute_self_update(
            context=agent_context,
            progress_callback=progress_callback,
            update_record=agent_update_record,
            agent_id="agent-456",
        )

        # Verify
        assert result.success is False
        assert "Failed to send" in result.error_message

    @pytest.mark.asyncio
    async def test_timeout_if_agent_never_reconnects(
        self, agent_executor, agent_update_record, agent_context, mock_command_executor
    ):
        """Should return failure if agent doesn't reconnect"""
        # Setup
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None
        )

        # Agent never reconnects
        agent_executor._wait_for_agent_reconnection = AsyncMock(return_value=False)

        async def progress_callback(stage, percent, message):
            pass

        # Execute
        result = await agent_executor.execute_self_update(
            context=agent_context,
            progress_callback=progress_callback,
            update_record=agent_update_record,
            agent_id="agent-456",
        )

        # Verify
        assert result.success is False
        assert "did not reconnect" in result.error_message

    @pytest.mark.asyncio
    async def test_validates_new_version_on_reconnection(
        self, agent_executor, agent_update_record, agent_context, mock_command_executor
    ):
        """Should check agent version after reconnection"""
        # Setup
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None
        )

        agent_executor._wait_for_agent_reconnection = AsyncMock(return_value=True)

        version_checked = False

        async def mock_get_version(agent_id):
            nonlocal version_checked
            version_checked = True
            return "2.2.1"

        agent_executor._get_agent_version = mock_get_version

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        agent_executor.db.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        agent_executor.db.get_session.return_value.__exit__ = MagicMock(return_value=False)

        async def progress_callback(stage, percent, message):
            pass

        # Execute
        await agent_executor.execute_self_update(
            context=agent_context,
            progress_callback=progress_callback,
            update_record=agent_update_record,
            agent_id="agent-456",
        )

        # Verify
        assert version_checked is True


class TestAgentSelfUpdateEvents:
    """Test event emission during agent self-update"""

    @pytest.mark.asyncio
    async def test_progress_callback_called_with_stages(
        self, agent_executor, agent_update_record, agent_context, mock_command_executor
    ):
        """Should call progress callback with appropriate stages"""
        # Setup
        mock_command_executor.execute_command.return_value = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={},
            error=None
        )

        agent_executor._wait_for_agent_reconnection = AsyncMock(return_value=True)
        agent_executor._get_agent_version = AsyncMock(return_value="2.2.1")

        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        agent_executor.db.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        agent_executor.db.get_session.return_value.__exit__ = MagicMock(return_value=False)

        progress_stages = []

        async def progress_callback(stage, percent, message):
            progress_stages.append(stage)

        # Execute
        await agent_executor.execute_self_update(
            context=agent_context,
            progress_callback=progress_callback,
            update_record=agent_update_record,
            agent_id="agent-456",
        )

        # Verify: Should have progress stages
        assert len(progress_stages) > 0
        assert "initiating" in progress_stages
        assert "completed" in progress_stages


class TestVersionExtraction:
    """Test version extraction from image tags"""

    def test_extracts_version_from_standard_tag(self, agent_executor):
        """Should extract version from standard tag format"""
        version = agent_executor._extract_version_from_image(
            "ghcr.io/darthnorse/dockmon-agent:2.2.1"
        )
        assert version == "2.2.1"

    def test_returns_latest_for_no_tag(self, agent_executor):
        """Should return 'latest' when no tag specified"""
        version = agent_executor._extract_version_from_image(
            "ghcr.io/darthnorse/dockmon-agent"
        )
        assert version == "latest"

    def test_extracts_version_with_v_prefix(self, agent_executor):
        """Should extract version with v prefix"""
        version = agent_executor._extract_version_from_image(
            "registry.example.com/agent:v1.0.0"
        )
        assert version == "v1.0.0"
