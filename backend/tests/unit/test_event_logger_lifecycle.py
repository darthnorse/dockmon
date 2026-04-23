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
