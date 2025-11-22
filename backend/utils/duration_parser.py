"""
Duration parsing utilities for Docker Compose time strings.

Converts Docker Compose duration strings (e.g., "30s", "1m", "1h30m") to
nanoseconds as required by Docker SDK API.
"""

import re
from typing import Union


def parse_docker_duration(duration: Union[str, int, None]) -> int:
    """
    Parse Docker Compose duration string to nanoseconds.

    Docker SDK requires timing parameters (healthcheck intervals, timeouts, etc.)
    as integers in nanoseconds, but Docker Compose files use human-readable
    strings like "30s", "1m", "1h30m".

    Supported units:
    - ns: nanoseconds
    - us: microseconds
    - ms: milliseconds
    - s: seconds
    - m: minutes
    - h: hours

    Args:
        duration: Duration string (e.g., "30s", "1m30s") or int (nanoseconds) or None

    Returns:
        Duration in nanoseconds as integer

    Raises:
        ValueError: If duration string format is invalid

    Examples:
        >>> parse_docker_duration("30s")
        30000000000
        >>> parse_docker_duration("1m30s")
        90000000000
        >>> parse_docker_duration("1h")
        3600000000000
        >>> parse_docker_duration(None)
        0
        >>> parse_docker_duration(30000000000)  # Already nanoseconds
        30000000000
    """
    # Handle None and empty string
    if duration is None or duration == '':
        return 0

    # Handle already-converted integers (nanoseconds)
    if isinstance(duration, int):
        return duration

    # Parse string format
    duration_str = str(duration).strip()
    if not duration_str:
        return 0

    # Pattern: number (int or float) followed by unit
    # Supports compound durations like "1h30m" or "1m30s"
    pattern = r'(\d+(?:\.\d+)?)(ns|us|ms|s|m|h)'
    matches = re.findall(pattern, duration_str)

    if not matches:
        raise ValueError(
            f"Invalid duration format: '{duration}'. "
            f"Expected format: <number><unit> (e.g., '30s', '1m', '1h30m'). "
            f"Valid units: ns, us, ms, s, m, h"
        )

    # Convert each component to nanoseconds and sum
    total_nanoseconds = 0
    for value_str, unit in matches:
        value = float(value_str)

        # Unit to nanoseconds multipliers
        multiplier = {
            'ns': 1,
            'us': 1_000,
            'ms': 1_000_000,
            's': 1_000_000_000,
            'm': 60_000_000_000,
            'h': 3_600_000_000_000,
        }[unit]

        total_nanoseconds += int(value * multiplier)

    return total_nanoseconds
