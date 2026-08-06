"""The expansion screen's invariant, checked mechanically.

_expansion_bound is a hand-written scanner, and under-counting is the dangerous
direction: a pattern it waves through goes straight to regex.compile, which
expands bounded repeats and can allocate gigabytes. Four separate review rounds
each found a different construct that fooled it - a '[' inside a comment, a
large repeated body, verbose mode. Enumerating constructs by hand clearly does
not converge.

So this asserts the property instead of the cases:

    if the screen accepts a pattern, compiling it is cheap.

The grid below is deterministic, not random, so a failure is reproducible and
names the exact pattern.
"""
import resource
import time

import pytest
import regex

from alerts.safe_regex import _expansion_bound, MAX_REPEAT_EXPANSION

# Budget an accepted pattern must respect. Generous: real selectors compile in
# microseconds, and the bombs this guards against ran to hundreds of MB.
MAX_COMPILE_SECONDS = 0.5
MAX_COMPILE_GROWTH_MB = 64

# Bodies chosen for how differently the engine expands them: a literal run is
# flattened, a character class and an alternation are not.
BODIES = [
    "a",
    "ab",
    "[a-z]",
    "(?:a|b)",
    r"\d",
    "ab" * 50,
    "[a-z]" * 50,
    "(?:a|b)" * 30,
]

COUNTS = [1, 2, 5, 100, 1000, 9000]

# Wrappers that have each, at some point, hidden a repeat from the scanner.
PREFIXES = ["", "(?#[)", "(?#comment)", "(?i)", "[x]", r"\[", "^"]


def _patterns():
    for prefix in PREFIXES:
        for body in BODIES:
            for count in COUNTS:
                yield f"{prefix}(?:{body}){{{count}}}"
                yield f"{prefix}(?:(?:{body}){{{count}}}){{{count}}}"


def _rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


ACCEPTED = [p for p in _patterns() if _expansion_bound(p) <= MAX_REPEAT_EXPANSION]


def test_the_grid_exercises_both_verdicts():
    """A screen that accepted nothing would pass the property vacuously."""
    total = len(list(_patterns()))
    assert 0 < len(ACCEPTED) < total, f"{len(ACCEPTED)} accepted of {total}"


@pytest.mark.parametrize("pattern", ACCEPTED, ids=lambda p: p[:40])
def test_accepted_patterns_compile_cheaply(pattern):
    """The invariant: passing the screen means compiling is safe."""
    before = _rss_mb()
    start = time.perf_counter()

    try:
        regex.compile(pattern, regex.VERSION0)
    except regex.error:
        # A syntactically invalid pattern is refused by the compiler itself,
        # which is a safe outcome - the screen only has to bound cost.
        return

    elapsed = time.perf_counter() - start
    growth = _rss_mb() - before

    assert elapsed < MAX_COMPILE_SECONDS, f"{pattern[:60]!r} took {elapsed:.2f}s"
    assert growth < MAX_COMPILE_GROWTH_MB, f"{pattern[:60]!r} grew RSS by {growth:.0f}MB"
