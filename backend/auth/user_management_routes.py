"""
DockMon User Management Routes - Admin-only User CRUD Operations

Phase 3 of Multi-User Support (v2.3.0)

SECURITY:
- All endpoints require admin role
- Soft delete preserves audit trail
- Password changes trigger must_change_password flag
"""

import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator, EmailStr
from argon2 import PasswordHasher

from auth.shared import db, safe_audit_log
from auth.api_key_auth import require_scope, get_current_user_or_api_key
from database import User
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

# Valid roles
VALID_ROLES = ["admin", "user", "readonly"]


# ==================== Request/Response Models ====================

class UserResponse(BaseModel):
    """User data returned to admin"""
    id: int
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    role: str
    auth_provider: str
    is_first_login: bool
    must_change_password: bool
    last_login: Optional[str] = None
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None
    is_deleted: bool


class UserListResponse(BaseModel):
    """List of users"""
    users: List[UserResponse]
    total: int


class CreateUserRequest(BaseModel):
    """Create a new user"""
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    email: Optional[EmailStr] = Field(None)
    display_name: Optional[str] = Field(None, max_length=100)
    role: str = Field(default="user")
    must_change_password: bool = Field(default=True)

    @field_validator('role')
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")
        return v

    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        # Basic username validation - alphanumeric, underscore, hyphen
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', v):
            raise ValueError("Username must start with a letter and contain only letters, numbers, underscores, and hyphens")
        return v


class UpdateUserRequest(BaseModel):
    """Update an existing user"""
    email: Optional[EmailStr] = Field(None)
    display_name: Optional[str] = Field(None, max_length=100)
    role: Optional[str] = None

    @field_validator('role')
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")
        return v


class ResetPasswordRequest(BaseModel):
    """Admin-initiated password reset"""
    new_password: Optional[str] = Field(None, min_length=8, max_length=128)


# ==================== Helper Functions ====================

def _format_timestamp(dt: Optional[datetime]) -> Optional[str]:
    """Format datetime to ISO string with 'Z' suffix for frontend."""
    if dt is None:
        return None
    return dt.isoformat() + 'Z'


def _format_timestamp_required(dt: Optional[datetime]) -> str:
    """Format datetime to ISO string, using now() if None."""
    if dt is None:
        return datetime.now(timezone.utc).isoformat() + 'Z'
    return dt.isoformat() + 'Z'


def _ensure_not_last_admin(session, user_id: int, action: str) -> None:
    """
    Raise HTTPException if the user is the last admin.

    Args:
        session: Database session
        user_id: ID of the user being modified
        action: Description for error message (e.g., "delete", "change role of")
    """
    user = session.query(User).filter(User.id == user_id).first()
    if user and user.role == 'admin':
        admin_count = session.query(User).filter(
            User.role == 'admin',
            User.deleted_at.is_(None),
            User.id != user_id
        ).count()
        if admin_count == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot {action}: this is the last admin user"
            )


def _user_to_response(user: User) -> UserResponse:
    """Convert User model to response"""
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        auth_provider=user.auth_provider,
        is_first_login=user.is_first_login,
        must_change_password=user.must_change_password,
        last_login=_format_timestamp(user.last_login),
        created_at=_format_timestamp_required(user.created_at),
        updated_at=_format_timestamp_required(user.updated_at),
        deleted_at=_format_timestamp(user.deleted_at),
        is_deleted=user.is_deleted
    )


# ==================== API Endpoints ====================

@router.get("", response_model=UserListResponse, dependencies=[Depends(require_scope("admin"))])
async def list_users(
    include_deleted: bool = False,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserListResponse:
    """
    List all users (admin only).

    Args:
        include_deleted: Include soft-deleted users in the list
    """
    with db.get_session() as session:
        query = session.query(User)

        if not include_deleted:
            query = query.filter(User.deleted_at.is_(None))

        users = query.order_by(User.created_at.desc()).all()

        return UserListResponse(
            users=[_user_to_response(u) for u in users],
            total=len(users)
        )


@router.post("", response_model=UserResponse, dependencies=[Depends(require_scope("admin"))])
async def create_user(
    user_data: CreateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserResponse:
    """
    Create a new user (admin only).

    Default behavior:
    - New users must change password on first login
    - Default role is 'user'
    - Auth provider is 'local'
    """
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

        # Hash password with Argon2id
        password_hash = ph.hash(user_data.password)

        # Create user
        new_user = User(
            username=user_data.username,
            password_hash=password_hash,
            email=user_data.email,
            display_name=user_data.display_name,
            role=user_data.role,
            auth_provider='local',
            is_first_login=True,
            must_change_password=user_data.must_change_password,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        session.add(new_user)
        session.flush()  # Get new_user.id for audit log

        # Audit log (before commit for atomicity)
        safe_audit_log(
            session,
            current_user['user_id'],
            current_user['username'],
            AuditAction.CREATE,
            AuditEntityType.USER,
            entity_id=str(new_user.id),
            entity_name=new_user.username,
            details={'role': user_data.role, 'must_change_password': user_data.must_change_password},
            **get_client_info(request)
        )

        session.commit()
        session.refresh(new_user)

        logger.info(f"User '{user_data.username}' created by admin '{current_user['username']}'")

        return _user_to_response(new_user)


@router.get("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_scope("admin"))])
async def get_user(
    user_id: int,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserResponse:
    """
    Get a specific user by ID (admin only).
    """
    with db.get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        return _user_to_response(user)


@router.put("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_scope("admin"))])
async def update_user(
    user_id: int,
    user_data: UpdateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserResponse:
    """
    Update a user (admin only).

    Only updates fields that are provided (partial update).
    Cannot change username (use separate endpoint if needed).
    """
    with db.get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

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

        # Update role if provided
        if user_data.role is not None:
            # Prevent removing the last admin
            if user.role == 'admin' and user_data.role != 'admin':
                _ensure_not_last_admin(session, user_id, "change role of")
            changes['role'] = {'old': user.role, 'new': user_data.role}
            user.role = user_data.role

        user.updated_at = datetime.now(timezone.utc)

        # Audit log (before commit for atomicity)
        if changes:
            safe_audit_log(
                session,
                current_user['user_id'],
                current_user['username'],
                AuditAction.UPDATE,
                AuditEntityType.USER,
                entity_id=str(user.id),
                entity_name=user.username,
                details={'changes': changes},
                **get_client_info(request)
            )

        session.commit()
        session.refresh(user)

        logger.info(f"User '{user.username}' updated by admin '{current_user['username']}': {changes}")

        return _user_to_response(user)


@router.delete("/{user_id}", dependencies=[Depends(require_scope("admin"))])
async def delete_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """
    Soft delete a user (admin only).

    Preserves audit trail by setting deleted_at timestamp.
    User cannot log in after deletion but records are preserved.
    """
    with db.get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        # Prevent self-deletion
        if user_id == current_user['user_id']:
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
        user.deleted_by = current_user['user_id']
        user.updated_at = datetime.now(timezone.utc)

        # Audit log (before commit for atomicity)
        safe_audit_log(
            session,
            current_user['user_id'],
            current_user['username'],
            AuditAction.DELETE,
            AuditEntityType.USER,
            entity_id=str(user.id),
            entity_name=user.username,
            **get_client_info(request)
        )

        session.commit()

        logger.info(f"User '{user.username}' deactivated by admin '{current_user['username']}'")

        return {"message": f"User '{user.username}' has been deactivated"}


@router.post("/{user_id}/reactivate", response_model=UserResponse, dependencies=[Depends(require_scope("admin"))])
async def reactivate_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> UserResponse:
    """
    Reactivate a soft-deleted user (admin only).
    """
    with db.get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

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
            current_user['user_id'],
            current_user['username'],
            AuditAction.UPDATE,
            AuditEntityType.USER,
            entity_id=str(user.id),
            entity_name=user.username,
            details={'action': 'reactivate'},
            **get_client_info(request)
        )

        session.commit()
        session.refresh(user)

        logger.info(f"User '{user.username}' reactivated by admin '{current_user['username']}'")

        return _user_to_response(user)


@router.post("/{user_id}/reset-password", dependencies=[Depends(require_scope("admin"))])
async def reset_user_password(
    user_id: int,
    password_data: ResetPasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_or_api_key)
) -> dict:
    """
    Reset a user's password (admin only).

    If new_password is provided, sets it directly.
    If not provided, generates a random password.

    Always sets must_change_password=True so user must change on next login.
    """
    with db.get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

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
            current_user['user_id'],
            current_user['username'],
            AuditAction.PASSWORD_CHANGE,
            AuditEntityType.USER,
            entity_id=str(user.id),
            entity_name=user.username,
            details={'admin_reset': True},
            **get_client_info(request)
        )

        session.commit()

        logger.info(f"Password reset for user '{user.username}' by admin '{current_user['username']}'")

        return {
            "message": f"Password reset for user '{user.username}'",
            "temporary_password": new_password if not password_data.new_password else None,
            "must_change_password": True
        }
