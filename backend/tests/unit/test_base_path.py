import pytest
from backend.utils.base_path import sanitize_base_path, get_base_path


class TestSanitizeBasePath:
    """Test base path sanitization logic"""

    def test_sanitize_base_path_valid_with_slashes(self):
        """Valid path with leading and trailing slashes should pass through"""
        assert sanitize_base_path("/dockmon/") == "/dockmon/"
        assert sanitize_base_path("/") == "/"
        assert sanitize_base_path("/services/monitoring/") == "/services/monitoring/"

    def test_sanitize_base_path_missing_leading_slash(self):
        """Path missing leading slash should have it added"""
        assert sanitize_base_path("dockmon/") == "/dockmon/"
        assert sanitize_base_path("services/") == "/services/"

    def test_sanitize_base_path_missing_trailing_slash(self):
        """Path missing trailing slash should have it added"""
        assert sanitize_base_path("/dockmon") == "/dockmon/"
        assert sanitize_base_path("/services") == "/services/"

    def test_sanitize_base_path_missing_both_slashes(self):
        """Path missing both slashes should have both added"""
        assert sanitize_base_path("dockmon") == "/dockmon/"
        assert sanitize_base_path("services") == "/services/"

    def test_sanitize_base_path_empty_string_returns_root(self):
        """Empty string should return root path"""
        assert sanitize_base_path("") == "/"

    def test_sanitize_base_path_whitespace_returns_root(self):
        """Whitespace-only string should return root path"""
        assert sanitize_base_path("   ") == "/"
        assert sanitize_base_path("\t\n") == "/"

    def test_sanitize_base_path_none_returns_root(self):
        """None should return root path"""
        assert sanitize_base_path(None) == "/"

    def test_sanitize_base_path_double_slashes(self):
        """Multiple consecutive slashes should be normalized"""
        assert sanitize_base_path("//dockmon//") == "/dockmon/"
        assert sanitize_base_path("/services//monitoring/") == "/services/monitoring/"

    def test_sanitize_base_path_complex_paths(self):
        """Complex nested paths should be sanitized correctly"""
        assert sanitize_base_path("/apps/monitoring/dockmon/") == "/apps/monitoring/dockmon/"
        assert sanitize_base_path("apps/monitoring/dockmon") == "/apps/monitoring/dockmon/"


class TestGetBasePath:
    """Test getting base path from environment"""

    def test_get_base_path_from_env(self, monkeypatch):
        """Should read BASE_PATH from environment"""
        monkeypatch.setenv("BASE_PATH", "/dockmon/")
        assert get_base_path() == "/dockmon/"

    def test_get_base_path_sanitizes_env_value(self, monkeypatch):
        """Should sanitize environment value"""
        monkeypatch.setenv("BASE_PATH", "dockmon")
        assert get_base_path() == "/dockmon/"

    def test_get_base_path_defaults_to_root(self, monkeypatch):
        """Should default to root when not set"""
        monkeypatch.delenv("BASE_PATH", raising=False)
        assert get_base_path() == "/"

    def test_get_base_path_empty_env_returns_root(self, monkeypatch):
        """Empty environment variable should return root"""
        monkeypatch.setenv("BASE_PATH", "")
        assert get_base_path() == "/"
