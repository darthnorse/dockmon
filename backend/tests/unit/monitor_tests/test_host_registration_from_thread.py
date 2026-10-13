"""Host add/edit run under asyncio.to_thread; their Go-service registration must still run.

The stats client's session is bound to the application loop, so registration
scheduled from the worker thread has to be handed back to that loop.
"""
import asyncio
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

import docker_monitor.monitor as monitor_module
from database import DockerHostDB
from docker_monitor.monitor import DockerMonitor
from models.docker_models import DockerHost, DockerHostConfig

HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
SYS_INFO = {
    'os_type': 'linux', 'os_version': 'Debian', 'kernel_version': '6.12',
    'docker_version': '28.0', 'daemon_started_at': None, 'total_memory': 1024,
    'num_cpus': 2, 'is_podman': False, 'engine_id': 'engine-1',
}


@pytest.fixture
def stats_client(monkeypatch):
    client = types.SimpleNamespace(
        add_docker_host=AsyncMock(return_value=True),
        add_event_host=AsyncMock(return_value=True),
        remove_docker_host=AsyncMock(return_value=True),
        remove_event_host=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(monitor_module, "get_stats_client", lambda: client)
    return client


@pytest.fixture
def monitor(db, monkeypatch):
    monkeypatch.setattr(monitor_module.docker, "DockerClient", MagicMock())
    monkeypatch.setattr(monitor_module, "_fetch_system_info_from_docker", lambda client, name: dict(SYS_INFO))
    mon = DockerMonitor.__new__(DockerMonitor)
    mon.db = db
    mon.hosts = {}
    mon.clients = {}
    mon.manager = None
    mon._main_loop = None
    mon.event_logger = MagicMock()
    mon.settings = types.SimpleNamespace(connection_timeout=5)
    mon._validate_host_security = MagicMock(return_value="insecure")
    return mon


async def _drain_loop():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_host_added_from_worker_thread_is_registered(monitor, stats_client):
    monitor.bind_event_loop(asyncio.get_running_loop())

    host = await asyncio.to_thread(monitor.add_host, DockerHostConfig(name="remote", url="tcp://10.0.0.9:2375"))
    await _drain_loop()

    stats_client.add_docker_host.assert_awaited_once()
    assert stats_client.add_docker_host.await_args.args[0] == host.id
    stats_client.add_event_host.assert_awaited_once()
    assert stats_client.add_event_host.await_args.args[0] == host.id


async def test_host_edited_from_worker_thread_is_reregistered(monitor, db, stats_client):
    monitor.bind_event_loop(asyncio.get_running_loop())
    with db.get_session() as session:
        session.add(DockerHostDB(id=HOST_ID, name="remote", url="tcp://10.0.0.9:2375", connection_type="remote"))
        session.commit()
    monitor.hosts[HOST_ID] = DockerHost(id=HOST_ID, name="remote", url="tcp://10.0.0.9:2375", status="online")
    monitor.clients[HOST_ID] = MagicMock()

    await asyncio.to_thread(monitor.update_host, HOST_ID, DockerHostConfig(name="remote", url="tcp://10.0.0.10:2375"))
    await _drain_loop()

    stats_client.add_docker_host.assert_awaited_once()
    assert stats_client.add_docker_host.await_args.args[2] == "tcp://10.0.0.10:2375"
    stats_client.remove_event_host.assert_awaited_once_with(HOST_ID)
    stats_client.add_event_host.assert_awaited_once()


async def test_add_before_loop_is_bound_defers_registration(monitor, stats_client):
    """Startup adds hosts before the loop is bound; monitor_containers registers them later."""
    await asyncio.to_thread(monitor.add_host, DockerHostConfig(name="local", url="tcp://10.0.0.11:2375"))
    await _drain_loop()

    stats_client.add_docker_host.assert_not_awaited()


async def test_failure_scheduled_from_worker_thread_is_logged(monitor, caplog):
    monitor.bind_event_loop(asyncio.get_running_loop())

    async def boom():
        raise RuntimeError("stats service exploded")

    assert await asyncio.to_thread(monitor._run_on_main_loop, boom())
    await _drain_loop()

    assert "stats service exploded" in caplog.text
