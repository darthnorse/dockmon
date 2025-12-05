"""
DockMon Application Update Checker

Checks GitHub for new DockMon and Agent releases (NOT container updates).
Runs every 6 hours (hardcoded) to notify users of available application updates.

Supports two release patterns:
- DockMon: v2.2.0 (standard semver with v prefix)
- Agent: agent-v1.0.0 (agent-prefixed semver)
"""

import asyncio
import logging
import os
import re
import aiohttp
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple
from packaging.version import parse as parse_version, InvalidVersion

from database import DatabaseManager, GlobalSettings

logger = logging.getLogger(__name__)

# Tag patterns for release filtering (strict semver, excludes prereleases)
DOCKMON_TAG_PATTERN = re.compile(r'^v(\d+\.\d+\.\d+)$')
AGENT_TAG_PATTERN = re.compile(r'^agent-v(\d+\.\d+\.\d+)$')


def normalize_version(version: str) -> str:
    """Normalize version string for PEP 440 compatibility.

    Converts formats like '2.1.8-hotfix.3' to '2.1.8.post3' which is valid PEP 440.
    """
    import re
    # Convert hotfix.N to post release format (PEP 440 compliant)
    # 2.1.8-hotfix.3 -> 2.1.8.post3
    normalized = re.sub(r'-hotfix\.(\d+)', r'.post\1', version)
    # Also handle hotfixN format (no dot)
    normalized = re.sub(r'-hotfix(\d+)', r'.post\1', normalized)
    return normalized


class DockMonUpdateChecker:
    """Check GitHub for DockMon and Agent application updates"""

    # Hardcoded constants
    GITHUB_REPO = "darthnorse/dockmon"
    GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
    GITHUB_LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    CHECK_INTERVAL_HOURS = 6  # Hardcoded: Check every 6 hours
    REQUEST_TIMEOUT = 10  # Seconds

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._releases_cache: Optional[List[Dict]] = None
        self._cache_time: Optional[datetime] = None

    async def check_for_update(self) -> Dict[str, any]:
        """
        Check GitHub for latest DockMon release.

        Returns:
            {
                'current_version': '2.0.1',
                'latest_version': '2.0.2',
                'update_available': True,
                'github_release_url': 'https://github.com/darthnorse/dockmon/releases/tag/v2.0.2',
                'error': None
            }
        """
        try:
            # Get current version from database
            settings = self.db.get_settings()
            if not settings:
                logger.error("GlobalSettings not found - database not initialized")
                return {
                    'current_version': '0.0.0',
                    'latest_version': None,
                    'update_available': False,
                    'github_release_url': None,
                    'error': 'Database not initialized'
                }
            current_version = settings.app_version or "0.0.0"

            logger.debug(f"Checking for DockMon updates (current: {current_version})")

            # DEBUG/TESTING: Allow override via environment variable
            # Set DOCKMON_TEST_VERSION=2.0.2 to simulate a new version being available
            test_version = os.environ.get('DOCKMON_TEST_VERSION')
            if test_version:
                logger.warning(f"🧪 TEST MODE: Simulating DockMon version {test_version} available (set via DOCKMON_TEST_VERSION)")
                latest_version = test_version
                release_url = f"https://github.com/{self.GITHUB_REPO}/releases/tag/v{test_version}"
            else:
                # Fetch latest release from GitHub API
                latest_version, release_url = await self._fetch_latest_release()

            if not latest_version:
                logger.warning("Failed to fetch latest DockMon version from GitHub")
                return {
                    'current_version': current_version,
                    'latest_version': None,
                    'update_available': False,
                    'github_release_url': None,
                    'error': 'Failed to fetch from GitHub'
                }

            # Compare versions using semver
            try:
                # Normalize versions for PEP 440 compatibility (e.g., hotfix.3 -> post3)
                normalized_current = normalize_version(current_version)
                normalized_latest = normalize_version(latest_version)
                update_available = parse_version(normalized_latest) > parse_version(normalized_current)
            except InvalidVersion as e:
                logger.error(f"Invalid version format: current={current_version}, latest={latest_version}: {e}")
                return {
                    'current_version': current_version,
                    'latest_version': latest_version,
                    'update_available': False,
                    'github_release_url': release_url,
                    'error': f'Invalid version format: {e}'
                }

            # Update database cache
            with self.db.get_session() as session:
                settings = session.query(GlobalSettings).first()
                if not settings:
                    logger.error("GlobalSettings not found in database - this should never happen!")
                    return {
                        'current_version': current_version,
                        'latest_version': None,
                        'update_available': False,
                        'github_release_url': None,
                        'error': 'Database not initialized'
                    }
                settings.latest_available_version = latest_version
                settings.last_dockmon_update_check_at = datetime.now(timezone.utc)
                session.commit()

            if update_available:
                logger.info(f"DockMon update available: {current_version} → {latest_version}")
            else:
                logger.debug(f"DockMon is up to date: {current_version}")

            return {
                'current_version': current_version,
                'latest_version': latest_version,
                'update_available': update_available,
                'github_release_url': release_url,
                'error': None
            }

        except Exception as e:
            logger.error(f"Error checking for DockMon updates: {e}", exc_info=True)
            return {
                'current_version': current_version if 'current_version' in locals() else '0.0.0',
                'latest_version': None,
                'update_available': False,
                'github_release_url': None,
                'error': str(e)
            }

    async def _fetch_latest_release(self) -> tuple[Optional[str], Optional[str]]:
        """
        Fetch latest release from GitHub API.

        Returns:
            (version, release_url) tuple, or (None, None) on failure
        """
        try:
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            headers = {
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'DockMon-Update-Checker'
            }

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.GITHUB_LATEST_URL, headers=headers) as response:
                    if response.status == 404:
                        logger.warning(f"GitHub repository not found: {self.GITHUB_REPO}")
                        return None, None

                    if response.status == 403:
                        logger.warning("GitHub API rate limit exceeded")
                        return None, None

                    if response.status != 200:
                        logger.warning(f"GitHub API returned status {response.status}")
                        return None, None

                    data = await response.json()

                    # Extract tag_name (e.g., "v2.0.2")
                    tag_name = data.get('tag_name', '')
                    if not tag_name:
                        logger.warning("No tag_name in GitHub release response")
                        return None, None

                    # Strip 'v' prefix if present
                    version = tag_name.lstrip('v')

                    # Get release URL
                    release_url = data.get('html_url', f"https://github.com/{self.GITHUB_REPO}/releases/latest")

                    logger.debug(f"Fetched latest DockMon release from GitHub: {version}")
                    return version, release_url

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching DockMon release from GitHub (after {self.REQUEST_TIMEOUT}s)")
            return None, None
        except aiohttp.ClientError as e:
            logger.warning(f"Network error fetching DockMon release: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error fetching DockMon release: {e}", exc_info=True)
            return None, None

    async def check_for_agent_update(self) -> Dict[str, any]:
        """
        Check GitHub for latest Agent release.

        Returns:
            {
                'latest_version': '1.0.0',
                'release_url': 'https://github.com/.../releases/tag/agent-v1.0.0',
                'error': None
            }
        """
        try:
            # DEBUG/TESTING: Allow override via environment variable
            test_version = os.environ.get('AGENT_TEST_VERSION')
            if test_version:
                logger.warning(f"TEST MODE: Simulating Agent version {test_version} available")
                return {
                    'latest_version': test_version,
                    'release_url': f"https://github.com/{self.GITHUB_REPO}/releases/tag/agent-v{test_version}",
                    'error': None
                }

            # Fetch all releases and find latest agent release
            releases = await self._fetch_all_releases()
            if not releases:
                return {
                    'latest_version': None,
                    'release_url': None,
                    'error': 'Failed to fetch releases from GitHub'
                }

            agent_release = self._find_latest_by_pattern(releases, AGENT_TAG_PATTERN)
            if not agent_release:
                logger.debug("No agent releases found on GitHub")
                return {
                    'latest_version': None,
                    'release_url': None,
                    'error': None  # Not an error - agent may not have releases yet
                }

            # Update database cache
            with self.db.get_session() as session:
                settings = session.query(GlobalSettings).first()
                if settings:
                    settings.latest_agent_version = agent_release['version']
                    settings.latest_agent_release_url = agent_release['html_url']
                    settings.last_agent_update_check_at = datetime.now(timezone.utc)
                    session.commit()

            logger.debug(f"Latest agent version from GitHub: {agent_release['version']}")

            return {
                'latest_version': agent_release['version'],
                'release_url': agent_release['html_url'],
                'error': None
            }

        except Exception as e:
            logger.error(f"Error checking for Agent updates: {e}", exc_info=True)
            return {
                'latest_version': None,
                'release_url': None,
                'error': str(e)
            }

    async def check_all_updates(self) -> Dict[str, Dict]:
        """
        Check for both DockMon and Agent updates in a single call.

        Returns:
            {
                'dockmon': { check_for_update() result },
                'agent': { check_for_agent_update() result }
            }
        """
        dockmon_result = await self.check_for_update()
        agent_result = await self.check_for_agent_update()

        return {
            'dockmon': dockmon_result,
            'agent': agent_result
        }

    async def _fetch_all_releases(self) -> Optional[List[Dict]]:
        """
        Fetch all releases from GitHub API (with caching).

        Returns:
            List of release objects, or None on failure
        """
        # Check cache (valid for 5 minutes)
        if self._releases_cache and self._cache_time:
            cache_age = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
            if cache_age < 300:  # 5 minute cache
                return self._releases_cache

        try:
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            headers = {
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'DockMon-Update-Checker'
            }

            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Fetch first page (100 releases should be enough)
                async with session.get(
                    f"{self.GITHUB_RELEASES_URL}?per_page=100",
                    headers=headers
                ) as response:
                    if response.status != 200:
                        logger.warning(f"GitHub API returned status {response.status}")
                        return None

                    releases = await response.json()

                    # Cache the result
                    self._releases_cache = releases
                    self._cache_time = datetime.now(timezone.utc)

                    return releases

        except Exception as e:
            logger.error(f"Error fetching releases from GitHub: {e}", exc_info=True)
            return None

    def _find_latest_by_pattern(
        self,
        releases: List[Dict],
        pattern: re.Pattern
    ) -> Optional[Dict]:
        """
        Find the latest release matching a tag pattern.

        Args:
            releases: List of GitHub release objects
            pattern: Regex pattern to match tag names

        Returns:
            Dict with 'version', 'html_url', 'tag_name' or None
        """
        matching = []

        for release in releases:
            # Skip drafts and prereleases
            if release.get('draft') or release.get('prerelease'):
                continue

            tag_name = release.get('tag_name', '')
            match = pattern.match(tag_name)
            if match:
                matching.append({
                    'version': match.group(1),
                    'html_url': release.get('html_url'),
                    'tag_name': tag_name,
                })

        if not matching:
            return None

        # Sort by semver and return latest
        try:
            matching.sort(
                key=lambda x: parse_version(normalize_version(x['version'])),
                reverse=True
            )
            return matching[0]
        except Exception as e:
            logger.warning(f"Error sorting versions: {e}")
            # Fallback: return first match (GitHub returns newest first)
            return matching[0] if matching else None

    async def fetch_agent_checksum(self, version: str, arch: str) -> Optional[str]:
        """
        Fetch checksum for agent binary from release assets.

        Args:
            version: Agent version (e.g., '1.0.0')
            arch: Architecture ('amd64' or 'arm64')

        Returns:
            SHA256 checksum string, or None if not found
        """
        tag = f"agent-v{version}"
        url = f"https://github.com/{self.GITHUB_REPO}/releases/download/{tag}/checksums.txt"

        try:
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            headers = {'User-Agent': 'DockMon-Update-Checker'}

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.warning(f"Failed to fetch checksums for {tag}: HTTP {response.status}")
                        return None

                    content = await response.text()

                    # Parse checksums.txt: "sha256hash  filename"
                    for line in content.strip().split('\n'):
                        parts = line.split()
                        if len(parts) >= 2:
                            checksum, filename = parts[0], parts[1]
                            if f"linux-{arch}" in filename:
                                logger.debug(f"Found checksum for {arch}: {checksum[:16]}...")
                                return checksum

                    logger.warning(f"No checksum found for linux-{arch} in {tag}")
                    return None

        except Exception as e:
            logger.error(f"Error fetching agent checksum: {e}", exc_info=True)
            return None


# Singleton instance
_dockmon_update_checker_instance: Optional[DockMonUpdateChecker] = None


def get_dockmon_update_checker(db: DatabaseManager) -> DockMonUpdateChecker:
    """Get or create singleton DockMonUpdateChecker instance"""
    global _dockmon_update_checker_instance
    if _dockmon_update_checker_instance is None:
        _dockmon_update_checker_instance = DockMonUpdateChecker(db)
    return _dockmon_update_checker_instance
