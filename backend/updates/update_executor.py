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
from datetime import datetime, timezone
from typing import Dict, Optional, Any, Tuple
import docker

from database import DatabaseManager, ContainerUpdate, AutoRestartConfig, ContainerDesiredState, ContainerHttpHealthCheck
from event_bus import Event, EventType as BusEventType, get_event_bus
from utils.async_docker import async_docker_call

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
    7. If health check passes: cleanup backup and emit success event
    8. If health check fails or error: rollback to backup and emit failure event
    9. Update database with new container ID
    """

    def __init__(self, db: DatabaseManager, monitor=None):
        self.db = db
        self.monitor = monitor
        self.updating_containers = set()  # Track containers currently being updated (format: "host_id:container_id")

    def is_container_updating(self, host_id: str, container_id: str) -> bool:
        """Check if a container is currently being updated"""
        composite_key = f"{host_id}:{container_id}"
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
            from database import ContainerUpdate
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
        for update_record in updates_data:
            # Parse composite key
            try:
                host_id, container_id = update_record.container_id.split(":", 1)
            except ValueError:
                logger.error(f"Invalid composite key format: {update_record.container_id}")
                stats["failed"] += 1
                continue

            stats["attempted"] += 1

            try:
                # Execute the update
                success = await self.update_container(host_id, container_id, update_record)

                if success:
                    stats["successful"] += 1
                    logger.info(f"Successfully updated container {container_id} on host {host_id}")
                else:
                    stats["failed"] += 1
                    logger.error(f"Failed to update container {container_id} on host {host_id}")

            except Exception as e:
                logger.error(f"Error updating container {container_id} on host {host_id}: {e}")
                stats["failed"] += 1

        logger.info(f"Auto-update execution complete: {stats}")
        return stats

    async def update_container(
        self,
        host_id: str,
        container_id: str,
        update_record: ContainerUpdate
    ) -> bool:
        """
        Execute update for a single container.

        Args:
            host_id: Host UUID
            container_id: Container short ID (12 chars)
            update_record: ContainerUpdate database record

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Executing update for container {container_id} on host {host_id}")

        # Check if already updating
        if self.is_container_updating(host_id, container_id):
            logger.warning(f"Container {container_id} is already being updated, rejecting concurrent update")
            return False

        # Mark this container as currently updating to prevent auto-restart conflicts
        composite_key = f"{host_id}:{container_id}"
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

            # Step 1: Pull new image
            logger.info(f"Pulling new image: {update_record.latest_image}")
            await self._broadcast_progress(host_id, container_id, "pulling", 20, "Pulling new image")
            await self._pull_image(docker_client, update_record.latest_image)

            # Step 2: Get full container configuration
            logger.info("Getting container configuration")
            await self._broadcast_progress(host_id, container_id, "configuring", 35, "Reading container configuration")
            old_container = await async_docker_call(docker_client.containers.get, container_id)
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

            # Step 5: Start new container
            logger.info(f"Starting new container {container_name}")
            # Use new container ID for broadcasts now that container is recreated
            await self._broadcast_progress(host_id, new_container_id, "starting", 80, "Starting new container")
            await async_docker_call(new_container.start)

            # Step 6: Wait for health check
            health_check_timeout = 120  # 2 minutes default
            with self.db.get_session() as session:
                from database import GlobalSettings
                settings = session.query(GlobalSettings).first()
                if settings:
                    health_check_timeout = settings.health_check_timeout_seconds

            logger.info(f"Waiting for health check (timeout: {health_check_timeout}s)")
            await self._broadcast_progress(host_id, new_container_id, "health_check", 90, "Waiting for health check")
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
                old_composite_key = f"{host_id}:{container_id}"
                new_composite_key = f"{host_id}:{new_container_id}"

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
            # Use new container ID for final broadcast
            await self._broadcast_progress(host_id, new_container_id, "completed", 100, "Update completed successfully")
            return True

        except Exception as e:
            logger.error(f"Error executing update for {container_name if 'container_name' in locals() else container_id}: {e}", exc_info=True)

            # Check if update was already committed to database
            if update_committed:
                # Update succeeded but post-update operations (event emission, cleanup) failed
                # DO NOT ROLLBACK - the update is complete and database is updated
                logger.error(
                    f"Update succeeded for {container_name if 'container_name' in locals() else container_id}, "
                    f"but post-update operations failed: {e}. "
                    f"Container is running with new image, but backup cleanup or event emission failed."
                )
                # Return False to indicate the operation didn't fully complete
                # but don't rollback the successful container update
                return False

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

    async def _pull_image(self, client: docker.DockerClient, image: str):
        """Pull Docker image"""
        try:
            # Use async wrapper to prevent event loop blocking
            await async_docker_call(client.images.pull, image)
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
            )
            return container
        except Exception as e:
            logger.error(f"Error creating container: {e}")
            raise

    async def _wait_for_health(
        self,
        client: docker.DockerClient,
        container_id: str,
        timeout: int = 120
    ) -> bool:
        """
        Wait for container to become healthy.

        Checks:
        1. Container is running
        2. If container has health check, wait for healthy status
        3. If no health check, wait 10s and verify still running

        Returns:
            True if healthy, False if unhealthy or timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Use async wrapper to prevent event loop blocking
                container = await async_docker_call(client.containers.get, container_id)
                state = container.attrs["State"]

                # Check if container is running
                if not state.get("Running", False):
                    logger.warning(f"Container {container_id} is not running")
                    return False

                # Check health if health check is configured
                health = state.get("Health")
                if health:
                    status = health.get("Status")
                    if status == "healthy":
                        logger.info(f"Container {container_id} is healthy")
                        return True
                    elif status == "unhealthy":
                        logger.error(f"Container {container_id} is unhealthy")
                        return False
                    # Status is "starting", continue waiting
                else:
                    # No health check configured
                    # If container has been running for 10s, consider it healthy
                    if time.time() - start_time > 10:
                        logger.info(f"Container {container_id} has no health check, running for 10s - considering healthy")
                        return True

                # Wait before next check
                await asyncio.sleep(2)

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

            # Stop container (use async wrapper)
            await async_docker_call(container.stop, timeout=30)
            logger.info(f"Stopped container {original_name}")

            # Rename to backup (use async wrapper)
            await async_docker_call(container.rename, backup_name)
            logger.info(f"Renamed {original_name} to {backup_name}")

            # Reload container to get updated attributes
            await async_docker_call(container.reload)

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
        1. Remove broken new container (if exists)
        2. Rename backup back to original name
        3. Start backup container

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

            # Step 1: Remove broken new container if it exists
            if new_container:
                try:
                    logger.info(f"Removing failed new container")
                    await async_docker_call(new_container.remove, force=True)
                    logger.info("Successfully removed failed container")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup new container: {cleanup_error}")
                    # Continue with rollback even if cleanup fails

            # Step 2: Remove any container with original name (cleanup edge case)
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

            # Step 3: Rename backup back to original name
            logger.info(f"Renaming backup {backup_name} back to {original_name}")
            await async_docker_call(backup_container.rename, original_name)
            logger.info(f"Renamed backup to {original_name}")

            # Step 4: Start restored container
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
                scope_id=container_id,
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
                scope_id=container_id,
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
