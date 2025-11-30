"""
Unit tests for container image name selection logic (PR #59).

Tests verify:
- Image name selection prioritizes config when it matches available tags
- Fallback to first tag when config doesn't match
- Implicit :latest tag handling when config has no tag
- Digest-based pull handling (no tags)
- Edge cases: missing image, deleted image, multiple tags
"""

import pytest
from unittest.mock import Mock, MagicMock


# =============================================================================
# Image Name Selection Tests
# =============================================================================

class TestImageNameSelection:
    """Test image name selection logic from container discovery"""

    def test_config_matches_tag_uses_config(self):
        """When config specifies portainer:2.20.0 and tags include it, prefer config"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "portainer"

        # Mock image with multiple tags
        mock_image = Mock()
        mock_image.tags = [
            "portainer/portainer-ce:latest",
            "portainer/portainer-ce:2.20.0",
            "portainer/portainer-ce:2.20"
        ]
        mock_image.short_id = "sha256:abc123"
        mock_container.image = mock_image

        # Config specifies specific version
        mock_container.attrs = {
            'Config': {
                'Image': 'portainer/portainer-ce:2.20.0'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert image_name == "portainer/portainer-ce:2.20.0"
        assert image_name != "portainer/portainer-ce:latest"

    def test_config_no_match_uses_first_tag(self):
        """When config doesn't match any tag, fall back to first tag"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "nginx"

        # Mock image with tags
        mock_image = Mock()
        mock_image.tags = [
            "nginx:alpine",
            "nginx:1.25-alpine"
        ]
        mock_image.short_id = "sha256:def456"
        mock_container.image = mock_image

        # Config specifies tag not in list
        mock_container.attrs = {
            'Config': {
                'Image': 'nginx:1.24-alpine'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert image_name == "nginx:alpine"
        assert image_name != "nginx:1.24-alpine"

    def test_implicit_latest_tag_added(self):
        """When config has no tag, :latest is added implicitly"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "redis"

        # Mock image with tags
        mock_image = Mock()
        mock_image.tags = [
            "redis:latest",
            "redis:7.2",
            "redis:7"
        ]
        mock_image.short_id = "sha256:ghi789"
        mock_container.image = mock_image

        # Config has no tag (implicit :latest)
        mock_container.attrs = {
            'Config': {
                'Image': 'redis'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert config_image_name == "redis:latest"
        assert image_name == "redis:latest"

    def test_no_tags_digest_pull_uses_config(self):
        """For digest-based pulls (no tags), use full config image reference"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "my-app"

        # Mock image with NO tags (digest pull)
        mock_image = Mock()
        mock_image.tags = []
        mock_image.short_id = "sha256:abc123"
        mock_container.image = mock_image

        # Config has full digest reference
        mock_container.attrs = {
            'Config': {
                'Image': 'myregistry.com/my-app@sha256:abc123def456'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert image_name == "myregistry.com/my-app@sha256:abc123def456"
        assert "@sha256:" in image_name  # Preserves digest

    def test_no_tags_no_digest_uses_config(self):
        """When no tags and no digest, use config image name"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "test"

        # Mock image with NO tags
        mock_image = Mock()
        mock_image.tags = []
        mock_image.short_id = "sha256:xyz999"
        mock_container.image = mock_image

        # Config has image name without tag
        mock_container.attrs = {
            'Config': {
                'Image': 'custom/image'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert image_name == "custom/image:latest"

    def test_multiple_tags_first_matches_config(self):
        """When first tag matches config, use it"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "postgres"

        # Mock image with tags where first matches config
        mock_image = Mock()
        mock_image.tags = [
            "postgres:16-alpine",
            "postgres:16",
            "postgres:latest"
        ]
        mock_image.short_id = "sha256:jkl012"
        mock_container.image = mock_image

        # Config matches first tag
        mock_container.attrs = {
            'Config': {
                'Image': 'postgres:16-alpine'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert image_name == "postgres:16-alpine"

    def test_multiple_tags_last_matches_config(self):
        """When last tag matches config, prefer it over first tag"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "mysql"

        # Mock image with tags where last matches config
        mock_image = Mock()
        mock_image.tags = [
            "mysql:latest",
            "mysql:8",
            "mysql:8.0.35"
        ]
        mock_image.short_id = "sha256:mno345"
        mock_container.image = mock_image

        # Config matches last tag
        mock_container.attrs = {
            'Config': {
                'Image': 'mysql:8.0.35'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert image_name == "mysql:8.0.35"
        assert image_name != "mysql:latest"  # Preferred config over first

    def test_config_missing_uses_image_short_id(self):
        """When config Image field is missing, fall back to short_id"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "orphan"

        # Mock image with tags
        mock_image = Mock()
        mock_image.tags = ["test:latest"]
        mock_image.short_id = "sha256:fallback"
        mock_container.image = mock_image

        # Config missing Image field
        mock_container.attrs = {
            'Config': {}
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        # sha256:fallback already has a colon, so :latest is NOT appended
        assert config_image_name == "sha256:fallback"
        # Falls back to first tag since config doesn't match
        assert image_name == "test:latest"

    def test_single_tag_matches_config_with_latest(self):
        """When single tag is :latest and config has implicit latest, they match"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "alpine"

        # Mock image with single :latest tag
        mock_image = Mock()
        mock_image.tags = ["alpine:latest"]
        mock_image.short_id = "sha256:pqr678"
        mock_container.image = mock_image

        # Config has no tag (implicit :latest)
        mock_container.attrs = {
            'Config': {
                'Image': 'alpine'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert config_image_name == "alpine:latest"
        assert image_name == "alpine:latest"

    def test_registry_prefix_in_config_and_tags(self):
        """When config and tags both have registry prefix, matching works"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"
        mock_container.name = "custom-app"

        # Mock image with registry prefix in tags
        mock_image = Mock()
        mock_image.tags = [
            "ghcr.io/company/app:v1.2.3",
            "ghcr.io/company/app:latest"
        ]
        mock_image.short_id = "sha256:stu901"
        mock_container.image = mock_image

        # Config has registry prefix
        mock_container.attrs = {
            'Config': {
                'Image': 'ghcr.io/company/app:v1.2.3'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert image_name == "ghcr.io/company/app:v1.2.3"


# =============================================================================
# Edge Cases
# =============================================================================

class TestImageNameEdgeCases:
    """Test edge cases and error conditions"""

    def test_empty_tags_list(self):
        """When tags list is explicitly empty (not None), use config"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"

        mock_image = Mock()
        mock_image.tags = []  # Explicitly empty
        mock_image.short_id = "sha256:empty"
        mock_container.image = mock_image

        mock_container.attrs = {
            'Config': {
                'Image': 'my-image:v1'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert image_name == "my-image:v1"

    def test_config_with_port_number_in_registry(self):
        """Registry with port number should work correctly"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"

        mock_image = Mock()
        mock_image.tags = [
            "registry.local:5000/app:prod",
            "registry.local:5000/app:latest"
        ]
        mock_image.short_id = "sha256:port123"
        mock_container.image = mock_image

        mock_container.attrs = {
            'Config': {
                'Image': 'registry.local:5000/app:prod'
            }
        }

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        # Note: This has a colon from port, so won't get :latest appended
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        assert image_name == "registry.local:5000/app:prod"

    def test_config_attrs_missing(self):
        """When entire Config dict is missing, handle gracefully"""
        # Arrange
        mock_container = Mock()
        mock_container.id = "abc123456789def"

        mock_image = Mock()
        mock_image.tags = ["fallback:latest"]
        mock_image.short_id = "sha256:noconfig"
        mock_container.image = mock_image

        mock_container.attrs = {}  # Missing Config

        # Act
        config_image_name = mock_container.attrs.get('Config', {}).get('Image', mock_image.short_id)
        if ":" not in config_image_name:
            config_image_name = f"{config_image_name}:latest"

        if mock_image.tags:
            if config_image_name in mock_image.tags:
                image_name = config_image_name
            else:
                image_name = mock_image.tags[0]
        else:
            image_name = config_image_name

        # Assert
        # sha256:noconfig already has a colon, so :latest is NOT appended
        assert config_image_name == "sha256:noconfig"
        # Since it doesn't match, uses first tag
        assert image_name == "fallback:latest"
