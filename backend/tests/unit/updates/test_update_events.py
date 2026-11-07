"""Characterization of when UPDATE_AVAILABLE is emitted and what it carries."""

from checker_fakes import CONTAINER_ID, CURRENT, HOST_ID, LATEST, container_dict, make_checker
from event_bus import EventType

UPDATE_INFO = {
    "current_image": "app:stable",
    "latest_image": "app:stable",
    "current_digest": CURRENT,
    "latest_digest": LATEST,
    "current_version": "1.0.0",
    "latest_version": "2.0.0",
    "changelog_url": "https://example.com/changelog",
}


async def test_first_check_emits_event(event_bus):
    await make_checker({})._create_update_event(container_dict(), UPDATE_INFO, previous_digest=None)

    assert event_bus.emit.await_count == 1


async def test_changed_latest_digest_emits_event(event_bus):
    await make_checker({})._create_update_event(container_dict(), UPDATE_INFO, previous_digest=CURRENT)

    assert event_bus.emit.await_count == 1


async def test_repeated_latest_digest_emits_nothing(event_bus):
    await make_checker({})._create_update_event(container_dict(), UPDATE_INFO, previous_digest=LATEST)

    assert event_bus.emit.await_count == 0


async def test_event_payload(event_bus):
    container = container_dict(id=CONTAINER_ID + "0" * 52)

    await make_checker({})._create_update_event(container, UPDATE_INFO, previous_digest=None)

    event = event_bus.emit.await_args.args[0]
    assert event.event_type == EventType.UPDATE_AVAILABLE
    assert event.scope_type == "container"
    assert event.scope_id == f"{HOST_ID}:{CONTAINER_ID}"
    assert event.scope_name == "app"
    assert event.host_id == HOST_ID
    assert event.host_name == "docker-1"
    assert event.data == {**UPDATE_INFO, "update_detected": True}


async def test_event_bus_failure_is_swallowed(event_bus):
    event_bus.emit.side_effect = RuntimeError("bus down")

    await make_checker({})._create_update_event(container_dict(), UPDATE_INFO, previous_digest=None)

    event_bus.emit.assert_awaited_once()
