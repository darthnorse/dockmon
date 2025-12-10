"""
Deployment API routes for DockMon v2.1

Provides REST endpoints for:
- Creating and executing container/stack deployments
- Managing deployment templates
- Tracking deployment progress
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from database import Deployment, DeploymentTemplate, DatabaseManager, GlobalSettings, DeploymentMetadata
from deployment import DeploymentExecutor, TemplateManager, SecurityException, SecurityValidator
from auth.api_key_auth import get_current_user_or_api_key as get_current_user, require_scope
from utils.keys import parse_composite_key

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/deployments", tags=["deployments"])
template_router = APIRouter(prefix="/api/templates", tags=["templates"])


# ==================== Request/Response Models ====================

class DeploymentCreate(BaseModel):
    """Create deployment request."""
    host_id: str = Field(..., description="UUID of the Docker host to deploy to")
    name: str = Field(..., description="Human-readable name for the deployment")
    deployment_type: str = Field(..., description="Type of deployment: 'container' or 'stack'")
    definition: Dict[str, Any] = Field(
        ...,
        description="Deployment configuration. For stacks: must include 'compose_yaml' field with Docker Compose YAML as string. For containers: include image, ports, volumes, etc."
    )
    rollback_on_failure: bool = Field(
        True,
        description="Automatically rollback if deployment fails (default: true)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "host_id": "86a10392-2289-409f-899d-5f5c799086da",
                "name": "my-nginx-stack",
                "deployment_type": "stack",
                "definition": {
                    "compose_yaml": "services:\n  web:\n    image: nginx:alpine\n    ports:\n      - 80:80"
                },
                "rollback_on_failure": True
            }
        }
    )


class DeploymentUpdate(BaseModel):
    """Update deployment request."""
    definition: Dict[str, Any]
    name: Optional[str] = None
    deployment_type: Optional[str] = None
    host_id: Optional[str] = None


class DeploymentResponse(BaseModel):
    """Deployment response."""
    id: str
    host_id: str
    name: str
    deployment_type: str
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
    definition: Optional[Dict[str, Any]] = None
    updated_at: Optional[str] = None
    host_name: Optional[str] = None
    container_ids: Optional[List[str]] = None  # List of SHORT container IDs (12 chars) from deployment_metadata


class TemplateCreate(BaseModel):
    """Create template request."""
    name: str = Field(..., description="Template name (must be unique)")
    deployment_type: str = Field(..., description="Type: 'container' or 'stack'")
    template_definition: Dict[str, Any] = Field(
        ...,
        description="Template definition with optional variables like ${VAR_NAME}"
    )
    category: Optional[str] = Field(None, description="Category for organization (e.g., 'media', 'networking')")
    description: Optional[str] = Field(None, description="Human-readable description of what this template does")
    variables: Optional[Dict[str, Any]] = Field(
        None,
        description="Variable definitions with defaults. Example: {'APP_PORT': '8080', 'APP_IMAGE': 'nginx:alpine'}"
    )


class TemplateUpdate(BaseModel):
    """Update template request."""
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    template_definition: Optional[Dict[str, Any]] = None
    variables: Optional[Dict[str, Any]] = None


class TemplateRenderRequest(BaseModel):
    """Render template request."""
    values: Dict[str, Any] = Field(
        ...,
        description="Variable values to substitute. Example: {'APP_PORT': '3000', 'APP_IMAGE': 'nginx:1.25'}"
    )


class SaveAsTemplateRequest(BaseModel):
    """Request to save deployment as reusable template."""
    name: str = Field(..., description="Template name (must be unique)")
    category: Optional[str] = Field(None, description="Category for organization")
    description: Optional[str] = Field(None, description="Template description")


# ==================== Dependency Injection ====================

# These will be set by main.py during startup
_deployment_executor: Optional[DeploymentExecutor] = None
_template_manager: Optional[TemplateManager] = None
_database_manager: Optional[DatabaseManager] = None


def set_deployment_executor(executor: DeploymentExecutor):
    """Set deployment executor instance (called from main.py)."""
    global _deployment_executor
    _deployment_executor = executor


def set_template_manager(manager: TemplateManager):
    """Set template manager instance (called from main.py)."""
    global _template_manager
    _template_manager = manager


def set_database_manager(db: DatabaseManager):
    """Set database manager instance (called from main.py)."""
    global _database_manager
    _database_manager = db


def get_deployment_executor() -> DeploymentExecutor:
    """Get deployment executor (dependency)."""
    if _deployment_executor is None:
        raise RuntimeError("DeploymentExecutor not initialized")
    return _deployment_executor


def get_template_manager() -> TemplateManager:
    """Get template manager (dependency)."""
    if _template_manager is None:
        raise RuntimeError("TemplateManager not initialized")
    return _template_manager


def get_database_manager() -> DatabaseManager:
    """Get database manager (dependency)."""
    if _database_manager is None:
        raise RuntimeError("DatabaseManager not initialized")
    return _database_manager


# ==================== Deployment Endpoints ====================

@router.post("", response_model=DeploymentResponse, status_code=201, dependencies=[Depends(require_scope("write"))])
async def create_deployment(
    request: DeploymentCreate,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    executor: DeploymentExecutor = Depends(get_deployment_executor)
):
    """
    Create a new deployment.

    Creates a deployment in 'planning' state. Call /deployments/{id}/execute to start it.

    **For Stack Deployments (Docker Compose):**
    - Set `deployment_type: "stack"`
    - Include `compose_yaml` in definition with Docker Compose YAML as a string
    - Use `\\n` for newlines in the YAML string

    **Example - Simple Stack:**
    ```json
    {
      "host_id": "your-host-id",
      "name": "nginx-redis",
      "deployment_type": "stack",
      "definition": {
        "compose_yaml": "services:\\n  web:\\n    image: nginx:alpine\\n  cache:\\n    image: redis:alpine"
      }
    }
    ```

    **Example - Stack with Variables:**
    ```json
    {
      "definition": {
        "compose_yaml": "services:\\n  app:\\n    image: ${APP_IMAGE}",
        "variables": {
          "APP_IMAGE": "nginx:1.25"
        }
      }
    }
    ```

    **For Container Deployments:**
    - Set `deployment_type: "container"`
    - Include container config directly in definition (image, ports, volumes, etc.)

    Security validation is performed before creation.
    """
    try:
        deployment_id = await executor.create_deployment(
            host_id=request.host_id,
            name=request.name,
            deployment_type=request.deployment_type,
            definition=request.definition,
            user_id=current_user['user_id'],
            rollback_on_failure=request.rollback_on_failure,
            created_by=current_user['username'],
        )

        # Fetch created deployment
        db = get_database_manager()
        with db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            return _deployment_to_response(deployment)

    except SecurityException as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create deployment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{deployment_id}/execute", response_model=DeploymentResponse, dependencies=[Depends(require_scope("write"))])
async def execute_deployment(
    deployment_id: str,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    executor: DeploymentExecutor = Depends(get_deployment_executor)
):
    """
    Execute a deployment (pull image, create container, start container).

    Deployment progress can be tracked via WebSocket events:
    - DEPLOYMENT_PROGRESS (real-time progress updates)
    - DEPLOYMENT_COMPLETED (success)
    - DEPLOYMENT_FAILED (error)
    - DEPLOYMENT_ROLLED_BACK (rollback after failure)
    """
    try:
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

            # Only allow execution from 'planning', 'failed', 'rolled_back', or 'partial' status
            # These are the states where a new execution attempt makes sense
            # In-progress states (validating, pulling_image, creating, starting) cannot be re-executed
            # Terminal success state (running) cannot be re-executed
            if deployment.status not in ('planning', 'failed', 'rolled_back', 'partial'):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot execute deployment in status '{deployment.status}'. Only 'planning', 'failed', 'rolled_back', or 'partial' deployments can be executed."
                )

            # Lock is held during this critical section - prevents other threads from modifying
            # Row lock is released when session closes (after this with block)

            # Execute deployment in background
            background_tasks.add_task(executor.execute_deployment, deployment_id)

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
    Update a deployment's definition (allowed in 'planning', 'failed', or 'rolled_back' states).

    This allows users to:
    - Review and modify deployment configuration before execution ('planning')
    - Edit and retry failed deployments ('failed')
    - Edit and retry rolled back deployments ('rolled_back')
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

            # Allow editing in 'planning', 'failed', 'rolled_back', or 'partial' states
            editable_statuses = ['planning', 'failed', 'rolled_back', 'partial']
            if deployment.status not in editable_statuses:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot edit deployment in status '{deployment.status}'. Only {editable_statuses} deployments can be edited."
                )

            # NOTE: Security validation removed - will be performed during execution
            # No need to validate on update since user is just editing configuration

            # If retrying a failed/rolled_back/partial deployment, reset error state and progress
            if deployment.status in ['failed', 'rolled_back', 'partial']:
                deployment.status = 'planning'  # Reset to planning for retry
                deployment.error_message = None  # Clear previous error
                deployment.progress_percent = 0  # Reset progress indicator
                logger.info(f"Deployment {deployment_id} being retried (was {deployment.status})")

            # Update fields if provided
            if request.name is not None:
                deployment.name = request.name
            if request.deployment_type is not None:
                deployment.deployment_type = request.deployment_type
            if request.host_id is not None:
                deployment.host_id = request.host_id

            # Update definition and timestamp
            deployment.definition = json.dumps(request.definition)
            deployment.updated_at = datetime.now(timezone.utc)

            # Commit changes
            session.commit()
            session.refresh(deployment)

            logger.info(f"Deployment {deployment_id} updated (name={deployment.name}, type={deployment.deployment_type})")
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


@router.post("/{deployment_id}/save-as-template", status_code=200, dependencies=[Depends(require_scope("write"))])
async def save_deployment_as_template(
    deployment_id: str,
    request: SaveAsTemplateRequest,
    current_user=Depends(get_current_user),
):
    """
    Convert a successful deployment into a reusable template.

    This allows users to save working configurations as templates for future deployments.

    Requirements:
    - Deployment must exist
    - Template name must be unique

    The endpoint:
    1. Fetches the deployment
    2. Extracts its configuration (definition JSON)
    3. Creates a new template with the same deployment type and definition
    4. Returns the created template ID

    This enables the workflow:
    1. User creates and tests a deployment
    2. User saves it as template: POST /api/deployments/{id}/save-as-template
    3. User can now deploy from template to other hosts
    """
    try:
        db = get_database_manager()

        with db.get_session() as session:
            # Fetch deployment
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()

            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

            # Check for duplicate template name
            existing = session.query(DeploymentTemplate).filter_by(name=request.name).first()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"Template with name '{request.name}' already exists"
                )

            # Generate template ID
            template_id = str(uuid.uuid4())

            # Use provided description or generate default
            description = request.description or f"Template created from deployment '{deployment.name}'"

            # Create template from deployment config
            template = DeploymentTemplate(
                id=template_id,
                name=request.name,
                category=request.category,
                description=description,
                deployment_type=deployment.deployment_type,
                template_definition=deployment.definition,
                variables=None,  # TODO: Add variable extraction from definition
                is_builtin=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            session.add(template)
            session.commit()

            logger.info(f"Created template '{template.name}' from deployment '{deployment.name}'")

            return {
                "id": template.id,
                "name": template.name,
                "category": template.category,
                "deployment_type": template.deployment_type
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save deployment as template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Template Endpoints ====================

@template_router.post("", status_code=201)
async def create_template(
    request: TemplateCreate,
    current_user=Depends(get_current_user),
    manager: TemplateManager = Depends(get_template_manager)
):
    """Create a new deployment template."""
    try:
        template_id = manager.create_template(
            name=request.name,
            deployment_type=request.deployment_type,
            template_definition=request.template_definition,
            category=request.category,
            description=request.description,
            variables=request.variables,
        )

        template = manager.get_template(template_id)
        return template

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@template_router.get("")
async def list_templates(
    category: Optional[str] = None,
    deployment_type: Optional[str] = None,
    include_builtin: bool = True,
    current_user=Depends(get_current_user),
    manager: TemplateManager = Depends(get_template_manager)
):
    """List deployment templates with optional filters."""
    try:
        templates = manager.list_templates(
            category=category,
            deployment_type=deployment_type,
            include_builtin=include_builtin
        )
        return templates

    except Exception as e:
        logger.error(f"Failed to list templates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@template_router.get("/{template_id}")
async def get_template(
    template_id: str,
    current_user=Depends(get_current_user),
    manager: TemplateManager = Depends(get_template_manager)
):
    """Get template by ID."""
    try:
        template = manager.get_template(template_id)

        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        return template

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@template_router.put("/{template_id}")
async def update_template(
    template_id: str,
    request: TemplateUpdate,
    current_user=Depends(get_current_user),
    manager: TemplateManager = Depends(get_template_manager)
):
    """Update template fields."""
    try:
        success = manager.update_template(
            template_id=template_id,
            name=request.name,
            category=request.category,
            description=request.description,
            template_definition=request.template_definition,
            variables=request.variables,
        )

        if not success:
            raise HTTPException(status_code=404, detail="Template not found")

        template = manager.get_template(template_id)
        return template

    except RuntimeError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@template_router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    current_user=Depends(get_current_user),
    manager: TemplateManager = Depends(get_template_manager)
):
    """Delete a template."""
    try:
        success = manager.delete_template(template_id)

        if not success:
            raise HTTPException(status_code=404, detail="Template not found")

        logger.info(f"Deleted template {template_id}")

        return {"success": True, "message": "Template deleted"}

    except RuntimeError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@template_router.post("/{template_id}/render")
async def render_template(
    template_id: str,
    request: TemplateRenderRequest,
    current_user=Depends(get_current_user),
    manager: TemplateManager = Depends(get_template_manager)
):
    """
    Render template with variable substitution.

    Replaces ${VAR_NAME} placeholders with provided values.
    Falls back to default values if not provided.

    Returns rendered container/stack configuration ready for deployment.
    """
    try:
        rendered = manager.render_template(template_id, request.values)
        return rendered

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to render template: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Helper Functions ====================

def _deployment_to_response(deployment: Deployment) -> DeploymentResponse:
    """Convert deployment model to response."""
    # Get current container IDs from deployment_metadata
    # These are kept up-to-date when containers are recreated during updates
    container_ids = []

    # Query deployment_metadata for containers linked to this deployment
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
        name=deployment.name,
        deployment_type=deployment.deployment_type,
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
        definition=json.loads(deployment.definition) if deployment.definition else None,
        updated_at=deployment.updated_at.isoformat() + 'Z' if deployment.updated_at else None,
        host_name=deployment.host.name if deployment.host and deployment.host.name else None,
        container_ids=container_ids if container_ids else None,
    )
