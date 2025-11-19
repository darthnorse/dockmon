"""
Update Executor Service

Handles the execution of container updates:
1. Pull new image
2. Stop old container
3. Recreate container with same config
4. Verify health
5. Rollback if health check fails
"""

import asyncio
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Optional, Any, Tuple
import docker
from sqlalchemy.exc import IntegrityError

from database import DatabaseManager, ContainerUpdate, AutoRestartConfig, ContainerDesiredState, ContainerHttpHealthCheck, GlobalSettings, DeploymentMetadata, TagAssignment
from event_bus import Event, EventType as BusEventType, get_event_bus
from utils.async_docker import async_docker_call
from utils.container_health import wait_for_container_health
from utils.image_pull_progress import ImagePullProgress
from utils.keys import make_composite_key, parse_composite_key
from utils.network_helpers import manually_connect_networks
from utils.cache import CACHE_REGISTRY
from updates.container_validator import ContainerValidator, ValidationResult

logger = logging.getLogger(__name__)

# Constants for internal DockMon metadata keys (same as stack_orchestrator)
_MANUAL_NETWORKS_KEY = '_dockmon_manual_networks'
_MANUAL_NETWORKING_CONFIG_KEY = '_dockmon_manual_networking_config'

# Docker container ID length (short format)
CONTAINER_ID_SHORT_LENGTH = 12


class UpdateExecutor:
    """
    Service that executes container updates with automatic rollback.

    Workflow:
    1. Verify update is available and auto-update is enabled
    2. Pull new image
    3. Get current container configuration
    4. Stop and rename old container to backup (for rollback capability)
    5. Create new container with same config but new image
    6. Wait for health check
    7. Update database with new container ID (if health check passes)
    8. Emit success event and cleanup backup
    9. If health check fails or error: rollback to backup and emit failure event
    """

    def __init__(self, db: DatabaseManager, monitor=None):
        self.db = db
        self.monitor = monitor
        self.updating_containers = set()  # Track containers currently being updated (format: "host_id:container_id")
        self._update_lock = threading.Lock()  # Lock for atomic check-and-set operations

        # Track active image pulls for WebSocket reconnection
        # Format: {"{host_id}:{container_id}": {"overall_progress": 80, "layers": [...], "speed_mbps": 12.5, "updated": timestamp}}
        self._active_pulls: Dict[str, Dict] = {}
        self._active_pulls_lock = threading.Lock()  # Thread-safe access to _active_pulls (main loop + thread pool)

        # Store reference to the main event loop for thread-safe coroutine scheduling
        # CRITICAL: asyncio.get_event_loop() is unreliable in thread pool (Python 3.11+)
        # This prevents "RuntimeError: no current event loop in thread" errors
        self.loop = asyncio.get_event_loop()

        # Initialize shared image pull progress tracker (shared with deployment system)
        # Callback updates _active_pulls for WebSocket reconnection support
        self.image_pull_tracker = ImagePullProgress(
            self.loop,
            monitor.manager if monitor and hasattr(monitor, 'manager') else None,
            progress_callback=self._store_pull_progress
        )

    def is_container_updating(self, host_id: str, container_id: str) -> bool:
        """Check if a container is currently being updated"""
        composite_key = make_composite_key(host_id, container_id)
        return composite_key in self.updating_containers

    def _store_pull_progress(self, host_id: str, entity_id: str, progress_data: Dict):
        """
        Callback for ImagePullProgress to store progress in _active_pulls.

        Used for WebSocket reconnection - newly connected clients get current progress.
        Thread-safe via _active_pulls_lock.
        """
        composite_key = make_composite_key(host_id, entity_id)
        with self._active_pulls_lock:
            self._active_pulls[composite_key] = {
                'host_id': host_id,
                'container_id': entity_id,
                **progress_data
            }

    def _get_registry_credentials(self, image_name: str) -> Optional[Dict[str, str]]:
        """Get credentials for registry from image name (delegates to shared utility)."""
        from utils.registry_credentials import get_registry_credentials
        return get_registry_credentials(self.db, image_name)

    async def execute_auto_updates(self) -> Dict[str, int]:
        """
        Execute auto-updates for all containers that:
        - Have auto_update_enabled = True
        - Have update_available = True

        Returns:
            Dict with keys: total, attempted, successful, failed
        """
        logger.info("Starting auto-update execution cycle")

        stats = {
            "total": 0,
            "attempted": 0,
            "successful": 0,
            "failed": 0,
        }

        # Get all containers with auto-update enabled and updates available
        # Extract data and close session BEFORE async operations
        updates_data = []
        with self.db.get_session() as session:
            updates = session.query(ContainerUpdate).filter_by(
                auto_update_enabled=True,
                update_available=True
            ).all()

            stats["total"] = len(updates)
            logger.info(f"Found {len(updates)} containers with auto-update enabled and updates available")

            # Extract data we need while session is open
            for update_record in updates:
                updates_data.append(update_record)

        # Session is now closed - safe for async operations

        # Detect dependency conflicts BEFORE starting updates
        # Fail fast if batch contains both a provider and its dependent
        from updates.dependency_analyzer import DependencyConflictDetector

        # Extract container IDs for conflict detection
        container_ids = [record.container_id for record in updates_data]
        detector = DependencyConflictDetector(self.monitor)
        dependency_conflict = detector.check_batch(container_ids)

        if dependency_conflict:
            logger.error(f"Dependency conflict detected: {dependency_conflict}")
            stats["failed"] = len(updates_data)
            return stats

        # Implement bounded concurrency to update multiple containers in parallel
        # but avoid overwhelming the system
        MAX_CONCURRENT_UPDATES = 3  # TODO: Make this configurable in global settings

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPDATES)

        async def update_with_semaphore(update_record):
            """Execute single update with semaphore to limit concurrency"""
            async with semaphore:
                # Parse composite key
                try:
                    host_id, container_id = parse_composite_key(update_record.container_id)
                except ValueError as e:
                    logger.error(f"Invalid composite key format: {update_record.container_id} - {e}")
                    return {"status": "failed", "reason": "invalid_key"}

                try:
                    # Execute the update
                    success = await self.update_container(host_id, container_id, update_record)

                    if success:
                        logger.info(f"Successfully updated container {container_id} on host {host_id}")
                        return {"status": "successful", "container_id": container_id, "host_id": host_id}
                    else:
                        logger.error(f"Failed to update container {container_id} on host {host_id}")
                        return {"status": "failed", "container_id": container_id, "host_id": host_id}

                except Exception as e:
                    logger.error(f"Error updating container {container_id} on host {host_id}: {e}", exc_info=True)
                    return {"status": "failed", "container_id": container_id, "host_id": host_id, "error": str(e)}

        # Execute all updates with bounded parallelism
        tasks = [update_with_semaphore(record) for record in updates_data]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results
        for result in results:
            stats["attempted"] += 1
            if isinstance(result, Exception):
                logger.error(f"Unexpected exception during update: {result}", exc_info=result)
                stats["failed"] += 1
            elif isinstance(result, dict):
                if result.get("status") == "successful":
                    stats["successful"] += 1
                else:
                    stats["failed"] += 1
            else:
                logger.error(f"Unexpected result type: {type(result)}")
                stats["failed"] += 1

        logger.info(f"Auto-update execution complete (parallel, max={MAX_CONCURRENT_UPDATES}): {stats}")
        return stats

    async def update_container(
        self,
        host_id: str,
        container_id: str,
        update_record: ContainerUpdate,
        force: bool = False,
        force_warn: bool = False
    ) -> bool:
        """
        Execute update for a single container.

        Args:
            host_id: Host UUID
            container_id: Container short ID (12 chars)
            update_record: ContainerUpdate database record
            force: If True, skip ALL validation (admin override)
            force_warn: If True, allow WARN containers but still block BLOCK containers (user confirmation)

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Executing update for container {container_id} on host {host_id} (force={force}, force_warn={force_warn})")

        composite_key = make_composite_key(host_id, container_id)

        # Atomic check-and-set to prevent concurrent updates
        with self._update_lock:
            if composite_key in self.updating_containers:
                logger.warning(f"Container {container_id} is already being updated, rejecting concurrent update")
                return False
            self.updating_containers.add(composite_key)

        # Track backup for rollback capability
        backup_container = None
        backup_name = ''
        new_container = None
        new_container_id = None
        update_committed = False  # Track if database was successfully updated

        try:
            # Get Docker client for this host
            docker_client = await self._get_docker_client(host_id)
            if not docker_client:
                error_message = "Container update failed: Docker client unavailable for host"
                logger.error(f"Could not get Docker client for host {host_id}")

                # Emit UPDATE_FAILED event (use container_id as name fallback)
                try:
                    await self._emit_update_failed_event(
                        host_id,
                        container_id,
                        container_id,  # Use ID as name fallback
                        error_message
                    )
                except Exception as e:
                    logger.error(f"Could not emit failure event: {e}")

                return False

            # Get container object directly from Docker (avoids expensive monitor.get_containers() call)
            # This prevents race conditions during batch updates where containers are being recreated
            try:
                old_container = await async_docker_call(docker_client.containers.get, container_id)
                container_name = old_container.name
            except docker.errors.NotFound:
                error_message = "Container update failed: Container not found"
                logger.error(f"Container not found: {container_id} on host {host_id}")

                # Emit UPDATE_FAILED event
                await self._emit_update_failed_event(
                    host_id,
                    container_id,
                    container_id,  # Use ID as name fallback
                    error_message
                )

                return False
            except Exception as e:
                error_message = f"Container update failed: Error getting container: {e}"
                logger.error(f"Error getting container {container_id} on host {host_id}: {e}")

                # Emit UPDATE_FAILED event
                await self._emit_update_failed_event(
                    host_id,
                    container_id,
                    container_id,  # Use ID as name fallback
                    error_message
                )

                return False

            # Priority 0: Block DockMon self-update (ALWAYS, even with force=True)
            # Defense-in-depth: protect at executor layer in case API layer is bypassed
            container_name_lower = container_name.lower()
            if container_name_lower == 'dockmon' or container_name_lower.startswith('dockmon-'):
                error_message = "DockMon cannot update itself. Please update manually by pulling the new image and restarting the container."
                logger.warning(f"Blocked self-update attempt for DockMon container '{container_name}' at executor layer")

                # Emit UPDATE_FAILED event
                await self._emit_update_failed_event(
                    host_id,
                    container_id,
                    container_name,
                    error_message
                )

                return False

            # Validate update is allowed (unless force=True)
            if not force:
                container_labels = old_container.labels or {}

                # Perform validation check
                with self.db.get_session() as session:
                    validator = ContainerValidator(session)
                    validation_result = validator.validate_update(
                        host_id=host_id,
                        container_id=container_id,
                        container_name=container_name,
                        image_name=update_record.current_image,
                        labels=container_labels
                    )

                # Handle validation results
                if validation_result.result == ValidationResult.BLOCK:
                    error_message = f"Container update blocked: {validation_result.reason}"
                    logger.warning(f"Update blocked for {container_name}: {validation_result.reason}")

                    # Emit UPDATE_FAILED event
                    await self._emit_update_failed_event(
                        host_id,
                        container_id,
                        container_name,
                        error_message
                    )

                    return False

                elif validation_result.result == ValidationResult.WARN:
                    # WARN requires user confirmation
                    # If force_warn=True, user has confirmed - allow update
                    # If force_warn=False, skip update (safety for auto-updates)
                    if not force_warn:
                        logger.info(
                            f"Skipping update for {container_name}: {validation_result.reason} "
                            f"(requires user confirmation - set force_warn=True to proceed)"
                        )

                        # Emit warning event (non-critical)
                        await self._emit_update_warning_event(
                            host_id,
                            container_id,
                            container_name,
                            validation_result.reason
                        )

                        return False
                    else:
                        # force_warn=True - user has confirmed, proceed with update
                        logger.info(
                            f"Proceeding with update for {container_name} despite warning: {validation_result.reason} "
                            f"(force_warn=True - user confirmed)"
                        )

                # ValidationResult.ALLOW - proceed with update
                logger.debug(f"Update allowed for {container_name}: {validation_result.reason}")
            else:
                logger.info(f"Skipping validation for {container_name} (force=True)")

            # Emit UPDATE_STARTED event (audit trail)
            await self._emit_update_started_event(
                host_id,
                container_id,
                container_name,
                update_record.latest_image
            )

            # Step 1: Pull new image
            logger.info(f"Pulling new image: {update_record.latest_image}")
            await self._broadcast_progress(host_id, container_id, "pulling", 20, "Starting image pull")

            # Look up registry credentials for authenticated pulls
            auth_config = self._get_registry_credentials(update_record.latest_image)
            if auth_config:
                logger.info(f"Using registry credentials for image pull: {update_record.latest_image}")
            else:
                logger.warning(f"No registry credentials found for image: {update_record.latest_image}")

            try:
                # Use shared ImagePullProgress for detailed layer tracking (same as deployment system)
                await self.image_pull_tracker.pull_with_progress(
                    docker_client,
                    update_record.latest_image,
                    host_id,
                    container_id,
                    auth_config=auth_config,
                    event_type="container_update_layer_progress"
                )
            except Exception as streaming_error:
                logger.warning(f"Streaming pull failed, falling back to simple pull: {streaming_error}")
                # Fallback to old method (still works, just no detailed progress)
                await self._pull_image(docker_client, update_record.latest_image, auth_config=auth_config)

            # Emit UPDATE_PULL_COMPLETED event (audit trail)
            await self._emit_update_pull_completed_event(
                host_id,
                container_id,
                container_name,
                update_record.latest_image
            )

            # Step 1b: Inspect new image to get labels for intelligent merge
            logger.info(f"Inspecting new image labels: {update_record.latest_image}")
            try:
                new_image = await async_docker_call(
                    docker_client.images.get,
                    update_record.latest_image
                )
                new_image_labels = new_image.attrs.get("Config", {}).get("Labels", {}) or {}
                logger.debug(f"New image has {len(new_image_labels)} labels")
            except Exception as e:
                # If image inspection fails (network issue, image deleted, etc.),
                # proceed with old labels rather than crashing the update
                logger.warning(
                    f"Failed to inspect new image labels: {e}. "
                    f"Proceeding with old container labels only."
                )
                new_image_labels = {}  # Fallback: no merge, preserve old labels

            # Step 2a: Find dependent containers (network_mode: container:this_container)
            # These must be recreated after update to point to new container ID
            logger.info(f"Checking for dependent containers")
            dependent_containers = await self._get_dependent_containers(
                docker_client,
                old_container,
                container_name,
                container_id
            )
            if dependent_containers:
                logger.info(
                    f"Found {len(dependent_containers)} dependent container(s): "
                    f"{[dep['name'] for dep in dependent_containers]}"
                )

            # Step 2b: Get full container configuration
            # (reuse old_container fetched during validation to avoid duplicate API call)
            logger.info("Getting container configuration")
            await self._broadcast_progress(host_id, container_id, "configuring", 35, "Reading container configuration")
            container_config = await self._extract_container_config(old_container, new_image_labels=new_image_labels)

            # Step 3: Create backup of old container (stop + rename for rollback)
            logger.info(f"Creating backup of {container_name}")
            await self._broadcast_progress(host_id, container_id, "backup", 50, "Creating backup for rollback")
            backup_container, backup_name = await self._rename_container_to_backup(
                docker_client,
                old_container,
                container_name
            )

            if not backup_container:
                error_message = f"Container update failed: unable to create backup (container may be stuck or unresponsive)"
                logger.error(f"Failed to create backup for {container_name}, aborting update")

                # Emit update failure event so alerts fire
                await self._emit_update_failed_event(
                    host_id,
                    container_id,
                    container_name,
                    error_message
                )
                return False

            logger.info(f"Backup created: {backup_name}")

            # Emit BACKUP_CREATED event (audit trail)
            await self._emit_backup_created_event(
                host_id,
                container_id,
                container_name,
                backup_name
            )

            # Step 4: Create new container with updated image
            logger.info(f"Creating new container with image {update_record.latest_image}")
            await self._broadcast_progress(host_id, container_id, "creating", 65, "Creating new container")
            new_container = await self._create_container(
                docker_client,
                update_record.latest_image,
                container_config
            )
            # Capture SHORT ID (12 chars) for event emission
            new_container_id = new_container.short_id

            # Step 5: Start new container (IMMEDIATELY to prevent backup from auto-restarting and stealing ports)
            logger.info(f"Starting new container {container_name}")
            await async_docker_call(new_container.start)
            # Broadcast progress AFTER start completes (eliminates timing gap that allows backup auto-restart)
            await self._broadcast_progress(host_id, container_id, "starting", 80, "Starting new container")

            # Step 6: Wait for health check
            health_check_timeout = 120  # 2 minutes default
            with self.db.get_session() as session:
                settings = session.query(GlobalSettings).first()
                if settings:
                    health_check_timeout = settings.health_check_timeout_seconds

            logger.info(f"Waiting for health check (timeout: {health_check_timeout}s)")
            await self._broadcast_progress(host_id, container_id, "health_check", 90, "Waiting for health check")
            is_healthy = await wait_for_container_health(
                docker_client,
                new_container_id,  # Use SHORT ID (12 chars) for consistency
                timeout=health_check_timeout
            )

            if not is_healthy:
                logger.error(f"Health check failed for {container_name}, initiating rollback")
                error_message = f"Container update failed: health check timeout after {health_check_timeout}s"

                # Attempt rollback to restore old container
                rollback_success = await self._rollback_container(
                    docker_client,
                    backup_container,
                    backup_name,
                    container_name,
                    new_container
                )

                if rollback_success:
                    error_message += " - Successfully rolled back to previous version"
                    logger.warning(f"Rollback successful for {container_name}")

                    # Emit ROLLBACK_COMPLETED event (audit trail)
                    await self._emit_rollback_completed_event(
                        host_id,
                        container_id,
                        container_name
                    )
                else:
                    error_message += f" - CRITICAL: Rollback failed, manual intervention required for backup: {backup_name}"
                    logger.critical(f"Rollback failed for {container_name}")

                # Emit update failure event via EventBus (which handles database logging)
                await self._emit_update_failed_event(
                    host_id,
                    container_id,
                    container_name,
                    error_message
                )
                return False

            # Step 7: Update database - mark update as applied
            with self.db.get_session() as session:
                old_composite_key = make_composite_key(host_id, container_id)
                new_composite_key = make_composite_key(host_id, new_container_id)

                record = session.query(ContainerUpdate).filter_by(
                    container_id=old_composite_key
                ).first()

                if record:
                    # CRITICAL: Update container_id to new container's ID
                    # After update, the container has a new Docker ID

                    # Race condition fix (Issue #30):
                    # Delete any existing record with new container ID that may have been created
                    # by the update checker while the update was in progress
                    conflicting_record = session.query(ContainerUpdate).filter_by(
                        container_id=new_composite_key
                    ).first()
                    if conflicting_record:
                        logger.warning(
                            f"Deleting conflicting ContainerUpdate record for {new_composite_key} "
                            f"(likely created by update checker during update)"
                        )
                        session.delete(conflicting_record)
                        session.flush()  # Ensure deletion is committed before update

                    # Update 1: ContainerUpdate table
                    record.container_id = new_composite_key
                    record.update_available = False
                    record.current_image = update_record.latest_image
                    record.current_digest = update_record.latest_digest
                    record.last_updated_at = datetime.now(timezone.utc)
                    record.updated_at = datetime.now(timezone.utc)

                    # Update 2: AutoRestartConfig table (uses SHORT ID only)
                    session.query(AutoRestartConfig).filter_by(
                        host_id=host_id,
                        container_id=container_id  # OLD short ID
                    ).update({
                        "container_id": new_container_id,  # NEW short ID
                        "updated_at": datetime.now(timezone.utc)
                    })

                    # Update 3: ContainerDesiredState table (uses SHORT ID only)
                    session.query(ContainerDesiredState).filter_by(
                        host_id=host_id,
                        container_id=container_id  # OLD short ID
                    ).update({
                        "container_id": new_container_id,  # NEW short ID
                        "updated_at": datetime.now(timezone.utc)
                    })

                    # Update 4: ContainerHttpHealthCheck table (uses COMPOSITE KEY)
                    session.query(ContainerHttpHealthCheck).filter_by(
                        container_id=old_composite_key  # OLD composite key
                    ).update({
                        "container_id": new_composite_key  # NEW composite key
                    })

                    # Update 5: DeploymentMetadata table (uses COMPOSITE KEY)
                    # Part of deployment v2.1 remediation (Phase 1.5)
                    # When a container is recreated during update, preserve its deployment linkage
                    session.query(DeploymentMetadata).filter_by(
                        container_id=old_composite_key  # OLD composite key
                    ).update({
                        "container_id": new_composite_key,  # NEW composite key
                        "updated_at": datetime.now(timezone.utc)
                    })

                    # Update 6: TagAssignment table (uses subject_id as composite key for containers)
                    # When a container is recreated during update, preserve its tag assignments
                    # DEFENSIVE: Check if reattachment already created assignments for new container (GitHub Issue #44)
                    # Prevents race condition between container_discovery reattachment and update executor migration
                    new_tag_count = session.query(TagAssignment).filter(
                        TagAssignment.subject_type == 'container',
                        TagAssignment.subject_id == new_composite_key
                    ).count()

                    if new_tag_count > 0:
                        # Reattachment already created tag assignments for new container
                        # Delete orphaned old assignments (cleanup)
                        logger.debug(f"Reattachment already migrated {new_tag_count} tags, cleaning up old assignments")
                        session.query(TagAssignment).filter(
                            TagAssignment.subject_type == 'container',
                            TagAssignment.subject_id == old_composite_key
                        ).delete()
                    else:
                        # Reattachment didn't run yet (unlikely), migrate tags ourselves
                        logger.debug("Migrating tag assignments from old to new container")
                        session.query(TagAssignment).filter(
                            TagAssignment.subject_type == 'container',
                            TagAssignment.subject_id == old_composite_key
                        ).update({
                            "subject_id": new_composite_key,  # NEW composite key
                            "last_seen_at": datetime.now(timezone.utc)
                        })

                    # Set commit flag BEFORE commit to prevent race condition (Issue #6 fix)
                    # If exception occurs after commit but before flag setting, rollback would incorrectly execute
                    update_committed = True

                    try:
                        session.commit()
                        logger.debug(
                            f"Updated database records from {old_composite_key} to {new_composite_key}: "
                            f"ContainerUpdate, AutoRestartConfig, ContainerDesiredState, ContainerHttpHealthCheck, DeploymentMetadata, TagAssignment"
                        )
                    except IntegrityError as integrity_error:
                        # Handle tag reattachment race condition (GitHub Issue #44 edge case)
                        # If reattachment commits tags in the millisecond window between our check and update,
                        # the UPDATE will fail with IntegrityError. This is NOT a real failure.
                        if "tag_assignments" in str(integrity_error).lower():
                            # Tags were migrated by reattachment during the race window
                            # Container update succeeded, tags exist (via reattachment) - continue as success
                            session.rollback()
                            logger.debug(
                                f"Tag migration race detected for {container_name}: "
                                f"reattachment already migrated tags during update. Continuing as success."
                            )
                            # Note: update_committed stays True - container was updated successfully
                        else:
                            # Different IntegrityError (unexpected) - treat as failure
                            update_committed = False
                            logger.error(f"Database integrity error for {container_name}: {integrity_error}", exc_info=True)
                            raise  # Trigger rollback in outer exception handler
                    except Exception as commit_error:
                        # Other database errors - treat as failure
                        update_committed = False
                        logger.error(f"Database commit failed for {container_name}: {commit_error}", exc_info=True)
                        raise  # Re-raise to trigger rollback in outer exception handler

            # Invalidate image digest cache for the old image (Issue #62)
            # This ensures the next update check will fetch fresh data from registry
            try:
                old_image = update_record.current_image
                if old_image:
                    # Invalidate all cache entries for this image (any platform)
                    invalidated = self.db.invalidate_image_cache(old_image)
                    if invalidated:
                        logger.debug(f"Invalidated {invalidated} cache entries for {old_image}")
            except Exception as cache_error:
                # Non-critical - just log and continue
                logger.warning(f"Failed to invalidate image cache: {cache_error}")

            # Notify frontend that container ID changed (keeps modal open during updates)
            await self._broadcast_container_recreated(
                host_id,
                old_composite_key,
                new_composite_key,
                container_name
            )

            # Step 8: Emit update completion event via EventBus (which handles database logging)
            await self._emit_update_completed_event(
                host_id,
                new_container_id,
                container_name,
                update_record.current_image,
                update_record.latest_image,
                update_record.current_digest,
                update_record.latest_digest
            )

            # Step 9: Recreate dependent containers (if any)
            # These are containers using network_mode: container:this_container
            # They must be recreated to point to the new container ID
            if dependent_containers:
                logger.info(f"Recreating {len(dependent_containers)} dependent container(s)")
                failed_dependents = []

                for dep in dependent_containers:
                    try:
                        logger.info(f"Recreating dependent container: {dep['name']}")
                        success = await self._recreate_dependent_container(
                            docker_client,
                            dep,
                            new_container.id  # Full container ID for network_mode
                        )
                        if not success:
                            failed_dependents.append(dep['name'])
                    except Exception as dep_error:
                        logger.error(f"Failed to recreate dependent {dep['name']}: {dep_error}", exc_info=True)
                        failed_dependents.append(dep['name'])

                if failed_dependents:
                    logger.warning(
                        f"Update succeeded but failed to recreate dependent containers: {', '.join(failed_dependents)}. "
                        f"Manual recreation may be required."
                    )
                    # Don't fail the update - main container updated successfully
                    # User can manually recreate dependents if needed
                else:
                    logger.info(f"Successfully recreated all {len(dependent_containers)} dependent container(s)")

            # Step 10: Cleanup backup container on success
            logger.info(f"Update successful, cleaning up backup container {backup_name}")
            await self._cleanup_backup_container(docker_client, backup_container, backup_name)

            # Step 11: Invalidate cache to ensure fresh container discovery
            for name, fn in CACHE_REGISTRY.items():
                fn.invalidate()
                logger.debug(f"Invalidated cache: {name}")

            logger.info(f"Successfully updated container {container_name}")
            await self._broadcast_progress(host_id, new_container_id, "completed", 100, "Update completed successfully")
            return True

        except Exception as e:
            logger.error(f"Error executing update for {container_name if 'container_name' in locals() else container_id}: {e}", exc_info=True)

            # Check if update was already committed to database
            if update_committed:
                # Update succeeded but post-update operations (event emission, cleanup) failed
                # DO NOT ROLLBACK - the update is complete and database is updated
                logger.warning(
                    f"Update succeeded for {container_name if 'container_name' in locals() else container_id}, "
                    f"but post-update operations failed: {e}. "
                    f"Container is running with new image, but backup cleanup or event emission failed."
                )
                # Return True because update succeeded (container updated correctly)
                # Post-commit failures are non-critical (backup cleanup, event emission)
                return True

            # Update failed before commit - safe to rollback
            error_message = f"Container update failed: {str(e)}"

            # Attempt rollback if we have a backup
            if backup_container and 'docker_client' in locals() and 'container_name' in locals():
                logger.warning(f"Attempting rollback due to exception for {container_name}")
                rollback_success = await self._rollback_container(
                    docker_client,
                    backup_container,
                    backup_name,
                    container_name,
                    new_container
                )

                if rollback_success:
                    error_message += " - Successfully rolled back to previous version"
                    logger.warning(f"Rollback successful after exception for {container_name}")

                    # Emit ROLLBACK_COMPLETED event (audit trail)
                    await self._emit_rollback_completed_event(
                        host_id,
                        container_id,
                        container_name
                    )
                else:
                    error_message += f" - CRITICAL: Rollback failed, manual intervention required for backup: {backup_name}"
                    logger.critical(f"Rollback failed after exception for {container_name}")

            # Emit update failure event via EventBus (which handles database logging)
            if 'container_name' in locals():
                await self._emit_update_failed_event(
                    host_id,
                    container_id,
                    container_name,
                    error_message
                )
            return False

        finally:
            # Always remove from updating set when done (whether success or failure)
            with self._update_lock:
                self.updating_containers.discard(composite_key)
            logger.debug(f"Removed {composite_key} from updating containers set")

            # Re-evaluate alerts that may have been suppressed during the update
            # Use new container ID if available, otherwise fall back to old ID
            eval_container_id = new_container_id if 'new_container_id' in locals() else container_id
            await self._re_evaluate_alerts_after_update(
                host_id,
                eval_container_id,
                container_name if 'container_name' in locals() else container_id
            )

    async def _broadcast_progress(
        self,
        host_id: str,
        container_id: str,
        stage: str,
        progress: int,
        message: str
    ):
        """Broadcast update progress to WebSocket clients"""
        try:
            if not self.monitor:
                logger.warning(f"No monitor available for progress broadcast: {stage}")
                return

            if not hasattr(self.monitor, 'manager'):
                logger.warning(f"No manager on monitor for progress broadcast: {stage}")
                return

            logger.info(f"Broadcasting update progress: {stage} ({progress}%) - {message}")
            await self.monitor.manager.broadcast({
                "type": "container_update_progress",
                "data": {
                    "host_id": host_id,
                    "container_id": container_id,
                    "stage": stage,
                    "progress": progress,
                    "message": message
                }
            })
            logger.info(f"Progress broadcast completed: {stage} at {progress}%")
        except Exception as e:
            logger.error(f"Error broadcasting progress: {e}", exc_info=True)

    async def _get_docker_client(self, host_id: str) -> Optional[docker.DockerClient]:
        """Get Docker client for a specific host from the monitor's client pool"""
        if not self.monitor:
            return None

        try:
            # Use the monitor's existing Docker client for this host
            # The monitor manages clients properly with persistent TLS certs
            client = self.monitor.clients.get(host_id)
            if not client:
                logger.warning(f"No Docker client found for host {host_id}")
                return None
            return client

        except Exception as e:
            logger.error(f"Error getting Docker client for host {host_id}: {e}")
            return None

    async def _pull_image(self, client: docker.DockerClient, image: str, auth_config: dict = None, timeout: int = 1800):
        """
        Pull Docker image with timeout and optional authentication.

        Args:
            client: Docker client instance
            image: Image name to pull
            auth_config: Optional Docker registry auth config dict with 'username' and 'password'
            timeout: Timeout in seconds (default: 1800 = 30 minutes)

        Raises:
            asyncio.TimeoutError: If pull takes longer than timeout
            Exception: If pull fails for other reasons
        """
        try:
            # Use async wrapper with timeout to prevent event loop blocking and handle large images
            pull_kwargs = {}
            if auth_config:
                pull_kwargs['auth_config'] = auth_config
                logger.debug(f"Pulling {image} with authentication")

            await asyncio.wait_for(
                async_docker_call(client.images.pull, image, **pull_kwargs),
                timeout=timeout
            )
            logger.debug(f"Successfully pulled image {image}")
        except asyncio.TimeoutError:
            error_msg = f"Image pull timed out after {timeout} seconds for {image}"
            logger.error(error_msg)
            raise Exception(error_msg)
        except Exception as e:
            logger.error(f"Error pulling image {image}: {e}")
            raise

    def _merge_labels(
        self,
        old_labels: Dict[str, str],
        new_image_labels: Dict[str, str] = None
    ) -> Dict[str, str]:
        """
        Merge container labels for update operation.

        Strategy: Preserve all old labels, but override with fresh image labels.
        This ensures:
        - Image metadata labels (version, created, etc.) are updated
        - Compose labels (com.docker.compose.*) are preserved
        - DockMon tracking labels (dockmon.*) are preserved
        - User custom labels are preserved

        Note on label removal: Labels present in old container but not in new image
        are PRESERVED. We cannot distinguish between "user added" vs "old image had it",
        so preservation is safer (don't delete user data). Stale image labels are
        unlikely since images typically add labels, not remove them.

        Args:
            old_labels: Labels from old container
            new_image_labels: Labels from new image (optional)

        Returns:
            Merged labels dict
        """
        # Defensive: Handle None inputs (Docker returns None for no labels)
        if old_labels is None:
            old_labels = {}
        if new_image_labels is None:
            new_image_labels = {}

        if not new_image_labels:
            # No new image labels provided - return old labels
            return old_labels.copy() if old_labels else {}

        # Merge: old labels first, then override with new image labels
        # When same key exists in both, new_image_labels wins (image is source of truth)
        merged = {
            **old_labels,        # Preserve compose, dockmon, custom labels
            **new_image_labels   # Update image metadata labels
        }

        logger.debug(
            f"Label merge: {len(old_labels)} old + {len(new_image_labels)} image = "
            f"{len(merged)} merged"
        )

        return merged

    async def _extract_container_config(self, container, new_image_labels: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Extract container configuration for recreation.

        Args:
            container: Container object to extract config from
            new_image_labels: Optional dict of labels from new image (for merging during updates)

        Returns a dict with all necessary config to recreate the container.
        """
        attrs = container.attrs
        config = attrs["Config"]
        host_config = attrs["HostConfig"]
        networking = attrs["NetworkSettings"]

        def _extract_ipam_config(network_data):
            """
            Extract IPAM configuration only if user-configured (not auto-assigned).

            Returns IPAMConfig dict if IPs were user-configured, None otherwise.
            """
            # Only preserve IPs if IPAMConfig exists in original config
            # If IPAMConfig is null, IPs are auto-assigned by Docker
            if not network_data.get("IPAMConfig"):
                return None

            ipam_config = {}
            if network_data.get("IPAddress"):
                ipam_config["IPv4Address"] = network_data["IPAddress"]
            if network_data.get("GlobalIPv6Address"):
                ipam_config["IPv6Address"] = network_data["GlobalIPv6Address"]

            return ipam_config if ipam_config else None

        # Extract network_mode early to check for conflicts
        network_mode = host_config.get("NetworkMode")

        # Docker field conflicts - these combinations are rejected by Docker API
        # Handle during extraction to avoid runtime errors during container creation

        # hostname conflicts with network_mode: container:X
        # When using shared network mode, hostname comes from the network provider
        hostname = None
        if not (network_mode and network_mode.startswith("container:")):
            hostname = config.get("Hostname")

        # mac_address conflicts with network_mode: container:X
        # MAC address comes from the network provider in shared mode
        mac_address = None
        if not (network_mode and network_mode.startswith("container:")):
            mac_address = config.get("MacAddress")

        container_config = {
            "name": attrs["Name"].lstrip("/"),
            "hostname": hostname,
            "mac_address": mac_address,
            "user": config.get("User"),
            "detach": True,
            "stdin_open": config.get("OpenStdin", False),
            "tty": config.get("Tty", False),
            "environment": config.get("Env", []),
            "command": config.get("Cmd"),
            "entrypoint": config.get("Entrypoint"),
            "working_dir": config.get("WorkingDir"),
            "labels": self._merge_labels(
                old_labels=config.get("Labels", {}),
                new_image_labels=new_image_labels
            ),
            "ports": {},
            "volumes": {},
            "network": None,
            "restart_policy": host_config.get("RestartPolicy", {}),
            "privileged": host_config.get("Privileged", False),
            "cap_add": host_config.get("CapAdd"),
            "cap_drop": host_config.get("CapDrop"),
            "devices": host_config.get("Devices"),
            "security_opt": host_config.get("SecurityOpt"),
            "tmpfs": host_config.get("Tmpfs"),
            "ulimits": host_config.get("Ulimits"),
            "dns": host_config.get("Dns"),
            "extra_hosts": host_config.get("ExtraHosts"),
            "ipc_mode": host_config.get("IpcMode"),
            "pid_mode": host_config.get("PidMode"),
            "shm_size": host_config.get("ShmSize"),
            # Phase 2: Critical config preservation (Issue #64)
            "healthcheck": config.get("Healthcheck"),
            "runtime": host_config.get("Runtime"),
            "cpu_period": host_config.get("CpuPeriod"),
            "cpu_quota": host_config.get("CpuQuota"),
            "cpu_shares": host_config.get("CpuShares"),
            "cpuset_cpus": host_config.get("CpusetCpus"),
            "cpuset_mems": host_config.get("CpusetMems"),
            "mem_limit": host_config.get("Memory"),
            "mem_reservation": host_config.get("MemoryReservation"),
            "memswap_limit": host_config.get("MemorySwap"),
            "nano_cpus": host_config.get("NanoCpus"),
            "oom_kill_disable": host_config.get("OomKillDisable"),
            "pids_limit": host_config.get("PidsLimit"),
            # Phase 3: High priority config (Issue #64)
            "stop_timeout": host_config.get("StopTimeout"),
            "read_only": host_config.get("ReadonlyRootfs"),
            "sysctls": host_config.get("Sysctls"),
            "group_add": host_config.get("GroupAdd"),
            "log_config": host_config.get("LogConfig"),
            "userns_mode": host_config.get("UsernsMode"),
            "init": host_config.get("Init"),
            "domainname": config.get("Domainname"),
            "storage_opt": host_config.get("StorageOpt"),
        }

        # Extract port bindings (skip if using host networking - ports are ignored anyway)
        if host_config.get("PortBindings") and network_mode != "host":
            container_config["ports"] = host_config["PortBindings"]

        # Extract volume bindings from legacy Binds format
        # Issue #68: Track used destinations to prevent duplicate mount points
        used_destinations = set()

        if host_config.get("Binds"):
            for bind in host_config["Binds"]:
                parts = bind.split(":")
                if len(parts) >= 2:
                    host_path = parts[0]
                    container_path = parts[1]
                    mode = parts[2] if len(parts) > 2 else "rw"
                    # CRITICAL: Use host_path as key (where data lives on host)
                    # and container_path as bind value (where it mounts in container)
                    container_config["volumes"][host_path] = {
                        "bind": container_path,
                        "mode": mode
                    }
                    # Track this destination as used
                    used_destinations.add(container_path)

        # Extract mounts from modern Docker API (Mounts array)
        # This handles bind mounts and named volumes that may not be
        # present in the legacy Binds format
        mounts = attrs.get('Mounts', [])
        for mount in mounts:
            mount_type = mount.get('Type', '')
            source = mount.get('Source', '')
            # Handle both field names - Docker API returns 'Destination' for most mounts
            # but Docker Compose secrets use 'Target'
            destination = mount.get('Destination') or mount.get('Target', '')

            # Handle both Mode string and ReadOnly boolean
            # Docker secrets use ReadOnly: true, regular mounts use Mode: 'ro'
            if mount.get('ReadOnly'):
                mode = 'ro'
            elif mount.get('RW') is False:
                mode = 'ro'
            else:
                mode = mount.get('Mode') or 'rw'

            if mount_type == 'bind' and source and destination:
                # Bind mount: use host path as key
                # Issue #68: Skip if destination already used (prevents "Duplicate mount point" error)
                if destination in used_destinations:
                    logger.debug(f"Skipping duplicate destination bind mount: {source} -> {destination}")
                    continue
                # Skip if source already extracted from Binds
                if source in container_config["volumes"]:
                    logger.debug(f"Skipping duplicate bind mount: {source}")
                    continue
                container_config["volumes"][source] = {
                    "bind": destination,
                    "mode": mode
                }
                used_destinations.add(destination)
                logger.debug(f"Extracted bind mount: {source} -> {destination} ({mode})")
            elif mount_type == 'volume' and destination:
                # Named volume: use volume name (not source path)
                # Source is /var/lib/docker/volumes/name/_data but we need just the name
                volume_name = mount.get('Name', '')
                if not volume_name:
                    logger.debug(f"Skipping volume mount without name: {mount}")
                    continue
                # Issue #68: Skip if destination already used (prevents "Duplicate mount point" error)
                if destination in used_destinations:
                    logger.debug(f"Skipping duplicate destination volume: {volume_name} -> {destination}")
                    continue
                # Skip if already extracted from Binds
                if volume_name in container_config["volumes"]:
                    logger.debug(f"Skipping duplicate volume: {volume_name}")
                    continue
                container_config["volumes"][volume_name] = {
                    "bind": destination,
                    "mode": mode
                }
                used_destinations.add(destination)
                logger.debug(f"Extracted named volume: {volume_name} -> {destination} ({mode})")
            elif mount_type == 'bind':
                # Log skipped mounts for debugging
                logger.warning(
                    f"Skipping bind mount with missing source or destination: "
                    f"source={source}, destination={destination}, mount={mount}"
                )

        # Extract network configuration
        # CRITICAL: Preserve full endpoint configuration including static IPs
        # HYBRID APPROACH: Use same logic as stack_orchestrator for consistency
        networks = networking.get("Networks", {})
        if networks:
            # Filter out network_mode pseudo-networks (bridge, host, none)
            # These are represented as network_mode, not actual custom networks
            # Only preserve real custom networks created by users
            custom_networks = {k: v for k, v in networks.items() if k not in ['bridge', 'host', 'none']}

            if not custom_networks:
                # Only on default bridge network - don't preserve
                pass
            elif len(custom_networks) == 1:
                # Single custom network - check if it has advanced config
                network_name, network_data = list(custom_networks.items())[0]
                # Check for user-configured static IP (IPAMConfig), not auto-assigned IP (IPAddress)
                # Every container on a network has IPAddress, but only user-configured ones have IPAMConfig
                has_static_ip = bool(network_data.get("IPAMConfig"))

                # Preserve all aliases except container ID (12 chars - Docker auto-adds this)
                # We keep container name and service name aliases for Docker Compose service discovery
                all_aliases = network_data.get("Aliases", []) or []
                preserved_aliases = [a for a in all_aliases if len(a) != CONTAINER_ID_SHORT_LENGTH]

                if has_static_ip or preserved_aliases:
                    # Has config to preserve - use manual connection format
                    # BUT also set network to avoid creating on bridge
                    container_config["network"] = network_name

                    endpoint_config = {}

                    # Extract user-configured static IPs (not auto-assigned)
                    ipam_config = _extract_ipam_config(network_data)
                    if ipam_config:
                        endpoint_config["IPAMConfig"] = ipam_config
                        logger.debug(f"Preserving user-configured IP for {network_name}")

                    if preserved_aliases:
                        endpoint_config["Aliases"] = preserved_aliases
                        logger.debug(f"Preserving aliases for {network_name}: {preserved_aliases}")

                    if network_data.get("Links"):
                        endpoint_config["Links"] = network_data["Links"]

                    container_config[_MANUAL_NETWORKING_CONFIG_KEY] = {
                        "EndpointsConfig": {network_name: endpoint_config}
                    }
                    logger.debug(f"Extracted advanced network config for {network_name}")
                else:
                    # Simple single network - use 'network' parameter
                    container_config["network"] = network_name
                    logger.debug(f"Extracted simple network: {network_name}")

            else:
                # Multiple custom networks - use manual connection format
                endpoints_config = {}

                # Set first network as primary to avoid creating on bridge
                primary_network = list(custom_networks.keys())[0]
                container_config["network"] = primary_network

                for network_name, network_data in custom_networks.items():
                    endpoint_config = {}

                    # Extract user-configured static IPs (not auto-assigned)
                    ipam_config = _extract_ipam_config(network_data)
                    if ipam_config:
                        endpoint_config["IPAMConfig"] = ipam_config
                        logger.debug(f"Preserving user-configured IP for {network_name}")

                    # Extract ALL network aliases (filter out just container ID)
                    if network_data.get("Aliases"):
                        preserved_aliases = [
                            a for a in network_data["Aliases"]
                            if len(a) != CONTAINER_ID_SHORT_LENGTH
                        ]
                        if preserved_aliases:
                            endpoint_config["Aliases"] = preserved_aliases

                    # Extract links (legacy)
                    if network_data.get("Links"):
                        endpoint_config["Links"] = network_data["Links"]

                    endpoints_config[network_name] = endpoint_config

                container_config[_MANUAL_NETWORKING_CONFIG_KEY] = {
                    "EndpointsConfig": endpoints_config
                }
                logger.debug(f"Extracted multiple network config: {list(custom_networks.keys())}")

        # Extract network_mode (v2.1.8 - Quick Wins)
        # NOTE: devices, extra_hosts, cap_add, cap_drop already extracted above (lines 818-820, 825)
        if "NetworkMode" in host_config:
            network_mode = host_config["NetworkMode"]

            # Filter Docker auto-defaults
            # "default" = Docker's automatic setting (don't preserve)
            # Everything else = potentially user-set (preserve)
            if network_mode and network_mode not in ["default"]:
                # CRITICAL: Check for conflict with custom networks
                # Cannot have both network_mode and networking_config (static IPs, etc.)
                # Defense-in-depth: Check both manual networking AND simple network parameter
                # Note: container_config["network"] is set to None by default (line 816),
                # so we check for truthiness, not just existence
                if (_MANUAL_NETWORKING_CONFIG_KEY not in container_config and
                    not container_config.get("network")):
                    container_config["network_mode"] = network_mode
                    logger.debug(f"Extracted network_mode: {network_mode}")
                else:
                    logger.debug(
                        f"Container has custom network config, "
                        f"skipping network_mode extraction (mutually exclusive)"
                    )

        return container_config

    async def _create_container(
        self,
        client: docker.DockerClient,
        image: str,
        config: Dict[str, Any]
    ) -> Any:
        """
        Create new container with given config.

        Preserves all network configuration including static IPs, aliases, and links.
        Bug Fix: Manually connects networks since Docker SDK networking_config doesn't work.
        """
        try:
            # Extract manual network connection instructions (if present)
            manual_networks = config.pop(_MANUAL_NETWORKS_KEY, None)
            manual_networking_config = config.pop(_MANUAL_NETWORKING_CONFIG_KEY, None)

            # Build create parameters
            create_params = {
                "image": image,
                "name": config["name"],
                "hostname": config.get("hostname"),
                "user": config.get("user"),
                "detach": config.get("detach", True),
                "stdin_open": config.get("stdin_open", False),
                "tty": config.get("tty", False),
                "environment": config.get("environment"),
                "command": config.get("command"),
                "entrypoint": config.get("entrypoint"),
                "working_dir": config.get("working_dir"),
                "labels": config.get("labels"),
                "ports": config.get("ports"),
                "volumes": config.get("volumes"),
                "restart_policy": config.get("restart_policy"),
                "privileged": config.get("privileged", False),
                "cap_add": config.get("cap_add"),
                "cap_drop": config.get("cap_drop"),
                "devices": config.get("devices"),
                "security_opt": config.get("security_opt"),
                "tmpfs": config.get("tmpfs"),
                "ulimits": config.get("ulimits"),
                "dns": config.get("dns"),
                "extra_hosts": config.get("extra_hosts"),
                "ipc_mode": config.get("ipc_mode"),
                "pid_mode": config.get("pid_mode"),
                "shm_size": config.get("shm_size"),
                "network_mode": config.get("network_mode"),  # v2.1.8 - Quick Wins
                "mac_address": config.get("mac_address"),  # Issue #64 - Was extracted but not passed
                # Phase 2: Critical config preservation (Issue #64)
                "healthcheck": config.get("healthcheck"),
                "runtime": config.get("runtime"),
                "cpu_period": config.get("cpu_period"),
                "cpu_quota": config.get("cpu_quota"),
                "cpu_shares": config.get("cpu_shares"),
                "cpuset_cpus": config.get("cpuset_cpus"),
                "cpuset_mems": config.get("cpuset_mems"),
                "mem_limit": config.get("mem_limit"),
                "mem_reservation": config.get("mem_reservation"),
                "memswap_limit": config.get("memswap_limit"),
                "nano_cpus": config.get("nano_cpus"),
                "oom_kill_disable": config.get("oom_kill_disable"),
                "pids_limit": config.get("pids_limit"),
                # Phase 3: High priority config (Issue #64)
                # Note: stop_timeout is not supported by Docker SDK containers.create()
                # It can only be set when calling container.stop(timeout=N)
                "read_only": config.get("read_only"),
                "sysctls": config.get("sysctls"),
                "group_add": config.get("group_add"),
                "log_config": config.get("log_config"),
                "userns_mode": config.get("userns_mode"),
                "init": config.get("init"),
                "domainname": config.get("domainname"),
                "storage_opt": config.get("storage_opt"),
            }

            # CRITICAL: Network configuration (Bug Fix: Use hybrid approach)
            # Simple single network can use 'network' parameter
            if config.get("network"):
                create_params["network"] = config["network"]

            # Create container
            container = await async_docker_call(
                client.containers.create,
                **create_params
            )

            # Manually connect to networks if needed (Bug fix: networking_config doesn't work)
            # This must happen BEFORE starting the container
            try:
                await manually_connect_networks(
                    container=container,
                    manual_networks=manual_networks,
                    manual_networking_config=manual_networking_config,
                    client=client,
                    async_docker_call=async_docker_call
                )
            except Exception:
                # Clean up: remove container since we failed to configure it properly
                await async_docker_call(container.remove, force=True)
                raise

            return container
        except Exception as e:
            logger.error(f"Error creating container: {e}")
            raise

    async def _rename_container_to_backup(
        self,
        client: docker.DockerClient,
        container,
        original_name: str
    ) -> Tuple[Optional[Any], str]:
        """
        Stop and rename container to backup name for rollback capability.

        Uses Docker's "manually stopped" flag - containers stopped with stop()
        will NOT auto-restart even with restart: always policy. This is Docker's
        standard behavior and does not require manipulating restart policies.

        Args:
            client: Docker client instance
            container: Container object to backup
            original_name: Original container name (without leading /)

        Returns:
            Tuple of (backup_container, backup_name) or (None, '') on failure
        """
        try:
            # Generate backup name with timestamp
            timestamp = int(time.time())
            backup_name = f"{original_name}-backup-{timestamp}"

            logger.info(f"Creating backup: stopping and renaming {original_name} to {backup_name}")

            # Stop container (sets "manually stopped" flag in Docker)
            await async_docker_call(container.stop, timeout=30)
            logger.info(f"Stopped container {original_name}")

            # Rename to backup (backup stays stopped due to "manually stopped" flag)
            await async_docker_call(container.rename, backup_name)
            logger.info(f"Renamed {original_name} to {backup_name}")

            return container, backup_name

        except Exception as e:
            logger.error(f"Error creating backup for {original_name}: {e}", exc_info=True)
            return None, ''

    async def _rollback_container(
        self,
        client: docker.DockerClient,
        backup_container,
        backup_name: str,
        original_name: str,
        new_container = None
    ) -> bool:
        """
        Rollback failed update by restoring backup container.

        Steps:
        1. Check backup container state (defensive check)
        2. Stop backup if running (shouldn't happen with "manually stopped" flag)
        3. Remove broken new container (if exists)
        4. Rename backup back to original name
        5. Start restored container

        Args:
            client: Docker client instance
            backup_container: Backup container object to restore
            backup_name: Current backup container name
            original_name: Original container name to restore
            new_container: Optional new container to clean up

        Returns:
            True if rollback successful, False otherwise
        """
        try:
            logger.warning(f"Starting rollback: restoring {backup_name} to {original_name}")

            # Step 1: Check backup container state (defensive check)
            await async_docker_call(backup_container.reload)
            backup_status = backup_container.status
            logger.info(f"Backup container {backup_name} status: {backup_status}")

            # Step 2: If backup is running (shouldn't happen), stop it
            if backup_status == 'running':
                logger.warning(f"Backup {backup_name} is running (unexpected), stopping before rollback")
                try:
                    await async_docker_call(backup_container.stop, timeout=10)
                    logger.info(f"Stopped backup {backup_name}")
                except Exception as stop_error:
                    logger.warning(f"Failed to stop running backup: {stop_error}, attempting force kill")
                    await async_docker_call(backup_container.kill)
            elif backup_status in ['restarting', 'dead']:
                logger.error(f"Backup {backup_name} in bad state: {backup_status}, attempting force stop")
                try:
                    await async_docker_call(backup_container.kill)
                except Exception as kill_error:
                    logger.warning(f"Failed to kill backup: {kill_error}")

            # Step 3: Remove broken new container if it exists
            if new_container:
                try:
                    logger.info(f"Removing failed new container")
                    await async_docker_call(new_container.remove, force=True)
                    logger.info("Successfully removed failed container")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup new container: {cleanup_error}")
                    # Continue with rollback even if cleanup fails

            # Step 4: Remove any container with original name (cleanup edge case)
            try:
                existing = await async_docker_call(client.containers.get, original_name)
                if existing:
                    logger.info(f"Found existing container with original name, removing it")
                    await async_docker_call(existing.remove, force=True)
            except docker.errors.NotFound:
                # Expected - no container with original name exists
                pass
            except Exception as e:
                logger.warning(f"Error checking for existing container: {e}")
                # Continue anyway

            # Step 5: Rename backup back to original name
            logger.info(f"Renaming backup {backup_name} back to {original_name}")
            await async_docker_call(backup_container.rename, original_name)
            logger.info(f"Renamed backup to {original_name}")

            # Step 6: Start restored container
            logger.info(f"Starting restored container {original_name}")
            await async_docker_call(backup_container.start)
            logger.info(f"Successfully started restored container {original_name}")

            logger.warning(f"Rollback successful: {original_name} restored to previous state")
            return True

        except Exception as e:
            logger.critical(
                f"CRITICAL: Rollback failed for {original_name}: {e}. "
                f"Manual intervention required - backup container: {backup_name}",
                exc_info=True
            )
            return False

    async def _cleanup_backup_container(
        self,
        client: docker.DockerClient,
        backup_container,
        backup_name: str
    ):
        """
        Remove backup container after successful update.

        Args:
            client: Docker client instance
            backup_container: Backup container object to remove
            backup_name: Backup container name for logging
        """
        try:
            logger.info(f"Removing backup container {backup_name}")
            await async_docker_call(backup_container.remove, force=True)
            logger.info(f"Successfully removed backup container {backup_name}")
        except Exception as e:
            logger.error(f"Error removing backup container {backup_name}: {e}", exc_info=True)
            # Non-critical error - backup container left behind but update succeeded

    async def _re_evaluate_alerts_after_update(
        self,
        host_id: str,
        container_id: str,
        container_name: str
    ):
        """
        Re-evaluate alerts after container update completes.
        This triggers alert evaluation for the container to check if any
        suppressed alerts should now fire (e.g., container is still stopped).
        """
        try:
            if not self.monitor or not hasattr(self.monitor, 'alert_evaluation_service'):
                logger.debug("Alert evaluation service not available for post-update check")
                return

            logger.info(f"Re-evaluating alerts for {container_name} after update")

            # Get current container state directly from Docker (avoids expensive monitor.get_containers() call)
            try:
                docker_client = await self._get_docker_client(host_id)
                if not docker_client:
                    logger.warning(f"Could not get Docker client for post-update alert evaluation: {container_id}")
                    return

                container_obj = await async_docker_call(docker_client.containers.get, container_id)
                container_state = container_obj.status.lower()  # 'running', 'exited', etc.
            except docker.errors.NotFound:
                logger.warning(f"Container not found for post-update alert evaluation: {container_id}")
                return
            except Exception as e:
                logger.warning(f"Could not get container info for post-update alert evaluation: {e}")
                return

            # Get host name
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

            # Trigger state change event evaluation to check container state
            event_data = {
                'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                'event_type': 'state_change',
                'new_state': container_state,
                'old_state': 'updating',
                'triggered_by': 'post_update_check',
            }

            # Call alert evaluation service
            await self.monitor.alert_evaluation_service.handle_container_event(
                event_type='state_change',
                container_id=container_id,
                container_name=container_name,
                host_id=host_id,
                host_name=host_name,
                event_data=event_data
            )

            logger.info(f"Post-update alert evaluation completed for {container_name}")

        except Exception as e:
            logger.error(f"Error re-evaluating alerts after update: {e}", exc_info=True)

    async def _broadcast_container_recreated(
        self,
        host_id: str,
        old_composite_key: str,
        new_composite_key: str,
        container_name: str
    ):
        """
        Broadcast container_recreated event to keep frontend modal open during updates.

        When a container is updated, it gets a new Docker ID. This notifies the frontend
        so modals/views tracking the old ID can update to track the new ID seamlessly.

        Args:
            host_id: Host UUID
            old_composite_key: Old composite key (host_id:old_container_id)
            new_composite_key: New composite key (host_id:new_container_id)
            container_name: Container name (for logging/debugging)
        """
        try:
            if not self.monitor or not hasattr(self.monitor, 'manager'):
                logger.warning("No WebSocket manager available for container_recreated broadcast")
                return

            logger.info(f"Broadcasting container_recreated event for {container_name}: {old_composite_key} → {new_composite_key}")

            await self.monitor.manager.broadcast({
                "type": "container_recreated",
                "data": {
                    "host_id": host_id,
                    "old_composite_key": old_composite_key,
                    "new_composite_key": new_composite_key,
                    "container_name": container_name
                }
            })

            logger.debug(f"Broadcast container_recreated event for {container_name}")

        except Exception as e:
            # Non-critical error - modal may close but update succeeded
            logger.error(f"Error broadcasting container_recreated event: {e}", exc_info=True)

    async def _emit_update_completed_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        previous_image: str,
        new_image: str,
        previous_digest: str = None,
        new_digest: str = None
    ):
        """
        Emit UPDATE_COMPLETED event via EventBus.
        EventBus handles database logging and alert triggering.
        """
        try:
            logger.info(f"Emitting UPDATE_COMPLETED event for {container_name}")

            # Get host name
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

            # Emit event via EventBus
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.UPDATE_COMPLETED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=host_name,
                data={
                    'previous_image': previous_image,
                    'new_image': new_image,
                    'current_digest': previous_digest,
                    'latest_digest': new_digest,
                }
            ))

            logger.debug(f"Emitted UPDATE_COMPLETED event for {container_name}")

        except Exception as e:
            logger.error(f"Error emitting update completion event: {e}", exc_info=True)

    async def _emit_update_warning_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        warning_message: str
    ):
        """
        Emit UPDATE_SKIPPED_VALIDATION event via EventBus for validation warnings.
        This is informational - the update was skipped due to validation policy.
        """
        try:
            logger.info(f"Emitting UPDATE_SKIPPED_VALIDATION event for {container_name}")

            # Get host name
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

            # Emit event via EventBus
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.UPDATE_SKIPPED_VALIDATION,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=host_name,
                data={
                    'message': f"Auto-update skipped: {warning_message}",
                    'category': 'update_validation',
                    'reason': warning_message
                }
            ))

            logger.debug(f"Emitted UPDATE_SKIPPED_VALIDATION event for {container_name}")

        except Exception as e:
            logger.error(f"Error emitting update warning event: {e}", exc_info=True)

    async def _emit_update_failed_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        error_message: str
    ):
        """
        Emit UPDATE_FAILED event via EventBus.
        EventBus handles database logging and alert triggering.
        """
        try:
            logger.info(f"Emitting UPDATE_FAILED event for {container_name}")

            # Get host name
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

            # Emit event via EventBus
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.UPDATE_FAILED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=host_name,
                data={
                    'error_message': error_message,
                }
            ))

            logger.debug(f"Emitted UPDATE_FAILED event for {container_name}")

        except Exception as e:
            logger.error(f"Error emitting update failure event: {e}", exc_info=True)

    async def _emit_update_started_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        target_image: str
    ):
        """
        Emit UPDATE_STARTED event via EventBus.
        EventBus handles database logging and alert triggering.
        """
        try:
            logger.info(f"Emitting UPDATE_STARTED event for {container_name}")

            # Get host name
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

            # Emit event via EventBus
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.UPDATE_STARTED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=host_name,
                data={
                    'target_image': target_image,
                }
            ))

            logger.debug(f"Emitted UPDATE_STARTED event for {container_name}")

        except Exception as e:
            logger.error(f"Error emitting update started event: {e}", exc_info=True)

    async def _emit_update_pull_completed_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        image: str,
        size_mb: Optional[float] = None
    ):
        """
        Emit UPDATE_PULL_COMPLETED event via EventBus.
        EventBus handles database logging and alert triggering.
        """
        try:
            logger.info(f"Emitting UPDATE_PULL_COMPLETED event for {container_name}")

            # Get host name
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

            # Build data
            data = {'image': image}
            if size_mb is not None:
                data['size_mb'] = size_mb

            # Emit event via EventBus
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.UPDATE_PULL_COMPLETED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=host_name,
                data=data
            ))

            logger.debug(f"Emitted UPDATE_PULL_COMPLETED event for {container_name}")

        except Exception as e:
            logger.error(f"Error emitting update pull completed event: {e}", exc_info=True)

    async def _emit_backup_created_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        backup_name: str
    ):
        """
        Emit BACKUP_CREATED event via EventBus.
        EventBus handles database logging and alert triggering.
        """
        try:
            logger.info(f"Emitting BACKUP_CREATED event for {container_name}")

            # Get host name
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

            # Emit event via EventBus
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.BACKUP_CREATED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=host_name,
                data={
                    'backup_name': backup_name,
                }
            ))

            logger.debug(f"Emitted BACKUP_CREATED event for {container_name}")

        except Exception as e:
            logger.error(f"Error emitting backup created event: {e}", exc_info=True)

    async def _emit_rollback_completed_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str
    ):
        """
        Emit ROLLBACK_COMPLETED event via EventBus.
        EventBus handles database logging and alert triggering.
        """
        try:
            logger.info(f"Emitting ROLLBACK_COMPLETED event for {container_name}")

            # Get host name
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

            # Emit event via EventBus
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.ROLLBACK_COMPLETED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=host_name,
                data={}
            ))

            logger.debug(f"Emitted ROLLBACK_COMPLETED event for {container_name}")

        except Exception as e:
            logger.error(f"Error emitting rollback completed event: {e}", exc_info=True)

    async def _get_dependent_containers(
        self,
        client: docker.DockerClient,
        container,
        container_name: str,
        container_id: str
    ) -> list:
        """
        Find containers that depend on this container via network_mode.

        When a container uses network_mode: container:other_container, it shares
        the network namespace of that container. If the target container is
        recreated with a new ID, dependent containers must also be recreated
        to point to the new ID.

        Common use cases:
        - VPN sidecars (Gluetun + qBittorrent, ProtonVPN + Transmission)
        - Log forwarders (Fluentd attached to app container)
        - Network proxies (nginx sharing network with backend)

        Args:
            client: Docker SDK client instance
            container: Container object being updated
            container_name: Container name (for logging)
            container_id: Container short ID (for logging)

        Returns:
            List of dicts with dependent container info:
            [
                {
                    'container': Docker container object,
                    'name': str,
                    'id': str (short),
                    'image': str,
                    'old_network_mode': str (original network_mode value)
                },
                ...
            ]
        """
        dependents = []

        try:
            # Get all containers (including stopped ones - they may be auto-restart)
            all_containers = await async_docker_call(client.containers.list, all=True)

            for other in all_containers:
                # Skip self
                if other.id == container.id:
                    continue

                # Check if this container uses network_mode pointing to our container
                network_mode = other.attrs.get('HostConfig', {}).get('NetworkMode', '')

                # network_mode can reference by name or ID
                # Examples: "container:gluetun", "container:abc123def456"
                if network_mode in [f'container:{container_name}', f'container:{container.id}']:
                    logger.info(
                        f"Found dependent container: {other.name} "
                        f"(network_mode: {network_mode})"
                    )

                    # Get image name (prefer tag, fallback to Config.Image)
                    try:
                        image_name = other.image.tags[0] if other.image.tags else other.attrs.get('Config', {}).get('Image', '')
                    except Exception:
                        image_name = other.attrs.get('Config', {}).get('Image', '')

                    dependents.append({
                        'container': other,
                        'name': other.name,
                        'id': other.short_id,
                        'image': image_name,
                        'old_network_mode': network_mode
                    })

        except Exception as e:
            logger.warning(f"Could not check for dependent containers: {e}")
            # Non-fatal - return empty list
            return []

        return dependents

    async def _recreate_dependent_container(
        self,
        client: docker.DockerClient,
        dep_info: dict,
        new_parent_container_id: str
    ) -> bool:
        """
        Recreate a dependent container with updated network_mode.

        This handles containers that use network_mode: container:other_container.
        When the parent container is updated, dependents must be recreated to
        point to the new parent container ID.

        Strategy:
        1. Extract current configuration
        2. Stop container
        3. Rename to temporary name (preserves for rollback)
        4. Create new container with updated network_mode
        5. Start new container
        6. Verify running for 3 seconds (stability check)
        7. Remove temp container
        8. On failure: Restore original container

        Args:
            client: Docker SDK client instance
            dep_info: Dict with dependent container info (from _get_dependent_containers)
            new_parent_container_id: Full container ID of new parent (for network_mode)

        Returns:
            True if recreation succeeded, False otherwise
        """
        dep_container = dep_info['container']
        dep_name = dep_info['name']

        try:
            logger.info(f"Recreating dependent container: {dep_name}")

            # Step 1: Extract current configuration
            config = await self._extract_container_config(dep_container)

            # Step 2: Update network_mode to point to new parent container
            # Use full container ID (not short ID) for network_mode
            old_network_mode = config.get('network_mode', '')
            config['network_mode'] = f'container:{new_parent_container_id}'
            logger.info(
                f"Updated network_mode: {old_network_mode} → {config['network_mode']}"
            )

            # Step 3: Extract networks (for restoration after network_mode removed)
            # Note: Containers using network_mode: container:X cannot have custom networks
            # But we preserve this info in case user manually fixes later
            networks = dep_container.attrs.get('NetworkSettings', {}).get('Networks', {})

            # Step 4: Stop container
            logger.info(f"Stopping dependent container: {dep_name}")
            try:
                await async_docker_call(dep_container.stop, timeout=10)
            except Exception as stop_error:
                logger.warning(f"Graceful stop failed, attempting kill: {stop_error}")
                await async_docker_call(dep_container.kill)

            # Step 5: Rename to temporary name (enables rollback)
            temp_name = f"{dep_name}-temp-{int(time.time())}"
            logger.info(f"Renaming to temporary: {temp_name}")
            await async_docker_call(dep_container.rename, temp_name)

            # Step 6: Create new container with updated config
            logger.info(f"Creating new dependent container: {dep_name}")
            new_dep_container = await self._create_container(
                client,
                dep_info['image'],
                config
            )

            # Step 7: Start new container
            logger.info(f"Starting new dependent container: {dep_name}")
            await async_docker_call(new_dep_container.start)

            # Step 8: Verify running (simple stability check - 3 seconds)
            logger.info(f"Verifying dependent container started: {dep_name}")
            await asyncio.sleep(3)

            # Reload and check status
            await async_docker_call(new_dep_container.reload)
            if new_dep_container.status != 'running':
                raise Exception(
                    f"Container failed to start properly (status: {new_dep_container.status})"
                )

            # Step 9: Success - remove temporary container
            logger.info(f"Removing temporary container: {temp_name}")
            temp_container = await async_docker_call(client.containers.get, temp_name)
            await async_docker_call(temp_container.remove, force=True)

            logger.info(f"Successfully recreated dependent container: {dep_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to recreate dependent {dep_name}: {e}", exc_info=True)

            # Attempt rollback: restore original container
            try:
                logger.info(f"Rolling back dependent container: {dep_name}")

                # Remove failed new container
                try:
                    await async_docker_call(new_dep_container.remove, force=True)
                except Exception:
                    pass  # May not exist

                # Restore temp container to original name
                temp_container = await async_docker_call(client.containers.get, temp_name)
                await async_docker_call(temp_container.rename, dep_name)

                # Restart original container
                await async_docker_call(temp_container.start)

                logger.info(f"Rollback successful for dependent: {dep_name}")

            except Exception as rollback_error:
                logger.error(
                    f"Rollback failed for dependent {dep_name}: {rollback_error}. "
                    f"Manual intervention may be required for container: {temp_name}"
                )

            return False

    async def cleanup_stale_pull_progress(self):
        """
        Remove pull progress older than 10 minutes (pull failed or completed).

        Called periodically by monitor to prevent unbounded memory growth of _active_pulls dict.
        Defense-in-depth: handles edge cases where finally block doesn't run (process crash, etc).
        """
        try:
            cutoff = time.time() - 600  # 10 minutes

            # Thread-safe iteration and deletion
            with self._active_pulls_lock:
                stale_keys = [
                    key for key, data in self._active_pulls.items()
                    if data['updated'] < cutoff
                ]
                for key in stale_keys:
                    del self._active_pulls[key]

            if stale_keys:
                logger.debug(f"Cleaned up {len(stale_keys)} stale pull progress entries")
        except Exception as e:
            logger.error(f"Error cleaning up stale pull progress: {e}", exc_info=True)


# Global singleton instance
_update_executor = None


def get_update_executor(db: DatabaseManager = None, monitor=None) -> UpdateExecutor:
    """Get or create global UpdateExecutor instance"""
    global _update_executor
    if _update_executor is None:
        if db is None:
            db = DatabaseManager('/app/data/dockmon.db')
        _update_executor = UpdateExecutor(db, monitor)
    # Update monitor if provided (and re-initialize image_pull_tracker with connection_manager)
    if monitor and _update_executor.monitor is None:
        _update_executor.monitor = monitor
        # Re-initialize image pull tracker with connection manager for WebSocket broadcasts
        # (fixes issue where tracker was initialized with connection_manager=None)
        _update_executor.image_pull_tracker = ImagePullProgress(
            _update_executor.loop,
            monitor.manager if hasattr(monitor, 'manager') else None,
            progress_callback=_update_executor._store_pull_progress
        )
    return _update_executor
