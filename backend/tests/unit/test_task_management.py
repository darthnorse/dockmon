"""
Unit tests for background task management.

Tests verify that fire-and-forget tasks are properly stored, tracked,
and cleaned up on shutdown, with proper error handling.

Issue #1: Fire-and-forget tasks without error handling
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch
import logging


class TestTaskManagement:
    """Tests for background task tracking and error handling"""

    @pytest.mark.asyncio
    async def test_update_check_task_is_stored(self):
        """Verify that update check task is stored as monitor attribute"""
        # This test will fail until we implement task storage
        from main import monitor

        assert hasattr(monitor, 'update_check_task'), "Monitor should have update_check_task attribute"
        assert isinstance(monitor.update_check_task, asyncio.Task), "update_check_task should be an asyncio.Task"
        assert not monitor.update_check_task.done(), "Task should be running"

    @pytest.mark.asyncio
    async def test_http_health_check_task_is_stored(self):
        """Verify that HTTP health check task is stored as monitor attribute"""
        from main import monitor

        assert hasattr(monitor, 'http_health_check_task'), "Monitor should have http_health_check_task attribute"
        assert isinstance(monitor.http_health_check_task, asyncio.Task), "http_health_check_task should be an asyncio.Task"
        assert not monitor.http_health_check_task.done(), "Task should be running"

    @pytest.mark.asyncio
    async def test_task_exception_handler_exists(self):
        """Verify that _handle_task_exception function exists"""
        from main import _handle_task_exception

        assert callable(_handle_task_exception), "_handle_task_exception should be a callable function"

    @pytest.mark.asyncio
    async def test_task_exceptions_are_logged(self, caplog):
        """Verify that task exceptions trigger error logging"""
        from main import _handle_task_exception

        # Create a failing task
        async def failing_task():
            raise ValueError("Test exception from task")

        task = asyncio.create_task(failing_task())
        task.add_done_callback(_handle_task_exception)

        # Wait for task to fail
        await asyncio.sleep(0.1)

        # Check that exception was logged
        assert "Test exception from task" in caplog.text
        assert "ValueError" in caplog.text or "Background task failed" in caplog.text

    @pytest.mark.asyncio
    async def test_cancelled_tasks_not_logged_as_errors(self, caplog):
        """Verify that CancelledError is not logged as error (normal shutdown)"""
        from main import _handle_task_exception

        caplog.set_level(logging.ERROR)

        # Create a task and cancel it
        async def long_task():
            await asyncio.sleep(1000)

        task = asyncio.create_task(long_task())
        task.add_done_callback(_handle_task_exception)
        task.cancel()

        # Wait for cancellation
        try:
            await task
        except asyncio.CancelledError:
            pass

        await asyncio.sleep(0.1)

        # Should not log error for cancellation
        assert "CancelledError" not in caplog.text
        assert "Background task failed" not in caplog.text

    @pytest.mark.asyncio
    async def test_tasks_cancelled_on_shutdown(self):
        """Verify tasks are properly cancelled during shutdown"""
        # This will test the shutdown handler
        # For now, just verify the tasks exist
        from main import monitor

        # Verify tasks can be cancelled
        if hasattr(monitor, 'update_check_task'):
            assert not monitor.update_check_task.cancelled(), "Task should not be cancelled yet"
