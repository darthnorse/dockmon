"""
DockMon User Management Routes - Admin-only User CRUD Operations

Phase 3 of Multi-User Support (v2.3.0)
Phase 4: Group-based permissions (v2.4.0)

SECURITY:
- All endpoints require users.manage capability
- Soft delete preserves audit trail
- Password changes trigger must_change_password flag
- Users are assigned to groups for permissions
"""

import logging
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator, EmailStr
from argon2 import PasswordHasher

from auth.shared import db, safe_audit_log
from auth.api_key_auth import require_capability, get_current_user_or_api_key, invalidate_user_groups_cache
from auth.utils import format_timestamp, format_timestamp_required, get_user_or_404, validate_group_ids
from database import User, CustomGroup, UserGroupMembership
from audit import get_client_info, AuditAction
from audit.audit_logger import AuditEntityType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/users", tags=["user-management"])

# Argon2 password hasher (same config as v2_routes.py)
ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16
)


def _get_auditable_user_info(current_user: dict) -> tuple[int | None, str]:
    """Extract user ID and username from auth context for audit logging.

    Handles both session auth and API key auth contexts.

    Args:
        current_user: Auth context from get_current_user_or_api_key

    Returns:
        Tuple of (user_id, display_name) where:
        - Session auth: (user_id, username)
        - API key auth: (created_by_user_id, "API Key: <name>")
    """
    if current_user.get("auth_type") == "api_key":
        return (
            current_user.get("created_by_user_id"),
            f"API Key: {current_user.get('api_key_name', 'unknown')}"
        )
    return (current_user.get("user_id"), current_user.get("username", "unknown"))


# ==================== Request/Response Models ====================

class UserGroupResponse(BaseModel):
    """Group membership for a user"""
    id: int
    name: str


class UserResponse(BaseModel):
    """User data returned to admin (v2.4.0: includes groups)"""
    id: int
    username: str
    email: str | None = None
    display_name: str | None = None
    role: str  # Kept for backwards compatibility
    groups: list[UserGroupResponse]  # New in v2.4.0
    auth_provider: str
    is_first_login: bool
    must_change_password: bool
    last_login: str | None = None
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    is_deleted: bool


class UserListResponse(BaseModel):
    """List of users"""
    users: list[UserResponse]
    total: int


class CreateUserRequest(BaseModel):
    """Create a new user (v2.4.0: uses group_ids instead of role)"""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    email: EmailStr | None = Field(None)
    display_name: str | None = Field(None, max_length=100)
    group_ids: list[int] = Field(..., min_length=1, description="List of group IDs to assign user to")
    must_change_password: bool = Field(default=True)

    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        # Basic username validation - alphanumeric, underscore, hyphen
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', v):
            raise ValueError("Username must start with a letter and contain only letters, numbers, underscores, and hyphens")
        return v


class UpdateUserRequest(BaseModel):
    """Update an existing user (v2.4.0: can manage group assignments)"""
    email: EmailStr | None = Field(None)
    display_name: str | None = Field(None, max_length=100)
    group_ids: list[int] | None = Field(None, description="Replace user's group assignments")


class ResetPasswordRequest(BaseModel):
    """Admin-initiated password reset"""
    new_password: str | None = Field(None, min_length=8, max_length=128)


# ==================== Helper Functions ====================
# format_timestamp and format_timestamp_required imported from auth.utils


def _ensure_not_last_admin(session, user_id: int, action: str) -> None:
    """
    Raise HTTPException if the user is the last member of the Administrators group.

    Uses group-based permissions (v2.4.0) - checks Administrators group membership,
    not the legacy role field.

    Args:
        session: Database session
        user_id: ID of the user being modified
        action: Description for error message (e.g., "delete", "remove from Administrators")
    """
    # Check if user is in Administrators group
    admin_group = session.query(CustomGroup).filter(CustomGroup.name == "Administrators").first()
    if not admin_group:
        return  # No Administrators group exists, nothing to protect

    user_is_admin = session.query(UserGroupMembership).filter(
        UserGroupMembership.user_id == user_id,
        UserGroupMembership.group_id == admin_group.id
    ).first() is not None

    if user_is_admin:
        # Count other active admins (not deleted, not this user)
        other_admin_count = session.query(UserGroupMembership).join(
            User, UserGroupMembership.user_id == User.id
        ).filter(
            UserGroupMembership.group_id == admin_group.id,
            UserGroupMembership.user_id != user_id,
            User.deleted_at.is_(None)
        ).count()

        if other_admin_count == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot {action}: this is the last member of the Administrators group"
            )


def _get_user_groups(session, user_id: int) -> list[UserGroupResponse]:
    """Get groups for a user."""
    memberships = session.query(UserGroupMembership, CustomGroup).join(
        CustomGroup, UserGroupMembership.group_id == CustomGroup.id
    ).filter(UserGroupMembership.user_id == user_id).all()

    return [UserGroupResponse(id=group.id, name=group.name) for _, group in memberships]


def _get_all_user_groups(session, user_ids: list[int]) -> dict[int, list[UserGroupResponse]]:
    """Pre-fetch groups for multiple users in a single query to avoid N+1."""
    if not user_ids:
        return {}

    memberships = session.query(UserGroupMembership, CustomGroup).join(
        CustomGroup, UserGroupMembership.group_id == CustomGroup.id
    ).filter(UserGroupMembership.user_id.in_(user_ids)).all()

    # Group by user_id
    groups_by_user: dict[int, list[UserGroupResponse]] = {uid: [] for uid in user_ids}
    for membership, group in memberships:
        groups_by_user[membership.user_id].append(
            UserGroupResponse(id=group.id, name=group.name)
        )

    return groups_by_user


def _user_to_response(
    user: User,
    session,
    groups: list[UserGroupResponse] | None = None
) -> UserResponse:
    """Convert User model to response (v2.4.0: includes groups).

    Args:
        user: User model to convert
        session: Database session (used if groups not provided)
        groups: Pre-fetched groups to avoid N+1 query (optional)
    """
    if groups is None:
        groups = _get_user_groups(session, user.id)
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        role=user.role if user.role else 'user',  # Backwards compatibility
        groups=groups,
        auth_provider=user.auth_provider,
        is_first_login=user.is_first_login,
        must_change_password=user.must_change_password,
        last_login=format_timestamp(user.last_login),
        created_at=format_timestamp_required(user.created_at),
        updated_at=format_timestamp_required(user.updated_at),
        deleted_at=format_timestamp(user.deleted_at),
        is_deleted=user.is_deleted
    )


# ==================== API Endpoints ====================

@router.get("", response_model=UserListResponse, dependencies=[Depends(require_capability("users.manage"))])
async def list_users(
    include_deleted: bool = False,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserListResponse:
    """
    List all users (requires users.manage capability).

    Args:
        include_deleted: Include soft-deleted users in the list
    """
    with db.get_session() as session:
        query = session.query(User)

        if not include_deleted:
            query = query.filter(User.deleted_at.is_(None))

        users = query.order_by(User.created_at.desc()).all()

        # Pre-fetch all groups in a single query to avoid N+1
        user_ids = [u.id for u in users]
        groups_by_user = _get_all_user_groups(session, user_ids)

        return UserListResponse(
            users=[
                _user_to_response(u, session, groups=groups_by_user.get(u.id, []))
                for u in users
            ],
            total=len(users)
        )


@router.post("", response_model=UserResponse, dependencies=[Depends(require_capability("users.manage"))])
async def create_user(
    user_data: CreateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserResponse:
    """
    Create a new user (requires users.manage capability).

    v2.4.0: Users are assigned to groups instead of roles.

    Default behavior:
    - New users must change password on first login
    - Must specify at least one group
    - Auth provider is 'local'
    """
    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = _get_auditable_user_info(current_user)

    with db.get_session() as session:
        # Check if username already exists
        existing = session.query(User).filter(User.username == user_data.username).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Username already exists"
            )

        # Check if email already exists (if provided)
        if user_data.email:
            existing_email = session.query(User).filter(User.email == user_data.email).first()
            if existing_email:
                raise HTTPException(
                    status_code=400,
                    detail="Email already in use"
                )

        # Validate all group_ids exist (uses shared helper)
        groups = validate_group_ids(session, user_data.group_ids)
        group_names = [g.name for g in groups]

        # Hash password with Argon2id
        password_hash = ph.hash(user_data.password)

        # Create user
        new_user = User(
            username=user_data.username,
            password_hash=password_hash,
            email=user_data.email,
            display_name=user_data.display_name,
            role='user',  # Default role for backwards compatibility
            auth_provider='local',
            is_first_login=True,
            must_change_password=user_data.must_change_password,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        session.add(new_user)
        session.flush()  # Get new_user.id for group memberships

        # Add group memberships
        now = datetime.now(timezone.utc)
        for group_id in user_data.group_ids:
            membership = UserGroupMembership(
                user_id=new_user.id,
                group_id=group_id,
                added_by=user_id,
                added_at=now,
            )
            session.add(membership)

        # Audit log (before commit for atomicity)
        safe_audit_log(
            session,
            user_id,
            display_name,
            AuditAction.CREATE,
            AuditEntityType.USER,
            entity_id=str(new_user.id),
            entity_name=new_user.username,
            details={'groups': group_names, 'must_change_password': user_data.must_change_password},
            **get_client_info(request)
        )

        session.commit()
        session.refresh(new_user)

        logger.info(f"User '{user_data.username}' created by {display_name} with groups: {group_names}")

        return _user_to_response(new_user, session)


@router.get("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_capability("users.manage"))])
async def get_user(
    user_id: int,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserResponse:
    """
    Get a specific user by ID (requires users.manage capability).
    """
    with db.get_session() as session:
        user = get_user_or_404(session, user_id)
        return _user_to_response(user, session)


@router.put("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_capability("users.manage"))])
async def update_user(
    user_id: int,
    user_data: UpdateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserResponse:
    """
    Update a user (requires users.manage capability).

    v2.4.0: Can manage group assignments via group_ids.

    Only updates fields that are provided (partial update).
    Cannot change username (use separate endpoint if needed).
    """
    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = _get_auditable_user_info(current_user)

    with db.get_session() as session:
        user = get_user_or_404(session, user_id)

        changes = {}

        # Update email if provided
        if user_data.email is not None:
            # Check for email uniqueness
            if user_data.email:
                existing = session.query(User).filter(
                    User.email == user_data.email,
                    User.id != user_id
                ).first()
                if existing:
                    raise HTTPException(
                        status_code=400,
                        detail="Email already in use"
                    )
            changes['email'] = {'old': user.email, 'new': user_data.email}
            user.email = user_data.email if user_data.email else None

        # Update display name if provided
        if user_data.display_name is not None:
            changes['display_name'] = {'old': user.display_name, 'new': user_data.display_name}
            user.display_name = user_data.display_name if user_data.display_name else None

        # Update group assignments if provided (v2.4.0)
        if user_data.group_ids is not None:
            if len(user_data.group_ids) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="User must belong to at least one group"
                )

            # Validate all new group_ids exist (uses shared helper)
            new_groups = validate_group_ids(session, user_data.group_ids)
            new_group_names = [g.name for g in new_groups]

            # Get current groups for audit log
            current_groups = _get_user_groups(session, user_id)
            old_group_names = [g.name for g in current_groups]

            # Remove all existing memberships
            session.query(UserGroupMembership).filter(
                UserGroupMembership.user_id == user_id
            ).delete()

            # Add new memberships
            now = datetime.now(timezone.utc)
            for group_id in user_data.group_ids:
                membership = UserGroupMembership(
                    user_id=user_id,
                    group_id=group_id,
                    added_by=user_id,
                    added_at=now,
                )
                session.add(membership)

            changes['groups'] = {'old': old_group_names, 'new': new_group_names}

            # Invalidate cache for this user
            invalidate_user_groups_cache(user_id)

        user.updated_at = datetime.now(timezone.utc)

        # Audit log (before commit for atomicity)
        if changes:
            safe_audit_log(
                session,
                user_id,
                display_name,
                AuditAction.UPDATE,
                AuditEntityType.USER,
                entity_id=str(user.id),
                entity_name=user.username,
                details={'changes': changes},
                **get_client_info(request)
            )

        session.commit()
        session.refresh(user)

        logger.info(f"User '{user.username}' updated by {display_name}: {changes}")

        return _user_to_response(user, session)


@router.delete("/{user_id}", dependencies=[Depends(require_capability("users.manage"))])
async def delete_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """
    Soft delete a user (requires users.manage capability).

    Preserves audit trail by setting deleted_at timestamp.
    User cannot log in after deletion but records are preserved.
    """
    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = _get_auditable_user_info(current_user)

    with db.get_session() as session:
        user = get_user_or_404(session, user_id)

        # Prevent self-deletion (only applies to session auth)
        current_user_id = current_user.get("user_id")
        if current_user.get("auth_type") != "api_key" and current_user_id == user_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete your own account"
            )

        # Prevent deleting the last admin
        _ensure_not_last_admin(session, user_id, "delete")

        # Check if already deleted
        if user.is_deleted:
            raise HTTPException(
                status_code=400,
                detail="User is already deactivated"
            )

        # Soft delete
        user.deleted_at = datetime.now(timezone.utc)
        user.deleted_by = user_id
        user.updated_at = datetime.now(timezone.utc)

        # Audit log (before commit for atomicity)
        safe_audit_log(
            session,
            user_id,
            display_name,
            AuditAction.DELETE,
            AuditEntityType.USER,
            entity_id=str(user.id),
            entity_name=user.username,
            **get_client_info(request)
        )

        session.commit()

        logger.info(f"User '{user.username}' deactivated by {display_name}")

        return {"message": f"User '{user.username}' has been deactivated"}


@router.post("/{user_id}/reactivate", response_model=UserResponse, dependencies=[Depends(require_capability("users.manage"))])
async def reactivate_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserResponse:
    """
    Reactivate a soft-deleted user (requires users.manage capability).
    """
    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = _get_auditable_user_info(current_user)

    with db.get_session() as session:
        user = get_user_or_404(session, user_id)

        if not user.is_deleted:
            raise HTTPException(
                status_code=400,
                detail="User is not deactivated"
            )

        # Reactivate
        user.deleted_at = None
        user.deleted_by = None
        user.updated_at = datetime.now(timezone.utc)

        # Audit log (before commit for atomicity)
        safe_audit_log(
            session,
            user_id,
            display_name,
            AuditAction.UPDATE,
            AuditEntityType.USER,
            entity_id=str(user.id),
            entity_name=user.username,
            details={'action': 'reactivate'},
            **get_client_info(request)
        )

        session.commit()
        session.refresh(user)

        logger.info(f"User '{user.username}' reactivated by {display_name}")

        return _user_to_response(user, session)


@router.post("/{user_id}/reset-password", dependencies=[Depends(require_capability("users.manage"))])
async def reset_user_password(
    user_id: int,
    password_data: ResetPasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """
    Reset a user's password (requires users.manage capability).

    If new_password is provided, sets it directly.
    If not provided, generates a random password.

    Always sets must_change_password=True so user must change on next login.
    """
    # Get user info for audit (handles both session and API key auth)
    user_id, display_name = _get_auditable_user_info(current_user)

    with db.get_session() as session:
        user = get_user_or_404(session, user_id)

        # Cannot reset OIDC user's password
        if user.is_oidc_user:
            raise HTTPException(
                status_code=400,
                detail="Cannot reset password for OIDC users"
            )

        # Generate or use provided password
        if password_data.new_password:
            new_password = password_data.new_password
        else:
            new_password = secrets.token_urlsafe(12)

        # Hash and set new password
        user.password_hash = ph.hash(new_password)
        user.must_change_password = True
        user.updated_at = datetime.now(timezone.utc)

        # Audit log (before commit for atomicity)
        safe_audit_log(
            session,
            user_id,
            display_name,
            AuditAction.PASSWORD_CHANGE,
            AuditEntityType.USER,
            entity_id=str(user.id),
            entity_name=user.username,
            details={'admin_reset': True},
            **get_client_info(request)
        )

        session.commit()

        logger.info(f"Password reset for user '{user.username}' by {display_name}")

        return {
            "message": f"Password reset for user '{user.username}'",
            "temporary_password": new_password if not password_data.new_password else None,
            "must_change_password": True
        }
