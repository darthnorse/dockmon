"""
Periodic Jobs Module for DockMon
Manages background tasks that run at regular intervals
"""

import asyncio
import logging

from database import DatabaseManager
from event_logger import EventLogger, EventSeverity, EventType
from auth.session_manager import session_manager

logger = logging.getLogger(__name__)


class PeriodicJobsManager:
    """Manages periodic background tasks (cleanup, updates, maintenance)"""

    def __init__(self, db: DatabaseManager, event_logger: EventLogger):
        self.db = db
        self.event_logger = event_logger
        self.monitor = None  # Will be set by monitor.py after initialization

    def auto_resolve_stale_alerts(self):
        """
        Auto-resolve alerts for entities that no longer exist or are stale.

        Resolves alerts for:
        1. Deleted containers (entity_gone)
        2. Offline hosts (entity_gone)
        3. Stale alerts with no updates in 24h (expired)

        Prevents alerts table from filling with orphaned alerts.
        """
        from datetime import datetime, timezone, timedelta
        from database import AlertV2

        resolved_count = 0

        with self.db.get_session() as session:
            # Get all open/snoozed alerts
            open_alerts = session.query(AlertV2).filter(
                AlertV2.state.in_(['open', 'snoozed'])
            ).all()

            for alert in open_alerts:
                should_resolve = False
                resolve_reason = None

                # Check if entity still exists
                if alert.scope_type == 'container':
                    # Check if container actually exists in Docker (any state - running, stopped, etc.)
                    if self.monitor:
                        container_exists = False

                        # Check all connected hosts for this container
                        for host_id, client in self.monitor.clients.items():
                            try:
                                # Try to get container by ID (works for any state)
                                client.containers.get(alert.scope_id)
                                container_exists = True
                                break
                            except Exception:
                                # Container not found on this host, try next
                                continue

                        if not container_exists:
                            should_resolve = True
                            resolve_reason = 'entity_gone'
                            logger.info(f"Container {alert.scope_id[:12]} no longer exists on any host, auto-resolving alert {alert.id}")

                elif alert.scope_type == 'host':
                    # Check if host exists and is connected
                    if self.monitor and alert.scope_id not in self.monitor.hosts:
                        should_resolve = True
                        resolve_reason = 'entity_gone'
                        logger.info(f"Host {alert.scope_id[:12]} no longer exists, auto-resolving alert {alert.id}")

                # Check for stale alerts (no updates in 24h)
                if not should_resolve and alert.last_seen:
                    last_seen_aware = alert.last_seen if alert.last_seen.tzinfo else alert.last_seen.replace(tzinfo=timezone.utc)
                    time_since_update = datetime.now(timezone.utc) - last_seen_aware

                    if time_since_update > timedelta(hours=24):
                        should_resolve = True
                        resolve_reason = 'expired'
                        logger.info(f"Alert {alert.id} stale for {time_since_update.total_seconds()/3600:.1f}h, auto-resolving")

                # Resolve the alert
                if should_resolve:
                    alert.state = 'resolved'
                    alert.resolved_at = datetime.now(timezone.utc)
                    alert.resolved_reason = resolve_reason
                    resolved_count += 1

            if resolved_count > 0:
                session.commit()
                logger.info(f"Auto-resolved {resolved_count} stale alerts")

        return resolved_count

    async def daily_maintenance(self):
        """
        Daily maintenance tasks.
        Runs every 24 hours to perform:
        - Data cleanup (old events, expired sessions, orphaned tags)
        - Host information updates (can be moved to separate job with different interval)
        """
        logger.info("Starting daily maintenance tasks...")

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

                # Clean up unused tags (tags with no assignments for N days)
                unused_tags = self.db.cleanup_unused_tags(days_unused=settings.unused_tag_retention_days)
                if unused_tags > 0:
                    self.event_logger.log_system_event(
                        "Unused Tag Cleanup",
                        f"Removed {unused_tags} unused tags not used in {settings.unused_tag_retention_days} days",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Auto-resolve stale alerts (deleted entities, expired)
                resolved_alerts = self.auto_resolve_stale_alerts()
                if resolved_alerts > 0:
                    self.event_logger.log_system_event(
                        "Alert Auto-Resolve",
                        f"Auto-resolved {resolved_alerts} stale alerts",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Note: Timezone offset is auto-synced from the browser, not from server
                # This ensures DST changes are handled automatically on the client side

                # Sleep for 24 hours before next cleanup
                await asyncio.sleep(24 * 60 * 60)  # 24 hours

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                # Wait 1 hour before retrying
                await asyncio.sleep(60 * 60)  # 1 hour
