"""
Client IP extraction with reverse proxy support.

SECURITY WARNING:
- Only trust X-Forwarded-For if you control the reverse proxy
- Enabling REVERSE_PROXY_MODE when directly exposed to internet is DANGEROUS
  (attackers can spoof X-Forwarded-For headers)
"""

import logging
from urllib.parse import urlparse
from fastapi import Request
from config.settings import AppConfig
from utils.base_path import get_base_path

logger = logging.getLogger(__name__)

# Ports that are implicit in a URL and must never be written into one, since
# OIDC providers match redirect URIs as exact strings.
DEFAULT_PORTS = {'http': '80', 'https': '443'}


def get_client_ip(request: Request) -> str:
    """
    Get client IP address, handling reverse proxies correctly.

    Behavior:
    - REVERSE_PROXY_MODE=true: Trust X-Forwarded-For header (first IP)
    - REVERSE_PROXY_MODE=false: Use request.client.host

    Args:
        request: FastAPI request object

    Returns:
        Client IP address as string

    Examples:
        Behind Traefik (REVERSE_PROXY_MODE=true):
        - X-Forwarded-For: "203.0.113.5, 192.168.1.1"
        - Returns: "203.0.113.5" (original client)

        Direct connection (REVERSE_PROXY_MODE=false):
        - request.client.host: "203.0.113.5"
        - Returns: "203.0.113.5"
    """
    if AppConfig.REVERSE_PROXY_MODE:
        # An external proxy fronts the bundled nginx. X-Forwarded-For is
        # "client, proxy1, ..., proxyN" where the right-most entries are added by
        # trusted infrastructure. Take the entry immediately left of the trusted
        # hops so a client cannot spoof its IP by prepending fake entries.
        xff = request.headers.get("x-forwarded-for")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            hops = AppConfig.TRUSTED_PROXY_COUNT
            if len(parts) > hops:
                client_ip = parts[-(hops + 1)]
                logger.debug(f"Using X-Forwarded-For (trusted hops={hops}): {client_ip}")
                return client_ip
            # Fewer entries than expected trusted hops — use the left-most as the
            # best available client identity rather than a proxy address.
            logger.debug(f"X-Forwarded-For shorter than trusted hops; using left-most: {parts[0]}")
            return parts[0]

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        logger.warning(
            "REVERSE_PROXY_MODE enabled but no X-Forwarded-For or X-Real-IP header found. "
            "Falling back to request.client.host."
        )
        return request.client.host if request.client else "unknown"

    # Default (bundled-nginx) deployment: uvicorn only sees the local nginx as the
    # socket peer. The bundled nginx sets X-Real-IP=$remote_addr, overwriting any
    # client-supplied value, so it is trustworthy for the real client IP.
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _get_cors_origin_parts() -> tuple[str, str] | None:
    """Parse scheme and host from the first CORS origin, if configured."""
    if AppConfig.CORS_ORIGINS:
        first_origin = AppConfig.CORS_ORIGINS.split(',')[0].strip()
        parsed = urlparse(first_origin)
        if parsed.scheme and parsed.netloc:
            return parsed.scheme, parsed.netloc
    return None


def _iter_cors_origins() -> list[tuple[str, str]]:
    """Parse (scheme, netloc) for every configured CORS origin.

    Multi-domain deployments declare several origins, and the one carrying a
    non-standard port is not necessarily first.
    """
    if not AppConfig.CORS_ORIGINS:
        return []
    origins = []
    for raw in AppConfig.CORS_ORIGINS.split(','):
        parsed = urlparse(raw.strip())
        if parsed.scheme and parsed.netloc:
            origins.append((parsed.scheme, parsed.netloc))
    return origins


def _split_host_port(netloc: str) -> tuple[str, str | None]:
    """Split a netloc into (host, port), keeping IPv6 literals intact.

    A bracketed literal keeps its brackets; an unbracketed address with several
    colons has no parsable port and is returned whole.
    """
    if netloc.startswith('['):
        closing = netloc.find(']')
        if closing == -1:
            return netloc, None
        host, rest = netloc[:closing + 1], netloc[closing + 1:]
        if rest.startswith(':') and rest[1:]:
            return host, rest[1:]
        return host, None
    if netloc.count(':') == 1:
        host, _, port = netloc.partition(':')
        return host, port or None
    return netloc, None


def _strip_implicit_port(netloc: str, scheme: str) -> str:
    """Drop a port the scheme implies anyway, so it cannot reach a redirect URI.

    Only the port implicit for *this* scheme: a port stated explicitly, however
    unusual (https on :80), is the operator's declaration and is kept.
    """
    host, port = _split_host_port(netloc)
    if port and port == DEFAULT_PORTS.get(scheme):
        return host
    return netloc


def _forwarded_port(request: Request) -> str | None:
    """Public port from X-Forwarded-Port, or None if absent/implicit/invalid.

    Any scheme's default port is discarded here, not just this scheme's: the
    header is the proxy's guess at the public port, and a cross-scheme default
    (:80 on https) is far more likely its own backend hop than a real origin.
    """
    raw = request.headers.get("x-forwarded-port")
    if not raw:
        return None
    port = raw.split(",")[0].strip()
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        logger.warning(f"Ignoring malformed X-Forwarded-Port header: {raw!r}")
        return None
    if port in DEFAULT_PORTS.values():
        return None
    return port


def _cors_origin_port(host: str, scheme: str) -> str | None:
    """Public port declared by DOCKMON_CORS_ORIGINS for this exact origin.

    Requires the scheme and hostname to match: in multi-domain deployments the
    request may be for a host the operator never declared, and a port borrowed
    from a different origin would break the redirect rather than fix it.
    """
    for cors_scheme, cors_netloc in _iter_cors_origins():
        cors_host, cors_port = _split_host_port(cors_netloc)
        if not cors_port or cors_scheme != scheme:
            continue
        if cors_host.lower() != host.lower():
            continue
        if cors_port == DEFAULT_PORTS.get(scheme):
            continue
        return cors_port
    return None


def _declared_origin_netloc(scheme: str) -> str | None:
    """Netloc of a declared origin, preferring one that matches the scheme.

    Mixing the effective scheme with another origin's netloc would name a host
    the operator never published under that scheme.
    """
    origins = _iter_cors_origins()
    if not origins:
        return None
    for cors_scheme, cors_netloc in origins:
        if cors_scheme == scheme:
            return cors_netloc
    return origins[0][1]


def _is_declared_host(host: str) -> bool:
    """Whether DOCKMON_CORS_ORIGINS names this hostname.

    Fails open when the operator declared nothing, which is the default.
    """
    origins = _iter_cors_origins()
    if not origins:
        return True
    return any(
        _split_host_port(netloc)[0].lower() == host.lower()
        for _, netloc in origins
    )


def _restore_public_port(netloc: str, request: Request, scheme: str) -> str:
    """Re-attach a port that an upstream proxy stripped from the host.

    Proxies commonly forward `Host: $host`, which drops the port, leaving the
    backend unable to reconstruct the origin the browser used. Only called in
    REVERSE_PROXY_MODE, where forwarded headers are trusted.
    """
    host, port = _split_host_port(netloc)
    if port:
        return _strip_implicit_port(netloc, scheme)
    if ':' in host and not host.startswith('['):
        # Unbracketed IPv6 literal: appending a port would yield an unparsable URL.
        return netloc
    port = _forwarded_port(request) or _cors_origin_port(host, scheme)
    if not port:
        return netloc
    logger.debug(f"Restored stripped port :{port} on forwarded host")
    return f"{host}:{port}"


def get_request_scheme(request: Request) -> str:
    """Get the effective request scheme, respecting reverse proxy headers.

    Precedence (when REVERSE_PROXY_MODE is on):
      1. DOCKMON_CORS_ORIGINS scheme — but ONLY when it's "https". The
         operator's explicit declaration of an HTTPS public URL is treated
         as authoritative because some proxies (notably Caddy in certain
         configurations) send X-Forwarded-Proto=http even when the inbound
         was https, which would otherwise downgrade OIDC redirect_uri and
         the cookie Secure flag.
      2. X-Forwarded-Proto header — used when CORS_ORIGINS doesn't declare
         https. This is the right place to trust the proxy: if the proxy
         says https, that's an upgrade signal we should honor even if CORS
         says http (e.g., misconfigured CORS with TLS-terminating proxy).
      3. DOCKMON_CORS_ORIGINS scheme when it's http — the operator did
         declare http and no header overrode that.
      4. request.url.scheme — last-resort fallback (the local TCP scheme
         between the proxy and DockMon, often wrong when TLS is
         terminated by the proxy).

    The "CORS=https wins, CORS=http defers to header" asymmetry is the
    upgrade-only trust pattern: trust the operator when they say https,
    but never use a CORS http to silently downgrade a real HTTPS request.

    Note on intentional asymmetry with get_request_host: host genuinely
    differs per request in multi-domain setups, so X-Forwarded-Host stays
    primary there. Scheme is canonical for a deployment, so the operator's
    declared scheme is trusted ahead of headers when it's the more secure
    option. See get_request_host's docstring for the host-side rationale.
    """
    if AppConfig.REVERSE_PROXY_MODE:
        parts = _get_cors_origin_parts()
        # Trust CORS_ORIGINS only when it declares https — never silently
        # downgrade a real HTTPS request because of a misconfigured CORS http.
        if parts and parts[0] == 'https':
            logger.debug("Using scheme from DOCKMON_CORS_ORIGINS (https)")
            return 'https'
        proto = request.headers.get("x-forwarded-proto")
        if proto:
            logger.debug("Using scheme from X-Forwarded-Proto")
            return proto.split(",")[0].strip().lower()
        if parts:
            # CORS declared http and no overriding header — honor it.
            logger.debug("Using scheme from DOCKMON_CORS_ORIGINS (http)")
            return parts[0]
        logger.warning(
            "REVERSE_PROXY_MODE enabled but neither DOCKMON_CORS_ORIGINS nor "
            "X-Forwarded-Proto is set. Falling back to request.url.scheme, which "
            "reflects the local TCP scheme and may be wrong if the proxy "
            "terminates TLS."
        )
    else:
        # Default (bundled-nginx) deployment: nginx sets X-Forwarded-Proto=$scheme
        # (overwriting any client value), so honor it for the Secure cookie flag
        # and OIDC redirect URIs even though the nginx->uvicorn hop is plain HTTP.
        proto = request.headers.get("x-forwarded-proto")
        if proto:
            logger.debug("Using scheme from X-Forwarded-Proto (bundled nginx)")
            return proto.split(",")[0].strip().lower()
    return request.url.scheme


def get_request_host(request: Request, scheme: str | None = None) -> str:
    """Get the effective request host (with port), respecting reverse proxy headers.

    Precedence (when REVERSE_PROXY_MODE is on):
      1. X-Forwarded-Host header — the actual host from the request.
      2. DOCKMON_CORS_ORIGINS host — fallback when no header is present.
      3. Host header / request.url.netloc — last-resort fallback.

    Cases 1 and 3 come from headers a proxy may have written as `$host`, which
    drops the port; the port is then restored from X-Forwarded-Port or from a
    DOCKMON_CORS_ORIGINS entry naming the same origin. Case 2 already carries
    whatever port the operator declared.

    X-Forwarded-Host is only honored for a hostname DOCKMON_CORS_ORIGINS names,
    when it names any: the header reaches outward-facing URLs (OIDC redirect
    URIs), the fronting proxy is not guaranteed to overwrite a client-supplied
    value, and nothing else here constrains which host lands in those URLs.
    Declaring no origins keeps the header trusted, which is the default.

    Args:
        request: FastAPI request object
        scheme: Effective scheme, to decide which port is implicit. Derived via
            get_request_scheme() when omitted; pass it if already computed.

    Note on intentional asymmetry with get_request_scheme: host genuinely
    differs per request in multi-domain setups (one DockMon serving
    multiple hostnames via a reverse proxy), so the request-specific
    X-Forwarded-Host is primary. Scheme, by contrast, is canonical for a
    deployment, so the operator's declared CORS_ORIGINS scheme is trusted
    over the header (when it declares https) to avoid downgrade attacks
    from misconfigured proxies. See get_request_scheme's docstring.
    """
    if AppConfig.REVERSE_PROXY_MODE:
        if scheme is None:
            scheme = get_request_scheme(request)
        forwarded_host = request.headers.get("x-forwarded-host")
        if forwarded_host:
            netloc = forwarded_host.split(",")[0].strip()
            if _is_declared_host(_split_host_port(netloc)[0]):
                return _restore_public_port(netloc, request, scheme)
            logger.warning(
                "Ignoring X-Forwarded-Host not named by DOCKMON_CORS_ORIGINS; "
                "using the declared origin instead"
            )
        declared = _declared_origin_netloc(scheme)
        if declared:
            logger.debug("No usable X-Forwarded-Host header; using host from DOCKMON_CORS_ORIGINS")
            return _strip_implicit_port(declared, scheme)
        logger.warning(
            "REVERSE_PROXY_MODE enabled but no X-Forwarded-Host header found "
            "and DOCKMON_CORS_ORIGINS not set. Falling back to Host header."
        )
        return _restore_public_port(
            request.headers.get("host", request.url.netloc), request, scheme
        )
    return request.headers.get("host", request.url.netloc)


def build_public_url(request: Request, path: str) -> str:
    """Build an absolute URL for `path` on the origin the browser used.

    Single source of truth for outward-facing URLs (OIDC redirect URIs, logout
    returns) so that what DockMon displays for registration and what it later
    sends to a provider cannot drift apart.
    """
    scheme = get_request_scheme(request)
    host = get_request_host(request, scheme)
    return f"{scheme}://{host}{get_base_path().rstrip('/')}{path}"


def get_client_ip_ws(websocket) -> str:
    """
    Get client IP from WebSocket, respecting reverse proxy headers.

    WebSocket objects have .headers and .client like Request objects,
    but are not FastAPI Request instances, so we need a separate function.
    """
    if AppConfig.REVERSE_PROXY_MODE:
        forwarded = websocket.headers.get('x-forwarded-for')
        if forwarded:
            parts = [p.strip() for p in forwarded.split(',') if p.strip()]
            hops = AppConfig.TRUSTED_PROXY_COUNT
            if len(parts) > hops:
                return parts[-(hops + 1)]
            return parts[0]
        real_ip = websocket.headers.get('x-real-ip')
        if real_ip:
            return real_ip.strip()
        return websocket.client.host if websocket.client else "unknown"

    # Default deployment: trust the bundled nginx's X-Real-IP.
    real_ip = websocket.headers.get('x-real-ip')
    if real_ip:
        return real_ip.strip()
    return websocket.client.host if websocket.client else "unknown"
