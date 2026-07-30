"""Shared OIDC provider URL helpers.

Centralizes the provider-URL normalization and discovery-document URL
construction that several OIDC code paths (login, logout, config validation)
would otherwise each reimplement.
"""

import logging
from urllib.parse import urlparse

from fastapi import Request

from utils.client_ip import build_public_url

logger = logging.getLogger(__name__)

_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"

CALLBACK_PATH = "/api/v2/auth/oidc/callback"
LOGIN_PATH = "/login"


def normalize_provider_url(provider_url: str) -> str:
    """Return the provider base URL without a trailing slash or discovery suffix.

    Accepts either the base issuer URL or the full discovery URL and returns the
    base, so callers can build other endpoints from a consistent value.
    """
    provider_url = provider_url.rstrip('/')
    if provider_url.endswith(_DISCOVERY_SUFFIX):
        provider_url = provider_url[:-len(_DISCOVERY_SUFFIX)]
    return provider_url


def build_discovery_url(provider_url: str) -> str:
    """Return the OpenID Connect discovery document URL for a provider URL."""
    return f"{normalize_provider_url(provider_url)}{_DISCOVERY_SUFFIX}"


def build_callback_url(request: Request, override: str | None = None) -> str:
    """Return the redirect_uri to send to the provider.

    Providers match redirect URIs as exact strings, so an operator override wins
    over detection: some proxy chains forward nothing that identifies the public
    origin, leaving detection unable to reproduce the registered value.
    """
    if override:
        return override
    return build_public_url(request, CALLBACK_PATH)


def build_post_logout_url(request: Request, override: str | None = None) -> str:
    """Return the post_logout_redirect_uri (the DockMon login page).

    Derived from the callback override when set, so both URIs describe the same
    origin and a provider validating post-logout URIs accepts it. The override's
    own path prefix is reused rather than re-derived from BASE_PATH, which can
    differ from the prefix a proxy exposes publicly.
    """
    if override:
        parsed = urlparse(override)
        if parsed.scheme and parsed.netloc and parsed.path.endswith(CALLBACK_PATH):
            prefix = parsed.path[:-len(CALLBACK_PATH)].rstrip('/')
            return f"{parsed.scheme}://{parsed.netloc}{prefix}{LOGIN_PATH}"
        logger.warning("Ignoring unusable OIDC redirect URI override for logout")
    return build_public_url(request, LOGIN_PATH)
