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
        self.streaming_containers: Set[str] = set()  # Currently streaming container IDs
        self.modal_containers: Set[str] = set()  # Container IDs with open modals

    def add_modal_container(self, container_id: str) -> None:
        """Track that a container modal is open"""
        self.modal_containers.add(container_id)
        logger.debug(f"Container modal opened for {container_id[:12]} - stats tracking enabled")

    def remove_modal_container(self, container_id: str) -> None:
        """Remove container from modal tracking"""
        self.modal_containers.discard(container_id)
        logger.debug(f"Container modal closed for {container_id[:12]}")

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
            Set of container IDs that need stats collection
        """
        containers_needing_stats = set()

        # Rule 1: Container stats OR host stats enabled = ALL running containers
        # (host stats need container data for aggregation)
        logger.debug(f"Stats decision: show_container_stats={settings.show_container_stats}, show_host_stats={settings.show_host_stats}")
        if settings.show_container_stats or settings.show_host_stats:
            for container in containers:
                if container.state == 'running':
                    containers_needing_stats.add(container.id)

        # Rule 2: Always add modal containers (even if settings are off)
        for modal_container_id in self.modal_containers:
            # Verify container is still running before adding
            for container in containers:
                if container.id == modal_container_id and container.state == 'running':
                    containers_needing_stats.add(container.id)
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
            containers_needing_stats: Set of container IDs that need stats
            stats_client: Stats client instance
            error_callback: Callback for handling async task errors
        """
        # Start streams for containers that need stats but aren't streaming yet
        for container in containers:
            if container.id in containers_needing_stats and container.id not in self.streaming_containers:
                task = asyncio.create_task(
                    stats_client.start_container_stream(
                        container.id,
                        container.name,
                        container.host_id
                    )
                )
                task.add_done_callback(error_callback)
                self.streaming_containers.add(container.id)
                logger.debug(f"Started stats stream for {container.name}")

        # Stop streams for containers that no longer need stats
        containers_to_stop = self.streaming_containers - containers_needing_stats
        for container_id in containers_to_stop:
            task = asyncio.create_task(stats_client.stop_container_stream(container_id))
            task.add_done_callback(error_callback)
            self.streaming_containers.discard(container_id)
            logger.debug(f"Stopped stats stream for container {container_id[:12]}")

    async def stop_all_streams(self, stats_client, error_callback) -> None:
        """
        Stop all active stats streams

        Used when there are no active viewers

        Args:
            stats_client: Stats client instance
            error_callback: Callback for handling async task errors
        """
        if self.streaming_containers:
            logger.info(f"Stopping {len(self.streaming_containers)} stats streams")
            for container_id in list(self.streaming_containers):
                task = asyncio.create_task(stats_client.stop_container_stream(container_id))
                task.add_done_callback(error_callback)
            self.streaming_containers.clear()

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
