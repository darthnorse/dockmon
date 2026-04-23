"""
Regression tests for EventLogger start/stop/start across event loops.

The queue must bind to the loop that actually runs `_process_events`.
An older implementation created the queue in `__init__`, which tied its
internal futures to whatever loop happened to be current at first use.
When the app lifespan was cycled (e.g. a second TestClient context),
the new loop inherited an incompatible queue and every `queue.get()`
raised RuntimeError("... bound to a different event loop"). The handler
in `_process_events` caught the error and logged it, which in the
pytest harness generated ~80k error records per second and eventually
OOM'd the test runner.
"""

import asyncio
import logging
from unittest.mock import MagicMock

import pytest

from event_logger import EventLogger, EventSeverity, EventType


def _make_logger():
    db = MagicMock()
    db.add_event = MagicMock(return_value=None)
    db.get_settings = MagicMock(return_value=None)
    return EventLogger(db=db, websocket_manager=None)


def test_queue_is_not_created_in_init():
    """Constructing EventLogger must not bind a queue to any loop yet."""
    el = _make_logger()
    assert el._event_queue is None


def test_queue_created_and_cleared_across_start_stop():
    """A fresh queue must appear in start() and be released in stop()."""
    el = _make_logger()

    async def cycle():
        await el.start()
        assert el._event_queue is not None
        await el.stop()
        assert el._event_queue is None

    asyncio.run(cycle())


def test_second_lifecycle_in_a_new_loop_does_not_raise(caplog):
    """
    Reproduces the original OOM trigger: run start/stop, then run
    start/stop again from a fresh asyncio.run() (new loop). The second
    cycle must not emit "bound to a different event loop" errors.
    """
    el = _make_logger()

    async def one_cycle():
        await el.start()
        # Exercise the enqueue path so any loop-binding happens now.
        el.log_system_event(
            title="probe",
            message="probe",
            severity=EventSeverity.INFO,
            event_type=EventType.STARTUP,
        )
        # Let the consumer run a tick so it actually awaits queue.get().
        await asyncio.sleep(0.01)
        await el.stop()

    with caplog.at_level(logging.ERROR, logger="event_logger"):
        asyncio.run(one_cycle())
        asyncio.run(one_cycle())

    bad = [r for r in caplog.records if "bound to a different event loop" in r.getMessage()]
    assert bad == [], f"Second lifecycle leaked loop-bound queue futures: {len(bad)} errors"


def test_log_event_before_start_is_safe():
    """Calling log_system_event before start() must not raise."""
    el = _make_logger()
    # Should no-op the queue path and only hit the Python logger.
    el.log_system_event(
        title="pre-start",
        message="pre-start",
        severity=EventSeverity.INFO,
        event_type=EventType.STARTUP,
    )


def test_process_events_bails_out_on_persistent_queue_error(caplog):
    """Persistent queue.get() failures must bail out within MAX_CONSECUTIVE_QUEUE_ERRORS."""
    el = _make_logger()
    cap = EventLogger.MAX_CONSECUTIVE_QUEUE_ERRORS

    class BrokenQueue:
        def __init__(self):
            self.gets = 0

        async def get(self):
            self.gets += 1
            raise RuntimeError("bound to a different event loop")

    broken = BrokenQueue()

    async def run():
        el._event_queue = broken
        task = asyncio.create_task(el._process_events())
        await asyncio.wait_for(task, timeout=5.0)

    with caplog.at_level(logging.ERROR, logger="event_logger"):
        asyncio.run(run())

    assert broken.gets == cap, f"expected {cap} get() calls, got {broken.gets}"

    error_records = [r for r in caplog.records if r.name == "event_logger"]
    # first-error log + bail-out summary.
    assert len(error_records) == 2, f"expected 2 error records, got {len(error_records)}"
    assert any("stopping after" in r.getMessage() for r in error_records)
    assert not el.is_healthy()


def test_process_events_survives_transient_processing_errors():
    """Item-level add_event failures must not trip the queue-error bail-out."""
    el = _make_logger()
    cap = EventLogger.MAX_CONSECUTIVE_QUEUE_ERRORS
    # More failures than the queue-error cap, so a broad catch would bail.
    failures_before_success = cap + 3

    calls = {"n": 0}

    def flaky_add(event_data):
        calls["n"] += 1
        if calls["n"] <= failures_before_success:
            raise RuntimeError("transient DB blip")
        return None

    el.db.add_event = flaky_add

    async def run():
        await el.start()
        total = failures_before_success + 2
        for i in range(total):
            el.log_system_event(
                title=f"probe-{i}",
                message=f"probe-{i}",
                severity=EventSeverity.INFO,
                event_type=EventType.STARTUP,
            )
        await asyncio.wait_for(el._event_queue.join(), timeout=1.0)
        assert el.is_healthy()
        assert calls["n"] == total, f"processed {calls['n']}/{total} events"
        await el.stop()

    asyncio.run(run())


def test_is_healthy_true_by_default_and_after_clean_lifecycle():
    """is_healthy() reports True on a fresh logger, during run, and after a clean stop."""
    el = _make_logger()
    assert el.is_healthy() is True

    async def cycle():
        await el.start()
        assert el.is_healthy() is True
        await el.stop()

    asyncio.run(cycle())
    assert el.is_healthy() is True
