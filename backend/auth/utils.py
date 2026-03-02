"""
Shared Authentication Utilities (v2.4.0)

Common helper functions for auth-related routes to reduce code duplication.
"""

from datetime import datetime, timezone
from typing import Literal, NotRequired, TypedDict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import User, CustomGroup


# ==================== Auth Context Types ====================

class SessionAuthContext(TypedDict):
    user_id: int
    username: str
    display_name: str
    auth_type: Literal["session"]
    groups: list[dict]
    session_id: NotRequired[str]


class ApiKeyAuthContext(TypedDict):
    api_key_id: int
    api_key_name: str
    group_id: int
    group_name: str
    created_by_user_id: int
    created_by_username: str
    auth_type: Literal["api_key"]


AuthContext = SessionAuthContext | ApiKeyAuthContext


def get_auditable_user_info(current_user: dict) -> tuple[int | None, str]:
    """Extract user ID and display name from auth context for audit logging.

    Handles both session auth and API key auth contexts.

    Args:
        current_user: Auth context from get_current_user_or_api_key

    Returns:
        Tuple of (user_id, display_name) where:
        - Session auth: (user_id, display_name or username)
        - API key auth: (created_by_user_id, "API Key: <name>")
    """
    if current_user.get("auth_type") == "api_key":
        return (
            current_user.get("created_by_user_id"),
            f"API Key: {current_user.get('api_key_name', 'unknown')}"
        )
    return (current_user.get("user_id"),
            current_user.get("display_name") or current_user.get("username", "unknown"))


def _to_naive_utc(dt: datetime) -> datetime:
    """Strip timezone info after converting to UTC, so .isoformat() won't embed an offset."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def format_timestamp(dt: datetime | None) -> str | None:
    """Format datetime to ISO string with 'Z' suffix for frontend."""
    if dt is None:
        return None
    return _to_naive_utc(dt).isoformat() + 'Z'


def format_timestamp_required(dt: datetime | None) -> str:
    """Format datetime to ISO string with 'Z' suffix, using now() if None."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return _to_naive_utc(dt).isoformat() + 'Z'


def get_user_or_404(session: Session, user_id: int) -> User:
    """Get user by ID or raise 404 HTTPException.

    Args:
        session: Database session
        user_id: User ID to look up

    Returns:
        User object

    Raises:
        HTTPException: 404 if user not found
    """
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def get_group_or_400(session: Session, group_id: int) -> CustomGroup:
    """Get group by ID or raise 400 HTTPException.

    Args:
        session: Database session
        group_id: Group ID to look up

    Returns:
        CustomGroup object

    Raises:
        HTTPException: 400 if group not found
    """
    group = session.query(CustomGroup).filter(CustomGroup.id == group_id).first()
    if not group:
        raise HTTPException(
            status_code=400,
            detail=f"Group with ID {group_id} not found"
        )
    return group


def validate_group_ids(session: Session, group_ids: list[int]) -> list[CustomGroup]:
    """Validate multiple group IDs exist and return the groups.

    Args:
        session: Database session
        group_ids: List of group IDs to validate

    Returns:
        List of CustomGroup objects

    Raises:
        HTTPException: 400 if any group not found
    """
    if not group_ids:
        raise HTTPException(
            status_code=400,
            detail="At least one group ID is required"
        )

    groups = session.query(CustomGroup).filter(CustomGroup.id.in_(group_ids)).all()

    if len(groups) != len(group_ids):
        found_ids = {g.id for g in groups}
        missing_ids = set(group_ids) - found_ids
        raise HTTPException(
            status_code=400,
            detail=f"Groups not found: {sorted(missing_ids)}"
        )

    return groups
