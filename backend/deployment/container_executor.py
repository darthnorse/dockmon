"""
Single container deployment executor.

Handles the deployment workflow for individual containers:
pull image -> validate resources -> create container -> start -> health check.

Extracted from executor.py for maintainability.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, Optional

from database import (
    Deployment,
    DeploymentContainer,
    DeploymentMetadata,
    GlobalSettings,
    DatabaseManager,
)
from .host_connector import get_host_connector
from .build_args import build_container_create_args

logger = logging.getLogger(__name__)


def is_named_volume(path: str) -> bool:
    """
    Check if volume is a named volume (not a bind mount).

    Named volumes: 'my_volume', 'db_data'
    Bind mounts: '/host/path', './relative/path', '../parent/path'
    """
    return not (path.startswith('/') or path.startswith('.'))


async def execute_container_deployment(
    deployment_id: str,
    definition: Dict[str, Any],
    db: DatabaseManager,
    docker_monitor,
    state_machine,
    transition_and_update: Callable[..., Coroutine],
    create_deployment_metadata: Callable,
) -> None:
    """
    Execute single container deployment with granular state transitions.

    State flow: validating -> pulling_image -> creating -> starting -> running

    ISSUE #4 FIX: Database sessions are opened only for updates, then closed
    before long-running async operations (image pull, health checks).
    This prevents connection pool exhaustion during concurrent deployments.

    Args:
        deployment_id: Composite deployment ID
        definition: Container configuration dict
        db: DatabaseManager instance
        docker_monitor: DockerMonitor instance
        state_machine: DeploymentStateMachine instance
        transition_and_update: Async callback to update state/progress
        create_deployment_metadata: Callback to create metadata records

    Raises:
        ValueError: If deployment not found or image missing
        RuntimeError: If container fails to start or health check fails
    """
    # Extract data needed for deployment (no session held)
    with db.get_session() as session:
        deployment = session.query(Deployment).filter_by(id=deployment_id).first()
        if not deployment:
            raise ValueError(f"Deployment {deployment_id} not found")
        host_id = deployment.host_id
        # session auto-closes here

    # Get HostConnector abstraction
    connector = get_host_connector(host_id, docker_monitor)

    # STATE: pulling_image
    await transition_and_update(deployment_id, 'pulling_image', 10, 'Starting image pull')

    image = definition.get('image')
    if not image:
        raise ValueError("Container definition missing 'image' field")

    await transition_and_update(deployment_id, None, 10, f'Pulling image {image}')

    # Pull image via connector with layer-by-layer progress tracking
    # ISSUE #4 FIX: No session held during image pull (can take 30+ seconds)
    await connector.pull_image(image, deployment_id=deployment_id)
    logger.info(f"Pulled image {image} for deployment {deployment_id}")

    # Stage 2: Prepare resources (50%)
    await transition_and_update(deployment_id, None, 50, 'Preparing resources')

    # Validate networks exist, fallback to 'bridge' if missing
    await _validate_networks(connector, definition, host_id)

    # Ensure named volumes exist (auto-create if needed)
    await _ensure_volumes(connector, definition)

    # STATE: creating
    await transition_and_update(deployment_id, 'creating', 55, 'Creating container')

    # Clean up any existing containers from previous deployment attempts
    # This handles redeploy from running, retry from failed/rolled_back
    with db.get_session() as session:
        existing_links = session.query(DeploymentContainer).filter_by(
            deployment_id=deployment_id
        ).all()

        if existing_links:
            logger.info(f"Cleaning up {len(existing_links)} existing container(s) for deployment {deployment_id}")
            for link in existing_links:
                try:
                    await connector.stop_container(link.container_id, timeout=10)
                    await connector.remove_container(link.container_id, force=True)
                    logger.info(f"Removed existing container {link.container_id}")
                except Exception as e:
                    logger.warning(f"Failed to remove existing container {link.container_id}: {e}")

            # Clear old records
            session.query(DeploymentContainer).filter_by(deployment_id=deployment_id).delete()
            session.query(DeploymentMetadata).filter_by(deployment_id=deployment_id).delete()
            session.commit()

    # Also try to remove any orphaned container with the same name
    # This handles cases where deployment failed after Docker created the container
    # but before DeploymentContainer link was created
    container_name = definition.get('name')
    if container_name:
        try:
            await connector.stop_container(container_name, timeout=10)
            await connector.remove_container(container_name, force=True)
            logger.info(f"Removed orphaned container by name: {container_name}")
        except Exception:
            # Container doesn't exist or already removed - that's fine
            pass

    # Build container create args
    create_args = build_container_create_args(definition)

    # Extract labels from create_args (if any)
    user_labels = create_args.pop('labels', {})

    # Merge with deployment tracking labels
    labels = {
        **user_labels,
        "dockmon.deployed_by": "deployment",
        "dockmon.deployment_id": deployment_id
    }

    # Create container via connector (returns SHORT ID - 12 chars)
    container_id = await connector.create_container(create_args, labels)
    logger.info(f"Created container {container_id} for deployment {deployment_id}")

    # CRITICAL: All three operations must be in ONE transaction
    # ISSUE #4 FIX: Open session only for this atomic commit
    with db.get_session() as session:
        deployment = session.query(Deployment).filter_by(id=deployment_id).first()
        if not deployment:
            raise ValueError(f"Deployment {deployment_id} not found for commitment")

        # COMMITMENT POINT - container created in Docker
        state_machine.mark_committed(deployment)

        # Link deployment to container
        link = DeploymentContainer(
            deployment_id=deployment_id,
            container_id=container_id,
            service_name=None,  # NULL for single containers
            created_at=datetime.now(timezone.utc)
        )
        session.add(link)

        # Create deployment metadata
        create_deployment_metadata(
            session=session,
            deployment_id=deployment_id,
            host_id=host_id,
            container_short_id=container_id,
            service_name=None
        )

        session.commit()

    # STATE: starting
    await transition_and_update(deployment_id, 'starting', 70, 'Starting container')

    await connector.start_container(container_id)
    logger.info(f"Started container {container_id} for deployment {deployment_id}")

    await transition_and_update(deployment_id, None, 90, 'Verifying container is running')

    # Get container status
    status_str = await connector.get_container_status(container_id)
    is_running = status_str == 'running'

    if not is_running:
        logger.error(f"Container {container_id} failed to start (status: {status_str})")
        # Cleanup: remove failed container
        try:
            await connector.remove_container(container_id, force=True)
            logger.info(f"Removed failed container {container_id}")
        except Exception as e:
            logger.error(f"Error removing failed container: {e}")
        raise RuntimeError(f"Container {container_id} not running (status: {status_str})")

    logger.info(f"Container {container_id} verified running")

    # Stage 4: Wait for health check (90-100%)
    health_check_timeout = 60  # Default
    with db.get_session() as session:
        settings = session.query(GlobalSettings).first()
        if settings:
            health_check_timeout = settings.health_check_timeout_seconds

    await transition_and_update(deployment_id, None, 95, 'Waiting for health check')

    logger.info(f"Waiting for health check (timeout: {health_check_timeout}s)")
    is_healthy = await connector.verify_container_running(
        container_id,
        max_wait_seconds=health_check_timeout
    )

    if not is_healthy:
        logger.error(f"Health check failed for deployment {deployment_id}")
        # Cleanup: stop and remove failed container
        try:
            await connector.stop_container(container_id, timeout=10)
            await connector.remove_container(container_id, force=True)
        except Exception as e:
            logger.error(f"Error cleaning up failed container: {e}")

        # Mark deployment as failed
        with db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if deployment:
                deployment.progress_percent = 100
                deployment.current_stage = 'Health check failed'
                state_machine.transition(deployment, 'failed')
                deployment.error_message = f"Container health check failed after {health_check_timeout}s"
                session.commit()

        raise RuntimeError(f"Deployment failed: health check timeout after {health_check_timeout}s")

    # Health check passed
    logger.info(f"Container {container_id} is healthy")
    await transition_and_update(deployment_id, None, 100, 'Deployment completed')


async def _validate_networks(connector, definition: Dict[str, Any], host_id: str) -> None:
    """
    Validate networks exist, fallback to 'bridge' if missing.

    Spec Section 9.5: Pre-deployment validation warns user, falls back to 'bridge'.
    """
    if 'networks' not in definition or not definition['networks']:
        return

    networks = definition['networks']
    if not isinstance(networks, list):
        return

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
            logger.warning(
                f"Network '{network_name}' not found on host {host_id}, "
                f"using 'bridge' instead. Create the network manually if needed."
            )
            validated_networks.append('bridge')

    # Update definition with validated networks
    definition['networks'] = validated_networks


async def _ensure_volumes(connector, definition: Dict[str, Any]) -> None:
    """
    Ensure named volumes exist (auto-create if needed).

    Only creates named volumes, not bind mounts.
    """
    if 'volumes' not in definition or not definition['volumes']:
        return

    volumes = definition['volumes']
    if not isinstance(volumes, list):
        return

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
        if source and is_named_volume(source):
            logger.info(f"Ensuring volume '{source}' exists")
            # Check if volume exists
            existing_volumes = await connector.list_volumes()
            if not any(v.get('name') == source for v in existing_volumes):
                await connector.create_volume(source)
