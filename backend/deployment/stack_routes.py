"""
Stacks API routes for DockMon v2.2.7+

Provides REST endpoints for filesystem-based stack management:
- List stacks with deployment counts
- Create, read, update, delete stacks
- Rename and copy stacks
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from database import DatabaseManager
from auth.api_key_auth import get_current_user_or_api_key as get_current_user
from deployment import stack_service
from security.rate_limiting import rate_limit_stacks

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/stacks", tags=["stacks"])

# Database manager instance
db = DatabaseManager()


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


class StackResponse(BaseModel):
    """Stack response."""
    name: str
    deployment_count: int
    compose_yaml: Optional[str] = None
    env_content: Optional[str] = None

    @classmethod
    def from_stack_info(cls, stack: "stack_service.StackInfo") -> "StackResponse":
        """Create response from StackInfo."""
        return cls(**stack.to_dict())


class StackListItem(BaseModel):
    """Stack list item (without content)."""
    name: str
    deployment_count: int


# ==================== Endpoints ====================

@router.get("", response_model=list[StackListItem])
async def list_stacks(user=Depends(get_current_user)):
    """
    List all stacks with deployment counts.

    Returns stacks from filesystem with count of deployments referencing each.
    """
    with db.get_session() as session:
        stacks = await stack_service.list_stacks_with_counts(session)
        return [StackListItem(name=s.name, deployment_count=s.deployment_count) for s in stacks]


@router.get("/{name}", response_model=StackResponse)
async def get_stack(name: str, user=Depends(get_current_user)):
    """
    Get a stack by name with its content.

    Returns compose.yaml and .env content along with deployment count.
    """
    with db.get_session() as session:
        stack = await stack_service.get_stack(session, name)

    if stack is None:
        raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")

    return StackResponse.from_stack_info(stack)


@router.post("", response_model=StackResponse, status_code=201, dependencies=[rate_limit_stacks])
async def create_stack(request: StackCreate, user=Depends(get_current_user)):
    """
    Create a new stack.

    Creates stack directory with compose.yaml and optional .env file.
    Stack name must be lowercase alphanumeric with hyphens/underscores.
    """
    try:
        stack = await stack_service.create_stack(
            name=request.name,
            compose_yaml=request.compose_yaml,
            env_content=request.env_content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"User {user.username} created stack '{request.name}'")

    return StackResponse.from_stack_info(stack)


@router.put("/{name}", response_model=StackResponse, dependencies=[rate_limit_stacks])
async def update_stack(name: str, request: StackUpdate, user=Depends(get_current_user)):
    """
    Update a stack's content.

    Overwrites compose.yaml and .env files.
    """
    try:
        stack = await stack_service.update_stack(
            name=name,
            compose_yaml=request.compose_yaml,
            env_content=request.env_content,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Get deployment count for response
    with db.get_session() as session:
        stack.deployment_count = stack_service.get_deployment_count(session, name)

    logger.info(f"User {user.username} updated stack '{name}'")

    return StackResponse.from_stack_info(stack)


@router.put("/{name}/rename", response_model=StackResponse, dependencies=[rate_limit_stacks])
async def rename_stack(name: str, request: StackRename, user=Depends(get_current_user)):
    """
    Rename a stack.

    Renames the stack directory and updates all deployment references.
    Returns the renamed stack with its content for API symmetry.
    """
    with db.get_session() as session:
        try:
            stack = await stack_service.rename_stack(session, name, request.new_name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"User {user.username} renamed stack '{name}' to '{request.new_name}'")

    return StackResponse.from_stack_info(stack)


@router.delete("/{name}", status_code=204, dependencies=[rate_limit_stacks])
async def delete_stack(name: str, user=Depends(get_current_user)):
    """
    Delete a stack.

    Only allowed if no deployments reference the stack.
    Delete deployments first before deleting the stack.
    """
    with db.get_session() as session:
        try:
            await stack_service.delete_stack(session, name)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")
        except ValueError as e:
            # Stack has active deployments
            raise HTTPException(status_code=409, detail=str(e))

    logger.info(f"User {user.username} deleted stack '{name}'")


@router.post("/{name}/copy", response_model=StackResponse, status_code=201, dependencies=[rate_limit_stacks])
async def copy_stack_endpoint(name: str, request: StackCopy, user=Depends(get_current_user)):
    """
    Copy a stack to a new name.

    Creates a copy of the stack with a new name.
    The copy has no deployments.
    Returns the new stack with its content for API symmetry.
    """
    try:
        stack = await stack_service.copy_stack(name, request.dest_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(f"User {user.username} copied stack '{name}' to '{request.dest_name}'")

    return StackResponse.from_stack_info(stack)
