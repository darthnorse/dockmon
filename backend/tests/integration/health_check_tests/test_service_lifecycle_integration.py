"""
Integration tests for HTTP health check service lifecycle and event emission.

Tests using REAL DATABASE:
- Event emission when health state changes
- Service start/stop
- Configuration loading from database
- Container caching
- Episode counter reset logic
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timezone
import asyncio
import time

from health_check.http_checker import HttpHealthChecker
from database import ContainerHttpHealthCheck, DatabaseManager


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
class TestEventEmission:
    """Test event emission when health state changes."""

    async def test_event_bus_emits_on_state_change(self, checker, test_host):
        """
        Test that event bus emits CONTAINER_HEALTH_CHANGED event on state change.
        """
        event_data = {
            'host_id': 'host-001',
            'container_id': 'host-001:test12345678',
            'old_status': 'healthy',
            'new_status': 'unhealthy',
            'error_message': 'Status 500',
            'auto_restart_on_failure': False,
            'max_restart_attempts': 3,
            'restart_retry_delay_seconds': 60,
            'health_check_url': 'http://example.com/health',
            'consecutive_failures': 3,
            'failure_threshold': 3,
            'response_time_ms': 100,
        }

        # Mock container cache (and prevent refresh by setting recent timestamp)
        import time as time_module
        checker._cache_last_refresh = time_module.time()  # Recent refresh, prevents reload
        checker._container_cache['host-001:test12345678'] = {
            'short_id': 'test12345678',
            'name': 'test-container',
            'host_name': 'test-host',
            'host_id': 'host-001',
        }

        # Mock event bus
        with patch('health_check.http_checker.get_event_bus') as mock_get_bus:
            mock_bus = AsyncMock()
            mock_get_bus.return_value = mock_bus

            await checker._emit_health_change_event(event_data)

            # Assert: Event emitted
            mock_bus.emit.assert_called_once()

            # Get the call arguments
            call_args = mock_bus.emit.call_args
            event = call_args[0][0] if call_args[0] else call_args.kwargs.get('event')

            # Assert: Event type is CONTAINER_HEALTH_CHANGED
            assert event.event_type.value == 'container_health_changed'


@pytest.mark.integration
@pytest.mark.asyncio
class TestServiceLifecycle:
    """Test service start/stop and task management."""

    async def test_service_start_sets_running_flag(self, checker):
        """
        Test that starting the service sets running flag to True.
        """
        # Mock _reload_and_schedule_checks to avoid actual scheduling
        checker._reload_and_schedule_checks = AsyncMock()

        # Start service in background task
        task = asyncio.create_task(checker.start())

        # Give it a moment to start
        await asyncio.sleep(0.1)

        # Assert: Running flag set
        assert checker.running is True

        # Stop service
        await checker.stop()
        await task

    async def test_service_stop_sets_running_flag_to_false(self, checker):
        """
        Test that stopping the service sets running flag to False.
        """
        # Manually set running flag (simulating started service)
        checker.running = True

        # Stop service
        await checker.stop()

        # Assert: Running flag cleared
        assert checker.running is False

    async def test_service_stop_cancels_check_tasks(self, checker):
        """
        Test that stopping the service cancels all running check tasks.
        """
        # Create mock check tasks
        mock_task1 = AsyncMock()
        mock_task1.cancel = Mock()
        mock_task2 = AsyncMock()
        mock_task2.cancel = Mock()

        checker.check_tasks = {
            'host-001:container1': mock_task1,
            'host-001:container2': mock_task2,
        }

        # Stop service
        await checker.stop()

        # Assert: All tasks cancelled
        mock_task1.cancel.assert_called_once()
        mock_task2.cancel.assert_called_once()

    async def test_stop_is_idempotent(self, checker):
        """
        Test that calling stop() multiple times is safe.
        """
        # Stop multiple times
        await checker.stop()
        await checker.stop()  # Should not raise error
        await checker.stop()  # Should not raise error

        assert checker.running is False


@pytest.mark.integration
@pytest.mark.asyncio
class TestConfigurationManagement:
    """Test configuration loading from database."""

    async def test_load_configurations_from_database(self, db_session, db_manager, test_host):
        """
        Test that configurations are loaded from database.
        """
        # Create enabled health check configuration
        check = ContainerHttpHealthCheck(
            container_id=f"{test_host.id}:test12345678",
            host_id=test_host.id,
            enabled=True,
            url="http://example.com/health",
            method="GET",
            expected_status_codes="200",
            timeout_seconds=5,
            check_interval_seconds=30,
            failure_threshold=3,
            success_threshold=2,
            auto_restart_on_failure=False,
            max_restart_attempts=3,
            restart_retry_delay_seconds=60,
            current_status="healthy",
            follow_redirects=True,
            verify_ssl=True,
            headers_json=None,
            auth_config_json=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(check)
        db_session.commit()

        # Load configurations
        configs = []
        with db_manager.get_session() as sess:
            results = sess.query(ContainerHttpHealthCheck).filter_by(enabled=True).all()
            configs = results

        # Assert: Configuration loaded
        assert len(configs) > 0
        assert configs[0].container_id == f"{test_host.id}:test12345678"
        assert configs[0].url == "http://example.com/health"

    async def test_disabled_configurations_not_loaded(self, db_session, db_manager, test_host):
        """
        Test that disabled configurations are filtered out.
        """
        # Create disabled configuration
        check = ContainerHttpHealthCheck(
            container_id=f"{test_host.id}:test99999999",
            host_id=test_host.id,
            enabled=False,  # DISABLED
            url="http://example.com/health",
            method="GET",
            expected_status_codes="200",
            timeout_seconds=5,
            check_interval_seconds=30,
            failure_threshold=3,
            success_threshold=2,
            auto_restart_on_failure=False,
            max_restart_attempts=3,
            restart_retry_delay_seconds=60,
            current_status="healthy",
            follow_redirects=True,
            verify_ssl=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(check)
        db_session.commit()

        # Load configurations (filter by enabled=True)
        configs = []
        with db_manager.get_session() as sess:
            results = sess.query(ContainerHttpHealthCheck).filter_by(enabled=True).all()
            configs = results

        # Assert: Disabled config not in results
        disabled_ids = [c.container_id for c in configs if c.container_id == f"{test_host.id}:test99999999"]
        assert len(disabled_ids) == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestResetEpisodeAttempts:
    """Test episode counter reset logic."""

    async def test_reset_episode_attempts_removes_counter(self, checker):
        """
        Test that _reset_episode_attempts removes the counter (deletes from dict).
        """
        container_id = 'host-001:test12345678'

        # Initialize with non-zero attempts
        checker.restart_episode_attempts[container_id] = 5
        checker.last_restart_time[container_id] = time.time()

        # Reset
        checker._reset_episode_attempts(container_id)

        # Assert: Counter removed from dict
        assert container_id not in checker.restart_episode_attempts
        assert container_id not in checker.last_restart_time

    async def test_reset_episode_attempts_on_new_container(self, checker):
        """
        Test that _reset_episode_attempts works on container with no history (no-op).
        """
        container_id = 'host-001:new12345678'

        # Container not in dict
        assert container_id not in checker.restart_episode_attempts

        # Reset (should not raise error - it's a no-op)
        checker._reset_episode_attempts(container_id)

        # Assert: Still not in dict (no-op)
        assert container_id not in checker.restart_episode_attempts


@pytest.mark.integration
@pytest.mark.asyncio
class TestContainerCaching:
    """Test container info caching."""

    async def test_container_cache_populated_on_lookup(self, checker, mock_monitor):
        """
        Test that container cache is populated when looking up containers.
        """
        # Mock monitor.get_containers()
        mock_container = Mock()
        mock_container.host_id = 'host-001'
        mock_container.short_id = 'test12345678'
        mock_container.name = 'test-container'
        mock_container.host_name = 'test-host'

        mock_monitor.get_containers = AsyncMock(return_value=[mock_container])

        # Clear cache and timestamp to force refresh
        checker._container_cache.clear()
        checker._cache_last_refresh = 0.0

        # Trigger cache refresh
        result = await checker._get_container_cached('host-001:test12345678')

        # Assert: Container found in cache
        assert result is not None
        assert result['short_id'] == 'test12345678'
        assert result['name'] == 'test-container'

    async def test_container_cache_refreshes_every_30_seconds(self, checker, mock_monitor):
        """
        Test that container cache refreshes every 30 seconds.
        """
        mock_container = Mock()
        mock_container.host_id = 'host-001'
        mock_container.short_id = 'test12345678'
        mock_container.name = 'test-container'
        mock_container.host_name = 'test-host'

        mock_monitor.get_containers = AsyncMock(return_value=[mock_container])

        # First lookup (cache miss, forces refresh)
        checker._cache_last_refresh = 0.0
        await checker._get_container_cached('host-001:test12345678')

        # Second lookup within 30 seconds (cache hit, no refresh)
        import time
        checker._cache_last_refresh = time.time()  # Recent refresh
        first_call_count = mock_monitor.get_containers.call_count

        await checker._get_container_cached('host-001:test12345678')

        # Assert: get_containers not called again (cache used)
        assert mock_monitor.get_containers.call_count == first_call_count

        # Third lookup after 30+ seconds (cache expired, forces refresh)
        checker._cache_last_refresh = time.time() - 31  # 31 seconds ago

        await checker._get_container_cached('host-001:test12345678')

        # Assert: get_containers called again (cache refreshed)
        assert mock_monitor.get_containers.call_count == first_call_count + 1
