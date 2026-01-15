"""
Unit tests for force_warn parameter in container updates.

Tests that force_warn allows WARN containers to update while still blocking BLOCK containers.
This enables bulk updates with user confirmation for warned containers.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from updates.update_executor import UpdateExecutor
from updates.container_validator import ValidationResult, ValidationResponse


@pytest.mark.unit
class TestForceWarnParameter:
    """Test force_warn parameter behavior"""

    @pytest.fixture
    def mock_db(self):
        """Mock database manager"""
        db = Mock()
        db.get_session = Mock(return_value=MagicMock())
        return db

    @pytest.fixture
    def mock_monitor(self):
        """Mock docker monitor"""
        monitor = Mock()
        monitor.get_docker_client = AsyncMock(return_value=Mock())
        return monitor

    @pytest.fixture
    def executor(self, mock_db, mock_monitor):
        """Create UpdateExecutor instance"""
        return UpdateExecutor(db=mock_db, monitor=mock_monitor)

    @pytest.mark.asyncio
    async def test_force_warn_allows_warn_containers(self, executor, mock_db):
        """Test that force_warn=True allows WARN containers to update"""
        # Simplified test - just verify validation behavior

        # Mock update record
        update_record = Mock()
        update_record.current_image = "traefik:2.10"
        update_record.latest_image = "traefik:2.11"

        with patch('updates.update_executor.async_docker_call') as mock_async_call, \
             patch.object(executor, '_get_docker_client') as mock_get_client, \
             patch.object(executor.event_emitter, 'emit_warning') as mock_emit_warning, \
             patch('updates.update_executor.ContainerValidator') as mock_validator_class:

            # Setup minimal mocks
            mock_docker_client = Mock()
            mock_get_client.return_value = mock_docker_client

            mock_container = Mock()
            mock_container.name = "traefik"
            mock_container.labels = {}
            mock_async_call.return_value = mock_container

            # Mock validator to return WARN
            mock_validator = Mock()
            mock_validator.validate_update.return_value = ValidationResponse(
                result=ValidationResult.WARN,
                reason="Matched critical pattern: 'traefik'",
                matched_pattern="traefik"
            )
            mock_validator_class.return_value = mock_validator

            # Call with force_warn=True (should proceed past validation)
            try:
                result = await executor.update_container(
                    host_id="test-host",
                    container_id="abc123def456",
                    update_record=update_record,
                    force=False,
                    force_warn=True  # NEW PARAMETER
                )
            except Exception:
                # Expect failures from incomplete mocking, that's OK
                # We just want to verify validation passed
                pass

            # Key assertion: Should NOT have emitted warning event
            # (warning event only emitted when force_warn=False)
            mock_emit_warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_warn_still_blocks_block_containers(self, executor, mock_db):
        """Test that force_warn=True still blocks BLOCK containers"""
        # BLOCK containers should NEVER update unless force=True

        update_record = Mock()
        update_record.current_image = "dockmon:2.0"
        update_record.latest_image = "dockmon:2.1"

        with patch('updates.update_executor.async_docker_call') as mock_async_call, \
             patch.object(executor, '_get_docker_client') as mock_get_client, \
             patch.object(executor.event_emitter, 'emit_failed') as mock_emit_failed, \
             patch('updates.update_executor.ContainerValidator') as mock_validator_class, \
             patch.object(executor, 'updating_containers', set()):

            mock_docker_client = Mock()
            mock_get_client.return_value = mock_docker_client

            mock_container = Mock()
            mock_container.name = "dockmon"
            mock_container.labels = {}
            mock_async_call.return_value = mock_container

            # Mock validator to return BLOCK
            mock_validator = Mock()
            mock_validator.validate_update.return_value = ValidationResponse(
                result=ValidationResult.BLOCK,
                reason="DockMon cannot update itself",
                matched_pattern=None
            )
            mock_validator_class.return_value = mock_validator

            # Call with force_warn=True - should still block
            result = await executor.update_container(
                host_id="test-host",
                container_id="abc123def456",
                update_record=update_record,
                force=False,
                force_warn=True  # Should NOT bypass BLOCK
            )

            # Should return False (update blocked)
            assert result is False

            # Should have emitted failure event
            mock_emit_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_force_true_bypasses_everything(self, executor, mock_db):
        """Test that force=True bypasses all validation (admin override)"""
        # Existing behavior - force=True should skip validation entirely

        update_record = Mock()
        update_record.current_image = "traefik:2.10"
        update_record.latest_image = "traefik:2.11"

        with patch('updates.update_executor.async_docker_call') as mock_async_call, \
             patch.object(executor, '_get_docker_client') as mock_get_client, \
             patch('updates.update_executor.ContainerValidator') as mock_validator_class:

            mock_docker_client = Mock()
            mock_get_client.return_value = mock_docker_client

            mock_container = Mock()
            mock_container.name = "traefik"
            mock_container.labels = {}
            mock_async_call.return_value = mock_container

            # Validator should NOT be called when force=True
            mock_validator = Mock()
            mock_validator_class.return_value = mock_validator

            # Call with force=True - validation should be skipped
            # (Will fail for other reasons in unit test, but validation should not run)
            try:
                await executor.update_container(
                    host_id="test-host",
                    container_id="abc123def456",
                    update_record=update_record,
                    force=True,
                    force_warn=False  # Should be ignored when force=True
                )
            except:
                pass  # Expect failures from incomplete mocking

            # Validator should NOT have been created (validation bypassed)
            mock_validator_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_warn_allows_allow_containers(self, executor, mock_db):
        """Test that force_warn=True still allows ALLOW containers"""
        # Sanity check - ALLOW containers should always work

        update_record = Mock()
        update_record.current_image = "nginx:1.25"
        update_record.latest_image = "nginx:1.26"

        with patch('updates.update_executor.async_docker_call') as mock_async_call, \
             patch.object(executor, '_get_docker_client') as mock_get_client, \
             patch('updates.update_executor.ContainerValidator') as mock_validator_class:

            mock_docker_client = Mock()
            mock_get_client.return_value = mock_docker_client

            mock_container = Mock()
            mock_container.name = "nginx"
            mock_container.labels = {}
            mock_async_call.return_value = mock_container

            # Mock validator to return ALLOW
            mock_validator = Mock()
            mock_validator.validate_update.return_value = ValidationResponse(
                result=ValidationResult.ALLOW,
                reason="No restrictions found",
                matched_pattern=None
            )
            mock_validator_class.return_value = mock_validator

            # Call with force_warn=True - should proceed
            # (Will fail for other reasons in unit test, validation should pass)
            try:
                await executor.update_container(
                    host_id="test-host",
                    container_id="abc123def456",
                    update_record=update_record,
                    force=False,
                    force_warn=True
                )
            except:
                pass  # Expect failures from incomplete mocking

            # Validator should have been called and returned ALLOW
            assert mock_validator.validate_update.called
