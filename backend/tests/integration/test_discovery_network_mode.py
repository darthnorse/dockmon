"""Discovery exposes network_mode internally on every host type, and nowhere else."""

import json
import uuid
from copy import copy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.command_executor import CommandResult, CommandStatus
from database import Agent, DockerHostDB
from docker_monitor.container_discovery import ContainerDiscovery
from models.docker_models import Container, DockerHost

NETWORK_MODE = "container:16678699c1634a4c0e7fb11255730d62d4f39be4ef58f6f8eaa996a2bf593904"


def add_host(db, url, with_agent):
    host_id = str(uuid.uuid4())
    with db.get_session() as session:
        session.add(DockerHostDB(
            id=host_id,
            name="test-host",
            url=url,
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        if with_agent:
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


def agent_container(host_config):
    return {
        "Id": "a" * 64,
        "Names": ["/qbittorrent"],
        "Image": "lscr.io/linuxserver/qbittorrent:latest",
        "ImageID": "sha256:" + "b" * 64,
        "Created": int(datetime.now(timezone.utc).timestamp()),
        "State": "running",
        "Status": "Up 1 hour",
        "Labels": {},
        "Ports": [],
        "HostConfig": host_config,
        "NetworkSettings": {"Networks": {}},
        "Mounts": [],
        "RepoDigests": [],
    }


async def discover_agent(db, host_config):
    host_id = add_host(db, "agent://", with_agent=True)
    host = DockerHost(id=host_id, name="test-host", url="agent://", connection_type="agent", status="online")
    discovery = ContainerDiscovery(db=db, settings=None, hosts={host_id: host}, clients={})
    executor = MagicMock()
    executor.execute_command = AsyncMock(return_value=CommandResult(
        status=CommandStatus.SUCCESS, success=True, response=[agent_container(host_config)], error=None,
    ))
    with patch("agent.command_executor.get_agent_command_executor", return_value=executor):
        return await discovery.discover_containers_for_host(host_id, lambda *_: False)


@pytest.mark.asyncio
async def test_agent_discovery_reads_network_mode(db):
    containers = await discover_agent(db, {"NetworkMode": NETWORK_MODE})

    assert containers[0].network_mode == NETWORK_MODE


@pytest.mark.asyncio
async def test_agent_discovery_tolerates_null_host_config(db):
    containers = await discover_agent(db, None)

    assert containers[0].network_mode is None


@pytest.mark.asyncio
async def test_local_discovery_reads_network_mode(db):
    host_id = add_host(db, "unix:///var/run/docker.sock", with_agent=False)
    host = DockerHost(id=host_id, name="test-host", url="unix:///var/run/docker.sock", connection_type="local", status="online")
    discovery = ContainerDiscovery(db=db, settings=None, hosts={host_id: host}, clients={host_id: MagicMock()})

    dc = MagicMock()
    dc.id = "a" * 64
    dc.name = "qbittorrent"
    dc.status = "running"
    dc.labels = {}
    dc.image.tags = ["lscr.io/linuxserver/qbittorrent:latest"]
    dc.attrs = {
        "Created": "2026-11-06T00:00:00Z",
        "State": {"Status": "running", "StartedAt": "2026-11-06T00:00:00Z"},
        "Config": {"Image": "lscr.io/linuxserver/qbittorrent:latest", "Env": []},
        "NetworkSettings": {"Ports": {}, "Networks": {}},
        "HostConfig": {"NetworkMode": NETWORK_MODE, "RestartPolicy": {"Name": "no"}},
        "Mounts": [],
    }

    with patch("utils.async_docker.async_containers_list", AsyncMock(return_value=[dc])):
        containers = await discovery.discover_containers_for_host(host_id, lambda *_: False)

    assert containers[0].network_mode == NETWORK_MODE


def make_container():
    return Container(
        id="aaaaaaaaaaaa",
        short_id="aaaaaaaaaaaa",
        name="qbittorrent",
        state="running",
        status="running",
        host_id="host",
        host_name="host",
        image="image",
        created="2026-11-06T00:00:00Z",
        network_mode=NETWORK_MODE,
    )


def test_network_mode_stays_out_of_serialized_output():
    container = make_container()

    assert "network_mode" not in container.dict()
    assert "network_mode" not in container.model_dump()
    assert "network_mode" not in json.loads(container.model_dump_json())


def test_network_mode_survives_on_live_objects_and_copies():
    container = make_container()

    assert container.model_copy().network_mode == NETWORK_MODE
    assert copy(container).network_mode == NETWORK_MODE
