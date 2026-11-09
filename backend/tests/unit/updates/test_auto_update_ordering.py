"""Auto-update runs dependents before providers and skips rows with no live container."""

import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database import ContainerUpdate, DockerHostDB
from updates.update_executor import UpdateExecutor


def container(name, short_id, host_id, network_mode=None):
    return SimpleNamespace(
        name=name, id=short_id, short_id=short_id, host_id=host_id, network_mode=network_mode
    )


@pytest.fixture
def host_id(db):
    return add_host(db)


def add_host(db):
    new_id = str(uuid.uuid4())
    with db.get_session() as session:
        session.add(DockerHostDB(
            id=new_id,
            name=f"host-{new_id[:4]}",
            url="agent://",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        session.commit()
    return new_id


def add_row(db, host_id, short_id, name, update_available=True, auto_update_enabled=True, check_status=None):
    with db.get_session() as session:
        session.add(ContainerUpdate(
            container_id=f"{host_id}:{short_id}",
            host_id=host_id,
            container_name=name,
            current_image=f"{name}:latest",
            current_digest="sha256:old",
            latest_image=f"{name}:latest" if update_available else None,
            latest_digest="sha256:new" if update_available else None,
            update_available=update_available,
            auto_update_enabled=auto_update_enabled,
            check_status=check_status,
        ))
        session.commit()


def make_executor(db, discovered):
    monitor = MagicMock()
    monitor.get_containers = AsyncMock(return_value=discovered)
    with patch("updates.update_executor.UpdateClient"):
        executor = UpdateExecutor(db=db, monitor=monitor)
    executor.timeline = []

    async def update_container(host_id, container_id, update_record, **kwargs):
        executor.timeline.append(("start", container_id))
        executor.timeline.append(("end", container_id))
        return True

    executor.update_container = update_container
    return executor


@pytest.mark.asyncio
async def test_dependent_goes_before_its_provider(db, host_id):
    add_row(db, host_id, "aaaaaaaaaaaa", "gluetun")
    add_row(db, host_id, "bbbbbbbbbbbb", "qbittorrent")
    executor = make_executor(db, [
        container("gluetun", "aaaaaaaaaaaa", host_id, "bridge"),
        container("qbittorrent", "bbbbbbbbbbbb", host_id, "container:aaaaaaaaaaaa" + "f" * 52),
    ])

    stats = await executor.execute_auto_updates()

    timeline = executor.timeline
    assert timeline.index(("end", "bbbbbbbbbbbb")) < timeline.index(("start", "aaaaaaaaaaaa"))
    assert stats == {"total": 2, "successful": 2, "failed": 0, "skipped": 0}


@pytest.mark.asyncio
async def test_row_for_a_removed_container_is_skipped(db, host_id):
    add_row(db, host_id, "aaaaaaaaaaaa", "live")
    add_row(db, host_id, "bbbbbbbbbbbb", "gone")
    executor = make_executor(db, [container("live", "aaaaaaaaaaaa", host_id)])

    stats = await executor.execute_auto_updates()

    assert ("start", "bbbbbbbbbbbb") not in executor.timeline
    assert stats == {"total": 2, "successful": 1, "failed": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_host_that_returned_nothing_is_skipped_with_a_warning(db, host_id, caplog):
    silent_host = add_host(db)
    add_row(db, host_id, "aaaaaaaaaaaa", "live")
    add_row(db, silent_host, "bbbbbbbbbbbb", "other")
    add_row(db, silent_host, "cccccccccccc", "another")
    executor = make_executor(db, [container("live", "aaaaaaaaaaaa", host_id)])

    stats = await executor.execute_auto_updates()

    assert stats == {"total": 3, "successful": 1, "failed": 0, "skipped": 2}
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and silent_host in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_failed_discovery_updates_nothing(db, host_id):
    add_row(db, host_id, "aaaaaaaaaaaa", "gluetun")
    executor = make_executor(db, [])
    executor.monitor.get_containers.side_effect = RuntimeError("boom")

    stats = await executor.execute_auto_updates()

    assert executor.timeline == []
    assert stats == {"total": 1, "successful": 0, "failed": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_recreated_dependent_is_picked_up_on_a_later_cycle(db, host_id):
    add_row(db, host_id, "bbbbbbbbbbbb", "qbittorrent")
    db.reattach_update_settings_for_container(
        host_id=host_id,
        container_id="cccccccccccc",
        container_name="qbittorrent",
        current_image="qbittorrent:latest",
    )
    with db.get_session() as session:
        new_row = session.query(ContainerUpdate).filter_by(container_id=f"{host_id}:cccccccccccc").one()
        assert new_row.auto_update_enabled is True
        assert new_row.update_available is False
        new_row.update_available = True
        new_row.latest_image = "qbittorrent:latest"
        new_row.latest_digest = "sha256:newer"
        session.commit()
    executor = make_executor(db, [container("qbittorrent", "cccccccccccc", host_id)])

    stats = await executor.execute_auto_updates()

    assert ("start", "cccccccccccc") in executor.timeline
    assert ("start", "bbbbbbbbbbbb") not in executor.timeline
    assert stats == {"total": 2, "successful": 1, "failed": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_malformed_row_does_not_stop_the_cycle(db, host_id):
    add_row(db, host_id, "a" * 64, "legacy")
    add_row(db, host_id, "bbbbbbbbbbbb", "live")
    executor = make_executor(db, [container("live", "bbbbbbbbbbbb", host_id)])

    stats = await executor.execute_auto_updates()

    assert stats == {"total": 2, "successful": 1, "failed": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_unverified_image_is_skipped_and_logged(db, host_id, caplog):
    caplog.set_level(logging.INFO, logger="updates.update_executor")
    add_row(db, host_id, "aaaaaaaaaaaa", "local-build", check_status="unverified_image")
    add_row(db, host_id, "bbbbbbbbbbbb", "pulled")
    executor = make_executor(db, [container("local-build", "aaaaaaaaaaaa", host_id),
                                  container("pulled", "bbbbbbbbbbbb", host_id)])

    stats = await executor.execute_auto_updates()

    assert ("start", "aaaaaaaaaaaa") not in executor.timeline
    assert ("start", "bbbbbbbbbbbb") in executor.timeline
    assert stats == {"total": 2, "successful": 1, "failed": 0, "skipped": 1}
    skips = [r.getMessage() for r in caplog.records if "local-build" in r.getMessage()]
    assert len(skips) == 1
    assert "can't confirm" in skips[0]


@pytest.mark.asyncio
async def test_row_marked_after_selection_is_skipped(db, host_id):
    add_row(db, host_id, "aaaaaaaaaaaa", "app")
    executor = make_executor(db, [container("app", "aaaaaaaaaaaa", host_id)])
    discovered = executor.monitor.get_containers.return_value

    async def mark_then_list():
        with db.get_session() as session:
            session.query(ContainerUpdate).one().check_status = "unverified_image"
            session.commit()
        return discovered

    executor.monitor.get_containers = mark_then_list

    stats = await executor.execute_auto_updates()

    assert executor.timeline == []
    assert stats == {"total": 1, "successful": 0, "failed": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_only_unverified_rows_still_count_when_discovery_fails(db, host_id):
    add_row(db, host_id, "aaaaaaaaaaaa", "local-build", check_status="unverified_image")
    add_row(db, host_id, "bbbbbbbbbbbb", "pulled")
    executor = make_executor(db, [])
    executor.monitor.get_containers.side_effect = RuntimeError("boom")

    stats = await executor.execute_auto_updates()

    assert stats == {"total": 2, "successful": 0, "failed": 0, "skipped": 2}


@pytest.mark.asyncio
async def test_only_unverified_rows_need_no_discovery(db, host_id):
    add_row(db, host_id, "aaaaaaaaaaaa", "local-build", check_status="unverified_image")
    executor = make_executor(db, [container("local-build", "aaaaaaaaaaaa", host_id)])

    stats = await executor.execute_auto_updates()

    executor.monitor.get_containers.assert_not_awaited()
    assert stats == {"total": 1, "successful": 0, "failed": 0, "skipped": 1}
