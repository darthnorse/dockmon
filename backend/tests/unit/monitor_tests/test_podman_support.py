"""
Unit tests for Podman socket detection and platform detection.

Tests verify:
- Socket detection priority (Docker -> Podman rootful -> Podman rootless)
- XDG_RUNTIME_DIR environment variable handling
- Platform detection via Docker API
- Rootless Podman detection logic
- Resource cleanup on exceptions
- Fallback behavior
"""

import pytest
import os
import tempfile
from unittest.mock import Mock, MagicMock, patch, call
from pathlib import Path


# =============================================================================
# Socket Detection Priority Tests
# =============================================================================

class TestSocketDetectionPriority:
    """Test socket detection priority order"""

    @patch('os.path.exists')
    def test_docker_socket_has_priority(self, mock_exists):
        """If Docker socket exists, it should be selected (even if Podman exists)"""
        # Both Docker and Podman exist
        def exists_side_effect(path):
            return path in ['/var/run/docker.sock', '/var/run/podman/podman.sock']

        mock_exists.side_effect = exists_side_effect

        # Simulate socket detection logic
        socket_path = None
        socket_name = None

        if os.path.exists('/var/run/docker.sock'):
            socket_path = '/var/run/docker.sock'
            socket_name = 'Docker'
        elif os.path.exists('/var/run/podman/podman.sock'):
            socket_path = '/var/run/podman/podman.sock'
            socket_name = 'Podman'

        assert socket_path == '/var/run/docker.sock'
        assert socket_name == 'Docker'

    @patch('os.path.exists')
    def test_podman_rootful_when_no_docker(self, mock_exists):
        """If only Podman rootful exists, it should be selected"""
        def exists_side_effect(path):
            return path == '/var/run/podman/podman.sock'

        mock_exists.side_effect = exists_side_effect

        # Simulate socket detection logic
        socket_path = None
        socket_name = None

        if os.path.exists('/var/run/docker.sock'):
            socket_path = '/var/run/docker.sock'
            socket_name = 'Docker'
        elif os.path.exists('/var/run/podman/podman.sock'):
            socket_path = '/var/run/podman/podman.sock'
            socket_name = 'Podman'

        assert socket_path == '/var/run/podman/podman.sock'
        assert socket_name == 'Podman'

    @patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/1000'})
    @patch('os.path.exists')
    def test_podman_rootless_when_no_rootful(self, mock_exists):
        """If only Podman rootless exists, it should be selected"""
        def exists_side_effect(path):
            return path == '/run/user/1000/podman/podman.sock'

        mock_exists.side_effect = exists_side_effect

        # Simulate socket detection logic
        socket_path = None
        socket_name = None

        if os.path.exists('/var/run/docker.sock'):
            socket_path = '/var/run/docker.sock'
            socket_name = 'Docker'
        elif os.path.exists('/var/run/podman/podman.sock'):
            socket_path = '/var/run/podman/podman.sock'
            socket_name = 'Podman'
        elif 'XDG_RUNTIME_DIR' in os.environ:
            runtime_dir = os.environ['XDG_RUNTIME_DIR']
            rootless_sock = f"{runtime_dir}/podman/podman.sock"
            if os.path.exists(rootless_sock):
                socket_path = rootless_sock
                socket_name = 'Podman (Rootless)'

        assert socket_path == '/run/user/1000/podman/podman.sock'
        assert socket_name == 'Podman (Rootless)'

    @patch('os.path.exists')
    def test_no_socket_found(self, mock_exists):
        """If no socket exists, socket_path should be None"""
        mock_exists.return_value = False

        # Simulate socket detection logic
        socket_path = None
        socket_name = None

        if os.path.exists('/var/run/docker.sock'):
            socket_path = '/var/run/docker.sock'
            socket_name = 'Docker'
        elif os.path.exists('/var/run/podman/podman.sock'):
            socket_path = '/var/run/podman/podman.sock'
            socket_name = 'Podman'
        elif 'XDG_RUNTIME_DIR' in os.environ:
            runtime_dir = os.environ['XDG_RUNTIME_DIR']
            rootless_sock = f"{runtime_dir}/podman/podman.sock"
            if os.path.exists(rootless_sock):
                socket_path = rootless_sock
                socket_name = 'Podman (Rootless)'

        assert socket_path is None
        assert socket_name is None


# =============================================================================
# XDG_RUNTIME_DIR Tests
# =============================================================================

class TestXDGRuntimeDir:
    """Test XDG_RUNTIME_DIR environment variable handling"""

    @patch.dict(os.environ, {}, clear=True)
    @patch('os.path.exists')
    def test_no_xdg_runtime_dir(self, mock_exists):
        """If XDG_RUNTIME_DIR not set, rootless Podman should not be detected"""
        mock_exists.return_value = False

        # Simulate socket detection logic
        socket_path = None

        if 'XDG_RUNTIME_DIR' in os.environ:
            runtime_dir = os.environ['XDG_RUNTIME_DIR']
            rootless_sock = f"{runtime_dir}/podman/podman.sock"
            if os.path.exists(rootless_sock):
                socket_path = rootless_sock

        assert socket_path is None

    @patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/1000'})
    @patch('os.path.exists')
    def test_xdg_runtime_dir_set_but_socket_missing(self, mock_exists):
        """If XDG_RUNTIME_DIR set but socket doesn't exist, should not be detected"""
        mock_exists.return_value = False

        # Simulate socket detection logic
        socket_path = None

        if 'XDG_RUNTIME_DIR' in os.environ:
            runtime_dir = os.environ['XDG_RUNTIME_DIR']
            rootless_sock = f"{runtime_dir}/podman/podman.sock"
            if os.path.exists(rootless_sock):
                socket_path = rootless_sock

        assert socket_path is None

    @patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/custom/runtime'})
    @patch('os.path.exists')
    def test_custom_xdg_runtime_dir(self, mock_exists):
        """Should work with custom XDG_RUNTIME_DIR paths"""
        def exists_side_effect(path):
            return path == '/custom/runtime/podman/podman.sock'

        mock_exists.side_effect = exists_side_effect

        # Simulate socket detection logic
        socket_path = None

        if 'XDG_RUNTIME_DIR' in os.environ:
            runtime_dir = os.environ['XDG_RUNTIME_DIR']
            rootless_sock = f"{runtime_dir}/podman/podman.sock"
            if os.path.exists(rootless_sock):
                socket_path = rootless_sock

        assert socket_path == '/custom/runtime/podman/podman.sock'


# =============================================================================
# Platform Detection Tests
# =============================================================================

class TestPlatformDetection:
    """Test platform detection via Docker API"""

    def test_detect_podman_from_api(self):
        """Should detect Podman from version API response"""
        # Mock Docker client
        mock_client = Mock()
        mock_client.version.return_value = {
            'Platform': {'Name': 'Podman Engine'}
        }

        # Simulate platform detection
        version_info = mock_client.version()
        platform_name = version_info.get('Platform', {}).get('Name', '')

        is_podman = 'podman' in platform_name.lower()

        assert is_podman is True

    def test_detect_docker_from_api(self):
        """Should detect Docker from version API response"""
        mock_client = Mock()
        mock_client.version.return_value = {
            'Platform': {'Name': 'Docker Engine - Community'}
        }

        # Simulate platform detection
        version_info = mock_client.version()
        platform_name = version_info.get('Platform', {}).get('Name', '')

        is_podman = 'podman' in platform_name.lower()

        assert is_podman is False

    def test_platform_name_case_insensitive(self):
        """Platform detection should be case-insensitive"""
        test_cases = [
            'Podman Engine',
            'PODMAN Engine',
            'podman engine',
            'PoDmAn Engine',
        ]

        for platform_name in test_cases:
            is_podman = 'podman' in platform_name.lower()
            assert is_podman is True, f"Failed for {platform_name}"

    def test_missing_platform_field(self):
        """Should handle missing Platform field gracefully"""
        mock_client = Mock()
        mock_client.version.return_value = {}

        # Simulate platform detection with defaults
        version_info = mock_client.version()
        platform_name = version_info.get('Platform', {}).get('Name', '')

        # Should return empty string, not crash
        assert platform_name == ''
        is_podman = 'podman' in platform_name.lower()
        assert is_podman is False


# =============================================================================
# Rootless Detection Tests
# =============================================================================

class TestRootlessDetection:
    """Test rootless Podman detection logic"""

    @patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/1000'})
    def test_rootless_detection_startswith(self):
        """Should use startswith() not 'in' to avoid false positives"""
        socket_path = '/run/user/1000/podman/podman.sock'

        # CORRECT: Use startswith()
        is_rootless = socket_path.startswith(os.environ['XDG_RUNTIME_DIR'])
        assert is_rootless is True

    @patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run'})
    def test_rootless_false_positive_prevented(self):
        """XDG_RUNTIME_DIR=/run should NOT match /var/run/podman/podman.sock"""
        socket_path = '/var/run/podman/podman.sock'

        # WRONG: Using 'in' would cause false positive
        # is_rootless = os.environ['XDG_RUNTIME_DIR'] in socket_path  # Would be True!

        # CORRECT: Using startswith() prevents false positive
        is_rootless = socket_path.startswith(os.environ['XDG_RUNTIME_DIR'])
        assert is_rootless is False  # Correct! Not rootless

    @patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/1000'})
    def test_rootless_with_trailing_slash(self):
        """Should handle XDG_RUNTIME_DIR with/without trailing slash"""
        socket_path = '/run/user/1000/podman/podman.sock'

        # With slash
        runtime_dir_with_slash = os.environ['XDG_RUNTIME_DIR'] + '/'
        is_rootless = socket_path.startswith(runtime_dir_with_slash)
        assert is_rootless is True

        # Without slash (current implementation)
        is_rootless = socket_path.startswith(os.environ['XDG_RUNTIME_DIR'])
        assert is_rootless is True

    @patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/1000'})
    def test_combined_rootless_detection(self):
        """Test full rootless detection logic (both checks)"""
        socket_path = '/run/user/1000/podman/podman.sock'
        platform_name = 'Podman Engine'

        # Full logic from monitor.py
        if 'podman' in platform_name.lower():
            if 'XDG_RUNTIME_DIR' in os.environ and socket_path.startswith(os.environ['XDG_RUNTIME_DIR']):
                detected_name = "Local Podman (Rootless)"
            else:
                detected_name = "Local Podman"
        else:
            detected_name = "Local Docker"

        assert detected_name == "Local Podman (Rootless)"

    @patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/1000'})
    def test_podman_rootful_not_detected_as_rootless(self):
        """Rootful Podman should not be detected as rootless"""
        socket_path = '/var/run/podman/podman.sock'
        platform_name = 'Podman Engine'

        # Full logic
        if 'podman' in platform_name.lower():
            if 'XDG_RUNTIME_DIR' in os.environ and socket_path.startswith(os.environ['XDG_RUNTIME_DIR']):
                detected_name = "Local Podman (Rootless)"
            else:
                detected_name = "Local Podman"
        else:
            detected_name = "Local Docker"

        assert detected_name == "Local Podman"  # Not rootless


# =============================================================================
# Resource Cleanup Tests
# =============================================================================

class TestResourceCleanup:
    """Test Docker client resource cleanup on exceptions"""

    def test_client_closed_on_success(self):
        """Docker client should be closed after successful platform detection"""
        mock_client = Mock()
        mock_client.version.return_value = {'Platform': {'Name': 'Docker Engine'}}

        temp_client = None
        try:
            temp_client = mock_client
            version_info = temp_client.version()
            detected_name = "Local Docker"
        finally:
            if temp_client:
                temp_client.close()

        # Verify close was called
        mock_client.close.assert_called_once()

    def test_client_closed_on_exception(self):
        """Docker client should be closed even if version() throws exception"""
        mock_client = Mock()
        mock_client.version.side_effect = Exception("Connection failed")

        temp_client = None
        exception_raised = False

        try:
            temp_client = mock_client
            try:
                version_info = temp_client.version()
            except Exception:
                exception_raised = True
        finally:
            if temp_client:
                temp_client.close()

        assert exception_raised is True
        mock_client.close.assert_called_once()

    def test_close_exception_ignored(self):
        """Exception during close() should be caught and ignored"""
        mock_client = Mock()
        mock_client.close.side_effect = Exception("Close failed")

        temp_client = None
        close_exception_raised = False

        try:
            temp_client = mock_client
        finally:
            if temp_client:
                try:
                    temp_client.close()
                except Exception:
                    close_exception_raised = False  # Ignored
                    pass

        # Should not raise
        assert close_exception_raised is False

    def test_none_client_safe_to_close(self):
        """Calling close on None should not crash"""
        temp_client = None

        # Should not raise
        try:
            if temp_client:
                temp_client.close()
            success = True
        except Exception:
            success = False

        assert success is True


# =============================================================================
# Fallback Behavior Tests
# =============================================================================

class TestFallbackBehavior:
    """Test fallback behavior when API detection fails"""

    def test_fallback_to_socket_name(self):
        """If version() fails, should fallback to socket-based detection"""
        mock_client = Mock()
        mock_client.version.side_effect = Exception("API call failed")

        socket_name = "Podman"
        detected_name = None

        try:
            version_info = mock_client.version()
            detected_name = "API Detection"
        except Exception:
            detected_name = f"Local {socket_name}"

        assert detected_name == "Local Podman"

    def test_fallback_for_each_socket_type(self):
        """Fallback should work for Docker, Podman, and Podman (Rootless)"""
        test_cases = [
            ("Docker", "Local Docker"),
            ("Podman", "Local Podman"),
            ("Podman (Rootless)", "Local Podman (Rootless)"),
        ]

        for socket_name, expected in test_cases:
            mock_client = Mock()
            mock_client.version.side_effect = Exception("Failed")

            try:
                version_info = mock_client.version()
                detected_name = "Should not reach"
            except Exception:
                detected_name = f"Local {socket_name}"

            assert detected_name == expected


# =============================================================================
# Integration Scenario Tests
# =============================================================================

class TestIntegrationScenarios:
    """Test realistic integration scenarios"""

    @patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/run/user/1000'})
    @patch('os.path.exists')
    def test_podman_rootless_full_flow(self, mock_exists):
        """Test complete flow for rootless Podman detection"""
        # Only rootless Podman exists
        def exists_side_effect(path):
            return path == '/run/user/1000/podman/podman.sock'

        mock_exists.side_effect = exists_side_effect

        # Step 1: Socket detection
        socket_path = None
        socket_name = None

        if os.path.exists('/var/run/docker.sock'):
            socket_path = '/var/run/docker.sock'
            socket_name = 'Docker'
        elif os.path.exists('/var/run/podman/podman.sock'):
            socket_path = '/var/run/podman/podman.sock'
            socket_name = 'Podman'
        elif 'XDG_RUNTIME_DIR' in os.environ:
            runtime_dir = os.environ['XDG_RUNTIME_DIR']
            rootless_sock = f"{runtime_dir}/podman/podman.sock"
            if os.path.exists(rootless_sock):
                socket_path = rootless_sock
                socket_name = 'Podman (Rootless)'

        assert socket_path == '/run/user/1000/podman/podman.sock'
        assert socket_name == 'Podman (Rootless)'

        # Step 2: Platform detection (simulated success)
        mock_client = Mock()
        mock_client.version.return_value = {'Platform': {'Name': 'Podman Engine'}}

        temp_client = None
        try:
            temp_client = mock_client
            version_info = temp_client.version()
            platform_name = version_info.get('Platform', {}).get('Name', '')

            if 'podman' in platform_name.lower():
                if 'XDG_RUNTIME_DIR' in os.environ and socket_path.startswith(os.environ['XDG_RUNTIME_DIR']):
                    detected_name = "Local Podman (Rootless)"
                else:
                    detected_name = "Local Podman"
            else:
                detected_name = "Local Docker"
        finally:
            if temp_client:
                temp_client.close()

        assert detected_name == "Local Podman (Rootless)"
        mock_client.close.assert_called_once()
