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
from docker import APIClient
import docker.tls

from database import DatabaseManager, ContainerUpdate, AutoRestartConfig, ContainerDesiredState, ContainerHttpHealthCheck, GlobalSettings
from event_bus import Event, EventType as BusEventType, get_event_bus
from utils.async_docker import async_docker_call
from utils.keys import make_composite_key, parse_composite_key
from updates.container_validator import ContainerValidator, ValidationResult

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

    def is_container_updating(self, host_id: str, container_id: str) -> bool:
        """Check if a container is currently being updated"""
        composite_key = make_composite_key(host_id, container_id)
        return composite_key in self.updating_containers

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
                # Try streaming pull with layer progress
                await self._pull_image_with_progress(
                    docker_client,
                    update_record.latest_image,
                    host_id,
                    container_id
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
            is_healthy = await self._wait_for_health(
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

                    session.commit()
                    update_committed = True  # Mark update as committed
                    logger.debug(
                        f"Updated database records from {old_composite_key} to {new_composite_key}: "
                        f"ContainerUpdate, AutoRestartConfig, ContainerDesiredState, ContainerHttpHealthCheck"
                    )

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
            # Use original container_id for final broadcast so frontend receives it
            await self._broadcast_progress(host_id, container_id, "completed", 100, "Update completed successfully")
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

    def _clone_api_client(self, client: docker.DockerClient) -> APIClient:
        """
        Create a low-level APIClient with the same connection settings as the high-level client.

        This safely copies TLS certificates, headers, and verification settings from the
        high-level Docker client to a low-level APIClient for streaming operations.

        CRITICAL: TLS config must be passed to APIClient constructor, not set after.
        The constructor validates the connection immediately, so certs must be present.

        Args:
            client: High-level Docker client

        Returns:
            Low-level APIClient configured with same connection settings
        """
        # Extract TLS configuration from high-level client
        cert = getattr(client.api, "cert", None)
        verify = getattr(client.api, "verify", True)

        # Build TLS config for APIClient constructor
        # If client cert exists, create TLSConfig object with proper mTLS settings
        if cert:
            # cert is tuple: (client_cert_path, client_key_path)
            # verify is either bool or string path to CA cert
            if isinstance(verify, str):
                # mTLS with CA certificate path
                tls_config = docker.tls.TLSConfig(
                    client_cert=cert,
                    ca_cert=verify,
                    verify=True
                )
            else:
                # TLS with client cert but no CA (unusual but supported)
                tls_config = docker.tls.TLSConfig(
                    client_cert=cert,
                    verify=verify
                )
        else:
            # No client cert
            if isinstance(verify, str):
                # TLS with server validation: CA cert but no client cert
                # This validates the server's certificate against a custom CA
                tls_config = docker.tls.TLSConfig(ca_cert=verify, verify=True)
            else:
                # Plain connection: no certs, just bool verify (True/False)
                tls_config = verify

        # Create APIClient with TLS config passed to constructor
        # This ensures the constructor's /version check uses the correct certs
        api_client = APIClient(
            base_url=client.api.base_url,
            tls=tls_config
        )

        # Copy headers (auth tokens, user-agent, etc.)
        api_client.headers = getattr(client.api, "headers", {})

        return api_client

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

    async def _pull_image_with_progress(
        self,
        client: docker.DockerClient,
        image: str,
        host_id: str,
        container_id: str,
        timeout: int = 1800
    ):
        """
        Pull Docker image with layer-by-layer progress tracking.

        Uses Docker's low-level API to stream pull status and broadcast
        real-time progress to WebSocket clients. Handles cached layers,
        download speed calculation, and WebSocket reconnection state.

        CRITICAL: Wrapped in async_docker_call to prevent event loop blocking.

        Args:
            client: High-level Docker client (for base URL and TLS config)
            image: Image name with tag (e.g., "nginx:latest")
            host_id: Full UUID of the Docker host
            container_id: SHORT container ID (12 chars)
            timeout: Maximum seconds for the entire pull operation
        """
        composite_key = make_composite_key(host_id, container_id)

        # Wrap the entire streaming operation in async_docker_call
        # to prevent blocking the event loop (DockMon standard)
        await async_docker_call(
            self._stream_pull_progress,
            client,
            image,
            host_id,
            container_id,
            composite_key,
            timeout
        )

    def _stream_pull_progress(
        self,
        client: docker.DockerClient,
        image: str,
        host_id: str,
        container_id: str,
        composite_key: str,
        timeout: int
    ):
        """
        Synchronous method that streams Docker pull progress.

        Called via async_docker_call to run in thread pool.
        This is the proper pattern per CLAUDE.md standards.
        """
        # Create low-level API client with same connection settings
        # Uses helper function for clean, explicit TLS/cert copying
        api_client = self._clone_api_client(client)

        # Layer tracking state
        layer_status = {}  # {layer_id: {"status": str, "current": int, "total": int}}

        # Progress tracking state
        last_broadcast = 0
        last_percent = 0
        last_total_bytes = 0
        last_speed_check = time.time()
        current_speed_mbps = 0.0
        speed_samples = []  # For moving average smoothing (prevents jittery display)
        total_bytes = 0  # Initialize to prevent NameError if stream has zero iterations

        start_time = time.time()

        try:
            # Stream pull with decode (returns generator of dicts)
            stream = api_client.pull(image, stream=True, decode=True)

            for line in stream:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise TimeoutError(f"Image pull exceeded {timeout} seconds")

                layer_id = line.get('id')
                status = line.get('status', '')
                progress_detail = line.get('progressDetail', {})

                # Skip non-layer messages (e.g., "Pulling from library/nginx")
                if not layer_id:
                    continue

                # Handle cached layers (critical for correct progress calculation)
                if status in ['Already exists', 'Pull complete']:
                    # For cached layers, mark as complete with no download
                    # Estimate size from existing data or mark as unknown
                    existing = layer_status.get(layer_id, {})
                    total = existing.get('total', 0)

                    layer_status[layer_id] = {
                        'status': status,
                        'current': total,  # Fully "downloaded" (from cache)
                        'total': total,
                    }
                    continue

                # Update layer tracking for active downloads/extractions
                current = progress_detail.get('current', 0)
                total = progress_detail.get('total', 0)

                # Preserve total if not provided in this update
                if total == 0 and layer_id in layer_status:
                    total = layer_status[layer_id].get('total', 0)

                layer_status[layer_id] = {
                    'status': status,
                    'current': current,
                    'total': total,
                }

                # Calculate overall progress (bytes-based when available)
                total_bytes = sum(l['total'] for l in layer_status.values() if l['total'] > 0)
                downloaded_bytes = sum(l['current'] for l in layer_status.values())

                if total_bytes > 0:
                    overall_percent = int((downloaded_bytes / total_bytes) * 100)
                else:
                    # Fallback: estimate based on layer completion count
                    completed = sum(1 for l in layer_status.values() if 'complete' in l['status'].lower() or l['status'] == 'Already exists')
                    overall_percent = int((completed / max(len(layer_status), 1)) * 100)

                # Calculate download speed (MB/s) with moving average smoothing
                now = time.time()
                time_delta = now - last_speed_check

                if time_delta >= 1.0:  # Update speed every second
                    bytes_delta = downloaded_bytes - last_total_bytes
                    if bytes_delta > 0:
                        # Calculate raw speed
                        raw_speed = (bytes_delta / time_delta) / (1024 * 1024)

                        # Apply 3-sample moving average to smooth jitter on variable networks
                        speed_samples.append(raw_speed)
                        if len(speed_samples) > 3:
                            speed_samples.pop(0)

                        # Use smoothed average for display
                        current_speed_mbps = sum(speed_samples) / len(speed_samples)

                    last_total_bytes = downloaded_bytes
                    last_speed_check = now

                # Throttle broadcasts (every 500ms OR 5% change OR completion events)
                should_broadcast = (
                    now - last_broadcast >= 0.5 or  # 500ms elapsed
                    abs(overall_percent - last_percent) >= 5 or  # 5% change
                    'complete' in status.lower() or  # Always broadcast completions
                    status == 'Already exists'  # Broadcast cache hits
                )

                if should_broadcast:
                    # Run broadcast in event loop (thread-safe)
                    # Use stored loop reference instead of get_event_loop() for Python 3.11+ compatibility
                    asyncio.run_coroutine_threadsafe(
                        self._broadcast_layer_progress(
                            host_id,
                            container_id,
                            layer_status,
                            overall_percent,
                            current_speed_mbps
                        ),
                        self.loop  # Thread-safe: explicit loop reference from __init__
                    ).result()

                    last_broadcast = now
                    last_percent = overall_percent

            # Final broadcast at 100%
            asyncio.run_coroutine_threadsafe(
                self._broadcast_layer_progress(
                    host_id,
                    container_id,
                    layer_status,
                    100,
                    current_speed_mbps
                ),
                self.loop  # Thread-safe: explicit loop reference from __init__
            ).result()

            logger.info(f"Successfully pulled {image} with {len(layer_status)} layers ({total_bytes / (1024 * 1024):.1f} MB)")

        except TimeoutError:
            logger.error(f"Image pull timed out after {timeout}s for {image}")
            raise
        except Exception as e:
            logger.error(f"Error streaming image pull for {image}: {e}", exc_info=True)
            raise
        finally:
            # CRITICAL: Clean up API client to prevent connection leaks
            try:
                api_client.close()
            except Exception as cleanup_error:
                logger.warning(f"Error closing API client: {cleanup_error}")

            # Remove from active pulls tracking (thread-safe)
            with self._active_pulls_lock:
                if composite_key in self._active_pulls:
                    del self._active_pulls[composite_key]

    async def _broadcast_layer_progress(
        self,
        host_id: str,
        container_id: str,
        layer_status: Dict[str, Dict],
        overall_percent: int,
        speed_mbps: float = 0.0
    ):
        """
        Broadcast detailed layer progress to WebSocket clients.

        Sends both old-style simple progress (for compatibility) and
        new-style layer progress (for enhanced UI).

        Also stores progress in _active_pulls for WebSocket reconnection.
        """
        try:
            if not self.monitor or not hasattr(self.monitor, 'manager'):
                return

            composite_key = make_composite_key(host_id, container_id)

            # Calculate summary statistics
            total_layers = len(layer_status)
            downloading = sum(1 for l in layer_status.values() if l['status'] == 'Downloading')
            extracting = sum(1 for l in layer_status.values() if l['status'] == 'Extracting')
            complete = sum(1 for l in layer_status.values() if 'complete' in l['status'].lower())
            cached = sum(1 for l in layer_status.values() if l['status'] == 'Already exists')

            # Build summary message with download speed
            if total_layers == 0:
                # Edge case: image with no layers (manifest-only or unusual image)
                summary = "Pull complete (manifest only)"
            elif downloading > 0:
                speed_text = f" @ {speed_mbps:.1f} MB/s" if speed_mbps > 0 else ""
                summary = f"Downloading {downloading} of {total_layers} layers ({overall_percent}%){speed_text}"
            elif extracting > 0:
                summary = f"Extracting {extracting} of {total_layers} layers ({overall_percent}%)"
            elif complete == total_layers:
                cache_text = f" ({cached} cached)" if cached > 0 else ""
                summary = f"Pull complete ({total_layers} layers{cache_text})"
            else:
                summary = f"Pulling image ({overall_percent}%)"

            # Prepare layer data for frontend (convert to list, sorted by status)
            layers = []
            for layer_id, data in layer_status.items():
                percent = 0
                if data['total'] > 0:
                    percent = int((data['current'] / data['total']) * 100)

                layers.append({
                    'id': layer_id,
                    'status': data['status'],
                    'current': data['current'],
                    'total': data['total'],
                    'percent': percent
                })

            # Sort: downloading first, then extracting, then verifying, then complete
            # This keeps active layers at the top for better UX
            status_priority = {
                'Downloading': 1,
                'Extracting': 2,
                'Verifying Checksum': 3,
                'Download complete': 4,
                'Already exists': 5,
                'Pull complete': 6,
                'Pulling fs layer': 0
            }
            layers.sort(key=lambda l: status_priority.get(l['status'], 99))

            # Trim large layer lists for network efficiency
            # UI only displays top 15, so sending all 50+ layers is wasteful
            # Send top 20 active layers + count for remaining
            total_layer_count = len(layers)
            remaining_layers = 0
            if len(layers) > 20:
                layers_to_broadcast = layers[:20]
                remaining_layers = len(layers) - 20
            else:
                layers_to_broadcast = layers

            # Store progress for WebSocket reconnection (thread-safe)
            # Trimmed to top 20 layers for memory efficiency and network bandwidth
            with self._active_pulls_lock:
                self._active_pulls[composite_key] = {
                    'host_id': host_id,
                    'container_id': container_id,
                    'overall_progress': overall_percent,
                    'layers': layers_to_broadcast,  # Top 20 layers
                    'total_layers': total_layer_count,
                    'remaining_layers': remaining_layers,
                    'summary': summary,
                    'speed_mbps': speed_mbps,
                    'updated': time.time()
                }

            # Broadcast NEW message type (detailed layer progress)
            await self.monitor.manager.broadcast({
                "type": "container_update_layer_progress",
                "data": {
                    "host_id": host_id,
                    "container_id": container_id,
                    "overall_progress": overall_percent,
                    "layers": layers_to_broadcast,  # Trimmed to top 20 for network efficiency
                    "total_layers": total_layer_count,
                    "remaining_layers": remaining_layers,
                    "summary": summary,
                    "speed_mbps": speed_mbps
                }
            })

            # ALSO broadcast OLD message type for backward compatibility
            # This ensures old clients still get basic progress updates
            await self.monitor.manager.broadcast({
                "type": "container_update_progress",
                "data": {
                    "host_id": host_id,
                    "container_id": container_id,
                    "stage": "pulling",
                    "progress": 20 + int(overall_percent * 0.15),  # Map 0-100 to 20-35%
                    "message": summary
                }
            })

        except Exception as e:
            logger.error(f"Error broadcasting layer progress: {e}", exc_info=True)

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

    async def _wait_for_health(
        self,
        client: docker.DockerClient,
        container_id: str,
        timeout: int = 10  # NOTE: This default is never used - caller always passes settings.health_check_timeout_seconds
    ) -> bool:
        """
        Wait for container to become healthy.

        NOTE: The timeout parameter default (10s) is NOT used in practice.
        The caller always explicitly passes settings.health_check_timeout_seconds
        which is user-configurable via Settings → Container Updates (default: 60s).
        This function default exists only for defensive programming.

        Health check logic:
        1. Wait for container to reach "running" state (up to timeout)
        2. If container has Docker health check: Poll for "healthy" status (up to timeout)
           - Short-circuits immediately when "healthy" detected
        3. If no health check: Wait 3s for stability, verify still running
           - Short-circuits as soon as container is running + stable

        Returns:
            True if healthy/stable, False if unhealthy/crashed/timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Use async wrapper to prevent event loop blocking
                container = await async_docker_call(client.containers.get, container_id)
                state = container.attrs["State"]

                # Check if container is running
                if not state.get("Running", False):
                    # Not running YET - wait and retry (don't fail immediately!)
                    await asyncio.sleep(1)
                    continue

                # Container IS running - now check health status
                health = state.get("Health")
                if health:
                    # Has Docker health check - poll for healthy status
                    status = health.get("Status")
                    if status == "healthy":
                        logger.info(f"Container {container_id} is healthy")
                        return True
                    elif status == "unhealthy":
                        logger.error(f"Container {container_id} is unhealthy")
                        return False
                    # Status is "starting", continue waiting
                    await asyncio.sleep(2)
                else:
                    # No health check configured - container is running (verified above)
                    # Wait 3s for stability, then verify still running
                    logger.info(f"Container {container_id} has no health check, waiting 3s for stability")
                    await asyncio.sleep(3)

                    # Check if STILL running (catch quick crashes)
                    container = await async_docker_call(client.containers.get, container_id)
                    state = container.attrs["State"]
                    if state.get("Running", False):
                        logger.info(f"Container {container_id} stable after 3s, considering healthy")
                        return True
                    else:
                        logger.error(f"Container {container_id} crashed within 3s of starting")
                        return False

            except Exception as e:
                logger.error(f"Error checking container health: {e}")
                return False

        logger.error(f"Health check timeout after {timeout}s for container {container_id}")
        return False

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
    return _update_executor
