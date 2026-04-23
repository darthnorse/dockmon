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


def test_process_events_bails_out_on_persistent_error(caplog):
    """
    If queue.get() raises persistently, `_process_events` must bail out
    within a bounded number of iterations instead of tight-looping through
    `except Exception: logger.error; continue`.

    Regression guard for the 15 GB OOM: an unfixed loop-binding bug drove
    ~80k error records/sec through the Python logger; pytest's caplog buffer
    held every record and anon RSS reached 15 GB in seconds, OOM-killing
    the host. This test pins the backoff + bail-out behaviour so that even
    if a future bug causes `get()` to raise persistently again, the failure
    mode is "processor exits, a few errors logged" rather than "host dies".
    """
    el = _make_logger()

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
        # Generous timeout: a well-behaved bailout completes in < 1 s.
        # A tight loop would blow through millions of iterations before this.
        await asyncio.wait_for(task, timeout=5.0)

    with caplog.at_level(logging.ERROR, logger="event_logger"):
        asyncio.run(run())

    assert broken.gets < 100, (
        f"_process_events looped {broken.gets} times on persistent errors; "
        "expected bounded bail-out (a tight loop reaches millions)"
    )
    error_records = [r for r in caplog.records if r.name == "event_logger"]
    assert len(error_records) < 20, (
        f"log spam exceeded safety budget: {len(error_records)} records. "
        "Under pytest's caplog this is what drives RSS to 15 GB."
    )
