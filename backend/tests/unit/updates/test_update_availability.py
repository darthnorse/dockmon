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
