"""
Deployment executor service for DockMon v2.1

Executes container and stack deployments with real-time progress tracking,
state management, and rollback support.

Usage:
    executor = DeploymentExecutor(event_bus, docker_monitor)
    deployment_id = await executor.create_deployment(
        host_id="host123",
        name="my-nginx",
        deployment_type="container",
        definition={"image": "nginx:1.25", "ports": {80: 8080}},
    )
    await executor.execute_deployment(deployment_id)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
import secrets

from database import Deployment, DeploymentContainer, DatabaseManager
from .state_machine import DeploymentStateMachine
from .security_validator import SecurityValidator, SecurityLevel
from utils.async_docker import async_docker_call
from utils.image_pull_progress import ImagePullProgress

logger = logging.getLogger(__name__)


class DeploymentExecutor:
    """
    Executes container and stack deployments with progress tracking.

    Integrates with:
    - DeploymentStateMachine for state transitions
    - SecurityValidator for pre-deployment validation
    - EventBus for real-time progress updates
    - DockerMonitor for container operations
    """

    def __init__(self, event_bus, docker_monitor, database_manager: DatabaseManager):
        """
        Initialize deployment executor.

        Args:
            event_bus: EventBus instance for emitting progress events
            docker_monitor: DockerMonitor instance for Docker operations
            database_manager: DatabaseManager instance for database sessions
        """
        self.event_bus = event_bus
        self.docker_monitor = docker_monitor
        self.db = database_manager
        self.state_machine = DeploymentStateMachine()
        self.security_validator = SecurityValidator()

        # Store event loop for layer progress tracker (thread-safe coroutine execution)
        self.loop = asyncio.get_event_loop()

        # Initialize image pull progress tracker (shared with update system)
        self.image_pull_tracker = ImagePullProgress(
            self.loop,
            docker_monitor.manager if hasattr(docker_monitor, 'manager') else None
        )

    def _generate_deployment_id(self, host_id: str) -> str:
        """
        Generate short deployment ID (12 chars) and composite key.

        Args:
            host_id: FULL UUID of host

        Returns:
            Composite key: {host_id}:{deployment_short_id}
        """
        # Generate 12-char ID (same length as Docker container short IDs)
        short_id = secrets.token_hex(6)  # 6 bytes = 12 hex chars
        return f"{host_id}:{short_id}"

    async def create_deployment(
        self,
        host_id: str,
        name: str,
        deployment_type: str,
        definition: Dict[str, Any],
        rollback_on_failure: bool = True,
    ) -> str:
        """
        Create a new deployment record.

        Args:
            host_id: Host UUID to deploy on
            name: Deployment name (must be unique per host)
            deployment_type: 'container' or 'stack'
            definition: Container/stack configuration dictionary
            rollback_on_failure: Whether to rollback on failure (default: True)

        Returns:
            Deployment composite ID: {host_id}:{deployment_id}

        Raises:
            ValueError: If deployment_type invalid or name already exists
            SecurityException: If security validation fails with CRITICAL issues
        """
        with self.db.get_session() as session:
            # Validate deployment type
            if deployment_type not in ('container', 'stack'):
                raise ValueError(f"Invalid deployment_type: {deployment_type}. Must be 'container' or 'stack'")

            # Check for duplicate name on this host
            existing = session.query(Deployment).filter_by(
                host_id=host_id,
                name=name
            ).first()
            if existing:
                raise ValueError(f"Deployment with name '{name}' already exists on this host")

            # Security validation
            violations = self.security_validator.validate_container_config(definition, host_id)
            if self.security_validator.has_blocking_violations(violations):
                formatted = self.security_validator.format_violations(violations)
                raise SecurityException(f"Security validation failed:\n{formatted}")

            # Log warnings for non-blocking violations
            warning_violations = self.security_validator.filter_by_level(
                violations, SecurityLevel.HIGH, include_higher=True
            )
            if warning_violations:
                logger.warning(f"Deployment {name} has security warnings: {len(warning_violations)} violations")

            # Generate deployment ID
            deployment_id = self._generate_deployment_id(host_id)
            utcnow = datetime.now(timezone.utc)

            # Create deployment record
            deployment = Deployment(
                id=deployment_id,
                host_id=host_id,
                deployment_type=deployment_type,
                name=name,
                status='planning',
                definition=json.dumps(definition),
                progress_percent=0,
                created_at=utcnow,
                updated_at=utcnow,
                committed=False,
                rollback_on_failure=rollback_on_failure,
            )

            session.add(deployment)
            session.commit()

            logger.info(f"Created deployment {deployment_id} ({deployment_type}: {name}) on host {host_id[:8]}")

            # Emit creation event
            await self._emit_deployment_event(deployment, 'DEPLOYMENT_CREATED')

            return deployment_id

    async def execute_deployment(self, deployment_id: str) -> None:
        """
        Execute a deployment (pull image, create container, start container).

        This is the main deployment workflow with progress tracking.

        Args:
            deployment_id: Composite deployment ID

        State Flow:
            planning → executing → completed
                              ↓ (on error)
                           failed → rolled_back (if rollback enabled)

        Commitment Point:
            Once container is created in Docker, deployment.committed=True.
            After this point, rollback will NOT destroy the container.
        """
        with self.db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment:
                raise ValueError(f"Deployment {deployment_id} not found")

            # Transition to executing
            if not self.state_machine.transition(deployment, 'executing'):
                raise ValueError(f"Cannot start deployment {deployment_id} in status {deployment.status}")

            await self._update_progress(session, deployment, 0, 'Validating configuration')
            session.commit()

            try:
                # Parse definition
                definition = json.loads(deployment.definition)

                if deployment.deployment_type == 'container':
                    await self._execute_container_deployment(session, deployment, definition)
                elif deployment.deployment_type == 'stack':
                    await self._execute_stack_deployment(session, deployment, definition)
                else:
                    raise ValueError(f"Unknown deployment_type: {deployment.deployment_type}")

                # Success - transition to completed
                self.state_machine.transition(deployment, 'completed')
                await self._update_progress(session, deployment, 100, 'Deployment completed successfully')
                session.commit()

                logger.info(f"Deployment {deployment_id} completed successfully")
                await self._emit_deployment_event(deployment, 'DEPLOYMENT_COMPLETED')

            except Exception as e:
                logger.error(f"Deployment {deployment_id} failed: {e}", exc_info=True)

                # Mark as failed
                self.state_machine.transition(deployment, 'failed')
                deployment.error_message = str(e)
                session.commit()

                await self._emit_deployment_event(deployment, 'DEPLOYMENT_FAILED')

                # Check if rollback needed
                if self.state_machine.should_rollback(deployment):
                    logger.info(f"Rolling back deployment {deployment_id}")
                    await self._rollback_deployment(session, deployment)
                else:
                    logger.info(f"Rollback not needed for deployment {deployment_id} (committed={deployment.committed})")

                raise

    async def _execute_container_deployment(
        self,
        session: Session,
        deployment: Deployment,
        definition: Dict[str, Any]
    ) -> None:
        """Execute single container deployment."""
        host_id = deployment.host_id
        client = self.docker_monitor.clients.get(host_id)
        if not client:
            raise ValueError(f"Docker client not found for host {host_id}")

        # Stage 1: Pull image with layer-by-layer progress (10-50%)
        image = definition.get('image')
        if not image:
            raise ValueError("Container definition missing 'image' field")

        await self._update_progress(session, deployment, 10, f'Pulling image {image}')
        session.commit()

        # Use shared ImagePullProgress for detailed layer tracking
        # Broadcasts real-time layer progress via WebSocket (same as update system)
        await self.image_pull_tracker.pull_with_progress(
            client,
            image,
            host_id,
            deployment.id,  # Use deployment ID as entity_id
            event_type="deployment_layer_progress",
            timeout=1800  # 30 minutes
        )
        logger.info(f"Pulled image {image} for deployment {deployment.id}")

        # Stage 2: Create container (50-70%)
        await self._update_progress(session, deployment, 50, 'Creating container')
        session.commit()

        # Build container create args
        create_args = self._build_container_create_args(definition)

        container = await async_docker_call(client.containers.create, **create_args)
        container_id = container.short_id

        logger.info(f"Created container {container_id} for deployment {deployment.id}")

        # COMMITMENT POINT - container created in Docker
        self.state_machine.mark_committed(deployment)
        session.commit()

        # Link deployment to container
        link = DeploymentContainer(
            deployment_id=deployment.id,
            container_id=container_id,
            service_name=None,  # NULL for single containers
            created_at=datetime.now(timezone.utc)
        )
        session.add(link)
        session.commit()

        # Stage 3: Start container (70-100%)
        await self._update_progress(session, deployment, 70, 'Starting container')
        session.commit()

        await async_docker_call(container.start)
        logger.info(f"Started container {container_id} for deployment {deployment.id}")

        await self._update_progress(session, deployment, 90, 'Verifying container is running')
        session.commit()

        # Reload container state
        await async_docker_call(container.reload)

        if container.status != 'running':
            raise RuntimeError(f"Container {container_id} not running (status: {container.status})")

        logger.info(f"Container {container_id} verified running")

    async def _execute_stack_deployment(
        self,
        session: Session,
        deployment: Deployment,
        definition: Dict[str, Any]
    ) -> None:
        """Execute Docker Compose stack deployment."""
        # Stack deployment implementation (future enhancement)
        # For now, raise NotImplementedError
        raise NotImplementedError("Stack deployments not yet implemented in v2.1")

    def _build_container_create_args(self, definition: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build Docker SDK container.create() arguments from definition.

        Maps DockMon definition format to Docker SDK parameters.
        """
        args = {}

        # Required
        args['image'] = definition['image']

        # Optional - basic
        if 'name' in definition:
            args['name'] = definition['name']
        if 'command' in definition:
            args['command'] = definition['command']
        if 'entrypoint' in definition:
            args['entrypoint'] = definition['entrypoint']
        if 'hostname' in definition:
            args['hostname'] = definition['hostname']
        if 'user' in definition:
            args['user'] = definition['user']
        if 'working_dir' in definition:
            args['working_dir'] = definition['working_dir']

        # Environment variables
        if 'environment' in definition:
            args['environment'] = definition['environment']

        # Ports
        if 'ports' in definition:
            args['ports'] = definition['ports']

        # Volumes
        if 'volumes' in definition:
            args['volumes'] = definition['volumes']

        # Network
        if 'network_mode' in definition:
            args['network_mode'] = definition['network_mode']
        if 'networks' in definition:
            args['network'] = definition['networks']

        # Security
        if 'privileged' in definition:
            args['privileged'] = definition['privileged']
        if 'cap_add' in definition:
            args['cap_add'] = definition['cap_add']
        if 'cap_drop' in definition:
            args['cap_drop'] = definition['cap_drop']

        # Resource limits
        if 'mem_limit' in definition:
            args['mem_limit'] = definition['mem_limit']
        if 'memswap_limit' in definition:
            args['memswap_limit'] = definition['memswap_limit']
        if 'cpu_shares' in definition:
            args['cpu_shares'] = definition['cpu_shares']
        if 'cpuset_cpus' in definition:
            args['cpuset_cpus'] = definition['cpuset_cpus']
        if 'cpus' in definition:
            args['nano_cpus'] = int(float(definition['cpus']) * 1e9)

        # Restart policy
        if 'restart_policy' in definition:
            args['restart_policy'] = definition['restart_policy']

        # Labels
        if 'labels' in definition:
            args['labels'] = definition['labels']

        # Detach (always True for daemon containers)
        args['detach'] = True

        return args

    async def _rollback_deployment(self, session: Session, deployment: Deployment) -> None:
        """
        Rollback a failed deployment.

        Only rolls back if deployment.committed=False (commitment point not reached).
        If committed=True, leaves created containers in place.
        """
        if deployment.committed:
            logger.warning(
                f"Deployment {deployment.id} rollback skipped - operation was committed. "
                f"Container(s) will remain in current state."
            )
            return

        # Get associated containers
        containers = session.query(DeploymentContainer).filter_by(
            deployment_id=deployment.id
        ).all()

        if not containers:
            logger.info(f"No containers to rollback for deployment {deployment.id}")
            self.state_machine.transition(deployment, 'rolled_back')
            session.commit()
            return

        # Rollback each container (remove)
        client = self.docker_monitor.clients.get(deployment.host_id)
        if not client:
            logger.error(f"Cannot rollback deployment {deployment.id} - Docker client not found")
            return

        for link in containers:
            try:
                container = await async_docker_call(client.containers.get, link.container_id)
                await async_docker_call(container.remove, force=True)
                logger.info(f"Rolled back container {link.container_id} for deployment {deployment.id}")
            except Exception as e:
                logger.error(f"Failed to rollback container {link.container_id}: {e}")

        # Mark as rolled back
        self.state_machine.transition(deployment, 'rolled_back')
        session.commit()

        await self._emit_deployment_event(deployment, 'DEPLOYMENT_ROLLED_BACK')

    async def _update_progress(
        self,
        session: Session,
        deployment: Deployment,
        percent: int,
        stage: str
    ) -> None:
        """Update deployment progress and emit event."""
        deployment.progress_percent = percent
        deployment.current_stage = stage
        deployment.updated_at = datetime.now(timezone.utc)

        logger.debug(f"Deployment {deployment.id}: {percent}% - {stage}")

        # Emit progress event
        await self._emit_deployment_event(deployment, 'DEPLOYMENT_PROGRESS')

    async def _emit_deployment_event(self, deployment: Deployment, event_type: str) -> None:
        """
        Emit deployment event for WebSocket broadcasting.

        Args:
            deployment: Deployment instance
            event_type: Event type (DEPLOYMENT_CREATED, DEPLOYMENT_PROGRESS, etc.)
        """
        payload = {
            'type': event_type.lower(),
            'deployment_id': deployment.id,
            'host_id': deployment.host_id,
            'name': deployment.name,
            'status': deployment.status,
            'progress_percent': deployment.progress_percent,
            'current_stage': deployment.current_stage,
            'error_message': deployment.error_message,
            'created_at': deployment.created_at.isoformat() + 'Z' if deployment.created_at else None,
            'completed_at': deployment.completed_at.isoformat() + 'Z' if deployment.completed_at else None,
        }

        # Broadcast via ConnectionManager
        try:
            if self.docker_monitor and hasattr(self.docker_monitor, 'manager'):
                await self.docker_monitor.manager.broadcast(payload)
        except Exception as e:
            logger.error(f"Error broadcasting deployment event: {e}")


class SecurityException(Exception):
    """Raised when security validation blocks deployment."""
    pass
