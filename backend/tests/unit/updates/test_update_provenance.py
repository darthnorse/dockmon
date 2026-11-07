"""A mismatch only means "stale" if this exact image ID was seen to match this exact reference earlier."""

import json

import pytest

from checker_fakes import (
    AMD64_CHILD,
    ARM64_CHILD,
    CURRENT,
    FakeClient,
    LATEST,
    LATEST_CONFIG,
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

pytestmark = pytest.mark.usefixtures("changelog_stub", "credentials_stub")

IMAGE = "app:latest"


def moved_registry(**kwargs):
    return {IMAGE: registry_result(LATEST, config_digest=LATEST_CONFIG, **kwargs)}


def stored(image_id=STALE_IMAGE_ID, **kwargs):
    return update_record(verified_image=evidence(image_id, **kwargs))


async def check(checker, image=IMAGE, **container):
    result = await checker._check_container_update(container_dict(image, **container))
    assert checker.registry.unexpected == []
    assert result is not None
    return result


async def test_stale_when_registry_moved_after_a_match_and_record_is_gone():
    client = FakeClient(image_id=STALE_IMAGE_ID, image_missing=True)

    result = await check(make_checker(moved_registry(), client=client, record=stored()))

    assert result["update_available"] is True
    assert result["current_digest"] == STALE_IMAGE_ID
    assert result["latest_digest"] == LATEST


async def test_stale_when_registry_moved_after_a_match_and_image_has_no_repo_digests():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())

    result = await check(make_checker(moved_registry(), client=client, record=stored()))

    assert result["update_available"] is True


@pytest.mark.parametrize("image_id", [LATEST, AMD64_CHILD, LATEST_CONFIG], ids=["index", "platform", "config"])
async def test_any_digest_match_means_current(image_id):
    client = FakeClient(image_id=image_id, repo_digests=())
    routes = {IMAGE: registry_result(LATEST, manifest=index_manifest(), config_digest=LATEST_CONFIG)}

    result = await check(make_checker(routes, client=client, record=stored(image_id)))

    assert result["update_available"] is False


async def test_local_build_never_matched_is_left_alone():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())

    result = await check(make_checker(moved_registry(), client=client))

    assert result["update_available"] is False
    assert result["current_digest"] == LATEST
    assert result["verified_image"] is None


async def test_container_recreated_on_a_new_local_build_is_left_alone():
    client = FakeClient(image_id=digest("2"), repo_digests=())

    result = await check(make_checker(moved_registry(), client=client, record=stored()))

    assert result["update_available"] is False


async def test_evidence_for_another_reference_does_not_count_on_repeated_checks():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())
    record = stored(ref="other:latest")
    checker = make_checker(moved_registry(), client=client, record=record)

    first = await check(checker)
    second = await check(checker)

    assert first["update_available"] is False
    assert second["update_available"] is False
    assert first["verified_image"] is None


async def test_evidence_for_another_platform_does_not_count():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())

    result = await check(make_checker(moved_registry(), client=client, record=stored(platform="linux/arm64")))

    assert result["update_available"] is False


@pytest.mark.parametrize("repo_digests,image_id", [
    ([f"app@{LATEST}"], STALE_IMAGE_ID),
    ([f"app@{AMD64_CHILD}"], STALE_IMAGE_ID),
    ((), LATEST),
    ((), AMD64_CHILD),
    ((), LATEST_CONFIG),
], ids=["repo-index", "repo-platform", "id-index", "id-platform", "id-config"])
async def test_a_match_writes_evidence(repo_digests, image_id):
    client = FakeClient(image_id=image_id, repo_digests=repo_digests)
    routes = {IMAGE: registry_result(LATEST, manifest=index_manifest(), config_digest=LATEST_CONFIG)}

    result = await check(make_checker(routes, client=client))

    assert json.loads(result["verified_image"]) == json.loads(evidence(image_id))


async def test_repo_digests_that_do_not_match_this_reference_write_no_evidence():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=[f"other/app@{CURRENT}"])

    result = await check(make_checker(moved_registry(), client=client))

    assert result["verified_image"] is None
    assert result["update_available"] is True


async def test_no_evidence_written_without_a_verified_platform():
    client = FakeClient(image_id=LATEST_CONFIG, image_missing=True)

    result = await check(make_checker(moved_registry(), client=client))

    assert result["verified_image"] is None


async def test_agent_hosts_write_no_evidence_and_are_never_stale():
    result = await check(make_checker(moved_registry(), record=stored()), repo_digests=None)

    assert result["verified_image"] is None
    assert result["update_available"] is False
    assert result["platform"] == "linux/amd64"


@pytest.mark.parametrize("config_digest", [
    None,
    "md5:" + "a" * 32,
    "sha256:abc",
    "sha256:" + "z" * 64,
    "sha256:" + "A" * 64,
], ids=["absent", "wrong-algorithm", "wrong-length", "non-hex", "uppercase"])
async def test_no_usable_config_digest_means_no_stale(config_digest):
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())
    routes = {IMAGE: registry_result(LATEST, config_digest=config_digest)}

    result = await check(make_checker(routes, client=client, record=stored()))

    assert result["update_available"] is False


@pytest.mark.parametrize("manifest_json", [
    "not json",
    "null",
    "[]",
    "3",
    '"text"',
    '{"config": 1}',
    json.dumps({"schemaVersion": 2}),
], ids=["invalid", "null", "list", "number", "string", "bad-config", "old-entry"])
async def test_unusable_cache_entry_means_no_stale(manifest_json):
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())
    cached = {"digest": LATEST, "registry_url": "docker.io", "manifest_json": manifest_json}
    routes = {IMAGE: registry_result(LATEST)}

    result = await check(make_checker(routes, client=client, record=stored(), cached=cached))

    assert result["update_available"] is False


@pytest.mark.parametrize("verified_image", [
    "not json",
    "[]",
    "null",
    json.dumps({"image_id": STALE_IMAGE_ID}),
    json.dumps({"image_id": 1, "platform": "linux/amd64", "ref": IMAGE}),
], ids=["invalid", "list", "null", "partial", "wrong-type"])
async def test_unusable_stored_evidence_means_no_stale(verified_image):
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())
    record = update_record(verified_image=verified_image)

    result = await check(make_checker(moved_registry(), client=client, record=record))

    assert result["update_available"] is False


async def test_container_lookup_failure_means_no_stale():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())

    def raising(_):
        raise RuntimeError("daemon down")

    client.containers.get = raising

    result = await check(make_checker(moved_registry(), client=client, record=stored()))

    assert result["update_available"] is False


async def test_stale_from_a_db_cache_hit():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())
    cached = {
        "digest": LATEST,
        "registry_url": "docker.io",
        "manifest_json": json.dumps({"schemaVersion": 2, "config_digest": LATEST_CONFIG}),
    }
    checker = make_checker({IMAGE: registry_result(LATEST)}, client=client, record=stored(), cached=cached)

    result = await check(checker)

    assert result["update_available"] is True
    assert checker.registry.refs() == [IMAGE]


async def test_older_latest_label_still_suppresses_a_stale_result():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=())
    routes = {IMAGE: registry_result(LATEST, labels={VERSION_LABEL: "1.0.0"}, config_digest=LATEST_CONFIG)}

    result = await check(make_checker(routes, client=client, record=stored()), labels={VERSION_LABEL: "2.0.0"})

    assert result["update_available"] is False


@pytest.mark.parametrize("architecture,variant,expected", [
    ("amd64", None, "linux/amd64"),
    ("arm64", None, "linux/arm64"),
    ("arm64", "v8", "linux/arm64"),
    ("arm", "v7", "linux/arm/v7"),
])
async def test_platform_comes_from_the_image(architecture, variant, expected):
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=(), architecture=architecture, variant=variant)
    checker = make_checker(moved_registry(), client=client)

    result = await check(checker)

    assert result["platform"] == expected
    assert [kwargs["platform"] for _, kwargs in checker.registry.calls] == [expected, expected]
    checker.db.get_cached_image_digest.assert_called_once_with(f"{IMAGE}:{expected}")


async def test_lost_record_uses_the_platform_in_the_evidence():
    client = FakeClient(image_id=STALE_IMAGE_ID, image_missing=True)
    record = stored(platform="linux/arm64")
    routes = {IMAGE: registry_result(LATEST, manifest=index_manifest(), config_digest=LATEST_CONFIG)}
    checker = make_checker(routes, client=client, record=record)

    result = await check(checker)

    assert result["platform"] == "linux/arm64"
    assert result["update_available"] is True


async def test_lost_record_without_evidence_is_unverified_whatever_the_row_says():
    client = FakeClient(image_id=STALE_IMAGE_ID, image_missing=True)
    record = update_record()
    record.platform = "linux/arm64"

    result = await check(make_checker(moved_registry(), client=client, record=record))

    assert result["platform"] == "linux/amd64"
    assert result["update_available"] is False


async def test_non_linux_images_are_never_stale():
    client = FakeClient(image_id=STALE_IMAGE_ID, repo_digests=(), image_os="windows")

    result = await check(make_checker(moved_registry(), client=client, record=stored()))

    assert result["update_available"] is False
    assert result["verified_image"] is None


async def test_arm64_platform_digest_verifies_on_an_arm64_image():
    client = FakeClient(image_id=ARM64_CHILD, repo_digests=(), architecture="arm64")
    routes = {IMAGE: registry_result(LATEST, manifest=index_manifest(), config_digest=LATEST_CONFIG)}

    result = await check(make_checker(routes, client=client))

    assert json.loads(result["verified_image"]) == json.loads(evidence(ARM64_CHILD, platform="linux/arm64"))


# Discovery reports "app" rather than "app:latest" once the image record is gone.
async def test_evidence_written_with_a_tag_still_counts_for_the_untagged_name():
    client = FakeClient(image_id=STALE_IMAGE_ID, image_missing=True)
    routes = {"app:latest": registry_result(LATEST, config_digest=LATEST_CONFIG), "app": registry_result(LATEST)}

    result = await check(make_checker(routes, client=client, record=stored()), image="app")

    assert result["update_available"] is True
