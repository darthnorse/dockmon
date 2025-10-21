"""
Update Checker Service

Background task that periodically checks all containers for available updates.
Runs daily by default, configurable via global settings.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from database import DatabaseManager, ContainerUpdate, GlobalSettings, RegistryCredential
from updates.registry_adapter import get_registry_adapter
from event_bus import Event, EventType, get_event_bus
from utils.keys import make_composite_key
from utils.encryption import decrypt_password

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
        """
        Get credentials for registry from image name.

        Extracts registry URL from image and looks up stored credentials.

        Args:
            image_name: Full image reference (e.g., "nginx:1.25", "ghcr.io/user/app:latest")

        Returns:
            Dict with {username, password} if credentials found, None otherwise

        Examples:
            nginx:1.25 → docker.io → lookup credentials for "docker.io"
            ghcr.io/user/app:latest → ghcr.io → lookup credentials for "ghcr.io"
            registry.example.com:5000/app:v1 → registry.example.com:5000 → lookup
        """
        try:
            # Extract registry URL using same logic as registry_adapter
            registry_url = "docker.io"  # Default

            # Check for explicit registry
            if "/" in image_name:
                parts = image_name.split("/", 1)
                # If first part has dot or colon, it's likely a registry
                if "." in parts[0] or ":" in parts[0]:
                    registry_url = parts[0]

            # Normalize (lowercase)
            registry_url = registry_url.lower()

            # Query database for credentials
            with self.db.get_session() as session:
                cred = session.query(RegistryCredential).filter_by(
                    registry_url=registry_url
                ).first()

                if cred:
                    try:
                        plaintext = decrypt_password(cred.password_encrypted)
                        logger.debug(f"Using credentials for registry '{registry_url}'")
                        return {
                            "username": cred.username,
                            "password": plaintext
                        }
                    except Exception as e:
                        logger.error(f"Failed to decrypt credentials for {registry_url}: {e}")
                        return None

                # No credentials found
                return None

        except Exception as e:
            logger.error(f"Error looking up credentials for {image_name}: {e}")
            return None

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

        # Check each container
        for container in containers:
            try:
                # Skip compose containers if configured
                if skip_compose and self._is_compose_container(container):
                    logger.debug(f"Skipping compose container: {container['name']}")
                    continue

                # Check for update
                update_info = await self._check_container_update(container)

                if update_info:
                    # Store in database
                    self._store_update_info(container, update_info)
                    stats["checked"] += 1

                    if update_info["update_available"]:
                        stats["updates_found"] += 1
                        logger.info(f"Update available for {container['name']}: {update_info['current_digest'][:12]} → {update_info['latest_digest'][:12]}")

                        # Create event for new update
                        await self._create_update_event(container, update_info)

            except Exception as e:
                logger.error(f"Error checking container {container.get('name', 'unknown')}: {e}")
                stats["errors"] += 1

        logger.info(f"Update check complete: {stats}")
        return stats

    async def check_single_container(self, host_id: str, container_id: str) -> Optional[Dict]:
        """
        Check a single container for updates (manual trigger).

        Args:
            host_id: Host UUID
            container_id: Container short ID (12 chars)

        Returns:
            Dict with update info or None if check failed
        """
        logger.info(f"Checking container {container_id} on host {host_id}")

        # Get container info
        container = await self._get_container_async(host_id, container_id)
        if not container:
            logger.error(f"Container not found: {container_id} on {host_id}")
            return None

        # Check for update
        update_info = await self._check_container_update(container)

        if update_info:
            # Store in database
            self._store_update_info(container, update_info)

            if update_info["update_available"]:
                logger.info(f"Update available for {container['name']}")
                # Create event
                await self._create_update_event(container, update_info)
            else:
                logger.info(f"No update available for {container['name']}")

            return update_info

        return None

    async def _check_container_update(self, container: Dict) -> Optional[Dict]:
        """
        Check if update is available for a container.

        Args:
            container: Dict with keys: host_id, id, name, image, image_id, etc.

        Returns:
            Dict with update info or None if check failed
        """
        image = container.get("image")
        if not image:
            logger.warning(f"Container {container['name']} has no image info")
            return None

        # Get or create container_update record to get tracking mode
        composite_key = make_composite_key(container['host_id'], container['id'])
        tracking_mode = self._get_tracking_mode(composite_key)

        # Compute floating tag based on tracking mode
        floating_tag = self.registry.compute_floating_tag(image, tracking_mode)

        logger.debug(f"Checking {image} with mode '{tracking_mode}' → tracking {floating_tag}")

        # Look up registry credentials for this image
        auth = self._get_registry_credentials(image)
        if auth:
            logger.debug(f"Using credentials for {container['name']}")

        # Get current digest from Docker API (the actual digest the container is running)
        current_digest = await self._get_container_image_digest(container)
        if not current_digest:
            logger.warning(f"Could not get current digest for {container['name']}, falling back to registry query")
            # Fallback: query registry for current image tag (less accurate for :latest tags)
            current_result = await self.registry.resolve_tag(image, auth=auth)
            if not current_result:
                logger.warning(f"Could not resolve current image: {image}")
                return None
            current_digest = current_result["digest"]

        # Resolve floating tag to digest (what's available in registry)
        latest_result = await self.registry.resolve_tag(floating_tag, auth=auth)
        if not latest_result:
            logger.warning(f"Could not resolve floating tag: {floating_tag}")
            return None

        # Compare digests
        latest_digest = latest_result["digest"]
        update_available = current_digest != latest_digest

        logger.debug(f"Digest comparison: current={current_digest[:16]}... latest={latest_digest[:16]}... update={update_available}")

        return {
            "current_image": image,
            "current_digest": current_digest,
            "latest_image": floating_tag,
            "latest_digest": latest_digest,
            "update_available": update_available,
            "registry_url": latest_result["registry"],
            "platform": container.get("platform", "linux/amd64"),
            "floating_tag_mode": tracking_mode,
        }

    async def _get_container_image_digest(self, container: Dict) -> Optional[str]:
        """
        Get the actual image digest that the container is running.

        This queries the Docker API to get the RepoDigest of the image,
        which is the sha256 digest the image was pulled with.

        Args:
            container: Container dict with host_id and id

        Returns:
            sha256 digest string or None if not available
        """
        if not self.monitor:
            return None

        try:
            # Get Docker client for this host from the monitor's client pool
            host_id = container.get("host_id")
            if not host_id:
                return None

            if not self.monitor:
                return None

            # Use the monitor's existing Docker client - it manages TLS certs properly
            client = self.monitor.clients.get(host_id)
            if not client:
                logger.debug(f"No Docker client found for host {host_id}")
                return None

            # Get container and extract digest (use async wrapper to prevent event loop blocking)
            from utils.async_docker import async_docker_call
            dc = await async_docker_call(client.containers.get, container["id"])
            image = dc.image
            repo_digests = image.attrs.get("RepoDigests", [])

            if repo_digests:
                # RepoDigests is a list like ["ghcr.io/org/app@sha256:abc123..."]
                # Extract the digest part
                for repo_digest in repo_digests:
                    if "@sha256:" in repo_digest:
                        digest = repo_digest.split("@", 1)[1]
                        logger.debug(f"Got container image digest from Docker API: {digest[:16]}...")
                        return digest

            logger.debug(f"No RepoDigests found for container {container['name']}, image may have been built locally")
            return None

        except Exception as e:
            logger.warning(f"Error getting container image digest: {e}")
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
            container = next((c for c in containers if c.id == container_id and c.host_id == host_id), None)
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
            Tracking mode (exact, minor, major, latest) - defaults to 'exact'
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

    def _store_update_info(self, container: Dict, update_info: Dict):
        """
        Store or update container update info in database.

        Args:
            container: Container dict
            update_info: Update info dict from _check_container_update
        """
        composite_key = make_composite_key(container['host_id'], container['id'])

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
            else:
                # Create new record
                record = ContainerUpdate(
                    container_id=composite_key,
                    host_id=container["host_id"],
                    current_image=update_info["current_image"],
                    current_digest=update_info["current_digest"],
                    latest_image=update_info["latest_image"],
                    latest_digest=update_info["latest_digest"],
                    update_available=update_info["update_available"],
                    floating_tag_mode=update_info["floating_tag_mode"],
                    registry_url=update_info["registry_url"],
                    platform=update_info["platform"],
                    last_checked_at=datetime.now(timezone.utc),
                )
                session.add(record)

            session.commit()

    async def _create_update_event(self, container: Dict, update_info: Dict):
        """
        Emit update_available event via EventBus.

        Only emits if this is a NEW update (not already in DB).

        Args:
            container: Container dict
            update_info: Update info dict
        """
        composite_key = make_composite_key(container['host_id'], container['id'])

        # Check if we already created an event for this update
        # Extract data and close session BEFORE async event emission
        should_emit_event = False
        existing_digest = None

        with self.db.get_session() as session:
            record = session.query(ContainerUpdate).filter_by(
                container_id=composite_key
            ).first()

            # Only create event if:
            # 1. No record exists (first time seeing update), OR
            # 2. Record exists but digest changed (new update available)
            if not record:
                should_emit_event = True
            elif record.latest_digest != update_info["latest_digest"]:
                should_emit_event = True
                existing_digest = record.latest_digest

        # Session is now closed - safe to emit events
        if should_emit_event:
            try:
                logger.info(f"New update available for {container['name']}: {update_info['latest_image']}")

                # Get host name
                host_name = self.monitor.hosts.get(container["host_id"]).name if container["host_id"] in self.monitor.hosts else container["host_id"]

                # Emit event via EventBus - it handles database logging and alert triggering
                event_bus = get_event_bus(self.monitor)
                await event_bus.emit(Event(
                    event_type=EventType.UPDATE_AVAILABLE,
                    scope_type='container',
                    scope_id=container["id"],
                    scope_name=container["name"],
                    host_id=container["host_id"],
                    host_name=host_name,
                    data={
                        'current_image': update_info['current_image'],
                        'latest_image': update_info['latest_image'],
                        'current_digest': update_info['current_digest'],
                        'latest_digest': update_info['latest_digest'],
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
