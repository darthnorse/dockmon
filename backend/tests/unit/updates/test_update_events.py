"""Characterization of when UPDATE_AVAILABLE is emitted and what it carries."""

from unittest.mock import MagicMock

from checker_fakes import CONTAINER_ID, CURRENT, HOST_ID, LATEST, container_dict, make_checker
from event_bus import Event, EventBus, EventType

UPDATE_INFO = {
    "current_image": "app:stable",
    "latest_image": "app:stable",
    "current_digest": CURRENT,
    "latest_digest": LATEST,
    "current_version": "1.0.0",
    "latest_version": "2.0.0",
    "changelog_url": "https://example.com/changelog",
}


async def test_first_check_emits_event(event_bus_stub):
    await make_checker({})._create_update_event(container_dict(), UPDATE_INFO, previous_digest=None)

    assert event_bus_stub.emit.await_count == 1


async def test_changed_latest_digest_emits_event(event_bus_stub):
    await make_checker({})._create_update_event(container_dict(), UPDATE_INFO, previous_digest=CURRENT)

    assert event_bus_stub.emit.await_count == 1


async def test_repeated_latest_digest_emits_nothing(event_bus_stub):
    await make_checker({})._create_update_event(container_dict(), UPDATE_INFO, previous_digest=LATEST)

    assert event_bus_stub.emit.await_count == 0


async def test_event_payload(event_bus_stub):
    container = container_dict(id=CONTAINER_ID + "0" * 52)

    await make_checker({})._create_update_event(container, UPDATE_INFO, previous_digest=None)

    event = event_bus_stub.emit.await_args.args[0]
    assert event.event_type == EventType.UPDATE_AVAILABLE
    assert event.scope_type == "container"
    assert event.scope_id == f"{HOST_ID}:{CONTAINER_ID}"
    assert event.scope_name == "app"
    assert event.host_id == HOST_ID
    assert event.host_name == "docker-1"
    assert event.data == {**UPDATE_INFO, "update_detected": True}


async def test_event_bus_failure_is_swallowed(event_bus_stub):
    event_bus_stub.emit.side_effect = RuntimeError("bus down")

    await make_checker({})._create_update_event(container_dict(), UPDATE_INFO, previous_digest=None)

    event_bus_stub.emit.assert_awaited_once()


async def test_marked_update_flags_its_event(event_bus_stub):
    info = {**UPDATE_INFO, "check_status": "unverified_image"}

    await make_checker({})._create_update_event(container_dict(), info, previous_digest=None)

    assert event_bus_stub.emit.await_args.args[0].data == {**UPDATE_INFO, "update_detected": True,
                                                            "auto_update_paused": True}


def update_event(**data):
    return Event(event_type=EventType.UPDATE_AVAILABLE, scope_type="container", scope_id=f"{HOST_ID}:{CONTAINER_ID}",
                 scope_name="app", host_id=HOST_ID, data={**UPDATE_INFO, **data})


def test_unmarked_update_message():
    title, message = EventBus(MagicMock())._generate_event_message(update_event())

    assert title == "Update Available: app"
    assert message == "Update available: app:stable → app:stable"


def test_marked_update_message_says_auto_update_is_paused():
    title, message = EventBus(MagicMock())._generate_event_message(update_event(auto_update_paused=True))

    assert title == "Update Available: app (auto-update paused)"
    assert message == ("Update available: app:stable → app:stable - auto-update paused: "
                       "can't confirm this image came from the registry")
