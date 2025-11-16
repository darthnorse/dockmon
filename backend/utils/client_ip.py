"""
Client IP extraction with reverse proxy support.

SECURITY WARNING:
- Only trust X-Forwarded-For if you control the reverse proxy
- Enabling REVERSE_PROXY_MODE when directly exposed to internet is DANGEROUS
  (attackers can spoof X-Forwarded-For headers)
"""

import logging
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
        # Trust X-Forwarded-For from reverse proxy
        # Format: "client, proxy1, proxy2"
        xff = request.headers.get("x-forwarded-for")
        if xff:
            client_ip = xff.split(",")[0].strip()
            logger.debug(f"Using X-Forwarded-For: {client_ip}")
            return client_ip

        # Fallback to X-Real-IP (nginx alternative)
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            client_ip = real_ip.strip()
            logger.debug(f"Using X-Real-IP: {client_ip}")
            return client_ip

        # No proxy headers found - unexpected in reverse proxy mode
        logger.warning(
            "REVERSE_PROXY_MODE enabled but no X-Forwarded-For or X-Real-IP header found. "
            "Falling back to request.client.host."
        )

    # Direct connection or no proxy headers
    client_ip = request.client.host if request.client else "unknown"
    logger.debug(f"Using request.client.host: {client_ip}")
    return client_ip
