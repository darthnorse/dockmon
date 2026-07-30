"""
Tests for OIDC redirect URI construction.

Providers match redirect URIs as exact strings, so the URI DockMon sends must
reproduce the origin the browser used - including a non-standard port that a
reverse proxy dropped when it rewrote the Host header.

Regression coverage for issue #242.
"""

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from auth.oidc_config_routes import OIDCConfigUpdateRequest
from config.settings import AppConfig
from utils.oidc import build_callback_url, build_post_logout_url

CALLBACK = "/api/v2/auth/oidc/callback"


def _make_request(headers: dict[str, str] | None = None, scheme: str = "http") -> Request:
    """Build a minimal ASGI Request without standing up the whole app."""
    raw_headers = [(k.encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/api/v2/auth/oidc/authorize",
        "raw_path": b"/api/v2/auth/oidc/authorize",
        "query_string": b"",
        "headers": raw_headers,
        "client": ("203.0.113.5", 12345),
        "server": ("dockmon.example.com", 443 if scheme == "https" else 80),
    })


class TestBuildCallbackUrl:
    """Detection path and operator override."""

    def test_detects_from_forwarded_headers(self, monkeypatch):
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", True, raising=False)
        monkeypatch.setattr(AppConfig, "CORS_ORIGINS", None, raising=False)
        request = _make_request({
            "host": "internal:8080",
            "x-forwarded-host": "dockmon.example.com",
            "x-forwarded-proto": "https",
        })
        assert build_callback_url(request) == f"https://dockmon.example.com{CALLBACK}"

    def test_detects_non_standard_port_from_forwarded_port(self, monkeypatch):
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", True, raising=False)
        monkeypatch.setattr(AppConfig, "CORS_ORIGINS", None, raising=False)
        request = _make_request({
            "host": "dockmon.example.com",
            "x-forwarded-host": "dockmon.example.com",
            "x-forwarded-proto": "https",
            "x-forwarded-port": "8314",
        })
        assert build_callback_url(request) == f"https://dockmon.example.com:8314{CALLBACK}"

    def test_detects_non_standard_port_from_cors_origins(self, monkeypatch):
        """The proxy stripped the port from Host; the operator declared it."""
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", True, raising=False)
        monkeypatch.setattr(
            AppConfig, "CORS_ORIGINS", "https://dockmon.example.com:8314", raising=False
        )
        request = _make_request({
            "host": "dockmon.example.com",
            "x-forwarded-host": "dockmon.example.com",
            "x-forwarded-proto": "https",
        })
        assert build_callback_url(request) == f"https://dockmon.example.com:8314{CALLBACK}"

    def test_override_wins_over_detection(self, monkeypatch):
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", True, raising=False)
        monkeypatch.setattr(AppConfig, "CORS_ORIGINS", None, raising=False)
        request = _make_request({
            "host": "internal:8080",
            "x-forwarded-host": "wrong.example.com",
        })
        override = "https://dockmon.example.com:8314/api/v2/auth/oidc/callback"
        assert build_callback_url(request, override) == override

    def test_includes_base_path(self, monkeypatch):
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", False, raising=False)
        monkeypatch.setenv("BASE_PATH", "/dockmon")
        request = _make_request({"host": "dockmon.example.com"}, scheme="https")
        assert build_callback_url(request) == f"https://dockmon.example.com/dockmon{CALLBACK}"


class TestBuildPostLogoutUrl:
    """The post-logout URI must describe the same origin as the callback."""

    def test_derives_origin_from_override(self, monkeypatch):
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", True, raising=False)
        monkeypatch.setattr(AppConfig, "CORS_ORIGINS", None, raising=False)
        request = _make_request({"host": "internal:8080"})
        override = "https://dockmon.example.com:8314/api/v2/auth/oidc/callback"
        assert build_post_logout_url(request, override) == "https://dockmon.example.com:8314/login"

    def test_derived_origin_keeps_base_path(self, monkeypatch):
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", False, raising=False)
        monkeypatch.setenv("BASE_PATH", "/dockmon")
        request = _make_request({"host": "internal:8080"})
        override = "https://dockmon.example.com:8314/dockmon/api/v2/auth/oidc/callback"
        assert (
            build_post_logout_url(request, override)
            == "https://dockmon.example.com:8314/dockmon/login"
        )

    def test_uses_the_overrides_own_prefix_not_base_path(self, monkeypatch):
        """A proxy's public prefix can differ from the local BASE_PATH; the
        override states the public one, so reuse it rather than re-deriving."""
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", False, raising=False)
        monkeypatch.delenv("BASE_PATH", raising=False)
        request = _make_request({"host": "internal:8080"})
        override = "https://dockmon.example.com:8314/dockmon/api/v2/auth/oidc/callback"
        assert (
            build_post_logout_url(request, override)
            == "https://dockmon.example.com:8314/dockmon/login"
        )

    def test_falls_back_to_detection_without_override(self, monkeypatch):
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", False, raising=False)
        request = _make_request({"host": "dockmon.example.com"}, scheme="https")
        assert build_post_logout_url(request) == "https://dockmon.example.com/login"

    def test_unparsable_override_falls_back_to_detection(self, monkeypatch):
        monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", False, raising=False)
        request = _make_request({"host": "dockmon.example.com"}, scheme="https")
        assert (
            build_post_logout_url(request, "not-a-url")
            == "https://dockmon.example.com/login"
        )


class TestRedirectUriOverrideValidation:
    """The override is sent verbatim to the provider, so validate its shape."""

    def test_accepts_absolute_https_url(self):
        body = OIDCConfigUpdateRequest(
            redirect_uri_override="https://dockmon.example.com:8314/api/v2/auth/oidc/callback"
        )
        assert body.redirect_uri_override == (
            "https://dockmon.example.com:8314/api/v2/auth/oidc/callback"
        )

    def test_accepts_http_for_plain_deployments(self):
        body = OIDCConfigUpdateRequest(
            redirect_uri_override="http://dockmon.lan:8314/api/v2/auth/oidc/callback"
        )
        assert body.redirect_uri_override.startswith("http://")

    def test_strips_trailing_slash(self):
        body = OIDCConfigUpdateRequest(
            redirect_uri_override="https://dockmon.example.com/api/v2/auth/oidc/callback/"
        )
        assert body.redirect_uri_override.endswith("/callback")

    def test_accepts_a_base_path_prefix(self):
        body = OIDCConfigUpdateRequest(
            redirect_uri_override="https://dockmon.example.com/dockmon/api/v2/auth/oidc/callback"
        )
        assert body.redirect_uri_override.endswith(CALLBACK)

    @pytest.mark.parametrize("bad", [
        "https://dockmon.example.com:8314",              # bare origin
        "https://dockmon.example.com/",                  # origin with a slash
        "https://dockmon.example.com/wrong/path",
        "https://dockmon.example.com/api/v2/auth/oidc",   # truncated
    ])
    def test_rejects_urls_that_cannot_reach_the_callback(self, bad):
        """Sent verbatim as redirect_uri: a wrong path makes the provider hand the
        code to a page that never exchanges it, failing login with no diagnostic."""
        with pytest.raises(ValidationError):
            OIDCConfigUpdateRequest(redirect_uri_override=bad)

    @pytest.mark.parametrize("bad", [
        "https://dockmon.example.com@evil.tld/api/v2/auth/oidc/callback",
        "https://user:pass@dockmon.example.com/api/v2/auth/oidc/callback",
    ])
    def test_rejects_embedded_credentials(self, bad):
        """Userinfo makes the authority read as one host and resolve to another."""
        with pytest.raises(ValidationError):
            OIDCConfigUpdateRequest(redirect_uri_override=bad)

    def test_rejects_a_non_numeric_port(self):
        """urlparse().hostname alone accepts this; the URL is still unusable."""
        with pytest.raises(ValidationError):
            OIDCConfigUpdateRequest(
                redirect_uri_override="https://dockmon.example.com:abc/api/v2/auth/oidc/callback"
            )

    def test_rejects_path_parameters(self):
        """urlparse splits ';foo' off the path, so the suffix check passes while
        the stored value still carries it into the provider comparison."""
        with pytest.raises(ValidationError):
            OIDCConfigUpdateRequest(
                redirect_uri_override="https://dockmon.example.com/api/v2/auth/oidc/callback;foo"
            )

    def test_empty_string_clears_the_override(self):
        assert OIDCConfigUpdateRequest(redirect_uri_override="   ").redirect_uri_override == ""

    def test_omitted_field_stays_none(self):
        assert OIDCConfigUpdateRequest().redirect_uri_override is None

    @pytest.mark.parametrize("bad", [
        "dockmon.example.com/api/v2/auth/oidc/callback",   # no scheme
        "/api/v2/auth/oidc/callback",                      # relative
        "ftp://dockmon.example.com/callback",              # wrong scheme
        "https:///callback",                               # no host
        "javascript:alert(1)",
    ])
    def test_rejects_non_absolute_http_urls(self, bad):
        with pytest.raises(ValidationError):
            OIDCConfigUpdateRequest(redirect_uri_override=bad)

    @pytest.mark.parametrize("bad", [
        "https://dockmon.example.com/callback?next=/admin",
        "https://dockmon.example.com/callback#frag",
    ])
    def test_rejects_query_and_fragment(self, bad):
        with pytest.raises(ValidationError):
            OIDCConfigUpdateRequest(redirect_uri_override=bad)
