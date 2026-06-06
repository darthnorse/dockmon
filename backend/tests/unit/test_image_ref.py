"""
Unit tests for image reference parsing.

Tests extract_image_repository(), which extracts the repository (image name)
from a full image reference, stripping registry host, tag, and digest. Used by
update-policy pattern matching so a pattern like 'nginx' is matched against the
image *name* only - not the tag (Issue #220) or the registry host.
"""

import pytest
from utils.image_ref import extract_image_repository


class TestStripsTag:
    """Tag must be stripped before matching (Issue #220)."""

    def test_simple_name_with_tag(self):
        assert extract_image_repository("nginx:1.25") == "nginx"

    def test_namespaced_with_tag(self):
        # The reported case: tag 'nginx' must NOT leak into the repository
        assert extract_image_repository("ghcr.io/aalmenar/baikal:nginx") == "aalmenar/baikal"

    def test_no_tag(self):
        assert extract_image_repository("nginx") == "nginx"

    def test_latest_tag(self):
        assert extract_image_repository("traefik:latest") == "traefik"


class TestStripsRegistry:
    """Registry host must be stripped so patterns don't match the hostname."""

    def test_ghcr_registry(self):
        assert extract_image_repository("ghcr.io/org/app:v1.0") == "org/app"

    def test_docker_io_registry(self):
        # A 'docker' pattern must not match every docker.io image
        assert extract_image_repository("docker.io/library/postgres:16") == "library/postgres"

    def test_registry_with_port(self):
        # The colon in the port must not be mistaken for a tag separator
        assert extract_image_repository("myregistry.com:5000/app") == "app"

    def test_registry_with_port_and_tag(self):
        assert extract_image_repository("myregistry.com:5000/app:1.2") == "app"

    def test_localhost_registry(self):
        assert extract_image_repository("localhost:5000/myapp:dev") == "myapp"

    def test_registry_host_containing_pattern_word(self):
        # 'docker' appears only in the host - repository must exclude it
        assert extract_image_repository("registry.docker.mycorp.com/app:1") == "app"


class TestStripsDigest:
    """Digest references must be stripped."""

    def test_digest_only(self):
        assert extract_image_repository("ghcr.io/org/app@sha256:abc123") == "org/app"

    def test_tag_and_digest(self):
        assert extract_image_repository("nginx:1.25@sha256:abc123") == "nginx"


class TestDefensive:
    """Helper runs in the check hot-loop - it must never raise."""

    def test_empty_string(self):
        assert extract_image_repository("") == ""

    def test_none(self):
        assert extract_image_repository(None) == ""

    def test_bare_digest_without_name(self):
        # Docker/agent can return a bare digest with no image name (Issue #116)
        assert extract_image_repository("sha256:abc123def456") == ""

    def test_does_not_lowercase(self):
        # Callers handle case-folding themselves; helper preserves case
        assert extract_image_repository("ghcr.io/Org/App:Tag") == "Org/App"
