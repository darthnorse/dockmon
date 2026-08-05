"""A host is either agent-owned or Docker-registered, never both (issue #243).

The stats-service host cache is written by the aggregator for registered Docker
hosts and by the agent ingest handler for agent hosts, under the same key. If a
host ever holds both roles the two writers race and the evaluator sees whichever
landed last, so every transition to agent must unregister the Docker client.
"""
import asyncio
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

import database as database_module
from database import DatabaseManager, DockerHostDB
from docker_monitor.monitor import DockerMonitor
from models.docker_models import DockerHost, DockerHostConfig

HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database_module._database_manager_instance = None
    db_manager = DatabaseManager(db_path=db_path)
    try:
        yield db_manager
    finally:
        if hasattr(db_manager, "engine"):
            db_manager.engine.dispose()
        database_module._database_manager_instance = None


@pytest.fixture
def stats_client(monkeypatch):
    """Stub the Go stats-service client and record unregistrations."""
    client = types.SimpleNamespace(
        remove_docker_host=AsyncMock(return_value=True),
        remove_event_host=AsyncMock(return_value=True),
        add_docker_host=AsyncMock(return_value=True),
        add_event_host=AsyncMock(return_value=True),
    )
    import docker_monitor.monitor as monitor_module
    monkeypatch.setattr(monitor_module, "get_stats_client", lambda: client)
    return client


@pytest.fixture
def monitor(db, monkeypatch):
    mon = DockerMonitor.__new__(DockerMonitor)
    mon.db = db
    mon.hosts = {}
    mon.clients = {}
    mon.manager = None
    mon._main_loop = None
    mon.event_logger = MagicMock()
    return mon


def _docker_host_row(db, connection_type="tcp"):
    with db.get_session() as session:
        session.add(DockerHostDB(
            id=HOST_ID,
            name="was-docker",
            url="tcp://10.0.0.5:2376",
            connection_type=connection_type,
        ))
        session.commit()


def _existing_docker_host(monitor):
    host = DockerHost(
        id=HOST_ID,
        name="was-docker",
        url="tcp://10.0.0.5:2376",
        connection_type="tcp",
        status="online",
    )
    monitor.hosts[HOST_ID] = host
    monitor.clients[HOST_ID] = MagicMock()
    return host


async def test_agent_taking_over_docker_host_unregisters_it(monitor, db, stats_client):
    """add_agent_host must repair a stale Docker registration, not return early."""
    _docker_host_row(db)
    _existing_docker_host(monitor)

    monitor.add_agent_host(host_id=HOST_ID, name="now-agent")
    await asyncio.sleep(0)  # let the scheduled unregistration run

    stats_client.remove_docker_host.assert_awaited_once_with(HOST_ID)
    assert monitor.hosts[HOST_ID].connection_type == "agent"
    assert monitor.hosts[HOST_ID].url == "agent://"
    assert monitor.hosts[HOST_ID].status == "online"
    assert HOST_ID not in monitor.clients


async def test_takeover_persists_connection_type(monitor, db, stats_client):
    _docker_host_row(db)
    _existing_docker_host(monitor)

    monitor.add_agent_host(host_id=HOST_ID, name="now-agent")
    await asyncio.sleep(0)

    with db.get_session() as session:
        row = session.query(DockerHostDB).filter_by(id=HOST_ID).first()
        assert row.connection_type == "agent"
        assert row.url == "agent://"


async def test_agent_reconnect_does_not_unregister(monitor, db, stats_client):
    """The common path - an agent host reconnecting - must stay a no-op."""
    monitor.hosts[HOST_ID] = DockerHost(
        id=HOST_ID, name="agent-box", url="agent://",
        connection_type="agent", status="offline",
    )

    monitor.add_agent_host(host_id=HOST_ID, name="agent-box")
    await asyncio.sleep(0)

    stats_client.remove_docker_host.assert_not_awaited()
    assert monitor.hosts[HOST_ID].status == "online"


async def test_update_host_to_agent_url_unregisters_docker_host(monitor, db, stats_client):
    """Editing a host to agent:// must drop its Docker registration.

    update_host returns early for agent:// URLs, so the cleanup has to live on
    that branch - the later re-registration block never sees an agent host.
    """
    _docker_host_row(db)
    _existing_docker_host(monitor)
    monitor.db.update_host = MagicMock(return_value=types.SimpleNamespace(
        os_type=None, os_version=None, kernel_version=None, docker_version=None,
        daemon_started_at=None, total_memory=None, num_cpus=None,
    ))
    monitor.event_logger = MagicMock()

    config = DockerHostConfig(name="now-agent", url="agent://")
    host = monitor.update_host(HOST_ID, config)
    await asyncio.sleep(0)

    assert host.connection_type == "agent"
    stats_client.remove_docker_host.assert_awaited_once_with(HOST_ID)
    stats_client.remove_event_host.assert_awaited_once_with(HOST_ID)
