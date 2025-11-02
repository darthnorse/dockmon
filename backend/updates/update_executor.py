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

from database import DatabaseManager, ContainerUpdate, AutoRestartConfig, ContainerDesiredState, ContainerHttpHealthCheck, GlobalSettings, DeploymentMetadata, TagAssignment, Agent
from event_bus import Event, EventType as BusEventType, get_event_bus
from utils.async_docker import async_docker_call
from utils.container_health import wait_for_container_health
from utils.image_pull_progress import ImagePullProgress
from utils.keys import make_composite_key, parse_composite_key
from updates.container_validator import ContainerValidator, ValidationResult
from agent.command_executor import CommandStatus

logger = logging.getLogger(__name__)


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
        force: bool = False
    ) -> bool:
        """
        Execute update for a single container.

        Args:
            host_id: Host UUID
            container_id: Container short ID (12 chars)
            update_record: ContainerUpdate database record
            force: If True, skip validation (API layer already validated)

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Executing update for container {container_id} on host {host_id} (force={force})")

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

        # Check host connection type to route to appropriate update mechanism
        from database import DockerHostDB
        with self.db.get_session() as session:
            host = session.query(DockerHostDB).filter_by(id=host_id).first()
            if not host:
                error_message = f"Host {host_id} not found in database"
                logger.error(error_message)
                await self._emit_update_failed_event(
                    host_id, container_id, container_id, error_message
                )
                return False

            connection_type = host.connection_type

        # Validate connection type
        if connection_type not in ('local', 'remote', 'agent'):
            error_message = f"Unknown connection_type '{connection_type}' for host {host_id}. Expected: 'local', 'remote', or 'agent'"
            logger.error(error_message)
            await self._emit_update_failed_event(
                host_id, container_id, container_id, error_message
            )
            return False

        # Route to agent-based update for agent hosts
        if connection_type == 'agent':
            logger.info(f"Routing update for container {container_id} to agent-based update (host connection_type='agent')")
            return await self._update_container_via_agent(
                host_id,
                container_id,
                update_record,
                force
            )

        # Continue with Docker SDK-based update for local/remote hosts
        logger.debug(f"Using Docker SDK update for host {host_id} (connection_type='{connection_type}')")

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

            # Get container info
            container_info = await self._get_container_info(host_id, container_id)
            if not container_info:
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

            container_name = container_info.get("name", container_id)

            # Get container object for configuration extraction
            old_container = await async_docker_call(docker_client.containers.get, container_id)

            # Priority 0: Block DockMon self-update (ALWAYS, even with force=True)
            # Defense-in-depth: protect at executor layer in case API layer is bypassed
            # NOTE: This only blocks the DockMon backend container itself, NOT agent containers
            container_name_lower = container_name.lower()
            if container_name_lower == 'dockmon' or (container_name_lower.startswith('dockmon-') and 'agent' not in container_name_lower):
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

            # Priority 1: Detect agent self-update and route to special handler
            # Agents update themselves in-place (binary swap), not container recreation
            if 'dockmon-agent' in update_record.current_image.lower():
                # Check if this host has an agent
                if hasattr(self, 'agent_manager'):
                    agent_id = self.agent_manager.get_agent_for_host(host_id)
                    if agent_id:
                        logger.info(
                            f"Detected agent self-update for container '{container_name}' on host {host_id}, "
                            f"routing to agent self-update mechanism"
                        )
                        return await self._execute_agent_self_update(
                            agent_id,
                            host_id,
                            container_id,
                            container_name,
                            update_record
                        )
                    else:
                        logger.warning(
                            f"Container '{container_name}' has agent image but no agent registered for host {host_id}"
                        )
                # If no agent_manager or no agent for host, fall through to normal update
                # (This shouldn't happen in normal operation, but provides fallback)

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
                    # For auto-updates, skip containers that require warnings
                    # (user confirmation required - not safe for auto-update)
                    logger.info(
                        f"Skipping auto-update for {container_name}: {validation_result.reason} "
                        f"(requires user confirmation)"
                    )

                    # Emit warning event (non-critical)
                    await self._emit_update_warning_event(
                        host_id,
                        container_id,
                        container_name,
                        validation_result.reason
                    )

                    return False

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

            try:
                # Use shared ImagePullProgress for detailed layer tracking (same as deployment system)
                await self.image_pull_tracker.pull_with_progress(
                    docker_client,
                    update_record.latest_image,
                    host_id,
                    container_id,
                    event_type="container_update_layer_progress"
                )
            except Exception as streaming_error:
                logger.warning(f"Streaming pull failed, falling back to simple pull: {streaming_error}")
                # Fallback to old method (still works, just no detailed progress)
                await self._pull_image(docker_client, update_record.latest_image)

            # Emit UPDATE_PULL_COMPLETED event (audit trail)
            await self._emit_update_pull_completed_event(
                host_id,
                container_id,
                container_name,
                update_record.latest_image
            )

            # Step 2: Get full container configuration
            # (reuse old_container fetched during validation to avoid duplicate API call)
            logger.info("Getting container configuration")
            await self._broadcast_progress(host_id, container_id, "configuring", 35, "Reading container configuration")
            container_config = await self._extract_container_config(old_container)

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
                    session.query(TagAssignment).filter(
                        TagAssignment.subject_type == 'container',
                        TagAssignment.subject_id == old_composite_key  # OLD composite key
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
                    except Exception as commit_error:
                        # Clear flag if commit failed - rollback should execute
                        update_committed = False
                        logger.error(f"Database commit failed for {container_name}: {commit_error}", exc_info=True)
                        raise  # Re-raise to trigger rollback in outer exception handler

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

            # Step 9: Cleanup backup container on success
            logger.info(f"Update successful, cleaning up backup container {backup_name}")
            await self._cleanup_backup_container(docker_client, backup_container, backup_name)

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

    async def _get_container_info(self, host_id: str, container_id: str) -> Optional[Dict]:
        """Get container info from monitor"""
        if not self.monitor:
            return None

        try:
            containers = await self.monitor.get_containers()
            container = next((c for c in containers if c.id == container_id and c.host_id == host_id), None)
            return container.dict() if container else None
        except Exception as e:
            logger.error(f"Error getting container info: {e}")
            return None

    async def _pull_image(self, client: docker.DockerClient, image: str, timeout: int = 1800):
        """
        Pull Docker image with timeout.

        Args:
            client: Docker client instance
            image: Image name to pull
            timeout: Timeout in seconds (default: 1800 = 30 minutes)

        Raises:
            asyncio.TimeoutError: If pull takes longer than timeout
            Exception: If pull fails for other reasons
        """
        try:
            # Use async wrapper with timeout to prevent event loop blocking and handle large images
            await asyncio.wait_for(
                async_docker_call(client.images.pull, image),
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

    async def _extract_container_config(self, container) -> Dict[str, Any]:
        """
        Extract container configuration for recreation.

        Returns a dict with all necessary config to recreate the container.
        """
        attrs = container.attrs
        config = attrs["Config"]
        host_config = attrs["HostConfig"]
        networking = attrs["NetworkSettings"]

        # Build configuration dict
        container_config = {
            "name": attrs["Name"].lstrip("/"),
            "hostname": config.get("Hostname"),
            "user": config.get("User"),
            "detach": True,
            "stdin_open": config.get("OpenStdin", False),
            "tty": config.get("Tty", False),
            "environment": config.get("Env", []),
            "command": config.get("Cmd"),
            "entrypoint": config.get("Entrypoint"),
            "working_dir": config.get("WorkingDir"),
            "labels": config.get("Labels", {}),
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
        }

        # Extract port bindings
        if host_config.get("PortBindings"):
            container_config["ports"] = host_config["PortBindings"]

        # Extract volume bindings
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

        # Extract network
        networks = networking.get("Networks", {})
        if networks:
            # Get first network (containers can be in multiple networks)
            network_name = list(networks.keys())[0]
            container_config["network"] = network_name

        return container_config

    async def _create_container(
        self,
        client: docker.DockerClient,
        image: str,
        config: Dict[str, Any]
    ) -> Any:
        """Create new container with given config"""
        try:
            # Use async wrapper to prevent event loop blocking
            container = await async_docker_call(
                client.containers.create,
                image,
                name=config["name"],
                hostname=config.get("hostname"),
                user=config.get("user"),
                detach=config.get("detach", True),
                stdin_open=config.get("stdin_open", False),
                tty=config.get("tty", False),
                environment=config.get("environment"),
                command=config.get("command"),
                entrypoint=config.get("entrypoint"),
                working_dir=config.get("working_dir"),
                labels=config.get("labels"),
                ports=config.get("ports"),
                volumes=config.get("volumes"),
                network=config.get("network"),
                restart_policy=config.get("restart_policy"),
                privileged=config.get("privileged", False),
                cap_add=config.get("cap_add"),
                cap_drop=config.get("cap_drop"),
                devices=config.get("devices"),
                security_opt=config.get("security_opt"),
                tmpfs=config.get("tmpfs"),
                ulimits=config.get("ulimits"),
                dns=config.get("dns"),
                extra_hosts=config.get("extra_hosts"),
                ipc_mode=config.get("ipc_mode"),
                pid_mode=config.get("pid_mode"),
                shm_size=config.get("shm_size"),
            )
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

    async def _execute_agent_self_update(
        self,
        agent_id: str,
        host_id: str,
        container_id: str,
        container_name: str,
        update_record: ContainerUpdate
    ) -> bool:
        """
        Execute agent self-update via self_update command.

        Agents update themselves in-place by swapping the binary, not by recreating
        the container. This ensures the agent container ID remains stable.

        Flow:
        1. Emit UPDATE_STARTED event
        2. Send self_update command to agent with new image
        3. Agent downloads new binary and prepares update
        4. Agent exits and Docker restarts it automatically
        5. On startup, agent detects update lock and swaps binaries
        6. Wait for agent to reconnect with new version (timeout: 5 min)
        7. Validate new version matches target
        8. Update database, emit UPDATE_COMPLETED
        9. Return True

        On failure: Emit UPDATE_FAILED, return False

        Args:
            agent_id: Agent UUID
            host_id: Host UUID
            container_id: Container short ID (12 chars)
            container_name: Container name (for logging)
            update_record: ContainerUpdate database record

        Returns:
            True if update successful, False otherwise
        """
        logger.info(
            f"Executing agent self-update for {container_name} (agent_id: {agent_id}): "
            f"{update_record.current_image} → {update_record.latest_image}"
        )

        # Emit UPDATE_STARTED event
        await self._emit_update_started_event(
            host_id,
            container_id,
            container_name,
            update_record.current_image,
            update_record.latest_image
        )

        try:
            # Send self_update command to agent
            command = {
                "type": "command",
                "payload": {
                    "action": "self_update",
                    "params": {
                        "image": update_record.latest_image,
                        "version": self._extract_version_from_image(update_record.latest_image),
                        "timeout_sec": 120
                    }
                }
            }

            logger.info(f"Sending self_update command to agent {agent_id}")

            # Execute command with timeout
            if not hasattr(self, 'agent_command_executor'):
                logger.error("AgentCommandExecutor not available")
                await self._emit_update_failed_event(
                    host_id, container_id, container_name,
                    "Agent command executor not initialized"
                )
                return False

            result = await self.agent_command_executor.execute_command(
                agent_id,
                command,
                timeout=150.0  # 2.5 minutes for download + prep
            )

            # Check if command was sent successfully
            if result.status != CommandStatus.SUCCESS:
                error_msg = f"Failed to send self-update command: {result.error}"
                logger.error(error_msg)
                await self._emit_update_failed_event(
                    host_id, container_id, container_name, error_msg
                )
                return False

            logger.info(f"Agent {agent_id} acknowledged self-update command, waiting for reconnection...")

            # Wait for agent to reconnect with new version (agent exits and Docker restarts it)
            # Timeout: 5 minutes (download, swap, restart)
            reconnected = await self._wait_for_agent_reconnection(
                agent_id,
                timeout=300.0  # 5 minutes
            )

            if not reconnected:
                error_msg = "Agent did not reconnect after self-update (timeout: 5 minutes)"
                logger.error(error_msg)
                await self._emit_update_failed_event(
                    host_id, container_id, container_name, error_msg
                )
                return False

            # Validate new version (optional - agent version should be updated on reconnection)
            new_version = await self._get_agent_version(agent_id)
            expected_version = self._extract_version_from_image(update_record.latest_image)

            logger.info(
                f"Agent reconnected with version: {new_version} "
                f"(expected: {expected_version})"
            )

            # Update database
            with self.db.get_session() as session:
                # Update ContainerUpdate record
                db_update = session.query(ContainerUpdate).filter_by(
                    container_id=make_composite_key(host_id, container_id)
                ).first()

                if db_update:
                    db_update.current_image = update_record.latest_image
                    db_update.update_available = False
                    db_update.last_updated_at = datetime.now(timezone.utc)
                    session.commit()
                    logger.debug(f"Updated database for {container_name}")

            # Emit UPDATE_COMPLETED event
            await self._emit_update_completed_event(
                host_id,
                container_id,
                container_name,
                update_record.latest_image
            )

            logger.info(f"Agent self-update completed successfully for {container_name}")
            return True

        except Exception as e:
            error_msg = f"Agent self-update failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await self._emit_update_failed_event(
                host_id, container_id, container_name, error_msg
            )
            return False

    async def _wait_for_agent_reconnection(
        self,
        agent_id: str,
        timeout: float = 300.0
    ) -> bool:
        """
        Wait for agent to reconnect after self-update.

        Polls agent connection status until agent is online or timeout occurs.

        Args:
            agent_id: Agent UUID
            timeout: Timeout in seconds (default: 5 minutes)

        Returns:
            True if agent reconnected, False if timeout
        """
        start_time = time.time()
        poll_interval = 2.0  # Check every 2 seconds

        logger.info(f"Waiting for agent {agent_id} to reconnect (timeout: {timeout}s)")

        while (time.time() - start_time) < timeout:
            # Check if agent is connected
            if hasattr(self, 'agent_manager'):
                # Get agent from database to check last_seen_at
                with self.db.get_session() as session:
                    agent = session.query(Agent).filter_by(id=agent_id).first()

                    if agent and agent.status == "online":
                        # Check if last_seen_at is recent (within last 10 seconds)
                        if agent.last_seen_at:
                            elapsed = (datetime.now(timezone.utc) - agent.last_seen_at).total_seconds()
                            if elapsed < 10:
                                logger.info(f"Agent {agent_id} reconnected successfully")
                                return True

            # Wait before next check
            await asyncio.sleep(poll_interval)

        logger.warning(f"Agent {agent_id} did not reconnect within {timeout} seconds")
        return False

    async def _get_agent_version(self, agent_id: str) -> str:
        """
        Get agent version from database.

        Args:
            agent_id: Agent UUID

        Returns:
            Agent version string or "unknown"
        """
        try:
            with self.db.get_session() as session:
                agent = session.query(Agent).filter_by(id=agent_id).first()
                if agent:
                    return agent.version or "unknown"
        except Exception as e:
            logger.warning(f"Could not get agent version: {e}")
        return "unknown"

    def _extract_version_from_image(self, image: str) -> str:
        """
        Extract version tag from Docker image string.

        Args:
            image: Docker image (e.g., "ghcr.io/darthnorse/dockmon-agent:2.2.1")

        Returns:
            Version tag (e.g., "2.2.1") or "latest"
        """
        if ':' in image:
            return image.split(':')[-1]
        return "latest"

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

            # Get current container state
            container_info = await self._get_container_info(host_id, container_id)
            if not container_info:
                logger.warning(f"Could not get container info for post-update alert evaluation: {container_id}")
                return

            # Get host name
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

            # Trigger state change event evaluation to check container state
            event_data = {
                'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                'event_type': 'state_change',
                'new_state': container_info.get('state', 'unknown'),
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

    async def _update_container_via_agent(
        self,
        host_id: str,
        container_id: str,
        update_record: ContainerUpdate,
        force: bool = False
    ) -> bool:
        """
        Execute container update via agent for agent-based hosts.

        Uses AgentContainerOperations to orchestrate the update:
        1. Get container info and config
        2. Pull new image
        3. Stop old container
        4. Create new container with new image
        5. Start new container
        6. Verify health
        7. Update database
        8. Remove old container

        Args:
            host_id: Host UUID
            container_id: Container short ID (12 chars)
            update_record: ContainerUpdate database record
            force: If True, skip validation

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Executing agent-based update for container {container_id} on host {host_id}")

        composite_key = make_composite_key(host_id, container_id)
        old_container_id = container_id
        new_container_id = None
        update_committed = False

        try:
            # Get agent for this host
            agent_id = self.agent_manager.get_agent_for_host(host_id)
            if not agent_id:
                error_message = "No agent registered for this host"
                logger.error(f"No agent found for host {host_id}")
                await self._emit_update_failed_event(
                    host_id, container_id, container_id, error_message
                )
                return False

            # Get container info from monitor
            container_info = await self._get_container_info(host_id, container_id)
            if not container_info:
                error_message = "Container not found"
                logger.error(f"Container {container_id} not found on host {host_id}")
                await self._emit_update_failed_event(
                    host_id, container_id, container_id, error_message
                )
                return False

            container_name = container_info.get("name", container_id)
            logger.info(f"Updating container '{container_name}' via agent")

            # Block DockMon self-update
            container_name_lower = container_name.lower()
            if container_name_lower == 'dockmon' or (container_name_lower.startswith('dockmon-') and 'agent' not in container_name_lower):
                error_message = "DockMon cannot update itself. Please update manually."
                logger.warning(f"Blocked self-update attempt for DockMon container '{container_name}' via agent")
                await self._emit_update_failed_event(
                    host_id, container_id, container_name, error_message
                )
                return False

            # Check for agent self-update (special handling)
            if 'dockmon-agent' in update_record.current_image.lower():
                logger.info(f"Routing to agent self-update for '{container_name}'")
                return await self._execute_agent_self_update(
                    agent_id, host_id, container_id, container_name, update_record
                )

            # Use AgentContainerOperations for the update
            from agent.container_operations import AgentContainerOperations
            agent_ops = AgentContainerOperations()

            # Step 1: Get full container configuration via inspect
            logger.info("Getting container configuration via agent")
            await self._broadcast_progress(host_id, container_id, "configuring", 10, "Reading container configuration")

            try:
                config_result = await agent_ops.inspect_container(host_id, container_id)
                container_attrs = config_result  # Full container inspection data
            except Exception as e:
                error_message = f"Failed to inspect container: {str(e)}"
                logger.error(error_message)
                await self._emit_update_failed_event(host_id, container_id, container_name, error_message)
                return False

            # Emit UPDATE_STARTED event
            await self._emit_update_started_event(
                host_id, container_id, container_name, update_record.latest_image
            )

            # Step 2: Pull new image
            logger.info(f"Pulling new image via agent: {update_record.latest_image}")
            await self._broadcast_progress(host_id, container_id, "pulling", 20, "Pulling new image")

            try:
                await agent_ops.pull_image(host_id, update_record.latest_image)
            except Exception as e:
                error_message = f"Failed to pull image: {str(e)}"
                logger.error(error_message)
                await self._emit_update_failed_event(host_id, container_id, container_name, error_message)
                return False

            await self._emit_update_pull_completed_event(
                host_id, container_id, container_name, update_record.latest_image
            )

            # Step 3: Extract container config for recreation
            logger.info("Extracting container configuration")
            await self._broadcast_progress(host_id, container_id, "backup", 50, "Preparing container recreation")

            # Build new container config from inspection data
            try:
                config = container_attrs.get("Config", {})
                host_config = container_attrs.get("HostConfig", {})
                networking = container_attrs.get("NetworkSettings", {})

                # Build configuration for create_container
                new_config = {
                    "name": container_name,
                    "image": update_record.latest_image,  # NEW IMAGE
                    "hostname": config.get("Hostname"),
                    "user": config.get("User"),
                    "stdin_open": config.get("OpenStdin", False),
                    "tty": config.get("Tty", False),
                    "environment": config.get("Env", []),
                    "command": config.get("Cmd"),
                    "entrypoint": config.get("Entrypoint"),
                    "working_dir": config.get("WorkingDir"),
                    "labels": config.get("Labels", {}),
                    "ports": host_config.get("PortBindings", {}),
                    "volumes": host_config.get("Binds", []),
                    "restart_policy": host_config.get("RestartPolicy", {}),
                    "privileged": host_config.get("Privileged", False),
                    "cap_add": host_config.get("CapAdd"),
                    "cap_drop": host_config.get("CapDrop"),
                    "devices": host_config.get("Devices"),
                    "security_opt": host_config.get("SecurityOpt"),
                }

                # Extract network
                networks = networking.get("Networks", {})
                if networks:
                    network_name = list(networks.keys())[0]
                    new_config["network"] = network_name

            except Exception as e:
                error_message = f"Failed to extract container config: {str(e)}"
                logger.error(error_message)
                await self._emit_update_failed_event(host_id, container_id, container_name, error_message)
                return False

            # Step 4: Stop old container
            logger.info(f"Stopping old container '{container_name}'")
            await self._broadcast_progress(host_id, container_id, "stopping", 60, "Stopping old container")

            try:
                await agent_ops.stop_container(host_id, old_container_id, timeout=30)
            except Exception as e:
                error_message = f"Failed to stop old container: {str(e)}"
                logger.error(error_message)
                await self._emit_update_failed_event(host_id, container_id, container_name, error_message)
                return False

            # Step 5: Remove old container
            logger.info(f"Removing old container '{container_name}'")
            try:
                await agent_ops.remove_container(host_id, old_container_id, force=False)
            except Exception as e:
                logger.warning(f"Failed to remove old container (non-fatal): {str(e)}")

            # Step 6: Create new container
            logger.info(f"Creating new container '{container_name}' with image {update_record.latest_image}")
            await self._broadcast_progress(host_id, container_id, "creating", 70, "Creating new container")

            try:
                new_container_id = await agent_ops.create_container(host_id, new_config)
                # Ensure SHORT ID
                if len(new_container_id) > 12:
                    new_container_id = new_container_id[:12]
                logger.info(f"New container created with ID: {new_container_id}")
            except Exception as e:
                error_message = f"Failed to create new container: {str(e)}"
                logger.error(error_message)
                await self._emit_update_failed_event(host_id, container_id, container_name, error_message)
                # TODO: Attempt to restart old container if possible
                return False

            # Step 7: Start new container
            logger.info(f"Starting new container '{container_name}'")
            await self._broadcast_progress(host_id, container_id, "starting", 80, "Starting new container")

            try:
                await agent_ops.start_container(host_id, new_container_id)
            except Exception as e:
                error_message = f"Failed to start new container: {str(e)}"
                logger.error(error_message)
                await self._emit_update_failed_event(host_id, container_id, container_name, error_message)
                # New container exists but failed to start - manual intervention needed
                return False

            # Step 8: Verify health
            logger.info(f"Verifying health of new container '{container_name}'")
            await self._broadcast_progress(host_id, container_id, "health_check", 90, "Verifying container health")

            try:
                is_healthy = await agent_ops.verify_container_running(host_id, new_container_id, timeout=120)
                if not is_healthy:
                    error_message = "Health check failed: container not running or unhealthy"
                    logger.error(error_message)
                    await self._emit_update_failed_event(host_id, container_id, container_name, error_message)
                    # TODO: Could attempt rollback here
                    return False
            except Exception as e:
                error_message = f"Health check failed: {str(e)}"
                logger.error(error_message)
                await self._emit_update_failed_event(host_id, container_id, container_name, error_message)
                return False

            # Step 9: Update database
            logger.info(f"Updating database records for '{container_name}'")
            new_composite_key = make_composite_key(host_id, new_container_id)
            old_composite_key = make_composite_key(host_id, old_container_id)

            with self.db.get_session() as session:
                record = session.query(ContainerUpdate).filter_by(
                    container_id=old_composite_key
                ).first()

                if record:
                    # Update all database tables (same as Docker SDK path)
                    record.container_id = new_composite_key
                    record.update_available = False
                    record.current_image = update_record.latest_image
                    record.current_digest = update_record.latest_digest
                    record.last_updated_at = datetime.now(timezone.utc)
                    record.updated_at = datetime.now(timezone.utc)

                    # Update AutoRestartConfig
                    session.query(AutoRestartConfig).filter_by(
                        host_id=host_id, container_id=old_container_id
                    ).update({
                        "container_id": new_container_id,
                        "updated_at": datetime.now(timezone.utc)
                    })

                    # Update ContainerDesiredState
                    session.query(ContainerDesiredState).filter_by(
                        host_id=host_id, container_id=old_container_id
                    ).update({
                        "container_id": new_container_id,
                        "updated_at": datetime.now(timezone.utc)
                    })

                    # Update ContainerHttpHealthCheck
                    session.query(ContainerHttpHealthCheck).filter_by(
                        container_id=old_composite_key
                    ).update({
                        "container_id": new_composite_key
                    })

                    # Update DeploymentMetadata
                    session.query(DeploymentMetadata).filter_by(
                        container_id=old_composite_key
                    ).update({
                        "container_id": new_composite_key,
                        "updated_at": datetime.now(timezone.utc)
                    })

                    # Update TagAssignment
                    session.query(TagAssignment).filter(
                        TagAssignment.subject_type == 'container',
                        TagAssignment.subject_id == old_composite_key
                    ).update({
                        "subject_id": new_composite_key,
                        "last_seen_at": datetime.now(timezone.utc)
                    })

                    update_committed = True
                    session.commit()
                    logger.info(f"Database updated: {old_composite_key} -> {new_composite_key}")

            # Notify frontend of container ID change
            await self._broadcast_container_recreated(
                host_id, old_composite_key, new_composite_key, container_name
            )

            # Emit success event
            await self._emit_update_completed_event(
                host_id, new_container_id, container_name,
                update_record.current_image, update_record.latest_image,
                update_record.current_digest, update_record.latest_digest
            )

            logger.info(f"Successfully updated container '{container_name}' via agent")
            await self._broadcast_progress(host_id, new_container_id, "completed", 100, "Update completed successfully")
            return True

        except Exception as e:
            logger.error(f"Error executing agent-based update for {container_name if 'container_name' in locals() else container_id}: {e}", exc_info=True)

            if not update_committed:
                error_message = f"Container update failed: {str(e)}"
                if 'container_name' in locals():
                    await self._emit_update_failed_event(
                        host_id, container_id, container_name, error_message
                    )

            return False

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
    # Update monitor if provided
    if monitor and _update_executor.monitor is None:
        _update_executor.monitor = monitor

    # Inject agent_command_executor if not already set
    if not hasattr(_update_executor, 'agent_command_executor'):
        from agent.command_executor import get_agent_command_executor
        _update_executor.agent_command_executor = get_agent_command_executor()
        logger.debug("Injected agent_command_executor into UpdateExecutor")

    # Inject agent_manager if not already set
    if not hasattr(_update_executor, 'agent_manager'):
        from agent.manager import AgentManager
        _update_executor.agent_manager = AgentManager()
        logger.debug("Injected agent_manager into UpdateExecutor")

    return _update_executor
