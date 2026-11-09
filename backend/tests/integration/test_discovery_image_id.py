"""Agent discovery keeps the image ID and platform for the update checker only; the API and live broadcast never show them."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.command_executor import CommandResult, CommandStatus
from docker_monitor.container_discovery import ContainerDiscovery
from models.docker_models import Container, DockerHost
from tests.integration.test_discovery_network_mode import add_host, agent_container
from updates.update_checker import UpdateChecker

IMAGE_ID = "sha256:" + "b" * 64


async def discover_agent(db, image_id, image_platform=...):
    host_id = add_host(db, "agent://", with_agent=True)
    host = DockerHost(id=host_id, name="test-host", url="agent://", connection_type="agent", status="online")
    discovery = ContainerDiscovery(db=db, settings=None, hosts={host_id: host}, clients={})
    payload = agent_container({})
    if image_id is ...:
        del payload["ImageID"]
    else:
        payload["ImageID"] = image_id
    if image_platform is not ...:
        payload["ImagePlatform"] = image_platform
    executor = MagicMock()
    executor.execute_command = AsyncMock(return_value=CommandResult(
        status=CommandStatus.SUCCESS, success=True, response=[payload], error=None,
    ))
    with patch("agent.command_executor.get_agent_command_executor", return_value=executor):
        return await discovery.discover_containers_for_host(host_id, lambda *_: False)


@pytest.mark.asyncio
async def test_agent_discovery_reads_the_image_id(db):
    containers = await discover_agent(db, IMAGE_ID)

    assert containers[0].image_id == IMAGE_ID


@pytest.mark.asyncio
@pytest.mark.parametrize("image_id", [..., None, "", "b" * 64, "sha256:bbb", "sha256:" + "B" * 64, 7],
                         ids=["absent", "null", "empty", "no-algorithm", "short", "uppercase", "number"])
async def test_agent_discovery_drops_an_unusable_image_id(db, image_id):
    containers = await discover_agent(db, image_id)

    assert containers[0].image_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("image_platform, expected", [
    ({"Os": "linux", "Architecture": "arm", "Variant": "v7"}, "linux/arm/v7"),
    ({"Os": "linux", "Architecture": "arm64", "Variant": "v8"}, "linux/arm64"),
    ({"Os": "linux", "Architecture": "amd64"}, "linux/amd64"),
], ids=["variant", "arm64-v8", "no-variant"])
async def test_agent_discovery_reads_the_image_platform(db, image_platform, expected):
    containers = await discover_agent(db, IMAGE_ID, image_platform)

    assert (containers[0].image_id, containers[0].image_platform) == (IMAGE_ID, expected)


@pytest.mark.asyncio
async def test_older_agent_without_the_platform_keeps_the_image_id(db):
    containers = await discover_agent(db, IMAGE_ID)

    assert (containers[0].image_id, containers[0].image_platform) == (IMAGE_ID, None)


# A missing image record would make the updater pin the old env, so its ID proves nothing.
@pytest.mark.asyncio
@pytest.mark.parametrize("image_platform", [
    None, {}, "linux/amd64", {"Os": "windows", "Architecture": "amd64"}, {"Architecture": "amd64"},
    {"Os": "linux", "Architecture": ""},
], ids=["null", "empty", "string", "windows", "no-os", "no-arch"])
async def test_lost_or_unusable_image_drops_the_image_id(db, image_platform):
    containers = await discover_agent(db, IMAGE_ID, image_platform)

    assert (containers[0].image_id, containers[0].image_platform) == (None, None)


def make_container():
    return Container(
        id="aaaaaaaaaaaa", short_id="aaaaaaaaaaaa", name="app", state="running", status="running",
        host_id="host", host_name="host", image="app:1", created="2026-11-08T00:00:00Z", image_id=IMAGE_ID,
        image_platform="linux/arm64",
    )


@pytest.mark.parametrize("field", ["image_id", "image_platform"])
def test_checker_fields_stay_out_of_serialized_output(field):
    container = make_container()

    assert field not in container.dict()
    assert field not in container.model_dump()
    assert field not in json.loads(container.model_dump_json())


def checker_for(container):
    monitor = SimpleNamespace(get_containers=AsyncMock(return_value=[container]))
    return UpdateChecker(db=MagicMock(), monitor=monitor)


@pytest.mark.asyncio
async def test_checker_sweep_sees_the_image_id():
    containers = await checker_for(make_container())._get_all_containers()

    assert (containers[0]["image_id"], containers[0]["image_platform"]) == (IMAGE_ID, "linux/arm64")


@pytest.mark.asyncio
async def test_checker_single_lookup_sees_the_image_id():
    container = await checker_for(make_container())._get_container_async("host", "aaaaaaaaaaaa")

    assert (container["image_id"], container["image_platform"]) == (IMAGE_ID, "linux/arm64")
