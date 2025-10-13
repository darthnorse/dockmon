"""
Cleanup Jobs Module for DockMon
Handles periodic cleanup of old data and sessions
"""

import asyncio
import logging

from database import DatabaseManager
from event_logger import EventLogger, EventSeverity, EventType
from auth.session_manager import session_manager

logger = logging.getLogger(__name__)


class CleanupManager:
    """Handles periodic cleanup tasks"""

    def __init__(self, db: DatabaseManager, event_logger: EventLogger):
        self.db = db
        self.event_logger = event_logger

    async def cleanup_old_data(self):
        """
        Periodic cleanup of old data.
        Runs every 24 hours to clean up:
        - Old events (if auto-cleanup is enabled)
        - Expired sessions
        """
        logger.info("Starting periodic data cleanup...")

        while True:
            try:
                settings = self.db.get_settings()

                if settings.auto_cleanup_events:
                    # Clean up old events
                    event_deleted = self.db.cleanup_old_events(settings.event_retention_days)
                    if event_deleted > 0:
                        self.event_logger.log_system_event(
                            "Automatic Event Cleanup",
                            f"Cleaned up {event_deleted} events older than {settings.event_retention_days} days",
                            EventSeverity.INFO,
                            EventType.STARTUP
                        )

                # Clean up expired sessions (runs daily regardless of event cleanup setting)
                expired_count = session_manager.cleanup_expired_sessions()
                if expired_count > 0:
                    logger.info(f"Cleaned up {expired_count} expired sessions")

                # Clean up orphaned tag assignments (containers not seen in 30 days)
                orphaned_tags = self.db.cleanup_orphaned_tag_assignments(days_old=30)
                if orphaned_tags > 0:
                    self.event_logger.log_system_event(
                        "Tag Cleanup",
                        f"Removed {orphaned_tags} orphaned tag assignments",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Sleep for 24 hours before next cleanup
                await asyncio.sleep(24 * 60 * 60)  # 24 hours

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                # Wait 1 hour before retrying
                await asyncio.sleep(60 * 60)  # 1 hour
