"""
Periodic Jobs Module for DockMon
Manages background tasks that run at regular intervals
"""

import asyncio
import logging
import time as time_module
from datetime import datetime, time as dt_time, timezone, timedelta

from database import DatabaseManager
from event_logger import EventLogger, EventSeverity, EventType
from auth.session_manager import session_manager
from utils.keys import make_composite_key
from utils.async_docker import async_docker_call

logger = logging.getLogger(__name__)


class PeriodicJobsManager:
    """Manages periodic background tasks (cleanup, updates, maintenance)"""

    def __init__(self, db: DatabaseManager, event_logger: EventLogger):
        self.db = db
        self.event_logger = event_logger
        self.monitor = None  # Will be set by monitor.py after initialization
        self._last_update_check = None  # Track when we last ran update check

    async def auto_resolve_stale_alerts(self):
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
        from utils.async_docker import async_docker_call

        resolved_count = 0

        # Extract alert data and close session BEFORE Docker API calls
        alerts_to_check = []
        with self.db.get_session() as session:
            # Get all open/snoozed alerts
            open_alerts = session.query(AlertV2).filter(
                AlertV2.state.in_(['open', 'snoozed'])
            ).all()

            # Extract data we need while session is open
            for alert in open_alerts:
                alerts_to_check.append({
                    'id': alert.id,
                    'scope_type': alert.scope_type,
                    'scope_id': alert.scope_id,
                    'last_seen': alert.last_seen
                })

        # Session is now closed - safe for async Docker API calls

        # Optimization: Batch-fetch all existing containers once per host (prevents N+1 queries)
        existing_containers_by_host = {}
        if self.monitor:
            for host_id, client in self.monitor.clients.items():
                try:
                    # Fetch all containers on this host in one call
                    containers = await async_docker_call(client.containers.list, all=True)
                    # Store SHORT IDs (12 chars) in set for fast lookup
                    existing_containers_by_host[host_id] = {c.id[:12] for c in containers}
                    logger.debug(f"Found {len(existing_containers_by_host[host_id])} containers on host {host_id}")
                except Exception as e:
                    logger.warning(f"Failed to fetch containers for host {host_id}: {e}")
                    existing_containers_by_host[host_id] = set()

        alerts_to_resolve = []

        for alert_data in alerts_to_check:
            should_resolve = False
            resolve_reason = None

            # Check if entity still exists
            if alert_data['scope_type'] == 'container':
                # Check if container exists in any host (using pre-fetched sets)
                if self.monitor:
                    container_exists = any(
                        alert_data['scope_id'] in existing_containers_by_host.get(host_id, set())
                        for host_id in self.monitor.clients.keys()
                    )

                    if not container_exists:
                        should_resolve = True
                        resolve_reason = 'entity_gone'
                        logger.info(f"Container {alert_data['scope_id'][:12]} no longer exists on any host, auto-resolving alert {alert_data['id']}")

            elif alert_data['scope_type'] == 'host':
                # Check if host exists and is connected
                if self.monitor and alert_data['scope_id'] not in self.monitor.hosts:
                    should_resolve = True
                    resolve_reason = 'entity_gone'
                    logger.info(f"Host {alert_data['scope_id'][:12]} no longer exists, auto-resolving alert {alert_data['id']}")

            # Check for stale alerts (no updates in 24h)
            if not should_resolve and alert_data['last_seen']:
                last_seen_aware = alert_data['last_seen'] if alert_data['last_seen'].tzinfo else alert_data['last_seen'].replace(tzinfo=timezone.utc)
                time_since_update = datetime.now(timezone.utc) - last_seen_aware

                if time_since_update > timedelta(hours=24):
                    should_resolve = True
                    resolve_reason = 'expired'
                    logger.info(f"Alert {alert_data['id']} stale for {time_since_update.total_seconds()/3600:.1f}h, auto-resolving")

            # Store alerts that need resolving
            if should_resolve:
                alerts_to_resolve.append({
                    'id': alert_data['id'],
                    'reason': resolve_reason
                })

        # Reopen session to update alerts
        if alerts_to_resolve:
            with self.db.get_session() as session:
                for alert_info in alerts_to_resolve:
                    alert = session.query(AlertV2).filter(AlertV2.id == alert_info['id']).first()
                    if alert:
                        alert.state = 'resolved'
                        alert.resolved_at = datetime.now(timezone.utc)
                        alert.resolved_reason = alert_info['reason']
                        resolved_count += 1

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

                # Clean up old events if retention period is set
                if settings.event_retention_days > 0:
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
                resolved_alerts = await self.auto_resolve_stale_alerts()
                if resolved_alerts > 0:
                    self.event_logger.log_system_event(
                        "Alert Auto-Resolve",
                        f"Auto-resolved {resolved_alerts} stale alerts",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Clean up old resolved alerts (based on retention setting)
                if settings.alert_retention_days > 0:
                    alerts_deleted = self.db.cleanup_old_alerts(settings.alert_retention_days)
                    if alerts_deleted > 0:
                        self.event_logger.log_system_event(
                            "Alert Cleanup",
                            f"Cleaned up {alerts_deleted} resolved alerts older than {settings.alert_retention_days} days",
                            EventSeverity.INFO,
                            EventType.STARTUP
                        )

                # Clean up old rule evaluations (24 hours retention)
                evaluations_deleted = self.db.cleanup_old_rule_evaluations(hours=24)
                if evaluations_deleted > 0:
                    self.event_logger.log_system_event(
                        "Rule Evaluation Cleanup",
                        f"Cleaned up {evaluations_deleted} rule evaluations older than 24 hours",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Clean up stale container state dictionaries (prevent memory leak)
                if self.monitor:
                    await self.monitor.cleanup_stale_container_state()

                # Refresh host system info (OS version, Docker version, etc.)
                if self.monitor:
                    await self.monitor.refresh_all_hosts_system_info()

                # Clean up stale container-related database entries (for deleted containers)
                from database import (
                    ContainerUpdate,
                    ContainerHttpHealthCheck,
                    AutoRestartConfig,
                    ContainerDesiredState
                )
                containers = await self.monitor.get_containers()
                current_container_keys = {make_composite_key(c.host_id, c.short_id) for c in containers}

                # Also track SHORT IDs only for tables that use SHORT IDs instead of composite keys
                current_container_short_ids_by_host = {}
                for c in containers:
                    if c.host_id not in current_container_short_ids_by_host:
                        current_container_short_ids_by_host[c.host_id] = set()
                    current_container_short_ids_by_host[c.host_id].add(c.short_id)

                total_cleaned = 0

                with self.db.get_session() as session:
                    # 1. Clean up container_updates (uses composite key)
                    all_updates = session.query(ContainerUpdate).all()
                    stale_updates = [u for u in all_updates if u.container_id not in current_container_keys]
                    if stale_updates:
                        for stale in stale_updates:
                            session.delete(stale)
                        total_cleaned += len(stale_updates)
                        logger.debug(f"Cleaned up {len(stale_updates)} stale container_updates entries")

                    # 2. Clean up container_http_health_checks (uses composite key)
                    all_health_checks = session.query(ContainerHttpHealthCheck).all()
                    stale_health_checks = [h for h in all_health_checks if h.container_id not in current_container_keys]
                    if stale_health_checks:
                        for stale in stale_health_checks:
                            session.delete(stale)
                        total_cleaned += len(stale_health_checks)
                        logger.debug(f"Cleaned up {len(stale_health_checks)} stale container_http_health_checks entries")

                    # 3. Clean up auto_restart_configs (uses SHORT ID, not composite)
                    all_restart_configs = session.query(AutoRestartConfig).all()
                    stale_restart_configs = []
                    for config in all_restart_configs:
                        # Check if container still exists on this host
                        host_containers = current_container_short_ids_by_host.get(config.host_id, set())
                        if config.container_id not in host_containers:
                            stale_restart_configs.append(config)
                    if stale_restart_configs:
                        for stale in stale_restart_configs:
                            session.delete(stale)
                        total_cleaned += len(stale_restart_configs)
                        logger.debug(f"Cleaned up {len(stale_restart_configs)} stale auto_restart_configs entries")

                    # 4. Clean up container_desired_states (uses SHORT ID, not composite)
                    all_desired_states = session.query(ContainerDesiredState).all()
                    stale_desired_states = []
                    for state in all_desired_states:
                        # Check if container still exists on this host
                        host_containers = current_container_short_ids_by_host.get(state.host_id, set())
                        if state.container_id not in host_containers:
                            stale_desired_states.append(state)
                    if stale_desired_states:
                        for stale in stale_desired_states:
                            session.delete(stale)
                        total_cleaned += len(stale_desired_states)
                        logger.debug(f"Cleaned up {len(stale_desired_states)} stale container_desired_states entries")

                    # Commit all deletions in one transaction
                    if total_cleaned > 0:
                        session.commit()
                        logger.info(f"Cleaned up {total_cleaned} total stale container-related database entries")

                # Clean up orphaned RuleRuntime entries (for deleted containers)
                runtime_cleaned = self.db.cleanup_orphaned_rule_runtime(current_container_keys)
                if runtime_cleaned > 0:
                    self.event_logger.log_system_event(
                        "Rule Runtime Cleanup",
                        f"Cleaned up {runtime_cleaned} orphaned rule runtime entries",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Clean up old backup containers (older than 24 hours)
                backup_cleaned = await self.cleanup_old_backup_containers()
                if backup_cleaned > 0:
                    self.event_logger.log_system_event(
                        "Backup Container Cleanup",
                        f"Removed {backup_cleaned} old backup containers (older than 24 hours)",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Note: Timezone offset is auto-synced from the browser, not from server
                # This ensures DST changes are handled automatically on the client side

                # Check if we should run update checker (based on configured time)
                await self._check_and_run_updates()

                # Sleep for 24 hours before next cleanup
                await asyncio.sleep(24 * 60 * 60)  # 24 hours

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                # Wait 1 hour before retrying
                await asyncio.sleep(60 * 60)  # 1 hour

    async def _check_and_run_updates(self):
        """
        Check if it's time to run update checker based on configured schedule.

        Runs once per day at the configured time (default: 02:00).
        Uses _last_update_check to ensure we don't run multiple times.
        """
        from updates.update_checker import get_update_checker

        try:
            settings = self.db.get_settings()
            check_time_str = settings.update_check_time if hasattr(settings, 'update_check_time') and settings.update_check_time else "02:00"

            # Parse configured time
            hour, minute = map(int, check_time_str.split(":"))
            target_time = dt_time(hour, minute)
            now = datetime.now(timezone.utc)
            current_time = now.time()

            # Check if we're past the target time and haven't run today
            should_run = False
            if self._last_update_check is None:
                # First run - run immediately
                should_run = True
                logger.info("First update check - running immediately")
            elif self._last_update_check.date() < now.date() and current_time >= target_time:
                # Haven't run today and we're past the target time
                should_run = True
                logger.info(f"Running scheduled update check (target time: {check_time_str})")

            if should_run:
                # Step 1: Check for updates
                checker = get_update_checker(self.db, self.monitor)
                stats = await checker.check_all_containers()

                # Log completion event
                self.event_logger.log_system_event(
                    "Container Update Check",
                    f"Checked {stats['checked']} containers, found {stats['updates_found']} updates available",
                    EventSeverity.INFO,
                    EventType.STARTUP
                )

                logger.info(f"Update check complete: {stats}")

                # Step 2: Execute auto-updates for containers with auto_update_enabled
                if stats['updates_found'] > 0:
                    from updates.update_executor import get_update_executor
                    executor = get_update_executor(self.db, self.monitor)
                    update_stats = await executor.execute_auto_updates()

                    # Log execution results
                    if update_stats['attempted'] > 0:
                        self.event_logger.log_system_event(
                            "Container Auto-Update",
                            f"Attempted {update_stats['attempted']} auto-updates, {update_stats['successful']} successful, {update_stats['failed']} failed",
                            EventSeverity.INFO if update_stats['failed'] == 0 else EventSeverity.WARNING,
                            EventType.STARTUP
                        )
                        logger.info(f"Auto-update execution complete: {update_stats}")

                # Update last check time
                self._last_update_check = now

        except Exception as e:
            logger.error(f"Error in update checker: {e}", exc_info=True)

    async def check_updates_now(self):
        """
        Manually trigger an immediate update check (called from API endpoint).

        Returns:
            Dict with stats (total, checked, updates_found, errors)
        """
        from updates.update_checker import get_update_checker

        try:
            logger.info("Manual update check triggered")
            checker = get_update_checker(self.db, self.monitor)
            stats = await checker.check_all_containers()

            # Log completion event
            self.event_logger.log_system_event(
                "Manual Update Check",
                f"Checked {stats['checked']} containers, found {stats['updates_found']} updates available",
                EventSeverity.INFO,
                EventType.STARTUP
            )

            # Update last check time
            self._last_update_check = datetime.now(timezone.utc)
            logger.info(f"Manual update check complete: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Error in manual update check: {e}", exc_info=True)
            return {"total": 0, "checked": 0, "updates_found": 0, "errors": 1}

    async def cleanup_old_backup_containers(self) -> int:
        """
        Remove backup containers older than 24 hours.

        Backup containers are created during updates with pattern: {name}-backup-{timestamp}
        If update succeeds, cleanup removes them. If cleanup fails, they accumulate.
        This job removes old backups to prevent disk bloat.

        Returns:
            Number of backup containers removed
        """
        if not self.monitor:
            logger.warning("No monitor available for backup container cleanup")
            return 0

        removed_count = 0
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

        try:
            # Check all hosts
            for host_id, client in self.monitor.clients.items():
                try:
                    # Get all containers (including stopped)
                    containers = await async_docker_call(client.containers.list, all=True)

                    for container in containers:
                        # Check if this is a backup container (pattern: {name}-backup-{timestamp})
                        if '-backup-' not in container.name:
                            continue

                        # Parse created timestamp
                        try:
                            created_str = container.attrs.get('Created', '')
                            if not created_str:
                                continue

                            # Parse ISO format timestamp
                            created_dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))

                            # Check if older than 24 hours
                            if created_dt < cutoff_time:
                                logger.info(f"Removing old backup container: {container.name} (created {created_dt})")
                                await async_docker_call(container.remove, force=True)
                                removed_count += 1

                        except Exception as e:
                            logger.warning(f"Error parsing/removing backup container {container.name}: {e}")
                            continue

                except Exception as e:
                    logger.error(f"Error cleaning backups on host {host_id}: {e}")
                    continue

            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} old backup containers")

            return removed_count

        except Exception as e:
            logger.error(f"Error in backup container cleanup: {e}", exc_info=True)
            return removed_count
