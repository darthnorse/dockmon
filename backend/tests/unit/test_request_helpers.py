"""
Tests for reverse proxy request helper functions.

Covers get_request_scheme(), get_request_host(), and _get_cors_origin_parts()
fallback chains used in OIDC callback URL construction.
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.client_ip import get_request_scheme, get_request_host, _get_cors_origin_parts


def _make_request(headers: dict[str, str] | None = None, scheme: str = "http", netloc: str = "internal:8080") -> MagicMock:
    """Create a mock FastAPI Request with the given headers and URL parts."""
    request = MagicMock()
    request.headers = headers or {}
    request.url.scheme = scheme
    request.url.netloc = netloc
    return request


class TestGetCorsOriginParts:
    """Tests for _get_cors_origin_parts() helper."""

    def test_returns_scheme_and_host(self):
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.CORS_ORIGINS = "https://dockmon.lokal"
            result = _get_cors_origin_parts()
            assert result == ("https", "dockmon.lokal")

    def test_returns_first_origin_from_comma_separated(self):
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.CORS_ORIGINS = "https://dockmon.lokal, https://other.host"
            result = _get_cors_origin_parts()
            assert result == ("https", "dockmon.lokal")

    def test_returns_none_when_not_set(self):
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.CORS_ORIGINS = None
            assert _get_cors_origin_parts() is None

    def test_returns_none_for_empty_string(self):
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.CORS_ORIGINS = ""
            assert _get_cors_origin_parts() is None

    def test_returns_none_for_invalid_url(self):
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.CORS_ORIGINS = "not-a-url"
            assert _get_cors_origin_parts() is None

    def test_preserves_port_in_host(self):
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:8443"
            result = _get_cors_origin_parts()
            assert result == ("https", "dockmon.lokal:8443")


class TestGetRequestScheme:
    """Tests for get_request_scheme() fallback chain."""

    def test_uses_forwarded_proto_in_proxy_mode(self):
        request = _make_request(headers={"x-forwarded-proto": "https"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_scheme(request) == "https"

    def test_strips_and_lowercases_forwarded_proto(self):
        request = _make_request(headers={"x-forwarded-proto": " HTTPS "})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_scheme(request) == "https"

    def test_takes_first_value_from_multi_hop_proto(self):
        request = _make_request(headers={"x-forwarded-proto": "https, http"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_scheme(request) == "https"

    def test_uses_cors_origins_https_as_canonical_scheme(self):
        """Operator's explicit DOCKMON_CORS_ORIGINS=https://... is the
        canonical scheme even with no proxy headers present."""
        request = _make_request()
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal"
            assert get_request_scheme(request) == "https"

    def test_cors_origins_https_takes_precedence_over_forwarded_proto(self):
        """When CORS_ORIGINS declares https, trust it over X-Forwarded-Proto.
        Fixes #208 follow-up where Caddy sent X-Forwarded-Proto=http even
        when the inbound was https; trusting the operator's declaration
        avoids that failure mode."""
        request = _make_request(headers={"x-forwarded-proto": "http"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal"
            assert get_request_scheme(request) == "https"

    def test_cors_origins_http_does_not_downgrade_when_forwarded_proto_https(self):
        """If CORS_ORIGINS declares http but X-Forwarded-Proto says https,
        honor the upgrade. CORS=http is treated as the operator's lower
        bound, not an authoritative downgrade — a TLS-terminating proxy
        signaling https should never be silently overridden into http
        (cookies would lose Secure flag, OIDC redirect would fail)."""
        request = _make_request(headers={"x-forwarded-proto": "https"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "http://internal.example"
            assert get_request_scheme(request) == "https"

    def test_cors_origins_http_used_when_no_forwarded_proto(self):
        """If CORS_ORIGINS=http and no X-Forwarded-Proto, honor the
        operator's explicit http declaration."""
        request = _make_request()
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "http://internal.example"
            assert get_request_scheme(request) == "http"

    def test_forwarded_proto_used_when_cors_origins_missing_scheme(self):
        """If CORS_ORIGINS is set but doesn't parse to scheme+host (e.g., a
        bare hostname), fall through to X-Forwarded-Proto."""
        request = _make_request(headers={"x-forwarded-proto": "https"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "dockmon.lokal"
            assert get_request_scheme(request) == "https"

    def test_falls_back_to_request_scheme_when_nothing_available(self):
        request = _make_request(scheme="http")
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_scheme(request) == "http"

    def test_ignores_proxy_headers_when_not_in_proxy_mode(self):
        request = _make_request(headers={"x-forwarded-proto": "https"}, scheme="http")
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = False
            assert get_request_scheme(request) == "http"

    def test_ignores_cors_origins_when_not_in_proxy_mode(self):
        request = _make_request(scheme="http")
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = False
            mock_config.CORS_ORIGINS = "https://dockmon.lokal"
            assert get_request_scheme(request) == "http"


class TestGetRequestHost:
    """Tests for get_request_host() fallback chain."""

    def test_uses_forwarded_host_in_proxy_mode(self):
        request = _make_request(headers={"x-forwarded-host": "dockmon.lokal"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request) == "dockmon.lokal"

    def test_sanitizes_multi_hop_forwarded_host(self):
        request = _make_request(headers={"x-forwarded-host": "dockmon.lokal, internal.proxy"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request) == "dockmon.lokal"

    def test_strips_whitespace_from_forwarded_host(self):
        request = _make_request(headers={"x-forwarded-host": " dockmon.lokal "})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request) == "dockmon.lokal"

    def test_falls_back_to_cors_origins_when_no_header(self):
        request = _make_request()
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal"
            assert get_request_host(request) == "dockmon.lokal"

    def test_falls_back_to_host_header_when_nothing_available(self):
        request = _make_request(headers={"host": "internal:8080"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request) == "internal:8080"

    def test_falls_back_to_netloc_when_no_headers_at_all(self):
        request = _make_request(netloc="_")
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request) == "_"

    def test_uses_host_header_when_not_in_proxy_mode(self):
        request = _make_request(headers={"host": "localhost:8080"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = False
            assert get_request_host(request) == "localhost:8080"

    def test_ignores_forwarded_host_when_not_in_proxy_mode(self):
        request = _make_request(
            headers={"x-forwarded-host": "dockmon.lokal", "host": "internal:8080"}
        )
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = False
            assert get_request_host(request) == "internal:8080"

    def test_ignores_cors_origins_when_not_in_proxy_mode(self):
        request = _make_request(headers={"host": "internal:8080"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = False
            mock_config.CORS_ORIGINS = "https://dockmon.lokal"
            assert get_request_host(request) == "internal:8080"


class TestCaddyScenario:
    """End-to-end test for the reported Caddy issue (#208)."""

    def test_caddy_without_forwarded_headers_uses_cors_origins(self):
        """Caddy sends no X-Forwarded-Host or X-Forwarded-Proto by default.
        With CORS_ORIGINS set, the callback URL should use that instead of
        falling back to the internal container address."""
        request = _make_request(
            headers={"host": "_"},
            scheme="http",
            netloc="_",
        )
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal"

            scheme = get_request_scheme(request)
            host = get_request_host(request)
            redirect_uri = f"{scheme}://{host}/api/v2/auth/oidc/callback"

            assert redirect_uri == "https://dockmon.lokal/api/v2/auth/oidc/callback"
