"""
Periodic Jobs Module for DockMon
Manages background tasks that run at regular intervals
"""

import asyncio
import logging
import time as time_module
import subprocess
import os
from datetime import datetime, time as dt_time, timezone, timedelta
import re

from cronsim import CronSim
from cronsim.cronsim import CronSimError
from database import DatabaseManager
from event_logger import EventLogger, EventSeverity, EventType
from auth.session_manager import session_manager
from utils.keys import make_composite_key, parse_composite_key
from utils.async_docker import async_docker_call, async_containers_list
from updates.dockmon_update_checker import get_dockmon_update_checker

logger = logging.getLogger(__name__)

# Pattern to detect HH:MM format (simple time)
SIMPLE_TIME_PATTERN = re.compile(r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$')


def is_cron_expression(schedule: str) -> bool:
    """
    Detect if a schedule string is a cron expression or simple HH:MM time.

    Args:
        schedule: Schedule string (e.g., "02:00" or "0 4 * * 6")

    Returns:
        True if cron expression, False if simple HH:MM time
    """
    # Simple HH:MM format
    if SIMPLE_TIME_PATTERN.match(schedule.strip()):
        return False

    # Try to parse as cron - if it works, it's a cron expression
    try:
        # CronSim validates on construction
        CronSim(schedule.strip(), datetime.now().astimezone())
        return True
    except CronSimError:
        return False


def calculate_next_cron_run(cron_expression: str) -> datetime:
    """
    Calculate the next run time for a cron expression.

    Args:
        cron_expression: Cron expression (e.g., "0 4 * * 6" for 4am every Saturday)

    Returns:
        Next run time as datetime (timezone-aware, local time)
    """
    # Use local time for cron calculations (respects TZ env var)
    local_now = datetime.now().astimezone()
    cron = CronSim(cron_expression.strip(), local_now)
    return next(cron)


def get_previous_cron_occurrence(cron_expression: str, reference_time: datetime) -> datetime:
    """
    Get the most recent cron occurrence before reference_time.

    Since CronSim iterates forward only, we start from a past point
    and iterate until we find the last occurrence before reference_time.

    Args:
        cron_expression: Cron expression (e.g., "0 4 * * 6")
        reference_time: The reference point (typically now)

    Returns:
        Most recent cron trigger before reference_time, or None if not found
    """
    # Look back 35 days to cover monthly schedules (31 days + margin)
    # This handles daily, weekly, and monthly cron expressions
    search_start = reference_time - timedelta(days=35)
    cron = CronSim(cron_expression.strip(), search_start)

    prev = None
    for trigger in cron:
        if trigger >= reference_time:
            break
        prev = trigger
    return prev


class PeriodicJobsManager:
    """Manages periodic background tasks (cleanup, updates, maintenance)"""

    def __init__(self, db: DatabaseManager, event_logger: EventLogger):
        self.db = db
        self.event_logger = event_logger
        self.monitor = None  # Will be set by monitor.py after initialization
        self._last_update_check = None  # Track when we last ran update check
        self._schedule_changed = asyncio.Event()  # Signal to wake sleep when schedule changes

    def notify_schedule_changed(self):
        """Signal that the update schedule has changed, waking the sleeping task."""
        logger.info("Update schedule changed, waking periodic job to recalculate next run")
        self._schedule_changed.set()

    async def auto_resolve_stale_alerts(self):
        """
        Auto-resolve alerts for entities that no longer exist or are stale.

        Resolves alerts for:
        1. Deleted containers (entity_gone)
        2. Offline hosts (entity_gone)
        3. Stale alerts with no updates in 24h (expired)

        Prevents alerts table from filling with orphaned alerts.
        """
        from database import AlertV2

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
                    containers = await async_containers_list(client, all=True)
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
                # Check if container exists on its host (using pre-fetched sets)
                # Parse composite scope_id to extract host_id and container_id
                if self.monitor:
                    alert_host_id, container_short_id = parse_composite_key(alert_data['scope_id'])
                    container_exists = container_short_id in existing_containers_by_host.get(alert_host_id, set())

                    if not container_exists:
                        should_resolve = True
                        resolve_reason = 'entity_gone'
                        logger.info(f"Container {container_short_id} no longer exists on host {alert_host_id}, auto-resolving alert {alert_data['id']}")

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

                # Clean up expired action tokens (v2.2.0+)
                from auth.action_token_auth import cleanup_expired_action_tokens
                action_tokens_deleted = cleanup_expired_action_tokens(self.db)
                if action_tokens_deleted > 0:
                    logger.info(f"Cleaned up {action_tokens_deleted} expired action tokens")

                # Clean up expired registration tokens (v2.2.0+)
                from agent.manager import AgentManager
                agent_manager = AgentManager()
                registration_tokens_deleted = agent_manager.cleanup_expired_registration_tokens()
                if registration_tokens_deleted > 0:
                    logger.info(f"Cleaned up {registration_tokens_deleted} expired registration tokens")

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
                    ContainerDesiredState,
                    DeploymentMetadata
                )
                containers = await self.monitor.get_containers()
                current_container_keys = {make_composite_key(c.host_id, c.short_id) for c in containers}

                # Track which hosts successfully returned containers (Issue #116)
                # Only delete stale entries for hosts that are online and reporting containers
                # This prevents deleting data when agent hosts haven't reconnected yet
                hosts_with_containers = {c.host_id for c in containers}

                # Also track SHORT IDs only for tables that use SHORT IDs instead of composite keys
                current_container_short_ids_by_host = {}
                for c in containers:
                    if c.host_id not in current_container_short_ids_by_host:
                        current_container_short_ids_by_host[c.host_id] = set()
                    current_container_short_ids_by_host[c.host_id].add(c.short_id)

                total_cleaned = 0

                with self.db.get_session() as session:
                    # 1. Clean up container_updates (uses composite key)
                    # Only clean up for hosts that are online (Issue #116)
                    all_updates = session.query(ContainerUpdate).all()
                    stale_updates = [
                        u for u in all_updates
                        if u.container_id not in current_container_keys
                        and u.host_id in hosts_with_containers  # Only if host is online
                    ]
                    if stale_updates:
                        for stale in stale_updates:
                            session.delete(stale)
                        total_cleaned += len(stale_updates)
                        logger.debug(f"Cleaned up {len(stale_updates)} stale container_updates entries")

                    # 2. Clean up container_http_health_checks (uses composite key)
                    # Only clean up for hosts that are online (Issue #116)
                    all_health_checks = session.query(ContainerHttpHealthCheck).all()
                    stale_health_checks = [
                        h for h in all_health_checks
                        if h.container_id not in current_container_keys
                        and h.host_id in hosts_with_containers  # Only if host is online
                    ]
                    if stale_health_checks:
                        for stale in stale_health_checks:
                            session.delete(stale)
                        total_cleaned += len(stale_health_checks)
                        logger.debug(f"Cleaned up {len(stale_health_checks)} stale container_http_health_checks entries")

                    # 3. Clean up auto_restart_configs (uses SHORT ID, not composite)
                    # Only clean up for hosts that are online (Issue #116)
                    all_restart_configs = session.query(AutoRestartConfig).all()
                    stale_restart_configs = []
                    for config in all_restart_configs:
                        # Skip if host is offline - can't confirm container is gone
                        if config.host_id not in hosts_with_containers:
                            continue
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
                    # Only clean up for hosts that are online (Issue #116)
                    all_desired_states = session.query(ContainerDesiredState).all()
                    stale_desired_states = []
                    for state in all_desired_states:
                        # Skip if host is offline - can't confirm container is gone
                        if state.host_id not in hosts_with_containers:
                            continue
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

                # Clean up orphaned deployment metadata (for containers deleted outside DockMon)
                # Part of deployment v2.1 remediation (Phase 1.6)
                # Pass hosts_with_containers to avoid cleaning up for offline hosts (Issue #116)
                deployment_metadata_cleaned = self.db.cleanup_orphaned_deployment_metadata(
                    current_container_keys,
                    hosts_with_containers=hosts_with_containers
                )
                if deployment_metadata_cleaned > 0:
                    self.event_logger.log_system_event(
                        "Deployment Metadata Cleanup",
                        f"Cleaned up {deployment_metadata_cleaned} orphaned deployment metadata entries",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Clean up orphaned RuleRuntime entries (for deleted containers)
                # Pass hosts_with_containers to avoid cleaning up for offline hosts (Issue #116)
                runtime_cleaned = self.db.cleanup_orphaned_rule_runtime(
                    current_container_keys,
                    hosts_with_containers=hosts_with_containers
                )
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

                # Clean up old Docker images (based on retention policy)
                images_cleaned = await self.cleanup_old_images()
                if images_cleaned > 0:
                    self.event_logger.log_system_event(
                        "Image Cleanup",
                        f"Removed {images_cleaned} old/dangling Docker images",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Clean up expired image digest cache entries (Issue #62)
                cache_cleaned = await self.cleanup_expired_image_cache()
                if cache_cleaned > 0:
                    logger.debug(f"Cleaned up {cache_cleaned} expired image cache entries")

                # Check SSL certificate expiry and regenerate if needed
                cert_regenerated = await self.check_certificate_expiry()
                if cert_regenerated:
                    logger.info("Certificate was regenerated during maintenance")

                # Note: Timezone offset is auto-synced from the browser, not from server
                # This ensures DST changes are handled automatically on the client side

                # Check if we should run update checker (based on configured time)
                await self._check_and_run_updates()

                # Calculate sleep duration until next scheduled check (Issue #49 fix)
                # This ensures checks run at configured time, not 24h after container restart
                # Supports both simple HH:MM format and cron expressions (Issue #103)
                try:
                    settings = self.db.get_settings()
                    schedule_str = settings.update_check_time if hasattr(settings, 'update_check_time') and settings.update_check_time else "02:00"

                    if is_cron_expression(schedule_str):
                        # Cron expression - use croniter for scheduling
                        next_run = calculate_next_cron_run(schedule_str)
                        sleep_seconds = (next_run - datetime.now().astimezone()).total_seconds()
                        sleep_seconds = max(60, sleep_seconds)  # Minimum 60 seconds

                        logger.info(
                            f"Next update check scheduled for {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')} "
                            f"(cron: {schedule_str}, sleeping {sleep_seconds/3600:.1f} hours)"
                        )
                    else:
                        # Simple HH:MM format - use existing logic
                        hour, minute = map(int, schedule_str.split(":"))

                        # Get system timezone offset from TZ environment variable
                        # This respects the TZ setting in docker-compose.yml
                        local_now = datetime.now().astimezone()
                        tz_offset_seconds = local_now.utcoffset().total_seconds()
                        timezone_offset = int(tz_offset_seconds / 60)  # Convert to minutes

                        # Convert local time to UTC for scheduling
                        # timezone_offset is minutes from UTC (e.g., -300 for ET, +60 for CET)
                        # User enters local time, we need UTC: UTC = local - offset
                        total_minutes_local = hour * 60 + minute
                        total_minutes_utc = total_minutes_local - timezone_offset

                        # Handle day wraparound (e.g., 1 AM ET = 6 AM UTC, or 11 PM ET = 4 AM UTC next day)
                        target_hour_utc = (total_minutes_utc // 60) % 24
                        target_minute_utc = total_minutes_utc % 60
                        target_time = dt_time(target_hour_utc, target_minute_utc)

                        # Calculate dynamic sleep duration
                        sleep_seconds = self._calculate_sleep_until_next_check(target_time)
                        next_check_time = datetime.now(timezone.utc) + timedelta(seconds=sleep_seconds)

                        logger.info(
                            f"Next update check scheduled for {next_check_time.strftime('%Y-%m-%d %H:%M:%S UTC')} "
                            f"(sleeping {sleep_seconds/3600:.1f} hours)"
                        )

                    # Interruptible sleep - can be woken early if schedule changes
                    try:
                        await asyncio.wait_for(self._schedule_changed.wait(), timeout=sleep_seconds)
                        # Event was set - schedule changed, clear and recalculate
                        self._schedule_changed.clear()
                        logger.info("Schedule change detected, recalculating next run time")
                        continue  # Skip to next iteration to recalculate
                    except asyncio.TimeoutError:
                        pass  # Normal timeout - continue to run update check

                except Exception as e:
                    # Fallback to 24-hour sleep on error
                    logger.error(f"Failed to calculate sleep duration, falling back to 24h: {e}")
                    await asyncio.sleep(24 * 60 * 60)

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                # Wait 1 hour before retrying
                await asyncio.sleep(60 * 60)  # 1 hour

    async def _check_and_run_updates(self):
        """
        Check if it's time to run update checker based on configured schedule.

        Supports both simple HH:MM format (daily at configured time) and cron
        expressions (flexible scheduling like "0 4 * * 6" for weekly Saturday 4am).

        Uses _last_update_check to ensure we don't run multiple times per schedule.
        """
        from updates.update_checker import get_update_checker

        try:
            settings = self.db.get_settings()
            schedule_str = settings.update_check_time if hasattr(settings, 'update_check_time') and settings.update_check_time else "02:00"

            now = datetime.now(timezone.utc)
            should_run = False

            if is_cron_expression(schedule_str):
                # Cron expression scheduling (Issue #103)
                # Determine if we should run based on cron schedule
                if self._last_update_check is None:
                    # First run - run immediately
                    should_run = True
                    logger.info("First update check - running immediately")
                else:
                    # Check if the last scheduled cron time is after our last check
                    # Use local time for cron calculations (respects TZ env var)
                    local_now = datetime.now().astimezone()
                    # Get the previous occurrence (the one that just triggered)
                    prev_run = get_previous_cron_occurrence(schedule_str, local_now)

                    # Convert last_update_check to local time for comparison
                    last_check_local = self._last_update_check.astimezone()

                    if prev_run and prev_run > last_check_local:
                        # There's been a scheduled cron trigger since our last check
                        should_run = True
                        logger.info(f"Running scheduled update check (cron: {schedule_str}, triggered: {prev_run.strftime('%Y-%m-%d %H:%M %Z')})")
            else:
                # Simple HH:MM format (daily at configured time)
                hour, minute = map(int, schedule_str.split(":"))

                # Get system timezone offset from TZ environment variable
                # This respects the TZ setting in docker-compose.yml
                local_now = datetime.now().astimezone()
                tz_offset_seconds = local_now.utcoffset().total_seconds()
                timezone_offset = int(tz_offset_seconds / 60)  # Convert to minutes

                # Convert local time to UTC for comparison
                # timezone_offset is minutes from UTC (e.g., -300 for ET, +60 for CET)
                # User enters local time, we need UTC: UTC = local - offset
                total_minutes_local = hour * 60 + minute
                total_minutes_utc = total_minutes_local - timezone_offset

                # Handle day wraparound
                target_hour_utc = (total_minutes_utc // 60) % 24
                target_minute_utc = total_minutes_utc % 60
                target_time = dt_time(target_hour_utc, target_minute_utc)

                # Check if we should run based on HH:MM schedule
                # Use same logic as cron: check if target time occurred SINCE last check
                if self._last_update_check is None:
                    # First run - run immediately
                    should_run = True
                    logger.info("First update check - running immediately")
                else:
                    # Build the most recent occurrence of the target time in UTC
                    target_datetime_utc = datetime.combine(now.date(), target_time, tzinfo=timezone.utc)

                    # If target time today is still in the future, use yesterday's occurrence
                    if target_datetime_utc > now:
                        target_datetime_utc -= timedelta(days=1)

                    # Check if the scheduled time is after our last check
                    if target_datetime_utc > self._last_update_check:
                        should_run = True
                        logger.info(f"Running scheduled update check (target time: {schedule_str}, triggered: {target_datetime_utc.strftime('%Y-%m-%d %H:%M UTC')})")

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
                    # Note: 'total' is the number of containers eligible for auto-update
                    if update_stats['total'] > 0:
                        self.event_logger.log_system_event(
                            "Container Auto-Update",
                            f"Processed {update_stats['total']} auto-updates: {update_stats['successful']} successful, {update_stats['failed']} failed, {update_stats['skipped']} skipped",
                            EventSeverity.INFO if update_stats['failed'] == 0 else EventSeverity.WARNING,
                            EventType.STARTUP
                        )
                        logger.info(f"Auto-update execution complete: {update_stats}")

                # Also check DockMon and Agent updates (tied to container update schedule)
                try:
                    dockmon_checker = get_dockmon_update_checker(self.db)

                    # Check DockMon updates
                    dockmon_result = await dockmon_checker.check_for_update()
                    if dockmon_result.get('update_available'):
                        logger.info(
                            f"DockMon update available: "
                            f"{dockmon_result['current_version']} → {dockmon_result['latest_version']}"
                        )

                    # Check Agent updates
                    agent_result = await dockmon_checker.check_for_agent_update()
                    if agent_result.get('latest_version'):
                        logger.debug(f"Latest Agent version: {agent_result['latest_version']}")
                except Exception as e:
                    logger.warning(f"Error checking DockMon/Agent updates: {e}")

                # Update last check time
                self._last_update_check = now

        except Exception as e:
            logger.error(f"Error in update checker: {e}", exc_info=True)

    def _calculate_sleep_until_next_check(self, target_time: dt_time) -> float:
        """
        Calculate seconds to sleep until next occurrence of target time.

        This ensures update checks run at the user-configured time, not 24 hours
        after container restart.

        Args:
            target_time: Target time of day (e.g., time(14, 0) for 2:00 PM UTC)

        Returns:
            Seconds to sleep (always >= 60 to prevent tight loops)

        Example:
            Current: 1:00 PM, Target: 2:00 PM → sleep ~1 hour
            Current: 3:00 PM, Target: 2:00 PM → sleep ~23 hours (until tomorrow)
        """
        now = datetime.now(timezone.utc)

        # Create datetime for target time today
        target_today = datetime.combine(now.date(), target_time, tzinfo=timezone.utc)

        if now.time() < target_time:
            # Haven't reached target time today yet
            next_check = target_today
        else:
            # Already past target time, schedule for tomorrow
            next_check = target_today + timedelta(days=1)

        # Calculate seconds until next check
        sleep_seconds = (next_check - now).total_seconds()

        # Ensure we always sleep at least 60 seconds (prevent tight loop if time calculation is off)
        return max(60, sleep_seconds)

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

            # Also check DockMon and Agent updates (tied to container update schedule)
            try:
                checker = get_dockmon_update_checker(self.db)

                # Check DockMon updates
                dockmon_result = await checker.check_for_update()
                if dockmon_result.get('update_available'):
                    logger.info(
                        f"DockMon update available: "
                        f"{dockmon_result['current_version']} → {dockmon_result['latest_version']}"
                    )

                # Check Agent updates
                agent_result = await checker.check_for_agent_update()
                if agent_result.get('latest_version'):
                    logger.debug(f"Latest Agent version: {agent_result['latest_version']}")
            except Exception as e:
                logger.warning(f"Error checking DockMon/Agent updates: {e}")

            return stats

        except Exception as e:
            logger.error(f"Error in manual update check: {e}", exc_info=True)
            return {"total": 0, "checked": 0, "updates_found": 0, "errors": 1}

    async def cleanup_old_backup_containers(self) -> int:
        """
        Remove backup containers older than 24 hours.

        Backup containers are created during updates with pattern: {name}-dockmon-backup-{timestamp}
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
                    containers = await async_containers_list(client, all=True)

                    for container in containers:
                        # Check if this is a backup container (pattern: {name}-dockmon-backup-{timestamp})
                        if '-dockmon-backup-' not in container.name:
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

    def _parse_image_created_time(self, image_attrs: dict) -> datetime:
        """
        Parse Created timestamp from image attributes.

        Defaults to current time if timestamp is missing or invalid.
        This ensures images without proper metadata are protected by grace period.

        Args:
            image_attrs: Docker image attributes dict

        Returns:
            Parsed datetime or current time if missing
        """
        created_str = image_attrs.get('Created', '')
        if created_str:
            try:
                return datetime.fromisoformat(created_str.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                logger.debug(f"Failed to parse image created time: {created_str}")
                return datetime.now(timezone.utc)
        else:
            return datetime.now(timezone.utc)

    async def cleanup_old_images(self) -> int:
        """
        Remove unused Docker images based on retention policy.

        Removes:
        - Dangling images (<none>:<none>) older than grace period
        - Old versions of images (keeps last N versions per repository)

        Safety checks:
        - Never removes images with running/stopped containers
        - Respects grace period (won't remove images newer than N hours)
        - Respects retention count (keeps at least N versions per image)

        Returns:
            Number of images removed
        """
        if not self.monitor:
            logger.warning("No monitor available for image cleanup")
            return 0

        settings = self.db.get_settings()

        # Check if image pruning is enabled
        if not settings.prune_images_enabled:
            logger.debug("Image pruning is disabled")
            return 0

        removed_count = 0
        retention_count = settings.image_retention_count
        grace_hours = settings.image_prune_grace_hours
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=grace_hours)

        try:
            # Process each host
            for host_id, client in self.monitor.clients.items():
                try:
                    containers = await async_containers_list(client, all=True)
                    images_in_use = {c.image.id for c in containers}
                    logger.debug(f"Host {host_id}: Found {len(images_in_use)} images in use by containers")

                    # Get all images on this host
                    all_images = await async_docker_call(client.images.list, all=True)
                    logger.debug(f"Host {host_id}: Found {len(all_images)} total images")

                    # Group images by repository name (e.g., "nginx", "postgres")
                    images_by_repo = {}
                    dangling_images = []

                    for image in all_images:
                        # Check if dangling image (<none>:<none>)
                        if not image.tags:
                            dangling_images.append(image)
                            continue

                        # Extract repository name from first tag
                        # Tag format: "repo:tag" or "registry/repo:tag"
                        tag = image.tags[0]
                        repo_name = tag.rsplit(':', 1)[0]  # Remove :tag

                        if repo_name not in images_by_repo:
                            images_by_repo[repo_name] = []

                        # Parse created timestamp
                        created_dt = self._parse_image_created_time(image.attrs)

                        images_by_repo[repo_name].append({
                            'image': image,
                            'created': created_dt,
                            'tags': image.tags
                        })

                    # Remove old versions (keep last N per repository)
                    for repo_name, images_list in images_by_repo.items():
                        # Sort by created date (newest first)
                        images_list.sort(key=lambda x: x['created'], reverse=True)

                        # Skip if we have retention_count or fewer versions
                        if len(images_list) <= retention_count:
                            continue

                        # Remove old versions beyond retention count
                        for img_data in images_list[retention_count:]:
                            image = img_data['image']
                            created_dt = img_data['created']

                            # Safety checks
                            if image.id in images_in_use:
                                logger.debug(f"Skipping {repo_name} - image in use by container")
                                continue

                            if created_dt >= cutoff_time:
                                logger.debug(f"Skipping {repo_name} - within grace period ({grace_hours}h)")
                                continue

                            # Safe to remove
                            try:
                                logger.info(f"Removing old image: {repo_name} (created {created_dt.isoformat()}, age: {(datetime.now(timezone.utc) - created_dt).days} days)")
                                await async_docker_call(image.remove, force=False)
                                removed_count += 1
                            except Exception as e:
                                logger.warning(f"Failed to remove image {repo_name}: {e}")

                    # Remove dangling images older than grace period
                    for image in dangling_images:
                        # Safety check: in use?
                        if image.id in images_in_use:
                            continue

                        # Parse created timestamp
                        created_dt = self._parse_image_created_time(image.attrs)

                        # Check grace period
                        if created_dt >= cutoff_time:
                            continue

                        # Safe to remove
                        try:
                            logger.info(f"Removing dangling image: {image.short_id}")
                            await async_docker_call(image.remove, force=False)
                            removed_count += 1
                        except Exception as e:
                            logger.debug(f"Failed to remove dangling image {image.short_id}: {e}")

                except Exception as e:
                    logger.error(f"Error cleaning images on host {host_id}: {e}", exc_info=True)
                    continue

            if removed_count > 0:
                logger.info(f"Image cleanup: Removed {removed_count} old/dangling images (retention: {retention_count} versions, grace: {grace_hours}h)")

            return removed_count

        except Exception as e:
            logger.error(f"Error in image cleanup: {e}", exc_info=True)
            return removed_count

    async def check_certificate_expiry(self) -> bool:
        """
        Check SSL certificate expiry and regenerate if approaching expiration.

        Certificates need to be regenerated if they expire in less than 41 days
        to comply with Apple's browser certificate policy (47-day maximum validity).

        Returns:
            True if certificate was regenerated, False otherwise
        """
        try:
            # Check if certificate exists
            cert_path = "/etc/nginx/certs/dockmon.crt"
            if not os.path.exists(cert_path):
                logger.debug(f"Certificate not found at {cert_path}, skipping expiry check")
                return False

            # Get certificate expiry date using openssl
            try:
                result = subprocess.run(
                    ["openssl", "x509", "-enddate", "-noout", "-in", cert_path],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode != 0:
                    logger.warning(f"Failed to read certificate expiry: {result.stderr}")
                    return False

                # Parse expiry date from output: "notAfter=Oct 12 10:23:45 2025 GMT"
                expiry_str = result.stdout.strip()
                if not expiry_str.startswith("notAfter="):
                    logger.warning(f"Unexpected openssl output: {expiry_str}")
                    return False

                # Parse the date string
                date_part = expiry_str.replace("notAfter=", "")
                # Format: "Oct 12 10:23:45 2025 GMT"
                expiry_dt = datetime.strptime(date_part, "%b %d %H:%M:%S %Y %Z")
                # Make timezone aware (GMT = UTC)
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)

                # Check if expiry is within 41 days
                days_until_expiry = (expiry_dt - datetime.now(timezone.utc)).days
                logger.debug(f"Certificate expires in {days_until_expiry} days ({expiry_dt.isoformat()})")

                if days_until_expiry > 41:
                    logger.debug(f"Certificate is healthy ({days_until_expiry} days remaining)")
                    return False

                # Certificate is expiring soon - regenerate
                logger.warning(f"Certificate expires in {days_until_expiry} days, regenerating...")
                return await self._regenerate_certificate()

            except subprocess.TimeoutExpired:
                logger.error("Timeout reading certificate expiry date")
                return False
            except ValueError as e:
                logger.warning(f"Failed to parse certificate expiry date: {e}")
                return False

        except Exception as e:
            logger.error(f"Error checking certificate expiry: {e}", exc_info=True)
            return False

    async def _regenerate_certificate(self) -> bool:
        """
        Regenerate the SSL certificate using OpenSSL.

        Generates a self-signed certificate with 47-day validity to comply
        with Apple's browser certificate policy.

        Returns:
            True if regeneration succeeded, False otherwise
        """
        try:
            cert_dir = "/etc/nginx/certs"
            key_path = f"{cert_dir}/dockmon.key"
            cert_path = f"{cert_dir}/dockmon.crt"

            # Ensure cert directory exists
            os.makedirs(cert_dir, exist_ok=True)

            # Generate private key and self-signed certificate
            # 47-day validity to comply with Apple's browser certificate policy
            result = subprocess.run(
                [
                    "openssl", "req", "-x509", "-nodes", "-days", "47",
                    "-newkey", "rsa:2048",
                    "-keyout", key_path,
                    "-out", cert_path,
                    "-subj", "/C=US/ST=State/L=City/O=DockMon/CN=localhost"
                ],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.error(f"Certificate generation failed: {result.stderr}")
                return False

            # Set appropriate permissions
            os.chmod(key_path, 0o600)
            os.chmod(cert_path, 0o644)

            logger.info("SSL certificate successfully regenerated with 47-day validity")
            self.event_logger.log_system_event(
                "Certificate Regeneration",
                "SSL certificate was regenerated due to approaching expiration (47-day validity)",
                EventSeverity.INFO,
                EventType.STARTUP
            )
            return True

        except subprocess.TimeoutExpired:
            logger.error("Timeout regenerating certificate")
            return False
        except OSError as e:
            logger.error(f"Error creating cert directory or setting permissions: {e}")
            return False
        except Exception as e:
            logger.error(f"Error regenerating certificate: {e}", exc_info=True)
            return False

    async def check_dockmon_update_once(self):
        """
        Check for DockMon and Agent updates once (called on startup).
        Does not loop - just runs a single check.
        """
        try:
            logger.info("Checking for DockMon and Agent updates on startup...")

            checker = get_dockmon_update_checker(self.db)

            # Check DockMon updates
            result = await checker.check_for_update()
            if result.get('update_available'):
                logger.info(
                    f"DockMon update available: "
                    f"{result['current_version']} → {result['latest_version']}"
                )
            elif result.get('error'):
                logger.debug(f"DockMon update check failed: {result['error']}")
            else:
                logger.info(f"DockMon is up to date: {result['current_version']}")

            # Also check Agent updates
            agent_result = await checker.check_for_agent_update()
            if agent_result.get('latest_version'):
                logger.info(f"Latest Agent version from GitHub: {agent_result['latest_version']}")
            elif agent_result.get('error'):
                logger.debug(f"Agent update check failed: {agent_result['error']}")

        except Exception as e:
            logger.warning(f"Error checking for updates on startup: {e}")

    async def cleanup_expired_image_cache(self) -> int:
        """
        Clean up expired image digest cache entries.

        Issue #62: Rate limit mitigation via caching.
        Expired entries are no longer useful and should be removed to prevent
        database bloat.

        Returns:
            Number of cache entries removed
        """
        try:
            removed_count = self.db.cleanup_expired_image_cache()
            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} expired image cache entries")
            return removed_count
        except Exception as e:
            logger.error(f"Error cleaning expired image cache: {e}", exc_info=True)
            return 0

    async def validate_engine_ids_periodic(self):
        """
        Periodic task: Validate and populate missing engine_ids for all hosts.
        Runs every 6 hours.

        This ensures:
        - New hosts from v2.1.0 get engine_id populated
        - Offline hosts get engine_id when they come online
        - Engine ID changes are detected (VM cloning, Docker data migration)

        Note: engine_id is also populated on host connect/reconnect (immediate),
        this periodic check is a safety net for edge cases.
        """
        # Wait 5 minutes after startup before first check (let hosts connect first)
        await asyncio.sleep(5 * 60)

        while True:
            try:
                logger.debug("Running periodic engine_id validation...")

                # Get all non-agent hosts that need engine_id check
                hosts_to_check = []
                with self.db.get_session() as session:
                    from database import DockerHostDB
                    # Get hosts where engine_id is NULL or host is active (to detect changes)
                    hosts = session.query(DockerHostDB).filter(
                        DockerHostDB.connection_type.in_(['local', 'remote']),  # Skip agent hosts
                        DockerHostDB.is_active == True
                    ).all()

                    for host in hosts:
                        hosts_to_check.append({
                            'id': host.id,
                            'name': host.name,
                            'url': host.url,
                            'connection_type': host.connection_type,
                            'current_engine_id': host.engine_id
                        })

                # Check each host's engine_id
                updated_count = 0
                for host_data in hosts_to_check:
                    try:
                        # Get Docker client from monitor
                        if not self.monitor:
                            continue

                        client = self.monitor.clients.get(host_data['id'])
                        if not client:
                            # Host offline, skip
                            continue

                        # Fetch current engine_id from Docker
                        info = await async_docker_call(client.info)
                        actual_engine_id = info.get('ID')

                        if not actual_engine_id:
                            continue

                        # Update if NULL or changed (VM clone detection)
                        if actual_engine_id != host_data['current_engine_id']:
                            with self.db.get_session() as session:
                                from database import DockerHostDB
                                db_host = session.query(DockerHostDB).filter_by(id=host_data['id']).first()
                                if db_host:
                                    old_value = db_host.engine_id
                                    db_host.engine_id = actual_engine_id
                                    session.commit()
                                    updated_count += 1

                                    if old_value is None:
                                        logger.info(f"Populated engine_id for {host_data['name']}: {actual_engine_id[:12]}...")
                                    else:
                                        logger.warning(
                                            f"Engine ID changed for {host_data['name']}! "
                                            f"Old: {old_value[:12]}..., New: {actual_engine_id[:12]}... "
                                            f"(Possible VM clone or Docker data migration)"
                                        )

                    except Exception as e:
                        logger.debug(f"Failed to check engine_id for {host_data['name']}: {e}")
                        continue

                if updated_count > 0:
                    logger.info(f"Engine ID validation: {updated_count} hosts updated")

                # Sleep for 6 hours before next check
                await asyncio.sleep(6 * 60 * 60)

            except Exception as e:
                logger.error(f"Error in engine_id validation: {e}", exc_info=True)
                # Wait 1 hour before retrying on error
                await asyncio.sleep(60 * 60)
