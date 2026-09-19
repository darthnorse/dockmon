"""
Tests for reverse proxy request helper functions.

Covers get_request_scheme(), get_request_host(), and _get_cors_origin_parts()
fallback chains used in OIDC callback URL construction.
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from utils.client_ip import (
    get_request_scheme,
    get_request_host,
    _get_cors_origin_parts,
    _split_host_port,
    get_client_ip,
)


def _make_request(headers: dict[str, str] | None = None, scheme: str = "http", netloc: str = "internal:8080", peer: str = "127.0.0.1") -> MagicMock:
    """Create a mock FastAPI Request with the given headers and URL parts."""
    request = MagicMock()
    request.headers = headers or {}
    request.url.scheme = scheme
    request.url.netloc = netloc
    request.client.host = peer
    return request


class TestGetClientIp:
    """Client IP derivation across default and reverse-proxy deployments."""

    def test_default_mode_trusts_x_real_ip_from_bundled_nginx(self):
        # Bundled nginx sets X-Real-IP=$remote_addr (overwriting client value),
        # so the real client is recoverable even though the socket peer is nginx.
        req = _make_request(headers={"x-real-ip": "203.0.113.5"}, peer="127.0.0.1")
        with patch("utils.client_ip.AppConfig") as cfg:
            cfg.REVERSE_PROXY_MODE = False
            assert get_client_ip(req) == "203.0.113.5"

    def test_default_mode_falls_back_to_socket_peer(self):
        req = _make_request(headers={}, peer="192.168.1.9")
        with patch("utils.client_ip.AppConfig") as cfg:
            cfg.REVERSE_PROXY_MODE = False
            assert get_client_ip(req) == "192.168.1.9"

    def test_reverse_proxy_takes_client_left_of_trusted_hop(self):
        req = _make_request(headers={"x-forwarded-for": "203.0.113.5, 10.0.0.2"})
        with patch("utils.client_ip.AppConfig") as cfg:
            cfg.REVERSE_PROXY_MODE = True
            cfg.TRUSTED_PROXY_COUNT = 1
            assert get_client_ip(req) == "203.0.113.5"

    def test_reverse_proxy_ignores_spoofed_leftmost_entry(self):
        # Attacker prepends a fake hop; with 1 trusted hop the real client is the
        # second-from-right, never the attacker-controlled left-most value.
        req = _make_request(headers={"x-forwarded-for": "9.9.9.9, 203.0.113.5, 10.0.0.2"})
        with patch("utils.client_ip.AppConfig") as cfg:
            cfg.REVERSE_PROXY_MODE = True
            cfg.TRUSTED_PROXY_COUNT = 1
            assert get_client_ip(req) == "203.0.113.5"


class TestGetRequestSchemeDefaultMode:
    """Default (bundled-nginx) deployment must honor X-Forwarded-Proto for the Secure cookie."""

    def test_default_mode_trusts_forwarded_proto(self):
        req = _make_request(headers={"x-forwarded-proto": "https"}, scheme="http")
        with patch("utils.client_ip.AppConfig") as cfg:
            cfg.REVERSE_PROXY_MODE = False
            assert get_request_scheme(req) == "https"

    def test_default_mode_falls_back_to_url_scheme(self):
        req = _make_request(headers={}, scheme="http")
        with patch("utils.client_ip.AppConfig") as cfg:
            cfg.REVERSE_PROXY_MODE = False
            assert get_request_scheme(req) == "http"


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


class TestSplitHostPort:
    """netloc splitting must survive IPv6 literals."""

    def test_hostname_without_port(self):
        assert _split_host_port("dockmon.lokal") == ("dockmon.lokal", None)

    def test_hostname_with_port(self):
        assert _split_host_port("dockmon.lokal:8314") == ("dockmon.lokal", "8314")

    def test_ipv6_literal_without_port(self):
        assert _split_host_port("[2001:db8::1]") == ("[2001:db8::1]", None)

    def test_ipv6_literal_with_port(self):
        assert _split_host_port("[2001:db8::1]:8314") == ("[2001:db8::1]", "8314")

    def test_bare_ipv6_is_not_split_on_its_colons(self):
        assert _split_host_port("2001:db8::1") == ("2001:db8::1", None)

    def test_trailing_colon_has_no_port(self):
        assert _split_host_port("dockmon.lokal:") == ("dockmon.lokal", None)

    def test_unterminated_bracket_is_returned_whole(self):
        assert _split_host_port("[2001:db8::1") == ("[2001:db8::1", None)


class TestForwardedPortRecovery:
    """A proxy forwarding `Host: $host` drops the port; recover it so OIDC
    redirect URIs keep the non-standard port the browser actually used."""

    def test_recovers_port_from_forwarded_port_header(self):
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal",
            "x-forwarded-port": "8314",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "dockmon.lokal:8314"

    def test_ignores_forwarded_port_443_for_https(self):
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal",
            "x-forwarded-port": "443",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "dockmon.lokal"

    def test_ignores_forwarded_port_80_for_http(self):
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal",
            "x-forwarded-port": "80",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "http") == "dockmon.lokal"

    def test_ignores_cross_scheme_default_port(self):
        """:80 on https is far more likely the proxy's backend hop than a real
        public port, and writing it in would break the provider's exact match."""
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal",
            "x-forwarded-port": "80",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "dockmon.lokal"

    def test_ignores_cross_scheme_default_port_443_on_http(self):
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal",
            "x-forwarded-port": "443",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "http") == "dockmon.lokal"

    def test_strips_implicit_port_already_in_forwarded_host(self):
        """An explicit :443 on https must not reach the redirect URI either."""
        request = _make_request(headers={"x-forwarded-host": "dockmon.lokal:443"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "dockmon.lokal"

    def test_keeps_a_stated_cross_scheme_port_in_forwarded_host(self):
        """A port stated outright is a declaration, however unusual — unlike
        X-Forwarded-Port, which is the proxy's guess and may name its own hop."""
        request = _make_request(headers={"x-forwarded-host": "dockmon.lokal:80"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "dockmon.lokal:80"

    def test_leaves_unbracketed_ipv6_literal_alone(self):
        """Appending a port to a bare IPv6 literal would yield an unparsable URL."""
        request = _make_request(headers={
            "x-forwarded-host": "2001:db8::1",
            "x-forwarded-port": "8314",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "2001:db8::1"

    def test_explicit_port_in_forwarded_host_wins(self):
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal:9000",
            "x-forwarded-port": "8314",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "dockmon.lokal:9000"

    def test_takes_first_value_from_multi_hop_forwarded_port(self):
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal",
            "x-forwarded-port": "8314, 443",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "dockmon.lokal:8314"

    def test_ignores_non_numeric_forwarded_port(self):
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal",
            "x-forwarded-port": "not-a-port",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "dockmon.lokal"

    def test_ignores_out_of_range_forwarded_port(self):
        for bad_port in ("0", "70000", "-1"):
            request = _make_request(headers={
                "x-forwarded-host": "dockmon.lokal",
                "x-forwarded-port": bad_port,
            })
            with patch("utils.client_ip.AppConfig") as mock_config:
                mock_config.REVERSE_PROXY_MODE = True
                mock_config.CORS_ORIGINS = None
                assert get_request_host(request, "https") == "dockmon.lokal", bad_port

    def test_recovers_port_on_host_header_fallback(self):
        """No X-Forwarded-Host and no CORS_ORIGINS: the Host header is the last
        resort, and the port is still recoverable from X-Forwarded-Port."""
        request = _make_request(headers={
            "host": "dockmon.lokal",
            "x-forwarded-port": "8314",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "dockmon.lokal:8314"

    def test_recovers_port_for_ipv6_literal_host(self):
        request = _make_request(headers={
            "x-forwarded-host": "[2001:db8::1]",
            "x-forwarded-port": "8314",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "[2001:db8::1]:8314"

    def test_ignores_forwarded_port_in_default_mode(self):
        """Outside REVERSE_PROXY_MODE nothing overwrites X-Forwarded-Port, so a
        client could set it freely; the bundled nginx forwards the real port in
        the Host header instead."""
        request = _make_request(headers={
            "host": "dockmon.lokal",
            "x-forwarded-port": "8314",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = False
            assert get_request_host(request, "https") == "dockmon.lokal"

    def test_derives_scheme_when_not_supplied(self):
        """Callers may omit the scheme; it is then derived to decide which port
        counts as the default."""
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal",
            "x-forwarded-proto": "https",
            "x-forwarded-port": "443",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request) == "dockmon.lokal"


class TestCorsOriginsPortRecovery:
    """DOCKMON_CORS_ORIGINS is the operator's declaration of the public origin,
    so its port is authoritative for the hostname it names."""

    def test_recovers_port_from_cors_origins(self):
        request = _make_request(headers={"x-forwarded-host": "dockmon.lokal"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:8314"
            assert get_request_host(request, "https") == "dockmon.lokal:8314"

    def test_host_match_is_case_insensitive(self):
        request = _make_request(headers={"x-forwarded-host": "DockMon.Lokal"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:8314"
            assert get_request_host(request, "https") == "DockMon.Lokal:8314"

    def test_does_not_graft_port_onto_a_different_host(self):
        """A multi-domain deployment declares each origin separately; one
        origin's port must not be grafted onto a sibling that has none."""
        request = _make_request(headers={"x-forwarded-host": "other.lokal"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:8314,https://other.lokal"
            assert get_request_host(request, "https") == "other.lokal"

    def test_does_not_graft_port_when_scheme_differs(self):
        """A port declared for http says nothing about the https listener."""
        request = _make_request(headers={"x-forwarded-host": "dockmon.lokal"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "http://dockmon.lokal:8314"
            assert get_request_host(request, "https") == "dockmon.lokal"

    def test_ignores_cors_default_port(self):
        request = _make_request(headers={"x-forwarded-host": "dockmon.lokal"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:443"
            assert get_request_host(request, "https") == "dockmon.lokal"

    def test_forwarded_port_wins_over_cors_port(self):
        request = _make_request(headers={
            "x-forwarded-host": "dockmon.lokal",
            "x-forwarded-port": "9443",
        })
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:8314"
            assert get_request_host(request, "https") == "dockmon.lokal:9443"

    def test_cors_fallback_host_keeps_its_own_port(self):
        """When CORS_ORIGINS supplies the host outright (no X-Forwarded-Host),
        its netloc already carries the port."""
        request = _make_request()
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:8314"
            assert get_request_host(request, "https") == "dockmon.lokal:8314"

    def test_cors_fallback_host_drops_an_implicit_port(self):
        """A declared https://host:443 must not put :443 in the redirect URI."""
        request = _make_request()
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:443"
            assert get_request_host(request, "https") == "dockmon.lokal"

    def test_recovers_port_from_a_later_cors_origin(self):
        """The port-bearing origin is not necessarily declared first."""
        request = _make_request(headers={"x-forwarded-host": "dockmon.lokal"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "http://192.168.1.5:8001,https://dockmon.lokal:8314"
            assert get_request_host(request, "https") == "dockmon.lokal:8314"


class TestForwardedHostMustBeDeclared:
    """X-Forwarded-Host reaches outward-facing URLs (OIDC redirect URIs) and the
    fronting proxy may pass a client-supplied value straight through, so it is
    only honored for a hostname the operator declared."""

    def test_undeclared_forwarded_host_falls_back_to_declared_origin(self):
        request = _make_request(headers={"x-forwarded-host": "dockmon.example.com@evil.tld"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:8314"
            assert get_request_host(request, "https") == "dockmon.lokal:8314"

    def test_declared_forwarded_host_is_honored(self):
        request = _make_request(headers={"x-forwarded-host": "second.lokal"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal,https://second.lokal"
            assert get_request_host(request, "https") == "second.lokal"

    def test_forwarded_host_trusted_when_nothing_declared(self):
        """Fails open: DOCKMON_CORS_ORIGINS is unset by default."""
        request = _make_request(headers={"x-forwarded-host": "anything.lokal"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None
            assert get_request_host(request, "https") == "anything.lokal"

    def test_fallback_prefers_a_declared_origin_matching_the_scheme(self):
        """Pairing the effective scheme with another origin's netloc would name a
        host the operator never published under that scheme."""
        request = _make_request(headers={"x-forwarded-host": "evil.tld"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "http://lan.lokal:8001,https://dockmon.lokal:8314"
            assert get_request_host(request, "https") == "dockmon.lokal:8314"

    def test_declared_match_ignores_the_port(self):
        """The declaration names a host; the request may carry a port with it."""
        request = _make_request(headers={"x-forwarded-host": "dockmon.lokal:8314"})
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:8314"
            assert get_request_host(request, "https") == "dockmon.lokal:8314"


class TestNonStandardPortScenario:
    """End-to-end test for the reported non-standard-port issue (#242)."""

    def test_external_nginx_stripping_the_port_still_yields_it(self):
        """An external nginx using the ubiquitous `proxy_set_header Host $host`
        drops :8314, and the bundled nginx then derives X-Forwarded-Host from
        that stripped Host. The operator's CORS_ORIGINS restores the port."""
        request = _make_request(
            headers={
                "host": "dockmon.lokal",
                "x-forwarded-host": "dockmon.lokal",
                "x-forwarded-proto": "https",
            },
            scheme="http",
            netloc="dockmon.lokal",
        )
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = "https://dockmon.lokal:8314"

            scheme = get_request_scheme(request)
            host = get_request_host(request, scheme)
            redirect_uri = f"{scheme}://{host}/api/v2/auth/oidc/callback"

            assert redirect_uri == "https://dockmon.lokal:8314/api/v2/auth/oidc/callback"

    def test_proxy_forwarding_the_port_header_yields_it(self):
        """Proxies that send X-Forwarded-Port (Traefik and similar) need no
        DockMon-side configuration at all."""
        request = _make_request(
            headers={
                "host": "dockmon.lokal",
                "x-forwarded-host": "dockmon.lokal",
                "x-forwarded-proto": "https",
                "x-forwarded-port": "8314",
            },
            scheme="http",
            netloc="dockmon.lokal",
        )
        with patch("utils.client_ip.AppConfig") as mock_config:
            mock_config.REVERSE_PROXY_MODE = True
            mock_config.CORS_ORIGINS = None

            scheme = get_request_scheme(request)
            host = get_request_host(request, scheme)
            redirect_uri = f"{scheme}://{host}/api/v2/auth/oidc/callback"

            assert redirect_uri == "https://dockmon.lokal:8314/api/v2/auth/oidc/callback"


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
