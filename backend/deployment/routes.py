"""
Deployment API routes for DockMon v2.2.7+

Provides REST endpoints for:
- Creating and executing stack deployments
- Tracking deployment progress

Note: Template management has been replaced by the Stacks API (see stack_routes.py)
"""

import logging
import os
import uuid
import yaml
from datetime import datetime, timezone
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from database import Deployment, DatabaseManager, DeploymentMetadata, DockerHostDB
from deployment import DeploymentExecutor
from deployment import stack_storage
from deployment.compose_generator import generate_compose_from_deployment, generate_compose_from_containers
from auth.api_key_auth import get_current_user_or_api_key as get_current_user, require_scope
from utils.keys import parse_composite_key
from agent.command_executor import get_agent_command_executor, RetryPolicy
from agent.manager import AgentManager

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/deployments", tags=["deployments"])


# ==================== Request/Response Models ====================

class DeploymentCreate(BaseModel):
    """Create deployment request (v2.2.7+).

    Creates a deployment for an existing stack. The stack must be created
    first via POST /api/stacks before creating a deployment.
    """
    host_id: str = Field(..., description="UUID of the Docker host to deploy to")
    stack_name: str = Field(..., description="Name of the stack to deploy (must exist in /api/stacks)")
    rollback_on_failure: bool = Field(
        True,
        description="Automatically rollback if deployment fails (default: true)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "host_id": "86a10392-2289-409f-899d-5f5c799086da",
                "stack_name": "my-nginx-stack",
                "rollback_on_failure": True
            }
        }
    )


class DeploymentUpdate(BaseModel):
    """Update deployment request (v2.2.7+).

    Note: To update compose content, use PUT /api/stacks/{name} instead.
    This endpoint only allows changing the target stack or host.
    """
    stack_name: Optional[str] = Field(None, description="Change target stack (must exist)")
    host_id: Optional[str] = Field(None, description="Change target host")


class DeploymentResponse(BaseModel):
    """Deployment response (v2.2.7+)."""
    id: str
    host_id: str
    stack_name: str  # References stack in /app/data/stacks/{stack_name}/
    status: str
    progress_percent: int
    current_stage: Optional[str]
    error_message: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    created_by: Optional[str] = None  # Username who created deployment
    committed: bool
    rollback_on_failure: bool
    updated_at: Optional[str] = None
    host_name: Optional[str] = None
    container_ids: Optional[List[str]] = None  # List of SHORT container IDs (12 chars) from deployment_metadata




class ExecuteDeploymentRequest(BaseModel):
    """Request to execute a deployment with optional redeploy options."""
    force_recreate: bool = Field(
        False,
        description="Force recreate containers even if unchanged (for redeploy)"
    )
    pull_images: bool = Field(
        False,
        description="Pull latest images before starting (for redeploy/update)"
    )


class DeployStackRequest(BaseModel):
    """Deploy a stack to a host (fire and forget - no persistent tracking).

    This is a simplified deployment flow that doesn't create persistent
    deployment records. Progress is tracked via WebSocket using a transient ID.
    """
    stack_name: str = Field(..., description="Name of the stack to deploy (must exist in /api/stacks)")
    host_id: str = Field(..., description="UUID of the Docker host to deploy to")
    force_recreate: bool = Field(
        True,
        description="Force recreate containers even if unchanged (default: true)"
    )
    pull_images: bool = Field(
        True,
        description="Pull latest images before starting (default: true)"
    )


class DeployStackResponse(BaseModel):
    """Response from deploy endpoint with transient deployment ID."""
    deployment_id: str = Field(..., description="Transient ID for progress tracking via WebSocket")
    stack_name: str
    host_id: str


# ==================== Import Stack Models ====================

class KnownStack(BaseModel):
    """A stack discovered from container labels."""
    name: str
    hosts: List[str]
    host_names: List[str]
    container_count: int
    services: List[str]


class ImportDeploymentRequest(BaseModel):
    """Request to import an existing compose stack."""
    compose_content: str = Field(..., description="Docker Compose YAML content")
    env_content: Optional[str] = Field(None, description="Optional .env file content")
    project_name: Optional[str] = Field(None, description="Stack name (required if compose has no name: field)")
    host_id: Optional[str] = Field(None, description="Host ID for import when no running containers found")
    overwrite_stack: bool = Field(False, description="If true, overwrite existing stack content")
    use_existing_stack: bool = Field(False, description="If true, skip stack creation (use existing stack on disk)")


class ImportDeploymentResponse(BaseModel):
    """Response from import operation."""
    success: bool
    deployments_created: List[DeploymentResponse]
    requires_name_selection: bool = False
    known_stacks: Optional[List[KnownStack]] = None
    stack_exists: bool = False
    existing_stack_name: Optional[str] = None


# ==================== Scan Compose Dirs Models ====================

class ScanComposeDirsRequest(BaseModel):
    """Request to scan directories for compose files."""
    paths: Optional[List[str]] = Field(
        None,
        description="Paths to scan. If empty, uses default paths (/opt, /srv, /var/lib/docker/volumes, etc.)"
    )
    recursive: bool = Field(True, description="Scan recursively (default: true)")
    max_depth: int = Field(5, description="Maximum depth for recursive scan (default: 5)")


class ComposeFileInfo(BaseModel):
    """Metadata about a discovered compose file."""
    path: str
    project_name: str
    services: List[str]
    size: int
    modified: str


class ScanComposeDirsResponse(BaseModel):
    """Response from directory scan."""
    success: bool
    compose_files: List[ComposeFileInfo]
    error: Optional[str] = None


# ==================== Read Compose File Models ====================

class ReadComposeFileRequest(BaseModel):
    """Request to read a compose file's content."""
    path: str = Field(..., description="Full path to compose file on agent host")


class ReadComposeFileResponse(BaseModel):
    """Response containing compose file content."""
    success: bool
    path: str
    content: Optional[str] = None
    env_content: Optional[str] = None
    error: Optional[str] = None


class ComposePreviewResponse(BaseModel):
    """Preview of generated compose.yaml from containers."""
    compose_yaml: str
    services: List[str]
    warnings: List[str]


class GenerateFromContainersRequest(BaseModel):
    """Request to generate compose.yaml from running containers."""
    project_name: str = Field(..., description="Docker Compose project name (from container labels)")
    host_id: str = Field(..., description="Host ID where containers are running")


class RunningProject(BaseModel):
    """A running Docker Compose project discovered from container labels."""
    project_name: str
    host_id: str
    host_name: Optional[str]
    container_count: int
    services: List[str]


# ==================== Dependency Injection ====================

# These will be set by main.py during startup
_deployment_executor: Optional[DeploymentExecutor] = None
_database_manager: Optional[DatabaseManager] = None
_docker_monitor = None  # DockerMonitor instance


def set_deployment_executor(executor: DeploymentExecutor):
    """Set deployment executor instance (called from main.py)."""
    global _deployment_executor
    _deployment_executor = executor


def set_database_manager(db: DatabaseManager):
    """Set database manager instance (called from main.py)."""
    global _database_manager
    _database_manager = db


def get_deployment_executor() -> DeploymentExecutor:
    """Get deployment executor (dependency)."""
    if _deployment_executor is None:
        raise RuntimeError("DeploymentExecutor not initialized")
    return _deployment_executor


def get_database_manager() -> DatabaseManager:
    """Get database manager (dependency)."""
    if _database_manager is None:
        raise RuntimeError("DatabaseManager not initialized")
    return _database_manager


def set_docker_monitor(monitor):
    """Set docker monitor instance (called from main.py)."""
    global _docker_monitor
    _docker_monitor = monitor


def get_docker_monitor():
    """Get docker monitor (dependency)."""
    if _docker_monitor is None:
        raise RuntimeError("DockerMonitor not initialized")
    return _docker_monitor


# ==================== Deployment Endpoints ====================

@router.post("/deploy", response_model=DeployStackResponse, dependencies=[Depends(require_scope("write"))])
async def deploy_stack(
    request: DeployStackRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
):
    """
    Deploy a stack to a host (fire and forget - no persistent tracking).

    This is a simplified deployment flow:
    1. Reads stack content from filesystem
    2. Generates a transient deployment_id for WebSocket progress tracking
    3. Routes to agent (for agent hosts) or Go compose service (for local/mTLS hosts)
    4. Does NOT persist any deployment records

    Progress can be tracked via WebSocket events using the returned deployment_id:
    - deployment_progress (real-time progress)
    - deployment_completed (success)
    - deployment_failed (error)

    Use this for simple "deploy and forget" workflows. The deployed_to info
    in the stacks list is derived from running container labels, not from
    deployment records.
    """
    from deployment.compose_client import ComposeClient, ComposeServiceError, ComposeServiceUnavailable
    from deployment.stack_executor import _get_host_connection_info
    from deployment.agent_executor import get_agent_deployment_executor

    # Validate stack exists
    if not await stack_storage.stack_exists(request.stack_name):
        raise HTTPException(status_code=404, detail=f"Stack '{request.stack_name}' not found")

    # Validate host exists and get connection type
    db = get_database_manager()
    with db.get_session() as session:
        host = session.query(DockerHostDB).filter_by(id=request.host_id).first()
        if not host:
            raise HTTPException(status_code=404, detail=f"Host '{request.host_id}' not found")
        host_name = host.name
        connection_type = host.connection_type

    # Read stack content
    compose_yaml, env_content = await stack_storage.read_stack(request.stack_name)

    # Generate transient deployment ID for progress tracking
    deployment_id = f"{request.host_id}:{request.stack_name}:{uuid.uuid4().hex[:8]}"

    # Get docker monitor for broadcasting
    docker_monitor = get_docker_monitor()

    async def broadcast_event(payload: dict):
        """Broadcast event via WebSocket."""
        try:
            if docker_monitor and hasattr(docker_monitor, 'manager'):
                await docker_monitor.manager.broadcast(payload)
        except Exception as e:
            logger.error(f"Error broadcasting deployment event: {e}")

    # Parse environment variables from .env content
    env_vars = {}
    if env_content:
        for line in env_content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()

    # Route based on connection type
    if connection_type == 'agent':
        # Execute deployment via agent
        async def execute_agent_deploy():
            try:
                # Send initial progress
                await broadcast_event({
                    'type': 'deployment_progress',
                    'deployment_id': deployment_id,
                    'host_id': request.host_id,
                    'name': request.stack_name,
                    'status': 'pending',
                    'progress': {
                        'overall_percent': 0,
                        'stage': 'Starting deployment via agent...',
                    },
                })

                executor = get_agent_deployment_executor(docker_monitor)
                success = await executor.deploy(
                    host_id=request.host_id,
                    deployment_id=deployment_id,
                    compose_content=compose_yaml,
                    project_name=request.stack_name,
                    environment=env_vars if env_vars else None,
                    force_recreate=request.force_recreate,
                    pull_images=request.pull_images,
                    wait_for_healthy=True,
                    health_timeout=120,
                )

                # Note: Don't broadcast completion here - the agent sends deploy_complete
                # which is handled by handle_deploy_complete and broadcasts to WebSocket
                if success:
                    logger.info(f"Stack '{request.stack_name}' deployment command accepted by agent for '{host_name}'")
                else:
                    # Agent executor already broadcasts failure via handle_deploy_complete
                    logger.error(f"Stack deployment to agent failed for '{host_name}'")

            except Exception as e:
                await broadcast_event({
                    'type': 'deployment_failed',
                    'deployment_id': deployment_id,
                    'host_id': request.host_id,
                    'name': request.stack_name,
                    'status': 'failed',
                    'error': str(e),
                })
                logger.error(f"Agent deployment failed: {e}", exc_info=True)

        background_tasks.add_task(execute_agent_deploy)

    else:
        # Execute deployment via local compose service (for local and mTLS hosts)
        async def execute_compose_deploy():
            client = ComposeClient()

            try:
                # Get host connection info
                host_info = _get_host_connection_info(request.host_id)

                # Progress callback that broadcasts to WebSocket
                async def on_progress(event):
                    await broadcast_event({
                        'type': 'deployment_progress',
                        'deployment_id': deployment_id,
                        'host_id': request.host_id,
                        'name': request.stack_name,
                        'status': 'in_progress',
                        'progress': {
                            'overall_percent': event.progress,
                            'stage': event.message,
                        },
                    })

                # Send initial progress
                await broadcast_event({
                    'type': 'deployment_progress',
                    'deployment_id': deployment_id,
                    'host_id': request.host_id,
                    'name': request.stack_name,
                    'status': 'pending',
                    'progress': {
                        'overall_percent': 0,
                        'stage': 'Starting deployment...',
                    },
                })

                # Execute deployment
                result = await client.deploy_with_progress(
                    deployment_id=deployment_id,
                    project_name=request.stack_name,
                    compose_yaml=compose_yaml,
                    progress_callback=on_progress,
                    action="up",
                    environment=env_vars,
                    force_recreate=request.force_recreate,
                    pull_images=request.pull_images,
                    wait_for_healthy=True,
                    health_timeout=120,
                    docker_host=host_info.get('docker_host'),
                    tls_ca_cert=host_info.get('tls_ca_cert'),
                    tls_cert=host_info.get('tls_cert'),
                    tls_key=host_info.get('tls_key'),
                    registry_credentials=host_info.get('registry_credentials'),
                )

                if result.success or result.partial_success:
                    status = "running" if result.success else "partial"
                    await broadcast_event({
                        'type': 'deployment_completed',
                        'deployment_id': deployment_id,
                        'host_id': request.host_id,
                        'name': request.stack_name,
                        'status': status,
                        'progress': {
                            'overall_percent': 100,
                            'stage': 'Deployment complete',
                        },
                    })
                    logger.info(f"Stack '{request.stack_name}' deployed to '{host_name}'")
                else:
                    await broadcast_event({
                        'type': 'deployment_failed',
                        'deployment_id': deployment_id,
                        'host_id': request.host_id,
                        'name': request.stack_name,
                        'status': 'failed',
                        'error': result.error or 'Deployment failed',
                        'progress': {
                            'overall_percent': 0,
                            'stage': 'Failed',
                        },
                    })
                    logger.error(f"Stack deployment failed: {result.error}")

            except ComposeServiceUnavailable as e:
                await broadcast_event({
                    'type': 'deployment_failed',
                    'deployment_id': deployment_id,
                    'host_id': request.host_id,
                    'name': request.stack_name,
                    'status': 'failed',
                    'error': 'Compose service unavailable. Ensure compose-service is running.',
                })
                logger.error(f"Compose service unavailable: {e}")

            except ComposeServiceError as e:
                await broadcast_event({
                    'type': 'deployment_failed',
                    'deployment_id': deployment_id,
                    'host_id': request.host_id,
                    'name': request.stack_name,
                    'status': 'failed',
                    'error': str(e.message),
                })
                logger.error(f"Compose service error: {e.message}")

            except Exception as e:
                await broadcast_event({
                    'type': 'deployment_failed',
                    'deployment_id': deployment_id,
                    'host_id': request.host_id,
                    'name': request.stack_name,
                    'status': 'failed',
                    'error': str(e),
                })
                logger.error(f"Deployment failed: {e}", exc_info=True)

        background_tasks.add_task(execute_compose_deploy)

    logger.info(f"User {current_user['username']} started deployment of '{request.stack_name}' to '{host_name}'")

    return DeployStackResponse(
        deployment_id=deployment_id,
        stack_name=request.stack_name,
        host_id=request.host_id,
    )


@router.post("", response_model=DeploymentResponse, status_code=201, dependencies=[Depends(require_scope("write"))])
async def create_deployment(
    request: DeploymentCreate,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    executor: DeploymentExecutor = Depends(get_deployment_executor)
):
    """
    Create a new deployment (v2.2.7+).

    Creates a deployment in 'planning' state. Call /deployments/{id}/execute to start it.

    **Workflow:**
    1. Create a stack first via POST /api/stacks (compose.yaml + optional .env)
    2. Create a deployment referencing the stack via this endpoint
    3. Execute the deployment via POST /deployments/{id}/execute

    **Example:**
    ```json
    {
      "host_id": "86a10392-2289-409f-899d-5f5c799086da",
      "stack_name": "my-nginx-stack",
      "rollback_on_failure": true
    }
    ```

    The stack must exist before creating a deployment.
    """
    try:
        deployment_id = await executor.create_deployment(
            host_id=request.host_id,
            stack_name=request.stack_name,
            user_id=current_user['user_id'],
            rollback_on_failure=request.rollback_on_failure,
            created_by=current_user['username'],
        )

        # Fetch created deployment
        db = get_database_manager()
        with db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            return _deployment_to_response(deployment)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create deployment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{deployment_id}/execute", response_model=DeploymentResponse, dependencies=[Depends(require_scope("write"))])
async def execute_deployment(
    deployment_id: str,
    background_tasks: BackgroundTasks,
    request: Optional[ExecuteDeploymentRequest] = None,
    current_user=Depends(get_current_user),
    executor: DeploymentExecutor = Depends(get_deployment_executor)
):
    """
    Execute a deployment (pull image, create container, start container).

    For redeploy (updating running stacks), set force_recreate=true and/or pull_images=true
    in the request body. This allows redeploying from 'running' status.

    Deployment progress can be tracked via WebSocket events:
    - DEPLOYMENT_PROGRESS (real-time progress updates)
    - DEPLOYMENT_COMPLETED (success)
    - DEPLOYMENT_FAILED (error)
    - DEPLOYMENT_ROLLED_BACK (rollback after failure)
    """
    try:
        # Extract redeploy options (default to False if no body provided)
        force_recreate = request.force_recreate if request else False
        pull_images = request.pull_images if request else False
        is_redeploy = force_recreate or pull_images

        # Check deployment status before executing with row-level lock
        # This prevents race condition where multiple concurrent requests execute same deployment
        db = get_database_manager()
        with db.get_session() as session:
            # Use with_for_update() to acquire row lock (prevents concurrent modifications)
            deployment = session.query(Deployment).filter_by(
                id=deployment_id,
                user_id=current_user['user_id']
            ).with_for_update().first()
            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

            # Determine valid statuses based on operation type
            # For redeploy: also allow 'running' status (force recreate running containers)
            # For normal execute: only non-terminal non-running states
            valid_statuses = {'planning', 'failed', 'rolled_back', 'partial'}
            if is_redeploy:
                valid_statuses.add('running')

            # Only allow execution from valid statuses
            # In-progress states (validating, pulling_image, creating, starting) cannot be re-executed
            if deployment.status not in valid_statuses:
                if is_redeploy:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot redeploy deployment in status '{deployment.status}'. Only 'running', 'planning', 'failed', 'rolled_back', or 'partial' deployments can be redeployed."
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot execute deployment in status '{deployment.status}'. Only 'planning', 'failed', 'rolled_back', or 'partial' deployments can be executed."
                    )

            # Lock is held during this critical section - prevents other threads from modifying
            # Row lock is released when session closes (after this with block)

            # Execute deployment in background with redeploy options
            background_tasks.add_task(
                executor.execute_deployment,
                deployment_id,
                force_recreate=force_recreate,
                pull_images=pull_images
            )

            # Return updated deployment state
            # Note: We DON'T need another query here - we already have the locked row
            return _deployment_to_response(deployment)

    except HTTPException:
        # Re-raise HTTP exceptions as-is (don't log as error)
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to execute deployment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[DeploymentResponse])
async def list_deployments(
    host_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user=Depends(get_current_user),
):
    """
    List deployments with optional filters.

    Filters:
    - host_id: Filter by host
    - status: Filter by status (planning, validating, pulling_image, creating, starting, running, failed, rolled_back)
    - limit: Max results (default: 100, max: 1000)
    - offset: Skip first N results (default: 0)
    """
    try:
        # Validate pagination parameters (prevent DoS via unlimited queries)
        if limit < 1:
            raise HTTPException(status_code=400, detail="limit must be at least 1")
        if limit > 1000:
            raise HTTPException(status_code=400, detail="limit cannot exceed 1000")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset cannot be negative")

        # Validate status if provided
        valid_statuses = {'planning', 'validating', 'pulling_image', 'creating', 'starting', 'running', 'failed', 'rolled_back'}
        if status and status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}")

        db = get_database_manager()
        with db.get_session() as session:
            query = session.query(Deployment)

            # CRITICAL: Filter by user_id to prevent users from seeing other users' deployments
            query = query.filter_by(user_id=current_user['user_id'])

            if host_id:
                query = query.filter_by(host_id=host_id)

            if status:
                query = query.filter_by(status=status)

            deployments = query.order_by(Deployment.created_at.desc()).offset(offset).limit(limit).all()

            return [_deployment_to_response(d) for d in deployments]

    except Exception as e:
        logger.error(f"Failed to list deployments: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Import Stack Endpoints ====================
# NOTE: Static routes MUST be defined BEFORE path parameter routes (/{deployment_id})
# to ensure FastAPI matches them first.

@router.get("/known-stacks", response_model=List[KnownStack])
async def get_known_stacks(
    current_user=Depends(get_current_user),
):
    """
    Get list of known stack names from container labels across all hosts.

    Used for the fallback UI when a compose file has no 'name:' field.
    Scans all containers for 'com.docker.compose.project' label.
    """
    from deployment.container_utils import scan_deployed_stacks

    monitor = get_docker_monitor()
    all_containers = monitor.get_last_containers()
    deployed_stacks = scan_deployed_stacks(all_containers)

    # Convert to KnownStack format
    return [
        KnownStack(
            name=info.name,
            hosts=[h.host_id for h in info.hosts],
            host_names=[h.host_name for h in info.hosts],
            container_count=info.container_count,
            services=info.services,
        )
        for info in deployed_stacks.values()
    ]


def _get_container_project(container) -> str | None:
    """Extract the compose project name from container labels."""
    labels = getattr(container, 'labels', {}) or {}
    return labels.get('com.docker.compose.project')


@router.get("/running-projects", response_model=List[RunningProject])
async def list_running_projects(
    current_user=Depends(get_current_user),
):
    """
    List all running Docker Compose projects discovered from container labels.

    Returns projects that can be adopted into DockMon management.
    Groups containers by com.docker.compose.project label.
    """
    monitor = get_docker_monitor()
    db = get_database_manager()

    # Group containers by (project_name, host_id)
    projects: Dict[tuple, dict] = {}
    all_containers = monitor.get_last_containers()
    for container in all_containers:
        labels = getattr(container, 'labels', {}) or {}
        project_name = _get_container_project(container)
        host_id = getattr(container, 'host_id', None)

        if not project_name or not host_id:
            continue

        key = (project_name, host_id)
        if key not in projects:
            projects[key] = {'services': set(), 'count': 0}

        projects[key]['count'] += 1
        service_name = labels.get('com.docker.compose.service')
        if service_name:
            projects[key]['services'].add(service_name)

    # Get host names
    with db.get_session() as session:
        host_names = {host.id: host.name for host in session.query(DockerHostDB).all()}

    # Build and sort response
    result = [
        RunningProject(
            project_name=project_name,
            host_id=host_id,
            host_name=host_names.get(host_id),
            container_count=data['count'],
            services=sorted(data['services']),
        )
        for (project_name, host_id), data in projects.items()
    ]
    result.sort(key=lambda p: (p.project_name, p.host_name or p.host_id))
    return result


@router.post("/generate-from-containers", response_model=ComposePreviewResponse)
async def generate_compose_from_running_containers(
    request: GenerateFromContainersRequest,
    current_user=Depends(get_current_user),
):
    """
    Generate compose.yaml from running containers with a specific project name.

    Used to "adopt" existing docker-compose stacks into DockMon management.
    Finds all containers on the specified host with the matching
    com.docker.compose.project label and generates a compose file from their config.
    """
    monitor = get_docker_monitor()

    # Find all containers on this host with matching project name
    matching_containers = [
        c for c in monitor.get_last_containers()
        if getattr(c, 'host_id', None) == request.host_id
        and _get_container_project(c) == request.project_name
    ]

    if not matching_containers:
        raise HTTPException(
            status_code=404,
            detail=f"No containers found with project '{request.project_name}' on host {request.host_id}"
        )

    # Generate compose from containers
    compose_yaml, warnings = await generate_compose_from_containers(
        project_name=request.project_name,
        host_id=request.host_id,
        containers=matching_containers,
        monitor=monitor,
    )

    # Parse services from generated YAML
    compose_dict = yaml.safe_load(compose_yaml)
    services = list(compose_dict.get("services", {}).keys())

    logger.info(f"User '{current_user['username']}' generated compose for project '{request.project_name}' ({len(services)} services)")

    return ComposePreviewResponse(
        compose_yaml=compose_yaml,
        services=services,
        warnings=warnings,
    )


# ==================== Deployment CRUD (Path Parameter Routes) ====================
# NOTE: These routes with /{deployment_id} MUST come AFTER all static routes above.

@router.get("/{deployment_id}", response_model=DeploymentResponse)
async def get_deployment(
    deployment_id: str,
    current_user=Depends(get_current_user),
):
    """Get deployment details by ID."""
    try:
        db = get_database_manager()
        with db.get_session() as session:
            deployment = session.query(Deployment).filter_by(
                id=deployment_id,
                user_id=current_user['user_id']
            ).first()

            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

            return _deployment_to_response(deployment)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deployment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{deployment_id}", response_model=DeploymentResponse, dependencies=[Depends(require_scope("write"))])
async def update_deployment(
    deployment_id: str,
    request: DeploymentUpdate,
    current_user=Depends(get_current_user),
):
    """
    Update a deployment (v2.2.7+).

    Allowed in: 'planning', 'failed', 'rolled_back', 'partial', or 'running' states.

    Note: To update compose content, use PUT /api/stacks/{name} instead.
    This endpoint allows changing the target stack or host.
    """
    try:
        db = get_database_manager()

        with db.get_session() as session:
            # Fetch deployment (with authorization check)
            deployment = session.query(Deployment).filter_by(
                id=deployment_id,
                user_id=current_user['user_id']
            ).first()
            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

            # Allow editing in 'planning', 'failed', 'rolled_back', 'partial', or 'running' states
            editable_statuses = ['planning', 'failed', 'rolled_back', 'partial', 'running']
            if deployment.status not in editable_statuses:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot edit deployment in status '{deployment.status}'. Only {editable_statuses} deployments can be edited."
                )

            # If retrying a failed/rolled_back/partial deployment, reset error state and progress
            if deployment.status in ['failed', 'rolled_back', 'partial']:
                deployment.status = 'planning'  # Reset to planning for retry
                deployment.error_message = None  # Clear previous error
                deployment.progress_percent = 0  # Reset progress indicator
                logger.info(f"Deployment {deployment_id} being retried (was {deployment.status})")

            # Update fields if provided
            if request.stack_name is not None:
                # Validate new stack exists
                if not await stack_storage.stack_exists(request.stack_name):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Stack '{request.stack_name}' not found"
                    )
                deployment.stack_name = request.stack_name

            if request.host_id is not None:
                deployment.host_id = request.host_id

            deployment.updated_at = datetime.now(timezone.utc)

            # Commit changes
            session.commit()
            session.refresh(deployment)

            logger.info(f"Deployment {deployment_id} updated (stack={deployment.stack_name})")
            return _deployment_to_response(deployment)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update deployment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{deployment_id}", dependencies=[Depends(require_scope("write"))])
async def delete_deployment(
    deployment_id: str,
    current_user=Depends(get_current_user),
):
    """
    Delete a deployment record.

    Only deletes the deployment record, does not affect created containers.
    Cannot delete deployments that are currently executing (validating, pulling_image, creating, starting).
    Can delete: planning (not started), running (completed), failed, rolled_back (terminal states).
    """
    try:
        db = get_database_manager()
        with db.get_session() as session:
            deployment = session.query(Deployment).filter_by(
                id=deployment_id,
                user_id=current_user['user_id']
            ).first()

            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

            # Prevent deletion of deployments that are actively executing
            # These states indicate the deployment is in progress: validating, pulling_image, creating, starting
            in_progress_states = {'validating', 'pulling_image', 'creating', 'starting'}
            if deployment.status in in_progress_states:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete deployment while it is executing. Wait for completion or failure."
                )

            session.delete(deployment)
            session.commit()

            logger.info(f"Deleted deployment {deployment_id}")

            return {"success": True, "message": "Deployment deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete deployment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{deployment_id}/compose-preview", response_model=ComposePreviewResponse)
async def preview_compose_from_containers(
    deployment_id: str,
    current_user=Depends(get_current_user),
):
    """
    Preview compose.yaml that would be generated from deployment's containers.

    Used before "Recreate from containers" to show what will be created.
    """
    db = get_database_manager()
    monitor = get_docker_monitor()

    with db.get_session() as session:
        deployment = session.query(Deployment).filter_by(
            id=deployment_id,
            user_id=current_user['user_id']
        ).first()

        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")

        compose_yaml, warnings = await generate_compose_from_deployment(
            deployment_id=deployment_id,
            host_id=deployment.host_id,
            session=session,
            monitor=monitor,
        )

        # Parse services from generated YAML
        compose_dict = yaml.safe_load(compose_yaml)
        services = list(compose_dict.get("services", {}).keys())

        return ComposePreviewResponse(
            compose_yaml=compose_yaml,
            services=services,
            warnings=warnings,
        )


@router.post("/import", response_model=ImportDeploymentResponse, status_code=201, dependencies=[Depends(require_scope("write"))])
async def import_deployment(
    request: ImportDeploymentRequest,
    current_user=Depends(get_current_user),
):
    """
    Import an existing stack by providing compose content.

    Auto-detects which host(s) have the stack running and creates
    deployment record(s) for each. If compose file has no 'name:' field,
    returns list of known stacks for user to select from.
    """
    user_id = current_user['user_id']

    # 1. Validate compose YAML syntax
    try:
        compose_dict = yaml.safe_load(request.compose_content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    if not compose_dict or not isinstance(compose_dict, dict):
        raise HTTPException(status_code=400, detail="Invalid compose file: expected YAML dictionary")

    # 2. Validate services exist
    services = compose_dict.get('services', {})
    if not services:
        raise HTTPException(status_code=400, detail="No services defined in compose file")

    # 3. Determine project name
    project_name = compose_dict.get('name') or request.project_name

    if not project_name:
        # No name in compose file and none provided - return known stacks for selection
        known_stacks = await get_known_stacks(current_user)
        return ImportDeploymentResponse(
            success=False,
            deployments_created=[],
            requires_name_selection=True,
            known_stacks=known_stacks
        )

    # 4. Find all hosts that have this stack running
    monitor = get_docker_monitor()
    all_containers = monitor.get_last_containers()

    # Extract container_name values from compose for fallback matching
    container_names_in_compose = set()
    for svc_name, svc_config in services.items():
        if isinstance(svc_config, dict) and svc_config.get('container_name'):
            container_names_in_compose.add(svc_config['container_name'])

    # Group containers by host for this project
    hosts_with_stack: Dict[str, List] = {}
    for container in all_containers:
        labels = getattr(container, 'labels', {}) or {}
        if labels.get('com.docker.compose.project') == project_name:
            host_id = getattr(container, 'host_id', None)
            if host_id:
                if host_id not in hosts_with_stack:
                    hosts_with_stack[host_id] = []
                hosts_with_stack[host_id].append(container)

    # Fallback: if no match by project label, try matching by container names
    if not hosts_with_stack and container_names_in_compose:
        logger.info(f"No containers found by project label '{project_name}', trying fallback by container names")
        for container in all_containers:
            container_name = getattr(container, 'name', '')
            if container_name in container_names_in_compose:
                host_id = getattr(container, 'host_id', None)
                if host_id:
                    if host_id not in hosts_with_stack:
                        hosts_with_stack[host_id] = []
                    hosts_with_stack[host_id].append(container)
        if hosts_with_stack:
            logger.info(f"Found containers by name fallback on {len(hosts_with_stack)} host(s)")

    # If still no containers found but host_id provided, allow import with status "stopped"
    import_as_stopped = False
    if not hosts_with_stack:
        if request.host_id:
            logger.info(f"No running containers found for '{project_name}', importing as stopped on host {request.host_id}")
            hosts_with_stack[request.host_id] = []
            import_as_stopped = True
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No running containers found for stack '{project_name}'. Provide host_id to import anyway."
            )

    # 5. Create or update stack on filesystem (v2.2.7+)
    stack_name = stack_storage.sanitize_stack_name(project_name)
    stack_already_exists = await stack_storage.stack_exists(stack_name)

    if stack_already_exists and not request.overwrite_stack and not request.use_existing_stack:
        # Stack exists and user hasn't made a choice - ask them
        return ImportDeploymentResponse(
            success=False,
            deployments_created=[],
            requires_name_selection=False,
            stack_exists=True,
            existing_stack_name=stack_name,
        )

    if request.use_existing_stack:
        # User chose to use existing stack - don't touch files
        # Find actual filesystem name (may differ in case from sanitized name)
        actual_stack_name = await stack_storage.find_stack_by_name(stack_name)
        if actual_stack_name:
            stack_name = actual_stack_name
            logger.info(f"User '{current_user['username']}' using existing stack '{stack_name}' on filesystem")
        else:
            # Edge case: stack was deleted between check and import
            await stack_storage.write_stack(
                name=stack_name,
                compose_yaml=request.compose_content,
                env_content=request.env_content,
            )
            logger.info(f"User '{current_user['username']}' created stack '{stack_name}' (use_existing_stack but stack was missing)")
    elif not stack_already_exists:
        # Create new stack
        await stack_storage.write_stack(
            name=stack_name,
            compose_yaml=request.compose_content,
            env_content=request.env_content,
        )
        logger.info(f"User '{current_user['username']}' created stack '{stack_name}' on filesystem during import")
    elif request.overwrite_stack:
        # Overwrite existing stack content
        await stack_storage.write_stack(
            name=stack_name,
            compose_yaml=request.compose_content,
            env_content=request.env_content,
        )
        logger.info(f"User '{current_user['username']}' overwrote existing stack '{stack_name}' on filesystem during import")

    # 6. Create deployment for each host
    db = get_database_manager()
    deployments_created = []

    with db.get_session() as session:
        for host_id, containers in hosts_with_stack.items():
            # Check for duplicate deployment on this host (v2.2.7+: use stack_name)
            existing = session.query(Deployment).filter_by(
                host_id=host_id,
                stack_name=stack_name,
                user_id=user_id
            ).first()
            if existing:
                logger.info(f"Deployment for stack '{stack_name}' already exists on host {host_id}, skipping")
                continue

            # Create Deployment record (v2.2.7+: no definition, no deployment_type)
            deployment_id = str(uuid.uuid4())

            deployment = Deployment(
                id=deployment_id,
                host_id=host_id,
                user_id=user_id,
                stack_name=stack_name,
                status='stopped' if import_as_stopped else 'running',
                created_by=current_user['username'],
                progress_percent=100,
                committed=True,
                rollback_on_failure=False,
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            session.add(deployment)

            # Link containers for this host (skip if imported as stopped with no containers)
            containers_linked = 0
            if containers:
                containers_linked = _link_containers_for_host(
                    session=session,
                    containers=containers,
                    host_id=host_id,
                    deployment_id=deployment_id
                )

            logger.info(f"Imported deployment for stack '{stack_name}' on host {host_id} with {containers_linked} containers (stopped={import_as_stopped})")
            deployments_created.append(deployment)

        session.commit()

        # Convert to response INSIDE session context to avoid DetachedInstanceError
        response_deployments = [_deployment_to_response(d, session) for d in deployments_created]

    return ImportDeploymentResponse(
        success=True,
        deployments_created=response_deployments,
        requires_name_selection=False
    )


# ==================== Scan Compose Dirs Endpoint ====================

@router.post("/scan-compose-dirs/{host_id}", response_model=ScanComposeDirsResponse)
async def scan_compose_dirs(
    host_id: str,
    request: Optional[ScanComposeDirsRequest] = None,
    current_user=Depends(get_current_user),
):
    """
    Scan directories for Docker Compose files.

    This allows discovery of existing compose stacks on a host for import.
    Works with:
    - local hosts: scans within DockMon container (paths must be mounted)
    - agent hosts: sends command to agent via WebSocket

    Default paths scanned: /opt, /srv, /var/lib/docker/volumes, /home, /stacks, /docker
    """
    # Validate host exists
    db = get_database_manager()
    with db.get_session() as session:
        host = session.query(DockerHostDB).filter_by(id=host_id).first()
        if not host:
            raise HTTPException(status_code=404, detail="Host not found")

        connection_type = host.connection_type

    # Route based on connection type
    if connection_type == 'local':
        return await _scan_local_dirs(request)
    elif connection_type == 'agent':
        return await _scan_agent_dirs(host_id, request)
    else:
        raise HTTPException(
            status_code=400,
            detail="Directory scanning is only available for local and agent-based hosts"
        )


def _is_path_safe(path: str) -> bool:
    """Check if a path is safe to access (not a system directory)."""
    # Normalize path to resolve .. and symlinks
    try:
        path = os.path.realpath(path)
    except (OSError, IOError):
        return False

    # Block system directories (consistent with agent's scan.go)
    # /etc is blocked entirely to prevent access to sensitive config files
    blocked_prefixes = [
        '/proc', '/sys', '/dev', '/run', '/boot',
        '/bin', '/sbin', '/lib', '/lib64',
        '/usr/bin', '/usr/sbin', '/usr/lib',
        '/etc',  # Block all of /etc, not just specific files
    ]
    for prefix in blocked_prefixes:
        if path == prefix or path.startswith(prefix + '/'):
            return False
    return True


async def _scan_local_dirs(request: Optional[ScanComposeDirsRequest]) -> ScanComposeDirsResponse:
    """Scan directories within the DockMon container for compose files."""
    # Default paths to scan
    default_paths = [
        "/opt",
        "/srv",
        "/var/lib/docker-compose",
        "/var/lib/docker/volumes",
    ]

    # Add home directory if it exists
    home = os.path.expanduser("~")
    if home and os.path.isdir(home):
        default_paths.append(home)

    # Add optional paths if they exist (NAS systems, common mount points)
    optional_paths = ["/stacks", "/docker", "/mnt", "/data", "/compose"]
    for p in optional_paths:
        if os.path.isdir(p):
            default_paths.append(p)

    # Merge user paths with defaults
    paths_to_scan = list(default_paths)
    if request and request.paths:
        seen = set(paths_to_scan)
        for p in request.paths:
            if p not in seen:
                paths_to_scan.append(p)
                seen.add(p)

    max_depth = request.max_depth if request else 5
    compose_filenames = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
    compose_files = []

    for base_path in paths_to_scan:
        # Security: Skip unsafe paths
        if not _is_path_safe(base_path):
            logger.warning(f"Skipping unsafe path: {base_path}")
            continue

        if not os.path.isdir(base_path):
            continue

        try:
            for root, dirs, files in os.walk(base_path, followlinks=False):
                # Check depth
                depth = root[len(base_path):].count(os.sep)
                if depth >= max_depth:
                    dirs.clear()  # Don't recurse further
                    continue

                for filename in files:
                    if filename.lower() in compose_filenames:
                        filepath = os.path.join(root, filename)
                        try:
                            stat = os.stat(filepath)
                            # Read file to extract project name and services
                            project_name = os.path.basename(root)
                            services = []
                            try:
                                with open(filepath, 'r') as f:
                                    content = yaml.safe_load(f)
                                    if content:
                                        if 'name' in content:
                                            project_name = content['name']
                                        if 'services' in content and isinstance(content['services'], dict):
                                            services = list(content['services'].keys())
                            except Exception:
                                pass  # Use defaults if parsing fails

                            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                            compose_files.append(ComposeFileInfo(
                                path=filepath,
                                project_name=project_name,
                                services=services,
                                size=stat.st_size,
                                modified=modified.isoformat() + 'Z'
                            ))
                        except (OSError, IOError):
                            continue
        except (OSError, IOError):
            continue

    logger.info(f"Found {len(compose_files)} compose files on localhost")
    return ScanComposeDirsResponse(success=True, compose_files=compose_files)


async def _scan_agent_dirs(host_id: str, request: Optional[ScanComposeDirsRequest]) -> ScanComposeDirsResponse:
    """Scan directories on an agent host via WebSocket command."""
    # Get agent ID for this host
    agent_manager = AgentManager()
    agent_id = agent_manager.get_agent_for_host(host_id)
    if not agent_id:
        raise HTTPException(
            status_code=503,
            detail="No agent connected for this host"
        )

    # Build scan command
    command = {
        "type": "command",
        "command": "scan_compose_dirs",
        "payload": {
            "paths": request.paths if request else None,
            "recursive": request.recursive if request else True,
            "max_depth": request.max_depth if request else 5,
        }
    }

    # Execute command on agent
    executor = get_agent_command_executor()
    retry_policy = RetryPolicy(max_attempts=1, initial_delay=1.0)

    result = await executor.execute_command(
        agent_id,
        command,
        timeout=60.0,  # 1 minute timeout for directory scan
        retry_policy=retry_policy
    )

    if not result.success:
        logger.error(f"Scan compose dirs failed for host {host_id}: {result.error}")
        return ScanComposeDirsResponse(
            success=False,
            compose_files=[],
            error=result.error or "Scan failed"
        )

    # Parse response
    response_data = result.response or {}
    compose_files = []

    # Handle null compose_files from Go (nil slice marshals to null, not [])
    for file_info in (response_data.get("compose_files") or []):
        # Convert modified timestamp to ISO format
        modified = file_info.get("modified", "")
        if isinstance(modified, str) and not modified.endswith("Z"):
            modified = modified + "Z"

        compose_files.append(ComposeFileInfo(
            path=file_info.get("path", ""),
            project_name=file_info.get("project_name", ""),
            services=file_info.get("services", []),
            size=file_info.get("size", 0),
            modified=modified
        ))

    logger.info(f"Found {len(compose_files)} compose files on host {host_id}")

    return ScanComposeDirsResponse(
        success=True,
        compose_files=compose_files
    )


# ==================== Read Compose File Endpoint ====================

@router.post("/read-compose-file/{host_id}", response_model=ReadComposeFileResponse)
async def read_compose_file(
    host_id: str,
    request: ReadComposeFileRequest,
    current_user=Depends(get_current_user),
):
    """
    Read a compose file's content from a host.

    Returns the compose file content and optional .env content if present
    in the same directory. Works with local and agent-based hosts.
    """
    # Validate host exists
    db = get_database_manager()
    with db.get_session() as session:
        host = session.query(DockerHostDB).filter_by(id=host_id).first()
        if not host:
            raise HTTPException(status_code=404, detail="Host not found")

        connection_type = host.connection_type

    # Route based on connection type
    if connection_type == 'local':
        return await _read_local_file(request)
    elif connection_type == 'agent':
        return await _read_agent_file(host_id, request)
    else:
        raise HTTPException(
            status_code=400,
            detail="File reading is only available for local and agent-based hosts"
        )


async def _read_local_file(request: ReadComposeFileRequest) -> ReadComposeFileResponse:
    """Read a compose file from the local filesystem (within DockMon container)."""
    path = request.path

    # Security: Validate path is absolute
    if not os.path.isabs(path):
        return ReadComposeFileResponse(
            success=False,
            path=path,
            error="Path must be absolute"
        )

    # Security: Check path is safe (resolves symlinks, blocks system dirs)
    if not _is_path_safe(path):
        return ReadComposeFileResponse(
            success=False,
            path=path,
            error="Path not allowed"
        )

    # Security: Validate it's a compose file
    compose_filenames = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
    if os.path.basename(path).lower() not in compose_filenames:
        return ReadComposeFileResponse(
            success=False,
            path=path,
            error="Not a compose file"
        )

    # Check file exists
    if not os.path.isfile(path):
        return ReadComposeFileResponse(
            success=False,
            path=path,
            error="File not found"
        )

    try:
        # Read compose file
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for .env file in same directory
        env_content = None
        env_path = os.path.join(os.path.dirname(path), '.env')
        if os.path.isfile(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    env_content = f.read()
            except (OSError, IOError):
                pass  # .env is optional

        logger.info(f"Read compose file from localhost: {path}")

        return ReadComposeFileResponse(
            success=True,
            path=path,
            content=content,
            env_content=env_content
        )

    except (OSError, IOError) as e:
        logger.error(f"Failed to read file {path}: {e}")
        return ReadComposeFileResponse(
            success=False,
            path=path,
            error=f"Failed to read file: {e}"
        )


async def _read_agent_file(host_id: str, request: ReadComposeFileRequest) -> ReadComposeFileResponse:
    """Read a compose file from an agent host via WebSocket command."""
    # Get agent ID for this host
    agent_manager = AgentManager()
    agent_id = agent_manager.get_agent_for_host(host_id)
    if not agent_id:
        raise HTTPException(
            status_code=503,
            detail="No agent connected for this host"
        )

    # Build read command
    command = {
        "type": "command",
        "command": "read_compose_file",
        "payload": {
            "path": request.path,
        }
    }

    # Execute command on agent
    executor = get_agent_command_executor()
    retry_policy = RetryPolicy(max_attempts=1, initial_delay=1.0)

    result = await executor.execute_command(
        agent_id,
        command,
        timeout=30.0,  # 30 second timeout for file read
        retry_policy=retry_policy
    )

    if not result.success:
        logger.error(f"Read compose file failed for host {host_id}: {result.error}")
        return ReadComposeFileResponse(
            success=False,
            path=request.path,
            error=result.error or "Read failed"
        )

    # Parse response
    response_data = result.response or {}

    if not response_data.get("success", False):
        return ReadComposeFileResponse(
            success=False,
            path=request.path,
            error=response_data.get("error", "Unknown error")
        )

    logger.info(f"Read compose file from host {host_id}: {request.path}")

    return ReadComposeFileResponse(
        success=True,
        path=request.path,
        content=response_data.get("content"),
        env_content=response_data.get("env_content")
    )


def _link_containers_for_host(
    session: Session,
    containers: List[dict],
    host_id: str,
    deployment_id: str
) -> int:
    """
    Link containers to a deployment via DeploymentMetadata.

    Returns count of containers linked.
    """
    linked_count = 0

    for container in containers:
        labels = getattr(container, 'labels', {}) or {}

        # CRITICAL: Use SHORT ID (12 chars) and composite key
        container_id = getattr(container, 'id', '') or ''
        short_id = container_id[:12]
        composite_key = f"{host_id}:{short_id}"

        # Check if metadata already exists
        existing = session.query(DeploymentMetadata).filter_by(
            container_id=composite_key
        ).first()

        if existing:
            # Update existing metadata to link to this deployment
            existing.deployment_id = deployment_id
            existing.is_managed = True
            existing.service_name = labels.get('com.docker.compose.service')
        else:
            # Create new metadata record
            metadata = DeploymentMetadata(
                container_id=composite_key,
                host_id=host_id,
                deployment_id=deployment_id,
                is_managed=True,
                service_name=labels.get('com.docker.compose.service'),
            )
            session.add(metadata)

        linked_count += 1

    return linked_count


# ==================== Helper Functions ====================

def _deployment_to_response(deployment: Deployment, existing_session=None) -> DeploymentResponse:
    """Convert deployment model to response (v2.2.7+).

    Args:
        deployment: The deployment model to convert
        existing_session: Optional existing session to use (avoids DetachedInstanceError)
    """
    # Get current container IDs from deployment_metadata
    # These are kept up-to-date when containers are recreated during updates
    container_ids = []

    # Query deployment_metadata for containers linked to this deployment
    # Use existing session if provided to avoid DetachedInstanceError
    if existing_session:
        metadata_records = existing_session.query(DeploymentMetadata).filter_by(deployment_id=deployment.id).all()
    else:
        db = get_database_manager()
        with db.get_session() as session:
            metadata_records = session.query(DeploymentMetadata).filter_by(deployment_id=deployment.id).all()

    for record in metadata_records:
        # Extract SHORT container ID (12 chars) from composite key
        try:
            _, container_id = parse_composite_key(record.container_id)
            container_ids.append(container_id)
        except ValueError:
            # Invalid composite key format, skip
            logger.warning(f"Failed to parse composite key: {record.container_id}")
            pass

    return DeploymentResponse(
        id=deployment.id,
        host_id=deployment.host_id,
        stack_name=deployment.stack_name,
        status=deployment.status,
        progress_percent=deployment.progress_percent,
        current_stage=deployment.current_stage,
        error_message=deployment.error_message,
        created_at=deployment.created_at.isoformat() + 'Z' if deployment.created_at else None,
        started_at=deployment.started_at.isoformat() + 'Z' if deployment.started_at else None,
        completed_at=deployment.completed_at.isoformat() + 'Z' if deployment.completed_at else None,
        created_by=deployment.created_by,
        committed=deployment.committed,
        rollback_on_failure=deployment.rollback_on_failure,
        updated_at=deployment.updated_at.isoformat() + 'Z' if deployment.updated_at else None,
        host_name=deployment.host.name if deployment.host and deployment.host.name else None,
        container_ids=container_ids if container_ids else None,
    )
