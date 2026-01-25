"""
Shared Authentication Utilities (v2.4.0)

Common helper functions for auth-related routes to reduce code duplication.
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import User, CustomGroup


def format_timestamp(dt: datetime | None) -> str | None:
    """Format datetime to ISO string with 'Z' suffix for frontend.

    Args:
        dt: Datetime to format, or None

    Returns:
        ISO formatted string with 'Z' suffix, or None if input is None
    """
    if dt is None:
        return None
    return dt.isoformat() + 'Z'


def format_timestamp_required(dt: datetime | None) -> str:
    """Format datetime to ISO string, using now() if None.

    Args:
        dt: Datetime to format, or None

    Returns:
        ISO formatted string with 'Z' suffix (uses current time if input is None)
    """
    if dt is None:
        return datetime.now(timezone.utc).isoformat() + 'Z'
    return dt.isoformat() + 'Z'


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
