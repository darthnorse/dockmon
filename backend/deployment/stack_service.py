"""
Stack service layer.

Coordinates between filesystem (stack_storage) and database (deployments).
Handles operations that require both filesystem and database changes.
"""
import logging
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from database import Deployment
from deployment import stack_storage

logger = logging.getLogger(__name__)


class StackInfo:
    """Stack information including deployment counts."""

    def __init__(
        self,
        name: str,
        deployment_count: int = 0,
        compose_yaml: Optional[str] = None,
        env_content: Optional[str] = None,
    ):
        self.name = name
        self.deployment_count = deployment_count
        self.compose_yaml = compose_yaml
        self.env_content = env_content

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        result = {
            "name": self.name,
            "deployment_count": self.deployment_count,
        }
        if self.compose_yaml is not None:
            result["compose_yaml"] = self.compose_yaml
        if self.env_content is not None:
            result["env_content"] = self.env_content
        return result


async def list_stacks_with_counts(session: Session) -> List[StackInfo]:
    """
    List all stacks with their deployment counts.

    Combines filesystem stacks with database deployment counts.

    Args:
        session: Database session

    Returns:
        List of StackInfo objects sorted by name
    """
    # Get all stacks from filesystem
    stack_names = await stack_storage.list_stacks()

    if not stack_names:
        return []

    # Get deployment counts per stack name
    counts = (
        session.query(Deployment.stack_name, func.count(Deployment.id))
        .filter(Deployment.stack_name.in_(stack_names))
        .group_by(Deployment.stack_name)
        .all()
    )

    count_map = {name: count for name, count in counts}

    return [
        StackInfo(name=name, deployment_count=count_map.get(name, 0))
        for name in stack_names
    ]


async def get_stack(session: Session, name: str) -> Optional[StackInfo]:
    """
    Get a stack with its content and deployment count.

    Args:
        session: Database session
        name: Stack name

    Returns:
        StackInfo with compose_yaml and env_content, or None if not found
    """
    # Check if stack exists on filesystem
    if not await stack_storage.stack_exists(name):
        return None

    # Read stack content
    compose_yaml, env_content = await stack_storage.read_stack(name)

    # Get deployment count
    count = (
        session.query(func.count(Deployment.id))
        .filter(Deployment.stack_name == name)
        .scalar()
    )

    return StackInfo(
        name=name,
        deployment_count=count or 0,
        compose_yaml=compose_yaml,
        env_content=env_content,
    )


async def create_stack(
    name: str,
    compose_yaml: str,
    env_content: Optional[str] = None,
) -> StackInfo:
    """
    Create a new stack.

    Args:
        name: Stack name (must be valid)
        compose_yaml: Compose file content
        env_content: Optional .env file content

    Returns:
        StackInfo for the created stack

    Raises:
        ValueError: If name is invalid or stack already exists
    """
    # Write to filesystem (validates name, fails if exists with create_only)
    await stack_storage.write_stack(name, compose_yaml, env_content, create_only=True)

    logger.info(f"Created stack '{name}'")

    return StackInfo(
        name=name,
        deployment_count=0,
        compose_yaml=compose_yaml,
        env_content=env_content,
    )


async def update_stack(
    name: str,
    compose_yaml: str,
    env_content: Optional[str] = None,
) -> StackInfo:
    """
    Update an existing stack's content.

    Args:
        name: Stack name
        compose_yaml: New compose file content
        env_content: New .env file content (None to remove)

    Returns:
        Updated StackInfo

    Raises:
        FileNotFoundError: If stack doesn't exist
    """
    # Verify stack exists
    if not await stack_storage.stack_exists(name):
        raise FileNotFoundError(f"Stack '{name}' not found")

    # Write updated content
    await stack_storage.write_stack(name, compose_yaml, env_content)

    logger.info(f"Updated stack '{name}'")

    return StackInfo(
        name=name,
        deployment_count=0,  # Caller should re-fetch if count needed
        compose_yaml=compose_yaml,
        env_content=env_content,
    )


async def rename_stack(
    session: Session,
    old_name: str,
    new_name: str,
) -> StackInfo:
    """
    Rename a stack (both filesystem and deployment references).

    Database is updated FIRST (can rollback), then filesystem is renamed.
    If filesystem rename fails, database change is rolled back.

    Args:
        session: Database session
        old_name: Current stack name
        new_name: New stack name

    Returns:
        StackInfo with new name and content

    Raises:
        FileNotFoundError: If old stack doesn't exist
        ValueError: If new name is invalid or already exists
    """
    # Validate new_name and check existence BEFORE any changes
    stack_storage.validate_stack_name(new_name)
    if not await stack_storage.stack_exists(old_name):
        raise FileNotFoundError(f"Stack '{old_name}' not found")
    if await stack_storage.stack_exists(new_name):
        raise ValueError(f"Stack '{new_name}' already exists")

    # Update database FIRST (can rollback if filesystem rename fails)
    updated = (
        session.query(Deployment)
        .filter(Deployment.stack_name == old_name)
        .update({Deployment.stack_name: new_name})
    )
    session.commit()

    # THEN rename files (DB is source of truth)
    try:
        await stack_storage.rename_stack_files(old_name, new_name)
    except Exception as e:
        # Filesystem rename failed - rollback database change
        logger.error(f"Filesystem rename failed, rolling back DB: {e}")
        session.query(Deployment).filter(Deployment.stack_name == new_name).update(
            {Deployment.stack_name: old_name}
        )
        session.commit()
        raise

    logger.info(f"Renamed stack '{old_name}' to '{new_name}' ({updated} deployments updated)")

    # Read content for response (API data flow symmetry)
    compose_yaml, env_content = await stack_storage.read_stack(new_name)

    return StackInfo(
        name=new_name,
        deployment_count=updated,
        compose_yaml=compose_yaml,
        env_content=env_content,
    )


async def delete_stack(session: Session, name: str) -> None:
    """
    Delete a stack.

    Args:
        session: Database session
        name: Stack name

    Raises:
        FileNotFoundError: If stack doesn't exist
        ValueError: If stack has active deployments
    """
    # Check if stack exists
    if not await stack_storage.stack_exists(name):
        raise FileNotFoundError(f"Stack '{name}' not found")

    # Check for deployments using this stack
    deployment_count = (
        session.query(func.count(Deployment.id))
        .filter(Deployment.stack_name == name)
        .scalar()
    )

    if deployment_count and deployment_count > 0:
        raise ValueError(
            f"Cannot delete stack '{name}': {deployment_count} deployment(s) still reference it. "
            f"Delete the deployments first."
        )

    # Safe to delete files
    await stack_storage.delete_stack_files(name)

    logger.info(f"Deleted stack '{name}'")


async def copy_stack(
    source_name: str,
    dest_name: str,
) -> StackInfo:
    """
    Copy a stack to a new name.

    Args:
        source_name: Source stack name
        dest_name: Destination stack name

    Returns:
        StackInfo for the new stack with content

    Raises:
        FileNotFoundError: If source doesn't exist
        ValueError: If dest name is invalid or already exists
    """
    await stack_storage.copy_stack(source_name, dest_name)

    logger.info(f"Copied stack '{source_name}' to '{dest_name}'")

    # Read content for response (API data flow symmetry)
    compose_yaml, env_content = await stack_storage.read_stack(dest_name)

    return StackInfo(
        name=dest_name,
        deployment_count=0,
        compose_yaml=compose_yaml,
        env_content=env_content,
    )


def get_deployment_count(session: Session, stack_name: str) -> int:
    """
    Get the number of deployments using a stack.

    Synchronous helper for quick checks.

    Args:
        session: Database session
        stack_name: Stack name

    Returns:
        Number of deployments referencing this stack
    """
    count = (
        session.query(func.count(Deployment.id))
        .filter(Deployment.stack_name == stack_name)
        .scalar()
    )
    return count or 0


class OrphanedDeploymentInfo:
    """Info about an orphaned deployment (references non-existent stack)."""

    def __init__(
        self,
        id: str,
        host_id: str,
        host_name: Optional[str],
        stack_name: str,
        status: str,
        container_ids: Optional[List[str]] = None,
    ):
        self.id = id
        self.host_id = host_id
        self.host_name = host_name
        self.stack_name = stack_name
        self.status = status
        self.container_ids = container_ids or []

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "host_id": self.host_id,
            "host_name": self.host_name,
            "stack_name": self.stack_name,
            "status": self.status,
            "container_ids": self.container_ids,
        }


async def find_orphaned_deployments(
    session: Session,
    user_id: int,
) -> List[OrphanedDeploymentInfo]:
    """
    Find deployments that reference stacks that no longer exist on filesystem.

    Args:
        session: Database session
        user_id: Filter by user

    Returns:
        List of OrphanedDeploymentInfo for deployments with missing stacks
    """
    from database import DeploymentMetadata
    from utils.keys import parse_composite_key

    # Get all valid stacks from filesystem
    valid_stacks = set(await stack_storage.list_stacks())

    # Get all deployments for user
    deployments = (
        session.query(Deployment)
        .filter(Deployment.user_id == user_id)
        .all()
    )

    orphaned = []
    for dep in deployments:
        if dep.stack_name and dep.stack_name not in valid_stacks:
            # Get container IDs from deployment metadata
            metadata_records = (
                session.query(DeploymentMetadata)
                .filter(DeploymentMetadata.deployment_id == dep.id)
                .all()
            )
            container_ids = []
            for record in metadata_records:
                try:
                    _, container_id = parse_composite_key(record.container_id)
                    container_ids.append(container_id)
                except (ValueError, AttributeError):
                    pass

            orphaned.append(OrphanedDeploymentInfo(
                id=dep.id,
                host_id=dep.host_id,
                host_name=dep.host.name if dep.host else None,
                stack_name=dep.stack_name,
                status=dep.status,
                container_ids=container_ids,
            ))

    return orphaned
