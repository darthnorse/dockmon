"""
Shared types for update executors.

This module contains dataclasses and types used by both DockerUpdateExecutor
and AgentUpdateExecutor to ensure consistent interfaces.
"""

from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable, Any, Dict
from enum import Enum


class UpdateStage(Enum):
    """Stages of a container update."""
    INITIATING = "initiating"
    PULLING_IMAGE = "pulling_image"
    PULL_COMPLETE = "pull_complete"
    CREATING_BACKUP = "creating_backup"
    BACKUP_CREATED = "backup_created"
    STOPPING_OLD = "stopping_old"
    CREATING_NEW = "creating_new"
    STARTING_NEW = "starting_new"
    HEALTH_CHECK = "health_check"
    CLEANUP = "cleanup"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLBACK_COMPLETE = "rollback_complete"
    # Agent-specific stages
    AGENT_UPDATING = "agent_updating"
    AGENT_RECONNECTING = "agent_reconnecting"


@dataclass
class UpdateContext:
    """
    Context for a container update operation.

    Passed from the router to executors to provide all necessary
    information for performing the update.
    """
    host_id: str
    container_id: str  # SHORT ID (12 chars)
    container_name: str
    current_image: str
    new_image: str
    update_record_id: int
    force: bool = False
    force_warn: bool = False

    # Optional metadata
    auth_config: Optional[Dict[str, str]] = None  # Registry credentials

    @property
    def composite_key(self) -> str:
        """Return composite key for this container."""
        return f"{self.host_id}:{self.container_id}"


@dataclass
class UpdateResult:
    """
    Result of a container update operation.

    Returned by executors to the router to communicate the outcome
    and any state changes that need to be persisted.
    """
    success: bool
    new_container_id: Optional[str] = None  # If container was recreated (SHORT ID)
    error_message: Optional[str] = None
    rollback_performed: bool = False

    # Additional metadata for database updates
    backup_container_id: Optional[str] = None
    backup_removed: bool = False

    @classmethod
    def success_result(cls, new_container_id: str) -> 'UpdateResult':
        """Create a successful result."""
        return cls(success=True, new_container_id=new_container_id)

    @classmethod
    def failure_result(cls, error_message: str, rollback_performed: bool = False) -> 'UpdateResult':
        """Create a failure result."""
        return cls(
            success=False,
            error_message=error_message,
            rollback_performed=rollback_performed
        )


# Type alias for progress callback
# Signature: async def callback(stage: str, percent: int, message: str) -> None
ProgressCallback = Callable[[str, int, str], Awaitable[None]]


@dataclass
class PullProgress:
    """Progress information for image pull operations."""
    layer_id: str
    status: str
    current: int = 0
    total: int = 0

    @property
    def percent(self) -> int:
        """Calculate percentage complete."""
        if self.total == 0:
            return 0
        return int((self.current / self.total) * 100)


def make_composite_key(host_id: str, container_id: str) -> str:
    """
    Create composite key for container identification.

    Format: {host_id}:{container_id}
    Where container_id is SHORT (12 chars).
    """
    # Normalize container_id to short format
    short_id = container_id[:12] if len(container_id) > 12 else container_id
    return f"{host_id}:{short_id}"


def normalize_container_id(container_id: str) -> str:
    """
    Normalize container ID to 12-char short format.

    Accepts both 12-char and 64-char IDs for defensive resilience.
    """
    return container_id[:12]
