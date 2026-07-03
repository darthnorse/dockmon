"""
Shared URL validation utilities for SSRF prevention.

Used by health check URL validation and Docker host URL validation
to block requests to cloud metadata services and dangerous internal endpoints.
"""

import re
import ipaddress
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Cloud metadata and dangerous internal targets
# These are extremely dangerous SSRF targets that should never be allowed as user-supplied URLs
SSRF_BLOCKED_PATTERNS = [
    r'169\.254\.169\.254',              # AWS/GCP metadata (specific)
    r'169\.254\.',                      # Link-local range (broader)
    r'metadata\.google\.internal',      # GCP metadata
    r'metadata\.goog',                  # GCP metadata alternative
    r'100\.100\.100\.200',              # Alibaba Cloud metadata
    r'fd00:ec2::254',                   # AWS IPv6 metadata
    r'0\.0\.0\.0',                      # All interfaces binding
    r'::1',                             # IPv6 localhost
]


def _host_as_ip(host: str):
    """Parse an URL host as an IP address, including integer and hex encodings.

    Returns an ip_address object or None if the host is not an IP literal.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        if host.startswith(('0x', '0X')):
            return ipaddress.ip_address(int(host, 16))
        if host.isdigit():
            return ipaddress.ip_address(int(host))
    except (ValueError, OverflowError):
        pass
    return None


def is_ssrf_target(url: str, block_loopback: bool = False) -> bool:
    """Check if a URL targets a cloud metadata service or dangerous internal endpoint.

    Args:
        url: The URL to check
        block_loopback: When True (HTTP health checks), also block localhost,
            loopback, link-local and reserved addresses (including integer/hex IP
            encodings). Default False keeps the Docker-host behaviour, which must
            allow private and loopback addresses for legitimate local daemons.

    Returns:
        True if the URL is a known SSRF target and should be blocked
    """
    for pattern in SSRF_BLOCKED_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True

    if not block_loopback:
        # Docker-host path: metadata denylist only; private/loopback are allowed.
        return False

    host = (urlparse(url).hostname or '').lower()
    if not host:
        return True  # unparseable host — fail closed
    if host == 'localhost' or host.endswith('.localhost'):
        return True

    ip = _host_as_ip(host)
    if ip is not None and (
        ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    ):
        return True
    # Note: hostnames are not DNS-resolved here to avoid false positives on
    # health-check targets that only resolve inside a Docker network. Redirect
    # hops are re-validated at request time (see http_checker).
    return False
