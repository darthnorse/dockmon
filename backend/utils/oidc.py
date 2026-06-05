"""Shared OIDC provider URL helpers.

Centralizes the provider-URL normalization and discovery-document URL
construction that several OIDC code paths (login, logout, config validation)
would otherwise each reimplement.
"""

_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"


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
