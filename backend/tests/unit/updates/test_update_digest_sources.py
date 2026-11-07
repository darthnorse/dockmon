"""Characterization of where the checker reads the running image's digest and version from."""

from unittest.mock import AsyncMock, patch

from checker_fakes import (
    CONTAINER_ID,
    CURRENT,
    FakeClient,
    LATEST,
    LOCAL_IMAGE_ID,
    VERSION_LABEL,
    container_dict,
    make_checker,
)
from utils.async_docker import async_docker_call


async def test_agent_repo_digests_take_priority_over_docker():
    client = FakeClient(repo_digests=[f"app@{LATEST}"])
    checker = make_checker({}, client=client)

    found = await checker._get_container_image_digest(container_dict(repo_digests=[f"app@{CURRENT}"]), None)

    assert found == CURRENT


async def test_docker_repo_digests_returned_and_stored():
    digests = [f"app@{CURRENT}", f"mirror/app@{LATEST}"]
    client = FakeClient(repo_digests=digests)
    checker = make_checker({}, client=client)
    container = container_dict()
    spy = AsyncMock(side_effect=async_docker_call)

    with patch("updates.update_checker.async_docker_call", spy):
        running = await checker._inspect_running_image(container)
        found = await checker._get_container_image_digest(container, running)

    assert found == CURRENT
    assert container["repo_digests"] == digests
    assert spy.await_count == 1
    assert client.containers.requested == [CONTAINER_ID]
    assert client.images.requested == [LOCAL_IMAGE_ID.split(":")[1]]


async def test_no_client_for_host_returns_none():
    checker = make_checker({})

    container = container_dict()
    running = await checker._inspect_running_image(container)

    assert await checker._get_container_image_digest(container, running) is None


async def test_deleted_image_record_returns_none():
    checker = make_checker({}, client=FakeClient(image_missing=True))
    container = container_dict()
    running = await checker._inspect_running_image(container)

    assert await checker._get_container_image_digest(container, running) is None
    assert "repo_digests" not in container


async def test_empty_repo_digests_returns_none():
    checker = make_checker({}, client=FakeClient(repo_digests=()))

    container = container_dict()
    running = await checker._inspect_running_image(container)

    assert await checker._get_container_image_digest(container, running) is None


async def test_version_prefers_container_label_without_docker():
    client = FakeClient(image_labels={VERSION_LABEL: "9.9.9"})
    checker = make_checker({}, client=client)

    container = container_dict(labels={VERSION_LABEL: "1.0.0"})
    running = await checker._inspect_running_image(container)

    assert await checker._get_container_image_version(container, running) == "1.0.0"


async def test_version_falls_back_to_image_label():
    checker = make_checker({}, client=FakeClient(image_labels={VERSION_LABEL: "9.9.9"}))

    container = container_dict()
    running = await checker._inspect_running_image(container)

    assert await checker._get_container_image_version(container, running) == "9.9.9"


async def test_version_docker_error_returns_none():
    checker = make_checker({}, client=FakeClient(image_missing=True))

    container = container_dict()
    running = await checker._inspect_running_image(container)

    assert await checker._get_container_image_version(container, running) is None
