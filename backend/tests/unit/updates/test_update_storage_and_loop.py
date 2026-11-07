"""Characterization of update persistence and both check entry points, on a real database."""

from unittest.mock import patch

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from checker_fakes import (
    CHANGELOG_CHECKED_AT,
    CONTAINER_ID,
    CURRENT,
    FakeRegistry,
    HOST_ID,
    LATEST,
    container_dict,
    digest,
    make_monitor,
    monitored_container,
    registry_result,
)
from database import ContainerUpdate, DockerHostDB, GlobalSettings, RegistryCredential, UpdatePolicy
from updates.update_checker import UpdateChecker

pytestmark = pytest.mark.usefixtures("changelog_stub", "event_bus_stub")

COMPOSITE_KEY = f"{HOST_ID}:{CONTAINER_ID}"
FULL_ID = CONTAINER_ID + "0" * 52


def update_info(**overrides):
    info = {
        "current_image": "app:1.0.0",
        "current_digest": CURRENT,
        "latest_image": "app:1",
        "latest_digest": LATEST,
        "update_available": True,
        "registry_url": "docker.io",
        "platform": "linux/amd64",
        "floating_tag_mode": "minor",
        "current_version": "1.0.0",
        "latest_version": "1.1.0",
        "changelog_url": "https://example.com/changelog",
        "changelog_source": "auto",
        "changelog_checked_at": CHANGELOG_CHECKED_AT,
    }
    info.update(overrides)
    return info


@pytest.fixture
def host_db(db):
    with db.get_session() as session:
        session.add(DockerHostDB(id=HOST_ID, name="docker-1", url="unix:///var/run/docker.sock", is_active=True))
        session.commit()
    return db


def existing_row(db, **overrides):
    values = dict(
        container_id=COMPOSITE_KEY, host_id=HOST_ID, current_image="app:0.9.0", current_digest=CURRENT,
        latest_digest=CURRENT, update_available=False, floating_tag_mode="patch",
    )
    values.update(overrides)
    with db.get_session() as session:
        session.add(ContainerUpdate(**values))
        session.commit()


def read_row(db):
    with db.get_session() as session:
        row = session.query(ContainerUpdate).filter_by(container_id=COMPOSITE_KEY).first()
        session.expunge(row)
    return row


def stored_names(db):
    with db.get_session() as session:
        return sorted(row.container_name for row in session.query(ContainerUpdate).all())


def test_store_creates_record_with_every_field(host_db):
    UpdateChecker(db=host_db)._store_update_info(container_dict(), update_info())

    row = read_row(host_db)
    assert row.host_id == HOST_ID
    assert row.container_name == "app"
    assert row.current_image == "app:1.0.0"
    assert row.current_digest == CURRENT
    assert row.latest_image == "app:1"
    assert row.latest_digest == LATEST
    assert row.update_available is True
    assert row.floating_tag_mode == "minor"
    assert row.registry_url == "docker.io"
    assert row.platform == "linux/amd64"
    assert row.current_version == "1.0.0"
    assert row.latest_version == "1.1.0"
    assert row.changelog_url == "https://example.com/changelog"
    assert row.changelog_source == "auto"
    assert row.changelog_checked_at is not None
    assert row.last_checked_at is not None


def test_store_updates_existing_record_and_keeps_tracking_mode(host_db):
    existing_row(host_db)

    UpdateChecker(db=host_db)._store_update_info(container_dict(), update_info())

    row = read_row(host_db)
    assert row.update_available is True
    assert row.current_image == "app:1.0.0"
    assert row.latest_digest == LATEST
    assert row.floating_tag_mode == "patch"
    assert row.container_name == "app"


def test_store_uses_short_id_in_composite_key(host_db):
    UpdateChecker(db=host_db)._store_update_info(container_dict(id=FULL_ID), update_info())

    assert read_row(host_db).container_id == COMPOSITE_KEY


class _RacingInsert:
    """Inserts the winning row after the checker's lookup missed, just before its own flush."""

    def __init__(self, db):
        self._db = db
        self._done = False

    def __call__(self, session, flush_context, instances):
        if self._done or not any(isinstance(obj, ContainerUpdate) for obj in session.new):
            return
        self._done = True
        with self._db.engine.begin() as connection:
            connection.execute(ContainerUpdate.__table__.insert().values(
                container_id=COMPOSITE_KEY, host_id=HOST_ID, current_image="winner:1", current_digest=CURRENT,
                update_available=False, floating_tag_mode="patch",
            ))


def test_store_retry_updates_concurrently_inserted_row(host_db):
    racing_insert = _RacingInsert(host_db)
    event.listen(Session, "before_flush", racing_insert)
    try:
        UpdateChecker(db=host_db)._store_update_info(container_dict(), update_info(update_available=True))
    finally:
        event.remove(Session, "before_flush", racing_insert)

    row = read_row(host_db)
    assert row.update_available is True
    assert row.current_image == "app:1.0.0"
    assert row.floating_tag_mode == "patch"


def test_store_retry_reraises_when_row_vanished(host_db):
    racing_insert = _RacingInsert(host_db)

    def delete_winner(session):
        with host_db.engine.begin() as connection:
            connection.execute(ContainerUpdate.__table__.delete().where(
                ContainerUpdate.container_id == COMPOSITE_KEY
            ))

    event.listen(Session, "before_flush", racing_insert)
    event.listen(Session, "after_rollback", delete_winner)
    try:
        with pytest.raises(IntegrityError):
            UpdateChecker(db=host_db)._store_update_info(container_dict(), update_info())
    finally:
        event.remove(Session, "before_flush", racing_insert)
        event.remove(Session, "after_rollback", delete_winner)


def test_previous_digest_absent_returns_none(host_db):
    assert UpdateChecker(db=host_db)._get_previous_digest(container_dict()) is None


@pytest.mark.parametrize("container_id", [CONTAINER_ID, FULL_ID])
def test_previous_digest_read_for_short_and_full_id(host_db, container_id):
    existing_row(host_db, latest_digest=LATEST)

    assert UpdateChecker(db=host_db)._get_previous_digest(container_dict(id=container_id)) == LATEST


def set_skip_compose(db, enabled):
    with db.get_session() as session:
        session.query(GlobalSettings).first().skip_compose_containers = enabled
        session.commit()


def add_ignore_policy(db, pattern):
    with db.get_session() as session:
        session.add(UpdatePolicy(category="custom", pattern=pattern, enabled=True, action="ignore"))
        session.commit()


def agent_container(container_id=CONTAINER_ID, name="app", image="app:stable", digest_value=CURRENT, labels=None):
    return container_dict(image, id=container_id, name=name, labels=labels or {},
                          repo_digests=[f"{image.split(':')[0]}@{digest_value}"])


def loop_checker(db, containers, routes):
    monitor = make_monitor(containers=[monitored_container(c) for c in containers])
    checker = UpdateChecker(db=db, monitor=monitor)
    checker.registry = FakeRegistry(routes)
    return checker


def record_call_order(checker):
    """Wraps the store and event steps so tests can assert their order and gating."""
    order = []

    def wrap(name):
        real = getattr(checker, name)

        def recording(*args, **kwargs):
            order.append(name)
            return real(*args, **kwargs)
        return recording

    checker._get_previous_digest = wrap("_get_previous_digest")
    checker._store_update_info = wrap("_store_update_info")
    checker._create_update_event = wrap("_create_update_event")
    return order


async def test_loop_without_update_stores_and_emits_nothing(host_db, event_bus_stub):
    container = agent_container(digest_value=LATEST)
    checker = loop_checker(host_db, [container], {"app:stable": registry_result(LATEST)})
    order = record_call_order(checker)

    stats = await checker.check_all_containers()

    assert order == ["_get_previous_digest", "_store_update_info"]
    assert read_row(host_db).update_available is False
    assert event_bus_stub.emit.await_count == 0
    assert stats == {"total": 1, "checked": 1, "updates_found": 0, "errors": 0}


async def test_loop_with_update_stores_then_emits(host_db, event_bus_stub):
    checker = loop_checker(host_db, [agent_container()], {"app:stable": registry_result(LATEST)})
    order = record_call_order(checker)

    stats = await checker.check_all_containers()

    assert order == ["_get_previous_digest", "_store_update_info", "_create_update_event"]
    assert read_row(host_db).update_available is True
    assert event_bus_stub.emit.await_count == 1
    assert stats == {"total": 1, "checked": 1, "updates_found": 1, "errors": 0}


@pytest.mark.parametrize("stored_latest,expected_events", [(LATEST, 0), (digest("7"), 1)])
async def test_loop_compares_new_latest_with_the_previously_stored_one(
    host_db, event_bus_stub, stored_latest, expected_events
):
    existing_row(host_db, latest_digest=stored_latest)
    checker = loop_checker(host_db, [agent_container()], {"app:stable": registry_result(LATEST)})

    await checker.check_all_containers()

    assert event_bus_stub.emit.await_count == expected_events


COMPOSE_LABELS = {"com.docker.compose.project": "stack"}


def skip_scenario_containers():
    return [
        agent_container("aaaaaaaaaaaa", name="plain"),
        agent_container("bbbbbbbbbbbb", name="composed", labels=COMPOSE_LABELS),
        agent_container("cccccccccccc", name="ignored-app"),
    ]


async def test_loop_skips_compose_containers_when_configured(host_db):
    set_skip_compose(host_db, True)
    add_ignore_policy(host_db, "ignored-app")
    checker = loop_checker(host_db, skip_scenario_containers(), {"app:stable": registry_result(LATEST)})

    stats = await checker.check_all_containers()

    assert stored_names(host_db) == ["plain"]
    assert stats == {"total": 3, "checked": 1, "updates_found": 1, "errors": 0}


async def test_loop_checks_compose_containers_when_not_configured(host_db):
    set_skip_compose(host_db, False)
    add_ignore_policy(host_db, "ignored-app")
    checker = loop_checker(host_db, skip_scenario_containers(), {"app:stable": registry_result(LATEST)})

    stats = await checker.check_all_containers()

    assert stored_names(host_db) == ["composed", "plain"]
    assert stats == {"total": 3, "checked": 2, "updates_found": 2, "errors": 0}


async def test_loop_continues_after_a_failing_container(host_db):
    containers = [
        agent_container("aaaaaaaaaaaa", name="broken", image="broken:stable"),
        agent_container("bbbbbbbbbbbb", name="healthy"),
    ]
    checker = loop_checker(host_db, containers, {
        "broken:stable": RuntimeError("registry exploded"),
        "app:stable": registry_result(LATEST),
    })

    stats = await checker.check_all_containers()

    assert stored_names(host_db) == ["healthy"]
    assert stats == {"total": 2, "checked": 1, "updates_found": 1, "errors": 1}


async def test_loop_counts_nothing_for_an_unresolvable_registry_image(host_db):
    container = agent_container(image="ghcr.io/org/gone:1.0")
    checker = loop_checker(host_db, [container], {"ghcr.io/org/gone:1.0": None})

    stats = await checker.check_all_containers()

    assert stats == {"total": 1, "checked": 0, "updates_found": 0, "errors": 0}


async def test_single_check_with_update_stores_then_emits(host_db, event_bus_stub):
    checker = loop_checker(host_db, [agent_container()], {"app:stable": registry_result(LATEST)})
    order = record_call_order(checker)

    result = await checker.check_single_container(HOST_ID, CONTAINER_ID)

    assert order == ["_get_previous_digest", "_store_update_info", "_create_update_event"]
    assert result["update_available"] is True
    assert read_row(host_db).update_available is True
    assert event_bus_stub.emit.await_count == 1


async def test_single_check_without_update_stores_and_emits_nothing(host_db, event_bus_stub):
    container = agent_container(digest_value=LATEST)
    checker = loop_checker(host_db, [container], {"app:stable": registry_result(LATEST)})
    order = record_call_order(checker)

    result = await checker.check_single_container(HOST_ID, CONTAINER_ID)

    assert order == ["_get_previous_digest", "_store_update_info"]
    assert result["update_available"] is False
    assert event_bus_stub.emit.await_count == 0


@pytest.mark.parametrize("bypass_cache,cache_consulted", [(True, False), (False, True)])
async def test_single_check_forwards_bypass_cache(host_db, bypass_cache, cache_consulted):
    checker = loop_checker(host_db, [agent_container()], {"app:stable": registry_result(LATEST)})

    with patch.object(host_db, "get_cached_image_digest", wraps=host_db.get_cached_image_digest) as cache_lookup:
        await checker.check_single_container(HOST_ID, CONTAINER_ID, bypass_cache=bypass_cache)

    assert cache_lookup.called is cache_consulted


async def test_stored_tracking_mode_is_read_by_composite_key(host_db):
    existing_row(host_db, floating_tag_mode="minor")
    checker = loop_checker(host_db, [], {"nginx:1": registry_result(LATEST)})

    result = await checker._check_container_update(agent_container(image="nginx:1.25.3"))

    assert checker.registry.refs() == ["nginx:1"]
    assert result["floating_tag_mode"] == "minor"


@pytest.mark.parametrize("labels,expected", [
    ({"com.docker.compose.project": "stack"}, True),
    ({"maintainer": "someone"}, False),
    ({}, False),
])
def test_is_compose_container(labels, expected):
    assert UpdateChecker(db=None)._is_compose_container({"labels": labels}) is expected


async def test_credentials_row_is_passed_to_the_registry(host_db):
    with host_db.get_session() as session:
        session.add(RegistryCredential(registry_url="ghcr.io", username="robot", password_encrypted="stored"))
        session.commit()
    image = "ghcr.io/org/app:stable"
    checker = loop_checker(host_db, [], {image: registry_result(LATEST)})

    with patch("utils.registry_credentials.decrypt_password", return_value="secret"):
        await checker._check_container_update(agent_container(image=image))

    assert checker.registry.calls == [(image, {"auth": {"username": "robot", "password": "secret"}})]
