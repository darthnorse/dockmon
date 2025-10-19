"""
Stats Collection Manager for DockMon
Centralized logic for determining which containers need stats collection
"""

import asyncio
import logging
from typing import Set, List
from models.docker_models import Container
from database import GlobalSettings

logger = logging.getLogger(__name__)


class StatsManager:
    """Manages stats collection decisions based on settings and modal state"""

    def __init__(self):
        """Initialize stats manager"""
        self.streaming_containers: Set[str] = set()  # Currently streaming container keys (host_id:container_id)
        self.modal_containers: Set[str] = set()  # Composite keys (host_id:container_id) with open modals
        self._streaming_lock = asyncio.Lock()  # Protect streaming_containers set from race conditions

    def add_modal_container(self, container_id: str, host_id: str) -> None:
        """Track that a container modal is open"""
        composite_key = f"{host_id}:{container_id}"
        self.modal_containers.add(composite_key)
        logger.debug(f"Container modal opened for {container_id[:12]} on host {host_id[:8]} - stats tracking enabled")

    def remove_modal_container(self, container_id: str, host_id: str) -> None:
        """Remove container from modal tracking"""
        composite_key = f"{host_id}:{container_id}"
        self.modal_containers.discard(composite_key)
        logger.debug(f"Container modal closed for {container_id[:12]} on host {host_id[:8]}")

    def clear_modal_containers(self) -> None:
        """Clear all modal containers (e.g., on WebSocket disconnect)"""
        if self.modal_containers:
            logger.debug(f"Clearing {len(self.modal_containers)} modal containers")
        self.modal_containers.clear()

    def determine_containers_needing_stats(
        self,
        containers: List[Container],
        settings: GlobalSettings
    ) -> Set[str]:
        """
        Centralized decision: determine which containers need stats collection

        Rules:
        1. If show_container_stats OR show_host_stats is ON → collect ALL running containers
           (host stats are aggregated from container stats)
        2. Always collect stats for containers with open modals

        Args:
            containers: List of all containers
            settings: Global settings with show_container_stats and show_host_stats flags

        Returns:
            Set of composite keys (host_id:container_id) that need stats collection
        """
        containers_needing_stats = set()

        # Rule 1: Container stats OR host stats enabled = ALL running containers
        # (host stats need container data for aggregation)
        if settings.show_container_stats or settings.show_host_stats:
            for container in containers:
                if container.status == 'running':
                    # Use short_id for consistency
                    containers_needing_stats.add(f"{container.host_id}:{container.short_id}")

        # Rule 2: Always add modal containers (even if settings are off)
        # Modal containers are already stored as composite keys
        for modal_composite_key in self.modal_containers:
            # Verify container is still running before adding
            for container in containers:
                # Use short_id for consistency
                container_key = f"{container.host_id}:{container.short_id}"
                if container_key == modal_composite_key and container.status == 'running':
                    containers_needing_stats.add(container_key)
                    break

        return containers_needing_stats

    async def sync_container_streams(
        self,
        containers: List[Container],
        containers_needing_stats: Set[str],
        stats_client,
        error_callback
    ) -> None:
        """
        Synchronize container stats streams with what's needed

        Starts streams for containers that need stats but aren't streaming yet
        Stops streams for containers that no longer need stats

        Args:
            containers: List of all containers
            containers_needing_stats: Set of composite keys (host_id:container_id) that need stats
            stats_client: Stats client instance
            error_callback: Callback for handling async task errors
        """
        async with self._streaming_lock:
            # Start streams for containers that need stats but aren't streaming yet
            for container in containers:
                # Use short_id for consistency
                container_key = f"{container.host_id}:{container.short_id}"
                if container_key in containers_needing_stats and container_key not in self.streaming_containers:
                    # Await the start request to verify it succeeded before marking as streaming
                    success = await stats_client.start_container_stream(
                        container.short_id,  # Docker API accepts short IDs
                        container.name,
                        container.host_id
                    )
                    # Only mark as streaming if the request succeeded
                    if success:
                        self.streaming_containers.add(container_key)
                        logger.debug(f"Started stats stream for {container.name} on {container.host_name}")
                    else:
                        logger.warning(f"Failed to start stats stream for {container.name} on {container.host_name}")

            # Stop streams for containers that no longer need stats
            containers_to_stop = self.streaming_containers - containers_needing_stats

            for container_key in containers_to_stop:
                # Extract host_id and container_id from the key (format: host_id:container_id)
                try:
                    host_id, container_id = container_key.split(':', 1)
                except ValueError:
                    logger.error(f"Invalid container key format: {container_key}")
                    self.streaming_containers.discard(container_key)
                    continue

                # Await the stop request to verify it succeeded before unmarking as streaming
                success = await stats_client.stop_container_stream(container_id, host_id)
                # Only unmark as streaming if the request succeeded
                if success:
                    self.streaming_containers.discard(container_key)
                    logger.debug(f"Stopped stats stream for container {container_id[:12]}")
                else:
                    logger.warning(f"Failed to stop stats stream for container {container_id[:12]}")

    async def stop_all_streams(self, stats_client, error_callback) -> None:
        """
        Stop all active stats streams

        Used when there are no active viewers

        Args:
            stats_client: Stats client instance
            error_callback: Callback for handling async task errors
        """
        async with self._streaming_lock:
            if self.streaming_containers:
                logger.info(f"Stopping {len(self.streaming_containers)} stats streams")
                # Build list of (container_key, stop_task) pairs
                stop_requests = []
                for container_key in list(self.streaming_containers):
                    # Extract host_id and container_id from the key (format: host_id:container_id)
                    try:
                        host_id, container_id = container_key.split(':', 1)
                    except ValueError:
                        logger.error(f"Invalid container key format during cleanup: {container_key}")
                        # Remove invalid keys immediately
                        self.streaming_containers.discard(container_key)
                        continue

                    stop_requests.append((container_key, stats_client.stop_container_stream(container_id, host_id)))

                # Wait for all stop requests to complete
                if stop_requests:
                    results = await asyncio.gather(*[task for _, task in stop_requests], return_exceptions=True)

                    # Only remove containers whose stop request actually succeeded
                    failed_count = 0
                    for (container_key, _), result in zip(stop_requests, results):
                        if isinstance(result, Exception):
                            logger.error(f"Failed to stop stream for {container_key}: {result}")
                            failed_count += 1
                        elif result is True:
                            # Successfully stopped - remove from tracking
                            self.streaming_containers.discard(container_key)
                        else:
                            # stop_container_stream returned False - keep tracking for retry
                            logger.warning(f"Stop request failed for {container_key}, keeping in tracking for retry")
                            failed_count += 1

                    if failed_count > 0:
                        logger.warning(
                            f"Failed to stop {failed_count} streams, "
                            f"{len(self.streaming_containers)} containers still tracked as streaming"
                        )

    def should_broadcast_host_metrics(self, settings: GlobalSettings) -> bool:
        """Determine if host metrics should be included in broadcast"""
        return settings.show_host_stats

    def get_stats_summary(self) -> dict:
        """Get current stats collection summary for debugging"""
        return {
            "streaming_containers": len(self.streaming_containers),
            "modal_containers": len(self.modal_containers),
            "modal_container_ids": list(self.modal_containers)
        }
