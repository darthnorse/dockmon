"""
Changelog URL Resolution for Docker Images

Resolves changelog URLs using a 3-tier approach:
1. OCI image labels (org.opencontainers.image.source)
2. GHCR registry heuristic (ghcr.io/owner/repo)
3. Fuzzy matching GitHub URLs (Docker Hub images)

Re-check strategy:
- OCI/GHCR: Always check (instant, deterministic)
- Fuzzy match: Every 3 days or on failure (expensive, network calls)

Usage:
    url, source, checked_at = await resolve_changelog_url(
        image_name="nginx:latest",
        manifest_labels={"org.opencontainers.image.source": "https://github.com/..."},
        current_url=None,
        current_source=None,
        last_checked=None
    )
"""
import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Re-check interval for fuzzy matches (3 days)
FUZZY_RECHECK_DAYS = 3


async def resolve_changelog_url(
    image_name: str,
    manifest_labels: dict,
    current_url: Optional[str],
    current_source: Optional[str],
    last_checked: Optional[datetime]
) -> Tuple[Optional[str], str, datetime]:
    """
    Resolve changelog URL for a container image.

    Args:
        image_name: Full image reference (e.g., "nginx:latest", "ghcr.io/owner/repo:tag")
        manifest_labels: OCI labels from image manifest
        current_url: Previously resolved URL (or None)
        current_source: How URL was found ('oci_label', 'ghcr', 'fuzzy_match', 'failed')
        last_checked: When we last checked for changelog

    Returns:
        Tuple of (url, source, checked_at):
            - url: GitHub releases URL or None
            - source: 'oci_label', 'ghcr', 'fuzzy_match', or 'failed'
            - checked_at: Current timestamp (UTC)

    Example:
        >>> url, source, checked = await resolve_changelog_url(
        ...     "ghcr.io/linuxserver/sabnzbd:latest",
        ...     {"org.opencontainers.image.source": "https://github.com/linuxserver/docker-sabnzbd"},
        ...     None, None, None
        ... )
        >>> print(url, source)
        https://github.com/linuxserver/docker-sabnzbd/releases oci_label
    """
    now = datetime.now(timezone.utc)

    # Tier 1: OCI Labels (always check - data already available from manifest)
    oci_url = _check_oci_labels(manifest_labels)
    if oci_url:
        if oci_url != current_url:
            logger.info(f"Changelog URL from OCI label: {oci_url}")
        return oci_url, 'oci_label', now

    # Tier 2: GHCR Heuristic (always check - instant string manipulation)
    ghcr_url = _check_ghcr_heuristic(image_name)
    if ghcr_url:
        if ghcr_url != current_url:
            logger.info(f"Changelog URL from GHCR heuristic: {ghcr_url}")
        return ghcr_url, 'ghcr', now

    # Tier 3: Fuzzy Matching (conditional - expensive network calls)
    should_fuzzy_match = _should_fuzzy_match(current_source, last_checked)

    if should_fuzzy_match:
        logger.debug(f"Running fuzzy match for {image_name}")
        fuzzy_url = await _fuzzy_match_github(image_name)
        if fuzzy_url:
            logger.info(f"Changelog URL from fuzzy match: {fuzzy_url}")
            return fuzzy_url, 'fuzzy_match', now
        else:
            logger.debug(f"No changelog found for {image_name}")
            return None, 'failed', now

    # Return cached result (no re-check needed)
    return current_url, current_source or 'failed', last_checked or now


def _check_oci_labels(labels: dict) -> Optional[str]:
    """
    Extract GitHub releases URL from OCI image labels.

    Checks for org.opencontainers.image.source label and converts to releases URL.

    Args:
        labels: OCI image labels dict

    Returns:
        GitHub releases URL or None

    Example:
        >>> _check_oci_labels({"org.opencontainers.image.source": "https://github.com/foo/bar"})
        'https://github.com/foo/bar/releases'
    """
    if not labels:
        return None

    source = labels.get('org.opencontainers.image.source')
    if source and 'github.com' in source:
        return source.rstrip('/') + '/releases'
    return None


def _check_ghcr_heuristic(image_name: str) -> Optional[str]:
    """
    Generate GitHub releases URL for GHCR images.

    GHCR images are always hosted on GitHub, so we can deterministically
    construct the releases URL from the image name.

    Args:
        image_name: Full image reference (e.g., "ghcr.io/owner/repo:tag")

    Returns:
        GitHub releases URL or None

    Example:
        >>> _check_ghcr_heuristic("ghcr.io/linuxserver/sabnzbd:latest")
        'https://github.com/linuxserver/sabnzbd/releases'
    """
    if image_name.startswith('ghcr.io/'):
        # ghcr.io/owner/repo:tag → github.com/owner/repo/releases
        parts = image_name.replace('ghcr.io/', '').split(':')[0]
        return f'https://github.com/{parts}/releases'
    return None


def _should_fuzzy_match(current_source: Optional[str], last_checked: Optional[datetime]) -> bool:
    """
    Determine if we should run expensive fuzzy matching.

    Re-check logic:
    - Never checked: Yes
    - Failed last time: Yes, if >3 days ago
    - Fuzzy match: Yes, if >3 days ago (repo might have moved)
    - OCI/GHCR: No (always rechecked above)

    Args:
        current_source: Previous resolution source
        last_checked: When we last checked

    Returns:
        True if fuzzy match should run
    """
    # Never checked before
    if current_source is None or last_checked is None:
        return True

    now = datetime.now(timezone.utc)
    # Make last_checked timezone-aware if it's naive (from SQLite)
    if last_checked.tzinfo is None:
        last_checked = last_checked.replace(tzinfo=timezone.utc)
    days_since_check = (now - last_checked).days

    # Failed last time - retry periodically
    if current_source == 'failed':
        return days_since_check >= FUZZY_RECHECK_DAYS

    # Previous fuzzy match - re-check periodically (repo might have moved)
    if current_source == 'fuzzy_match':
        return days_since_check >= FUZZY_RECHECK_DAYS

    # OCI/GHCR are always rechecked above, shouldn't reach here
    return False


async def _fuzzy_match_github(image_name: str) -> Optional[str]:
    """
    Fuzzy match Docker image to GitHub repository.

    Tries common GitHub URL patterns and validates they exist via HEAD requests.

    Strategy:
    1. Strip registry prefix (ghcr.io, lscr.io, etc.)
    2. Parse image name (e.g., "portainer/portainer-ce:latest" → owner/repo)
    3. Generate candidate URLs (exact match, repo named after owner, docker- prefix, etc.)
    4. Validate each candidate with HEAD request
    5. Return first valid /releases URL

    Args:
        image_name: Full image reference (e.g., "lscr.io/linuxserver/sabnzbd:latest")

    Returns:
        GitHub releases URL or None

    Example:
        >>> await _fuzzy_match_github("lscr.io/linuxserver/sabnzbd:latest")
        'https://github.com/linuxserver/docker-sabnzbd/releases'
    """
    # Parse image: Strip tag first, then split by /
    image_without_tag = image_name.split(':')[0]
    parts = image_without_tag.split('/')

    # Strip registry prefix (e.g., "lscr.io", "ghcr.io", "registry.example.com:5000")
    # Registry prefixes contain '.' or ':' (domain names or domain:port)
    if len(parts) > 1 and ('.' in parts[0] or ':' in parts[0]):
        # Has registry prefix - strip it
        parts = parts[1:]  # Remove first element (registry)

    if len(parts) == 1:
        # Official image like "nginx" - rarely have GitHub releases
        logger.debug(f"Skipping fuzzy match for official image: {image_name}")
        return None

    if len(parts) < 2:
        logger.debug(f"Could not parse owner/repo from: {image_name}")
        return None

    owner, repo = parts[0], parts[1]

    # Generate candidate URLs (in priority order)
    candidates = [
        f"https://github.com/{owner}/{repo}",                      # Exact match (louislam/uptime-kuma)
        f"https://github.com/{owner}/{owner}",                     # Repo named after owner (portainer/portainer)
        f"https://github.com/{owner}/docker-{repo}",               # linuxserver pattern (linuxserver/docker-sabnzbd)
        f"https://github.com/{owner}/{repo.replace('-', '_')}",    # Dash vs underscore
    ]

    # Try each candidate
    for candidate in candidates:
        releases_url = f"{candidate}/releases"
        logger.debug(f"Trying: {releases_url}")
        if await _validate_github_url(releases_url):
            logger.debug(f"Found: {releases_url}")
            return releases_url

    logger.debug(f"No GitHub repo found for {image_name}")
    return None


async def _validate_github_url(url: str) -> bool:
    """
    Check if GitHub URL exists via HEAD request.

    Uses HEAD request (no download) with 3-second timeout.

    Args:
        url: GitHub URL to validate

    Returns:
        True if URL returns 200, False otherwise
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(
                url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=3)
            ) as response:
                return response.status == 200
    except asyncio.TimeoutError:
        logger.debug(f"Timeout validating: {url}")
        return False
    except Exception as e:
        logger.debug(f"Error validating {url}: {e}")
        return False
