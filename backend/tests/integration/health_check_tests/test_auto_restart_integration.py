"""
Integration tests for HTTP health check auto-restart logic.

Tests the complex auto-restart logic using REAL DATABASE:
- Episode-based retry attempts (max_restart_attempts per episode)
- Retry delay enforcement (must wait retry_delay_seconds between restarts)
- 10-minute sliding window safety net (max 12 restarts in 10 minutes)
- Episode counter reset on recovery

CRITICAL: Auto-restart bugs can cause production outages!
"""

import pytest
from unittest.mock import AsyncMock, Mock
import time

from health_check.http_checker import HttpHealthChecker
from database import DatabaseManager


@pytest.fixture
def db_manager(db_session):
    """Create mock DatabaseManager with test database session."""
    manager = Mock(spec=DatabaseManager)
    manager.get_session = lambda: _TestSessionContext(db_session)
    return manager


class _TestSessionContext:
    """Context manager wrapper for test database session."""
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *args):
        pass


@pytest.fixture
def mock_monitor():
    """Create mock container monitor."""
    monitor = Mock()
    monitor.hosts = {}
    monitor.restart_container = AsyncMock()
    monitor.get_containers = AsyncMock(return_value=[])
    return monitor


@pytest.fixture
def checker(db_manager, mock_monitor):
    """Create HttpHealthChecker with real database."""
    return HttpHealthChecker(mock_monitor, db_manager)


@pytest.mark.integration
@pytest.mark.asyncio
class TestEpisodeBasedRetries:
    """Test episode-based retry attempt tracking."""

    async def test_first_unhealthy_triggers_first_restart_attempt(self, checker, mock_monitor):
        """
        Test that first transition to unhealthy triggers first restart attempt.

        Scenario: Container becomes unhealthy for first time, auto_restart enabled.
        Expected: Restart triggered immediately (first attempt in episode).
        """
        container_id = 'host-001:test12345678'
        event_data = {
            'max_restart_attempts': 3,
            'restart_retry_delay_seconds': 60,
        }

        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: Restart triggered (called with positional args)
        mock_monitor.restart_container.assert_called_once_with('host-001', 'test12345678')

        # Assert: Episode tracking initialized
        assert checker.restart_episode_attempts[container_id] == 1
        assert container_id in checker.last_restart_time
        assert len(checker.restart_history[container_id]) == 1

    async def test_max_restart_attempts_per_episode_enforced(self, checker, mock_monitor):
        """
        CRITICAL: Test that max_restart_attempts per episode is enforced.

        Scenario: Container has already had 3 restart attempts (max), still unhealthy.
        Expected: No more restarts in this episode (prevents restart loops!).
        """
        container_id = 'host-001:test12345678'

        # Initialize: Already had 3 restart attempts (max reached)
        checker.restart_episode_attempts[container_id] = 3
        checker.last_restart_time[container_id] = time.time() - 120  # Long enough ago
        checker.restart_history[container_id] = [
            time.time() - 300,
            time.time() - 180,
            time.time() - 120,
        ]

        event_data = {
            'max_restart_attempts': 3,  # Max is 3
            'restart_retry_delay_seconds': 60,
        }

        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: NO restart triggered (max attempts reached)
        mock_monitor.restart_container.assert_not_called()

        # Assert: Attempts counter unchanged
        assert checker.restart_episode_attempts[container_id] == 3

    async def test_episode_counter_resets_on_recovery(self, checker):
        """
        CRITICAL: Test that episode counter resets when container recovers.

        Scenario: Container had 2 restart attempts, then recovers (becomes healthy).
        Expected: Episode counter removed (allows fresh episode if unhealthy again).
        """
        container_id = 'host-001:test12345678'

        # Initialize: Had 2 restart attempts in previous episode
        checker.restart_episode_attempts[container_id] = 2
        checker.last_restart_time[container_id] = time.time() - 300

        # Trigger recovery (called from _update_check_state when status changes to healthy)
        checker._reset_episode_attempts(container_id)

        # Assert: Episode counter removed (deleted from dict)
        assert container_id not in checker.restart_episode_attempts
        assert container_id not in checker.last_restart_time


@pytest.mark.integration
@pytest.mark.asyncio
class TestRetryDelayEnforcement:
    """Test retry delay enforcement between restart attempts."""

    async def test_retry_delay_prevents_immediate_retry(self, checker, mock_monitor):
        """
        CRITICAL: Test that retry_delay_seconds prevents immediate retries.

        Scenario: Container restarted 10 seconds ago, still unhealthy, retry_delay=60s.
        Expected: No restart (must wait 60 seconds between restarts).
        """
        container_id = 'host-001:test12345678'

        # Initialize: Restarted 10 seconds ago (not long enough!)
        checker.restart_episode_attempts[container_id] = 1
        checker.last_restart_time[container_id] = time.time() - 10  # Only 10 seconds ago
        checker.restart_history[container_id] = [time.time() - 10]

        event_data = {
            'max_restart_attempts': 3,
            'restart_retry_delay_seconds': 60,  # Must wait 60 seconds
        }

        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: NO restart triggered (delay not elapsed)
        mock_monitor.restart_container.assert_not_called()

    async def test_retry_allowed_after_delay_elapsed(self, checker, mock_monitor):
        """
        Test that retry is allowed after retry_delay_seconds has elapsed.

        Scenario: Container restarted 65 seconds ago, still unhealthy, retry_delay=60s.
        Expected: Restart allowed (delay elapsed).
        """
        container_id = 'host-001:test12345678'

        # Initialize: Restarted 65 seconds ago (long enough!)
        checker.restart_episode_attempts[container_id] = 1
        checker.last_restart_time[container_id] = time.time() - 65  # 65 seconds ago
        checker.restart_history[container_id] = [time.time() - 65]

        event_data = {
            'max_restart_attempts': 3,
            'restart_retry_delay_seconds': 60,
        }

        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: Restart triggered (delay elapsed)
        mock_monitor.restart_container.assert_called_once()

        # Assert: Attempts incremented
        assert checker.restart_episode_attempts[container_id] == 2

    async def test_first_attempt_bypasses_delay(self, checker, mock_monitor):
        """
        Test that first restart attempt bypasses retry delay (immediate restart).

        Scenario: Container just became unhealthy (first attempt).
        Expected: Restart immediately without delay check.
        """
        container_id = 'host-001:test12345678'

        # No previous restart attempts
        assert container_id not in checker.restart_episode_attempts

        event_data = {
            'max_restart_attempts': 3,
            'restart_retry_delay_seconds': 60,
        }

        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: Restart triggered immediately (first attempt)
        mock_monitor.restart_container.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
class TestSlidingWindowSafetyNet:
    """Test 10-minute sliding window safety net."""

    async def test_sliding_window_prevents_excessive_restarts(self, checker, mock_monitor):
        """
        CRITICAL: Test that 10-minute sliding window prevents excessive restarts.

        Scenario: Container has had 12 restarts in last 10 minutes (safety limit).
        Expected: No more restarts (prevents restart storms!).

        Note: This is a SAFETY NET independent of episode tracking.
        """
        container_id = 'host-001:test12345678'
        now = time.time()

        # Initialize: 12 restarts in last 10 minutes (safety limit!)
        checker.restart_episode_attempts[container_id] = 1  # Episode counter is low
        checker.last_restart_time[container_id] = now - 2
        checker.restart_history[container_id] = [
            # 12 restarts spread across last 10 minutes
            now - 590, now - 540, now - 480, now - 420,
            now - 360, now - 300, now - 240, now - 180,
            now - 120, now - 60, now - 30, now - 2,
        ]

        event_data = {
            'max_restart_attempts': 10,  # Episode limit is high
            'restart_retry_delay_seconds': 1,  # Delay is short
        }

        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: NO restart triggered (sliding window limit reached)
        mock_monitor.restart_container.assert_not_called()

    async def test_sliding_window_allows_restart_after_old_attempts_expire(self, checker, mock_monitor):
        """
        Test that sliding window allows restart after old attempts expire.

        Scenario: Container has 12 restarts, but 1 is older than 10 minutes.
        Expected: Restart allowed (only 11 restarts in sliding window).
        """
        container_id = 'host-001:test12345678'
        now = time.time()

        # Initialize: 12 restarts, but 1 is 11 minutes old (expired from window)
        checker.restart_episode_attempts[container_id] = 1
        checker.last_restart_time[container_id] = now - 2
        checker.restart_history[container_id] = [
            now - 660,  # EXPIRED! (11 minutes old)
            now - 590, now - 540, now - 480, now - 420,
            now - 360, now - 300, now - 240, now - 180,
            now - 120, now - 60, now - 2,
        ]

        event_data = {
            'max_restart_attempts': 10,
            'restart_retry_delay_seconds': 1,
        }

        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: Restart triggered (only 11 in sliding window after cleanup)
        mock_monitor.restart_container.assert_called_once()


@pytest.mark.integration
@pytest.mark.asyncio
class TestRestartExecution:
    """Test container restart execution."""

    async def test_restart_calls_monitor_restart_container(self, checker, mock_monitor):
        """
        Test that restart correctly calls monitor.restart_container().
        """
        container_id = 'host-001:test12345678'
        event_data = {
            'max_restart_attempts': 3,
            'restart_retry_delay_seconds': 60,
        }

        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: Correct restart call (positional args)
        mock_monitor.restart_container.assert_called_once_with('host-001', 'test12345678')

    async def test_restart_times_list_updated(self, checker, mock_monitor):
        """
        Test that restart_history list is updated with each restart.
        """
        container_id = 'host-001:test12345678'
        event_data = {
            'max_restart_attempts': 3,
            'restart_retry_delay_seconds': 1,
        }

        # First restart
        await checker._trigger_auto_restart('host-001', container_id, event_data)
        assert len(checker.restart_history[container_id]) == 1

        # Wait for retry delay
        time.sleep(1.1)

        # Second restart
        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: restart_history list updated
        assert len(checker.restart_history[container_id]) == 2

    async def test_invalid_container_id_format_handled(self, checker, mock_monitor):
        """
        Test that invalid container_id format (missing colon) is handled gracefully.
        """
        container_id = 'invalid_no_colon'  # Missing colon separator
        event_data = {
            'max_restart_attempts': 3,
            'restart_retry_delay_seconds': 60,
        }

        # Should not raise exception
        await checker._trigger_auto_restart('host-001', container_id, event_data)

        # Assert: No restart attempted
        mock_monitor.restart_container.assert_not_called()
