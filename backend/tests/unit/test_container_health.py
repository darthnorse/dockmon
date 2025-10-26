"""
Unit tests for shared container health check utility.

TDD RED Phase: These tests are written BEFORE the implementation.
They will fail until backend/utils/container_health.py is created.

Tests verify:
- Docker health check detection and polling
- No health check fallback (running + 3s stability)
- Timeout handling
- Container crash detection
- Docker API error handling
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch
from docker.errors import NotFound, APIError

# This import will fail until we create the module (expected in RED phase)
from utils.container_health import wait_for_container_health


class TestWaitForContainerHealthWithDockerHealthCheck:
    """Test health check logic when container has Docker HEALTHCHECK configured."""

    @pytest.mark.asyncio
    async def test_container_becomes_healthy(self):
        """
        Container with Docker health check should return True when status becomes 'healthy'.

        Scenario:
        - Container starts (running=True)
        - Health status: "starting" → poll → "healthy"
        - Should return True immediately when healthy detected
        """
        mock_client = Mock()
        mock_container = Mock()

        # Simulate health check progression: starting → healthy
        health_checks = [
            {"State": {"Running": True, "Health": {"Status": "starting"}}},
            {"State": {"Running": True, "Health": {"Status": "starting"}}},
            {"State": {"Running": True, "Health": {"Status": "healthy"}}},
        ]

        mock_container.attrs = health_checks[0]
        call_count = 0

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            nonlocal call_count
            mock_container.attrs = health_checks[min(call_count, len(health_checks) - 1)]
            call_count += 1
            return mock_container

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=10)

        assert result is True
        assert call_count >= 3  # Called at least 3 times before healthy

    @pytest.mark.asyncio
    async def test_container_becomes_unhealthy(self):
        """
        Container with Docker health check should return False when status becomes 'unhealthy'.

        Scenario:
        - Container starts (running=True)
        - Health status: "starting" → "unhealthy"
        - Should return False immediately when unhealthy detected
        """
        mock_client = Mock()
        mock_container = Mock()

        # Simulate health check progression: starting → unhealthy
        health_checks = [
            {"State": {"Running": True, "Health": {"Status": "starting"}}},
            {"State": {"Running": True, "Health": {"Status": "unhealthy"}}},
        ]

        mock_container.attrs = health_checks[0]
        call_count = 0

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            nonlocal call_count
            mock_container.attrs = health_checks[min(call_count, len(health_checks) - 1)]
            call_count += 1
            return mock_container

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=10)

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_timeout(self):
        """
        Container with Docker health check should return False if timeout reached.

        Scenario:
        - Container starts (running=True)
        - Health status stays "starting" forever
        - Should return False after timeout (5s for this test)
        """
        mock_client = Mock()
        mock_container = Mock()

        # Health check stuck at "starting"
        mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "starting"}}}

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            return mock_container

        start_time = time.time()

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=5)

        elapsed = time.time() - start_time

        assert result is False
        assert elapsed >= 5  # Should wait full timeout
        assert elapsed < 7   # Should not wait significantly longer


class TestWaitForContainerHealthNoHealthCheck:
    """Test health check logic when container has NO Docker HEALTHCHECK configured."""

    @pytest.mark.asyncio
    async def test_container_stable_after_3_seconds(self):
        """
        Container without health check should return True if still running after 3s.

        Scenario:
        - Container starts (running=True)
        - No health check configured (Health=None)
        - Wait 3s for stability
        - Container still running → return True
        """
        mock_client = Mock()
        mock_container = Mock()

        # No health check, container running
        mock_container.attrs = {"State": {"Running": True, "Health": None}}

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            return mock_container

        start_time = time.time()

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=10)

        elapsed = time.time() - start_time

        assert result is True
        assert elapsed >= 3  # Should wait 3s for stability
        assert elapsed < 5   # Should return quickly after stability check

    @pytest.mark.asyncio
    async def test_container_crashes_within_3_seconds(self):
        """
        Container without health check should return False if it crashes during stability check.

        Scenario:
        - Container starts (running=True)
        - No health check configured
        - Wait 3s for stability
        - Container crashes (running=False) → return False
        """
        mock_client = Mock()
        mock_container = Mock()

        call_count = 0

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: container running, no health check
                mock_container.attrs = {"State": {"Running": True, "Health": None}}
            else:
                # Second call (after 3s wait): container crashed
                mock_container.attrs = {"State": {"Running": False, "Health": None}}

            return mock_container

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=10)

        assert result is False
        assert call_count == 2  # Called twice: initial check + stability verification


class TestWaitForContainerHealthEdgeCases:
    """Test edge cases and error scenarios."""

    @pytest.mark.asyncio
    async def test_container_not_running_yet_then_starts(self):
        """
        Container should wait for 'running' state before checking health.

        Scenario:
        - Container created but not started yet (running=False)
        - Wait and retry
        - Container starts (running=True)
        - No health check → verify stability → return True
        """
        mock_client = Mock()
        mock_container = Mock()

        call_count = 0

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count <= 2:
                # First 2 calls: not running yet
                mock_container.attrs = {"State": {"Running": False}}
            else:
                # After retries: now running, no health check
                mock_container.attrs = {"State": {"Running": True, "Health": None}}

            return mock_container

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=10)

        assert result is True
        assert call_count >= 3  # Multiple checks before running state achieved

    @pytest.mark.asyncio
    async def test_container_never_starts(self):
        """
        Container should timeout if it never reaches 'running' state.

        Scenario:
        - Container stuck at running=False
        - Timeout after configured duration
        - Return False
        """
        mock_client = Mock()
        mock_container = Mock()

        # Container never starts
        mock_container.attrs = {"State": {"Running": False}}

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            return mock_container

        start_time = time.time()

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=5)

        elapsed = time.time() - start_time

        assert result is False
        assert elapsed >= 5

    @pytest.mark.asyncio
    async def test_docker_api_error(self):
        """
        Docker API errors should be caught and return False.

        Scenario:
        - Docker API raises exception (network error, permission denied, etc.)
        - Should catch exception and return False
        - Should not crash
        """
        mock_client = Mock()

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            raise APIError("Docker daemon not responding")

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=10)

        assert result is False

    @pytest.mark.asyncio
    async def test_container_not_found(self):
        """
        Container not found error should return False.

        Scenario:
        - Container removed during health check
        - Docker API raises NotFound
        - Should return False
        """
        mock_client = Mock()

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            raise NotFound("No such container")

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=10)

        assert result is False


class TestWaitForContainerHealthPerformance:
    """Test performance and short-circuit behavior."""

    @pytest.mark.asyncio
    async def test_short_circuit_on_healthy(self):
        """
        Health check should return immediately when 'healthy' detected.
        Should NOT wait for full timeout.
        """
        mock_client = Mock()
        mock_container = Mock()

        # Container immediately healthy
        mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            return mock_container

        start_time = time.time()

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=60)

        elapsed = time.time() - start_time

        assert result is True
        assert elapsed < 2  # Should return almost immediately, not wait 60s

    @pytest.mark.asyncio
    async def test_short_circuit_on_unhealthy(self):
        """
        Health check should return immediately when 'unhealthy' detected.
        Should NOT wait for full timeout.
        """
        mock_client = Mock()
        mock_container = Mock()

        # Container immediately unhealthy
        mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "unhealthy"}}}

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            return mock_container

        start_time = time.time()

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=60)

        elapsed = time.time() - start_time

        assert result is False
        assert elapsed < 2  # Should return almost immediately

    @pytest.mark.asyncio
    async def test_short_circuit_on_stable_no_healthcheck(self):
        """
        Container without health check should return after 3s stability check.
        Should NOT wait for full timeout.
        """
        mock_client = Mock()
        mock_container = Mock()

        # No health check, container running
        mock_container.attrs = {"State": {"Running": True, "Health": None}}

        async def mock_async_docker_call(sync_fn, *args, **kwargs):
            return mock_container

        start_time = time.time()

        with patch('utils.container_health.async_docker_call', side_effect=mock_async_docker_call):
            result = await wait_for_container_health(mock_client, "abc123def456", timeout=60)

        elapsed = time.time() - start_time

        assert result is True
        assert elapsed >= 3   # Must wait 3s for stability
        assert elapsed < 10   # Should not wait anywhere near 60s timeout
