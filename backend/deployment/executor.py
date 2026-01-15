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

Refactored in v2.2.0:
- Container deployment logic: container_executor.py
- Stack deployment logic: stack_executor.py
- Container args builder: build_args.py
- Network/IPAM helpers: network_helpers.py
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
import secrets

from database import (
    Deployment,
    DeploymentContainer,
    DeploymentMetadata,
    DatabaseManager,
    DockerHostDB,
)
from .state_machine import DeploymentStateMachine
from .security_validator import SecurityValidator, SecurityLevel
from .host_connector import get_host_connector
from .container_executor import execute_container_deployment
from .stack_executor import execute_stack_deployment
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

        # Image pull tracker initialized lazily to get running loop in async context
        self._image_pull_tracker = None

    @property
    def image_pull_tracker(self) -> ImagePullProgress:
        """Lazy initialization of image pull tracker to avoid event loop issues."""
        if self._image_pull_tracker is None:
            loop = asyncio.get_running_loop()
            self._image_pull_tracker = ImagePullProgress(
                loop,
                self.docker_monitor.manager if hasattr(self.docker_monitor, 'manager') else None
            )
        return self._image_pull_tracker

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
        user_id: int,
        rollback_on_failure: bool = True,
        created_by: Optional[str] = None,
    ) -> str:
        """
        Create a new deployment record.

        Args:
            host_id: Host UUID to deploy on
            name: Deployment name (must be unique per host)
            deployment_type: 'container' or 'stack'
            definition: Container/stack configuration dictionary
            user_id: User ID of creator (for authorization and audit)
            rollback_on_failure: Whether to rollback on failure (default: True)
            created_by: Username who created the deployment (for audit tracking)

        Returns:
            Deployment composite ID: {host_id}:{deployment_id}

        Raises:
            ValueError: If deployment_type invalid or name already exists
            SecurityException: If security validation fails with CRITICAL issues
        """
        with self.db.get_session() as session:
            # Validate deployment type
            if deployment_type not in ('container', 'stack'):
                raise ValueError(
                    f"Invalid deployment_type: {deployment_type}. "
                    "Must be 'container' or 'stack'"
                )

            # Validate definition structure matches deployment type
            if deployment_type == 'container':
                if 'image' not in definition:
                    raise ValueError(
                        "Container deployments require an 'image' field at root level. "
                        "Example: {\"image\": \"nginx:alpine\", \"ports\": [\"80:80\"]}"
                    )
                if 'compose_yaml' in definition or 'services' in definition:
                    raise ValueError(
                        "Container deployments cannot use 'compose_yaml' or 'services'. "
                        "Use deployment_type='stack' for Docker Compose multi-service deployments."
                    )

            elif deployment_type == 'stack':
                if 'compose_yaml' not in definition:
                    raise ValueError(
                        "Stack deployments require a 'compose_yaml' field with Docker Compose YAML. "
                        "Example: {\"compose_yaml\": \"services:\\n  nginx:\\n    image: nginx:alpine\"}"
                    )
                if 'image' in definition:
                    raise ValueError(
                        "Stack deployments use 'compose_yaml' with 'services', not a root-level 'image'. "
                        "Use deployment_type='container' for single-container deployments."
                    )

            # Check for duplicate name on this host
            existing = session.query(Deployment).filter_by(
                host_id=host_id,
                name=name
            ).first()
            if existing:
                raise ValueError(f"Deployment with name '{name}' already exists on this host")

            # Security validation (container deployments only)
            # Stack deployments use native Docker Compose which handles its own execution.
            # The SecurityValidator doesn't parse compose YAML, so it provides no value for stacks.
            if deployment_type == 'container':
                violations = self.security_validator.validate_container_config(definition, host_id)
                if self.security_validator.has_blocking_violations(violations):
                    formatted = self.security_validator.format_violations(violations)
                    raise SecurityException(f"Security validation failed:\n{formatted}")

                # Log warnings for non-blocking violations
                warning_violations = self.security_validator.filter_by_level(
                    violations, SecurityLevel.HIGH, include_higher=True
                )
                if warning_violations:
                    logger.warning(
                        f"Deployment {name} has security warnings: {len(warning_violations)} violations"
                    )

            # Generate deployment ID
            deployment_id = self._generate_deployment_id(host_id)
            utcnow = datetime.now(timezone.utc)

            # Create deployment record
            deployment = Deployment(
                id=deployment_id,
                host_id=host_id,
                user_id=user_id,
                deployment_type=deployment_type,
                name=name,
                status='planning',
                definition=json.dumps(definition),
                progress_percent=0,
                created_at=utcnow,
                updated_at=utcnow,
                created_by=created_by,
                committed=False,
                rollback_on_failure=rollback_on_failure,
            )

            session.add(deployment)
            session.commit()

            logger.info(
                f"Created deployment {deployment_id} ({deployment_type}: {name}) "
                f"on host {host_id[:8]}"
            )

            # Emit creation event
            await self._emit_deployment_event(deployment, 'DEPLOYMENT_CREATED')

            return deployment_id

    async def execute_deployment(
        self,
        deployment_id: str,
        force_recreate: bool = False,
        pull_images: bool = False
    ) -> bool:
        """
        Execute a deployment (pull image, create container, start container).

        This is the main deployment workflow with progress tracking.

        Args:
            deployment_id: Composite deployment ID
            force_recreate: Force recreate containers even if unchanged (for redeploy)
            pull_images: Pull latest images before starting (for redeploy/update)

        Returns:
            True if deployment succeeded, False if it failed

        State Flow (7-state machine):
            pending -> validating -> pulling_image -> creating -> starting -> running
                                                                            | (on error)
                                                                         failed -> rolled_back (if rollback enabled)
        """
        with self.db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment:
                raise ValueError(f"Deployment {deployment_id} not found")

            # Transition to validating (first granular state)
            if not self.state_machine.transition(deployment, 'validating'):
                raise ValueError(
                    f"Cannot start deployment {deployment_id} in status {deployment.status}"
                )

            await self._update_progress(session, deployment, 0, 'Validating configuration')
            session.commit()

            try:
                # 30-minute timeout for entire deployment
                async with asyncio.timeout(1800):
                    # Parse definition
                    definition = json.loads(deployment.definition)

                    # Check if this is an agent-based host
                    host_connection_type = self._get_host_connection_type(deployment.host_id)

                    if host_connection_type == 'agent':
                        # Agent hosts use native compose deployment
                        success = await self._execute_agent_deployment(
                            deployment_id=deployment_id,
                            host_id=deployment.host_id,
                            deployment_type=deployment.deployment_type,
                            definition=definition,
                            name=deployment.name,
                            force_recreate=force_recreate,
                            pull_images=pull_images
                        )
                        if not success:
                            raise RuntimeError(
                                "Agent deployment failed - check agent logs for details"
                            )
                        return True

                    # Direct Docker SDK deployment (local or remote hosts)
                    if deployment.deployment_type == 'container':
                        await execute_container_deployment(
                            deployment_id=deployment_id,
                            definition=definition,
                            db=self.db,
                            docker_monitor=self.docker_monitor,
                            state_machine=self.state_machine,
                            transition_and_update=self._transition_and_update,
                            create_deployment_metadata=self._create_deployment_metadata,
                        )
                    elif deployment.deployment_type == 'stack':
                        await execute_stack_deployment(
                            session=session,
                            deployment=deployment,
                            definition=definition,
                            docker_monitor=self.docker_monitor,
                            state_machine=self.state_machine,
                            update_progress=self._update_progress,
                            create_deployment_metadata=self._create_deployment_metadata,
                            force_recreate=force_recreate,
                            pull_images=pull_images,
                        )
                    else:
                        raise ValueError(f"Unknown deployment_type: {deployment.deployment_type}")

                    # Success - transition to running
                    deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                    session.expire(deployment)
                    session.refresh(deployment)
                    self.state_machine.transition(deployment, 'running')
                    await self._update_progress(
                        session, deployment, 100, 'Deployment completed - container running'
                    )
                    session.commit()

                    logger.info(f"Deployment {deployment_id} completed successfully")
                    await self._emit_deployment_event(deployment, 'DEPLOYMENT_COMPLETED')
                    return True

            except asyncio.TimeoutError:
                logger.error(f"Deployment {deployment_id} timed out after 30 minutes")

                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                session.expire(deployment)
                session.refresh(deployment)
                self.state_machine.transition(deployment, 'failed')
                deployment.error_message = "Deployment timed out after 30 minutes"
                session.commit()

                await self._emit_deployment_event(deployment, 'DEPLOYMENT_FAILED')

                if self.state_machine.should_rollback(deployment):
                    logger.info(f"Rolling back deployment {deployment_id} after timeout")
                    await self._rollback_deployment(session, deployment)

                return False

            except Exception as e:
                is_validation_error = (
                    isinstance(e, RuntimeError) and "validation failed" in str(e).lower()
                )

                if is_validation_error:
                    logger.warning(f"Deployment {deployment_id} failed validation")
                else:
                    logger.error(f"Deployment {deployment_id} failed: {e}", exc_info=True)

                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                session.expire(deployment)
                session.refresh(deployment)
                self.state_machine.transition(deployment, 'failed')
                deployment.error_message = str(e)
                session.commit()

                await self._emit_deployment_event(deployment, 'DEPLOYMENT_FAILED')

                if self.state_machine.should_rollback(deployment):
                    logger.info(f"Rolling back deployment {deployment_id}")
                    await self._rollback_deployment(session, deployment)

                return False

    def _get_host_connection_type(self, host_id: str) -> str:
        """
        Get the connection type for a host.

        Args:
            host_id: Docker host UUID

        Returns:
            Connection type: 'local', 'remote', or 'agent'
        """
        with self.db.get_session() as session:
            host = session.query(DockerHostDB).filter_by(id=host_id).first()
            if not host:
                raise ValueError(f"Host {host_id} not found")
            return host.connection_type

    async def _execute_agent_deployment(
        self,
        deployment_id: str,
        host_id: str,
        deployment_type: str,
        definition: Dict[str, Any],
        name: str,
        force_recreate: bool = False,
        pull_images: bool = False
    ) -> bool:
        """
        Execute deployment via agent using native Docker Compose.

        For agent-based hosts, we send the compose YAML to the agent which
        runs `docker compose up` natively.

        Args:
            deployment_id: Deployment composite ID
            host_id: Docker host UUID
            deployment_type: 'container' or 'stack'
            definition: Deployment definition dict
            name: Deployment name (used as compose project name)
            force_recreate: Force recreate containers even if unchanged
            pull_images: Pull latest images before starting

        Returns:
            True if deployment command was sent successfully
        """
        from .agent_executor import (
            get_agent_deployment_executor,
            container_params_to_compose,
            validate_compose_for_agent
        )

        executor = get_agent_deployment_executor(self.docker_monitor)

        # Convert definition to compose YAML based on deployment type
        if deployment_type == 'container':
            compose_content = container_params_to_compose(definition)
            logger.info(
                f"Converted container deployment {deployment_id} to compose format for agent"
            )
        elif deployment_type == 'stack':
            compose_content = definition.get('compose_yaml')
            if not compose_content:
                logger.error(f"Stack deployment {deployment_id} missing compose_yaml")
                return False
        else:
            logger.error(f"Unknown deployment_type: {deployment_type}")
            return False

        # Validate compose content before sending to agent
        is_valid, error = validate_compose_for_agent(compose_content)
        if not is_valid:
            logger.error(
                f"Compose validation failed for deployment {deployment_id}: {error}"
            )
            with self.db.get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment:
                    deployment.status = 'failed'
                    deployment.error_message = error
                    session.commit()
            return False

        # Get environment variables from definition
        environment = definition.get('variables', {})

        logger.info(
            f"Sending deployment {deployment_id} to agent for native compose execution"
        )
        return await executor.deploy(
            host_id=host_id,
            deployment_id=deployment_id,
            compose_content=compose_content,
            project_name=name,
            environment=environment,
            force_recreate=force_recreate,
            pull_images=pull_images
        )

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
        connector = get_host_connector(deployment.host_id, self.docker_monitor)

        for link in containers:
            try:
                await connector.stop_container(link.container_id, timeout=10)
                await connector.remove_container(link.container_id, force=True)
                logger.info(
                    f"Rolled back container {link.container_id} for deployment {deployment.id}"
                )
            except Exception as e:
                logger.error(f"Failed to rollback container {link.container_id}: {e}")

        # Mark as rolled back
        self.state_machine.transition(deployment, 'rolled_back')
        session.commit()

        await self._emit_deployment_event(deployment, 'DEPLOYMENT_ROLLED_BACK')

    async def _transition_and_update(
        self,
        deployment_id: str,
        new_state: Optional[str],
        progress_percent: int,
        stage: str
    ) -> None:
        """
        Helper for Issue #4 fix: Update deployment state/progress with short-lived session.

        Opens session, updates deployment, commits, and closes session immediately.
        Use this instead of holding session across async operations.

        Args:
            deployment_id: Deployment composite key
            new_state: New state to transition to (or None to skip state change)
            progress_percent: Progress percentage (0-100)
            stage: Progress stage description
        """
        with self.db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment:
                logger.error(f"Deployment {deployment_id} not found for state update")
                return

            # Transition state if requested
            if new_state:
                if not self.state_machine.transition(deployment, new_state):
                    logger.warning(
                        f"Invalid state transition for {deployment_id}: "
                        f"{deployment.status} -> {new_state}"
                    )

            # Update progress
            deployment.progress_percent = progress_percent
            deployment.current_stage = stage
            deployment.updated_at = datetime.now(timezone.utc)

            session.commit()

            logger.debug(f"Deployment {deployment_id}: {progress_percent}% - {stage}")

            # Emit progress event
            await self._emit_deployment_event(deployment, 'DEPLOYMENT_PROGRESS')

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

        Event structure follows spec Section 6.2:
        - Nested 'progress' object with overall_percent and stage
        - Optional 'error' field for failures
        - Timestamps with 'Z' suffix for UTC

        Args:
            deployment: Deployment instance
            event_type: Event type (DEPLOYMENT_CREATED, DEPLOYMENT_PROGRESS, etc.)
        """
        # Build nested progress object
        progress = {
            'overall_percent': deployment.progress_percent,
            'stage': deployment.current_stage,
        }

        # Base payload structure
        payload = {
            'type': event_type.lower(),
            'deployment_id': deployment.id,
            'host_id': deployment.host_id,
            'name': deployment.name,
            'status': deployment.status,
            'progress': progress,
            'created_at': deployment.created_at.isoformat() + 'Z' if deployment.created_at else None,
            'completed_at': deployment.completed_at.isoformat() + 'Z' if deployment.completed_at else None,
        }

        # Add error field only if present
        if deployment.error_message:
            payload['error'] = deployment.error_message

        # Broadcast via ConnectionManager
        try:
            if self.docker_monitor and hasattr(self.docker_monitor, 'manager'):
                logger.info(f"[BROADCAST] {event_type}: {deployment.id} - {progress['overall_percent']}% {progress['stage']}")
                await self.docker_monitor.manager.broadcast(payload)
            else:
                logger.warning(f"[BROADCAST] No manager available for {event_type}")
        except Exception as e:
            logger.error(f"Error broadcasting deployment event: {e}")

    def _create_deployment_metadata(
        self,
        session: Session,
        deployment_id: str,
        host_id: str,
        container_short_id: str,
        service_name: Optional[str] = None
    ) -> DeploymentMetadata:
        """
        Create deployment_metadata record for a deployed container.

        Links container to deployment using composite key format.
        Metadata persists even if deployment record is deleted (SET NULL).

        Args:
            session: Database session
            deployment_id: Deployment composite key {host_id}:{deployment_id}
            host_id: FULL host UUID
            container_short_id: Container SHORT ID (12 chars, NOT 64 chars)
            service_name: Service name (for stack deployments), None for single containers

        Returns:
            DeploymentMetadata: Created metadata record

        Raises:
            ValueError: If container_short_id is not 12 characters (SHORT ID)
        """
        # Validate container ID is SHORT format (12 chars)
        if len(container_short_id) != 12:
            raise ValueError(
                f"container_short_id must be SHORT ID (12 chars), got {len(container_short_id)} chars"
            )

        # Composite key format: {host_id}:{container_short_id}
        container_composite_key = f"{host_id}:{container_short_id}"

        # Create metadata record
        metadata = DeploymentMetadata(
            container_id=container_composite_key,
            host_id=host_id,
            deployment_id=deployment_id,
            is_managed=True,
            service_name=service_name,
        )

        session.add(metadata)
        logger.info(
            f"Created deployment_metadata: container={container_composite_key}, "
            f"deployment={deployment_id}, service={service_name or 'N/A'}"
        )

        return metadata


class SecurityException(Exception):
    """Raised when security validation blocks deployment."""
    pass
