"""Characterization of _check_container_update through the real method. Boundaries only are faked."""

import json

import pytest

from checker_fakes import (
    AMD64_CHILD,
    CHANGELOG_CHECKED_AT,
    CHANGELOG_URL,
    CURRENT,
    FakeClient,
    LATEST,
    LATEST_CONFIG,
    OCI_INDEX,
    STALE_IMAGE_ID,
    VERSION_LABEL,
    container_dict,
    digest,
    index_manifest,
    make_checker,
    registry_result,
    update_record,
)

pytestmark = pytest.mark.usefixtures("changelog_stub", "credentials_stub")


async def run_check(checker, container, **kwargs):
    result = await checker._check_container_update(container, **kwargs)
    assert checker.registry.unexpected == []
    return result


def assert_subset(result, **expected):
    assert result is not None
    assert {key: result.get(key) for key in expected} == expected


def repo_digests(*digests, repo="app"):
    return [f"{repo}@{value}" for value in digests]


def version_labels(version):
    return {VERSION_LABEL: version}


async def test_latest_index_digest_in_any_repo_digest_means_no_update():
    client = FakeClient(repo_digests=repo_digests(CURRENT, LATEST))
    checker = make_checker({"app:stable": registry_result(LATEST, manifest=index_manifest())}, client=client)

    result = await run_check(checker, container_dict())

    assert_subset(result, update_available=False, current_digest=CURRENT, latest_digest=LATEST)


async def test_platform_child_digest_in_repo_digests_means_no_update():
    client = FakeClient(repo_digests=repo_digests(AMD64_CHILD))
    checker = make_checker({"app:stable": registry_result(LATEST, manifest=index_manifest())}, client=client)

    result = await run_check(checker, container_dict())

    assert_subset(result, update_available=False, current_digest=AMD64_CHILD, latest_digest=LATEST)


async def test_index_and_child_missing_from_repo_digests_means_update():
    client = FakeClient(repo_digests=repo_digests(CURRENT, digest("7")))
    checker = make_checker({"app:stable": registry_result(LATEST, manifest=index_manifest())}, client=client)

    result = await run_check(checker, container_dict())

    assert_subset(result, update_available=True, current_digest=CURRENT, latest_digest=LATEST)


async def test_agent_repo_digests_decide_without_docker():
    client = FakeClient()
    checker = make_checker({"app:stable": registry_result(LATEST)}, client=client)
    container = container_dict(repo_digests=repo_digests(CURRENT, LATEST), labels=version_labels("1.0.0"))

    result = await run_check(checker, container)

    assert_subset(result, update_available=False, current_digest=CURRENT)
    assert client.containers.requested == []


async def test_different_digests_mean_update():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"app:stable": registry_result(LATEST)}, client=client)

    result = await run_check(checker, container_dict())

    assert_subset(result, update_available=True, current_digest=CURRENT, latest_digest=LATEST)


# The container's real architecture is never looked up, so arm64 hosts compare against amd64.
async def test_arm64_host_is_checked_as_amd64_known_gap():
    client = FakeClient(repo_digests=repo_digests(AMD64_CHILD), architecture="aarch64")
    checker = make_checker({"app:stable": registry_result(LATEST, manifest=index_manifest())}, client=client)

    result = await run_check(checker, container_dict())

    assert_subset(result, update_available=False, platform="linux/amd64")
    _, kwargs = checker.registry.calls[-1]
    assert kwargs.get("platform", "linux/amd64") == "linux/amd64"


# Without a local image record the fallback compares the registry tag with itself, so a
# stale running image reads as current.
async def test_stale_image_without_local_record_reports_no_update_known_gap():
    client = FakeClient(image_id=STALE_IMAGE_ID, image_missing=True)
    route = registry_result(LATEST, config_digest=LATEST_CONFIG)
    checker = make_checker({"app:latest": route}, client=client)

    result = await run_check(checker, container_dict("app:latest"))

    assert_subset(result, update_available=False, current_digest=LATEST, latest_digest=LATEST)


async def test_fresh_image_without_local_record_reports_no_update():
    client = FakeClient(image_id=LATEST_CONFIG, image_missing=True)
    route = registry_result(LATEST, config_digest=LATEST_CONFIG)
    checker = make_checker({"app:latest": route}, client=client)

    result = await run_check(checker, container_dict("app:latest"))

    assert_subset(result, update_available=False, current_digest=LATEST)


async def test_agent_host_without_repo_digests_reports_no_update_via_fallback():
    route = registry_result(LATEST, config_digest=LATEST_CONFIG)
    checker = make_checker({"app:latest": route})

    result = await run_check(checker, container_dict("app:latest"))

    assert_subset(result, update_available=False, current_digest=LATEST)


async def test_fallback_uses_registry_digest_of_current_tag():
    client = FakeClient(image_id=STALE_IMAGE_ID, image_missing=True)
    checker = make_checker(
        {
            "nginx:1.25.3": registry_result(CURRENT),
            "nginx:1": registry_result(LATEST, labels=version_labels("1.26.0")),
        },
        client=client,
        record=update_record("minor"),
    )

    result = await run_check(checker, container_dict("nginx:1.25.3"))

    assert_subset(result, update_available=True, current_digest=CURRENT, latest_digest=LATEST)


async def test_digest_ref_skips_registry_fallback():
    image = f"ghcr.io/org/app@{CURRENT}"
    client = FakeClient(repo_digests=())
    checker = make_checker({}, client=client)

    result = await run_check(checker, container_dict(image))

    assert result is None
    assert checker.registry.calls == []


async def test_older_latest_label_suppresses_update():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"app:stable": registry_result(LATEST, labels=version_labels("1.0.0"))}, client=client)

    result = await run_check(checker, container_dict(labels=version_labels("2.0.0")))

    assert_subset(result, update_available=False, current_version="2.0.0", latest_version="1.0.0")


async def test_same_label_new_digest_is_still_an_update():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"app:stable": registry_result(LATEST, labels=version_labels("1.0.0"))}, client=client)

    result = await run_check(checker, container_dict(labels=version_labels("1.0.0")))

    assert_subset(result, update_available=True)


async def test_frozen_floating_tag_suppresses_update():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker(
        {"nextcloud:32.0-fpm-alpine": registry_result(LATEST)},
        client=client,
        record=update_record("patch"),
    )

    result = await run_check(checker, container_dict("nextcloud:32.0.3-fpm-alpine"))

    assert_subset(result, update_available=False, latest_image="nextcloud:32.0-fpm-alpine")


# Same path as the frozen-tag case: an unlabelled floating tag parses as x.y.0, older than
# the current x.y.z, so a tag that really moved is suppressed too.
@pytest.mark.parametrize("mode,floating", [("patch", "nginx:1.25"), ("minor", "nginx:1")])
async def test_moved_floating_tag_without_labels_is_suppressed_known_gap(mode, floating):
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({floating: registry_result(LATEST)}, client=client, record=update_record(mode))

    result = await run_check(checker, container_dict("nginx:1.25.3"))

    assert_subset(result, update_available=False, current_digest=CURRENT, latest_digest=LATEST)


@pytest.mark.parametrize("image,mode,floating,current_label,latest_label", [
    ("nginx:1.0.0", "minor", "nginx:1", None, None),
    ("nginx:1.25.3", "latest", "nginx:latest", None, None),
    ("nginx:1.25.3", "patch", "nginx:1.25", "1.25.3", "1.25.4"),
])
async def test_floating_tag_suppression_boundaries(image, mode, floating, current_label, latest_label):
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    labels = version_labels(latest_label) if latest_label else None
    checker = make_checker({floating: registry_result(LATEST, labels=labels)}, client=client,
                           record=update_record(mode))
    container = container_dict(image, labels=version_labels(current_label) if current_label else {})

    result = await run_check(checker, container)

    assert_subset(result, update_available=True)


async def test_versions_fall_back_to_tags():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"app:1.2.3": registry_result(LATEST)}, client=client)

    result = await run_check(checker, container_dict("app:1.2.3"))

    assert_subset(result, current_version="1.2.3", latest_version="1.2.3", update_available=True)


async def test_labels_win_over_tags():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"app:1.2.3": registry_result(LATEST, labels=version_labels("6.0.0"))}, client=client)

    result = await run_check(checker, container_dict("app:1.2.3", labels=version_labels("5.0.0")))

    assert_subset(result, current_version="5.0.0", latest_version="6.0.0")


async def test_current_version_comes_from_container_label():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"app:stable": registry_result(LATEST, labels=version_labels("2.0.0"))}, client=client)

    result = await run_check(checker, container_dict(labels=version_labels("1.0.0")))

    assert_subset(result, current_version="1.0.0", latest_version="2.0.0")


async def test_current_version_falls_back_to_local_image_label():
    client = FakeClient(repo_digests=repo_digests(CURRENT), image_labels=version_labels("1.0.0"))
    checker = make_checker({"app:stable": registry_result(LATEST)}, client=client)

    result = await run_check(checker, container_dict())

    assert_subset(result, current_version="1.0.0")


CACHED_ENTRY = {
    "digest": LATEST,
    "registry_url": "cache.example.com",
    "manifest_json": json.dumps({
        **index_manifest(),
        "config": {"config": {"Labels": version_labels("3.0.0")}},
    }),
}


async def test_bypass_cache_skips_db_cache():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"app:stable": registry_result(LATEST)}, client=client, cached=CACHED_ENTRY)

    result = await run_check(checker, container_dict(), bypass_cache=True)

    checker.db.get_cached_image_digest.assert_not_called()
    assert checker.registry.refs() == ["app:stable"]
    assert_subset(result, registry_url="docker.io")


async def test_cache_hit_supplies_decision_without_registry():
    client = FakeClient(repo_digests=repo_digests(AMD64_CHILD))
    checker = make_checker({}, client=client, cached=CACHED_ENTRY)

    result = await run_check(checker, container_dict())

    checker.db.get_cached_image_digest.assert_called_once_with("app:stable:linux/amd64")
    checker.db.cache_image_digest.assert_not_called()
    assert checker.registry.calls == []
    assert_subset(result, update_available=False, latest_digest=LATEST, latest_version="3.0.0",
                  registry_url="cache.example.com")


async def test_cache_miss_stores_registry_result():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"app:stable": registry_result(LATEST)}, client=client)

    await run_check(checker, container_dict())

    checker.db.cache_image_digest.assert_called_once()
    stored = checker.db.cache_image_digest.call_args.kwargs
    assert (stored["cache_key"], stored["digest"], stored["registry_url"]) == (
        "app:stable:linux/amd64", LATEST, "docker.io",
    )


async def test_tracking_mode_from_record_selects_floating_tag():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"nginx:1": registry_result(LATEST)}, client=client, record=update_record("minor"))

    result = await run_check(checker, container_dict("nginx:1.25.3"))

    assert checker.registry.refs() == ["nginx:1"]
    assert_subset(result, floating_tag_mode="minor", latest_image="nginx:1")


async def test_missing_record_tracks_exact_tag():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    checker = make_checker({"nginx:1.25.3": registry_result(LATEST)}, client=client)

    result = await run_check(checker, container_dict("nginx:1.25.3"))

    assert checker.registry.refs() == ["nginx:1.25.3"]
    assert_subset(result, floating_tag_mode="exact", latest_image="nginx:1.25.3")


async def test_credentials_reach_both_registry_calls(credentials_stub):
    credentials = {"username": "robot", "password": "secret"}
    credentials_stub.return_value = credentials
    client = FakeClient(image_id=STALE_IMAGE_ID, image_missing=True)
    checker = make_checker(
        {
            "nginx:1.25.3": registry_result(CURRENT),
            "nginx:1": registry_result(LATEST, labels=version_labels("1.26.0")),
        },
        client=client,
        record=update_record("minor"),
    )

    await run_check(checker, container_dict("nginx:1.25.3"))

    credentials_stub.assert_called_once_with(checker.db, "nginx:1.25.3")
    assert checker.registry.calls == [
        ("nginx:1.25.3", {"auth": credentials}),
        ("nginx:1", {"auth": credentials}),
    ]


async def test_untagged_registry_with_port_stays_on_its_own_registry(credentials_stub):
    credentials = {"username": "robot", "password": "secret"}
    credentials_stub.return_value = credentials
    client = FakeClient(repo_digests=repo_digests(CURRENT, repo="registry:5000/app"))
    route = registry_result(LATEST, registry="registry:5000")
    checker = make_checker({"registry:5000/app:latest": route}, client=client, record=update_record("latest"))

    result = await run_check(checker, container_dict("registry:5000/app"))

    assert checker.registry.calls == [("registry:5000/app:latest", {"auth": credentials})]
    assert_subset(result, latest_image="registry:5000/app:latest", update_available=True)


async def test_result_contract():
    client = FakeClient(repo_digests=repo_digests(CURRENT))
    route = registry_result(LATEST, labels=version_labels("1.6.0"), registry="ghcr.io")
    checker = make_checker({"ghcr.io/org/app:1": route}, client=client, record=update_record("minor"))
    container = container_dict("ghcr.io/org/app:1.5.0", labels=version_labels("1.5.0"))

    result = await run_check(checker, container)

    assert_subset(
        result,
        current_image="ghcr.io/org/app:1.5.0",
        current_digest=CURRENT,
        latest_image="ghcr.io/org/app:1",
        latest_digest=LATEST,
        update_available=True,
        registry_url="ghcr.io",
        platform="linux/amd64",
        floating_tag_mode="minor",
        current_version="1.5.0",
        latest_version="1.6.0",
        changelog_url=CHANGELOG_URL,
        changelog_source="auto",
        changelog_checked_at=CHANGELOG_CHECKED_AT,
    )


@pytest.mark.parametrize("image", [None, ""])
async def test_missing_image_returns_none(image):
    checker = make_checker({})

    assert await run_check(checker, container_dict(image)) is None
    assert checker.registry.calls == []


# Image-ID comparison added to this fallback path must not override downgrade suppression.
async def test_stale_image_with_older_latest_label_reports_no_update():
    client = FakeClient(image_id=STALE_IMAGE_ID, image_missing=True)
    route = registry_result(LATEST, labels=version_labels("1.0.0"), config_digest=LATEST_CONFIG)
    checker = make_checker({"app:stable": route}, client=client)

    result = await run_check(checker, container_dict(labels=version_labels("2.0.0")))

    assert_subset(result, update_available=False)


async def test_oci_index_child_digest_is_matched_like_docker_list():
    client = FakeClient(repo_digests=repo_digests(AMD64_CHILD))
    route = registry_result(LATEST, manifest=index_manifest(media_type=OCI_INDEX))
    checker = make_checker({"app:stable": route}, client=client)

    result = await run_check(checker, container_dict())

    assert_subset(result, update_available=False)
