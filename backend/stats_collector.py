"""
Background service for collecting and persisting container statistics.

Ensures stats streams are active in the Go stats-service regardless of
WebSocket viewers, then snapshots container stats and persists them.
"""

import asyncio
from datetime import datetime, timezone
import logging

from database import DatabaseManager, ContainerStatsHistory
from stats_client import StatsServiceClient

logger = logging.getLogger(__name__)


class StatsCollector:
    def __init__(self, db: DatabaseManager, stats_client: StatsServiceClient, monitor, interval: int = 60):
        self.db = db
        self.stats_client = stats_client
        self.monitor = monitor
        self.interval = interval
        self.running = False
        self._active_streams: set[str] = set()

    async def start(self):
        self.running = True
        logger.info(f"Stats collector started (interval: {self.interval}s)")
        while self.running:
            try:
                await self._ensure_streams()
                await self._collect_and_persist()
            except Exception as e:
                logger.error(f"Stats collection error: {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    def stop(self):
        self.running = False
        logger.info("Stats collector stopped")

    async def _ensure_streams(self):
        """Start stats streams for running containers that don't have one yet."""
        containers = self.monitor._last_containers
        if not containers:
            return

        running_ids = set()
        for c in containers:
            if c.status != 'running':
                continue
            running_ids.add(c.id)

            if c.id not in self._active_streams:
                await self.stats_client.start_container_stream(c.short_id, c.name, c.host_id)
                self._active_streams.add(c.id)

        stale = self._active_streams - running_ids
        for key in stale:
            self._active_streams.discard(key)

    async def _collect_and_persist(self):
        container_stats = await self.stats_client.get_container_stats()
        if not container_stats:
            return

        now = datetime.now(timezone.utc)
        batch = []
        for composite_key, stats in container_stats.items():
            parts = composite_key.split(":")
            if len(parts) < 2:
                continue

            batch.append({
                'container_id': composite_key,
                'host_id': parts[0],
                'timestamp': now,
                'cpu_percent': stats.get('cpu_percent'),
                'memory_usage': stats.get('memory_usage'),
                'memory_limit': stats.get('memory_limit'),
                'network_rx_bytes': stats.get('net_bytes_per_sec'),
                'network_tx_bytes': None,
                'resolution': '1m',
            })

        if batch:
            with self.db.get_session() as session:
                session.bulk_insert_mappings(ContainerStatsHistory, batch)
                session.commit()
            logger.debug(f"Persisted stats for {len(batch)} containers")
