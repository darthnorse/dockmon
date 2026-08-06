"""Bounded matching for user-supplied selector regexes.

Selector patterns come from alert rules and are matched synchronously inside the
async evaluation loop, so a pattern with catastrophic backtracking blocks every
task on the loop, not just alerting.

Two layers, because a per-match timeout alone is not enough: a selector runs once
per rule per target per metric, so N containers would cost N x timeout every
cycle even with one. The quarantine makes a known-bad pattern cost nothing on its
second and later evaluations.

Uses the `regex` module for its `timeout=` support, pinned to VERSION0 so stored
patterns keep the stdlib `re` semantics they were written against. That timeout
is cooperative - checked between internal steps - so treat it as a tight bound
rather than a hard deadline.
"""
import logging
from functools import lru_cache
from typing import List, Set

import regex

logger = logging.getLogger(__name__)

SELECTOR_REGEX_TIMEOUT_SECONDS = 0.1
MAX_PATTERN_LENGTH = 500

# Bounded so a pathological rule set cannot grow this without limit.
MAX_QUARANTINED_PATTERNS = 256

_quarantined: Set[str] = set()
_new_quarantines: List[str] = []


@lru_cache(maxsize=512)
def _compiled(pattern: str):
    """Compile once per pattern. Raises regex.error on a bad pattern."""
    return regex.compile(pattern, regex.VERSION0)


def compile_selector_pattern(pattern: str):
    """Compile a pattern for storage, raising ValueError with the reason.

    Write-time only: the length cap must not be applied at match time, or rules
    stored before it existed would stop evaluating.
    """
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(
            f"Regex pattern too long ({len(pattern)} chars, max {MAX_PATTERN_LENGTH})"
        )
    try:
        return _compiled(pattern)
    except regex.error as e:
        raise ValueError(f"Invalid regex pattern: {e}")


def _quarantine(pattern: str, reason: str) -> None:
    if pattern in _quarantined:
        return
    if len(_quarantined) >= MAX_QUARANTINED_PATTERNS:
        _quarantined.clear()
        _new_quarantines.clear()
    _quarantined.add(pattern)
    _new_quarantines.append(pattern)
    logger.warning(
        f"Selector regex quarantined ({reason}); rules using it will not match: {pattern!r}"
    )


def selector_matches(pattern: str, subject: str) -> bool:
    """Whether `subject` matches `pattern`, never raising and never unbounded.

    A pattern that cannot be evaluated is a non-match: it is not a positive
    assertion about the host or container. It is also recorded, so the
    evaluation service can report it rather than let the rule fail in silence.
    """
    if pattern in _quarantined:
        return False

    try:
        compiled = _compiled(pattern)
    except regex.error as e:
        # Reachable despite write-time validation: restores, migrations and
        # direct database writes all bypass it.
        _quarantine(pattern, f"does not compile: {e}")
        return False

    try:
        return compiled.match(subject, timeout=SELECTOR_REGEX_TIMEOUT_SECONDS) is not None
    except TimeoutError:
        _quarantine(pattern, f"exceeded {SELECTOR_REGEX_TIMEOUT_SECONDS}s")
        return False


def take_new_quarantines() -> List[str]:
    """Drain patterns quarantined since the last call, for cycle reporting."""
    drained = list(_new_quarantines)
    _new_quarantines.clear()
    return drained


def clear_quarantine() -> None:
    """Reset all state. Tests only."""
    _quarantined.clear()
    _new_quarantines.clear()
    _compiled.cache_clear()
