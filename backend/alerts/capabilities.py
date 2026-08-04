"""Per-host metric capability, derived from observed stats.

Capability is a property of what a host's samples actually contain and how
recently they arrived - never of its connection type. Two agent hosts of the
same type differ purely by whether /host/proc is mounted, so connection type
cannot answer the question.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# Host metrics the stats pipeline can carry today.
HOST_METRIC_FIELDS = ("cpu_percent", "memory_percent")

# Samples older than this are treated as absent. stats-service prunes on a 60s
# tick, so a dead host can linger up to 120s in the cache; this makes staleness
# a property of the reader rather than of cleanup timing.
STATS_MAX_AGE_SECONDS = 60


def parse_stats_timestamp(value: Any) -> Optional[datetime]:
    """Parse a stats-service `last_update` into an aware UTC datetime.

    Returns None when the value is absent or unparseable - callers fail open on
    None rather than dropping the sample, because silent non-evaluation is the
    exact failure this module exists to prevent.

    Go marshals time.Time as RFC3339 with up to nanosecond precision, which
    datetime.fromisoformat rejects, so fractional seconds are trimmed to
    microseconds first.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        if "." in text:
            head, _, tail = text.partition(".")
            digits = ""
            for char in tail:
                if char.isdigit():
                    digits += char
                else:
                    break
            offset = tail[len(digits):]
            text = f"{head}.{digits[:6].ljust(6, '0')}{offset}" if digits else head + offset
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        # stats-service stamps UTC; a naive value is the same instant.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sample_age_seconds(stats: Dict[str, Any], now: Optional[datetime] = None) -> Optional[float]:
    """Age of a sample in seconds, or None when it carries no usable timestamp."""
    parsed = parse_stats_timestamp(stats.get("last_update"))
    if parsed is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - parsed).total_seconds()


def is_sample_fresh(
    stats: Dict[str, Any],
    now: Optional[datetime] = None,
    max_age_seconds: int = STATS_MAX_AGE_SECONDS,
) -> bool:
    """Whether a sample is recent enough to evaluate. Unstamped samples pass."""
    age = sample_age_seconds(stats, now)
    if age is None:
        return True
    return age <= max_age_seconds


def host_metric_capabilities(
    host_stats: Dict[str, Dict[str, Any]],
    host_ids: Iterable[str],
    now: Optional[datetime] = None,
) -> Dict[str, List[str]]:
    """Map each host id to the host metrics it is currently observed to report."""
    now = now or datetime.now(timezone.utc)
    capabilities: Dict[str, List[str]] = {}

    for host_id in host_ids:
        stats = host_stats.get(host_id)
        if not stats or not is_sample_fresh(stats, now):
            capabilities[host_id] = []
            continue
        capabilities[host_id] = [
            field for field in HOST_METRIC_FIELDS if stats.get(field) is not None
        ]

    return capabilities
