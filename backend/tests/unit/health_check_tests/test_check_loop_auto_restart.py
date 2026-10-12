"""The check loop's restart retry must only fire while a container stays unhealthy.

Regression: the loop decided on a status snapshot taken before the check, so the
first passing check after an auto-restart (unhealthy -> healthy) restarted the
container a second time.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from health_check import http_checker
from health_check.http_checker import HttpHealthChecker


def _config(current_status: str) -> SimpleNamespace:
    return SimpleNamespace(
        container_id="host-1:abc123def456", host_id="host-1", url="http://plex:32400/web/index.html",
        method="GET", expected_status_codes="200", timeout_seconds=10, check_interval_seconds=60,
        follow_redirects=False, verify_ssl=True, headers_json=None, auth_config_json=None,
        auto_restart_on_failure=True, failure_threshold=3, success_threshold=1, max_restart_attempts=3,
        restart_retry_delay_seconds=120, current_status=current_status, enabled=True,
    )


def _checker(current_status: str, status_after_check: str, monkeypatch) -> HttpHealthChecker:
    session = Mock()
    session.query.return_value.filter_by.return_value.first.return_value = _config(current_status)

    @contextmanager
    def get_session():
        yield session

    db = Mock(get_session=get_session)
    checker = HttpHealthChecker(Mock(), db)
    checker.running = True
    checker._perform_check = AsyncMock(return_value=status_after_check)
    checker._trigger_auto_restart = AsyncMock()

    async def stop_after_one_pass(_seconds):
        checker.running = False

    monkeypatch.setattr(http_checker.asyncio, "sleep", stop_after_one_pass)
    return checker


@pytest.mark.asyncio
async def test_recovery_does_not_restart_again(monkeypatch):
    checker = _checker("unhealthy", "healthy", monkeypatch)
    await checker._check_loop("host-1:abc123def456")
    checker._trigger_auto_restart.assert_not_awaited()


@pytest.mark.asyncio
async def test_staying_unhealthy_retries_the_restart(monkeypatch):
    checker = _checker("unhealthy", "unhealthy", monkeypatch)
    await checker._check_loop("host-1:abc123def456")
    checker._trigger_auto_restart.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_fresh_failure_is_left_to_the_state_change_restart(monkeypatch):
    checker = _checker("healthy", "unhealthy", monkeypatch)
    await checker._check_loop("host-1:abc123def456")
    checker._trigger_auto_restart.assert_not_awaited()
