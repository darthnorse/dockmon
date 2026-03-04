"""
Shared URL validation utilities for SSRF prevention.

Used by health check URL validation and Docker host URL validation
to block requests to cloud metadata services and dangerous internal endpoints.
"""

import re
import logging

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


def is_ssrf_target(url: str) -> bool:
    """Check if a URL targets a cloud metadata service or dangerous internal endpoint.

    Args:
        url: The URL to check

    Returns:
        True if the URL is a known SSRF target and should be blocked
    """
    for pattern in SSRF_BLOCKED_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False
