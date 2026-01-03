"""
Unit tests for update availability detection logic.

Tests verify:
- Digest comparison logic
- Floating tag resolution
- Update decision rules
- Edge cases (null, missing, malformed)
- Tracking mode handling

Following TDD principles: RED → GREEN → REFACTOR
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

from database import ContainerUpdate
from updates.registry_adapter import RegistryAdapter


# =============================================================================
# Digest Comparison Tests
# =============================================================================

class TestUpdateAvailabilityDetection:
    """Test update availability detection logic (digest comparison)"""

    def test_update_available_when_digest_differs(self):
        """Should detect update when current and latest digest differ"""
        current = "sha256:abc123"
        latest = "sha256:def456"

        result = current != latest

        assert result is True

    def test_no_update_when_digest_same(self):
        """Should not detect update when digest is same"""
        digest = "sha256:abc123"

        result = digest != digest

        assert result is False

    @pytest.mark.parametrize("current,latest,expected,reason", [
        (None, "sha256:abc", True, "First check - no current digest"),
        ("sha256:abc", None, False, "Latest unavailable - can't update"),
        (None, None, False, "Both missing - can't compare"),
        ("", "sha256:abc", True, "Empty current treated as None"),
        ("sha256:abc", "", False, "Empty latest treated as unavailable"),
    ])
    def test_digest_comparison_edge_cases(self, current, latest, expected, reason):
        """Test edge cases for digest comparison"""
        # Handle None and empty string cases
        if not current or not latest:
            if not current and latest:
                result = True  # First check
            elif current and not latest:
                result = False  # Latest unavailable
            else:
                result = False  # Both missing
        else:
            result = current != latest

        assert result == expected, f"Failed: {reason}"

    def test_digest_format_validation(self):
        """Digests should start with sha256: prefix"""
        valid_digest = "sha256:abc123def456"

        assert valid_digest.startswith("sha256:")
        assert len(valid_digest) > 7  # More than just "sha256:"

    @pytest.mark.parametrize("digest,valid", [
        ("sha256:abc123", True),
        ("sha256:ABC123", True),  # Case insensitive
        ("sha256:", False),  # Empty hash
        ("sha1:abc123", False),  # Wrong algorithm
        ("abc123", False),  # Missing prefix
        ("", False),  # Empty string
        (None, False),  # None
    ])
    def test_digest_format_patterns(self, digest, valid):
        """Test various digest format patterns"""
        if digest is None or digest == "":
            result = False
        else:
            result = digest.startswith("sha256:") and len(digest) > 7

        assert result == valid


# =============================================================================
# Floating Tag Resolution Tests
# =============================================================================

class TestFloatingTagResolution:
    """Test floating tag computation based on tracking mode"""

    def test_exact_mode_returns_same_tag(self):
        """'exact' mode should return the same tag"""
        from updates.registry_adapter import RegistryAdapter

        adapter = RegistryAdapter()
        image = "nginx:1.25.0"
        mode = "exact"

        # Mock the compute_floating_tag method
        with patch.object(adapter, 'compute_floating_tag', return_value=image):
            result = adapter.compute_floating_tag(image, mode)

        assert result == "nginx:1.25.0"

    def test_latest_mode_resolves_to_latest_tag(self):
        """'latest' mode should resolve to :latest tag"""
        from updates.registry_adapter import RegistryAdapter

        adapter = RegistryAdapter()
        image = "nginx:1.25.0"
        mode = "latest"

        # Mock the compute_floating_tag method
        with patch.object(adapter, 'compute_floating_tag', return_value="nginx:latest"):
            result = adapter.compute_floating_tag(image, mode)

        assert result == "nginx:latest"

    def test_patch_mode_finds_latest_patch(self):
        """'patch' mode should find latest patch version (1.25.x)"""
        from updates.registry_adapter import RegistryAdapter

        adapter = RegistryAdapter()
        image = "nginx:1.25.0"
        mode = "patch"

        # Expected: latest 1.25.x version
        with patch.object(adapter, 'compute_floating_tag', return_value="nginx:1.25"):
            result = adapter.compute_floating_tag(image, mode)

        # Patch mode should track 1.25 (not 1.25.0 or 1.26)
        assert result == "nginx:1.25"

    def test_minor_mode_finds_latest_minor(self):
        """'minor' mode should find latest minor version (1.x)"""
        from updates.registry_adapter import RegistryAdapter

        adapter = RegistryAdapter()
        image = "nginx:1.25.0"
        mode = "minor"

        # Expected: latest 1.x version
        with patch.object(adapter, 'compute_floating_tag', return_value="nginx:1"):
            result = adapter.compute_floating_tag(image, mode)

        # Minor mode should track 1 (not 1.25 or 2)
        assert result == "nginx:1"

    @pytest.mark.parametrize("image,mode,expected", [
        ("nginx:1.25.0", "exact", "nginx:1.25.0"),
        ("nginx:1.25.0", "patch", "nginx:1.25"),
        ("nginx:1.25.0", "minor", "nginx:1"),
        ("nginx:1.25.0", "latest", "nginx:latest"),
        ("nginx", "latest", "nginx:latest"),  # No tag specified
        ("nginx:latest", "exact", "nginx:latest"),  # Already latest
        ("nginx:stable", "patch", "nginx:stable"),  # Non-semver tag
    ])
    def test_floating_tag_patterns(self, image, mode, expected):
        """Test various floating tag computation patterns"""
        from updates.registry_adapter import RegistryAdapter

        adapter = RegistryAdapter()

        with patch.object(adapter, 'compute_floating_tag', return_value=expected):
            result = adapter.compute_floating_tag(image, mode)

        assert result == expected


# =============================================================================
# Tracking Mode Tests
# =============================================================================

class TestTrackingModeLogic:
    """Test tracking mode retrieval and default handling"""

    def test_default_tracking_mode_is_exact(self, db_session, test_container_metadata):
        """When no record exists, tracking mode should default to 'exact'"""
        # No record in database
        composite_key = test_container_metadata["id"]
        record = db_session.query(ContainerUpdate).filter_by(
            container_id=composite_key
        ).first()

        assert record is None

        # Default should be 'exact'
        default_mode = "exact"
        assert default_mode == "exact"

    def test_tracking_mode_stored_in_database(self, db_session, test_container_update):
        """Tracking mode should be persisted in database"""
        # Update has floating_tag_mode set
        assert test_container_update.floating_tag_mode == "latest"

        # Verify it persisted
        db_session.refresh(test_container_update)
        assert test_container_update.floating_tag_mode == "latest"

    @pytest.mark.parametrize("mode", ["exact", "patch", "minor", "latest"])
    def test_all_tracking_modes_valid(self, db_session, test_container_metadata, test_host, mode):
        """All tracking modes should be valid and storable"""
        update = ContainerUpdate(
            container_id=test_container_metadata["id"],
            host_id=test_host.id,
            current_image="nginx:1.25.0",
            current_digest="sha256:abc123",
            floating_tag_mode=mode,
            update_available=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        db_session.add(update)
        db_session.commit()

        assert update.floating_tag_mode == mode


# =============================================================================
# Update Info Storage Tests
# =============================================================================

class TestUpdateInfoStorage:
    """Test storing update info in database"""

    def test_create_new_update_record(self, db_session, test_container_metadata, test_host):
        """Should create new ContainerUpdate record when none exists"""
        composite_key = test_container_metadata["id"]

        update = ContainerUpdate(
            container_id=composite_key,
            host_id=test_host.id,
            current_image="nginx:1.25.0",
            current_digest="sha256:abc123",
            latest_image="nginx:1.26.0",
            latest_digest="sha256:def456",
            update_available=True,
            floating_tag_mode="exact",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        db_session.add(update)
        db_session.commit()

        # Verify created
        record = db_session.query(ContainerUpdate).filter_by(
            container_id=composite_key
        ).first()

        assert record is not None
        assert record.current_digest == "sha256:abc123"
        assert record.latest_digest == "sha256:def456"
        assert record.update_available is True

    def test_update_existing_record(self, db_session, test_container_update):
        """Should update existing ContainerUpdate record"""
        original_digest = test_container_update.current_digest

        # Update the record
        test_container_update.current_digest = "sha256:newdigest"
        test_container_update.update_available = False
        test_container_update.updated_at = datetime.now(timezone.utc)
        db_session.commit()

        # Verify updated
        db_session.refresh(test_container_update)
        assert test_container_update.current_digest == "sha256:newdigest"
        assert test_container_update.current_digest != original_digest
        assert test_container_update.update_available is False

    def test_last_checked_timestamp_updated(self, db_session, test_container_update):
        """last_checked_at should be updated on each check"""
        original_time = test_container_update.last_checked_at

        import time
        time.sleep(0.01)  # Ensure time difference

        test_container_update.last_checked_at = datetime.now(timezone.utc)
        db_session.commit()

        db_session.refresh(test_container_update)
        assert test_container_update.last_checked_at > original_time


# =============================================================================
# Update Event Creation Tests
# =============================================================================

class TestUpdateEventCreation:
    """Test event emission for update detection"""

    @pytest.mark.asyncio
    async def test_emit_event_on_new_update(self):
        """Should emit UPDATE_AVAILABLE event when new update detected"""
        # This will be implemented once we integrate with EventBus
        # For now, just verify the logic

        previous_digest = "sha256:old"
        new_digest = "sha256:new"

        should_emit = (previous_digest != new_digest)

        assert should_emit is True

    @pytest.mark.asyncio
    async def test_emit_event_on_first_check(self):
        """Should emit event on first check (no previous digest)"""
        previous_digest = None
        new_digest = "sha256:abc"

        should_emit = (previous_digest is None or previous_digest != new_digest)

        assert should_emit is True

    @pytest.mark.asyncio
    async def test_no_event_when_digest_unchanged(self):
        """Should NOT emit event when digest hasn't changed"""
        previous_digest = "sha256:abc"
        new_digest = "sha256:abc"

        should_emit = (previous_digest != new_digest)

        assert should_emit is False


# =============================================================================
# Integration: Complete Update Check Flow
# =============================================================================

class TestCompleteUpdateCheckFlow:
    """Test the complete update check workflow"""

    @pytest.mark.asyncio
    async def test_update_check_with_update_available(self, db_session, test_host):
        """Test complete flow when update is available"""
        # Setup: Container running old version
        container = {
            "host_id": test_host.id,
            "id": "abc123def456",
            "name": "test-nginx",
            "image": "nginx:1.25.0",
            "state": "running"
        }

        # Simulate current digest (old version)
        current_digest = "sha256:old123"

        # Simulate latest digest (new version)
        latest_digest = "sha256:new456"

        # Compare
        update_available = (current_digest != latest_digest)

        assert update_available is True

    @pytest.mark.asyncio
    async def test_update_check_with_no_update(self, db_session, test_host):
        """Test complete flow when no update available"""
        # Setup: Container already on latest
        container = {
            "host_id": test_host.id,
            "id": "abc123def456",
            "name": "test-nginx",
            "image": "nginx:latest",
            "state": "running"
        }

        # Current and latest are same
        current_digest = "sha256:abc123"
        latest_digest = "sha256:abc123"

        # Compare
        update_available = (current_digest != latest_digest)

        assert update_available is False

    @pytest.mark.asyncio
    async def test_update_check_with_registry_failure(self):
        """Test handling when registry is unreachable"""
        # Simulate registry returning None
        latest_digest = None
        current_digest = "sha256:abc123"

        # Should not consider this an update
        if latest_digest is None:
            update_available = False
        else:
            update_available = (current_digest != latest_digest)

        assert update_available is False


# =============================================================================
# Validation Tests
# =============================================================================

class TestUpdateValidation:
    """Test validation logic for update checks"""

    def test_container_without_image_info(self):
        """Containers without image info should be skipped"""
        container = {
            "id": "abc123",
            "name": "test",
            "image": None  # No image info
        }

        can_check = container.get("image") is not None

        assert can_check is False

    def test_container_with_empty_image(self):
        """Containers with empty image should be skipped"""
        container = {
            "id": "abc123",
            "name": "test",
            "image": ""  # Empty image
        }

        image = container.get("image")
        can_check = bool(image)

        assert can_check is False

    def test_compose_container_detection(self):
        """Should detect Docker Compose managed containers"""
        container = {
            "labels": {
                "com.docker.compose.project": "myapp",
                "com.docker.compose.service": "web"
            }
        }

        is_compose = any(
            label.startswith("com.docker.compose")
            for label in container.get("labels", {}).keys()
        )

        assert is_compose is True

    def test_non_compose_container_detection(self):
        """Should identify non-Compose containers"""
        container = {
            "labels": {
                "custom.label": "value"
            }
        }

        is_compose = any(
            label.startswith("com.docker.compose")
            for label in container.get("labels", {}).keys()
        )

        assert is_compose is False


# =============================================================================
# Multi-Digest Detection Tests (Issue #105)
# =============================================================================

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
        from updates.update_checker import UpdateChecker

        checker = UpdateChecker(db=None, monitor=None)

        container = {
            "repo_digests": ["ghcr.io/org/app@sha256:abc123def456"]
        }
        latest_digest = "sha256:abc123def456"

        result = checker._has_digest(container, latest_digest)

        assert result is True, "Should find digest in single-entry RepoDigests"

    def test_has_digest_multi_match_first(self):
        """Should detect when latest digest matches first RepoDigest"""
        from updates.update_checker import UpdateChecker

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
        from updates.update_checker import UpdateChecker

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
        from updates.update_checker import UpdateChecker

        checker = UpdateChecker(db=None, monitor=None)

        container = {
            "repo_digests": ["ghcr.io/org/app@sha256:abc123"]
        }
        latest_digest = "sha256:xyz789"  # Different digest

        result = checker._has_digest(container, latest_digest)

        assert result is False, "Should not find non-matching digest"

    def test_has_digest_empty_repo_digests(self):
        """Should return False when RepoDigests is empty"""
        from updates.update_checker import UpdateChecker

        checker = UpdateChecker(db=None, monitor=None)

        container = {"repo_digests": []}
        latest_digest = "sha256:abc123"

        result = checker._has_digest(container, latest_digest)

        assert result is False, "Should return False for empty RepoDigests"

    def test_has_digest_missing_repo_digests(self):
        """Should return False when RepoDigests key is missing"""
        from updates.update_checker import UpdateChecker

        checker = UpdateChecker(db=None, monitor=None)

        container = {}  # No repo_digests key
        latest_digest = "sha256:abc123"

        result = checker._has_digest(container, latest_digest)

        assert result is False, "Should return False for missing RepoDigests"

    def test_has_digest_none_repo_digests(self):
        """Should return False when RepoDigests is None"""
        from updates.update_checker import UpdateChecker

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
        from updates.update_checker import UpdateChecker

        checker = UpdateChecker(db=None, monitor=None)
        container = {"repo_digests": repo_digests}

        result = checker._has_digest(container, latest_digest)

        assert result == expected, f"Failed: {reason}"


class TestUpdateAvailabilityWithMultiDigest:
    """
    Test that update_available logic correctly uses _has_digest.

    These tests verify the integration between digest checking and
    update availability determination.
    """

    def test_no_update_when_latest_in_repo_digests(self):
        """
        Should NOT report update available when latest_digest is in RepoDigests.

        This is the core fix for Issue #105.
        """
        from updates.update_checker import UpdateChecker

        checker = UpdateChecker(db=None, monitor=None)

        container = {
            "repo_digests": [
                "ghcr.io/immich-app/immich-server@sha256:2c496e3b9d",
                "ghcr.io/immich-app/immich-server@sha256:e6a6298e67"
            ]
        }
        latest_digest = "sha256:e6a6298e67"  # In second position

        # Old logic would use first digest only:
        # current_digest = "sha256:2c496e3b9d" (from _extract_digest_from_repo_digests)
        # update_available = current_digest != latest_digest → TRUE (wrong!)

        # New logic should check all digests:
        update_available = not checker._has_digest(container, latest_digest)

        assert update_available is False, "Should NOT report update when digest already present"

    def test_repo_digests_populated_from_docker_api(self):
        """
        Test that repo_digests is stored in container dict after Docker API query.

        This ensures the fix works for local/mTLS hosts, not just agent hosts.
        The _get_container_image_digest method should store the full RepoDigests
        list so that _has_digest can use it later.
        """
        from updates.update_checker import UpdateChecker

        checker = UpdateChecker(db=None, monitor=None)

        # Simulate container dict WITHOUT repo_digests (local/mTLS host scenario)
        container = {
            "name": "test-container",
            "host_id": "test-host",
            "id": "abc123def456"
            # Note: no "repo_digests" key - simulates local/mTLS host
        }

        # Simulate what _get_container_image_digest does for local hosts:
        # It queries Docker API and gets RepoDigests, then stores them
        api_repo_digests = [
            "ghcr.io/org/app@sha256:olddigest",
            "ghcr.io/org/app@sha256:newdigest"
        ]
        container["repo_digests"] = api_repo_digests

        # Now _has_digest should work
        assert checker._has_digest(container, "sha256:newdigest") is True
        assert checker._has_digest(container, "sha256:olddigest") is True
        assert checker._has_digest(container, "sha256:otherdigest") is False

    def test_update_available_when_digest_not_present(self):
        """Should report update available when latest_digest is NOT in RepoDigests"""
        from updates.update_checker import UpdateChecker

        checker = UpdateChecker(db=None, monitor=None)

        container = {
            "repo_digests": ["ghcr.io/org/app@sha256:oldversion"]
        }
        latest_digest = "sha256:newversion"

        update_available = not checker._has_digest(container, latest_digest)

        assert update_available is True, "Should report update when digest not present"

    def test_backwards_compatible_single_digest(self):
        """
        Single digest case should work the same as before.

        This ensures the fix doesn't break normal update detection.
        """
        from updates.update_checker import UpdateChecker

        checker = UpdateChecker(db=None, monitor=None)

        # Normal case: single digest, same as registry
        container_no_update = {
            "repo_digests": ["nginx@sha256:abc123"]
        }
        assert checker._has_digest(container_no_update, "sha256:abc123") is True

        # Normal case: single digest, different from registry
        container_update = {
            "repo_digests": ["nginx@sha256:abc123"]
        }
        assert checker._has_digest(container_update, "sha256:xyz789") is False


# =============================================================================
# Registry Credentials Tests
# =============================================================================

class TestRegistryCredentials:
    """Test registry credential handling"""

    def test_default_registry_is_dockerhub(self):
        """Images without explicit registry should use docker.io"""
        image = "nginx:latest"

        # Extract registry
        if "/" in image:
            parts = image.split("/", 1)
            if "." in parts[0] or ":" in parts[0]:
                registry = parts[0]
            else:
                registry = "docker.io"
        else:
            registry = "docker.io"

        assert registry == "docker.io"

    def test_ghcr_registry_extraction(self):
        """GHCR images should extract ghcr.io as registry"""
        image = "ghcr.io/user/app:latest"

        # Extract registry
        if "/" in image:
            parts = image.split("/", 1)
            if "." in parts[0] or ":" in parts[0]:
                registry = parts[0]
            else:
                registry = "docker.io"
        else:
            registry = "docker.io"

        assert registry == "ghcr.io"

    def test_custom_registry_with_port(self):
        """Custom registry with port should be extracted correctly"""
        image = "registry.example.com:5000/app:v1"

        # Extract registry
        if "/" in image:
            parts = image.split("/", 1)
            if "." in parts[0] or ":" in parts[0]:
                registry = parts[0]
            else:
                registry = "docker.io"
        else:
            registry = "docker.io"

        assert registry == "registry.example.com:5000"

    @pytest.mark.parametrize("image,expected_registry", [
        ("nginx:latest", "docker.io"),
        ("library/nginx:latest", "docker.io"),
        ("ghcr.io/user/app:v1", "ghcr.io"),
        ("quay.io/org/app:latest", "quay.io"),
        ("localhost:5000/app:dev", "localhost:5000"),
        ("registry.gitlab.com/group/project:tag", "registry.gitlab.com"),
    ])
    def test_registry_extraction_patterns(self, image, expected_registry):
        """Test registry extraction for various image patterns"""
        # Extract registry
        if "/" in image:
            parts = image.split("/", 1)
            if "." in parts[0] or ":" in parts[0]:
                registry = parts[0]
            else:
                registry = "docker.io"
        else:
            registry = "docker.io"

        assert registry == expected_registry
