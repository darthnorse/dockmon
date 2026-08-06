"""Selector regexes must not be able to stall the event loop.

Alert selectors accept user-supplied patterns and the engine matches them on
every evaluation cycle, synchronously, inside an async coroutine. A pattern with
catastrophic backtracking therefore blocks every task on the loop - not just
alerting. Measured before this module existed: re.match(r'(a+)+$', 'a'*30 + '!')
took 21.2s, against a loop that sleeps 10s between cycles.

A per-match timeout alone is not enough: a selector is evaluated once per rule
per target per metric, so N containers cost N x timeout every cycle. Hence the
quarantine - the second match of a known-bad pattern must not run at all.
"""
import time

import pytest

from alerts.safe_regex import (
    MAX_PATTERN_LENGTH,
    MAX_REPEAT_EXPANSION,
    SELECTOR_REGEX_TIMEOUT_SECONDS,
    active_quarantines,
    clear_quarantine,
    compile_selector_pattern,
    selector_matches,
)

# 31 characters, compiles in 0.000s under stdlib re, allocates over a gigabyte
# under the regex module. Short enough to pass every length cap.
COMPILE_BOMB = r"(?:(?:(?:a{1000}){1000}){1000})"

# Survives the regex module's optimiser, unlike (a+)+$ which it flattens to ~0s.
CATASTROPHIC = r"(a|aa)+$"
CATASTROPHIC_SUBJECT = "a" * 60 + "b"


@pytest.fixture(autouse=True)
def _clean_quarantine():
    clear_quarantine()
    yield
    clear_quarantine()


class TestOrdinaryPatterns:
    def test_matches_and_rejects_normally(self):
        assert selector_matches(r"^web-[0-9]+$", "web-01") is True
        assert selector_matches(r"^web-[0-9]+$", "db-01") is False

    def test_ordinary_patterns_are_never_quarantined(self):
        for _ in range(5):
            selector_matches(r"^web-[0-9]+$", "web-01")
        assert active_quarantines() == []

    def test_empty_subject_is_handled(self):
        assert selector_matches(r"^web", "") is False


class TestTimeoutBound:
    def test_catastrophic_pattern_returns_within_the_budget(self):
        start = time.perf_counter()
        result = selector_matches(CATASTROPHIC, CATASTROPHIC_SUBJECT)
        elapsed = time.perf_counter() - start

        assert result is False
        # Generous multiple of the budget: the timeout is cooperative, checked
        # between internal steps, so slight overshoot is expected.
        assert elapsed < SELECTOR_REGEX_TIMEOUT_SECONDS * 5, f"took {elapsed:.3f}s"


class TestQuarantine:
    def test_second_match_of_a_bad_pattern_does_not_run(self):
        selector_matches(CATASTROPHIC, CATASTROPHIC_SUBJECT)

        start = time.perf_counter()
        result = selector_matches(CATASTROPHIC, CATASTROPHIC_SUBJECT)
        elapsed = time.perf_counter() - start

        assert result is False
        # This is the N-targets defence: without it, every container costs
        # another full timeout, every cycle.
        assert elapsed < SELECTOR_REGEX_TIMEOUT_SECONDS / 10, f"took {elapsed:.3f}s"

    def test_quarantine_holds_across_different_subjects(self):
        selector_matches(CATASTROPHIC, CATASTROPHIC_SUBJECT)

        start = time.perf_counter()
        selector_matches(CATASTROPHIC, "a" * 70 + "b")
        assert time.perf_counter() - start < SELECTOR_REGEX_TIMEOUT_SECONDS / 10

    def test_quarantined_patterns_are_reported_every_cycle(self):
        selector_matches(CATASTROPHIC, CATASTROPHIC_SUBJECT)

        # Reported for as long as the rule is suppressed. Reporting once would
        # let the aggregated system alert auto-resolve while the rule stays dead.
        assert active_quarantines() == [CATASTROPHIC]
        assert active_quarantines() == [CATASTROPHIC]

    def test_quarantine_expires_so_a_one_off_trip_self_heals(self, monkeypatch):
        """The subject decides whether a match backtracks, not the pattern alone.

        One unusual container name must not disable a working rule until restart.
        """
        selector_matches(CATASTROPHIC, CATASTROPHIC_SUBJECT)
        assert active_quarantines() == [CATASTROPHIC]

        import alerts.safe_regex as safe_regex

        real_monotonic = time.monotonic
        monkeypatch.setattr(
            safe_regex.time,
            "monotonic",
            lambda: real_monotonic() + safe_regex.QUARANTINE_TTL_SECONDS + 1,
        )

        assert active_quarantines() == []

    def test_quarantine_is_bounded_without_wiping_what_it_knows(self):
        # Uncompilable patterns quarantine instantly, so this stays fast.
        for i in range(400):
            selector_matches(f"(unclosed{i}", "x")

        from alerts.safe_regex import _quarantined

        assert len(_quarantined) <= 256
        # Overflow must not clear: wiping would make every known-bad pattern
        # executable again and restore the N x timeout stall.
        assert len(_quarantined) >= 256

    def test_saturation_fails_closed_rather_than_evicting(self):
        """Evicting to make room re-opens the stall.

        With more bad patterns than slots, evicting the entry needed next makes
        every pattern miss and pay a full timeout on every cycle.
        """
        for i in range(300):
            selector_matches(f"(unclosed{i}", "x")

        start = time.perf_counter()
        assert selector_matches(CATASTROPHIC, CATASTROPHIC_SUBJECT) is False
        # Refused without running, so no timeout is paid.
        assert time.perf_counter() - start < SELECTOR_REGEX_TIMEOUT_SECONDS / 10

        from alerts.safe_regex import _quarantined

        assert "(unclosed0" in _quarantined


class TestCompileExpansionBomb:
    """The regex module expands bounded repeats at compile time.

    A pattern far under every length cap can allocate gigabytes, and catching
    MemoryError is no defence: under a container memory limit the kernel sends
    SIGKILL and no handler runs. The allocation has to be prevented.
    """

    def test_write_time_rejects_the_bomb_without_compiling_it(self):
        start = time.perf_counter()
        with pytest.raises(ValueError, match="expands"):
            compile_selector_pattern(COMPILE_BOMB)
        # Fast means it was screened, not compiled and caught.
        assert time.perf_counter() - start < 0.05

    def test_match_time_quarantines_the_bomb(self):
        """Restores and direct database writes bypass write-time validation."""
        start = time.perf_counter()
        assert selector_matches(COMPILE_BOMB, "web-01") is False
        assert time.perf_counter() - start < 0.05
        assert COMPILE_BOMB in active_quarantines()

    def test_a_single_huge_repeat_is_rejected(self):
        # Passes the 500-char length cap on its own.
        with pytest.raises(ValueError, match="expands"):
            compile_selector_pattern("a{99999999}")

    @pytest.mark.parametrize("pattern", [
        r"^web-[0-9]{1,3}$",
        r"^(?:[a-z0-9]{1,20}-){1,5}[a-z0-9]{1,20}$",
        r"(?:[0-9a-f]{8}-){4}",
        r"^prod-\d{2}$",
    ])
    def test_realistic_name_selectors_are_not_rejected(self, pattern):
        assert compile_selector_pattern(pattern) is not None

    def test_braces_that_are_not_quantifiers_do_not_count(self):
        # A literal brace inside a class, and an escaped one, are not repeats.
        assert compile_selector_pattern(r"^[a{1000}]+$") is not None
        assert compile_selector_pattern(r"^a\{1000\}$") is not None

    @pytest.mark.parametrize("pattern", [
        # A '[' inside a comment used to put the scanner into character-class
        # mode, so it skipped every repeat that followed and returned 1.
        r"(?#[)(?:a{1000}){1000}",
        # Verbose mode makes '#' a comment, which can hide a '[' the same way.
        "(?x)# [\na{1000}{1000}",
        # An unbalanced '[' means the scan lost track of the rest.
        r"[a{1000}",
    ])
    def test_constructs_that_could_hide_a_repeat_are_refused(self, pattern):
        from alerts.safe_regex import _expansion_bound

        assert _expansion_bound(pattern) > MAX_REPEAT_EXPANSION

    def test_expansion_bound_threshold_is_enforced(self):
        from alerts.safe_regex import _expansion_bound

        assert _expansion_bound(r"^web-[0-9]{1,3}$") <= MAX_REPEAT_EXPANSION
        assert _expansion_bound(COMPILE_BOMB) > MAX_REPEAT_EXPANSION

    @pytest.mark.parametrize("body", ["[a-z]" * 90, "(?:a|b)" * 60])
    def test_a_large_repeated_body_is_rejected_despite_a_small_count(self, body):
        """Repeat counts say nothing about how much each repetition copies.

        Measured: a 460-char pattern whose counts multiply to only 9000
        allocated 281MB, because the repeated body was a character class.
        """
        pattern = "(?:" + body + "){9000}"
        assert len(pattern) < MAX_PATTERN_LENGTH  # passes the length cap

        with pytest.raises(ValueError, match="expands"):
            compile_selector_pattern(pattern)


class TestCompileValidation:
    def test_valid_pattern_compiles(self):
        assert compile_selector_pattern(r"^web-[0-9]+$") is not None

    def test_invalid_pattern_raises(self):
        with pytest.raises(ValueError, match="Invalid regex"):
            compile_selector_pattern("(unclosed")

    def test_over_long_pattern_raises(self):
        with pytest.raises(ValueError, match="too long"):
            compile_selector_pattern("a" * (MAX_PATTERN_LENGTH + 1))

    def test_length_cap_is_write_time_only(self):
        """A legacy row may hold a longer pattern; it must still evaluate.

        Applying the cap at match time would silently stop rules that were
        stored before the cap existed.
        """
        long_pattern = "a" * (MAX_PATTERN_LENGTH + 1)

        assert selector_matches(long_pattern, "a" * (MAX_PATTERN_LENGTH + 1)) is True
        assert selector_matches(long_pattern, "aaa") is False
        assert active_quarantines() == []

    def test_uncompilable_pattern_at_runtime_is_a_reported_non_match(self):
        # Direct DB writes and restores bypass write-time validation, so the
        # matcher must survive a pattern that never passed it.
        assert selector_matches("(unclosed", "anything") is False
        assert "(unclosed" in active_quarantines()


class TestSemanticsPreserved:
    """VERSION0 keeps stdlib re semantics for patterns already stored."""

    @pytest.mark.parametrize("pattern,subject,expected", [
        (r"^web", "web-01", True),
        # match() anchors at the start, so a trailing anchor alone does not match.
        (r"web$", "01-web", False),
        (r"web$", "web", True),
        (r"^(web|db)-\d+$", "db-12", True),
        (r"^(web|db)-\d+$", "cache-12", False),
        (r"[a-z]+", "abc", True),
        (r"^a.c$", "abc", True),
    ])
    def test_common_selector_patterns_behave_like_re(self, pattern, subject, expected):
        import re

        assert selector_matches(pattern, subject) is expected
        assert bool(re.match(pattern, subject)) is expected
