"""
Unit tests for version parsing and comparison in UpdateChecker.

Tests the _parse_version_from_tag(), _extract_version_from_tag(), and
_is_downgrade() methods used for version display (Issue #178) and
downgrade suppression (Issue #147).
"""

import pytest
from unittest.mock import Mock

from updates.update_checker import UpdateChecker


@pytest.fixture
def checker():
    """Create UpdateChecker with mocked dependencies."""
    mock_db = Mock()
    return UpdateChecker(db=mock_db)


class TestParseVersionFromTag:
    """Tests for _parse_version_from_tag() method."""

    def test_simple_semver(self, checker):
        assert checker._parse_version_from_tag("1.25.3") == (1, 25, 3)

    def test_semver_with_suffix(self, checker):
        assert checker._parse_version_from_tag("32.0.3-fpm-alpine") == (32, 0, 3)

    def test_semver_with_v_prefix(self, checker):
        assert checker._parse_version_from_tag("v2.1.0") == (2, 1, 0)

    def test_major_minor_only(self, checker):
        assert checker._parse_version_from_tag("1.25") == (1, 25, 0)

    def test_major_minor_with_suffix(self, checker):
        assert checker._parse_version_from_tag("32.0-fpm-alpine") == (32, 0, 0)

    def test_major_only(self, checker):
        assert checker._parse_version_from_tag("3") == (3, 0, 0)

    def test_full_image_reference(self, checker):
        assert checker._parse_version_from_tag("nginx:1.25.3-alpine") == (1, 25, 3)

    def test_full_image_reference_with_registry(self, checker):
        assert checker._parse_version_from_tag("ghcr.io/org/app:2.0.1") == (2, 0, 1)

    def test_non_semver_latest(self, checker):
        assert checker._parse_version_from_tag("latest") is None

    def test_non_semver_stable(self, checker):
        assert checker._parse_version_from_tag("stable") is None

    def test_non_semver_alpine(self, checker):
        assert checker._parse_version_from_tag("alpine") is None

    def test_empty_string(self, checker):
        assert checker._parse_version_from_tag("") is None

    def test_none_input(self, checker):
        assert checker._parse_version_from_tag(None) is None

    def test_complex_suffix(self, checker):
        assert checker._parse_version_from_tag("1.2.3-beta.1+build.456") == (1, 2, 3)

    def test_four_part_version(self, checker):
        # 1.2.3.4 should parse as (1, 2, 3), ignoring .4
        assert checker._parse_version_from_tag("1.2.3.4") == (1, 2, 3)


class TestIsDowngrade:
    """Tests for _is_downgrade() method."""

    def test_older_patch_is_downgrade(self, checker):
        assert checker._is_downgrade((32, 0, 3), (32, 0, 0)) is True

    def test_newer_patch_is_not_downgrade(self, checker):
        assert checker._is_downgrade((32, 0, 3), (32, 0, 4)) is False

    def test_same_version_is_not_downgrade(self, checker):
        # Same version with different digest should be allowed (security patches)
        assert checker._is_downgrade((32, 0, 3), (32, 0, 3)) is False

    def test_older_minor_is_downgrade(self, checker):
        assert checker._is_downgrade((1, 25, 3), (1, 24, 0)) is True

    def test_newer_minor_is_not_downgrade(self, checker):
        assert checker._is_downgrade((1, 25, 3), (1, 26, 0)) is False

    def test_older_major_is_downgrade(self, checker):
        assert checker._is_downgrade((2, 0, 0), (1, 99, 99)) is True

    def test_newer_major_is_not_downgrade(self, checker):
        assert checker._is_downgrade((2, 99, 99), (3, 0, 0)) is False

    def test_edge_case_zero_versions(self, checker):
        assert checker._is_downgrade((0, 0, 1), (0, 0, 0)) is True
        assert checker._is_downgrade((0, 0, 0), (0, 0, 1)) is False

    def test_large_version_numbers(self, checker):
        assert checker._is_downgrade((2024, 1, 15), (2024, 1, 14)) is True
        assert checker._is_downgrade((2024, 1, 14), (2024, 1, 15)) is False


class TestDowngradeDetectionIntegration:
    """Integration tests for the downgrade detection flow."""

    def test_nextcloud_scenario(self, checker):
        """Issue #147: Nextcloud 32.0.3-fpm-alpine with patch tracking.
        Floating tag 32.0-fpm-alpine is older - should detect as downgrade.
        """
        current_ver = checker._parse_version_from_tag("nextcloud:32.0.3-fpm-alpine")
        latest_ver = checker._parse_version_from_tag("nextcloud:32.0-fpm-alpine")

        assert current_ver == (32, 0, 3)
        assert latest_ver == (32, 0, 0)
        assert checker._is_downgrade(current_ver, latest_ver) is True

    def test_legitimate_update_scenario(self, checker):
        """Legitimate update: nginx 1.25.3 -> 1.25.4 should NOT be suppressed."""
        current_ver = checker._parse_version_from_tag("nginx:1.25.3")
        latest_ver = checker._parse_version_from_tag("nginx:1.25.4")

        assert current_ver == (1, 25, 3)
        assert latest_ver == (1, 25, 4)
        assert checker._is_downgrade(current_ver, latest_ver) is False

    def test_rebuild_scenario(self, checker):
        """Same version with new digest (security patch) should NOT be suppressed."""
        current_ver = checker._parse_version_from_tag("app:1.0.0")
        latest_ver = checker._parse_version_from_tag("app:1.0.0")

        assert current_ver == (1, 0, 0)
        assert latest_ver == (1, 0, 0)
        assert checker._is_downgrade(current_ver, latest_ver) is False

    def test_non_parseable_versions_bypass_check(self, checker):
        """Non-parseable versions (stable, latest) return None - check is skipped."""
        current_ver = checker._parse_version_from_tag("app:stable")
        latest_ver = checker._parse_version_from_tag("app:latest")

        assert current_ver is None
        assert latest_ver is None


class TestExtractVersionFromTag:
    """Tests for _extract_version_from_tag() - Issue #178 fallback for notification variables."""

    def test_simple_semver(self, checker):
        assert checker._extract_version_from_tag("nginx:1.25.3") == "1.25.3"

    def test_semver_with_suffix(self, checker):
        assert checker._extract_version_from_tag("nextcloud:32.0.3-fpm-alpine") == "32.0.3"

    def test_v_prefix_stripped(self, checker):
        """v-prefix is stripped to match OCI label format (e.g., '2.1.0' not 'v2.1.0')."""
        assert checker._extract_version_from_tag("app:v2.1.0") == "2.1.0"

    def test_v_prefix_major_minor_only(self, checker):
        assert checker._extract_version_from_tag("app:v7.2") == "7.2"

    def test_major_minor_only(self, checker):
        assert checker._extract_version_from_tag("redis:7.2") == "7.2"

    def test_four_part_version(self, checker):
        assert checker._extract_version_from_tag("app:1.2.3.4") == "1.2.3.4"

    def test_registry_prefix(self, checker):
        assert checker._extract_version_from_tag("ghcr.io/org/app:3.1.4") == "3.1.4"

    def test_latest_returns_none(self, checker):
        assert checker._extract_version_from_tag("nginx:latest") is None

    def test_stable_returns_none(self, checker):
        assert checker._extract_version_from_tag("app:stable") is None

    def test_alpine_returns_none(self, checker):
        assert checker._extract_version_from_tag("nginx:alpine") is None

    def test_no_tag_returns_none(self, checker):
        assert checker._extract_version_from_tag("nginx") is None

    def test_empty_returns_none(self, checker):
        assert checker._extract_version_from_tag("") is None

    def test_none_returns_none(self, checker):
        assert checker._extract_version_from_tag(None) is None

    def test_registry_with_port(self, checker):
        assert checker._extract_version_from_tag("myregistry.local:5000/app:2.0.0") == "2.0.0"

    def test_registry_with_port_no_tag(self, checker):
        """Registry port should not be extracted as a version."""
        assert checker._extract_version_from_tag("myregistry.local:5000/app") is None

    def test_major_only_returns_none(self, checker):
        """Single number tags like 'redis:7' are ambiguous, not useful as version display."""
        assert checker._extract_version_from_tag("redis:7") is None
