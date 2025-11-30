"""
Integration tests for HTTP health check debouncing and state management.

Tests the critical debouncing logic using REAL DATABASE:
- failure_threshold: Consecutive failures needed before marking unhealthy
- success_threshold: Consecutive successes needed before marking healthy
- State transitions and consecutive counter tracking
- Response time tracking and error message storage

These tests use real database operations (not mocks) to verify the complete flow.
"""

import pytest
from unittest.mock import AsyncMock, patch, Mock
from datetime import datetime, timezone
import httpx

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
        pass  # Don't close test session


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


@pytest.fixture
def test_health_check(db_session, test_host):
    """Create a test HTTP health check configuration."""
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
        consecutive_successes=0,
        consecutive_failures=0,
        follow_redirects=True,
        verify_ssl=True,
        headers_json=None,
        auth_config_json=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    db_session.add(check)
    db_session.commit()
    db_session.refresh(check)
    return check


@pytest.mark.integration
@pytest.mark.asyncio
class TestDebouncingIntegration:
    """Test debouncing logic with real database."""

    async def test_failure_threshold_prevents_immediate_unhealthy(self, checker, test_health_check, db_session):
        """
        CRITICAL: Single failure should NOT mark container unhealthy when failure_threshold > 1.

        Scenario: failure_threshold=3, container gets 1 failure.
        Expected: State stays 'healthy', consecutive_failures=1
        """
        # Mock HTTP failure
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.elapsed.total_seconds.return_value = 0.1

        config = {
            'container_id': test_health_check.container_id,
            'host_id': test_health_check.host_id,
            'url': test_health_check.url,
            'method': test_health_check.method,
            'expected_status_codes': test_health_check.expected_status_codes,
            'timeout_seconds': test_health_check.timeout_seconds,
            'follow_redirects': test_health_check.follow_redirects,
            'verify_ssl': test_health_check.verify_ssl,
            'headers_json': test_health_check.headers_json,
            'auth_config_json': test_health_check.auth_config_json,
            'failure_threshold': test_health_check.failure_threshold,
            'success_threshold': test_health_check.success_threshold,
            'current_status': test_health_check.current_status,
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            await checker._perform_check(config)

        # Refresh from database
        db_session.refresh(test_health_check)

        # Assert: Consecutive failures incremented
        assert test_health_check.consecutive_failures == 1
        assert test_health_check.consecutive_successes == 0

        # Assert: Status still healthy (debouncing prevents immediate state change)
        assert test_health_check.current_status == "healthy", \
            "Single failure should not mark unhealthy when threshold=3"

    async def test_failure_threshold_reached_transitions_to_unhealthy(self, checker, db_session, test_host):
        """
        Test that reaching failure_threshold transitions state to unhealthy.

        Scenario: failure_threshold=3, container already has 2 failures, gets 3rd failure.
        Expected: State transitions to 'unhealthy'
        """
        # Create health check with 2 existing failures
        check = ContainerHttpHealthCheck(
            container_id=f"{test_host.id}:test22222222",
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
            consecutive_successes=0,
            consecutive_failures=2,  # Already has 2 failures
            follow_redirects=True,
            verify_ssl=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(check)
        db_session.commit()

        # Mock HTTP failure
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.elapsed.total_seconds.return_value = 0.1

        config = {
            'container_id': check.container_id,
            'host_id': check.host_id,
            'url': check.url,
            'method': check.method,
            'expected_status_codes': check.expected_status_codes,
            'timeout_seconds': check.timeout_seconds,
            'follow_redirects': check.follow_redirects,
            'verify_ssl': check.verify_ssl,
            'headers_json': check.headers_json,
            'auth_config_json': check.auth_config_json,
            'failure_threshold': check.failure_threshold,
            'success_threshold': check.success_threshold,
            'current_status': check.current_status,
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            await checker._perform_check(config)

        # Refresh from database
        db_session.refresh(check)

        # Assert: Consecutive failures now 3
        assert check.consecutive_failures == 3

        # Assert: Now unhealthy (threshold reached)
        assert check.current_status == "unhealthy", \
            "Should transition to unhealthy after 3 consecutive failures"

    async def test_success_threshold_prevents_immediate_recovery(self, checker, db_session, test_host):
        """
        CRITICAL: Single success should NOT mark container healthy when success_threshold > 1.

        Scenario: success_threshold=2, unhealthy container gets 1 success.
        Expected: State stays 'unhealthy', consecutive_successes=1
        """
        # Create unhealthy health check
        check = ContainerHttpHealthCheck(
            container_id=f"{test_host.id}:test33333333",
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
            current_status="unhealthy",
            consecutive_successes=0,
            consecutive_failures=5,
            follow_redirects=True,
            verify_ssl=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(check)
        db_session.commit()

        # Mock HTTP success
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1

        config = {
            'container_id': check.container_id,
            'host_id': check.host_id,
            'url': check.url,
            'method': check.method,
            'expected_status_codes': check.expected_status_codes,
            'timeout_seconds': check.timeout_seconds,
            'follow_redirects': check.follow_redirects,
            'verify_ssl': check.verify_ssl,
            'headers_json': check.headers_json,
            'auth_config_json': check.auth_config_json,
            'failure_threshold': check.failure_threshold,
            'success_threshold': check.success_threshold,
            'current_status': check.current_status,
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            await checker._perform_check(config)

        # Refresh from database
        db_session.refresh(check)

        # Assert: Consecutive successes incremented
        assert check.consecutive_successes == 1
        assert check.consecutive_failures == 0

        # Assert: Still unhealthy (debouncing prevents immediate recovery)
        assert check.current_status == "unhealthy", \
            "Single success should not mark healthy when threshold=2"

    async def test_success_threshold_reached_transitions_to_healthy(self, checker, db_session, test_host):
        """
        Test that reaching success_threshold transitions state to healthy.

        Scenario: success_threshold=2, unhealthy container already has 1 success, gets 2nd success.
        Expected: State transitions to 'healthy'
        """
        # Create unhealthy health check with 1 success
        check = ContainerHttpHealthCheck(
            container_id=f"{test_host.id}:test44444444",
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
            current_status="unhealthy",
            consecutive_successes=1,  # Already has 1 success
            consecutive_failures=0,
            follow_redirects=True,
            verify_ssl=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(check)
        db_session.commit()

        # Mock HTTP success
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1

        config = {
            'container_id': check.container_id,
            'host_id': check.host_id,
            'url': check.url,
            'method': check.method,
            'expected_status_codes': check.expected_status_codes,
            'timeout_seconds': check.timeout_seconds,
            'follow_redirects': check.follow_redirects,
            'verify_ssl': check.verify_ssl,
            'headers_json': check.headers_json,
            'auth_config_json': check.auth_config_json,
            'failure_threshold': check.failure_threshold,
            'success_threshold': check.success_threshold,
            'current_status': check.current_status,
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            await checker._perform_check(config)

        # Refresh from database
        db_session.refresh(check)

        # Assert: Consecutive successes now 2
        assert check.consecutive_successes == 2

        # Assert: Now healthy (threshold reached)
        assert check.current_status == "healthy", \
            "Should transition to healthy after 2 consecutive successes"

    async def test_consecutive_counter_resets_on_opposite_result(self, checker, db_session, test_host):
        """
        Test that consecutive counters reset when opposite result occurs.

        Scenario: Container has 2 consecutive failures, then gets a success.
        Expected: consecutive_failures resets to 0, consecutive_successes becomes 1
        """
        # Create health check with 2 failures
        check = ContainerHttpHealthCheck(
            container_id=f"{test_host.id}:test55555555",
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
            consecutive_successes=0,
            consecutive_failures=2,
            follow_redirects=True,
            verify_ssl=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(check)
        db_session.commit()

        # Mock HTTP success
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1

        config = {
            'container_id': check.container_id,
            'host_id': check.host_id,
            'url': check.url,
            'method': check.method,
            'expected_status_codes': check.expected_status_codes,
            'timeout_seconds': check.timeout_seconds,
            'follow_redirects': check.follow_redirects,
            'verify_ssl': check.verify_ssl,
            'headers_json': check.headers_json,
            'auth_config_json': check.auth_config_json,
            'failure_threshold': check.failure_threshold,
            'success_threshold': check.success_threshold,
            'current_status': check.current_status,
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            await checker._perform_check(config)

        # Refresh from database
        db_session.refresh(check)

        # Assert: Counters reset correctly
        assert check.consecutive_failures == 0, "Failures should reset to 0 on success"
        assert check.consecutive_successes == 1, "Successes should increment to 1"

    async def test_response_time_tracked(self, checker, test_health_check, db_session):
        """
        Test that response time is tracked in database.
        """
        # Mock HTTP success
        mock_response = Mock()
        mock_response.status_code = 200

        config = {
            'container_id': test_health_check.container_id,
            'host_id': test_health_check.host_id,
            'url': test_health_check.url,
            'method': test_health_check.method,
            'expected_status_codes': test_health_check.expected_status_codes,
            'timeout_seconds': test_health_check.timeout_seconds,
            'follow_redirects': test_health_check.follow_redirects,
            'verify_ssl': test_health_check.verify_ssl,
            'headers_json': test_health_check.headers_json,
            'auth_config_json': test_health_check.auth_config_json,
            'failure_threshold': test_health_check.failure_threshold,
            'success_threshold': test_health_check.success_threshold,
            'current_status': test_health_check.current_status,
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            await checker._perform_check(config)

        # Refresh from database
        db_session.refresh(test_health_check)

        # Assert: Response time tracked (in milliseconds)
        # Note: Implementation uses time.time(), so very fast tests might be 0ms
        assert test_health_check.last_response_time_ms is not None
        assert test_health_check.last_response_time_ms >= 0

    async def test_error_message_stored_on_failure(self, checker, db_session, test_host):
        """
        Test that error message is stored when check fails.
        """
        # Create health check with failure_threshold=1 (immediate unhealthy)
        check = ContainerHttpHealthCheck(
            container_id=f"{test_host.id}:test66666666",
            host_id=test_host.id,
            enabled=True,
            url="http://example.com/health",
            method="GET",
            expected_status_codes="200",
            timeout_seconds=5,
            check_interval_seconds=30,
            failure_threshold=1,  # Immediate unhealthy
            success_threshold=2,
            auto_restart_on_failure=False,
            max_restart_attempts=3,
            restart_retry_delay_seconds=60,
            current_status="healthy",
            consecutive_successes=0,
            consecutive_failures=0,
            follow_redirects=True,
            verify_ssl=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(check)
        db_session.commit()

        # Mock HTTP failure
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.elapsed.total_seconds.return_value = 0.1

        config = {
            'container_id': check.container_id,
            'host_id': check.host_id,
            'url': check.url,
            'method': check.method,
            'expected_status_codes': check.expected_status_codes,
            'timeout_seconds': check.timeout_seconds,
            'follow_redirects': check.follow_redirects,
            'verify_ssl': check.verify_ssl,
            'headers_json': check.headers_json,
            'auth_config_json': check.auth_config_json,
            'failure_threshold': check.failure_threshold,
            'success_threshold': check.success_threshold,
            'current_status': check.current_status,
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            await checker._perform_check(config)

        # Refresh from database
        db_session.refresh(check)

        # Assert: Error message stored
        assert check.last_error_message is not None
        assert "Status 500" in check.last_error_message
