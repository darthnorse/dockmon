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

logger = logging.getLogger(__name__)


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


def get_request_host(request: Request) -> str:
    """Get the effective request host, respecting reverse proxy headers.

    Precedence (when REVERSE_PROXY_MODE is on):
      1. X-Forwarded-Host header — the actual host from the request.
      2. DOCKMON_CORS_ORIGINS host — fallback when no header is present.
      3. Host header / request.url.netloc — last-resort fallback.

    Note on intentional asymmetry with get_request_scheme: host genuinely
    differs per request in multi-domain setups (one DockMon serving
    multiple hostnames via a reverse proxy), so the request-specific
    X-Forwarded-Host is primary. Scheme, by contrast, is canonical for a
    deployment, so the operator's declared CORS_ORIGINS scheme is trusted
    over the header (when it declares https) to avoid downgrade attacks
    from misconfigured proxies. See get_request_scheme's docstring.
    """
    if AppConfig.REVERSE_PROXY_MODE:
        forwarded_host = request.headers.get("x-forwarded-host")
        if forwarded_host:
            return forwarded_host.split(",")[0].strip()
        parts = _get_cors_origin_parts()
        if parts:
            logger.debug("No X-Forwarded-Host header; using host from DOCKMON_CORS_ORIGINS")
            return parts[1]
        logger.warning(
            "REVERSE_PROXY_MODE enabled but no X-Forwarded-Host header found "
            "and DOCKMON_CORS_ORIGINS not set. Falling back to Host header."
        )
    return request.headers.get("host", request.url.netloc)


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
