"""Tests for the digest and ignore-pattern helpers used by the update checker."""

import pytest

from updates.update_checker import UpdateChecker


class TestMultiDigestDetection:
    """
    Test update detection when container has multiple RepoDigests.

    Issue #105: Images can have multiple manifest digests pointing to the same
    image ID (e.g., after registry re-signing). Dockmon should recognize that
    if ANY of the local RepoDigests matches the registry's latest digest,
    no update is needed.
    """

    def test_has_digest_single_match(self):
        """Should detect when latest digest is in RepoDigests (single entry)"""
        checker = UpdateChecker(db=None, monitor=None)

        container = {
            "repo_digests": ["ghcr.io/org/app@sha256:abc123def456"]
        }
        latest_digest = "sha256:abc123def456"

        result = checker._has_digest(container, latest_digest)

        assert result is True, "Should find digest in single-entry RepoDigests"

    def test_has_digest_multi_match_first(self):
        """Should detect when latest digest matches first RepoDigest"""
        checker = UpdateChecker(db=None, monitor=None)

        container = {
            "repo_digests": [
                "ghcr.io/org/app@sha256:abc123",
                "ghcr.io/org/app@sha256:def456"
            ]
        }
        latest_digest = "sha256:abc123"

        result = checker._has_digest(container, latest_digest)

        assert result is True, "Should find digest matching first entry"

    def test_has_digest_multi_match_second(self):
        """Should detect when latest digest matches second RepoDigest (Issue #105 case)"""
        checker = UpdateChecker(db=None, monitor=None)

        # This is the Immich case: same image ID, two digests
        container = {
            "repo_digests": [
                "ghcr.io/immich-app/immich-server@sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b61f4ed75597679892d86311a",
                "ghcr.io/immich-app/immich-server@sha256:e6a6298e67ae077808fdb7d8d5565955f60b0708191576143fc02d30ab1389d1"
            ]
        }
        # Registry returns the second digest
        latest_digest = "sha256:e6a6298e67ae077808fdb7d8d5565955f60b0708191576143fc02d30ab1389d1"

        result = checker._has_digest(container, latest_digest)

        assert result is True, "Should find digest matching second entry (Issue #105)"

    def test_has_digest_no_match(self):
        """Should return False when latest digest is not in RepoDigests"""
        checker = UpdateChecker(db=None, monitor=None)

        container = {
            "repo_digests": ["ghcr.io/org/app@sha256:abc123"]
        }
        latest_digest = "sha256:xyz789"  # Different digest

        result = checker._has_digest(container, latest_digest)

        assert result is False, "Should not find non-matching digest"

    def test_has_digest_empty_repo_digests(self):
        """Should return False when RepoDigests is empty"""
        checker = UpdateChecker(db=None, monitor=None)

        container = {"repo_digests": []}
        latest_digest = "sha256:abc123"

        result = checker._has_digest(container, latest_digest)

        assert result is False, "Should return False for empty RepoDigests"

    def test_has_digest_missing_repo_digests(self):
        """Should return False when RepoDigests key is missing"""
        checker = UpdateChecker(db=None, monitor=None)

        container = {}  # No repo_digests key
        latest_digest = "sha256:abc123"

        result = checker._has_digest(container, latest_digest)

        assert result is False, "Should return False for missing RepoDigests"

    def test_has_digest_none_repo_digests(self):
        """Should return False when RepoDigests is None"""
        checker = UpdateChecker(db=None, monitor=None)

        container = {"repo_digests": None}
        latest_digest = "sha256:abc123"

        result = checker._has_digest(container, latest_digest)

        assert result is False, "Should return False for None RepoDigests"

    @pytest.mark.parametrize("repo_digests,latest_digest,expected,reason", [
        # Single digest scenarios
        (["repo@sha256:abc"], "sha256:abc", True, "Exact match"),
        (["repo@sha256:abc"], "sha256:xyz", False, "No match"),
        # Multi-digest scenarios (Issue #105)
        (["repo@sha256:old", "repo@sha256:new"], "sha256:new", True, "Match second"),
        (["repo@sha256:old", "repo@sha256:new"], "sha256:old", True, "Match first"),
        (["repo@sha256:old", "repo@sha256:new"], "sha256:other", False, "Match neither"),
        # Edge cases
        ([], "sha256:abc", False, "Empty list"),
        (None, "sha256:abc", False, "None value"),
        # Defensive type checks
        ("not-a-list", "sha256:abc", False, "repo_digests not a list"),
        (["repo@sha256:abc"], None, False, "digest is None"),
        (["repo@sha256:abc"], "", False, "digest is empty string"),
        (["repo@sha256:abc", None, 123], "sha256:abc", True, "list with non-string elements"),
        ([None, 123, "repo@sha256:abc"], "sha256:abc", True, "non-strings before match"),
    ])
    def test_has_digest_parametrized(self, repo_digests, latest_digest, expected, reason):
        """Parametrized tests for _has_digest edge cases"""
        checker = UpdateChecker(db=None, monitor=None)
        container = {"repo_digests": repo_digests}

        result = checker._has_digest(container, latest_digest)

        assert result == expected, f"Failed: {reason}"


class TestPlatformDigestExtraction:
    """
    Test extraction of platform-specific digest from manifest lists.

    Issue #105 part 2: Docker may store the platform-specific manifest digest
    in RepoDigests instead of the index (manifest list) digest. When the index
    digest doesn't match any local RepoDigest, we fall back to checking the
    platform-specific digest from the manifest list body.
    """

    def test_extract_from_docker_manifest_list(self):
        """Should extract platform digest from Docker manifest list v2"""
        checker = UpdateChecker(db=None, monitor=None)

        manifest = {
            "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
            "manifests": [
                {
                    "digest": "sha256:amd64digest",
                    "platform": {"os": "linux", "architecture": "amd64"}
                },
                {
                    "digest": "sha256:arm64digest",
                    "platform": {"os": "linux", "architecture": "arm64"}
                }
            ]
        }

        assert checker._extract_platform_digest(manifest, "linux/amd64") == "sha256:amd64digest"
        assert checker._extract_platform_digest(manifest, "linux/arm64") == "sha256:arm64digest"

    def test_extract_from_oci_index(self):
        """Should extract platform digest from OCI image index"""
        checker = UpdateChecker(db=None, monitor=None)

        manifest = {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "digest": "sha256:amd64digest",
                    "platform": {"os": "linux", "architecture": "amd64"}
                }
            ]
        }

        assert checker._extract_platform_digest(manifest, "linux/amd64") == "sha256:amd64digest"

    def test_returns_none_for_single_manifest(self):
        """Should return None for non-manifest-list (single platform manifest)"""
        checker = UpdateChecker(db=None, monitor=None)

        manifest = {
            "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
            "config": {"digest": "sha256:configdigest"}
        }

        assert checker._extract_platform_digest(manifest, "linux/amd64") is None

    def test_returns_none_for_missing_platform(self):
        """Should return None when platform not found in manifest list"""
        checker = UpdateChecker(db=None, monitor=None)

        manifest = {
            "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
            "manifests": [
                {
                    "digest": "sha256:arm64only",
                    "platform": {"os": "linux", "architecture": "arm64"}
                }
            ]
        }

        assert checker._extract_platform_digest(manifest, "linux/amd64") is None

    def test_returns_none_for_empty_manifest(self):
        """Should return None for empty dict"""
        checker = UpdateChecker(db=None, monitor=None)
        assert checker._extract_platform_digest({}, "linux/amd64") is None

    def test_returns_none_for_empty_manifests_array(self):
        """Should return None when manifests array is empty"""
        checker = UpdateChecker(db=None, monitor=None)

        manifest = {
            "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
            "manifests": []
        }

        assert checker._extract_platform_digest(manifest, "linux/amd64") is None

    def test_immich_scenario(self):
        """
        Reproduce the exact immich_server scenario from Issue #105.

        Registry returns index digest sha256:e6a6298e6... but Docker stores
        platform digest sha256:2c496e3b9... in RepoDigests. The index digest
        never appears in RepoDigests, but the platform-specific digest does.
        """
        checker = UpdateChecker(db=None, monitor=None)

        # What the registry returns (manifest list with index digest)
        index_digest = "sha256:e6a6298e67ae077808fdb7d8d5565955f60b0708"
        platform_digest = "sha256:2c496e3b9d476ea723e6f0df05d1f690fed2d79b"

        manifest = {
            "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
            "manifests": [
                {
                    "digest": platform_digest,
                    "platform": {"os": "linux", "architecture": "amd64"}
                },
                {
                    "digest": "sha256:arm64variant",
                    "platform": {"os": "linux", "architecture": "arm64"}
                }
            ]
        }

        # What Docker stores locally (platform-specific digest, NOT index)
        container = {
            "repo_digests": [
                f"ghcr.io/immich-app/immich-server@{platform_digest}"
            ]
        }

        # Step 1: Index digest NOT in RepoDigests (old logic fails here)
        assert checker._has_digest(container, index_digest) is False

        # Step 2: Extract platform digest from manifest list
        extracted = checker._extract_platform_digest(manifest, "linux/amd64")
        assert extracted == platform_digest

        # Step 3: Platform digest IS in RepoDigests (new fallback succeeds)
        assert checker._has_digest(container, extracted) is True

    def test_extract_with_arm_variant(self):
        """Should match platform with variant (e.g., linux/arm/v7)"""
        checker = UpdateChecker(db=None, monitor=None)

        manifest = {
            "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
            "manifests": [
                {
                    "digest": "sha256:amd64digest",
                    "platform": {"os": "linux", "architecture": "amd64"}
                },
                {
                    "digest": "sha256:armv7digest",
                    "platform": {"os": "linux", "architecture": "arm", "variant": "v7"}
                },
                {
                    "digest": "sha256:armv6digest",
                    "platform": {"os": "linux", "architecture": "arm", "variant": "v6"}
                }
            ]
        }

        assert checker._extract_platform_digest(manifest, "linux/arm/v7") == "sha256:armv7digest"
        assert checker._extract_platform_digest(manifest, "linux/arm/v6") == "sha256:armv6digest"
        # Without variant, should match the first arm entry (v7)
        assert checker._extract_platform_digest(manifest, "linux/arm") == "sha256:armv7digest"

    def test_extract_with_none_manifest(self):
        """Should return None for None manifest"""
        checker = UpdateChecker(db=None, monitor=None)
        assert checker._extract_platform_digest(None, "linux/amd64") is None


class TestMatchesIgnorePattern:
    """
    Ignore patterns must match the image *name* (repository), not the tag
    (Issue #220) or the registry host. Container-name matching stays substring.
    """

    def test_pattern_does_not_match_tag(self):
        """'nginx' ignore pattern must NOT skip ghcr.io/aalmenar/baikal:nginx."""
        checker = UpdateChecker(db=None, monitor=None)

        container = {"name": "baikal", "image": "ghcr.io/aalmenar/baikal:nginx"}

        assert checker._matches_ignore_pattern(container, ["nginx"]) is False

    def test_pattern_does_not_match_registry_host(self):
        """'docker' ignore pattern must NOT skip every docker.io image."""
        checker = UpdateChecker(db=None, monitor=None)

        container = {"name": "my-postgres", "image": "docker.io/library/postgres:16"}

        assert checker._matches_ignore_pattern(container, ["docker"]) is False

    def test_pattern_matches_repository_name(self):
        """A genuine image-name match still skips the container."""
        checker = UpdateChecker(db=None, monitor=None)

        container = {"name": "web", "image": "docker.io/library/nginx:1.25"}

        assert checker._matches_ignore_pattern(container, ["nginx"]) is True

    def test_pattern_matches_container_name(self):
        """Container-name substring matching is unaffected."""
        checker = UpdateChecker(db=None, monitor=None)

        container = {"name": "my-traefik-proxy", "image": "ghcr.io/org/app:latest"}

        assert checker._matches_ignore_pattern(container, ["traefik"]) is True

    def test_no_patterns_never_matches(self):
        """Empty pattern list never matches."""
        checker = UpdateChecker(db=None, monitor=None)

        container = {"name": "nginx", "image": "nginx:latest"}

        assert checker._matches_ignore_pattern(container, []) is False
