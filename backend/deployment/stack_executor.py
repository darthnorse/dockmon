"""
Docker Compose stack deployment executor.

Handles multi-service stack deployments from Docker Compose files.
Uses Go Compose Service for full compatibility when available,
with fallback to Python implementation.

Deployment paths:
- Go Compose Service (preferred): Full Docker Compose SDK compatibility
- Python fallback: Manual reimplementation for when Go service is unavailable
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from database import DatabaseManager, Deployment, DockerHostDB
from .host_connector import get_host_connector
from .compose_parser import ComposeParser, ComposeParseError
from .compose_validator import ComposeValidator, ComposeValidationError
from .stack_orchestrator import StackOrchestrator, StackOrchestrationError
from .network_helpers import parse_ipam_config, reconcile_existing_network
from .compose_client import (
    ComposeClient,
    DeployResult,
    ProgressEvent,
    ComposeServiceError,
    ComposeServiceUnavailable,
    is_compose_service_available,
)

logger = logging.getLogger(__name__)

# Cache compose service availability to avoid repeated checks
_compose_service_checked = False
_compose_service_available = False


def _check_compose_service_available() -> bool:
    """
    Check if Go compose service is available.

    Caches the result to avoid repeated checks during a single deployment.
    """
    global _compose_service_checked, _compose_service_available

    if not _compose_service_checked:
        _compose_service_available = is_compose_service_available()
        _compose_service_checked = True
        if _compose_service_available:
            logger.info("Go compose service available - using for stack deployments")
        else:
            logger.info("Go compose service unavailable - using Python fallback")

    return _compose_service_available


def reset_compose_service_check() -> None:
    """Reset compose service availability check (for testing or after service restart)."""
    global _compose_service_checked, _compose_service_available
    _compose_service_checked = False
    _compose_service_available = False


async def execute_stack_deployment(
    session: Session,
    deployment: Deployment,
    definition: Dict[str, Any],
    docker_monitor,
    state_machine,
    update_progress: Callable,
    create_deployment_metadata: Callable,
) -> None:
    """
    Execute Docker Compose stack deployment.

    Uses Go Compose Service when available for full Docker Compose SDK compatibility.
    Falls back to Python implementation if Go service is unavailable.

    Args:
        session: Database session
        deployment: Deployment instance
        definition: Stack definition with compose_yaml and variables
        docker_monitor: DockerMonitor instance
        state_machine: DeploymentStateMachine instance
        update_progress: Async callback to update progress
        create_deployment_metadata: Callback to create metadata records

    Raises:
        RuntimeError: If validation, parsing, or deployment fails
    """
    logger.info(f"Starting stack deployment {deployment.id}")

    # Extract compose YAML and variables
    compose_yaml = definition.get('compose_yaml')
    variables = definition.get('variables', {})

    if not compose_yaml:
        raise RuntimeError("Stack deployment requires 'compose_yaml' in definition")

    # Step 1: Validate YAML safety (always done in Python for security)
    parser = ComposeParser()
    validator = ComposeValidator()

    try:
        await update_progress(session, deployment, 5, 'Validating compose file')
        validator.validate_yaml_safety(compose_yaml)

        # Step 2: Apply variable substitution (Python handles templates)
        await update_progress(session, deployment, 10, 'Processing compose file')
        if variables:
            compose_yaml = parser.substitute_variables(compose_yaml, variables)

    except (ComposeParseError, ComposeValidationError) as e:
        logger.warning(f"Compose validation failed for deployment {deployment.id}: {e}")
        raise RuntimeError(f"Compose validation failed: {e}")

    # Check if Go compose service is available
    if _check_compose_service_available():
        # Use Go compose service (full Docker Compose SDK)
        await _execute_via_go_service(
            session=session,
            deployment=deployment,
            compose_yaml=compose_yaml,
            variables=variables,
            state_machine=state_machine,
            update_progress=update_progress,
            create_deployment_metadata=create_deployment_metadata,
        )
    else:
        # Fallback to Python implementation
        await _execute_via_python_fallback(
            session=session,
            deployment=deployment,
            compose_yaml=compose_yaml,
            variables=variables,
            docker_monitor=docker_monitor,
            state_machine=state_machine,
            update_progress=update_progress,
            create_deployment_metadata=create_deployment_metadata,
        )


async def _execute_via_go_service(
    session: Session,
    deployment: Deployment,
    compose_yaml: str,
    variables: Dict[str, str],
    state_machine,
    update_progress: Callable,
    create_deployment_metadata: Callable,
) -> None:
    """
    Execute stack deployment via Go Compose Service.

    Uses the official Docker Compose SDK for full compatibility.
    """
    logger.info(f"Executing deployment {deployment.id} via Go compose service")

    # Get host connection info
    host_info = _get_host_connection_info(deployment.host_id)

    # Build project name from deployment name
    project_name = deployment.name.lower().replace(' ', '-')

    # Create compose client
    client = ComposeClient()

    # Progress callback that updates database and broadcasts to WebSocket
    async def on_progress(event: ProgressEvent):
        await update_progress(
            session,
            deployment,
            event.progress,
            event.message
        )

    try:
        # Transition to pulling state
        state_machine.transition(deployment, 'pulling_image')

        # Execute deployment with progress streaming
        result = await client.deploy_with_progress(
            deployment_id=str(deployment.id),
            project_name=project_name,
            compose_yaml=compose_yaml,
            progress_callback=on_progress,
            action="up",
            environment=variables,
            wait_for_healthy=True,
            health_timeout=120,
            docker_host=host_info.get('docker_host'),
            tls_ca_cert=host_info.get('tls_ca_cert'),
            tls_cert=host_info.get('tls_cert'),
            tls_key=host_info.get('tls_key'),
            registry_credentials=host_info.get('registry_credentials'),
        )

        # Handle result
        if result.success or result.partial_success:
            # Link containers to deployment
            if result.services:
                for service_name, service_info in result.services.items():
                    container_id = service_info.get('container_id', '')[:12]
                    if container_id:
                        create_deployment_metadata(
                            session,
                            deployment.id,
                            deployment.host_id,
                            container_id,
                            service_name=service_name
                        )
                        logger.info(
                            f"Linked container {container_id} to deployment "
                            f"{deployment.id} (service: {service_name})"
                        )

            # Complete state transitions
            state_machine.transition(deployment, 'creating')
            state_machine.transition(deployment, 'starting')

            if result.partial_success:
                # Some services failed - log warning but don't fail
                failed = result.failed_services or []
                logger.warning(
                    f"Deployment {deployment.id} partially succeeded - "
                    f"failed services: {failed}"
                )
                await update_progress(
                    session, deployment, 100,
                    f'Stack deployment completed (some services failed: {", ".join(failed)})'
                )
            else:
                await update_progress(
                    session, deployment, 100, 'Stack deployment completed'
                )

            deployment.committed = True
            session.commit()

            service_count = len(result.services) if result.services else 0
            logger.info(
                f"Stack deployment {deployment.id} completed via Go service - "
                f"{service_count} services created"
            )

        else:
            # Deployment failed
            error_msg = result.error or "Deployment failed"
            logger.error(f"Go compose service deployment failed: {error_msg}")
            raise RuntimeError(f"Stack deployment failed: {error_msg}")

    except ComposeServiceUnavailable:
        # Go service became unavailable - reset check and try Python fallback
        logger.warning(
            f"Go compose service became unavailable during deployment {deployment.id}, "
            "falling back to Python"
        )
        reset_compose_service_check()
        raise RuntimeError(
            "Go compose service unavailable - please retry deployment"
        )

    except ComposeServiceError as e:
        logger.error(f"Compose service error: {e.message}")
        raise RuntimeError(f"Stack deployment failed: {e.message}")


def _get_host_connection_info(host_id: str) -> Dict[str, Any]:
    """
    Get Docker host connection info for compose service.

    Returns:
        Dict with docker_host, tls certs (for mTLS), and registry credentials
    """
    from security.encryption import EncryptionManager

    db = DatabaseManager()
    encryption = EncryptionManager()

    with db.get_session() as session:
        host = session.query(DockerHostDB).filter_by(id=host_id).first()
        if not host:
            raise ValueError(f"Host {host_id} not found")

        result: Dict[str, Any] = {}

        # For remote hosts, include Docker URL and TLS certs
        if host.connection_type == 'remote':
            result['docker_host'] = host.docker_url

            # Decrypt TLS certificates if present
            if host.tls_ca_cert:
                result['tls_ca_cert'] = encryption.decrypt(host.tls_ca_cert)
            if host.tls_cert:
                result['tls_cert'] = encryption.decrypt(host.tls_cert)
            if host.tls_key:
                result['tls_key'] = encryption.decrypt(host.tls_key)

        # Get registry credentials for this host
        # TODO: Implement registry credentials lookup
        result['registry_credentials'] = None

        return result


async def _execute_via_python_fallback(
    session: Session,
    deployment: Deployment,
    compose_yaml: str,
    variables: Dict[str, str],
    docker_monitor,
    state_machine,
    update_progress: Callable,
    create_deployment_metadata: Callable,
) -> None:
    """
    Execute stack deployment using Python implementation (fallback).

    This is the original implementation used when Go service is unavailable.
    """
    logger.info(f"Executing deployment {deployment.id} via Python fallback")

    # Parse compose file for Python implementation
    parser = ComposeParser()
    validator = ComposeValidator()
    orchestrator = StackOrchestrator()

    try:
        # Parse with variable substitution already applied
        compose_data = parser.parse(compose_yaml)

        # Validate compose structure and dependencies
        await update_progress(session, deployment, 15, 'Validating dependencies')
        validator.validate_required_fields(compose_data)
        validator.validate_service_configuration(compose_data)
        validator.validate_dependencies(compose_data)

    except (ComposeParseError, ComposeValidationError, StackOrchestrationError) as e:
        logger.warning(f"Compose validation failed for deployment {deployment.id}: {e}")
        raise RuntimeError(f"Compose validation failed: {e}")

    # Get host connector
    connector = get_host_connector(deployment.host_id, docker_monitor)

    # Track created resources for rollback
    created_networks: List[str] = []
    created_volumes: List[str] = []
    created_services: List[str] = []
    container_ids: Dict[str, str] = {}

    try:
        # Step 4: Create networks
        await _create_networks(
            session, deployment, compose_data, connector,
            created_networks, update_progress
        )

        # Step 5: Create volumes
        await _create_volumes(
            session, deployment, compose_data, connector,
            created_volumes, update_progress
        )

        # Step 6: Deploy services in dependency order
        await _deploy_services(
            session, deployment, compose_data, connector, orchestrator,
            created_services, container_ids, update_progress, create_deployment_metadata
        )

        # Step 7: Deployment complete
        state_machine.transition(deployment, 'pulling_image')
        state_machine.transition(deployment, 'creating')
        state_machine.transition(deployment, 'starting')
        await update_progress(session, deployment, 100, 'Stack deployment completed')
        deployment.committed = True
        session.commit()

        logger.info(
            f"Stack deployment {deployment.id} completed via Python fallback - "
            f"{len(created_services)} services created"
        )

    except Exception as e:
        logger.error(f"Stack deployment {deployment.id} failed: {e}")
        raise


async def _create_networks(
    session: Session,
    deployment: Deployment,
    compose_data: Dict[str, Any],
    connector,
    created_networks: List[str],
    update_progress: Callable,
) -> None:
    """Create networks defined in compose file."""
    if 'networks' not in compose_data:
        return

    await update_progress(session, deployment, 20, 'Creating networks')

    for network_name, network_config in compose_data['networks'].items():
        # Skip external networks
        if network_config and network_config.get('external'):
            logger.info(f"Skipping external network: {network_name}")
            continue

        # Get network driver (default to bridge)
        driver = 'bridge'
        ipam_config = None
        if network_config and isinstance(network_config, dict):
            driver = network_config.get('driver', 'bridge')
            # Parse IPAM configuration if present
            if 'ipam' in network_config:
                ipam_config = parse_ipam_config(network_config['ipam'])

        logger.info(f"Creating network: {network_name} (driver: {driver})")
        try:
            await connector.create_network(network_name, driver=driver, ipam=ipam_config)
            created_networks.append(network_name)
        except Exception as e:
            # Check if network already exists (smart reconciliation)
            if '409' in str(e) or 'already exists' in str(e).lower():
                await reconcile_existing_network(
                    connector=connector,
                    network_name=network_name,
                    driver=driver,
                    ipam_config=ipam_config,
                    created_networks=created_networks
                )
            else:
                raise RuntimeError(f"Failed to create network {network_name}: {e}")


async def _create_volumes(
    session: Session,
    deployment: Deployment,
    compose_data: Dict[str, Any],
    connector,
    created_volumes: List[str],
    update_progress: Callable,
) -> None:
    """Create volumes defined in compose file."""
    if 'volumes' not in compose_data:
        return

    await update_progress(session, deployment, 25, 'Creating volumes')

    for volume_name, volume_config in compose_data['volumes'].items():
        if volume_name.startswith('/'):
            continue  # Skip bind mounts

        logger.info(f"Creating volume: {volume_name}")
        await connector.create_volume(volume_name)
        created_volumes.append(volume_name)


async def _deploy_services(
    session: Session,
    deployment: Deployment,
    compose_data: Dict[str, Any],
    connector,
    orchestrator: StackOrchestrator,
    created_services: List[str],
    container_ids: Dict[str, str],
    update_progress: Callable,
    create_deployment_metadata: Callable,
) -> None:
    """Deploy services in dependency order."""
    service_groups = orchestrator.get_service_groups(compose_data)
    services = compose_data.get('services', {})
    total_services = len(services)
    completed_services = 0

    for group_idx, service_group in enumerate(service_groups):
        for service_name in service_group:
            service_config = services[service_name]

            logger.info(
                f"Deploying service: {service_name} "
                f"({completed_services + 1}/{total_services})"
            )

            # Map compose config to Docker container config
            try:
                container_config = orchestrator.map_service_to_container_config(
                    service_name,
                    service_config,
                    compose_data
                )
            except StackOrchestrationError as e:
                raise RuntimeError(f"Service '{service_name}' configuration error: {e}")

            # Pull image
            progress_base = 30 + (completed_services * 60 // total_services)
            await update_progress(
                session, deployment,
                progress_base,
                f'Pulling image for {service_name}'
            )

            image = container_config['image']

            try:
                await connector.pull_image(image, deployment_id=deployment.id)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to pull image {image} for service {service_name}: {e}"
                )

            # Create container
            await update_progress(
                session, deployment,
                progress_base + 10,
                f'Creating {service_name}'
            )

            # Determine project name for labels
            project_name = compose_data.get('name', deployment.name)

            # Build labels
            labels = _build_service_labels(
                container_config, project_name, service_name, deployment.id
            )
            container_config['labels'] = labels

            # Set container name
            container_config['name'] = _determine_container_name(
                service_config, service_name, compose_data
            )

            try:
                container_short_id = await connector.create_container(
                    container_config,
                    labels
                )
                container_ids[service_name] = container_short_id
                created_services.append(service_name)

                logger.info(
                    f"Created container for {service_name}: {container_short_id}"
                )

            except Exception as e:
                raise RuntimeError(
                    f"Failed to create container for {service_name}: {e}"
                )

            # Start container
            await update_progress(
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
            create_deployment_metadata(
                session,
                deployment.id,
                deployment.host_id,
                container_short_id,
                service_name=service_name
            )

            completed_services += 1


def _build_service_labels(
    container_config: Dict[str, Any],
    project_name: str,
    service_name: str,
    deployment_id: str,
) -> Dict[str, str]:
    """
    Build labels for a service container.

    Handles both list and dict formats from compose config.
    """
    existing_labels = container_config.get('labels', {})

    # Convert list format to dict if needed
    if isinstance(existing_labels, list):
        labels_dict = {}
        for label in existing_labels:
            if '=' in label:
                key, value = label.split('=', 1)
                labels_dict[key] = value
        existing_labels = labels_dict

    # Merge with stack labels
    labels = existing_labels.copy() if isinstance(existing_labels, dict) else {}
    labels.update({
        'com.docker.compose.project': project_name,
        'com.docker.compose.service': service_name,
        'dockmon.deployment_id': deployment_id,
        'dockmon.managed': 'true'
    })

    return labels


def _determine_container_name(
    service_config: Dict[str, Any],
    service_name: str,
    compose_data: Dict[str, Any],
) -> str:
    """
    Determine container name for a service.

    Priority order:
    1. Use explicit container_name from service config if present
    2. Use {compose_name}_{service} if compose has top-level name field
    3. Use just {service} as default
    """
    if 'container_name' in service_config:
        logger.debug(f"Using explicit container_name: {service_config['container_name']}")
        return service_config['container_name']
    elif 'name' in compose_data:
        name = f"{compose_data['name']}_{service_name}"
        logger.debug(f"Using compose name prefix: {name}")
        return name
    else:
        logger.debug(f"Using service name as container name: {service_name}")
        return service_name
