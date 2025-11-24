"""
Unit tests for label extraction during container updates.

Tests the _extract_user_labels method to ensure correct behavior when
extracting user-added labels by filtering out old image defaults.

Issue: #69 (replaces old merge approach from Issue #57)
"""

import pytest
from updates.update_executor import UpdateExecutor


class TestLabelMerge:
    """Test label extraction logic (formerly label merge)"""

    @pytest.fixture
    def executor(self):
        """Create UpdateExecutor instance for testing"""
        return UpdateExecutor(db=None, monitor=None)

    def test_merge_updates_image_labels(self, executor):
        """Image labels from old image should be removed (Docker will add new ones)"""
        old_container_labels = {
            "org.opencontainers.image.version": "1.0.0"
        }
        old_image_labels = {
            "org.opencontainers.image.version": "1.0.0"
        }

        # Extract user labels (removes image defaults)
        user_labels = executor._extract_user_labels(old_container_labels, old_image_labels)

        # Image label removed - Docker will merge from new image
        assert user_labels == {}

    def test_merge_preserves_compose_labels(self, executor):
        """Compose labels should be preserved"""
        old_container_labels = {
            "com.docker.compose.project": "mystack",
            "org.opencontainers.image.version": "1.0.0"
        }
        old_image_labels = {
            "org.opencontainers.image.version": "1.0.0"
        }

        user_labels = executor._extract_user_labels(old_container_labels, old_image_labels)

        # Compose label preserved, image label removed
        assert user_labels == {"com.docker.compose.project": "mystack"}

    def test_merge_preserves_dockmon_labels(self, executor):
        """DockMon tracking labels should be preserved"""
        old_container_labels = {
            "dockmon.deployment_id": "uuid-123",
            "dockmon.managed": "true",
            "org.opencontainers.image.version": "1.0.0"
        }
        old_image_labels = {
            "org.opencontainers.image.version": "1.0.0"
        }

        user_labels = executor._extract_user_labels(old_container_labels, old_image_labels)

        # DockMon labels preserved, image label removed
        assert user_labels == {
            "dockmon.deployment_id": "uuid-123",
            "dockmon.managed": "true"
        }

    def test_merge_preserves_custom_labels(self, executor):
        """User custom labels should be preserved"""
        old_container_labels = {
            "custom.environment": "production",
            "traefik.enable": "true"
        }
        old_image_labels = {}

        user_labels = executor._extract_user_labels(old_container_labels, old_image_labels)

        # All custom labels preserved (no image labels to remove)
        assert user_labels == {
            "custom.environment": "production",
            "traefik.enable": "true"
        }

    def test_merge_with_no_old_labels(self, executor):
        """Should work with empty old container labels"""
        old_container_labels = {}
        old_image_labels = {
            "org.opencontainers.image.version": "2.0.0"
        }

        user_labels = executor._extract_user_labels(old_container_labels, old_image_labels)

        # No container labels = no user labels
        assert user_labels == {}

    def test_merge_with_no_new_labels(self, executor):
        """Should work with empty old image labels"""
        old_container_labels = {
            "custom.environment": "production"
        }
        old_image_labels = {}

        user_labels = executor._extract_user_labels(old_container_labels, old_image_labels)

        # No image labels to subtract = all container labels preserved
        assert user_labels == old_container_labels

    def test_merge_with_both_empty(self, executor):
        """Should work with both empty"""
        user_labels = executor._extract_user_labels({}, {})
        assert user_labels == {}

    def test_merge_adds_new_image_labels(self, executor):
        """New labels from image should NOT be in user labels (Docker adds them)"""
        old_container_labels = {
            "custom.old": "value"
        }
        old_image_labels = {}

        user_labels = executor._extract_user_labels(old_container_labels, old_image_labels)

        # Only custom label preserved
        # New image labels will be added by Docker during container creation
        assert user_labels == {"custom.old": "value"}

    def test_merge_resolves_conflicts_in_favor_of_image(self, executor):
        """When label matches old image, it's removed (new image value will be used)"""
        old_container_labels = {
            "app.version": "1.0",
            "org.opencontainers.image.version": "1.0.0"
        }
        old_image_labels = {
            "app.version": "1.0",
            "org.opencontainers.image.version": "1.0.0"
        }

        user_labels = executor._extract_user_labels(old_container_labels, old_image_labels)

        # Both labels matched old image = both removed
        # New image will provide updated values
        assert user_labels == {}

    def test_merge_with_none_new_labels(self, executor):
        """Should handle None as old_image_labels (defensive)"""
        old_container_labels = {
            "custom.environment": "production"
        }
        old_image_labels = None

        user_labels = executor._extract_user_labels(old_container_labels, old_image_labels)

        # None treated as empty dict = all container labels preserved
        assert user_labels == old_container_labels
