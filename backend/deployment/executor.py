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

from database import Deployment, DeploymentContainer, DeploymentMetadata, DatabaseManager, GlobalSettings
from .state_machine import DeploymentStateMachine
from .security_validator import SecurityValidator, SecurityLevel
from .host_connector import get_host_connector
from .compose_parser import ComposeParser, ComposeParseError
from .compose_validator import ComposeValidator
from .stack_orchestrator import StackOrchestrator, StackOrchestrationError
from utils.async_docker import async_docker_call
from utils.container_health import wait_for_container_health
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

            # Validate definition structure matches deployment type
            if deployment_type == 'container':
                # Container deployments require 'image' at root level
                if 'image' not in definition:
                    raise ValueError(
                        "Container deployments require an 'image' field at root level. "
                        "Example: {\"image\": \"nginx:alpine\", \"ports\": [\"80:80\"]}"
                    )
                # Prevent using Compose YAML in container deployments
                if 'compose_yaml' in definition or 'services' in definition:
                    raise ValueError(
                        "Container deployments cannot use 'compose_yaml' or 'services'. "
                        "Use deployment_type='stack' for Docker Compose multi-service deployments."
                    )

            elif deployment_type == 'stack':
                # Stack deployments require 'compose_yaml' field
                if 'compose_yaml' not in definition:
                    raise ValueError(
                        "Stack deployments require a 'compose_yaml' field with Docker Compose YAML. "
                        "Example: {\"compose_yaml\": \"services:\\n  nginx:\\n    image: nginx:alpine\"}"
                    )
                # Prevent using single-container fields in stack deployments
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

    async def execute_deployment(self, deployment_id: str) -> bool:
        """
        Execute a deployment (pull image, create container, start container).

        This is the main deployment workflow with progress tracking.

        Args:
            deployment_id: Composite deployment ID

        Returns:
            True if deployment succeeded, False if it failed

        State Flow (7-state machine):
            pending → validating → pulling_image → creating → starting → running
                                                                            ↓ (on error)
                                                                         failed → rolled_back (if rollback enabled)

        State Transitions:
            - validating: Config validation and security checks
            - pulling_image: Docker image pull with layer-by-layer progress
            - creating: Container creation with resource allocation
            - starting: Container startup
            - running: Container running successfully (terminal state)
            - failed → rolled_back: Cleanup on failure (if rollback enabled)

        Commitment Point:
            Once container is created in Docker, deployment.committed=True.
            After this point, rollback will NOT destroy the container.
        """
        with self.db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment:
                raise ValueError(f"Deployment {deployment_id} not found")

            # Transition to validating (first granular state)
            if not self.state_machine.transition(deployment, 'validating'):
                raise ValueError(f"Cannot start deployment {deployment_id} in status {deployment.status}")

            await self._update_progress(session, deployment, 0, 'Validating configuration')
            session.commit()

            try:
                # Parse definition
                definition = json.loads(deployment.definition)

                if deployment.deployment_type == 'container':
                    container_config = definition.get('container', {})
                    await self._execute_container_deployment(session, deployment, container_config)
                elif deployment.deployment_type == 'stack':
                    await self._execute_stack_deployment(session, deployment, definition)
                else:
                    raise ValueError(f"Unknown deployment_type: {deployment.deployment_type}")

                # Success - transition to running (terminal state)
                self.state_machine.transition(deployment, 'running')
                await self._update_progress(session, deployment, 100, 'Deployment completed - container running')
                session.commit()

                logger.info(f"Deployment {deployment_id} completed successfully - container running")
                await self._emit_deployment_event(deployment, 'DEPLOYMENT_COMPLETED')
                return True

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

                return False

    async def _execute_container_deployment(
        self,
        session: Session,
        deployment: Deployment,
        definition: Dict[str, Any]
    ) -> None:
        """
        Execute single container deployment with granular state transitions.

        State flow: validating → pulling_image → creating → starting → running
        """
        host_id = deployment.host_id

        # Get HostConnector abstraction (v2.1: DirectDockerConnector, v2.2: AgentRPCConnector)
        connector = get_host_connector(host_id, self.docker_monitor)

        # STATE: pulling_image
        # Transition to pulling_image before image pull (10-50%)
        self.state_machine.transition(deployment, 'pulling_image')
        session.commit()

        image = definition.get('image')
        if not image:
            raise ValueError("Container definition missing 'image' field")

        await self._update_progress(session, deployment, 10, f'Pulling image {image}')
        session.commit()

        # Pull image via connector with layer-by-layer progress tracking
        # Passing deployment.id enables real-time WebSocket progress events
        await connector.pull_image(image, deployment_id=deployment.id)
        logger.info(f"Pulled image {image} for deployment {deployment.id}")

        # Stage 2: Create container (50-70%)
        await self._update_progress(session, deployment, 50, 'Preparing resources')
        session.commit()

        # Validate networks exist, fallback to 'bridge' if missing
        # Spec Section 9.5: Pre-deployment validation warns user, falls back to 'bridge'
        if 'networks' in definition and definition['networks']:
            networks = definition['networks']
            if isinstance(networks, list):
                # Get existing networks from Docker
                existing_networks = await connector.list_networks()
                existing_network_names = {net.get('name') for net in existing_networks}

                # Validate each requested network
                validated_networks = []
                for network_name in networks:
                    if network_name in existing_network_names:
                        validated_networks.append(network_name)
                        logger.debug(f"Network '{network_name}' exists")
                    else:
                        # Spec Section 9.5: Fallback to 'bridge', log warning
                        logger.warning(
                            f"Network '{network_name}' not found on host {deployment.host_id}, "
                            f"using 'bridge' instead. Create the network manually if needed."
                        )
                        validated_networks.append('bridge')

                # Update definition with validated networks
                definition['networks'] = validated_networks

        # Ensure named volumes exist (auto-create if needed)
        if 'volumes' in definition and definition['volumes']:
            volumes = definition['volumes']
            if isinstance(volumes, list):
                for vol in volumes:
                    # Handle dict format: {'source': 'vol_name', 'target': '/path', 'mode': 'rw'}
                    if isinstance(vol, dict):
                        source = vol.get('source', '')
                    # Handle string format: 'vol_name:/path:rw'
                    elif isinstance(vol, str):
                        source = vol.split(':')[0]
                    else:
                        continue

                    # Only auto-create named volumes (not bind mounts)
                    if source and self._is_named_volume(source):
                        logger.info(f"Ensuring volume '{source}' exists")
                        # Check if volume exists
                        existing_volumes = await connector.list_volumes()
                        if not any(vol.get('name') == source for vol in existing_volumes):
                            await connector.create_volume(source)

        # STATE: creating
        # Transition to creating before container creation (50-70%)
        self.state_machine.transition(deployment, 'creating')
        await self._update_progress(session, deployment, 55, 'Creating container')
        session.commit()

        # Build container create args
        create_args = self._build_container_create_args(definition)

        # Extract labels from create_args (if any)
        user_labels = create_args.pop('labels', {})

        # Merge with deployment tracking labels
        labels = {
            **user_labels,
            "dockmon.deployed_by": "deployment",
            "dockmon.deployment_id": deployment.id
        }

        # Create container via connector (returns SHORT ID - 12 chars)
        container_id = await connector.create_container(create_args, labels)

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

        # Create deployment metadata (v2.1.1 - Phase 1.3)
        # Tracks deployment ownership for containers
        self._create_deployment_metadata(
            session=session,
            deployment_id=deployment.id,
            host_id=deployment.host_id,
            container_short_id=container_id,  # Already SHORT ID (12 chars)
            service_name=None  # Single container (not stack)
        )

        session.commit()

        # STATE: starting
        # Transition to starting before starting container (70-100%)
        self.state_machine.transition(deployment, 'starting')
        await self._update_progress(session, deployment, 70, 'Starting container')
        session.commit()

        await connector.start_container(container_id)
        logger.info(f"Started container {container_id} for deployment {deployment.id}")

        await self._update_progress(session, deployment, 90, 'Verifying container is running')
        session.commit()

        # Get container status
        status = await connector.get_container_status(container_id)
        is_running = status.get('State', {}).get('Running', False)

        if not is_running:
            container_state = status.get('State', {}).get('Status', 'unknown')
            logger.error(f"Container {container_id} crashed during startup (status: {container_state})")
            # Cleanup: remove crashed container
            try:
                await connector.remove_container(container_id, force=True)
                logger.info(f"Removed crashed container {container_id}")
            except Exception as e:
                logger.error(f"Error removing crashed container: {e}")
            raise RuntimeError(f"Container {container_id} not running (status: {container_state})")

        logger.info(f"Container {container_id} verified running")

        # Stage 4: Wait for health check (90-100%)
        # Get configured timeout from settings
        health_check_timeout = 60  # Default
        settings = session.query(GlobalSettings).first()
        if settings:
            health_check_timeout = settings.health_check_timeout_seconds

        await self._update_progress(session, deployment, 95, 'Waiting for health check')
        session.commit()

        logger.info(f"Waiting for health check (timeout: {health_check_timeout}s)")
        is_healthy = await connector.verify_container_running(
            container_id,
            max_wait_seconds=health_check_timeout
        )

        if not is_healthy:
            logger.error(f"Health check failed for deployment {deployment.id}")
            # Cleanup: stop and remove failed container
            try:
                await connector.stop_container(container_id, timeout=10)
                await connector.remove_container(container_id, force=True)
            except Exception as e:
                logger.error(f"Error cleaning up failed container: {e}")

            # Mark deployment as failed
            await self._update_progress(session, deployment, deployment.progress_percent, 'Health check failed')
            deployment.status = 'failed'
            deployment.error_message = f"Container health check failed after {health_check_timeout}s"
            session.commit()

            raise RuntimeError(f"Deployment failed: health check timeout after {health_check_timeout}s")

        # Health check passed
        logger.info(f"Container {container_id} is healthy")
        await self._update_progress(session, deployment, 100, 'Deployment completed')
        # Note: state transition to 'running' (terminal state) happens in execute_deployment() after this returns
        session.commit()

    async def _execute_stack_deployment(
        self,
        session: Session,
        deployment: Deployment,
        definition: Dict[str, Any]
    ) -> None:
        """
        Execute Docker Compose stack deployment.

        Deploys multi-service stacks from Docker Compose files.
        Creates networks, volumes, and services in correct dependency order.
        """
        logger.info(f"Starting stack deployment {deployment.id}")

        # Extract compose YAML and variables
        compose_yaml = definition.get('compose_yaml')
        variables = definition.get('variables', {})

        if not compose_yaml:
            raise RuntimeError("Stack deployment requires 'compose_yaml' in definition")

        # Parse and validate compose file
        parser = ComposeParser()
        validator = ComposeValidator()
        orchestrator = StackOrchestrator()

        try:
            # Step 1: Validate YAML safety
            await self._update_progress(session, deployment, 5, 'Validating compose file')
            validator.validate_yaml_safety(compose_yaml)

            # Step 2: Parse compose file with variable substitution
            await self._update_progress(session, deployment, 10, 'Parsing compose file')
            compose_data = parser.parse(compose_yaml, variables=variables)

            # Step 3: Validate compose structure and dependencies
            await self._update_progress(session, deployment, 15, 'Validating dependencies')
            validator.validate_required_fields(compose_data)
            validator.validate_service_configuration(compose_data)
            validator.validate_dependencies(compose_data)

        except (ComposeParseError, StackOrchestrationError) as e:
            raise RuntimeError(f"Compose validation failed: {e}")

        # Get host connector
        connector = get_host_connector(deployment.host_id, self.docker_monitor)

        # Track created resources for rollback
        created_networks = []
        created_volumes = []
        created_services = []
        container_ids = {}  # service_name -> container_short_id

        try:
            # Step 4: Create networks
            if 'networks' in compose_data:
                await self._update_progress(session, deployment, 20, 'Creating networks')

                for network_name, network_config in compose_data['networks'].items():
                    # Skip external networks
                    if network_config and network_config.get('external'):
                        logger.info(f"Skipping external network: {network_name}")
                        continue

                    logger.info(f"Creating network: {network_name}")
                    # Note: Network creation implementation depends on connector
                    # For now, we'll let Docker handle networks via service creation
                    created_networks.append(network_name)

            # Step 5: Create volumes
            if 'volumes' in compose_data:
                await self._update_progress(session, deployment, 25, 'Creating volumes')

                for volume_name, volume_config in compose_data['volumes'].items():
                    if volume_name.startswith('/'):
                        continue  # Skip bind mounts

                    logger.info(f"Creating volume: {volume_name}")
                    await connector.create_volume(volume_name)
                    created_volumes.append(volume_name)

            # Step 6: Deploy services in dependency order
            service_groups = orchestrator.get_service_groups(compose_data)
            services = compose_data.get('services', {})
            total_services = len(services)
            completed_services = 0

            for group_idx, service_group in enumerate(service_groups):
                for service_name in service_group:
                    service_config = services[service_name]

                    logger.info(f"Deploying service: {service_name} ({completed_services + 1}/{total_services})")

                    # Map compose config to Docker container config
                    try:
                        container_config = orchestrator.map_service_to_container_config(
                            service_name,
                            service_config
                        )
                    except StackOrchestrationError as e:
                        raise RuntimeError(f"Service '{service_name}' configuration error: {e}")

                    # Pull image
                    progress_base = 30 + (completed_services * 60 // total_services)
                    await self._update_progress(
                        session, deployment,
                        progress_base,
                        f'Pulling image for {service_name}'
                    )

                    image = container_config['image']

                    try:
                        # Pass deployment_id to enable layer-by-layer progress tracking via WebSocket
                        await connector.pull_image(image, deployment_id=deployment.id)
                    except Exception as e:
                        raise RuntimeError(f"Failed to pull image {image} for service {service_name}: {e}")

                    # Create container
                    await self._update_progress(
                        session, deployment,
                        progress_base + 10,
                        f'Creating {service_name}'
                    )

                    # Add stack labels
                    labels = container_config.get('labels', {})
                    labels.update({
                        'com.docker.compose.project': deployment.name,
                        'com.docker.compose.service': service_name,
                        'dockmon.deployment_id': deployment.id,
                        'dockmon.managed': 'true'
                    })
                    container_config['labels'] = labels

                    # Set container name
                    # For single-service stacks, use just the service name to avoid duplication (e.g., "radarr" instead of "Radarr_radarr")
                    # For multi-service stacks, use Docker Compose format: {project}_{service}
                    if total_services == 1:
                        container_config['name'] = service_name
                    else:
                        container_config['name'] = f"{deployment.name}_{service_name}"

                    try:
                        # Create container using connector
                        container_short_id = await connector.create_container(
                            container_config,
                            labels
                        )
                        container_ids[service_name] = container_short_id
                        created_services.append(service_name)

                        logger.info(f"Created container for {service_name}: {container_short_id}")

                    except Exception as e:
                        raise RuntimeError(f"Failed to create container for {service_name}: {e}")

                    # Start container
                    await self._update_progress(
                        session, deployment,
                        progress_base + 15,
                        f'Starting {service_name}'
                    )

                    try:
                        await connector.start_container(container_short_id)
                        logger.info(f"Started service: {service_name}")
                    except Exception as e:
                        raise RuntimeError(f"Failed to start service {service_name}: {e}")

                    # Create deployment metadata
                    self._create_deployment_metadata(
                        session,
                        deployment.id,
                        deployment.host_id,
                        container_short_id,
                        service_name=service_name
                    )

                    completed_services += 1

            # Step 7: Deployment complete
            # Transition through required states so execute_deployment() can transition to 'running'
            # State machine requires: validating → pulling_image → creating → starting → running
            self.state_machine.transition(deployment, 'pulling_image')
            self.state_machine.transition(deployment, 'creating')
            self.state_machine.transition(deployment, 'starting')
            await self._update_progress(session, deployment, 100, 'Stack deployment completed')
            deployment.committed = True
            session.commit()

            logger.info(f"Stack deployment {deployment.id} completed successfully - {len(created_services)} services created")

        except Exception as e:
            logger.error(f"Stack deployment {deployment.id} failed: {e}")

            # Rollback if not committed
            if not deployment.committed:
                logger.warning(f"Rolling back stack deployment {deployment.id}")

                # Remove created services
                for service_name in reversed(created_services):
                    if service_name in container_ids:
                        try:
                            container_id = container_ids[service_name]
                            await connector.stop_container(container_id, timeout=10)
                            await connector.remove_container(container_id, force=True)
                            logger.info(f"Rolled back service: {service_name}")
                        except Exception as rollback_error:
                            logger.error(f"Failed to rollback service {service_name}: {rollback_error}")

            raise

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
        connector = get_host_connector(deployment.host_id, self.docker_monitor)

        for link in containers:
            try:
                # Try to stop first, then remove
                await connector.stop_container(link.container_id, timeout=10)
                await connector.remove_container(link.container_id, force=True)
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

        Event structure follows spec Section 6.2 (lines 1116-1145):
        - Nested 'progress' object with overall_percent, stage, stage_percent
        - Optional 'error' field for failures
        - Timestamps with 'Z' suffix for UTC

        Args:
            deployment: Deployment instance
            event_type: Event type (DEPLOYMENT_CREATED, DEPLOYMENT_PROGRESS, etc.)
        """
        # Build nested progress object (spec-compliant)
        progress = {
            'overall_percent': deployment.progress_percent,
            'stage': deployment.current_stage,
            'stage_percent': deployment.stage_percent  # Stage-level progress (0-100)
        }

        # Base payload structure
        payload = {
            'type': event_type.lower(),
            'deployment_id': deployment.id,
            'host_id': deployment.host_id,
            'name': deployment.name,
            'status': deployment.status,
            'progress': progress,  # NESTED OBJECT (spec requirement)
            'created_at': deployment.created_at.isoformat() + 'Z' if deployment.created_at else None,
            'completed_at': deployment.completed_at.isoformat() + 'Z' if deployment.completed_at else None,
        }

        # Add error field only if present (don't send null)
        if deployment.error_message:
            payload['error'] = deployment.error_message

        # Broadcast via ConnectionManager
        try:
            if self.docker_monitor and hasattr(self.docker_monitor, 'manager'):
                await self.docker_monitor.manager.broadcast(payload)
        except Exception as e:
            logger.error(f"Error broadcasting deployment event: {e}")

    # ========== Deployment Metadata Helpers ==========

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
            is_managed=True,  # Created by deployment system
            service_name=service_name,  # None for single containers, populated for stacks
        )

        session.add(metadata)
        logger.info(
            f"Created deployment_metadata: container={container_composite_key}, "
            f"deployment={deployment_id}, service={service_name or 'N/A'}"
        )

        return metadata

    # ========== Network and Volume Helpers ==========

    # Network and volume helper methods removed - volumes are now created directly via connector.create_volume()
    # Networks fallback to 'bridge' network if requested network doesn't exist (per spec Section 9.5)


class SecurityException(Exception):
    """Raised when security validation blocks deployment."""
    pass
