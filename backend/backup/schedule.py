"""When scheduled backups run: `HH:MM` or a 5-field cron expression, in the container's time zone.

Unlike the update-check scheduler, times are computed with a real ZoneInfo zone
rather than today's UTC offset, so runs stay at the configured local time across
DST changes.
"""

import os
import re
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cronsim import CronSim, CronSimError

from backup.errors import BackupError

MIN_INTERVAL = timedelta(hours=1)
INTERVAL_CHECK_OCCURRENCES = 60
MAX_SCHEDULE_LENGTH = 100
_SIMPLE_TIME = re.compile(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$")


class InvalidSchedule(BackupError):
    """The schedule is not HH:MM or a 5-field cron expression, or runs too often."""


def resolve_timezone() -> Tuple[tzinfo, Optional[str]]:
    """The container's zone from TZ; UTC with an error message when TZ names no known zone."""
    name = os.environ.get("TZ", "").strip().lstrip(":")
    if not name:
        return ZoneInfo("UTC"), None
    try:
        return ZoneInfo(name), None
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC"), f"TZ={name} is not a known time zone; scheduling in UTC"


def _as_cron(schedule: str) -> str:
    schedule = schedule.strip()
    match = _SIMPLE_TIME.match(schedule)
    if match:
        return f"{int(match.group(2))} {int(match.group(1))} * * *"
    return schedule


def _iterate(schedule: str, start: datetime, reverse: bool = False) -> CronSim:
    expression = _as_cron(schedule)
    if len(expression.split()) != 5:
        raise InvalidSchedule("Use HH:MM or a 5-field cron expression")
    try:
        return CronSim(expression, start, reverse=reverse)
    except CronSimError as e:
        raise InvalidSchedule(f"Invalid cron expression: {e}") from None


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc)


def next_occurrence(schedule: str, now: datetime, tz: tzinfo) -> datetime:
    """The first occurrence after now. CronSim steps in wall-clock time, so inside a
    repeated DST hour it can yield an instant that has already passed: skip those."""
    occurrences = _iterate(schedule, now.astimezone(tz))
    upcoming = next(occurrences)
    while _utc(upcoming) <= _utc(now):
        upcoming = next(occurrences)
    return upcoming


def previous_occurrence(schedule: str, now: datetime, tz: tzinfo) -> datetime:
    """The latest occurrence at or before now (CronSim iterates exclusively of its start)."""
    occurrences = _iterate(schedule, now.astimezone(tz) + timedelta(seconds=1), reverse=True)
    latest = next(occurrences)
    while _utc(latest) > _utc(now):
        latest = next(occurrences)
    return latest


def validate_schedule(schedule: str, tz: tzinfo) -> None:
    if not isinstance(schedule, str) or not schedule.strip() or len(schedule) > MAX_SCHEDULE_LENGTH:
        raise InvalidSchedule("Use HH:MM or a 5-field cron expression")
    occurrences = _iterate(schedule, datetime.now(tz))
    previous = next(occurrences)
    for _ in range(INTERVAL_CHECK_OCCURRENCES):
        current = next(occurrences)
        if _utc(current) - _utc(previous) < MIN_INTERVAL:
            raise InvalidSchedule("Scheduled backups must be at least an hour apart")
        previous = current
