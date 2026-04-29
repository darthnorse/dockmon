"""
Integration tests for the reattach-skip gate in container_discovery.

The discover_containers_for_host loop runs reattach_*_for_container
calls (sticky tags, update settings, health checks, deployment
metadata) only the first time it sees a given (host, container_id);
subsequent sweeps skip them. The seen-set is rewritten each sweep so
destroyed containers are pruned automatically. These tests lock that
behavior down via the agent path with a mocked AgentCommandExecutor.
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import database
from agent.command_executor import CommandResult, CommandStatus
from database import Agent, DatabaseManager, DockerHostDB
from docker_monitor.container_discovery import ContainerDiscovery
from models.docker_models import DockerHost


def _make_dc(container_id: str, name: str = "ctr", image: str = "nginx:1") -> dict:
    """Build the Docker API container-list dict shape the agent emits."""
    return {
        "Id": container_id + "f" * (64 - len(container_id)),  # pad to 64
        "Names": [f"/{name}"],
        "Image": image,
        "ImageID": "sha256:" + "a" * 64,
        "Created": int(datetime.now(timezone.utc).timestamp()),
        "State": "running",
        "Status": "Up 1 hour",
        "Labels": {},
        "Ports": [],
        "HostConfig": {"RestartPolicy": {"Name": "no"}},
        "NetworkSettings": {"Networks": {}},
        "Mounts": [],
        "RepoDigests": [],
        "StartedAt": "2026-04-29T10:00:00Z",
    }


@pytest.fixture
def db_manager():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_discovery_gating_")
    os.close(fd)
    database._database_manager_instance = None
    db = DatabaseManager(db_path=db_path)
    try:
        yield db
    finally:
        if hasattr(db, "engine"):
            db.engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass
        database._database_manager_instance = None


@pytest.fixture
def host_id(db_manager):
    host_id = str(uuid.uuid4())
    with db_manager.get_session() as session:
        session.add(DockerHostDB(
            id=host_id,
            name="test-host",
            url="agent://",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        session.add(Agent(
            id=str(uuid.uuid4()),
            host_id=host_id,
            engine_id=str(uuid.uuid4()),
            version="1.0.0",
            proto_version="1.1",
            capabilities={},
            status="online",
        ))
        session.commit()
    return host_id


@pytest.fixture
def discovery(db_manager, host_id):
    """
    ContainerDiscovery wired against the real test DB, with reattach
    methods replaced by call-counting spies.
    """
    host = DockerHost(
        id=host_id,
        name="test-host",
        url="agent://",
        connection_type="agent",
        status="online",
    )
    disc = ContainerDiscovery(
        db=db_manager,
        settings=None,
        hosts={host_id: host},
        clients={},
    )
    return disc


def _wrap_count(db_manager, method_name: str) -> dict:
    """
    Replace one of the db.reattach_*_for_container methods with a
    counting wrapper. Returns a dict with a "count" key updated each
    call. The original is restored when the dict is GC'd? — no, the
    test owns it. Tests should restore manually if they need
    cross-test isolation, but each test gets a fresh db_manager
    fixture so it's not necessary.
    """
    original = getattr(db_manager, method_name)
    counter = {"count": 0, "calls_for": []}

    def wrapper(*args, **kwargs):
        counter["count"] += 1
        counter["calls_for"].append(kwargs.get("container_id") or (args[1] if len(args) > 1 else None))
        return original(*args, **kwargs)

    setattr(db_manager, method_name, wrapper)
    return counter


class _MockExecutor:
    """Async executor double that returns a controllable CommandResult."""

    def __init__(self):
        self.next_response: list = []

    async def execute_command(self, agent_id, command, timeout=30.0):
        return CommandResult(
            status=CommandStatus.SUCCESS,
            success=True,
            response=list(self.next_response),
            error=None,
        )


@pytest.fixture
def mock_executor():
    return _MockExecutor()


@pytest.fixture
def patch_executor(mock_executor):
    with patch(
        "agent.command_executor.get_agent_command_executor",
        return_value=mock_executor,
    ):
        yield mock_executor


@pytest.fixture
def get_auto_restart():
    return lambda host_id, container_id: False


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_sweep_runs_reattach_for_every_container(
    db_manager, discovery, host_id, patch_executor, get_auto_restart
):
    update_settings = _wrap_count(db_manager, "reattach_update_settings_for_container")
    health_check = _wrap_count(db_manager, "reattach_http_health_check_for_container")
    deployment = _wrap_count(db_manager, "reattach_deployment_metadata_for_container")

    patch_executor.next_response = [
        _make_dc("aaaaaaaaaaaa", name="a"),
        _make_dc("bbbbbbbbbbbb", name="b"),
        _make_dc("cccccccccccc", name="c"),
    ]

    containers = await discovery.discover_containers_for_host(host_id, get_auto_restart)

    assert len(containers) == 3
    assert update_settings["count"] == 3
    assert health_check["count"] == 3
    assert deployment["count"] == 3
    assert discovery._reattached_container_ids[host_id] == {"aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"}


@pytest.mark.asyncio
async def test_second_sweep_skips_reattach_for_unchanged_containers(
    db_manager, discovery, host_id, patch_executor, get_auto_restart
):
    update_settings = _wrap_count(db_manager, "reattach_update_settings_for_container")

    patch_executor.next_response = [
        _make_dc("aaaaaaaaaaaa", name="a"),
        _make_dc("bbbbbbbbbbbb", name="b"),
    ]

    # First sweep: reattach runs for both.
    await discovery.discover_containers_for_host(host_id, get_auto_restart)
    assert update_settings["count"] == 2

    # Second sweep with the SAME containers: must invalidate the
    # @async_ttl_cache so the function actually runs again, then
    # assert no new reattach calls.
    discovery.discover_containers_for_host.invalidate()
    await discovery.discover_containers_for_host(host_id, get_auto_restart)
    assert update_settings["count"] == 2  # unchanged


@pytest.mark.asyncio
async def test_new_container_triggers_reattach_only_for_itself(
    db_manager, discovery, host_id, patch_executor, get_auto_restart
):
    update_settings = _wrap_count(db_manager, "reattach_update_settings_for_container")

    patch_executor.next_response = [
        _make_dc("aaaaaaaaaaaa", name="a"),
        _make_dc("bbbbbbbbbbbb", name="b"),
    ]
    await discovery.discover_containers_for_host(host_id, get_auto_restart)
    assert update_settings["count"] == 2
    update_settings["calls_for"].clear()

    # Add a new container; existing ones unchanged.
    discovery.discover_containers_for_host.invalidate()
    patch_executor.next_response = [
        _make_dc("aaaaaaaaaaaa", name="a"),
        _make_dc("bbbbbbbbbbbb", name="b"),
        _make_dc("dddddddddddd", name="d"),  # new
    ]
    await discovery.discover_containers_for_host(host_id, get_auto_restart)

    assert update_settings["count"] == 3  # only the new one ran
    assert update_settings["calls_for"] == ["dddddddddddd"]
    assert discovery._reattached_container_ids[host_id] == {
        "aaaaaaaaaaaa", "bbbbbbbbbbbb", "dddddddddddd",
    }


@pytest.mark.asyncio
async def test_destroyed_container_is_pruned_from_seen_set(
    db_manager, discovery, host_id, patch_executor, get_auto_restart
):
    update_settings = _wrap_count(db_manager, "reattach_update_settings_for_container")

    patch_executor.next_response = [
        _make_dc("aaaaaaaaaaaa", name="a"),
        _make_dc("bbbbbbbbbbbb", name="b"),
    ]
    await discovery.discover_containers_for_host(host_id, get_auto_restart)
    assert discovery._reattached_container_ids[host_id] == {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}

    # b is destroyed; only a remains visible.
    discovery.discover_containers_for_host.invalidate()
    patch_executor.next_response = [_make_dc("aaaaaaaaaaaa", name="a")]
    await discovery.discover_containers_for_host(host_id, get_auto_restart)

    # Seen-set is rewritten to currently-visible containers.
    assert discovery._reattached_container_ids[host_id] == {"aaaaaaaaaaaa"}

    # If b reappears (e.g., recreated with the same short id by Docker —
    # unlikely in practice, but the gate must not have stale state), it
    # should hit the reattach path again.
    pre = update_settings["count"]
    update_settings["calls_for"].clear()
    discovery.discover_containers_for_host.invalidate()
    patch_executor.next_response = [
        _make_dc("aaaaaaaaaaaa", name="a"),
        _make_dc("bbbbbbbbbbbb", name="b"),
    ]
    await discovery.discover_containers_for_host(host_id, get_auto_restart)

    assert update_settings["count"] == pre + 1
    assert update_settings["calls_for"] == ["bbbbbbbbbbbb"]


@pytest.mark.asyncio
async def test_seen_set_is_per_host(
    db_manager, discovery, host_id, patch_executor, get_auto_restart
):
    """A second host's containers must not bleed into the first host's seen-set."""
    other_host_id = str(uuid.uuid4())
    with db_manager.get_session() as session:
        session.add(DockerHostDB(
            id=other_host_id, name="other", url="agent://", is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        session.add(Agent(
            id=str(uuid.uuid4()), host_id=other_host_id,
            engine_id=str(uuid.uuid4()),
            version="1.0.0", proto_version="1.1",
            capabilities={}, status="online",
        ))
        session.commit()
    discovery.hosts[other_host_id] = DockerHost(
        id=other_host_id, name="other", url="agent://",
        connection_type="agent", status="online",
    )

    update_settings = _wrap_count(db_manager, "reattach_update_settings_for_container")

    patch_executor.next_response = [_make_dc("aaaaaaaaaaaa", name="a")]
    await discovery.discover_containers_for_host(host_id, get_auto_restart)

    discovery.discover_containers_for_host.invalidate()
    patch_executor.next_response = [_make_dc("bbbbbbbbbbbb", name="b")]
    await discovery.discover_containers_for_host(other_host_id, get_auto_restart)

    assert discovery._reattached_container_ids[host_id] == {"aaaaaaaaaaaa"}
    assert discovery._reattached_container_ids[other_host_id] == {"bbbbbbbbbbbb"}
    # Both seen for the first time on their respective hosts.
    assert update_settings["count"] == 2
