"""
Update Executor Service (Router)

Routes container updates to the appropriate executor based on host connection type:
- Docker SDK executor for local and mTLS remote hosts
- Agent executor for agent-based remote hosts

This module handles:
1. Routing decisions based on host connection type
2. Event emission (started, completed, failed, etc.)
3. Progress broadcasting to WebSocket clients
4. Auto-update scheduling
5. Database updates after successful updates
"""

import asyncio
import logging
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Optional, Any
import docker
from sqlalchemy.exc import IntegrityError

from database import (
    DatabaseManager,
    ContainerUpdate,
    AutoRestartConfig,
    ContainerDesiredState,
    ContainerHttpHealthCheck,
    GlobalSettings,
    DeploymentMetadata,
    TagAssignment,
    DockerHostDB,
)
from event_bus import Event, EventType as BusEventType, get_event_bus
from utils.async_docker import async_docker_call
from utils.image_pull_progress import ImagePullProgress
from utils.keys import make_composite_key
from utils.cache import CACHE_REGISTRY
from updates.container_validator import ContainerValidator, ValidationResult
from updates.types import UpdateContext, UpdateResult
from updates.docker_executor import DockerUpdateExecutor
from updates.agent_executor import AgentUpdateExecutor
from agent.command_executor import CommandStatus

logger = logging.getLogger(__name__)

# Maximum concurrent updates to prevent resource exhaustion
MAX_CONCURRENT_UPDATES = 5


class UpdateExecutor:
    """
    Service that routes container updates to appropriate executors.

    Routes to:
    - DockerUpdateExecutor: Local hosts, mTLS remote hosts (direct Docker access)
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

        # Track active image pulls for WebSocket reconnection
        self._active_pulls: Dict[str, Dict] = {}
        self._active_pulls_lock = threading.Lock()

        # Store reference to the main event loop
        self.loop = asyncio.get_event_loop()

        # Initialize shared image pull progress tracker
        self.image_pull_tracker = ImagePullProgress(
            self.loop,
            monitor.manager if monitor and hasattr(monitor, 'manager') else None,
            progress_callback=self._store_pull_progress
        )

        # Initialize executors
        self.docker_executor = DockerUpdateExecutor(
            db=db,
            monitor=monitor,
            image_pull_tracker=self.image_pull_tracker
        )

        # Agent executor will be initialized lazily when agent_manager is available
        self._agent_executor = None

    @property
    def agent_executor(self) -> Optional[AgentUpdateExecutor]:
        """Lazy initialization of agent executor."""
        if self._agent_executor is None and hasattr(self, 'agent_manager'):
            self._agent_executor = AgentUpdateExecutor(
                db=self.db,
                agent_manager=self.agent_manager,
                agent_command_executor=getattr(self, 'agent_command_executor', None),
                monitor=self.monitor,
            )
        return self._agent_executor

    # Delegation methods for backward compatibility with tests
    # These forward to DockerUpdateExecutor which now owns these methods

    def _extract_user_labels(self, old_container_labels, old_image_labels):
        """Delegate to DockerUpdateExecutor for backward compatibility."""
        return self.docker_executor._extract_user_labels(old_container_labels, old_image_labels)

    def _extract_network_config(self, attrs):
        """Delegate to DockerUpdateExecutor for backward compatibility."""
        return self.docker_executor._extract_network_config(attrs)

    async def _extract_container_config_v2(self, container, client, **kwargs):
        """Delegate to DockerUpdateExecutor for backward compatibility."""
        return await self.docker_executor._extract_container_config_v2(container, client, **kwargs)

    async def _create_container_v2(self, client, image, extracted_config, **kwargs):
        """Delegate to DockerUpdateExecutor for backward compatibility."""
        return await self.docker_executor._create_container_v2(client, image, extracted_config, **kwargs)

    async def _rename_container_to_backup(self, client, container, original_name):
        """Delegate to DockerUpdateExecutor for backward compatibility."""
        return await self.docker_executor._rename_container_to_backup(client, container, original_name)

    async def _rollback_container(self, client, backup_container, backup_name, original_name, new_container=None):
        """Delegate to DockerUpdateExecutor for backward compatibility."""
        return await self.docker_executor._rollback_container(client, backup_container, backup_name, original_name, new_container)

    async def _cleanup_backup_container(self, client, backup_container, backup_name):
        """Delegate to DockerUpdateExecutor for backward compatibility."""
        return await self.docker_executor._cleanup_backup_container(client, backup_container, backup_name)

    async def _get_dependent_containers(self, client, container, container_name, container_id):
        """Delegate to DockerUpdateExecutor for backward compatibility."""
        return await self.docker_executor._get_dependent_containers(client, container, container_name, container_id)

    async def _recreate_dependent_container(self, client, dep_info, new_parent_container_id, is_podman=False):
        """Delegate to DockerUpdateExecutor for backward compatibility."""
        return await self.docker_executor._recreate_dependent_container(client, dep_info, new_parent_container_id, is_podman)

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

    def _store_pull_progress(self, host_id: str, entity_id: str, progress_data: Dict):
        """Callback for ImagePullProgress to store progress in _active_pulls."""
        composite_key = make_composite_key(host_id, entity_id)
        with self._active_pulls_lock:
            self._active_pulls[composite_key] = {
                'host_id': host_id,
                'container_id': entity_id,
                **progress_data
            }

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
                await self._emit_update_failed_event(host_id, container_id, container_name, error_message)
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
                await self._emit_update_completed_event(
                    host_id,
                    result.new_container_id or container_id,
                    container_name,
                    update_record.current_image,
                    update_record.latest_image,
                    update_record.current_digest,
                    update_record.latest_digest
                )

                # Update database if container ID changed
                if result.new_container_id and result.new_container_id != container_id:
                    await self._update_database_after_update(
                        host_id, container_id, result.new_container_id, update_record
                    )

                    # Broadcast container recreated event
                    old_key = make_composite_key(host_id, container_id)
                    new_key = make_composite_key(host_id, result.new_container_id)
                    await self._broadcast_container_recreated(host_id, old_key, new_key, container_name)

                return True
            else:
                # Emit failure event
                await self._emit_update_failed_event(
                    host_id, container_id, container_name,
                    result.error_message or "Update failed"
                )

                if result.rollback_performed:
                    await self._emit_rollback_completed_event(host_id, container_id, container_name)

                return False

        except Exception as e:
            logger.error(f"Error executing update: {e}", exc_info=True)
            await self._emit_update_failed_event(
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
        """Execute update via Docker SDK executor."""
        # Get Docker client
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
                    await self._emit_update_warning_event(
                        context.host_id, context.container_id,
                        context.container_name, validation_result.reason
                    )
                    return UpdateResult.failure_result(f"Update requires confirmation: {validation_result.reason}")

            except docker.errors.NotFound:
                return UpdateResult.failure_result("Container not found")

        # Emit started event
        await self._emit_update_started_event(
            context.host_id, context.container_id,
            context.container_name, context.new_image
        )

        # Get Podman flag
        is_podman = False
        if self.monitor and hasattr(self.monitor, 'hosts') and context.host_id in self.monitor.hosts:
            is_podman = getattr(self.monitor.hosts[context.host_id], 'is_podman', False)

        # Execute via Docker executor
        return await self.docker_executor.execute(
            context=context,
            docker_client=docker_client,
            progress_callback=progress_callback,
            update_record=update_record,
            is_podman=is_podman,
            get_registry_credentials=self._get_registry_credentials,
        )

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
        await self._emit_update_started_event(
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

    async def _update_database_after_update(
        self,
        host_id: str,
        old_container_id: str,
        new_container_id: str,
        update_record: ContainerUpdate
    ):
        """Update all database records after container update."""
        old_composite_key = make_composite_key(host_id, old_container_id)
        new_composite_key = make_composite_key(host_id, new_container_id)

        logger.info(f"Updating database: {old_composite_key} -> {new_composite_key}")

        with self.db.get_session() as session:
            # Update ContainerUpdate
            record = session.query(ContainerUpdate).filter_by(
                container_id=old_composite_key
            ).first()

            if record:
                # Handle race condition with update checker
                conflicting = session.query(ContainerUpdate).filter_by(
                    container_id=new_composite_key
                ).first()
                if conflicting:
                    session.delete(conflicting)
                    session.flush()

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
            new_tag_count = session.query(TagAssignment).filter(
                TagAssignment.subject_type == 'container',
                TagAssignment.subject_id == new_composite_key
            ).count()

            if new_tag_count > 0:
                # Reattachment already migrated tags
                session.query(TagAssignment).filter(
                    TagAssignment.subject_type == 'container',
                    TagAssignment.subject_id == old_composite_key
                ).delete()
            else:
                session.query(TagAssignment).filter(
                    TagAssignment.subject_type == 'container',
                    TagAssignment.subject_id == old_composite_key
                ).update({
                    "subject_id": new_composite_key,
                    "last_seen_at": datetime.now(timezone.utc)
                })

            try:
                session.commit()
                logger.debug(f"Database updated: {old_composite_key} -> {new_composite_key}")
            except IntegrityError as e:
                if "tag_assignments" in str(e).lower():
                    session.rollback()
                    logger.debug("Tag migration race detected, continuing")
                else:
                    raise

        # Invalidate image digest cache
        try:
            old_image = update_record.current_image
            if old_image:
                invalidated = self.db.invalidate_image_cache(old_image)
                if invalidated:
                    logger.debug(f"Invalidated {invalidated} cache entries for {old_image}")
        except Exception as e:
            logger.warning(f"Failed to invalidate image cache: {e}")

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
        """Emit UPDATE_COMPLETED event via EventBus."""
        try:
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

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
        except Exception as e:
            logger.error(f"Error emitting update completion event: {e}")

    async def _emit_update_warning_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        warning_message: str
    ):
        """Emit UPDATE_SKIPPED_VALIDATION event via EventBus."""
        try:
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

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
        except Exception as e:
            logger.error(f"Error emitting update warning event: {e}")

    async def _emit_update_failed_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        error_message: str
    ):
        """Emit UPDATE_FAILED event via EventBus."""
        try:
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

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
        except Exception as e:
            logger.error(f"Error emitting update failure event: {e}")

    async def _emit_update_started_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        target_image: str
    ):
        """Emit UPDATE_STARTED event via EventBus."""
        try:
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

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
        except Exception as e:
            logger.error(f"Error emitting update started event: {e}")

    async def _emit_rollback_completed_event(
        self,
        host_id: str,
        container_id: str,
        container_name: str
    ):
        """Emit ROLLBACK_COMPLETED event via EventBus."""
        try:
            host_name = self.monitor.hosts.get(host_id).name if host_id in self.monitor.hosts else host_id

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
        except Exception as e:
            logger.error(f"Error emitting rollback completed event: {e}")

    async def _re_evaluate_alerts_after_update(
        self,
        host_id: str,
        container_id: str,
        container_name: str
    ):
        """Re-evaluate alerts after container update completes."""
        try:
            if not self.monitor or not hasattr(self.monitor, 'alert_evaluation_service'):
                return

            logger.debug(f"Re-evaluating alerts for {container_name} after update")
            await self.monitor.alert_evaluation_service.evaluate_container(
                host_id=host_id,
                container_id=container_id,
                container_name=container_name
            )
        except Exception as e:
            logger.error(f"Error re-evaluating alerts after update: {e}")

    async def cleanup_stale_pull_progress(self):
        """Remove pull progress older than 10 minutes."""
        try:
            cutoff = time.time() - 600

            with self._active_pulls_lock:
                stale_keys = [
                    key for key, data in self._active_pulls.items()
                    if data.get('updated', 0) < cutoff
                ]
                for key in stale_keys:
                    del self._active_pulls[key]

            if stale_keys:
                logger.debug(f"Cleaned up {len(stale_keys)} stale pull progress entries")
        except Exception as e:
            logger.error(f"Error cleaning up stale pull progress: {e}")


# Global singleton instance
_update_executor = None


def get_update_executor(db: DatabaseManager = None, monitor=None) -> UpdateExecutor:
    """Get or create the global UpdateExecutor instance."""
    global _update_executor

    if _update_executor is None:
        if db is None:
            raise ValueError("db is required to create UpdateExecutor")
        _update_executor = UpdateExecutor(db=db, monitor=monitor)
    elif monitor is not None and _update_executor.monitor is None:
        _update_executor.monitor = monitor

    return _update_executor
