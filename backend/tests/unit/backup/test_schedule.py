import errno
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backup.errors import BackupSpaceError, disk_space_errors
from backup.schedule import (
    InvalidSchedule,
    next_occurrence,
    previous_occurrence,
    resolve_timezone,
    validate_schedule,
)

UTC = timezone.utc
OSLO = ZoneInfo("Europe/Oslo")


def test_hh_mm_is_a_daily_local_time():
    now = datetime(2026, 9, 25, 12, 0, tzinfo=OSLO)
    assert next_occurrence("03:00", now, OSLO) == datetime(2026, 9, 26, 3, 0, tzinfo=OSLO)
    assert previous_occurrence("03:00", now, OSLO) == datetime(2026, 9, 25, 3, 0, tzinfo=OSLO)


def test_cron_expression():
    now = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)  # a Friday
    assert next_occurrence("0 4 * * 6", now, UTC) == datetime(2026, 9, 26, 4, 0, tzinfo=UTC)


def test_spring_forward_time_runs_at_the_jump():
    now = datetime(2026, 3, 28, 12, 0, tzinfo=OSLO)
    nxt = next_occurrence("02:30", now, OSLO)
    assert nxt.astimezone(UTC) == datetime(2026, 3, 29, 1, 0, tzinfo=UTC)


def test_fall_back_time_runs_once():
    now = datetime(2026, 10, 24, 12, 0, tzinfo=OSLO)
    first = next_occurrence("02:30", now, OSLO)
    second = next_occurrence("02:30", first + timedelta(minutes=1), OSLO)
    assert second - first > timedelta(hours=20)


@pytest.mark.parametrize("schedule", ["03:00", "0 3 * * *", "30 2 * * 0", "0 */6 * * *"])
def test_valid_schedules(schedule):
    validate_schedule(schedule, UTC)


@pytest.mark.parametrize(
    "schedule",
    ["", "25:00", "every day", "* * * * *", "*/30 * * * *", "0 3 * * * *", "0 0 3 * * *", "x" * 200],
)
def test_invalid_or_too_frequent_schedules(schedule):
    with pytest.raises(InvalidSchedule):
        validate_schedule(schedule, UTC)


def test_timezone_from_env(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    tz, error = resolve_timezone()
    assert tz == ZoneInfo("America/New_York") and error is None


def test_invalid_timezone_falls_back_to_utc_with_an_error(monkeypatch):
    monkeypatch.setenv("TZ", "Mars/Olympus_Mons")
    tz, error = resolve_timezone()
    assert tz == ZoneInfo("UTC")
    assert "Mars/Olympus_Mons" in error


def test_quota_exceeded_is_a_space_error():
    with pytest.raises(BackupSpaceError):
        with disk_space_errors("full"):
            raise OSError(errno.EDQUOT, "Disk quota exceeded")


def test_an_occurrence_exactly_now_counts_as_passed():
    now = datetime(2026, 9, 25, 3, 0, tzinfo=UTC)
    assert previous_occurrence("03:00", now, UTC) == now
    assert next_occurrence("03:00", now, UTC) == now + timedelta(days=1)
