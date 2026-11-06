"""
Unit tests for containers whose running image no longer exists locally.

When an image is built and pushed on the same host that runs it, re-tagging
:latest to the new build deletes the old image record while the container keeps
running it. The container then has no RepoDigests, so the Issue #143 fallback
resolves the *registry* tag and uses that as the current digest - which is by
construction the latest digest, so the container was always reported up to date
even though it ran an old build.

When the current digest came from that fallback, the checker must compare what
the container actually runs (its image ID, then its version label) instead.

Following TDD: RED -> GREEN -> REFACTOR.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from database import DatabaseManager
from updates.update_checker import UpdateChecker

INDEX_DIGEST = "sha256:" + "1" * 64
PLATFORM_DIGEST = "sha256:" + "2" * 64
CONFIG_DIGEST = "sha256:" + "3" * 64
OLD_IMAGE_ID = "sha256:" + "9" * 64


def _registry_result():
    """resolve_tag() result for an OCI index pushed by buildx (amd64 + attestation)."""
    return {
        "digest": INDEX_DIGEST,
        "registry": "git.example.net",
        "manifest": {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {"digest": PLATFORM_DIGEST, "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:" + "4" * 64, "platform": {"os": "unknown", "architecture": "unknown"}},
            ],
            "config": {"config": {"Labels": {"org.opencontainers.image.version": "31.6.4"}}},
            "config_digest": CONFIG_DIGEST,
        },
    }


def _make_checker(image_id=None, current_version=None, registry_result=None):
    checker = UpdateChecker(db=MagicMock(spec=DatabaseManager), monitor=MagicMock())
    checker.registry = MagicMock()
    checker.registry.compute_floating_tag = MagicMock(side_effect=lambda image, mode: image)
    checker.registry.resolve_tag = AsyncMock(return_value=registry_result or _registry_result())
    checker._get_tracking_mode = MagicMock(return_value="exact")
    checker._get_registry_credentials = MagicMock(return_value=None)
    checker._get_container_image_version = AsyncMock(return_value=current_version)
    checker._get_container_image_id = AsyncMock(return_value=image_id)
    # The running image record is gone: no local digest
    checker._get_container_image_digest = AsyncMock(return_value=None)
    return checker


CONTAINER = {
    "host_id": "host-123",
    "id": "abc123def456",
    "name": "gunbot",
    "image": "git.example.net/olen/gunbot:latest",
}


class TestStaleRunningImage:

    @pytest.mark.asyncio
    async def test_old_image_id_reports_update(self):
        """Running an image that is none of the registry's digests => update available."""
        checker = _make_checker(image_id=OLD_IMAGE_ID, current_version="31.6.2")

        result = await checker._check_container_update(dict(CONTAINER), bypass_cache=True)

        assert result["update_available"] is True
        assert result["current_version"] == "31.6.2"
        assert result["latest_version"] == "31.6.4"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("running_id", [INDEX_DIGEST, PLATFORM_DIGEST, CONFIG_DIGEST])
    async def test_current_image_id_reports_no_update(self, running_id):
        """Image ID matches the index (containerd store), platform manifest or config digest."""
        checker = _make_checker(image_id=running_id, current_version="31.6.4")

        result = await checker._check_container_update(dict(CONTAINER), bypass_cache=True)

        assert result["update_available"] is False

    @pytest.mark.asyncio
    async def test_same_version_rebuild_detected_by_image_id(self):
        """A rebuild with an unchanged version label is still caught via the image ID."""
        checker = _make_checker(image_id=OLD_IMAGE_ID, current_version="31.6.4")

        result = await checker._check_container_update(dict(CONTAINER), bypass_cache=True)

        assert result["update_available"] is True

    @pytest.mark.asyncio
    async def test_falls_back_to_version_label_without_image_id(self):
        """No image ID (e.g. agent host) => compare OCI version labels."""
        checker = _make_checker(image_id=None, current_version="31.6.2")

        result = await checker._check_container_update(dict(CONTAINER), bypass_cache=True)

        assert result["update_available"] is True

    @pytest.mark.asyncio
    async def test_matching_version_label_without_image_id_reports_no_update(self):
        checker = _make_checker(image_id=None, current_version="31.6.4")

        result = await checker._check_container_update(dict(CONTAINER), bypass_cache=True)

        assert result["update_available"] is False

    @pytest.mark.asyncio
    async def test_cached_manifest_without_config_digest_still_matches_index(self):
        """Manifests cached before config_digest existed: index/platform digests still count."""
        cached = _registry_result()
        del cached["manifest"]["config_digest"]
        checker = _make_checker(image_id=INDEX_DIGEST, current_version="31.6.4", registry_result=cached)

        result = await checker._check_container_update(dict(CONTAINER), bypass_cache=True)

        assert result["update_available"] is False

    @pytest.mark.asyncio
    async def test_normal_path_does_not_consult_image_id(self):
        """Containers with RepoDigests keep the existing digest comparison."""
        checker = _make_checker(image_id=OLD_IMAGE_ID, current_version="31.6.4")
        checker._get_container_image_digest = AsyncMock(return_value=INDEX_DIGEST)

        result = await checker._check_container_update(
            dict(CONTAINER, repo_digests=[f"git.example.net/olen/gunbot@{INDEX_DIGEST}"]),
            bypass_cache=True,
        )

        assert result["update_available"] is False
        checker._get_container_image_id.assert_not_awaited()


class TestResolveTagConfigDigest:
    """resolve_tag() must expose the config digest that the image-ID comparison relies on."""

    @pytest.mark.asyncio
    async def test_config_digest_included_in_manifest(self):
        from updates.registry_adapter import RegistryAdapter

        adapter = RegistryAdapter()
        adapter._get_auth_token = AsyncMock(return_value=None)
        adapter._fetch_manifest = AsyncMock(return_value=(INDEX_DIGEST, {"mediaType": "x", "manifests": []}))
        adapter._fetch_config_blob = AsyncMock(return_value=({"config": {"Labels": {}}}, CONFIG_DIGEST))

        result = await adapter.resolve_tag("git.example.net/olen/gunbot:latest")

        assert result["digest"] == INDEX_DIGEST
        assert result["manifest"]["config_digest"] == CONFIG_DIGEST
        assert result["manifest"]["config"] == {"config": {"Labels": {}}}

    @pytest.mark.asyncio
    async def test_config_fetch_failure_leaves_config_digest_empty(self):
        from updates.registry_adapter import RegistryAdapter

        adapter = RegistryAdapter()
        adapter._get_auth_token = AsyncMock(return_value=None)
        adapter._fetch_manifest = AsyncMock(return_value=(INDEX_DIGEST, {"config": {"digest": "d"}}))
        adapter._fetch_config_blob = AsyncMock(return_value=(None, None))

        result = await adapter.resolve_tag("git.example.net/olen/gunbot:latest")

        assert result["manifest"]["config_digest"] is None
        assert result["manifest"]["config"] == {"digest": "d"}
