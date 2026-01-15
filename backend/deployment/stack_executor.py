"""
Docker Compose stack deployment executor.

Uses Go Compose Service with official Docker Compose SDK for full compatibility.
Handles validation, variable substitution, and container linkage.
"""

import logging
from typing import Any, Callable, Dict

from sqlalchemy.orm import Session

from database import DatabaseManager, Deployment, DockerHostDB, DeploymentMetadata, DeploymentContainer
from utils.registry_credentials import get_all_registry_credentials
from .compose_parser import ComposeParser, ComposeParseError
from .compose_validator import ComposeValidator, ComposeValidationError
from .compose_client import (
    ComposeClient,
    ProgressEvent,
    ComposeServiceError,
    ComposeServiceUnavailable,
)

logger = logging.getLogger(__name__)


async def execute_stack_deployment(
    session: Session,
    deployment: Deployment,
    definition: Dict[str, Any],
    docker_monitor,  # Unused but kept for API compatibility
    state_machine,
    update_progress: Callable,
    create_deployment_metadata: Callable,
    force_recreate: bool = False,
    pull_images: bool = False,
) -> None:
    """
    Execute Docker Compose stack deployment via Go Compose Service.

    Args:
        session: Database session
        deployment: Deployment instance
        definition: Stack definition with compose_yaml and variables
        docker_monitor: DockerMonitor instance (unused, kept for API compatibility)
        state_machine: DeploymentStateMachine instance
        update_progress: Async callback to update progress
        create_deployment_metadata: Callback to create metadata records
        force_recreate: Force recreate containers even if unchanged (for redeploy)
        pull_images: Pull latest images before starting (for redeploy/update)

    Raises:
        RuntimeError: If validation, parsing, or deployment fails
    """
    logger.info(f"Starting stack deployment {deployment.id}")

    # Extract compose YAML and variables
    compose_yaml = definition.get('compose_yaml')
    variables = definition.get('variables', {})

    if not compose_yaml:
        raise RuntimeError("Stack deployment requires 'compose_yaml' in definition")

    # Step 1: Validate YAML safety (security check)
    parser = ComposeParser()
    validator = ComposeValidator()

    try:
        await update_progress(session, deployment, 5, 'Validating compose file')
        validator.validate_yaml_safety(compose_yaml)

        # Step 2: Apply variable substitution
        await update_progress(session, deployment, 10, 'Processing compose file')
        if variables:
            compose_yaml = parser.substitute_variables(compose_yaml, variables)

    except (ComposeParseError, ComposeValidationError) as e:
        logger.warning(f"Compose validation failed for deployment {deployment.id}: {e}")
        raise RuntimeError(f"Compose validation failed: {e}")

    # Step 3: Execute via Go Compose Service
    await _execute_via_go_service(
        session=session,
        deployment=deployment,
        compose_yaml=compose_yaml,
        variables=variables,
        state_machine=state_machine,
        update_progress=update_progress,
        create_deployment_metadata=create_deployment_metadata,
        force_recreate=force_recreate,
        pull_images=pull_images,
    )


async def _execute_via_go_service(
    session: Session,
    deployment: Deployment,
    compose_yaml: str,
    variables: Dict[str, str],
    state_machine,
    update_progress: Callable,
    create_deployment_metadata: Callable,
    force_recreate: bool = False,
    pull_images: bool = False,
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
        logger.info(f"[PROGRESS] Deployment {deployment.id}: {event.progress}% - {event.stage}: {event.message}")
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
            force_recreate=force_recreate,
            pull_images=pull_images,
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
            # Clear old deployment_metadata records (for redeploy - containers have new IDs)
            session.query(DeploymentMetadata).filter(
                DeploymentMetadata.deployment_id == deployment.id
            ).delete()

            # Clear old deployment_containers records
            session.query(DeploymentContainer).filter(
                DeploymentContainer.deployment_id == deployment.id
            ).delete()

            # Link containers to deployment with new IDs
            if result.services:
                # Collect container IDs for this deployment
                container_ids_to_link = []
                for service_name, service_info in result.services.items():
                    container_id = service_info.get('container_id', '')[:12]
                    if container_id:
                        composite_id = f"{deployment.host_id}:{container_id}"
                        container_ids_to_link.append(composite_id)

                # Clear any existing metadata for these container IDs
                # This handles race conditions with container discovery and
                # reused containers from previous deployments
                if container_ids_to_link:
                    deleted = session.query(DeploymentMetadata).filter(
                        DeploymentMetadata.container_id.in_(container_ids_to_link)
                    ).delete(synchronize_session='fetch')
                    if deleted:
                        logger.debug(f"Cleared {deleted} existing metadata records for reused containers")

                # Now insert fresh metadata
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
                # Some services failed - transition to partial state (not running)
                failed = result.failed_services or []
                logger.warning(
                    f"Deployment {deployment.id} partially succeeded - "
                    f"failed services: {failed}"
                )
                # Transition to 'partial' terminal state instead of 'running'
                state_machine.transition(deployment, 'partial')
                await update_progress(
                    session, deployment, 100,
                    f'Partial deployment - some services failed: {", ".join(failed)}'
                )
            else:
                # Full success - transition to running
                state_machine.transition(deployment, 'running')
                await update_progress(
                    session, deployment, 100, 'Stack deployment completed'
                )

            deployment.committed = True
            session.commit()

            service_count = len(result.services) if result.services else 0
            logger.info(
                f"Stack deployment {deployment.id} completed - "
                f"{service_count} services created"
            )

        else:
            # Deployment failed
            error_msg = result.error or "Deployment failed"
            logger.error(f"Go compose service deployment failed: {error_msg}")
            raise RuntimeError(f"Stack deployment failed: {error_msg}")

    except ComposeServiceUnavailable as e:
        logger.error(f"Go compose service unavailable: {e}")
        raise RuntimeError(
            "Go compose service unavailable. "
            "Ensure compose-service is running and try again."
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
    db = DatabaseManager()

    with db.get_session() as session:
        host = session.query(DockerHostDB).filter_by(id=host_id).first()
        if not host:
            raise ValueError(f"Host {host_id} not found")

        result: Dict[str, Any] = {}

        # For remote hosts, include Docker URL and TLS certs
        if host.connection_type == 'remote':
            result['docker_host'] = host.url

            # TLS certificates are stored as plain PEM (not encrypted)
            if host.tls_ca:
                result['tls_ca_cert'] = host.tls_ca
            if host.tls_cert:
                result['tls_cert'] = host.tls_cert
            if host.tls_key:
                result['tls_key'] = host.tls_key

        # Get all registry credentials for compose deployment
        # We pass all credentials since we don't know which registries
        # the compose file might reference
        try:
            credentials = get_all_registry_credentials(db)
            if credentials:
                result['registry_credentials'] = credentials
                logger.debug(f"Including {len(credentials)} registry credentials for stack deployment")
            else:
                result['registry_credentials'] = None
        except Exception as e:
            logger.warning(f"Failed to get registry credentials for stack deployment: {e}")
            result['registry_credentials'] = None

        return result
