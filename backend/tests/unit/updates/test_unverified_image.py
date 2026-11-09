"""A fallback update is only trusted for auto-update when the running image is the registry's image for its tag."""

import pytest

from checker_fakes import (
    AMD64_CHILD,
    ARM64_CHILD,
    CURRENT,
    FakeClient,
    LATEST,
    LATEST_CONFIG,
    LOCAL_IMAGE_ID,
    STALE_IMAGE_ID,
    VERSION_LABEL,
    container_dict,
    digest,
    evidence,
    index_manifest,
    make_checker,
    registry_result,
    update_record,
)
from updates.update_checker import UNVERIFIED_IMAGE_STATUS

pytestmark = pytest.mark.usefixtures("changelog_stub", "credentials_stub")

IMAGE = "nginx:1.25.3"
CURRENT_CONFIG = digest("3")


def routes():
    return {
        IMAGE: registry_result(CURRENT, manifest=index_manifest(), config_digest=CURRENT_CONFIG),
        "nginx:1": registry_result(LATEST, labels={VERSION_LABEL: "1.26.0"}, config_digest=LATEST_CONFIG),
    }


async def check(client=None, agent_arch=None, **container):
    checker = make_checker(routes(), client=client, record=update_record("minor"), agent_arch=agent_arch)
    result = await checker._check_container_update(container_dict(IMAGE, **container))
    assert checker.registry.unexpected == []
    assert result is not None
    return result


def test_status_value():
    assert UNVERIFIED_IMAGE_STATUS == "unverified_image"


@pytest.mark.parametrize("image_id", [CURRENT_CONFIG, CURRENT, AMD64_CHILD], ids=["config", "index", "platform"])
async def test_local_image_matching_its_own_tag_is_trusted(image_id):
    result = await check(FakeClient(image_id=image_id, repo_digests=()))

    assert result["update_available"] is True
    assert result["current_digest"] == CURRENT
    assert result["check_status"] is None


async def test_local_build_with_a_public_name_is_marked():
    result = await check(FakeClient(image_id=LOCAL_IMAGE_ID, repo_digests=()))

    assert result["update_available"] is True
    assert result["check_status"] == UNVERIFIED_IMAGE_STATUS


# The updater would pin the old image's env without its record, so even a matching ID is not trusted.
async def test_lost_image_record_is_marked_even_when_its_id_matches():
    result = await check(FakeClient(image_id=CURRENT_CONFIG, image_missing=True))

    assert result["update_available"] is True
    assert result["check_status"] == UNVERIFIED_IMAGE_STATUS


async def test_lost_image_record_ignores_an_agent_style_image_id():
    result = await check(FakeClient(image_id=LOCAL_IMAGE_ID, image_missing=True), image_id=CURRENT_CONFIG)

    assert result["check_status"] == UNVERIFIED_IMAGE_STATUS


@pytest.mark.parametrize("image_id", [CURRENT_CONFIG, CURRENT, AMD64_CHILD], ids=["config", "index", "platform"])
async def test_agent_image_matching_its_own_tag_is_trusted(image_id):
    result = await check(image_id=image_id)

    assert result["update_available"] is True
    assert result["platform"] == "linux/amd64"
    assert result["check_status"] is None


async def test_arm64_agent_proves_with_its_own_platform_digest():
    result = await check(image_id=ARM64_CHILD, agent_arch="arm64")

    assert result["platform"] == "linux/arm64"
    assert result["check_status"] is None


@pytest.mark.parametrize("image_id", [LOCAL_IMAGE_ID, None, "3" * 64, "sha256:333"],
                         ids=["other", "missing", "no-algorithm", "short"])
async def test_agent_image_not_matching_is_marked(image_id):
    result = await check(image_id=image_id)

    assert result["update_available"] is True
    assert result["check_status"] == UNVERIFIED_IMAGE_STATUS


async def test_agent_without_image_id_field_is_marked():
    result = await check()

    assert result["check_status"] == UNVERIFIED_IMAGE_STATUS


async def test_local_host_container_lookup_failure_is_marked():
    client = FakeClient(image_id=CURRENT_CONFIG, repo_digests=())

    def raising(_):
        raise RuntimeError("daemon down")

    client.containers.get = raising

    result = await check(client)

    assert result["check_status"] == UNVERIFIED_IMAGE_STATUS


async def test_no_update_is_never_marked():
    checker = make_checker({IMAGE: registry_result(CURRENT, config_digest=CURRENT_CONFIG)},
                           client=FakeClient(image_id=LOCAL_IMAGE_ID, repo_digests=()))

    result = await checker._check_container_update(container_dict(IMAGE))

    assert result["update_available"] is False
    assert result["check_status"] is None


async def test_suppressed_downgrade_is_not_marked():
    checker = make_checker(routes(), client=FakeClient(image_id=LOCAL_IMAGE_ID, repo_digests=()),
                           record=update_record("minor"))

    result = await checker._check_container_update(container_dict(IMAGE, labels={VERSION_LABEL: "2.0.0"}))

    assert result["update_available"] is False
    assert result["check_status"] is None


async def test_repo_digests_path_is_not_marked():
    result = await check(FakeClient(image_id=LOCAL_IMAGE_ID, repo_digests=[f"nginx@{CURRENT}"]))

    assert result["update_available"] is True
    assert result["check_status"] is None


async def test_agent_repo_digests_path_is_not_marked():
    result = await check(repo_digests=[f"nginx@{CURRENT}"])

    assert result["update_available"] is True
    assert result["check_status"] is None


async def test_stale_running_image_is_not_marked():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())
    checker = make_checker({"app:latest": registry_result(LATEST, config_digest=LATEST_CONFIG)}, client=client,
                           record=update_record(verified_image=evidence(STALE_IMAGE_ID)))

    result = await checker._check_container_update(container_dict("app:latest"))

    assert result["update_available"] is True
    assert result["current_digest"] == STALE_IMAGE_ID
    assert result["check_status"] is None


async def test_arm64_image_proves_with_its_own_platform_digest():
    client = FakeClient(image_id=digest("d"), repo_digests=(), architecture="arm64")

    result = await check(client)

    assert result["platform"] == "linux/arm64"
    assert result["check_status"] is None


async def test_amd64_child_does_not_prove_an_arm64_image():
    client = FakeClient(image_id=AMD64_CHILD, repo_digests=(), architecture="arm64")

    result = await check(client)

    assert result["check_status"] == UNVERIFIED_IMAGE_STATUS
