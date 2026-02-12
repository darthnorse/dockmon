"""
Update Executor Service (Router)

Routes container updates to the appropriate executor based on host connection type:
- Go update service for local and mTLS remote hosts (via compose-service)
- Agent executor for agent-based remote hosts (via WebSocket)

This module handles:
1. Routing decisions based on host connection type
2. Event emission (started, completed, failed, etc.)
3. Progress broadcasting to WebSocket clients
4. Auto-update scheduling
5. Database updates after successful updates
"""

import asyncio
import logging
import threading
from typing import Dict, Optional
import docker
from database import (
    DatabaseManager,
    ContainerUpdate,
    GlobalSettings,
    DockerHostDB,
)
from utils.async_docker import async_docker_call
from utils.keys import make_composite_key
from utils.cache import CACHE_REGISTRY
from updates.container_validator import ContainerValidator, ValidationResult
from updates.types import UpdateContext, UpdateResult
from updates.agent_executor import AgentUpdateExecutor
from updates.database_updater import update_container_records_after_update
from updates.event_emitter import UpdateEventEmitter
from updates.update_client import (
    UpdateClient,
    UpdateServiceUnavailable,
    UpdateServiceError,
    RegistryAuth as UpdateRegistryAuth,
)
from agent.command_executor import CommandStatus

logger = logging.getLogger(__name__)

# Maximum concurrent updates to prevent resource exhaustion
MAX_CONCURRENT_UPDATES = 5


class UpdateExecutor:
    """
    Service that routes container updates to appropriate executors.

    Routes to:
    - Go update service: Local hosts, mTLS remote hosts (via compose-service)
    - AgentUpdateExecutor: Agent-based remote hosts (WebSocket communication)

    Handles common concerns:
    - Event emission for audit trail
    - Progress broadcasting to WebSocket clients
    - Database updates after successful updates
    - Auto-update scheduling
    """

    def __init__(self, db: DatabaseManager, monitor=None):
        self.db = db
        self.monitor = monitor
        self.updating_containers = set()  # Track containers being updated
        self._update_lock = threading.Lock()

        # Initialize Go update service client
        self.update_client = UpdateClient()

        # Agent executor will be initialized lazily when agent_manager is available
        self._agent_executor = None

        # Initialize event emitter
        self.event_emitter = UpdateEventEmitter(monitor)

    @property
    def agent_executor(self) -> Optional[AgentUpdateExecutor]:
        """Lazy initialization of agent executor."""
        if self._agent_executor is None:
            # Import here to avoid circular imports
            from agent.command_executor import get_agent_command_executor
            from agent.manager import AgentManager

            self._agent_executor = AgentUpdateExecutor(
                db=self.db,
                agent_manager=AgentManager(monitor=self.monitor),
                agent_command_executor=get_agent_command_executor(),
                monitor=self.monitor,
                get_registry_credentials=self._get_registry_credentials,
            )
        return self._agent_executor

    # Agent-related delegation methods for backward compatibility with tests

    async def _execute_agent_self_update(self, agent_id, host_id, container_id, container_name, update_record):
        """Delegate to AgentUpdateExecutor for backward compatibility."""
        if not self.agent_executor:
            return False
        context = UpdateContext(
            host_id=host_id,
            container_id=container_id,
            container_name=container_name,
            current_image=update_record.current_image,
            new_image=update_record.latest_image,
            update_record_id=update_record.id,
        )
        async def progress_callback(stage, percent, message):
            await self._broadcast_progress(host_id, container_id, stage, percent, message)
        result = await self.agent_executor.execute_self_update(context, progress_callback, update_record, agent_id)
        return result.success

    async def _wait_for_agent_reconnection(self, agent_id, timeout=300.0):
        """Delegate to AgentUpdateExecutor for backward compatibility."""
        if not self.agent_executor:
            return False
        return await self.agent_executor._wait_for_agent_reconnection(agent_id, timeout)

    async def _get_agent_version(self, agent_id):
        """Delegate to AgentUpdateExecutor for backward compatibility."""
        if not self.agent_executor:
            return "unknown"
        return await self.agent_executor._get_agent_version(agent_id)

    def _extract_version_from_image(self, image):
        """Delegate to AgentUpdateExecutor for backward compatibility."""
        if not self.agent_executor:
            return image.split(':')[-1] if ':' in image else 'latest'
        return self.agent_executor._extract_version_from_image(image)

    def is_container_updating(self, host_id: str, container_id: str) -> bool:
        """Check if a container is currently being updated."""
        composite_key = make_composite_key(host_id, container_id)
        return composite_key in self.updating_containers

    def _get_registry_credentials(self, image_name: str) -> Optional[Dict[str, str]]:
        """Get credentials for registry from image name."""
        from utils.registry_credentials import get_registry_credentials
        return get_registry_credentials(self.db, image_name)

    async def execute_auto_updates(self) -> Dict[str, int]:
        """
        Execute auto-updates for all containers that:
        - Have auto_update_enabled = True
        - Have update_available = True

        Returns:
            Dict with counts: {"total": N, "successful": N, "failed": N, "skipped": N}
        """
        stats = {"total": 0, "successful": 0, "failed": 0, "skipped": 0}

        with self.db.get_session() as session:
            updates = session.query(ContainerUpdate).filter_by(
                auto_update_enabled=True,
                update_available=True
            ).all()

            stats["total"] = len(updates)

            if not updates:
                logger.info("No containers eligible for auto-update")
                return stats

            logger.info(f"Found {len(updates)} containers eligible for auto-update")

            # Create list of update records (detach from session)
            update_records = []
            for update in updates:
                host_id, container_id = update.container_id.split(':', 1)
                update_records.append({
                    'host_id': host_id,
                    'container_id': container_id,
                    'update_record': update
                })

        # Execute updates with concurrency limit
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPDATES)

        async def update_with_semaphore(record):
            async with semaphore:
                try:
                    # Refresh update record in new session
                    with self.db.get_session() as session:
                        update_record = session.query(ContainerUpdate).filter_by(
                            container_id=make_composite_key(record['host_id'], record['container_id'])
                        ).first()

                        if not update_record or not update_record.update_available:
                            logger.debug(f"Skipping {record['container_id']}: update no longer available")
                            return {"status": "skipped"}

                        result = await self.update_container(
                            record['host_id'],
                            record['container_id'],
                            update_record
                        )
                        return {"status": "successful" if result else "failed"}
                except Exception as e:
                    logger.error(f"Error updating {record['container_id']}: {e}")
                    return {"status": "failed"}

        results = await asyncio.gather(
            *[update_with_semaphore(record) for record in update_records],
            return_exceptions=True
        )

        for result in results:
            if isinstance(result, Exception):
                stats["failed"] += 1
            elif isinstance(result, dict):
                if result.get("status") == "successful":
                    stats["successful"] += 1
                elif result.get("status") == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1
            else:
                stats["failed"] += 1

        logger.info(f"Auto-update execution complete: {stats}")
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

        Routes to appropriate executor based on host connection type.

        Args:
            host_id: Host UUID
            container_id: Container short ID (12 chars)
            update_record: ContainerUpdate database record
            force: If True, skip ALL validation
            force_warn: If True, allow WARN containers but still block BLOCK

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Executing update for container {container_id} on host {host_id}")

        composite_key = make_composite_key(host_id, container_id)

        # Atomic check-and-set to prevent concurrent updates
        with self._update_lock:
            if composite_key in self.updating_containers:
                logger.warning(f"Container {container_id} is already being updated")
                return False
            self.updating_containers.add(composite_key)

        try:
            # Determine host connection type
            connection_type = 'local'
            with self.db.get_session() as session:
                host = session.query(DockerHostDB).filter_by(id=host_id).first()
                if host:
                    connection_type = host.connection_type or 'local'

            # Get container info
            container_info = await self._get_container_info(host_id, container_id)
            container_name = container_info.get("name", container_id) if container_info else container_id

            # Block DockMon self-update
            container_name_lower = container_name.lower()
            if container_name_lower == 'dockmon' or (
                container_name_lower.startswith('dockmon-') and 'agent' not in container_name_lower
            ):
                error_message = "DockMon cannot update itself. Please update manually."
                logger.warning(f"Blocked self-update for DockMon container '{container_name}'")
                await self.event_emitter.emit_failed(host_id, container_id, container_name, error_message)
                return False

            # Create update context
            context = UpdateContext(
                host_id=host_id,
                container_id=container_id,
                container_name=container_name,
                current_image=update_record.current_image,
                new_image=update_record.latest_image,
                update_record_id=update_record.id,
                force=force,
                force_warn=force_warn,
            )

            # Progress callback
            async def progress_callback(stage: str, percent: int, message: str):
                await self._broadcast_progress(host_id, container_id, stage, percent, message)

            # Route to appropriate executor
            if connection_type == 'agent':
                logger.info(f"Routing update to agent executor (connection_type='agent')")
                result = await self._execute_agent_update(context, progress_callback, update_record)
            else:
                logger.info(f"Routing update to Docker executor (connection_type='{connection_type}')")
                result = await self._execute_docker_update(
                    context, progress_callback, update_record, force, force_warn
                )

            # Handle result
            if result.success:
                # Emit completion event
                await self.event_emitter.emit_completed(
                    host_id=host_id,
                    container_id=result.new_container_id or container_id,
                    container_name=container_name,
                    previous_image=update_record.current_image,
                    new_image=update_record.latest_image,
                    current_digest=update_record.current_digest,
                    latest_digest=update_record.latest_digest,
                    changelog_url=update_record.changelog_url,
                    current_version=update_record.current_version,
                    latest_version=update_record.latest_version,
                )

                # Emit warning if dependent containers failed
                if result.failed_dependents:
                    await self.event_emitter.emit_dependents_failed(
                        host_id,
                        result.new_container_id or container_id,
                        container_name,
                        result.failed_dependents
                    )

                # Update database if container ID changed
                if result.new_container_id and result.new_container_id != container_id:
                    update_container_records_after_update(
                        db=self.db,
                        host_id=host_id,
                        old_container_id=container_id,
                        new_container_id=result.new_container_id,
                        new_image=update_record.latest_image,
                        new_digest=update_record.latest_digest,
                        old_image=update_record.current_image,
                    )

                    # Broadcast container recreated event
                    old_key = make_composite_key(host_id, container_id)
                    new_key = make_composite_key(host_id, result.new_container_id)
                    await self._broadcast_container_recreated(host_id, old_key, new_key, container_name)

                return True
            else:
                # Emit failure event
                await self.event_emitter.emit_failed(
                    host_id, container_id, container_name,
                    result.error_message or "Update failed"
                )

                if result.rollback_performed:
                    await self.event_emitter.emit_rollback_completed(host_id, container_id, container_name)

                return False

        except Exception as e:
            logger.error(f"Error executing update: {e}", exc_info=True)
            await self.event_emitter.emit_failed(
                host_id, container_id, container_id, f"Update failed: {str(e)}"
            )
            return False

        finally:
            # Remove from updating set
            with self._update_lock:
                self.updating_containers.discard(composite_key)

            # Re-evaluate alerts
            await self._re_evaluate_alerts_after_update(host_id, container_id, container_name)

    async def _execute_docker_update(
        self,
        context: UpdateContext,
        progress_callback,
        update_record: ContainerUpdate,
        force: bool,
        force_warn: bool
    ) -> UpdateResult:
        """Execute update via Go update service (compose-service)."""
        # Get Docker client for validation
        docker_client = await self._get_docker_client(context.host_id)
        if not docker_client:
            return UpdateResult.failure_result("Docker client unavailable for host")

        # Validation (unless force)
        if not force:
            try:
                container = await async_docker_call(docker_client.containers.get, context.container_id)
                container_labels = container.labels or {}

                with self.db.get_session() as session:
                    validator = ContainerValidator(session)
                    validation_result = validator.validate_update(
                        host_id=context.host_id,
                        container_id=context.container_id,
                        container_name=context.container_name,
                        image_name=update_record.current_image,
                        labels=container_labels
                    )

                if validation_result.result == ValidationResult.BLOCK:
                    return UpdateResult.failure_result(f"Update blocked: {validation_result.reason}")

                if validation_result.result == ValidationResult.WARN and not force_warn:
                    await self.event_emitter.emit_warning(
                        context.host_id, context.container_id,
                        context.container_name, validation_result.reason
                    )
                    return UpdateResult.failure_result(f"Update requires confirmation: {validation_result.reason}")

            except docker.errors.NotFound:
                return UpdateResult.failure_result("Container not found")

        # Emit started event
        await self.event_emitter.emit_started(
            context.host_id, context.container_id,
            context.container_name, context.new_image
        )

        # Execute via Go update service
        return await self._execute_go_update(context, progress_callback, update_record)

    async def _execute_go_update(
        self,
        context: UpdateContext,
        progress_callback,
        update_record: ContainerUpdate,
    ) -> UpdateResult:
        """Execute update via Go update service."""
        try:
            # Get TLS credentials for remote hosts
            docker_host = None
            tls_ca_cert = None
            tls_cert = None
            tls_key = None

            with self.db.get_session() as session:
                host = session.query(DockerHostDB).filter_by(id=context.host_id).first()
                if host and host.connection_type == 'remote':
                    docker_host = host.url
                    tls_ca_cert = host.tls_ca
                    tls_cert = host.tls_cert
                    tls_key = host.tls_key

            # Get registry credentials
            registry_auth = None
            creds = self._get_registry_credentials(context.new_image)
            if creds:
                registry_auth = UpdateRegistryAuth(
                    username=creds.get('username', ''),
                    password=creds.get('password', ''),
                )

            # Get global settings for timeouts
            with self.db.get_session() as session:
                settings = session.query(GlobalSettings).first()
                health_timeout = settings.health_check_timeout_seconds if settings else 180
                stop_timeout = 30  # Default stop timeout (not configurable)

            # Progress callback wrapper
            async def on_progress(event):
                await progress_callback(event.stage, event.progress, event.message)

            async def on_pull_progress(event):
                # Broadcast pull progress with full layer details
                await self._broadcast_pull_progress(
                    context.host_id,
                    context.container_id,
                    event.overall_progress,
                    event.summary,
                    event.speed_mbps,
                    event.layers,
                    event.total_layers,
                )

            # Execute via Go service
            result = await self.update_client.update_with_progress(
                container_id=context.container_id,
                new_image=context.new_image,
                progress_callback=on_progress,
                pull_progress_callback=on_pull_progress,
                stop_timeout=stop_timeout,
                health_timeout=health_timeout,
                docker_host=docker_host,
                tls_ca_cert=tls_ca_cert,
                tls_cert=tls_cert,
                tls_key=tls_key,
                registry_auth=registry_auth,
            )

            if result.success:
                # Invalidate caches to avoid stale data after update
                for name, fn in CACHE_REGISTRY.items():
                    fn.invalidate()
                    logger.debug(f"Invalidated cache: {name}")

                return UpdateResult(
                    success=True,
                    new_container_id=result.new_container_id,
                    failed_dependents=result.failed_dependents,
                )
            else:
                return UpdateResult(
                    success=False,
                    error_message=result.error or "Update failed",
                    rollback_performed=result.rolled_back,
                )

        except UpdateServiceUnavailable as e:
            logger.error(f"Go update service unavailable: {e}")
            return UpdateResult.failure_result(f"Update service unavailable: {e}")
        except UpdateServiceError as e:
            logger.error(f"Go update service error: {e}")
            return UpdateResult(
                success=False,
                error_message=str(e),
                rollback_performed=e.rolled_back,
            )
        except Exception as e:
            logger.error(f"Unexpected error during Go update: {e}", exc_info=True)
            return UpdateResult.failure_result(f"Update failed: {e}")

    async def _broadcast_pull_progress(
        self,
        host_id: str,
        container_id: str,
        overall_progress: int,
        summary: str,
        speed_mbps: float,
        layers: list = None,
        total_layers: int = 0,
    ):
        """Broadcast image pull progress to WebSocket clients."""
        try:
            if not self.monitor or not hasattr(self.monitor, 'manager'):
                return

            # Format matches frontend LayerProgressData interface
            await self.monitor.manager.broadcast({
                "type": "container_update_layer_progress",
                "data": {
                    "host_id": host_id,
                    "entity_id": container_id,  # Frontend expects entity_id
                    "overall_progress": overall_progress,
                    "layers": layers or [],
                    "total_layers": total_layers,
                    "remaining_layers": max(0, total_layers - len(layers or [])),
                    "summary": summary,
                    "speed_mbps": speed_mbps
                }
            })
        except Exception as e:
            logger.error(f"Error broadcasting pull progress: {e}")

    async def _execute_agent_update(
        self,
        context: UpdateContext,
        progress_callback,
        update_record: ContainerUpdate,
    ) -> UpdateResult:
        """Execute update via agent executor."""
        if not self.agent_executor:
            return UpdateResult.failure_result("Agent executor not available")

        # Emit started event
        await self.event_emitter.emit_started(
            context.host_id, context.container_id,
            context.container_name, context.new_image
        )

        # Execute via agent executor
        return await self.agent_executor.execute(
            context=context,
            progress_callback=progress_callback,
            update_record=update_record,
        )

    async def _get_docker_client(self, host_id: str) -> Optional[docker.DockerClient]:
        """Get Docker client for a specific host from the monitor's client pool."""
        if not self.monitor:
            return None

        try:
            client = self.monitor.clients.get(host_id)
            if not client:
                logger.warning(f"No Docker client found for host {host_id}")
                return None
            return client
        except Exception as e:
            logger.error(f"Error getting Docker client for host {host_id}: {e}")
            return None

    async def _get_container_info(self, host_id: str, container_id: str) -> Optional[Dict]:
        """Get container info from monitor."""
        if not self.monitor:
            return None

        try:
            containers = await self.monitor.get_containers()
            container = next(
                (c for c in containers if (c.short_id == container_id or c.id == container_id) and c.host_id == host_id),
                None
            )
            return container.dict() if container else None
        except Exception as e:
            logger.error(f"Error getting container info: {e}")
            return None

    async def _broadcast_progress(
        self,
        host_id: str,
        container_id: str,
        stage: str,
        progress: int,
        message: str
    ):
        """Broadcast update progress to WebSocket clients."""
        try:
            if not self.monitor or not hasattr(self.monitor, 'manager'):
                return

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
        except Exception as e:
            logger.error(f"Error broadcasting progress: {e}")

    async def _broadcast_container_recreated(
        self,
        host_id: str,
        old_composite_key: str,
        new_composite_key: str,
        container_name: str
    ):
        """Broadcast container_recreated event to keep frontend modal open."""
        try:
            if not self.monitor or not hasattr(self.monitor, 'manager'):
                return

            await self.monitor.manager.broadcast({
                "type": "container_recreated",
                "data": {
                    "host_id": host_id,
                    "old_composite_key": old_composite_key,
                    "new_composite_key": new_composite_key,
                    "container_name": container_name
                }
            })
        except Exception as e:
            logger.error(f"Error broadcasting container_recreated: {e}")

    async def _re_evaluate_alerts_after_update(
        self,
        host_id: str,
        container_id: str,
        container_name: str
    ):
        """Re-evaluate alerts after container update completes."""
        # Note: Per-container alert evaluation was intended here but never implemented.
        # Alerts are evaluated periodically by the evaluation service, so the updated
        # container will be picked up on the next cycle. No immediate action needed.
        logger.debug(f"Container {container_name} updated; alerts will re-evaluate on next cycle")


# Global singleton instance
_update_executor = None


def get_update_executor(db: DatabaseManager = None, monitor=None) -> Optional[UpdateExecutor]:
    """Get or create the global UpdateExecutor instance.

    Returns None if called without db and the singleton hasn't been created yet.
    This allows callers to safely check for executor availability without try/except.
    """
    global _update_executor

    if _update_executor is None:
        if db is None:
            # Return None instead of raising - allows safe optional access
            return None
        _update_executor = UpdateExecutor(db=db, monitor=monitor)
    elif monitor is not None and _update_executor.monitor is None:
        _update_executor.monitor = monitor

    return _update_executor
