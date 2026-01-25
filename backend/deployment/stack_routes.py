"""
Stacks API routes for DockMon v2.2.7+

Provides REST endpoints for filesystem-based stack management:
- List stacks with deployed_to info (derived from container labels)
- Create, read, update, delete stacks
- Rename and copy stacks

Note: "Deployed to" information is derived from running containers with
com.docker.compose.project labels, not from database records.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from auth.api_key_auth import get_current_user_or_api_key as get_current_user, require_capability, check_auth_capability, Capabilities
from database import DatabaseManager, StackMetadata
from deployment import stack_storage
from deployment.container_utils import scan_deployed_stacks
from deployment.routes import get_docker_monitor
from security.rate_limiting import rate_limit_stacks
from utils.response_filtering import filter_stack_env_content

# Database manager for audit tracking (v2.3.0+)
_db_manager = None


def get_db_manager():
    """Get or create singleton DatabaseManager for audit tracking."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/stacks", tags=["stacks"])


# ==================== Request/Response Models ====================

class StackCreate(BaseModel):
    """Create stack request."""
    name: str = Field(
        ...,
        description="Stack name (lowercase alphanumeric, hyphens, underscores)",
        min_length=1,
        max_length=100,
    )
    compose_yaml: str = Field(
        ...,
        description="Docker Compose YAML content",
    )
    env_content: Optional[str] = Field(
        None,
        description="Optional .env file content",
    )


class StackUpdate(BaseModel):
    """Update stack request."""
    compose_yaml: str = Field(
        ...,
        description="Docker Compose YAML content",
    )
    env_content: Optional[str] = Field(
        None,
        description="Optional .env file content (None to remove)",
    )


class StackRename(BaseModel):
    """Rename stack request."""
    new_name: str = Field(
        ...,
        description="New stack name",
        min_length=1,
        max_length=100,
    )


class StackCopy(BaseModel):
    """Copy stack request."""
    dest_name: str = Field(
        ...,
        description="Destination stack name",
        min_length=1,
        max_length=100,
    )


class DeployedHost(BaseModel):
    """Host where a stack is deployed."""
    host_id: str
    host_name: str


class StackListItem(BaseModel):
    """Stack list item (without content)."""
    name: str
    deployed_to: List[DeployedHost] = Field(
        default_factory=list,
        description="Hosts where this stack is running (from container labels)",
    )


class StackResponse(BaseModel):
    """Stack response with content."""
    name: str
    deployed_to: List[DeployedHost] = Field(default_factory=list)
    compose_yaml: Optional[str] = None
    env_content: Optional[str] = None


# ==================== Endpoints ====================

@router.get("", response_model=List[StackListItem], dependencies=[Depends(require_capability("stacks.view"))])
async def list_stacks(user=Depends(get_current_user)):
    """
    List all stacks with deployed_to information.

    Returns stacks from filesystem. The deployed_to field shows which hosts
    have running containers for each stack (derived from container labels).
    """
    # Get all stacks from filesystem
    stack_names = await stack_storage.list_stacks()

    if not stack_names:
        return []

    # Scan containers to find where stacks are deployed
    monitor = get_docker_monitor()
    all_containers = monitor.get_last_containers()
    deployed_stacks = scan_deployed_stacks(all_containers)

    # Build response
    result = []
    for name in stack_names:
        deployed_to = []
        if name in deployed_stacks:
            deployed_to = [
                DeployedHost(host_id=h.host_id, host_name=h.host_name)
                for h in deployed_stacks[name].hosts
            ]
        result.append(StackListItem(name=name, deployed_to=deployed_to))

    return result


@router.get("/{name}", response_model=StackResponse, dependencies=[Depends(require_capability("stacks.view"))])
async def get_stack(name: str, user=Depends(get_current_user)):
    """
    Get a stack by name with its content.

    Returns compose.yaml and .env content along with deployed_to info.
    Note: .env content is filtered out for users without stacks.view_env capability (v2.3.0+).
    """
    # Check if stack exists
    if not await stack_storage.stack_exists(name):
        raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")

    # Read stack content
    compose_yaml, env_content = await stack_storage.read_stack(name)

    # Get deployed_to info from containers
    monitor = get_docker_monitor()
    all_containers = monitor.get_last_containers()
    deployed_stacks = scan_deployed_stacks(all_containers)

    deployed_to = []
    if name in deployed_stacks:
        deployed_to = [
            DeployedHost(host_id=h.host_id, host_name=h.host_name)
            for h in deployed_stacks[name].hosts
        ]

    # Filter env_content for users without stacks.view_env capability
    can_view_env = check_auth_capability(user, Capabilities.STACKS_VIEW_ENV)

    return StackResponse(
        name=name,
        deployed_to=deployed_to,
        compose_yaml=compose_yaml,
        env_content=filter_stack_env_content(env_content, can_view_env),
    )


@router.post("", response_model=StackResponse, status_code=201, dependencies=[rate_limit_stacks, Depends(require_capability("stacks.edit"))])
async def create_stack(request: StackCreate, user=Depends(get_current_user)):
    """
    Create a new stack.

    Creates stack directory with compose.yaml and optional .env file.
    Stack name must be lowercase alphanumeric with hyphens/underscores.
    """
    try:
        await stack_storage.write_stack(
            name=request.name,
            compose_yaml=request.compose_yaml,
            env_content=request.env_content,
            create_only=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Track created_by in StackMetadata (v2.3.0+)
    user_id = user.get("user_id")
    db = get_db_manager()
    with db.get_session() as session:
        metadata = StackMetadata(
            stack_name=request.name,
            created_by=user_id,
            updated_by=user_id
        )
        session.add(metadata)
        session.commit()

    logger.info(f"User {user['username']} created stack '{request.name}'")

    return StackResponse(
        name=request.name,
        deployed_to=[],
        compose_yaml=request.compose_yaml,
        env_content=request.env_content,
    )


@router.put("/{name}", response_model=StackResponse, dependencies=[rate_limit_stacks, Depends(require_capability("stacks.edit"))])
async def update_stack(name: str, request: StackUpdate, user=Depends(get_current_user)):
    """
    Update a stack's content.

    Overwrites compose.yaml and .env files.
    """
    # Check if stack exists
    if not await stack_storage.stack_exists(name):
        raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")

    try:
        await stack_storage.write_stack(
            name=name,
            compose_yaml=request.compose_yaml,
            env_content=request.env_content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Track updated_by in StackMetadata (v2.3.0+)
    user_id = user.get("user_id")
    db = get_db_manager()
    with db.get_session() as session:
        metadata = session.query(StackMetadata).filter_by(stack_name=name).first()
        if metadata:
            metadata.updated_by = user_id
            metadata.updated_at = datetime.now(timezone.utc)
        else:
            # Create metadata if it doesn't exist (for pre-v2.3.0 stacks)
            metadata = StackMetadata(
                stack_name=name,
                created_by=user_id,
                updated_by=user_id
            )
            session.add(metadata)
        session.commit()

    # Get deployed_to info from containers
    monitor = get_docker_monitor()
    all_containers = monitor.get_last_containers()
    deployed_stacks = scan_deployed_stacks(all_containers)

    deployed_to = []
    if name in deployed_stacks:
        deployed_to = [
            DeployedHost(host_id=h.host_id, host_name=h.host_name)
            for h in deployed_stacks[name].hosts
        ]

    logger.info(f"User {user['username']} updated stack '{name}'")

    return StackResponse(
        name=name,
        deployed_to=deployed_to,
        compose_yaml=request.compose_yaml,
        env_content=request.env_content,
    )


@router.put("/{name}/rename", response_model=StackResponse, dependencies=[rate_limit_stacks, Depends(require_capability("stacks.edit"))])
async def rename_stack(name: str, request: StackRename, user=Depends(get_current_user)):
    """
    Rename a stack.

    Renames the stack directory on filesystem.
    Note: Running containers will still have the old project name in their labels.
    """
    # Validate new name
    stack_storage.validate_stack_name(request.new_name)

    # Check source exists
    if not await stack_storage.stack_exists(name):
        raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")

    # Check dest doesn't exist
    if await stack_storage.stack_exists(request.new_name):
        raise HTTPException(status_code=400, detail=f"Stack '{request.new_name}' already exists")

    try:
        await stack_storage.rename_stack_files(name, request.new_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename stack: {e}")

    # Update StackMetadata - since stack_name is PK, delete old and create new (v2.3.0+)
    user_id = user.get("user_id")
    db = get_db_manager()
    with db.get_session() as session:
        old_metadata = session.query(StackMetadata).filter_by(stack_name=name).first()
        if old_metadata:
            # Preserve original created_by and created_at
            new_metadata = StackMetadata(
                stack_name=request.new_name,
                created_by=old_metadata.created_by,
                updated_by=user_id,
                created_at=old_metadata.created_at,
                updated_at=datetime.now(timezone.utc)
            )
            session.delete(old_metadata)
            session.add(new_metadata)
        else:
            # Create metadata if it doesn't exist (for pre-v2.3.0 stacks)
            new_metadata = StackMetadata(
                stack_name=request.new_name,
                created_by=user_id,
                updated_by=user_id
            )
            session.add(new_metadata)
        session.commit()

    # Read content for response
    compose_yaml, env_content = await stack_storage.read_stack(request.new_name)

    # Filter env_content for users without stacks.view_env capability
    can_view_env = check_auth_capability(user, Capabilities.STACKS_VIEW_ENV)

    logger.info(f"User {user.get('username', 'unknown')} renamed stack '{name}' to '{request.new_name}'")

    # New stack has no deployed containers (they still have old name in labels)
    return StackResponse(
        name=request.new_name,
        deployed_to=[],
        compose_yaml=compose_yaml,
        env_content=filter_stack_env_content(env_content, can_view_env),
    )


@router.delete("/{name}", status_code=204, dependencies=[rate_limit_stacks, Depends(require_capability("stacks.edit"))])
async def delete_stack(name: str, user=Depends(get_current_user)):
    """
    Delete a stack from filesystem.

    This only removes the stack files (compose.yaml, .env).
    Running containers are NOT affected - they will continue running.
    """
    # Check if stack exists
    if not await stack_storage.stack_exists(name):
        raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")

    try:
        await stack_storage.delete_stack_files(name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete stack: {e}")

    # Delete StackMetadata (v2.3.0+)
    db = get_db_manager()
    with db.get_session() as session:
        session.query(StackMetadata).filter_by(stack_name=name).delete()
        session.commit()

    logger.info(f"User {user['username']} deleted stack '{name}'")


@router.post("/{name}/copy", response_model=StackResponse, status_code=201, dependencies=[rate_limit_stacks, Depends(require_capability("stacks.edit"))])
async def copy_stack_endpoint(name: str, request: StackCopy, user=Depends(get_current_user)):
    """
    Copy a stack to a new name.

    Creates a copy of the stack with a new name.
    """
    try:
        await stack_storage.copy_stack(name, request.dest_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create StackMetadata for the copied stack (v2.3.0+)
    user_id = user.get("user_id")
    db = get_db_manager()
    with db.get_session() as session:
        metadata = StackMetadata(
            stack_name=request.dest_name,
            created_by=user_id,
            updated_by=user_id
        )
        session.add(metadata)
        session.commit()

    # Read content for response
    compose_yaml, env_content = await stack_storage.read_stack(request.dest_name)

    # Filter env_content for users without stacks.view_env capability
    can_view_env = check_auth_capability(user, Capabilities.STACKS_VIEW_ENV)

    logger.info(f"User {user.get('username', 'unknown')} copied stack '{name}' to '{request.dest_name}'")

    return StackResponse(
        name=request.dest_name,
        deployed_to=[],
        compose_yaml=compose_yaml,
        env_content=filter_stack_env_content(env_content, can_view_env),
    )
