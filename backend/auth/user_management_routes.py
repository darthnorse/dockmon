"""
DockMon User Management Routes - Admin-only User CRUD Operations

Phase 3 of Multi-User Support (v2.3.0)
Phase 4: Group-based permissions (v2.4.0)

SECURITY:
- All endpoints require users.manage capability
- Hard delete with pre-delete audit logging
- Password changes trigger must_change_password flag
- Users are assigned to groups for permissions
"""

import logging
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator, EmailStr
from auth.password import ph
from auth.shared import db, safe_audit_log
from auth.api_key_auth import require_capability, get_current_user_or_api_key, invalidate_user_groups_cache
from auth.cookie_sessions import cookie_session_manager
from auth.utils import format_timestamp, format_timestamp_required, get_user_or_404, validate_group_ids, get_auditable_user_info, ensure_not_last_admin, verify_critical_capabilities
from database import User, CustomGroup, UserGroupMembership
from audit import get_client_info, AuditAction
from audit.audit_logger import AuditEntityType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/users", tags=["user-management"])



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
    approved: bool  # New in v2.6.0 - pending approval for OIDC users
    last_login: str | None = None
    created_at: str
    updated_at: str


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
        approved=user.approved,
        last_login=format_timestamp(user.last_login),
        created_at=format_timestamp_required(user.created_at),
        updated_at=format_timestamp_required(user.updated_at),
    )


# ==================== API Endpoints ====================

@router.get("", response_model=UserListResponse, dependencies=[Depends(require_capability("users.manage"))])
async def list_users(
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserListResponse:
    """List all users (requires users.manage capability)."""
    with db.get_session() as session:
        users = session.query(User).order_by(User.created_at.desc()).all()

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
    user_id, display_name = get_auditable_user_info(current_user)

    with db.get_session() as session:
        existing = session.query(User).filter(
            User.username == user_data.username,
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Username already exists"
            )

        # Check if email already exists (if provided)
        if user_data.email:
            existing_email = session.query(User).filter(
                User.email == user_data.email,
            ).first()
            if existing_email:
                raise HTTPException(
                    status_code=400,
                    detail="Email already in use"
                )

        # Validate all group_ids exist (uses shared helper)
        groups = validate_group_ids(session, user_data.group_ids)
        group_names = [g.name for g in groups]

        password_hash = ph.hash(user_data.password)

        new_user = User(
            username=user_data.username,
            password_hash=password_hash,
            email=user_data.email,
            display_name=user_data.display_name,
            role='user',
            auth_provider='local',
            is_first_login=True,
            must_change_password=user_data.must_change_password,
            approved=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        session.add(new_user)
        session.flush()  # Get new_user.id for group memberships

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


@router.get("/pending-count", dependencies=[Depends(require_capability("users.manage"))])
async def get_pending_count(
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """Get count of users pending approval (requires users.manage capability)."""
    with db.get_session() as session:
        count = session.query(User).filter(User.approved == False).count()  # noqa: E712
        return {"count": count}


@router.post("/approve-all", dependencies=[Depends(require_capability("users.manage"))])
async def approve_all_users(
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """Approve all pending users (requires users.manage capability)."""
    user_id, display_name = get_auditable_user_info(current_user)

    with db.get_session() as session:
        pending_users = session.query(User).filter(User.approved == False).all()  # noqa: E712

        if not pending_users:
            return {"message": "No pending users", "count": 0}

        usernames = [u.username for u in pending_users]
        now = datetime.now(timezone.utc)

        for user in pending_users:
            user.approved = True
            user.updated_at = now

        safe_audit_log(
            session,
            user_id,
            display_name,
            AuditAction.APPROVE,
            AuditEntityType.USER,
            details={'action': 'approve_all', 'count': len(usernames), 'usernames': usernames},
            **get_client_info(request)
        )

        session.commit()

        logger.info(f"Approved {len(usernames)} pending user(s) by {display_name}: {usernames}")

        return {"message": f"Approved {len(usernames)} user(s)", "count": len(usernames)}


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
    # NOTE: user_id path param = target; audit user_id = acting user
    target_user_id = user_id
    user_id, display_name = get_auditable_user_info(current_user)

    _needs_ws_refresh = None

    with db.get_session() as session:
        user = get_user_or_404(session, target_user_id)

        changes = {}

        # Update email if provided
        if user_data.email is not None:
            if user_data.email:
                existing = session.query(User).filter(
                    User.email == user_data.email,
                    User.id != target_user_id,
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

            admin_group = session.query(CustomGroup).filter(
                CustomGroup.name == "Administrators"
            ).first()
            if admin_group and admin_group.id not in user_data.group_ids:
                ensure_not_last_admin(session, target_user_id, "remove from Administrators")

            # Get current groups for audit log
            current_groups = _get_user_groups(session, target_user_id)
            old_group_names = [g.name for g in current_groups]

            # Remove all existing memberships
            session.query(UserGroupMembership).filter(
                UserGroupMembership.user_id == target_user_id
            ).delete()

            # Add new memberships (deduplicate to prevent unique constraint violations)
            now = datetime.now(timezone.utc)
            for group_id in set(user_data.group_ids):
                membership = UserGroupMembership(
                    user_id=target_user_id,
                    group_id=group_id,
                    added_by=user_id,
                    added_at=now,
                )
                session.add(membership)

            changes['groups'] = {'old': old_group_names, 'new': new_group_names}

            # Invalidate cache for this user
            invalidate_user_groups_cache(target_user_id)
            _needs_ws_refresh = target_user_id

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

        response = _user_to_response(user, session)

    # Refresh WS capabilities outside the DB session
    if _needs_ws_refresh is not None:
        from auth.custom_groups_routes import _refresh_ws_capabilities
        await _refresh_ws_capabilities(_needs_ws_refresh)

    return response


@router.post("/{user_id}/approve", dependencies=[Depends(require_capability("users.manage"))])
async def approve_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """
    Approve a single user (requires users.manage capability).

    Sets the user's approved flag to True. If already approved, returns a no-op message.
    """
    target_user_id = user_id
    user_id, display_name = get_auditable_user_info(current_user)

    with db.get_session() as session:
        user = get_user_or_404(session, target_user_id)

        if user.approved:
            return {"message": f"User '{user.username}' is already approved"}

        user.approved = True
        user.updated_at = datetime.now(timezone.utc)

        safe_audit_log(
            session,
            user_id,
            display_name,
            AuditAction.APPROVE,
            AuditEntityType.USER,
            entity_id=str(user.id),
            entity_name=user.username,
            details={'action': 'approve'},
            **get_client_info(request)
        )

        session.commit()

        logger.info(f"User '{user.username}' approved by {display_name}")

        return {"message": f"User '{user.username}' approved"}


@router.delete("/{user_id}", dependencies=[Depends(require_capability("users.manage"))])
async def delete_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """
    Hard delete a user (requires users.manage capability).

    The audit log captures user info before deletion. FK cascades handle
    related data (memberships deleted, API keys orphaned via SET NULL).
    """
    # Get user info for audit (handles both session and API key auth)
    # NOTE: user_id path param = target; audit user_id = acting user
    target_user_id = user_id
    user_id, display_name = get_auditable_user_info(current_user)

    with db.get_session() as session:
        user = get_user_or_404(session, target_user_id)

        # Prevent self-deletion (applies to both session and API key auth)
        acting_user_id = current_user.get("user_id") or current_user.get("created_by_user_id")
        if acting_user_id == target_user_id:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete your own account"
            )

        # Prevent deleting the last admin
        ensure_not_last_admin(session, target_user_id, "delete")

        # Capture info before deletion for audit and response
        username = user.username
        email = user.email

        # Audit log BEFORE delete (captures user info while row still exists)
        safe_audit_log(
            session,
            user_id,
            display_name,
            AuditAction.DELETE,
            AuditEntityType.USER,
            entity_id=str(user.id),
            entity_name=username,
            details={'username': username, 'email': email},
            **get_client_info(request)
        )

        # Hard delete — FK cascades handle related data
        session.delete(user)
        session.flush()
        verify_critical_capabilities(session)
        session.commit()

        # Evict sessions and invalidate caches AFTER commit
        # (avoids logging out a user if the delete fails)
        evicted = cookie_session_manager.delete_sessions_for_user(target_user_id)
        if evicted:
            logger.info(f"Evicted {evicted} active session(s) for deleted user '{username}'")
        invalidate_user_groups_cache(target_user_id)

        logger.info(f"User '{username}' deleted by {display_name}")

        return {"message": f"User '{username}' has been deleted"}


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
    # NOTE: user_id path param = target; audit user_id = acting user
    target_user_id = user_id
    user_id, display_name = get_auditable_user_info(current_user)

    with db.get_session() as session:
        user = get_user_or_404(session, target_user_id)

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

        # Terminate all existing sessions for the target user
        evicted = cookie_session_manager.delete_sessions_for_user(target_user_id)
        if evicted:
            logger.info(f"Evicted {evicted} session(s) for user '{user.username}' after password reset")

        logger.info(f"Password reset for user '{user.username}' by {display_name}")

        return {
            "message": f"Password reset for user '{user.username}'",
            "temporary_password": new_password if not password_data.new_password else None,
            "must_change_password": True
        }
