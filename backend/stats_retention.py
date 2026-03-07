"""
Stats retention safety net.
Delegates ring buffer enforcement to the CascadingAggregator
and cleans up data older than retention_days as a fallback.
"""

from datetime import datetime, timedelta, timezone
import logging

from database import DatabaseManager, ContainerStatsHistory

logger = logging.getLogger(__name__)


class StatsRetentionManager:
    def __init__(self, db: DatabaseManager):
        self.db = db

    async def run_retention_job(self):
        """Run periodic cleanup — call from daily maintenance."""
        logger.info("Starting stats retention job...")
        try:
            # Ring buffer enforcement via aggregator (if available)
            from main import monitor
            if hasattr(monitor, '_rrd_aggregator') and monitor._rrd_aggregator:
                deleted = monitor._rrd_aggregator.enforce_ring_buffers()
                logger.info(f"Ring buffer enforcement: {deleted} rows removed")

            # Safety net: delete data older than retention period
            cleaned = await self._cleanup_old_data()
            logger.info(f"Stats retention complete: {cleaned} expired rows deleted")
        except Exception as e:
            logger.error(f"Stats retention job failed: {e}", exc_info=True)

    async def _cleanup_old_data(self) -> int:
        """Delete all stats older than configured retention period."""
        settings = self.db.get_settings()
        days = getattr(settings, 'stats_retention_days', 30)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        with self.db.get_session() as session:
            deleted = session.query(ContainerStatsHistory).filter(
                ContainerStatsHistory.timestamp < cutoff
            ).delete()
            session.commit()
            return deleted
