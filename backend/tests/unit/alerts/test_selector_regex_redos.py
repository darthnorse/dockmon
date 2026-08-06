"""Selector regexes are ReDoS-bounded on the path that actually runs them.

This file used to test AlertRuleValidator, which no production code ever
imported - so its guarantees were never in force. It now targets the live
matcher in AlertEngine and the write path, keeping the adversarial pattern
corpus that was the useful part of the original.

The engine matches host_selector['host_name'] / container_selector['container_name']
as a regex when the value starts with 'regex:'.
"""
import asyncio
import time
import types

import pytest

import database as database_module
from alerts.engine import AlertEngine, EvaluationContext
from alerts.safe_regex import SELECTOR_REGEX_TIMEOUT_SECONDS, clear_quarantine
from database import AlertRuleV2, DatabaseManager

HOST_A = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"

CATASTROPHIC = r"(a|aa)+$"
EVIL_NAME = "a" * 60 + "b"

# Kept from the original file: patterns that must not be able to hang the loop.
ADVERSARIAL_PATTERNS = [
    r"(a|aa)+$",
    r"(a+)+$",
    r"(x|x)*y",
    r"(\d+)*$",
    r"(.*)*",
    r"([a-z]+)+$",
]


@pytest.fixture(autouse=True)
def _clean_quarantine():
    clear_quarantine()
    yield
    clear_quarantine()


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database_module._database_manager_instance = None
    db_manager = DatabaseManager(db_path=db_path)
    try:
        yield db_manager
    finally:
        if hasattr(db_manager, "engine"):
            db_manager.engine.dispose()
        database_module._database_manager_instance = None


def _rule(host_selector_json=None, container_selector_json=None):
    """A rule stub carrying every attribute matches_selectors reads."""
    return types.SimpleNamespace(
        id="test-rule", scope="host",
        host_selector_json=host_selector_json,
        container_selector_json=container_selector_json,
        labels_json=None,
    )


def _context(host_name):
    return EvaluationContext(
        scope_type="host", scope_id=HOST_A, host_id=HOST_A, host_name=host_name,
        container_id=None, container_name=None, desired_state="running",
        labels={}, tags=[],
    )


def _insert_rule(db, rule_id, host_selector_json, enabled=True):
    """Insert directly, bypassing the API - what a legacy or restored row is."""
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id=rule_id, name=rule_id, kind="cpu_high", enabled=enabled,
            scope="host", metric="cpu_percent", operator=">=", threshold=1.0,
            occurrences=1, severity="warning", host_selector_json=host_selector_json,
        ))
        session.commit()


@pytest.mark.parametrize("pattern", ADVERSARIAL_PATTERNS)
def test_adversarial_patterns_stay_bounded(db, pattern):
    engine = AlertEngine(db)
    selector = f'{{"host_name": "regex:{pattern}"}}'
    rule = _rule(host_selector_json=selector)

    start = time.perf_counter()
    engine.matches_selectors(rule, _context(EVIL_NAME))
    elapsed = time.perf_counter() - start

    assert elapsed < SELECTOR_REGEX_TIMEOUT_SECONDS * 5, f"{pattern} took {elapsed:.3f}s"


def test_legacy_row_written_straight_to_the_database_stays_bounded(db):
    """Write-time validation is not a security boundary; restores bypass it."""
    _insert_rule(db, "legacy-evil", f'{{"host_name": "regex:{CATASTROPHIC}"}}')
    engine = AlertEngine(db)

    with db.get_session() as session:
        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == "legacy-evil").first()
        session.expunge(rule)

    start = time.perf_counter()
    engine.matches_selectors(rule, _context(EVIL_NAME))
    assert time.perf_counter() - start < SELECTOR_REGEX_TIMEOUT_SECONDS * 5


def test_a_bad_selector_does_not_stop_other_rules_matching(db):
    engine = AlertEngine(db)
    evil = _rule(host_selector_json=f'{{"host_name": "regex:{CATASTROPHIC}"}}')
    good = _rule(host_selector_json='{"host_name": "regex:^prod-"}')

    engine.matches_selectors(evil, _context(EVIL_NAME))

    assert engine.matches_selectors(good, _context("prod-01")) is True


def test_timing_out_selector_does_not_match(db):
    engine = AlertEngine(db)
    rule = _rule(host_selector_json=f'{{"host_name": "regex:{CATASTROPHIC}"}}')

    # A pattern we cannot evaluate is not a positive assertion about this host.
    assert engine.matches_selectors(rule, _context(EVIL_NAME)) is False


@pytest.mark.asyncio
async def test_many_targets_cannot_multiply_the_timeout(db):
    """The N-targets case: quarantine must stop per-target re-evaluation.

    Also asserts the event loop keeps ticking - the real damage of a blocking
    match is every other asyncio task stalling, not just alerting.
    """
    engine = AlertEngine(db)
    rule = _rule(host_selector_json=f'{{"host_name": "regex:{CATASTROPHIC}"}}')

    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.05)

    start = time.perf_counter()
    for i in range(50):
        engine.matches_selectors(rule, _context(f"{EVIL_NAME}-{i}"))
        await asyncio.sleep(0)
    elapsed = time.perf_counter() - start

    beat.cancel()

    # 50 targets must not cost 50 timeouts.
    assert elapsed < SELECTOR_REGEX_TIMEOUT_SECONDS * 5, f"50 targets took {elapsed:.3f}s"
    assert ticks > 0


def test_exact_match_selectors_are_unaffected(db):
    engine = AlertEngine(db)
    rule = _rule(host_selector_json='{"host_name": "web-01"}')

    assert engine.matches_selectors(rule, _context("web-01")) is True
    assert engine.matches_selectors(rule, _context("web-02")) is False


def test_safe_regex_selector_still_works(db):
    engine = AlertEngine(db)
    rule = _rule(host_selector_json='{"host_name": "regex:^web-[0-9]+$"}')

    assert engine.matches_selectors(rule, _context("web-01")) is True
    assert engine.matches_selectors(rule, _context("db-01")) is False
