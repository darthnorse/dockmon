"""
Deployment API routes for DockMon v2.1

Provides REST endpoints for:
- Creating and executing container/stack deployments
- Managing deployment templates
- Tracking deployment progress
"""

import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Deployment, DatabaseManager
from deployment import DeploymentExecutor, TemplateManager, SecurityException
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
        # Execute deployment in background
        background_tasks.add_task(executor.execute_deployment, deployment_id)

        # Return current deployment state
        db = get_database_manager()
        with db.get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            if not deployment:
                raise HTTPException(status_code=404, detail="Deployment not found")

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

            # Prevent deletion of active deployments
            if deployment.status not in ('completed', 'failed', 'rolled_back'):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete deployment in status '{deployment.status}'"
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
    )
