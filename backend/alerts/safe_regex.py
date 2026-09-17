"""Bounded compilation and matching for user-supplied selector regexes.

Selector patterns come from alert rules and are matched synchronously inside the
async evaluation loop, so an expensive pattern blocks every task on the loop, not
just alerting.

Three layers, because each covers a hole the others cannot:

1. An expansion screen before compiling. The `regex` module expands bounded
   repeats at compile time, so `(?:(?:(?:a{1000}){1000}){1000})` - 31 characters,
   well under any length cap - allocates gigabytes. Catching MemoryError is not a
   defence: under a container memory limit the kernel sends SIGKILL and no handler
   runs. The allocation has to be prevented, not caught.
2. A match timeout, for patterns that compile cheaply and backtrack expensively.
3. A quarantine, because a per-match timeout alone still costs N x timeout when a
   rule is evaluated against N targets every cycle.

Quarantine entries expire: the subject decides whether a match backtracks, so one
unusual container name - or a moment of CPU starvation, since the timeout is
wall-clock - must not disable a working rule permanently.

Uses `regex` for its `timeout=` support, pinned to VERSION0 so stored patterns
keep the stdlib `re` semantics they were written against.
"""
import json
import logging
import time
from functools import lru_cache
from typing import Dict, FrozenSet, List, Optional

import regex

logger = logging.getLogger(__name__)

SELECTOR_REGEX_TIMEOUT_SECONDS = 0.1
MAX_PATTERN_LENGTH = 500

# Conservative ceiling on compile-time expansion, measured as the product of
# every bounded repeat multiplied by the pattern's length - because what gets
# expanded is the repeated body, not a single atom. A 460-char pattern whose
# repeat counts multiply to only 9000 still allocated 281MB when the body was a
# character class. Real name selectors land far below the ceiling:
# ^web-[0-9]{1,3}$ costs 51, ^(?:[a-z0-9]{1,20}-){1,5}[a-z0-9]{1,20}$ costs 80k.
MAX_REPEAT_EXPANSION = 200_000

# How long a pattern stays quarantined before it is retried.
QUARANTINE_TTL_SECONDS = 900

MAX_QUARANTINED_PATTERNS = 256

REGEX_PREFIX = "regex:"

# Only these selector keys are executed as patterns (AlertEngine.matches_selectors).
REGEX_SELECTOR_KEYS: FrozenSet[str] = frozenset({"host_name", "container_name"})

SELECTOR_RULE_FIELDS: FrozenSet[str] = frozenset(
    {"host_selector_json", "container_selector_json"}
)

MAX_SELECTOR_SIZE_BYTES = 10_000

# pattern -> monotonic time it was quarantined. Insertion-ordered, so the oldest
# entry is the one evicted when full.
_quarantined: Dict[str, float] = {}

_BOUNDED_REPEAT = regex.compile(r"\{(\d+)(?:,(\d*))?\}")

# An inline flag group enabling verbose mode, e.g. (?x) or (?ix:...).
_VERBOSE_FLAG = regex.compile(r"\(\?[aiLmsux]*x[aiLmsux]*[):]")

# Returned when the scan cannot account for the whole pattern.
_OVER_LIMIT = MAX_REPEAT_EXPANSION + 1


def _expansion_bound(pattern: str) -> int:
    """Upper bound on how many atoms compiling this pattern would expand to.

    Deliberately crude: every bounded repeat multiplies, whether or not it is
    actually nested. Over-rejecting a pattern no name selector would use is much
    cheaper than under-rejecting one that allocates gigabytes. Escapes and
    character classes are tracked so `\\{1000\\}` and `[a{1000}]` read as
    literals rather than repeats.

    Anything that could hide a repeat from this scan is refused outright rather
    than scanned optimistically - a `[` inside a comment would otherwise put it
    in character-class mode and make it skip every repeat that follows.
    """
    # Verbose mode turns unescaped `#` into a comment, which can hide a `[`.
    # No name selector needs it.
    if _VERBOSE_FLAG.search(pattern):
        return _OVER_LIMIT

    product = 1
    i = 0
    in_class = False
    length = len(pattern)

    while i < length:
        char = pattern[i]

        if char == "\\":
            i += 2
            continue
        if in_class:
            if char == "]":
                in_class = False
            i += 1
            continue
        if char == "[":
            in_class = True
            i += 1
            continue

        if pattern.startswith("(?#", i):
            end = pattern.find(")", i)
            if end == -1:
                return _OVER_LIMIT
            i = end + 1
            continue

        if char == "{":
            match = _BOUNDED_REPEAT.match(pattern, i)
            if match:
                low, high = match.group(1), match.group(2)
                # {n,} leaves an open tail, which is a star: no expansion beyond n.
                count = int(low) if high in (None, "") else int(high)
                product *= max(count, 1)
                if product * len(pattern) > MAX_REPEAT_EXPANSION:
                    return _OVER_LIMIT
                i = match.end()
                continue

        i += 1

    if in_class:
        # Unbalanced '[': the scan lost track, so it cannot vouch for the rest.
        return _OVER_LIMIT

    # Length stands in for the size of whatever is being repeated: the counts
    # alone say nothing about how much each repetition copies.
    return product * max(len(pattern), 1)


@lru_cache(maxsize=512)
def _compiled(pattern: str):
    """Compile once per pattern. Screen first - see the module docstring."""
    bound = _expansion_bound(pattern)
    if bound > MAX_REPEAT_EXPANSION:
        raise ValueError(
            f"Regex pattern expands to roughly {bound} atoms at compile time "
            f"(max {MAX_REPEAT_EXPANSION})"
        )
    try:
        return regex.compile(pattern, regex.VERSION0)
    except regex.error as e:
        raise ValueError(f"Invalid regex pattern: {e}")
    except (MemoryError, RecursionError, OverflowError) as e:
        # Belt and braces: the screen above is the real control, since a
        # container memory limit kills the process before this could run.
        raise ValueError(f"Regex pattern too expensive to compile: {type(e).__name__}")


def compile_selector_pattern(pattern: str):
    """Compile a pattern for storage, raising ValueError with the reason.

    The length cap is write-time only: applying it at match time would silently
    stop rules stored before the cap existed.
    """
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError(
            f"Regex pattern too long ({len(pattern)} chars, max {MAX_PATTERN_LENGTH})"
        )
    return _compiled(pattern)


def _is_quarantined(pattern: str) -> bool:
    quarantined_at = _quarantined.get(pattern)
    if quarantined_at is None:
        return False
    if time.monotonic() - quarantined_at > QUARANTINE_TTL_SECONDS:
        del _quarantined[pattern]
        return False
    return True


def _purge_expired() -> None:
    now = time.monotonic()
    for pattern in [
        p for p, at in _quarantined.items() if now - at > QUARANTINE_TTL_SECONDS
    ]:
        del _quarantined[pattern]


def _is_saturated() -> bool:
    """Whether every quarantine slot is held by a still-active entry."""
    _purge_expired()
    return len(_quarantined) >= MAX_QUARANTINED_PATTERNS


def _quarantine(pattern: str, reason: str) -> None:
    if pattern in _quarantined:
        return
    if _is_saturated():
        # Do not evict an active entry to make room: with more bad patterns than
        # slots, evicting the one needed next makes every pattern miss and pay a
        # full timeout every cycle - the stall this module exists to prevent.
        # Unknown patterns are refused instead, until TTLs free space.
        logger.warning(
            f"Selector regex quarantine is full ({MAX_QUARANTINED_PATTERNS}); "
            f"refusing to evaluate further patterns: {pattern!r}"
        )
        return
    _quarantined[pattern] = time.monotonic()
    logger.warning(
        f"Selector regex quarantined ({reason}); rules using it will not match "
        f"for {QUARANTINE_TTL_SECONDS}s: {pattern!r}"
    )


def selector_matches(pattern: str, subject: str) -> bool:
    """Whether `subject` matches `pattern`, bounded in both time and memory.

    A pattern that cannot be evaluated is a non-match: it is not a positive
    assertion about the host or container. It is also quarantined, so the
    evaluation service can report it rather than let the rule fail in silence.
    """
    if _is_quarantined(pattern):
        return False

    if _is_saturated():
        # Fail closed: with every slot held, an unknown pattern cannot be
        # evaluated without risking the per-cycle stall the quarantine bounds.
        return False

    try:
        compiled = _compiled(pattern)
    except ValueError as e:
        # Reachable despite write-time validation: restores, migrations and
        # direct database writes all bypass it.
        _quarantine(pattern, str(e))
        return False

    try:
        return compiled.match(subject, timeout=SELECTOR_REGEX_TIMEOUT_SECONDS) is not None
    except TimeoutError:
        _quarantine(pattern, f"exceeded {SELECTOR_REGEX_TIMEOUT_SECONDS}s")
        return False


def selector_value_matches(selector_value: str, subject: Optional[str]) -> bool:
    """Match one selector value, which is a pattern only if it says so.

    Single definition of "this value is a regex", so the write path and the
    match path cannot drift apart on the question.
    """
    if selector_value.startswith(REGEX_PREFIX):
        return selector_matches(selector_value[len(REGEX_PREFIX):], subject or "")
    return subject == selector_value


def active_quarantines() -> List[str]:
    """Patterns currently suppressed, for per-cycle reporting.

    Reported every cycle rather than once: a quarantined pattern means its rules
    are silently not matching, so the alert must stay open while that is true
    instead of being announced once and then auto-resolved.
    """
    return [pattern for pattern in list(_quarantined) if _is_quarantined(pattern)]


def clear_quarantine() -> None:
    """Reset all state. Tests only."""
    _quarantined.clear()
    _compiled.cache_clear()


def validate_selector_field(field_name: str, raw: Optional[str]) -> None:
    """Validate one selector JSON blob, raising ValueError with the reason.

    Not a security boundary - restores, migrations and direct database writes
    bypass it. The runtime guards above are what keep the evaluation loop safe;
    this only stops a bad selector at the door with a usable message.
    """
    if not raw:
        return

    if len(raw.encode("utf-8")) > MAX_SELECTOR_SIZE_BYTES:
        raise ValueError(f"{field_name} too large (max {MAX_SELECTOR_SIZE_BYTES} bytes)")

    try:
        selector = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{field_name} is not valid JSON: {e}")

    if not isinstance(selector, dict):
        raise ValueError(f"{field_name} must be a JSON object")

    # The engine tests membership with `in`; on a string that is a substring match,
    # so a bare-string include would silently widen to every id containing it
    include = selector.get("include")
    if include is not None and (not isinstance(include, list) or not all(isinstance(x, str) for x in include)):
        raise ValueError(f"{field_name}.include must be a list of strings")

    # Only the keys the engine actually executes: rejecting a `regex:` string in
    # a key compared with == would refuse a write runtime never evaluates.
    for key in REGEX_SELECTOR_KEYS:
        value = selector.get(key)
        if isinstance(value, str) and value.startswith(REGEX_PREFIX):
            try:
                compile_selector_pattern(value[len(REGEX_PREFIX):])
            except ValueError as e:
                raise ValueError(f"{field_name} field {key!r}: {e}")
