"""
Container Dependency Conflict Detection

Analyzes update batches to prevent catastrophic failures when updating
containers with network dependencies simultaneously.
"""

import logging
from typing import List, Optional, Dict
from utils.keys import parse_composite_key

logger = logging.getLogger(__name__)


class DependencyConflictDetector:
    """
    Detects container dependency conflicts in update batches.

    When a container uses network_mode: container:X, it shares the network
    namespace with container X (the "provider"). If both containers are
    updated simultaneously:

    1. Provider updates, gets new container ID
    2. Provider tries to recreate dependent (points to new ID)
    3. Dependent's own update is running in parallel
    4. Both try to recreate the same container → catastrophic collision

    This detector prevents that scenario by failing fast with a clear error.
    """

    def __init__(self, monitor):
        """
        Initialize detector.

        Args:
            monitor: DockerMonitor instance (for accessing Docker clients)
        """
        self.monitor = monitor

    def check_batch(
        self,
        container_ids: List[str],
        container_map: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Check if update batch contains network provider + dependent.

        Args:
            container_ids: List of container composite keys (host_id:container_id)
            container_map: Optional pre-built map of {composite_key: container}
                          If not provided, will fetch containers from monitor

        Returns:
            Error message if conflict detected, None otherwise
        """
        logger.info(f"DependencyConflictDetector.check_batch called with {len(container_ids)} containers: {container_ids}")
        if len(container_ids) < 2:
            logger.info("Batch has less than 2 containers, skipping dependency check")
            return None

        # Build container map if not provided
        if container_map is None:
            container_map = self._build_container_map(container_ids)

        # Check each container for network_mode dependencies
        for container_id in container_ids:
            container = container_map.get(container_id)
            if not container:
                continue

            # Check if this container depends on another in the batch
            conflict = self._check_network_dependency(
                container,
                container_id,
                container_ids,
                container_map
            )
            if conflict:
                return conflict

        return None

    def _build_container_map(self, container_ids: List[str]) -> Dict:
        """Build map of container composite keys to container objects."""
        container_map = {}

        try:
            # Get all containers from monitor
            import asyncio
            containers = asyncio.run(self.monitor.get_containers())

            # Build map using composite keys
            for c in containers:
                composite_key = f"{c.host_id}:{c.short_id}"
                if composite_key in container_ids:
                    container_map[composite_key] = c
        except Exception as e:
            logger.error(f"Error building container map: {e}")

        return container_map

    def _check_network_dependency(
        self,
        container,
        container_id: str,
        container_ids: List[str],
        container_map: Dict
    ) -> Optional[str]:
        """
        Check if container has network dependency on another container in batch.

        Returns:
            Error message if dependency conflict found, None otherwise
        """
        try:
            # Get Docker client for this container's host
            client = self.monitor.clients.get(container.host_id) if self.monitor else None
            if not client:
                logger.warning(f"No Docker client found for host {container.host_id}")
                return None

            # Get container's network_mode from Docker
            logger.info(f"Checking container {container.name} ({container.short_id}) for network dependencies")
            dc = client.containers.get(container.short_id)
            network_mode = dc.attrs.get('HostConfig', {}).get('NetworkMode', '')
            logger.info(f"Container {container.name} has network_mode: {network_mode}")

            # Check if using container: network mode
            if not network_mode.startswith('container:'):
                logger.info(f"Container {container.name} does not use container network mode, skipping")
                return None

            # Extract provider container reference
            provider_ref = network_mode[10:]  # Remove 'container:' prefix
            logger.info(f"Container {container.name} depends on provider: {provider_ref}")

            # Check if provider is also in the update batch
            provider_container = self._find_provider_in_batch(
                provider_ref,
                container.host_id,
                container_ids,
                container_map
            )

            if provider_container:
                conflict_msg = (
                    f"Cannot update containers with network dependencies simultaneously. "
                    f"Container '{container.name}' depends on '{provider_container.name}' for networking. "
                    f"Please update '{provider_container.name}' first - '{container.name}' will be "
                    f"automatically recreated with the new network connection."
                )
                logger.error(f"DEPENDENCY CONFLICT DETECTED: {conflict_msg}")
                return conflict_msg
            else:
                logger.info(f"Provider {provider_ref} not found in batch, no conflict")

        except Exception as e:
            logger.error(f"Error checking dependencies for {container_id}: {e}", exc_info=True)

        return None

    def _find_provider_in_batch(
        self,
        provider_ref: str,
        host_id: str,
        container_ids: List[str],
        container_map: Dict
    ):
        """
        Find provider container in the batch.

        Args:
            provider_ref: Provider container name or ID from network_mode
            host_id: Host ID to match (dependencies are host-specific)
            container_ids: List of container IDs in batch
            container_map: Map of container IDs to container objects

        Returns:
            Container object if provider found in batch, None otherwise
        """
        for other_id in container_ids:
            other_container = container_map.get(other_id)
            if not other_container:
                continue

            # Must be on same host
            if other_container.host_id != host_id:
                continue

            # Check if this matches the provider reference
            # Provider can be referenced by name, short ID, or full ID
            # Also check if provider_ref (possibly full 64-char ID) starts with short_id
            if provider_ref in [other_container.name, other_container.short_id, other_container.id]:
                return other_container
            # Check if provider_ref is a full ID that starts with this container's short ID
            if provider_ref.startswith(other_container.short_id):
                logger.info(f"Matched provider {provider_ref[:12]}... (full ID) to container {other_container.name} ({other_container.short_id})")
                return other_container

        return None
