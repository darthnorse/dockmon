"""stats-service keeps hosts and streams in memory; a restart must be reconciled without restarting DockMon."""
import asyncio
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

import docker_monitor.monitor as monitor_module
from database import DockerHostDB
from docker_monitor.monitor import DockerMonitor
from docker_monitor.stats_manager import StatsManager
from models.docker_models import DockerHost

LOCAL_ID = "0b8d2fdd-8789-464b-950f-448723cbc0bb"
REMOTE_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
AGENT_ID = "14253255-e0d8-4530-a9fc-36e845961a0c"
LOCAL_STREAM = f"{LOCAL_ID}:abc123def456"


@pytest.fixture
def stats_client(monkeypatch):
    client = types.SimpleNamespace(
        get_instance_id=AsyncMock(return_value="instance-a"),
        add_docker_host=AsyncMock(return_value=True),
        add_event_host=AsyncMock(return_value=True),
        remove_docker_host=AsyncMock(return_value=True),
        remove_event_host=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(monitor_module, "get_stats_client", lambda: client)
    return client


@pytest.fixture
def monitor(db):
    with db.get_session() as session:
        session.add(DockerHostDB(id=LOCAL_ID, name="local", url="unix:///var/run/docker.sock", connection_type="local",
                                 num_cpus=8, total_memory=16_000))
        session.add(DockerHostDB(id=REMOTE_ID, name="remote", url="tcp://10.0.0.9:2376", connection_type="remote",
                                 tls_ca="CA", tls_cert="CERT", tls_key="KEY", num_cpus=4, total_memory=8_000))
        session.add(DockerHostDB(id=AGENT_ID, name="agent", url="agent://", connection_type="agent"))
        session.commit()
    mon = DockerMonitor.__new__(DockerMonitor)
    mon.db = db
    mon.hosts = {
        LOCAL_ID: DockerHost(id=LOCAL_ID, name="local", url="unix:///var/run/docker.sock", status="online"),
        REMOTE_ID: DockerHost(id=REMOTE_ID, name="remote", url="tcp://10.0.0.9:2376", status="online"),
        AGENT_ID: DockerHost(id=AGENT_ID, name="agent", url="agent://", connection_type="agent", status="online"),
    }
    mon.stats_manager = StatsManager()
    mon._stats_instance_id = None
    mon._stats_pending_hosts = set()
    mon._stats_retry_at = 0.0
    return mon


def registered_ids(mock):
    return sorted(call.args[0] for call in mock.await_args_list)


def allow_retry_now(monitor):
    monitor._stats_retry_at = 0.0


async def test_first_instance_registers_every_socket_host(monitor, stats_client):
    await monitor._reconcile_stats_service()

    assert registered_ids(stats_client.add_docker_host) == sorted([LOCAL_ID, REMOTE_ID])
    assert registered_ids(stats_client.add_event_host) == sorted([LOCAL_ID, REMOTE_ID])
    assert monitor._stats_instance_id == "instance-a"
    assert monitor._stats_pending_hosts == set()


async def test_registration_sends_current_host_metadata(monitor, stats_client):
    await monitor._reconcile_stats_service()

    calls = {call.args[0]: call for call in stats_client.add_docker_host.await_args_list}
    assert calls[REMOTE_ID].args[1:] == ("remote", "tcp://10.0.0.9:2376", "CA", "CERT", "KEY", 4, 8_000, False)
    assert calls[LOCAL_ID].args[-1] is True
    event_call = next(c for c in stats_client.add_event_host.await_args_list if c.args[0] == REMOTE_ID)
    assert event_call.args[1:] == ("remote", "tcp://10.0.0.9:2376", "CA", "CERT", "KEY")


async def test_same_instance_is_left_alone(monitor, stats_client):
    await monitor._reconcile_stats_service()
    stats_client.add_docker_host.reset_mock()

    await monitor._reconcile_stats_service()

    stats_client.add_docker_host.assert_not_awaited()


async def test_restarted_instance_is_reregistered_and_streams_restart(monitor, stats_client):
    await monitor._reconcile_stats_service()
    monitor.stats_manager.streaming_containers = {LOCAL_STREAM}
    stats_client.add_docker_host.reset_mock()
    stats_client.get_instance_id.return_value = "instance-b"

    await monitor._reconcile_stats_service()

    assert registered_ids(stats_client.add_docker_host) == sorted([LOCAL_ID, REMOTE_ID])
    assert monitor.stats_manager.streaming_containers == set()
    assert monitor._stats_instance_id == "instance-b"


async def test_unreachable_service_changes_nothing(monitor, stats_client):
    stats_client.get_instance_id.return_value = None

    await monitor._reconcile_stats_service()

    stats_client.add_docker_host.assert_not_awaited()
    assert monitor._stats_instance_id is None


async def test_a_failing_host_is_retried_alone_without_touching_streams(monitor, stats_client):
    async def reject_remote(host_id, *args):
        return host_id != REMOTE_ID

    stats_client.add_docker_host.side_effect = reject_remote
    await monitor._reconcile_stats_service()
    assert monitor._stats_instance_id == "instance-a"
    assert monitor._stats_pending_hosts == {REMOTE_ID}

    monitor.stats_manager.streaming_containers = {LOCAL_STREAM}
    stats_client.add_docker_host.reset_mock()
    stats_client.add_event_host.reset_mock()
    await monitor._reconcile_stats_service()
    stats_client.add_docker_host.assert_not_awaited()

    allow_retry_now(monitor)
    stats_client.add_docker_host.side_effect = None
    await monitor._reconcile_stats_service()

    assert registered_ids(stats_client.add_docker_host) == [REMOTE_ID]
    assert registered_ids(stats_client.add_event_host) == [REMOTE_ID]
    assert monitor.stats_manager.streaming_containers == {LOCAL_STREAM}
    assert monitor._stats_pending_hosts == set()


async def test_marking_one_host_stale_retries_only_that_host(monitor, stats_client):
    await monitor._reconcile_stats_service()
    stats_client.add_docker_host.reset_mock()
    monitor.stats_manager.streaming_containers = {LOCAL_STREAM}

    monitor.mark_stats_registration_stale(REMOTE_ID)
    allow_retry_now(monitor)
    await monitor._reconcile_stats_service()

    assert registered_ids(stats_client.add_docker_host) == [REMOTE_ID]
    assert monitor.stats_manager.streaming_containers == {LOCAL_STREAM}


async def test_a_host_marked_stale_during_a_full_pass_is_still_retried(monitor, stats_client):
    async def mark_late_host(host_id, *args):
        if host_id == LOCAL_ID:
            monitor.mark_stats_registration_stale("late-host")
        return True

    stats_client.add_docker_host.side_effect = mark_late_host
    await monitor._reconcile_stats_service()

    assert monitor._stats_instance_id == "instance-a"
    assert "late-host" in monitor._stats_pending_hosts


async def test_host_removed_during_registration_is_unregistered_on_retry(monitor, stats_client):
    async def remove_remote_while_registering(host_id, *args):
        if host_id == REMOTE_ID:
            monitor.hosts.pop(REMOTE_ID, None)
        return True

    stats_client.add_docker_host.side_effect = remove_remote_while_registering
    await monitor._reconcile_stats_service()
    assert monitor._stats_pending_hosts == {REMOTE_ID}

    allow_retry_now(monitor)
    await monitor._reconcile_stats_service()

    assert registered_ids(stats_client.remove_docker_host) == [REMOTE_ID]
    assert registered_ids(stats_client.remove_event_host) == [REMOTE_ID]
    assert monitor._stats_pending_hosts == set()


async def test_host_edited_during_registration_is_registered_again(monitor, stats_client):
    async def edit_remote_while_registering(host_id, *args):
        if host_id == REMOTE_ID and args[1] == "tcp://10.0.0.9:2376":
            monitor.hosts[REMOTE_ID] = DockerHost(id=REMOTE_ID, name="remote", url="tcp://10.0.0.10:2376", status="online")
        return True

    stats_client.add_docker_host.side_effect = edit_remote_while_registering
    await monitor._reconcile_stats_service()
    assert monitor._stats_pending_hosts == {REMOTE_ID}

    allow_retry_now(monitor)
    await monitor._reconcile_stats_service()

    last = [c for c in stats_client.add_docker_host.await_args_list if c.args[0] == REMOTE_ID][-1]
    assert last.args[2] == "tcp://10.0.0.10:2376"
    assert monitor._stats_pending_hosts == set()


async def test_host_converted_to_agent_during_registration_is_unregistered(monitor, stats_client):
    async def convert_remote_in_place(host_id, *args):
        if host_id == REMOTE_ID:
            monitor.hosts[REMOTE_ID].connection_type = "agent"
            monitor.hosts[REMOTE_ID].url = "agent://"
        return True

    stats_client.add_docker_host.side_effect = convert_remote_in_place
    await monitor._reconcile_stats_service()
    assert monitor._stats_pending_hosts == {REMOTE_ID}

    allow_retry_now(monitor)
    await monitor._reconcile_stats_service()

    assert registered_ids(stats_client.remove_docker_host) == [REMOTE_ID]
    assert registered_ids(stats_client.remove_event_host) == [REMOTE_ID]
    assert monitor._stats_pending_hosts == set()


async def test_failed_cleanup_of_a_removed_host_is_retried(monitor, stats_client):
    monitor.hosts.pop(REMOTE_ID)
    monitor.mark_stats_registration_stale(REMOTE_ID)
    await monitor._reconcile_stats_service()
    stats_client.remove_docker_host.return_value = False

    allow_retry_now(monitor)
    await monitor._reconcile_stats_service()
    assert monitor._stats_pending_hosts == {REMOTE_ID}

    stats_client.remove_docker_host.return_value = True
    allow_retry_now(monitor)
    await monitor._reconcile_stats_service()
    assert monitor._stats_pending_hosts == set()


async def test_reset_waits_for_an_in_progress_stream_sync(monitor):
    order = []
    monitor.stats_manager.streaming_containers = {"h:c"}

    async def register():
        order.append("register")

    async with monitor.stats_manager._streaming_lock:
        task = asyncio.create_task(monitor.stats_manager.reregister_and_reset(register))
        await asyncio.sleep(0)
        order.append("sync-finished")
    await task

    assert order == ["sync-finished", "register"]
    assert monitor.stats_manager.streaming_containers == set()


class StopLoop(Exception):
    pass


async def test_monitor_loop_survives_a_discovery_error_on_its_first_pass(monitor, stats_client, monkeypatch):
    stats_client.connect_event_stream = AsyncMock()
    monitor.get_containers = AsyncMock(side_effect=RuntimeError("docker unreachable"))
    monitor.manager = MagicMock()
    monitor.settings = types.SimpleNamespace(polling_interval=2)

    async def stop_after_first_iteration(_seconds):
        raise StopLoop

    monkeypatch.setattr(monitor_module.asyncio, "sleep", stop_after_first_iteration)

    with pytest.raises(StopLoop):
        await monitor.monitor_containers()

    assert monitor._stats_instance_id == "instance-a"
