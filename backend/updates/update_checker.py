"""
Update Checker Service

Background task that periodically checks all containers for available updates.
Runs daily by default, configurable via global settings.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from database import DatabaseManager, ContainerUpdate, GlobalSettings, RegistryCredential, UpdatePolicy

# Image cache TTL configuration (in seconds)
# Can be overridden via environment variables
CACHE_TTL_LATEST = int(os.getenv('DOCKMON_CACHE_TTL_LATEST', 30 * 60))  # 30 minutes
CACHE_TTL_PINNED = int(os.getenv('DOCKMON_CACHE_TTL_PINNED', 24 * 3600))  # 24 hours
CACHE_TTL_FLOATING = int(os.getenv('DOCKMON_CACHE_TTL_FLOATING', 6 * 3600))  # 6 hours
CACHE_TTL_DEFAULT = int(os.getenv('DOCKMON_CACHE_TTL_DEFAULT', 6 * 3600))  # 6 hours
from updates.registry_adapter import get_registry_adapter
from updates.changelog_resolver import resolve_changelog_url
from event_bus import Event, EventType, get_event_bus
from utils.keys import make_composite_key
from utils.encryption import decrypt_password
from utils.container_id import normalize_container_id

logger = logging.getLogger(__name__)


class UpdateChecker:
    """
    Service that checks containers for available image updates.

    Workflow:
    1. Fetch all containers from all hosts
    2. For each container:
       - Get current image digest from Docker
       - Compute floating tag based on tracking mode
       - Resolve floating tag to latest digest
       - Compare digests to determine if update available
    3. Store results in container_updates table
    4. Create events for newly available updates
    """

    def __init__(self, db: DatabaseManager, monitor=None):
        self.db = db
        self.monitor = monitor
        self.registry = get_registry_adapter()

    def _get_registry_credentials(self, image_name: str) -> Optional[Dict[str, str]]:
        """Get credentials for registry from image name (delegates to shared utility)."""
        from utils.registry_credentials import get_registry_credentials
        return get_registry_credentials(self.db, image_name)

    def _compute_cache_ttl_seconds(self, image_tag: str) -> int:
        """
        Compute cache TTL in seconds based on tag pattern.

        Issue #62: Different TTLs to balance freshness vs rate limits.

        TTLs can be configured via environment variables:
        - DOCKMON_CACHE_TTL_LATEST: For :latest tags (default: 1800s / 30min)
        - DOCKMON_CACHE_TTL_PINNED: For pinned versions like 1.25.3 (default: 86400s / 24h)
        - DOCKMON_CACHE_TTL_FLOATING: For floating tags like 1.25 (default: 21600s / 6h)
        - DOCKMON_CACHE_TTL_DEFAULT: For other tags (default: 21600s / 6h)

        Args:
            image_tag: Full image reference (e.g., "nginx:1.25.3", "ghcr.io/org/app:latest")

        Returns:
            TTL in seconds
        """
        # Check for :latest tag
        if ':latest' in image_tag:
            return CACHE_TTL_LATEST

        # Extract just the tag portion
        tag = image_tag.split(':')[-1] if ':' in image_tag else 'latest'

        # Pinned version (1.25.3, v2.0.1, 1.2.3.4)
        if re.match(r'^v?\d+\.\d+\.\d+', tag):
            return CACHE_TTL_PINNED

        # Floating minor/major (1.25, 1, v2)
        if re.match(r'^v?\d+(\.\d+)?$', tag):
            return CACHE_TTL_FLOATING

        # Default (alpine, stable, bullseye, etc.)
        return CACHE_TTL_DEFAULT

    async def check_all_containers(self) -> Dict[str, int]:
        """
        Check all containers for updates.

        Returns:
            Dict with keys: total, checked, updates_found, errors
        """
        logger.info("Starting update check for all containers")

        stats = {
            "total": 0,
            "checked": 0,
            "updates_found": 0,
            "errors": 0,
        }

        # Get global settings
        with self.db.get_session() as session:
            settings = session.query(GlobalSettings).first()
            skip_compose = settings.skip_compose_containers if settings else True

        # Get all containers
        containers = await self._get_all_containers()
        stats["total"] = len(containers)

        logger.info(f"Found {len(containers)} containers to check")

        # Load ignore patterns once before the loop
        ignore_patterns = self._get_ignore_patterns()

        # Check each container
        for container in containers:
            try:
                # Skip compose containers if configured
                if skip_compose and self._is_compose_container(container):
                    logger.debug(f"Skipping compose container: {container['name']}")
                    continue

                # Skip containers matching ignore patterns (Issue #85)
                if self._matches_ignore_pattern(container, ignore_patterns):
                    logger.debug(f"Skipping ignored container: {container['name']}")
                    continue

                # Check for update
                update_info = await self._check_container_update(container)

                if update_info:
                    # Capture old digest BEFORE updating database
                    previous_digest = self._get_previous_digest(container)

                    # Store in database
                    self._store_update_info(container, update_info)
                    stats["checked"] += 1

                    if update_info["update_available"]:
                        stats["updates_found"] += 1
                        logger.info(f"Update available for {container['name']}: {update_info['current_digest'][:12]} → {update_info['latest_digest'][:12]}")

                        # Create event for new update (pass previous_digest for proper comparison)
                        await self._create_update_event(container, update_info, previous_digest)

            except Exception as e:
                logger.error(f"Error checking container {container.get('name', 'unknown')}: {e}")
                stats["errors"] += 1

        logger.info(f"Update check complete: {stats}")
        return stats

    async def check_single_container(self, host_id: str, container_id: str, bypass_cache: bool = False) -> Optional[Dict]:
        """
        Check a single container for updates (manual trigger).

        Args:
            host_id: Host UUID
            container_id: Container short ID (12 chars)
            bypass_cache: If True, skip cache lookup and query registry directly.
                         Default True for manual checks (Issue #101).

        Returns:
            Dict with update info or None if check failed
        """
        logger.info(f"Checking container {container_id} on host {host_id} (bypass_cache={bypass_cache})")

        # Get container info
        container = await self._get_container_async(host_id, container_id)
        if not container:
            logger.error(f"Container not found: {container_id} on {host_id}")
            return None

        # Check for update
        update_info = await self._check_container_update(container, bypass_cache=bypass_cache)

        if update_info:
            # Capture old digest BEFORE updating database
            previous_digest = self._get_previous_digest(container)

            # Store in database
            self._store_update_info(container, update_info)

            if update_info["update_available"]:
                logger.info(f"Update available for {container['name']}")
                # Create event (pass previous_digest for proper comparison)
                await self._create_update_event(container, update_info, previous_digest)
            else:
                logger.info(f"No update available for {container['name']}")

            return update_info

        return None

    async def _check_container_update(self, container: Dict, bypass_cache: bool = False) -> Optional[Dict]:
        """
        Check if update is available for a container.

        Args:
            container: Dict with keys: host_id, id, name, image, image_id, etc.
            bypass_cache: If True, skip cache lookup and query registry directly.
                         Use for manual single-container checks (Issue #101).

        Returns:
            Dict with update info or None if check failed
        """
        image = container.get("image")
        if not image:
            logger.warning(f"Container {container['name']} has no image info")
            return None

        # Get or create container_update record to get tracking mode
        # DEFENSIVE: Normalize container ID (agents may send 64-char IDs)
        container_id = normalize_container_id(container['id'])
        composite_key = make_composite_key(container['host_id'], container_id)
        tracking_mode = self._get_tracking_mode(composite_key)

        # Compute floating tag based on tracking mode
        floating_tag = self.registry.compute_floating_tag(image, tracking_mode)

        logger.info(f"[{container['name']}] Checking {image} with mode '{tracking_mode}' → tracking {floating_tag}")

        # Look up registry credentials for this image
        auth = self._get_registry_credentials(image)
        if auth:
            logger.debug(f"Using credentials for {container['name']}")

        # Get current digest from Docker API (the actual digest the container is running)
        current_digest = await self._get_container_image_digest(container)
        if not current_digest:
            # Fallback for digest-pinned images (Issue #143)
            # Images pulled by digest (e.g., image@sha256:...) don't have RepoDigests.
            # Query registry for the current image tag's digest instead.
            current_image = container.get("image")
            if current_image and '@' not in current_image:
                # Not a digest reference (image@sha256:...) - query registry
                # Images without explicit tag default to :latest
                logger.info(f"[{container['name']}] No local digest available, querying registry for {current_image}")
                try:
                    current_result = await self.registry.resolve_tag(current_image, auth=auth)
                    if current_result:
                        current_digest = current_result["digest"]
                        logger.info(f"[{container['name']}] Got current digest from registry: {current_digest[:16]}...")
                except Exception as e:
                    logger.warning(f"[{container['name']}] Registry fallback failed: {e}")

        if not current_digest:
            logger.warning(f"Could not get current digest for {container['name']}")
            return None

        # Get current version from local Docker image
        current_version = await self._get_container_image_version(container)

        # Build cache key for this image:tag:platform combination
        platform = container.get("platform", "linux/amd64")
        cache_key = f"{floating_tag}:{platform}"

        # Check database cache first (Issue #62: rate limit mitigation)
        # Skip cache if bypass_cache=True (Issue #101: manual checks should get fresh data)
        cached_result = None
        if not bypass_cache:
            try:
                cached_result = self.db.get_cached_image_digest(cache_key)
            except Exception as e:
                logger.warning(f"Failed to check image cache: {e}")
        else:
            logger.info(f"[{container['name']}] Bypassing cache (manual check)")

        if cached_result:
            # Cache hit - use cached data
            logger.info(f"[{container['name']}] Cache hit for {floating_tag}")
            latest_digest = cached_result["digest"]
            registry_url = cached_result["registry_url"]

            # Parse cached manifest for labels
            latest_manifest_labels = {}
            if cached_result.get("manifest_json"):
                try:
                    manifest_data = json.loads(cached_result["manifest_json"])
                    latest_manifest_labels = manifest_data.get("config", {}).get("config", {}).get("Labels", {}) or {}
                except json.JSONDecodeError:
                    pass
        else:
            # Cache miss - call registry
            latest_result = await self.registry.resolve_tag(floating_tag, auth=auth)
            if not latest_result:
                logger.warning(f"Could not resolve floating tag: {floating_tag}")
                return None

            latest_digest = latest_result["digest"]
            registry_url = latest_result["registry"]

            # Extract manifest labels
            latest_manifest_labels = latest_result.get("manifest", {}).get("config", {}).get("config", {}).get("Labels", {}) or {}

            # Store in cache for future lookups
            try:
                ttl_seconds = self._compute_cache_ttl_seconds(floating_tag)
                manifest_json = json.dumps(latest_result.get("manifest", {}))
                self.db.cache_image_digest(
                    cache_key=cache_key,
                    digest=latest_digest,
                    manifest_json=manifest_json,
                    registry_url=registry_url,
                    ttl_seconds=ttl_seconds
                )
                logger.debug(f"Cached {floating_tag} with TTL {ttl_seconds}s")
            except Exception as e:
                logger.warning(f"Failed to cache image digest: {e}")

        # Compare digests - Issue #105: check if latest_digest is in ANY local RepoDigest
        # This handles the case where the same image ID has multiple manifest digests
        # (e.g., after registry re-signing or manifest list updates)
        if self._has_digest(container, latest_digest):
            # Latest digest already present locally (handles multi-digest case)
            update_available = False
            logger.debug(f"[{container['name']}] Latest digest found in local RepoDigests - no update needed")
        else:
            # Fall back to simple comparison (handles case where repo_digests not available)
            update_available = current_digest != latest_digest

        logger.info(f"[{container['name']}] Digest comparison: current={current_digest[:16]}... latest={latest_digest[:16]}... update_available={update_available}")

        # Resolve changelog URL (v2.0.1+)
        # Get existing record to check if re-resolution needed
        existing_record = None
        with self.db.get_session() as session:
            existing_record = session.query(ContainerUpdate).filter_by(
                container_id=composite_key
            ).first()

        # Extract latest version from OCI labels
        latest_version = latest_manifest_labels.get("org.opencontainers.image.version")

        # Fallback to image tag when OCI version label is missing (Issue #178)
        if not current_version:
            current_version = self._extract_version_from_tag(image)
        if not latest_version:
            latest_version = self._extract_version_from_tag(floating_tag)

        if current_version or latest_version:
            logger.debug(f"Version info: current={current_version}, latest={latest_version}")

        # Issue #147: Suppress false positive updates (downgrades)
        # Some registries (e.g., Nextcloud) don't maintain floating tags - their "32.0" tag
        # is a fixed old release, not "latest 32.0.x". Compare versions to catch this.
        if update_available:
            # Try OCI labels first, fall back to parsing from tag
            current_ver = self._parse_version_from_tag(current_version or image)
            latest_ver = self._parse_version_from_tag(latest_version or floating_tag)

            # Debug logging when version parsing fails (helps diagnose missing downgrade protection)
            if not current_ver:
                logger.debug(f"[{container['name']}] Could not parse current version from {current_version or image}")
            if not latest_ver:
                logger.debug(f"[{container['name']}] Could not parse latest version from {latest_version or floating_tag}")

            if current_ver and latest_ver and self._is_downgrade(current_ver, latest_ver):
                update_available = False
                logger.info(f"[{container['name']}] Suppressing update: {floating_tag} version {latest_ver} is not newer than current {current_ver}")

        # Check if user has manually set a changelog URL (v2.0.2+)
        # If manual, skip auto-detection to preserve user's choice
        if existing_record and existing_record.changelog_source == 'manual':
            changelog_url = existing_record.changelog_url
            changelog_source = 'manual'
            changelog_checked_at = existing_record.changelog_checked_at
        else:
            # Resolve changelog URL with 3-tier strategy
            changelog_url, changelog_source, changelog_checked_at = await resolve_changelog_url(
                image_name=floating_tag,
                manifest_labels=latest_manifest_labels,
                current_url=existing_record.changelog_url if existing_record else None,
                current_source=existing_record.changelog_source if existing_record else None,
                last_checked=existing_record.changelog_checked_at if existing_record else None
            )

        return {
            "current_image": image,
            "current_digest": current_digest,
            "latest_image": floating_tag,
            "latest_digest": latest_digest,
            "update_available": update_available,
            "registry_url": registry_url,
            "platform": platform,
            "floating_tag_mode": tracking_mode,
            "current_version": current_version,
            "latest_version": latest_version,
            "changelog_url": changelog_url,
            "changelog_source": changelog_source,
            "changelog_checked_at": changelog_checked_at,
        }

    def _extract_digest_from_repo_digests(self, repo_digests: List[str]) -> Optional[str]:
        """Extract sha256 digest from RepoDigests list.

        Args:
            repo_digests: List like ["ghcr.io/org/app@sha256:abc123..."]

        Returns:
            Digest string like "sha256:abc123..." or None
        """
        for repo_digest in repo_digests:
            if "@sha256:" in repo_digest:
                return repo_digest.split("@", 1)[1]
        return None

    def _has_digest(self, container: Dict, digest: str) -> bool:
        """
        Check if container's image already has a specific digest in RepoDigests.

        Issue #105: Images can have multiple manifest digests pointing to the same
        image ID (e.g., after registry re-signing). This method checks if ANY of
        the local RepoDigests contains the specified digest.

        Args:
            container: Container dict with optional 'repo_digests' key
            digest: The digest to search for (e.g., "sha256:abc123...")

        Returns:
            True if digest is found in any RepoDigest entry, False otherwise
        """
        repo_digests = container.get("repo_digests")
        if not repo_digests or not isinstance(repo_digests, list):
            return False

        # Defensive: ensure digest is a valid string
        if not digest or not isinstance(digest, str):
            return False

        search_pattern = f"@{digest}"
        for repo_digest in repo_digests:
            # Defensive: skip non-string elements
            if isinstance(repo_digest, str) and search_pattern in repo_digest:
                return True

        return False

    def _extract_version_from_tag(self, image_ref: str) -> Optional[str]:
        """
        Extract version string from an image reference tag.

        Used as fallback when OCI version label is missing.
        Returns the version portion only (e.g., "nginx:1.25.3-alpine" -> "1.25.3").
        Returns None for non-version tags like "latest", "stable", "edge".
        """
        if not image_ref or ":" not in image_ref:
            return None
        tag = image_ref.rsplit(":", 1)[1]
        version_match = re.match(r"v?(\d+(?:\.\d+)+)", tag)
        return version_match.group(1) if version_match else None

    def _parse_version_from_tag(self, tag: str) -> Optional[Tuple[int, int, int]]:
        """
        Parse version tuple from an image tag or full image reference.

        Extracts semantic version components from tags like:
        - "32.0.3-fpm-alpine" → (32, 0, 3)
        - "1.25.3" → (1, 25, 3)
        - "v2.1.0" → (2, 1, 0)
        - "1.25" → (1, 25, 0)  # Missing patch treated as 0
        - "nginx:1.25.3-alpine" → (1, 25, 3)  # Full image reference

        Args:
            tag: Image tag string, may include:
                - Suffix like -alpine, -fpm (ignored after version)
                - Full image reference with colon (tag extracted)

        Returns:
            Tuple of (major, minor, patch) or None if not parseable
        """
        if not tag:
            return None

        # Extract just the tag portion if full image reference
        if ":" in tag:
            tag = tag.rsplit(":", 1)[1]

        # Match semver patterns: 1.25.3, v2.1.0, 32.0.3-fpm-alpine, etc.
        version_match = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", tag)
        if not version_match:
            return None

        major, minor, patch = version_match.groups()
        return (
            int(major),
            int(minor) if minor else 0,
            int(patch) if patch else 0,
        )

    def _is_downgrade(self, current_ver: Tuple[int, int, int], latest_ver: Tuple[int, int, int]) -> bool:
        """
        Check if the "latest" version would actually be a downgrade.

        Note: Returns True only if latest is STRICTLY older than current.
        Same version with different digest is allowed (could be security
        patches in base image or 3rd party library updates).

        Args:
            current_ver: Current version tuple (major, minor, patch)
            latest_ver: Latest version tuple (major, minor, patch)

        Returns:
            True if latest_ver < current_ver (would be downgrade)
        """
        return latest_ver < current_ver

    async def _get_container_image_digest(self, container: Dict) -> Optional[str]:
        """
        Get the actual image digest that the container is running.

        Priority order:
        1. Use stored repo_digests from container discovery (agent hosts, v2.2.0+)
        2. Query Docker API directly (legacy hosts with direct Docker access)

        Args:
            container: Container dict with host_id and id

        Returns:
            sha256 digest string or None if not available
        """
        container_name = container.get("name", "unknown")

        try:
            # PRIORITY 1: Check if we have repo_digests stored from agent discovery (v2.2.0+)
            # This is the only way to get digest info from agent-monitored hosts
            repo_digests = container.get("repo_digests")
            if repo_digests and isinstance(repo_digests, list) and len(repo_digests) > 0:
                digest = self._extract_digest_from_repo_digests(repo_digests)
                if digest:
                    logger.debug(f"[{container_name}] Got container image digest from stored data: {digest[:16]}...")
                    return digest

            # PRIORITY 2: Fall back to Docker API query for legacy hosts
            # (Agent hosts won't have Docker client, so this will fail gracefully)
            if not self.monitor:
                logger.debug(f"[{container_name}] No monitor object available")
                return None

            host_id = container.get("host_id")
            if not host_id:
                logger.warning(f"[{container_name}] No host_id in container dict")
                return None

            # Use the monitor's existing Docker client - it manages TLS certs properly
            client = self.monitor.clients.get(host_id)
            if not client:
                # No Docker client for this host - likely an agent-monitored host
                # This is expected and normal, not a warning
                logger.debug(f"[{container_name}] No Docker client found for host {host_id} (likely agent host)")
                return None

            # Get container and extract digest (use async wrapper to prevent event loop blocking)
            from utils.async_docker import async_docker_call
            logger.debug(f"[{container_name}] Fetching container with ID: {container['id']}")
            dc = await async_docker_call(client.containers.get, container["id"])
            logger.debug(f"[{container_name}] Got container object, fetching image...")
            image = dc.image
            api_repo_digests = image.attrs.get("RepoDigests", [])
            logger.debug(f"[{container_name}] RepoDigests: {api_repo_digests}")

            if api_repo_digests:
                # Store full list for _has_digest to use (Issue #105)
                # This enables multi-digest detection for local/mTLS hosts
                container["repo_digests"] = api_repo_digests
                digest = self._extract_digest_from_repo_digests(api_repo_digests)
                if digest:
                    logger.debug(f"[{container_name}] Got container image digest from Docker API: {digest[:16]}...")
                    return digest

            logger.warning(f"[{container_name}] No RepoDigests found (image may be built locally)")
            return None

        except Exception as e:
            logger.warning(f"[{container_name}] Error getting container image digest: {e}", exc_info=True)
            return None

    async def _get_container_image_version(self, container: Dict) -> Optional[str]:
        """
        Get the OCI version label from the running container's local image.

        This inspects the local Docker image (not the registry) to get the version
        of the image that's actually running.

        Args:
            container: Container dict with host_id and id

        Returns:
            Version string from org.opencontainers.image.version label or None
        """
        if not self.monitor:
            return None

        try:
            # Get Docker client for this host
            host_id = container.get("host_id")
            if not host_id:
                return None

            client = self.monitor.clients.get(host_id)
            if not client:
                return None

            # Get container's image (use async wrapper)
            from utils.async_docker import async_docker_call
            dc = await async_docker_call(client.containers.get, container["id"])
            image = dc.image

            # Extract OCI version label from image config
            labels = image.attrs.get("Config", {}).get("Labels", {}) or {}
            version = labels.get("org.opencontainers.image.version")

            if version:
                logger.debug(f"Got version from local image: {version}")

            return version

        except Exception as e:
            logger.warning(f"Error getting container image version: {e}")
            return None

    async def _get_all_containers(self) -> List[Dict]:
        """
        Get all containers from all hosts via monitor.

        Returns:
            List of container dicts with keys: host_id, id, name, image, etc.
        """
        if not self.monitor:
            logger.error("Monitor not set - cannot fetch containers")
            return []

        try:
            # Get containers from monitor (async)
            containers = await self.monitor.get_containers()
            # Convert to dict format
            return [c.dict() for c in containers]
        except Exception as e:
            logger.error(f"Error fetching containers: {e}", exc_info=True)
            return []

    async def _get_container_async(self, host_id: str, container_id: str) -> Optional[Dict]:
        """
        Get a single container from monitor (async version).

        Args:
            host_id: Host UUID
            container_id: Container short ID (12 chars)

        Returns:
            Container dict or None if not found
        """
        if not self.monitor:
            logger.error("Monitor not set - cannot fetch container")
            return None

        try:
            # Get all containers and find the one we want
            containers = await self.monitor.get_containers()

            # Match by short_id or full id - check with truncation for robustness
            def matches(c):
                if c.host_id != host_id:
                    return False
                # Truncate both IDs to 12 chars for comparison (handles both 12-char and 64-char IDs)
                c_short = c.id[:12] if len(c.id) > 12 else c.id
                c_short_from_field = c.short_id[:12] if len(c.short_id) > 12 else c.short_id
                search_short = container_id[:12] if len(container_id) > 12 else container_id

                return c_short == search_short or c_short_from_field == search_short or c.id == container_id

            container = next((c for c in containers if matches(c)), None)
            return container.dict() if container else None
        except Exception as e:
            logger.error(f"Error fetching container: {e}")
            return None

    def _get_tracking_mode(self, composite_key: str) -> str:
        """
        Get tracking mode for container from database.

        Args:
            composite_key: host_id:container_id

        Returns:
            Tracking mode (exact, patch, minor, latest) - defaults to 'exact'
        """
        with self.db.get_session() as session:
            record = session.query(ContainerUpdate).filter_by(
                container_id=composite_key
            ).first()

            if record:
                return record.floating_tag_mode
            else:
                # Default to exact tracking
                return "exact"

    def _get_previous_digest(self, container: Dict) -> Optional[str]:
        """
        Get the previously stored latest_digest before updating.

        Args:
            container: Container dict with host_id and id

        Returns:
            Previous latest_digest from database, or None if no record exists (first check)
        """
        container_id = normalize_container_id(container['id'])
        composite_key = make_composite_key(container['host_id'], container_id)
        with self.db.get_session() as session:
            record = session.query(ContainerUpdate).filter_by(
                container_id=composite_key
            ).first()
            return record.latest_digest if record else None

    def _store_update_info(self, container: Dict, update_info: Dict):
        """
        Store or update container update info in database.

        Args:
            container: Container dict
            update_info: Update info dict from _check_container_update
        """
        container_id = normalize_container_id(container['id'])
        composite_key = make_composite_key(container['host_id'], container_id)

        with self.db.get_session() as session:
            record = session.query(ContainerUpdate).filter_by(
                container_id=composite_key
            ).first()

            if record:
                # Update existing record
                record.current_image = update_info["current_image"]
                record.current_digest = update_info["current_digest"]
                record.latest_image = update_info["latest_image"]
                record.latest_digest = update_info["latest_digest"]
                record.update_available = update_info["update_available"]
                record.registry_url = update_info["registry_url"]
                record.platform = update_info["platform"]
                record.last_checked_at = datetime.now(timezone.utc)
                record.updated_at = datetime.now(timezone.utc)
                record.current_version = update_info.get("current_version")
                record.latest_version = update_info.get("latest_version")
                record.changelog_url = update_info.get("changelog_url")
                record.changelog_source = update_info.get("changelog_source")
                record.changelog_checked_at = update_info.get("changelog_checked_at")
                # Update container_name if available (for reattachment)
                if container.get("name"):
                    record.container_name = container["name"]
            else:
                # Create new record
                record = ContainerUpdate(
                    container_id=composite_key,
                    host_id=container["host_id"],
                    container_name=container.get("name"),
                    current_image=update_info["current_image"],
                    current_digest=update_info["current_digest"],
                    latest_image=update_info["latest_image"],
                    latest_digest=update_info["latest_digest"],
                    update_available=update_info["update_available"],
                    floating_tag_mode=update_info["floating_tag_mode"],
                    registry_url=update_info["registry_url"],
                    platform=update_info["platform"],
                    last_checked_at=datetime.now(timezone.utc),
                    current_version=update_info.get("current_version"),
                    latest_version=update_info.get("latest_version"),
                    changelog_url=update_info.get("changelog_url"),
                    changelog_source=update_info.get("changelog_source"),
                    changelog_checked_at=update_info.get("changelog_checked_at"),
                )
                session.add(record)

            try:
                session.commit()
            except IntegrityError:
                # Race condition: Another check created the record between our query and insert
                # This is extremely rare (single-process async + SQLite locking), but handle it properly
                session.rollback()
                logger.debug(f"Concurrent insert detected for {composite_key}, updating with our data")

                # Re-query for the record that was created concurrently
                record = session.query(ContainerUpdate).filter_by(
                    container_id=composite_key
                ).first()

                if record:
                    # NOTE: Inline duplication of update logic (exception to DRY principle)
                    # Extracting to method adds unnecessary abstraction for extremely rare code path
                    record.current_image = update_info["current_image"]
                    record.current_digest = update_info["current_digest"]
                    record.latest_image = update_info["latest_image"]
                    record.latest_digest = update_info["latest_digest"]
                    record.update_available = update_info["update_available"]
                    record.registry_url = update_info["registry_url"]
                    record.platform = update_info["platform"]
                    record.last_checked_at = datetime.now(timezone.utc)
                    record.updated_at = datetime.now(timezone.utc)
                    record.current_version = update_info.get("current_version")
                    record.latest_version = update_info.get("latest_version")
                    record.changelog_url = update_info.get("changelog_url")
                    record.changelog_source = update_info.get("changelog_source")
                    record.changelog_checked_at = update_info.get("changelog_checked_at")
                    # Update container_name if available (for reattachment)
                    if container.get("name"):
                        record.container_name = container["name"]
                    session.commit()
                else:
                    # Record vanished between operations - extremely unlikely
                    logger.warning(f"Record vanished during race condition handling for {composite_key}")
                    raise

    async def _create_update_event(
        self,
        container: Dict,
        update_info: Dict,
        previous_digest: Optional[str] = None
    ):
        """
        Emit update_available event via EventBus.

        Only emits if this is a NEW update (digest changed from previous check).

        Args:
            container: Container dict
            update_info: Update info dict
            previous_digest: Previously stored latest_digest, or None if first check
        """
        # Determine if event should be emitted by comparing previous vs new digest
        should_emit_event = False

        if previous_digest is None:
            # First time checking this container - emit event
            should_emit_event = True
        elif previous_digest != update_info["latest_digest"]:
            # Digest changed (new update available) - emit event
            should_emit_event = True

        # Emit event if conditions met
        if should_emit_event:
            try:
                logger.info(f"New update available for {container['name']}: {update_info['latest_image']}")

                # Get host name
                host_name = self.monitor.hosts.get(container["host_id"]).name if container["host_id"] in self.monitor.hosts else container["host_id"]

                # Emit event via EventBus - it handles database logging and alert triggering
                event_bus = get_event_bus(self.monitor)
                # DEFENSIVE: Normalize container ID (agents may send 64-char IDs)
                container_id = normalize_container_id(container["id"])
                await event_bus.emit(Event(
                    event_type=EventType.UPDATE_AVAILABLE,
                    scope_type='container',
                    scope_id=make_composite_key(container["host_id"], container_id),
                    scope_name=container["name"],
                    host_id=container["host_id"],
                    host_name=host_name,
                    data={
                        'current_image': update_info['current_image'],
                        'latest_image': update_info['latest_image'],
                        'current_digest': update_info['current_digest'],
                        'latest_digest': update_info['latest_digest'],
                        'current_version': update_info.get('current_version'),
                        'latest_version': update_info.get('latest_version'),
                        'changelog_url': update_info.get('changelog_url'),
                        'update_detected': True,  # For alert engine
                    }
                ))

                logger.debug(f"Emitted UPDATE_AVAILABLE event for {container['name']}")

            except Exception as e:
                logger.error(f"Could not emit update event: {e}", exc_info=True)

    def _is_compose_container(self, container: Dict) -> bool:
        """
        Check if container is managed by Docker Compose.

        Args:
            container: Container dict

        Returns:
            True if container has compose labels
        """
        labels = container.get("labels", {})
        return any(
            label.startswith("com.docker.compose")
            for label in labels.keys()
        )

    def _get_ignore_patterns(self) -> List[str]:
        """
        Get list of patterns with action='ignore' for skipping update checks.

        Returns:
            List of pattern strings to match against container/image names
        """
        with self.db.get_session() as session:
            patterns = session.query(UpdatePolicy).filter_by(
                enabled=True,
                action='ignore'
            ).all()
            return [p.pattern.lower() for p in patterns]

    def _matches_ignore_pattern(self, container: Dict, ignore_patterns: List[str]) -> bool:
        """
        Check if container matches any ignore pattern.

        Args:
            container: Container dict with 'name' and 'image' keys
            ignore_patterns: List of pattern strings (lowercase)

        Returns:
            True if container name or image matches any ignore pattern
        """
        if not ignore_patterns:
            return False

        container_name = container.get('name', '').lower()
        image_name = container.get('image', '').lower()

        for pattern in ignore_patterns:
            if pattern in container_name or pattern in image_name:
                return True

        return False


# Global singleton instance
_update_checker = None


def get_update_checker(db: DatabaseManager = None, monitor=None) -> UpdateChecker:
    """Get or create global UpdateChecker instance"""
    global _update_checker
    if _update_checker is None:
        if db is None:
            db = DatabaseManager('/app/data/dockmon.db')
        _update_checker = UpdateChecker(db, monitor)
    # Update monitor if provided (in case it wasn't available on first creation)
    if monitor and _update_checker.monitor is None:
        _update_checker.monitor = monitor
    return _update_checker
