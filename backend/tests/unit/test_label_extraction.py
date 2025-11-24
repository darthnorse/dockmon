"""
Unit tests for label extraction logic in UpdateExecutor.

Tests the _extract_user_labels method that subtracts old image defaults
from container labels to identify user-added customizations.
"""
import pytest
from updates.update_executor import UpdateExecutor


class TestLabelExtraction:
    """Test suite for label extraction logic"""

    @pytest.fixture
    def executor(self):
        """Create UpdateExecutor instance for testing"""
        # UpdateExecutor needs db and monitor, but for unit testing _extract_user_labels
        # we can pass None since the method doesn't use them
        return UpdateExecutor(db=None, monitor=None)

    def test_basic_user_labels_preserved(self, executor):
        """Test that user-added labels are preserved"""
        old_container_labels = {
            "version": "1.0",
            "environment": "production",
            "custom_label": "user_value"
        }
        old_image_labels = {
            "version": "1.0"
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == {
            "environment": "production",
            "custom_label": "user_value"
        }
        assert "version" not in result  # Image default removed

    def test_image_labels_all_removed(self, executor):
        """Test that labels matching image defaults are removed"""
        old_container_labels = {
            "version": "1.0",
            "author": "official"
        }
        old_image_labels = {
            "version": "1.0",
            "author": "official"
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == {}  # All labels matched image defaults

    def test_user_customized_image_labels(self, executor):
        """Test that user-customized image labels are preserved"""
        old_container_labels = {
            "version": "custom",
            "author": "official"
        }
        old_image_labels = {
            "version": "1.0",
            "author": "official"
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == {"version": "custom"}
        assert "author" not in result  # Matched image default

    def test_mixed_labels(self, executor):
        """Test mix of image defaults, user customizations, and user additions"""
        old_container_labels = {
            "org.opencontainers.image.version": "1.0",  # From image
            "com.docker.compose.service": "web",  # From compose
            "environment": "production",  # User added
            "custom.setting": "value"  # User added
        }
        old_image_labels = {
            "org.opencontainers.image.version": "1.0",
            "org.opencontainers.image.author": "maintainer"
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == {
            "com.docker.compose.service": "web",
            "environment": "production",
            "custom.setting": "value"
        }

    def test_empty_container_labels(self, executor):
        """Test handling of empty container labels"""
        old_container_labels = {}
        old_image_labels = {"version": "1.0"}

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == {}

    def test_empty_image_labels(self, executor):
        """Test handling of empty image labels"""
        old_container_labels = {
            "environment": "production",
            "custom": "value"
        }
        old_image_labels = {}

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == old_container_labels  # All preserved

    def test_both_empty(self, executor):
        """Test handling of both empty dicts"""
        result = executor._extract_user_labels({}, {})
        assert result == {}

    def test_none_inputs(self, executor):
        """Test defensive handling of None inputs"""
        result = executor._extract_user_labels(None, None)
        assert result == {}

        result = executor._extract_user_labels(None, {"version": "1.0"})
        assert result == {}

        result = executor._extract_user_labels({"custom": "value"}, None)
        assert result == {"custom": "value"}

    def test_immich_scenario(self, executor):
        """Test real-world Immich scenario (Issue #69)"""
        # Old container with v1.0 labels
        old_container_labels = {
            "org.opencontainers.image.version": "1.0",
            "immich.migration_version": "5.0",
            "com.docker.compose.service": "immich",
            "environment": "production"
        }
        # Old image v1.0 labels
        old_image_labels = {
            "org.opencontainers.image.version": "1.0",
            "immich.migration_version": "5.0"
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        # Should preserve user/compose labels, remove image defaults
        assert result == {
            "com.docker.compose.service": "immich",
            "environment": "production"
        }
        # Stale labels removed
        assert "immich.migration_version" not in result
        assert "org.opencontainers.image.version" not in result

    def test_traefik_labels_preserved(self, executor):
        """Test that Traefik reverse proxy labels are preserved"""
        old_container_labels = {
            "traefik.enable": "true",
            "traefik.http.routers.app.rule": "Host(`example.com`)",
            "traefik.http.services.app.loadbalancer.server.port": "80",
            "org.opencontainers.image.version": "1.0"
        }
        old_image_labels = {
            "org.opencontainers.image.version": "1.0"
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        # All Traefik labels preserved (user infrastructure)
        assert "traefik.enable" in result
        assert "traefik.http.routers.app.rule" in result
        assert "traefik.http.services.app.loadbalancer.server.port" in result
        # Image default removed
        assert "org.opencontainers.image.version" not in result

    def test_whitespace_values(self, executor):
        """Test handling of whitespace in label values"""
        old_container_labels = {
            "label1": "  value with spaces  ",
            "label2": "value"
        }
        old_image_labels = {
            "label1": "  value with spaces  ",  # Exact match
            "label2": " value"  # Different whitespace
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        # label1 matches exactly, removed
        # label2 has different whitespace, preserved
        assert result == {"label2": "value"}

    def test_empty_string_values(self, executor):
        """Test handling of empty string values"""
        old_container_labels = {
            "label1": "",
            "label2": "value"
        }
        old_image_labels = {
            "label1": ""  # Matches empty string
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == {"label2": "value"}
        assert "label1" not in result

    def test_special_characters(self, executor):
        """Test handling of special characters in keys and values"""
        old_container_labels = {
            "traefik.rule": "Host(`example.com`) && PathPrefix(`/api`)",
            "custom.key-with-dashes": "value",
            "namespace/key": "value"
        }
        old_image_labels = {}

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == old_container_labels  # All preserved

    def test_unicode_labels(self, executor):
        """Test handling of unicode in labels"""
        old_container_labels = {
            "emoji": "🎯",
            "chinese": "你好",
            "german": "Grüße"
        }
        old_image_labels = {}

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == old_container_labels

    def test_very_long_values(self, executor):
        """Test handling of very long label values"""
        long_value = "x" * 10000
        old_container_labels = {
            "long_label": long_value,
            "short_label": "y"
        }
        old_image_labels = {
            "long_label": long_value  # Exact match
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        assert result == {"short_label": "y"}
        assert "long_label" not in result

    def test_case_sensitivity(self, executor):
        """Test that label keys are case-sensitive"""
        old_container_labels = {
            "Label": "value1",
            "label": "value2"
        }
        old_image_labels = {
            "label": "value2"  # Lowercase match
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        # Lowercase "label" removed, uppercase "Label" preserved
        assert result == {"Label": "value1"}

    def test_original_not_modified(self, executor):
        """Test that original dictionaries are not modified"""
        old_container_labels = {"a": "1", "b": "2"}
        old_image_labels = {"a": "1"}

        original_container = old_container_labels.copy()
        original_image = old_image_labels.copy()

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        # Original dicts unchanged
        assert old_container_labels == original_container
        assert old_image_labels == original_image
        # Result is independent
        assert result == {"b": "2"}

    def test_label_not_in_container(self, executor):
        """Test image labels that don't exist in container"""
        old_container_labels = {
            "environment": "production"
        }
        old_image_labels = {
            "version": "1.0",
            "author": "official"
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        # Container label preserved, image-only labels ignored
        assert result == {"environment": "production"}

    def test_compose_stack_labels(self, executor):
        """Test typical Docker Compose stack labels"""
        old_container_labels = {
            "com.docker.compose.project": "myapp",
            "com.docker.compose.service": "web",
            "com.docker.compose.version": "2.20.0",
            "com.docker.compose.container-number": "1",
            "org.opencontainers.image.version": "latest"
        }
        old_image_labels = {
            "org.opencontainers.image.version": "latest"
        }

        result = executor._extract_user_labels(old_container_labels, old_image_labels)

        # All Compose labels preserved (system infrastructure)
        assert "com.docker.compose.project" in result
        assert "com.docker.compose.service" in result
        assert "com.docker.compose.version" in result
        assert "com.docker.compose.container-number" in result
        # Image label removed
        assert "org.opencontainers.image.version" not in result
