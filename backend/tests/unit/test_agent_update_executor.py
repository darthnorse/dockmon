"""
Unit tests for AgentUpdateExecutor registry auth.

Tests verify:
- Registry credentials are looked up and passed to agent
- No credentials when callback is None
- No credentials when lookup returns None
- Correct credential format in command payload

Following TDD principles: RED -> GREEN -> REFACTOR
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from contextlib import contextmanager


class TestAgentUpdateExecutorRegistryAuth:
    """Tests for registry auth in AgentUpdateExecutor"""

    @pytest.fixture
    def mock_agent_manager(self):
        """Mock AgentManager that returns an agent ID"""
        manager = Mock()
        manager.get_agent_for_host = Mock(return_value="agent-123")
        return manager

    @pytest.fixture
    def mock_command_executor(self):
        """Mock command executor with successful result"""
        from agent.command_executor import CommandStatus, CommandResult

        executor = Mock()
        result = CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response={"message": "Update started"},
            error=None
        )
        executor.execute_command = AsyncMock(return_value=result)
        return executor

    @pytest.fixture
    def mock_db_manager(self, test_db):
        """Mock DatabaseManager"""
        mock_db = Mock()
        @contextmanager
        def get_session_cm():
            yield test_db
        mock_db.get_session = get_session_cm
        return mock_db

    @pytest.fixture
    def mock_monitor(self):
        """Mock DockerMonitor"""
        monitor = Mock()
        monitor.hosts = {}
        return monitor

    @pytest.fixture
    def update_context(self):
        """Create UpdateContext for testing"""
        from updates.types import UpdateContext

        return UpdateContext(
            host_id="test-host-uuid",
            container_id="abc123def456",
            container_name="test-container",
            current_image="nginx:1.24",
            new_image="nginx:1.25",
            update_record_id=1,
        )

    @pytest.fixture
    def update_record(self, test_db, test_host):
        """Create ContainerUpdate record for testing"""
        from database import ContainerUpdate
        from datetime import datetime, timezone

        update = ContainerUpdate(
            container_id=f"{test_host.id}:abc123def456",
            host_id=test_host.id,
            current_image="nginx:1.24",
            current_digest="sha256:abc123",
            latest_image="nginx:1.25",
            latest_digest="sha256:def456",
            update_available=True,
            last_checked_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db.add(update)
        test_db.commit()
        return update

    @pytest.mark.asyncio
    async def test_includes_registry_auth_when_credentials_found(
        self,
        mock_db_manager,
        mock_agent_manager,
        mock_command_executor,
        mock_monitor,
        update_context,
        update_record
    ):
        """Should include registry_auth in command payload when credentials found"""
        from updates.agent_executor import AgentUpdateExecutor

        # Mock credential lookup
        def mock_get_creds(image_name):
            return {"username": "myuser", "password": "mypass"}

        executor = AgentUpdateExecutor(
            db=mock_db_manager,
            agent_manager=mock_agent_manager,
            agent_command_executor=mock_command_executor,
            monitor=mock_monitor,
            get_registry_credentials=mock_get_creds,
        )

        # Mock wait for completion to succeed
        with patch.object(executor, '_wait_for_agent_update_completion', new_callable=AsyncMock) as mock_wait:
            mock_wait.return_value = True

            with patch.object(executor, '_get_container_info_by_name', new_callable=AsyncMock) as mock_get_info:
                mock_get_info.return_value = {"id": "newcontainer12"}

                with patch('updates.agent_executor.update_container_records_after_update'):
                    progress_callback = AsyncMock()

                    await executor.execute(update_context, progress_callback, update_record)

        # Verify command was called with registry_auth
        mock_command_executor.execute_command.assert_called_once()
        call_args = mock_command_executor.execute_command.call_args
        command = call_args[0][1]  # Second positional arg is the command

        assert command["command"] == "update_container"
        assert command["payload"]["registry_auth"] is not None
        assert command["payload"]["registry_auth"]["username"] == "myuser"
        assert command["payload"]["registry_auth"]["password"] == "mypass"

    @pytest.mark.asyncio
    async def test_no_registry_auth_when_credentials_not_found(
        self,
        mock_db_manager,
        mock_agent_manager,
        mock_command_executor,
        mock_monitor,
        update_context,
        update_record
    ):
        """Should have registry_auth=None when no credentials found"""
        from updates.agent_executor import AgentUpdateExecutor

        # Mock credential lookup returns None
        def mock_get_creds(image_name):
            return None

        executor = AgentUpdateExecutor(
            db=mock_db_manager,
            agent_manager=mock_agent_manager,
            agent_command_executor=mock_command_executor,
            monitor=mock_monitor,
            get_registry_credentials=mock_get_creds,
        )

        with patch.object(executor, '_wait_for_agent_update_completion', new_callable=AsyncMock) as mock_wait:
            mock_wait.return_value = True

            with patch.object(executor, '_get_container_info_by_name', new_callable=AsyncMock) as mock_get_info:
                mock_get_info.return_value = {"id": "newcontainer12"}

                with patch('updates.agent_executor.update_container_records_after_update'):
                    progress_callback = AsyncMock()

                    await executor.execute(update_context, progress_callback, update_record)

        # Verify command was called with registry_auth=None
        call_args = mock_command_executor.execute_command.call_args
        command = call_args[0][1]

        assert command["payload"]["registry_auth"] is None

    @pytest.mark.asyncio
    async def test_no_registry_auth_when_callback_is_none(
        self,
        mock_db_manager,
        mock_agent_manager,
        mock_command_executor,
        mock_monitor,
        update_context,
        update_record
    ):
        """Should have registry_auth=None when no callback provided"""
        from updates.agent_executor import AgentUpdateExecutor

        # No callback provided
        executor = AgentUpdateExecutor(
            db=mock_db_manager,
            agent_manager=mock_agent_manager,
            agent_command_executor=mock_command_executor,
            monitor=mock_monitor,
            get_registry_credentials=None,  # No callback
        )

        with patch.object(executor, '_wait_for_agent_update_completion', new_callable=AsyncMock) as mock_wait:
            mock_wait.return_value = True

            with patch.object(executor, '_get_container_info_by_name', new_callable=AsyncMock) as mock_get_info:
                mock_get_info.return_value = {"id": "newcontainer12"}

                with patch('updates.agent_executor.update_container_records_after_update'):
                    progress_callback = AsyncMock()

                    await executor.execute(update_context, progress_callback, update_record)

        # Verify command was called with registry_auth=None
        call_args = mock_command_executor.execute_command.call_args
        command = call_args[0][1]

        assert command["payload"]["registry_auth"] is None

    @pytest.mark.asyncio
    async def test_passes_correct_image_to_credential_lookup(
        self,
        mock_db_manager,
        mock_agent_manager,
        mock_command_executor,
        mock_monitor,
        update_context,
        update_record
    ):
        """Should pass new_image to credential lookup callback"""
        from updates.agent_executor import AgentUpdateExecutor

        # Track what image was passed
        images_looked_up = []

        def mock_get_creds(image_name):
            images_looked_up.append(image_name)
            return None

        executor = AgentUpdateExecutor(
            db=mock_db_manager,
            agent_manager=mock_agent_manager,
            agent_command_executor=mock_command_executor,
            monitor=mock_monitor,
            get_registry_credentials=mock_get_creds,
        )

        with patch.object(executor, '_wait_for_agent_update_completion', new_callable=AsyncMock) as mock_wait:
            mock_wait.return_value = True

            with patch.object(executor, '_get_container_info_by_name', new_callable=AsyncMock) as mock_get_info:
                mock_get_info.return_value = {"id": "newcontainer12"}

                with patch('updates.agent_executor.update_container_records_after_update'):
                    progress_callback = AsyncMock()

                    await executor.execute(update_context, progress_callback, update_record)

        # Verify correct image was looked up
        assert len(images_looked_up) == 1
        assert images_looked_up[0] == "nginx:1.25"  # new_image from update_context

    @pytest.mark.asyncio
    async def test_handles_credential_lookup_exception_gracefully(
        self,
        mock_db_manager,
        mock_agent_manager,
        mock_command_executor,
        mock_monitor,
        update_context,
        update_record
    ):
        """Should continue without auth if credential lookup raises exception"""
        from updates.agent_executor import AgentUpdateExecutor

        # Mock credential lookup raises exception
        def mock_get_creds(image_name):
            raise Exception("Database connection failed")

        executor = AgentUpdateExecutor(
            db=mock_db_manager,
            agent_manager=mock_agent_manager,
            agent_command_executor=mock_command_executor,
            monitor=mock_monitor,
            get_registry_credentials=mock_get_creds,
        )

        with patch.object(executor, '_wait_for_agent_update_completion', new_callable=AsyncMock) as mock_wait:
            mock_wait.return_value = True

            with patch.object(executor, '_get_container_info_by_name', new_callable=AsyncMock) as mock_get_info:
                mock_get_info.return_value = {"id": "newcontainer12"}

                with patch('updates.agent_executor.update_container_records_after_update'):
                    progress_callback = AsyncMock()

                    # Should not raise - handles exception gracefully
                    result = await executor.execute(update_context, progress_callback, update_record)

        # Update should still succeed (just without auth)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_skips_registry_auth_for_self_update(
        self,
        mock_db_manager,
        mock_agent_manager,
        mock_command_executor,
        mock_monitor,
        update_context,
        test_db,
        test_host
    ):
        """Should route to self-update flow which has different auth handling"""
        from updates.agent_executor import AgentUpdateExecutor
        from database import ContainerUpdate
        from datetime import datetime, timezone

        # Create update record for dockmon-agent
        update_record = ContainerUpdate(
            container_id=f"{test_host.id}:abc123def456",
            host_id=test_host.id,
            current_image="ghcr.io/dockmon-agent:v1",  # Agent image
            current_digest="sha256:abc123",
            latest_image="ghcr.io/dockmon-agent:v2",
            latest_digest="sha256:def456",
            update_available=True,
            last_checked_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db.add(update_record)
        test_db.commit()

        # Track calls to credential lookup
        cred_calls = []

        def mock_get_creds(image_name):
            cred_calls.append(image_name)
            return {"username": "user", "password": "pass"}

        executor = AgentUpdateExecutor(
            db=mock_db_manager,
            agent_manager=mock_agent_manager,
            agent_command_executor=mock_command_executor,
            monitor=mock_monitor,
            get_registry_credentials=mock_get_creds,
        )

        # Mock self-update to return success
        with patch.object(executor, 'execute_self_update', new_callable=AsyncMock) as mock_self_update:
            from updates.types import UpdateResult
            mock_self_update.return_value = UpdateResult.success_result("abc123def456")

            progress_callback = AsyncMock()
            result = await executor.execute(update_context, progress_callback, update_record)

        # Self-update should be called instead of normal flow
        mock_self_update.assert_called_once()

        # Normal credential lookup should NOT be called (self-update handles its own)
        assert len(cred_calls) == 0
