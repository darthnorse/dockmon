"""Batch updates run dependents before their providers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from batch_manager import BatchJobManager
from database import BatchJob

HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"


def container(name, short_id, network_mode=None):
    return SimpleNamespace(
        name=name, id=short_id, short_id=short_id, host_id=HOST_ID, host_name="radarr", network_mode=network_mode
    )


PROVIDER = container("gluetun", "16678699c163", "bridge")
DEPENDENT = container("qbittorrent", "395e946d84cc", "container:16678699c163" + "f" * 52)
UNRELATED = container("radarr", "e14c178c18f0", "bridge")


def key(c):
    return f"{c.host_id}:{c.short_id}"


def make_manager(db, discovered, failing=()):
    monitor = MagicMock()
    monitor.get_containers = AsyncMock(return_value=discovered)
    manager = BatchJobManager(db, monitor, MagicMock())
    manager._broadcast_job_update = AsyncMock()
    manager._broadcast_item_update = AsyncMock()
    manager._emit_batch_job_event = AsyncMock()
    manager.timeline = []

    async def execute_action(action, host_id, container_id, container_name, params):
        manager.timeline.append(("start", container_name))
        await asyncio.sleep(0.01)
        manager.timeline.append(("end", container_name))
        if container_name in failing:
            return {"status": "error", "message": "Container update failed"}
        return {"status": "success", "message": "ok"}

    manager._execute_action = execute_action
    return manager


async def run_job(manager, selected, action="update-containers"):
    job_id = await manager.create_job(None, "container", action, [key(c) for c in selected])
    await manager.active_jobs[job_id]
    return job_id


def assert_all_succeeded(db, job_id):
    with db.get_session() as session:
        assert session.query(BatchJob).filter_by(id=job_id).one().status == "completed"


def hold_items_until_two_started(manager):
    """Items only succeed if they overlap, so a test fails if they ran one after another."""
    gate = asyncio.Event()
    started = []

    async def execute_action(action, host_id, container_id, container_name, params):
        started.append(container_name)
        if len(started) == 2:
            gate.set()
        await asyncio.wait_for(gate.wait(), timeout=2)
        return {"status": "success", "message": "ok"}

    manager._execute_action = execute_action
    return started


@pytest.mark.asyncio
async def test_a_selected_pair_runs_dependent_first(db):
    manager = make_manager(db, [PROVIDER, DEPENDENT, UNRELATED])

    await run_job(manager, [PROVIDER, DEPENDENT, UNRELATED])

    timeline = manager.timeline
    assert timeline.index(("end", "qbittorrent")) < timeline.index(("start", "gluetun"))
    assert timeline.index(("end", "radarr")) < timeline.index(("start", "gluetun"))


@pytest.mark.asyncio
async def test_a_failed_dependent_does_not_stop_its_provider(db):
    manager = make_manager(db, [PROVIDER, DEPENDENT], failing=["qbittorrent"])

    job_id = await run_job(manager, [PROVIDER, DEPENDENT])

    assert ("start", "gluetun") in manager.timeline
    with db.get_session() as session:
        job = session.query(BatchJob).filter_by(id=job_id).one()
        assert job.status == "partial"
        assert job.success_items == 1
        assert job.error_items == 1


@pytest.mark.asyncio
async def test_an_unselected_pair_does_not_affect_the_batch(db):
    manager = make_manager(db, [PROVIDER, DEPENDENT, UNRELATED])
    started = hold_items_until_two_started(manager)

    job_id = await run_job(manager, [PROVIDER, UNRELATED])

    assert sorted(started) == ["gluetun", "radarr"]
    assert_all_succeeded(db, job_id)


@pytest.mark.asyncio
async def test_other_actions_are_not_ordered(db):
    manager = make_manager(db, [PROVIDER, DEPENDENT])
    started = hold_items_until_two_started(manager)

    job_id = await run_job(manager, [PROVIDER, DEPENDENT], action="restart")

    assert len(started) == 2
    assert_all_succeeded(db, job_id)
