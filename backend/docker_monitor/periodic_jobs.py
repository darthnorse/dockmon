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

from database import DatabaseManager
from event_logger import EventLogger, EventSeverity, EventType
from auth.session_manager import session_manager
from utils.keys import make_composite_key, parse_composite_key
from utils.async_docker import async_docker_call
from updates.dockmon_update_checker import get_dockmon_update_checker

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

                # Clean up stale container state dictionaries (prevent memory leak)
                if self.monitor:
                    await self.monitor.cleanup_stale_container_state()

                # Clean up stale pull progress entries (defense-in-depth for crashed pulls)
                # Local import to break circular dependency: periodic_jobs ↔ monitor ↔ update_executor
                from updates.update_executor import get_update_executor
                update_executor = get_update_executor()
                if update_executor:
                    await update_executor.cleanup_stale_pull_progress()

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

                # Clean up orphaned deployment metadata (for containers deleted outside DockMon)
                # Part of deployment v2.1 remediation (Phase 1.6)
                deployment_metadata_cleaned = self.db.cleanup_orphaned_deployment_metadata(current_container_keys)
                if deployment_metadata_cleaned > 0:
                    self.event_logger.log_system_event(
                        "Deployment Metadata Cleanup",
                        f"Cleaned up {deployment_metadata_cleaned} orphaned deployment metadata entries",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

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

                # Clean up old Docker images (based on retention policy)
                images_cleaned = await self.cleanup_old_images()
                if images_cleaned > 0:
                    self.event_logger.log_system_event(
                        "Image Cleanup",
                        f"Removed {images_cleaned} old/dangling Docker images",
                        EventSeverity.INFO,
                        EventType.STARTUP
                    )

                # Check SSL certificate expiry and regenerate if needed
                cert_regenerated = await self.check_certificate_expiry()
                if cert_regenerated:
                    logger.info("Certificate was regenerated during maintenance")

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
                    # Get all containers (including stopped) to check which images are in use
                    containers = await async_docker_call(client.containers.list, all=True)
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
        Check for DockMon updates once (called on startup).
        Does not loop - just runs a single check.
        """
        try:
            logger.info("Checking for DockMon updates on startup...")

            checker = get_dockmon_update_checker(self.db)
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

        except Exception as e:
            logger.warning(f"Error checking for DockMon updates on startup: {e}")

    async def check_dockmon_updates_periodic(self):
        """
        Periodic task: Check for DockMon application updates from GitHub.
        Runs every 6 hours (hardcoded).

        This is separate from container update checks (which run daily at configured time).
        Checks GitHub releases for new DockMon versions and caches result in database.
        Frontend polls settings to detect updates and show notification banner.
        """
        while True:
            try:
                logger.debug("Running periodic DockMon update check...")

                checker = get_dockmon_update_checker(self.db)
                result = await checker.check_for_update()

                if result.get('update_available'):
                    logger.info(
                        f"DockMon update available: "
                        f"{result['current_version']} → {result['latest_version']}"
                    )
                    # Frontend will detect via settings polling
                elif result.get('error'):
                    logger.warning(f"DockMon update check failed: {result['error']}")
                else:
                    logger.debug(
                        f"DockMon is up to date: {result['current_version']}"
                    )

                # Sleep for 6 hours before next check
                await asyncio.sleep(6 * 60 * 60)

            except Exception as e:
                logger.error(f"Error in DockMon update checker: {e}", exc_info=True)
                # Wait 1 hour before retrying on error
                await asyncio.sleep(60 * 60)
