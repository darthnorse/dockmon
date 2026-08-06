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
    SELECTOR_REGEX_TIMEOUT_SECONDS,
    clear_quarantine,
    compile_selector_pattern,
    selector_matches,
    take_new_quarantines,
)

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
        assert take_new_quarantines() == []

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

    def test_newly_quarantined_patterns_are_reported_once(self):
        selector_matches(CATASTROPHIC, CATASTROPHIC_SUBJECT)
        selector_matches(CATASTROPHIC, CATASTROPHIC_SUBJECT)

        reported = take_new_quarantines()

        assert CATASTROPHIC in reported
        assert len(reported) == 1
        # Draining means the aggregated report does not repeat every cycle.
        assert take_new_quarantines() == []

    def test_quarantine_is_bounded(self):
        for i in range(400):
            selector_matches(f"(a|aa)+{i}$", "a" * 60 + "b")
        from alerts.safe_regex import _quarantined

        assert len(_quarantined) <= 256


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
        assert take_new_quarantines() == []

    def test_uncompilable_pattern_at_runtime_is_a_reported_non_match(self):
        # Direct DB writes and restores bypass write-time validation, so the
        # matcher must survive a pattern that never passed it.
        assert selector_matches("(unclosed", "anything") is False
        assert "(unclosed" in take_new_quarantines()


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
