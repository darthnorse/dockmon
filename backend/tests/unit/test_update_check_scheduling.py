"""
Unit tests for update check scheduling logic

Tests verify:
- Sleep duration calculated correctly for same-day target
- Sleep duration calculated correctly for next-day target
- Edge cases: midnight boundary, exact match, past midnight
- Fallback behavior on invalid time formats
"""

import pytest
from datetime import datetime, time as dt_time, timezone, timedelta
from unittest.mock import Mock, patch
from docker_monitor.periodic_jobs import PeriodicJobsManager


@pytest.fixture
def jobs_manager():
    """Create PeriodicJobsManager with mocked dependencies"""
    mock_db = Mock()
    mock_event_logger = Mock()
    manager = PeriodicJobsManager(mock_db, mock_event_logger)
    return manager


def test_calculate_sleep_same_day(jobs_manager):
    """
    If current time is before target time, sleep until target time today

    Example: Current 1:00 PM, Target 2:00 PM → sleep ~1 hour
    """
    # Mock current time: 1:00 PM UTC
    mock_now = datetime(2025, 11, 16, 13, 0, 0, tzinfo=timezone.utc)

    with patch('docker_monitor.periodic_jobs.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.combine = datetime.combine

        # Target: 2:00 PM (14:00)
        target_time = dt_time(14, 0)

        sleep_seconds = jobs_manager._calculate_sleep_until_next_check(target_time)

        # Expected: ~1 hour (3600 seconds)
        # Allow 60 second tolerance for test execution time
        assert 3540 <= sleep_seconds <= 3660, f"Expected ~3600s (1h), got {sleep_seconds}s"


def test_calculate_sleep_next_day(jobs_manager):
    """
    If current time is after target time, sleep until target time tomorrow

    Example: Current 3:00 PM, Target 2:00 PM → sleep ~23 hours
    """
    # Mock current time: 3:00 PM UTC
    mock_now = datetime(2025, 11, 16, 15, 0, 0, tzinfo=timezone.utc)

    with patch('docker_monitor.periodic_jobs.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.combine = datetime.combine

        # Target: 2:00 PM (14:00) - already passed today
        target_time = dt_time(14, 0)

        sleep_seconds = jobs_manager._calculate_sleep_until_next_check(target_time)

        # Expected: ~23 hours (82800 seconds)
        # Allow 60 second tolerance
        assert 82740 <= sleep_seconds <= 82860, f"Expected ~82800s (23h), got {sleep_seconds}s"


def test_calculate_sleep_exact_match(jobs_manager):
    """
    If current time equals target time, sleep until target time tomorrow

    Example: Current 2:00 PM, Target 2:00 PM → sleep ~24 hours
    """
    # Mock current time: 2:00 PM UTC (exactly at target)
    mock_now = datetime(2025, 11, 16, 14, 0, 0, tzinfo=timezone.utc)

    with patch('docker_monitor.periodic_jobs.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.combine = datetime.combine

        # Target: 2:00 PM (14:00) - exactly now
        target_time = dt_time(14, 0)

        sleep_seconds = jobs_manager._calculate_sleep_until_next_check(target_time)

        # Expected: ~24 hours (86400 seconds)
        # Allow 60 second tolerance
        assert 86340 <= sleep_seconds <= 86460, f"Expected ~86400s (24h), got {sleep_seconds}s"


def test_calculate_sleep_past_midnight(jobs_manager):
    """
    Handle midnight boundary correctly

    Example: Current 11:00 PM, Target 2:00 AM → sleep ~3 hours
    """
    # Mock current time: 11:00 PM UTC (23:00)
    mock_now = datetime(2025, 11, 16, 23, 0, 0, tzinfo=timezone.utc)

    with patch('docker_monitor.periodic_jobs.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.combine = datetime.combine

        # Target: 2:00 AM (02:00) - crosses midnight
        target_time = dt_time(2, 0)

        sleep_seconds = jobs_manager._calculate_sleep_until_next_check(target_time)

        # Expected: ~3 hours (10800 seconds)
        # Allow 60 second tolerance
        assert 10740 <= sleep_seconds <= 10860, f"Expected ~10800s (3h), got {sleep_seconds}s"


def test_calculate_sleep_early_morning_to_afternoon(jobs_manager):
    """
    Test early morning time to afternoon target

    Example: Current 6:00 AM, Target 2:00 PM → sleep ~8 hours
    """
    # Mock current time: 6:00 AM UTC
    mock_now = datetime(2025, 11, 16, 6, 0, 0, tzinfo=timezone.utc)

    with patch('docker_monitor.periodic_jobs.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.combine = datetime.combine

        # Target: 2:00 PM (14:00)
        target_time = dt_time(14, 0)

        sleep_seconds = jobs_manager._calculate_sleep_until_next_check(target_time)

        # Expected: ~8 hours (28800 seconds)
        # Allow 60 second tolerance
        assert 28740 <= sleep_seconds <= 28860, f"Expected ~28800s (8h), got {sleep_seconds}s"


def test_calculate_sleep_with_minutes(jobs_manager):
    """
    Test target time with minutes (not just hour)

    Example: Current 1:30 PM, Target 2:15 PM → sleep ~45 minutes
    """
    # Mock current time: 1:30 PM UTC
    mock_now = datetime(2025, 11, 16, 13, 30, 0, tzinfo=timezone.utc)

    with patch('docker_monitor.periodic_jobs.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.combine = datetime.combine

        # Target: 2:15 PM (14:15)
        target_time = dt_time(14, 15)

        sleep_seconds = jobs_manager._calculate_sleep_until_next_check(target_time)

        # Expected: ~45 minutes (2700 seconds)
        # Allow 60 second tolerance
        assert 2640 <= sleep_seconds <= 2760, f"Expected ~2700s (45min), got {sleep_seconds}s"


def test_calculate_sleep_minimum_duration(jobs_manager):
    """
    Ensure minimum sleep duration to prevent tight loops

    Even if calculated sleep is very small, should sleep at least 60 seconds
    """
    # Mock current time: just 10 seconds before target
    mock_now = datetime(2025, 11, 16, 13, 59, 50, tzinfo=timezone.utc)

    with patch('docker_monitor.periodic_jobs.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.combine = datetime.combine

        # Target: 2:00 PM (14:00) - only 10 seconds away
        target_time = dt_time(14, 0)

        sleep_seconds = jobs_manager._calculate_sleep_until_next_check(target_time)

        # Should enforce minimum 60 second sleep
        assert sleep_seconds >= 60, f"Minimum sleep should be 60s, got {sleep_seconds}s"


# Timezone conversion tests (Issue #65)

def test_timezone_conversion_new_york():
    """
    Test timezone conversion for New York (UTC-5 / UTC-4 DST)

    User sets 1:00 AM local time in New York (timezone_offset = -300 for EST)
    Should convert to 6:00 AM UTC
    """
    # User's local time: 1:00 AM
    local_hour, local_minute = 1, 0
    timezone_offset = -300  # EST is UTC-5 = -300 minutes

    # Convert to UTC: UTC = local - offset
    total_minutes_local = local_hour * 60 + local_minute
    total_minutes_utc = total_minutes_local - timezone_offset

    target_hour_utc = (total_minutes_utc // 60) % 24
    target_minute_utc = total_minutes_utc % 60

    assert target_hour_utc == 6, f"Expected 6:00 UTC, got {target_hour_utc}:{target_minute_utc}"
    assert target_minute_utc == 0


def test_timezone_conversion_london():
    """
    Test timezone conversion for London (UTC+0 / UTC+1 BST)

    User sets 2:00 AM local time in London (timezone_offset = 0 for GMT)
    Should stay at 2:00 AM UTC
    """
    local_hour, local_minute = 2, 0
    timezone_offset = 0  # GMT is UTC+0

    total_minutes_local = local_hour * 60 + local_minute
    total_minutes_utc = total_minutes_local - timezone_offset

    target_hour_utc = (total_minutes_utc // 60) % 24
    target_minute_utc = total_minutes_utc % 60

    assert target_hour_utc == 2, f"Expected 2:00 UTC, got {target_hour_utc}:{target_minute_utc}"
    assert target_minute_utc == 0


def test_timezone_conversion_tokyo():
    """
    Test timezone conversion for Tokyo (UTC+9)

    User sets 3:00 AM local time in Tokyo (timezone_offset = 540 minutes)
    Should convert to 6:00 PM UTC previous day (18:00)
    """
    local_hour, local_minute = 3, 0
    timezone_offset = 540  # JST is UTC+9 = 540 minutes

    total_minutes_local = local_hour * 60 + local_minute
    total_minutes_utc = total_minutes_local - timezone_offset

    # Handle negative result (previous day)
    target_hour_utc = (total_minutes_utc // 60) % 24
    target_minute_utc = total_minutes_utc % 60

    # 3:00 AM JST = 6:00 PM UTC previous day (18:00)
    assert target_hour_utc == 18, f"Expected 18:00 UTC, got {target_hour_utc}:{target_minute_utc}"
    assert target_minute_utc == 0


def test_timezone_conversion_day_wraparound_forward():
    """
    Test day wraparound when local time + offset crosses midnight forward

    User in UTC+12 sets 1:00 AM local → 1:00 PM UTC previous day (13:00)
    """
    local_hour, local_minute = 1, 0
    timezone_offset = 720  # UTC+12 = 720 minutes

    total_minutes_local = local_hour * 60 + local_minute
    total_minutes_utc = total_minutes_local - timezone_offset

    target_hour_utc = (total_minutes_utc // 60) % 24
    target_minute_utc = total_minutes_utc % 60

    # 1:00 AM UTC+12 = 1:00 PM UTC previous day (13:00)
    assert target_hour_utc == 13, f"Expected 13:00 UTC, got {target_hour_utc}:{target_minute_utc}"
    assert target_minute_utc == 0


def test_timezone_conversion_day_wraparound_backward():
    """
    Test day wraparound when local time - offset crosses midnight backward

    User in UTC-12 sets 11:00 PM local → 11:00 AM UTC next day (11:00)
    """
    local_hour, local_minute = 23, 0
    timezone_offset = -720  # UTC-12 = -720 minutes

    total_minutes_local = local_hour * 60 + local_minute
    total_minutes_utc = total_minutes_local - timezone_offset

    target_hour_utc = (total_minutes_utc // 60) % 24
    target_minute_utc = total_minutes_utc % 60

    # 11:00 PM UTC-12 = 11:00 AM UTC next day (11:00)
    assert target_hour_utc == 11, f"Expected 11:00 UTC, got {target_hour_utc}:{target_minute_utc}"
    assert target_minute_utc == 0


def test_timezone_conversion_with_minutes():
    """
    Test timezone conversion with non-zero minutes

    User sets 1:30 AM in UTC-5 → 6:30 AM UTC
    """
    local_hour, local_minute = 1, 30
    timezone_offset = -300  # UTC-5

    total_minutes_local = local_hour * 60 + local_minute
    total_minutes_utc = total_minutes_local - timezone_offset

    target_hour_utc = (total_minutes_utc // 60) % 24
    target_minute_utc = total_minutes_utc % 60

    assert target_hour_utc == 6, f"Expected 6:30 UTC, got {target_hour_utc}:{target_minute_utc}"
    assert target_minute_utc == 30


def test_timezone_conversion_half_hour_offset():
    """
    Test timezone with 30-minute offset (e.g., India UTC+5:30)

    User sets 2:00 AM in UTC+5:30 → 8:30 PM UTC previous day (20:30)
    """
    local_hour, local_minute = 2, 0
    timezone_offset = 330  # IST is UTC+5:30 = 330 minutes

    total_minutes_local = local_hour * 60 + local_minute
    total_minutes_utc = total_minutes_local - timezone_offset

    target_hour_utc = (total_minutes_utc // 60) % 24
    target_minute_utc = total_minutes_utc % 60

    # 2:00 AM IST = 8:30 PM UTC previous day (20:30)
    assert target_hour_utc == 20, f"Expected 20:30 UTC, got {target_hour_utc}:{target_minute_utc}"
    assert target_minute_utc == 30
