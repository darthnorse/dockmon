"""
Unit tests for Quick Wins validation.

Tests the validation of 4 new Docker Compose directives:
- network_mode
- devices
- extra_hosts
- cap_add / cap_drop
"""

import pytest
from deployment.compose_validator import ComposeValidator, ComposeValidationError


class TestQuickWinsValidation:
    """Test validation for Quick Wins features"""

    def test_validate_network_mode_host(self):
        """Test that network_mode: host passes validation"""
        compose_yaml = """
version: '3.8'
services:
  app:
    image: app:latest
    network_mode: host
"""
        validator = ComposeValidator()
        result = validator.validate(compose_yaml)
        assert result['valid'] is True

    def test_validate_network_mode_invalid(self):
        """Test that invalid network_mode fails validation"""
        compose_yaml = """
version: '3.8'
services:
  app:
    image: app:latest
    network_mode: invalid_mode
"""
        validator = ComposeValidator()
        with pytest.raises(ComposeValidationError, match="Invalid network_mode"):
            validator.validate(compose_yaml)

    def test_validate_network_mode_empty_string(self):
        """FLAW 7 FIX: Test that empty network_mode has clear error message"""
        compose_yaml = """
version: '3.8'
services:
  app:
    image: app:latest
    network_mode: ""
"""
        validator = ComposeValidator()

        try:
            validator.validate(compose_yaml)
            assert False, "Should have raised validation error"
        except ComposeValidationError as e:
            error_msg = str(e)
            # Error should explicitly say "cannot be empty"
            assert "cannot be empty" in error_msg.lower()
            # Error should list valid values
            assert "bridge" in error_msg or "host" in error_msg

    def test_validate_network_mode_conflict_error_message_quality(self):
        """Test that error message for network_mode conflict is helpful"""
        compose_yaml = """
version: '3.8'
services:
  app:
    image: app:latest
    network_mode: host
    networks:
      - mynet
networks:
  mynet:
"""
        validator = ComposeValidator()

        try:
            validator.validate(compose_yaml)
            assert False, "Should have raised validation error"
        except ComposeValidationError as e:
            error_msg = str(e)
            # Error should mention BOTH directives
            assert "network_mode" in error_msg
            assert "networks" in error_msg
            # Error should use clear language
            assert "mutually exclusive" in error_msg or "cannot use both" in error_msg.lower()
            # Error should suggest a fix
            assert "remove" in error_msg.lower() or "choose" in error_msg.lower()

    def test_validate_devices_list(self):
        """Test that devices as list passes validation"""
        compose_yaml = """
version: '3.8'
services:
  app:
    image: app:latest
    devices:
      - /dev/sda:/dev/xvda
"""
        validator = ComposeValidator()
        result = validator.validate(compose_yaml)
        assert result['valid'] is True

    def test_validate_devices_not_list(self):
        """Test that non-list devices fails validation"""
        compose_yaml = """
version: '3.8'
services:
  app:
    image: app:latest
    devices: /dev/sda:/dev/xvda
"""
        validator = ComposeValidator()
        with pytest.raises(ComposeValidationError, match="must be a list"):
            validator.validate(compose_yaml)

    def test_validate_extra_hosts_list(self):
        """Test that extra_hosts as list passes validation"""
        compose_yaml = """
version: '3.8'
services:
  app:
    image: app:latest
    extra_hosts:
      - "db:192.168.1.100"
"""
        validator = ComposeValidator()
        result = validator.validate(compose_yaml)
        assert result['valid'] is True

    def test_validate_cap_add_list(self):
        """Test that cap_add as list passes validation"""
        compose_yaml = """
version: '3.8'
services:
  app:
    image: app:latest
    cap_add:
      - NET_ADMIN
"""
        validator = ComposeValidator()
        result = validator.validate(compose_yaml)
        assert result['valid'] is True

    def test_validate_cap_drop_not_list(self):
        """Test that non-list cap_drop is rejected"""
        compose_yaml = """
version: '3.8'
services:
  app:
    image: app:latest
    cap_drop: MKNOD
"""
        validator = ComposeValidator()
        with pytest.raises(ComposeValidationError, match="must be a list"):
            validator.validate(compose_yaml)
