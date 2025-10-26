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
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Deployment, DeploymentTemplate, DatabaseManager, GlobalSettings
from deployment import DeploymentExecutor, TemplateManager, SecurityException, SecurityValidator
from auth.v2_routes import get_current_user

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/deployments", tags=["deployments"])
template_router = APIRouter(prefix="/api/templates", tags=["templates"])


# ==================== Request/Response Models ====================

class DeploymentCreate(BaseModel):
    """Create deployment request."""
    host_id: str
    name: str
    deployment_type: str  # 'container' or 'stack'
    definition: Dict[str, Any]
    rollback_on_failure: bool = True


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
    committed: bool
    rollback_on_failure: bool
    definition: Optional[Dict[str, Any]] = None
    updated_at: Optional[str] = None
    host_name: Optional[str] = None
    container_ids: Optional[List[str]] = None  # List of SHORT container IDs (12 chars) from deployment_metadata


class TemplateCreate(BaseModel):
    """Create template request."""
    name: str
    deployment_type: str
    template_definition: Dict[str, Any]
    category: Optional[str] = None
    description: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None


class TemplateUpdate(BaseModel):
    """Update template request."""
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    template_definition: Optional[Dict[str, Any]] = None
    variables: Optional[Dict[str, Any]] = None


class TemplateRenderRequest(BaseModel):
    """Render template request."""
    values: Dict[str, Any]


class SaveAsTemplateRequest(BaseModel):
    """Request to save deployment as reusable template."""
    name: str
    category: Optional[str] = None
    description: Optional[str] = None


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

@router.post("", response_model=DeploymentResponse, status_code=201)
async def create_deployment(
    request: DeploymentCreate,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    executor: DeploymentExecutor = Depends(get_deployment_executor)
):
    """
    Create a new deployment.

    Security validation is performed before creation.
    Deployment will be in 'planning' state initially.
    Use /deployments/{id}/execute to start deployment.
    """
    try:
        deployment_id = await executor.create_deployment(
            host_id=request.host_id,
            name=request.name,
            deployment_type=request.deployment_type,
            definition=request.definition,
            rollback_on_failure=request.rollback_on_failure,
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


@router.post("/{deployment_id}/execute", response_model=DeploymentResponse)
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
        # Check deployment status before executing
        db = get_database_manager()
        with db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

            # Only allow execution from 'planning' status
            # Terminal states (completed, failed, rolled_back) cannot be re-executed
            if deployment.status != 'planning':
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot execute deployment in status '{deployment.status}'. Only 'planning' deployments can be executed."
                )

        # Execute deployment in background
        background_tasks.add_task(executor.execute_deployment, deployment_id)

        # Return updated deployment state
        with db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            return _deployment_to_response(deployment)

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
    current_user=Depends(get_current_user),
):
    """
    List deployments with optional filters.

    Filters:
    - host_id: Filter by host
    - status: Filter by status (planning, executing, completed, failed, rolled_back)
    - limit: Max results (default: 100)
    """
    try:
        db = get_database_manager()
        with db.get_session() as session:
            query = session.query(Deployment)

            if host_id:
                query = query.filter_by(host_id=host_id)

            if status:
                query = query.filter_by(status=status)

            deployments = query.order_by(Deployment.created_at.desc()).limit(limit).all()

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
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()

            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

            return _deployment_to_response(deployment)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deployment: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{deployment_id}", response_model=DeploymentResponse)
async def update_deployment(
    deployment_id: str,
    request: DeploymentUpdate,
    current_user=Depends(get_current_user),
):
    """
    Update a deployment's definition (only allowed in 'planning' state).

    This allows users to review and modify deployment configuration
    before execution.
    """
    try:
        db = get_database_manager()
        security_validator = SecurityValidator()

        with db.get_session() as session:
            # Fetch deployment
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

            # Only allow editing in 'planning' state
            if deployment.status != 'planning':
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot edit deployment in status '{deployment.status}'. Only 'planning' deployments can be edited."
                )

            # NOTE: Security validation removed - will be performed during execution
            # No need to validate on update since user is just editing configuration

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


@router.delete("/{deployment_id}")
async def delete_deployment(
    deployment_id: str,
    current_user=Depends(get_current_user),
):
    """
    Delete a deployment record.

    Only deletes the deployment record, does not affect created containers.
    Can only delete deployments in terminal states (completed, failed, rolled_back).
    """
    try:
        db = get_database_manager()
        with db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()

            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

            # Prevent deletion of EXECUTING deployments only
            # Allow deletion of: planning, completed, failed, rolled_back
            if deployment.status == 'executing':
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


@router.post("/{deployment_id}/save-as-template", status_code=200)
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
    from database import DeploymentMetadata
    from utils.keys import parse_composite_key

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
        committed=deployment.committed,
        rollback_on_failure=deployment.rollback_on_failure,
        definition=json.loads(deployment.definition) if deployment.definition else None,
        updated_at=deployment.updated_at.isoformat() + 'Z' if deployment.updated_at else None,
        host_name=deployment.host.name if deployment.host and deployment.host.name else None,
        container_ids=container_ids if container_ids else None,
    )
