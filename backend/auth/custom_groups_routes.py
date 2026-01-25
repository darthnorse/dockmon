"""
Custom Groups Management API (v2.3.0 Phase 5)

Provides endpoints for managing custom user groups.
Groups are organizational units that users can be assigned to.
Admin-only endpoints for CRUD operations on groups and membership.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import aliased

from auth.api_key_auth import (
    require_capability,
    get_current_user_or_api_key,
    invalidate_group_permissions_cache,
    invalidate_user_groups_cache,
)
from auth.shared import db
from database import CustomGroup, UserGroupMembership, User, ApiKey, GroupPermission
from audit.audit_logger import log_audit
from auth.capabilities import ALL_CAPABILITIES, CAPABILITY_INFO


router = APIRouter(prefix="/api/v2/groups", tags=["groups"])


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


# =============================================================================
# Request/Response Models
# =============================================================================

class GroupMemberResponse(BaseModel):
    """User in a group"""
    user_id: int
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: str
    added_at: str
    added_by: Optional[str] = None


class GroupResponse(BaseModel):
    """Group with metadata"""
    id: int
    name: str
    description: Optional[str] = None
    is_system: bool = False
    member_count: int
    created_at: str
    created_by: Optional[str] = None
    updated_at: str


class GroupDetailResponse(BaseModel):
    """Group with full member list"""
    id: int
    name: str
    description: Optional[str] = None
    is_system: bool = False
    members: list[GroupMemberResponse]
    created_at: str
    created_by: Optional[str] = None
    updated_at: str


class GroupListResponse(BaseModel):
    """List of groups"""
    groups: list[GroupResponse]
    total: int


class CreateGroupRequest(BaseModel):
    """Request to create a new group"""
    name: str
    description: Optional[str] = None


class UpdateGroupRequest(BaseModel):
    """Request to update a group"""
    name: Optional[str] = None
    description: Optional[str] = None


class AddMemberRequest(BaseModel):
    """Request to add a member to a group"""
    user_id: int


class AddMemberResponse(BaseModel):
    """Response when adding a member"""
    success: bool
    message: str


class RemoveMemberResponse(BaseModel):
    """Response when removing a member"""
    success: bool
    message: str


class DeleteGroupResponse(BaseModel):
    """Response when deleting a group"""
    success: bool
    message: str


class GroupPermissionResponse(BaseModel):
    """Permission for a group"""
    capability: str
    allowed: bool
    category: str
    display_name: str
    description: str


class GroupPermissionsListResponse(BaseModel):
    """List of permissions for a group"""
    group_id: int
    group_name: str
    permissions: list[GroupPermissionResponse]


class PermissionUpdateRequest(BaseModel):
    """Request to update a single permission"""
    capability: str
    allowed: bool


class UpdatePermissionsRequest(BaseModel):
    """Request to update group permissions"""
    permissions: list[PermissionUpdateRequest]


class UpdatePermissionsResponse(BaseModel):
    """Response after updating permissions"""
    updated: int  # Number of permissions updated (matches frontend expectation)
    message: str


# =============================================================================
# Constants
# =============================================================================

MAX_GROUP_NAME_LENGTH = 100
MAX_GROUP_DESCRIPTION_LENGTH = 500


# =============================================================================
# Helper Functions
# =============================================================================

def _get_username_by_id(session, user_id: int) -> Optional[str]:
    """Get username by user ID"""
    if user_id is None:
        return None
    user = session.query(User).filter(User.id == user_id).first()
    return user.username if user else None


def _validate_group_name(name: str) -> str:
    """Validate and sanitize group name. Returns sanitized name or raises HTTPException."""
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Group name cannot be empty")

    sanitized = name.strip()

    if len(sanitized) > MAX_GROUP_NAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Group name cannot exceed {MAX_GROUP_NAME_LENGTH} characters"
        )

    return sanitized


def _validate_group_description(description: Optional[str]) -> Optional[str]:
    """Validate and sanitize group description. Returns sanitized description."""
    if description is None:
        return None

    sanitized = description.strip()
    if not sanitized:
        return None

    if len(sanitized) > MAX_GROUP_DESCRIPTION_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Group description cannot exceed {MAX_GROUP_DESCRIPTION_LENGTH} characters"
        )

    return sanitized


def _format_datetime(dt: datetime) -> Optional[str]:
    """Format datetime for API response with Z suffix"""
    if dt is None:
        return None
    iso = dt.isoformat()
    return iso if iso.endswith('Z') else iso + 'Z'


def _get_group_members(session, group_id: int) -> list[GroupMemberResponse]:
    """Get all members of a group with user details. Avoids N+1 queries."""
    memberships = session.query(UserGroupMembership, User).join(
        User, UserGroupMembership.user_id == User.id
    ).filter(
        UserGroupMembership.group_id == group_id
    ).all()

    if not memberships:
        return []

    # Prefetch all added_by usernames to avoid N+1 queries
    added_by_ids = {m.added_by for m, _ in memberships if m.added_by is not None}
    if added_by_ids:
        adders = session.query(User.id, User.username).filter(User.id.in_(added_by_ids)).all()
        adder_map = {user_id: username for user_id, username in adders}
    else:
        adder_map = {}

    members = []
    for membership, user in memberships:
        members.append(GroupMemberResponse(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            role=user.role,
            added_at=_format_datetime(membership.added_at),
            added_by=adder_map.get(membership.added_by) if membership.added_by else None,
        ))

    return members


# =============================================================================
# Endpoints
# =============================================================================

@router.get("", response_model=GroupListResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def list_groups(
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    List all custom groups.

    Returns groups with member counts.
    Requires groups.manage capability.
    """
    with db.get_session() as session:
        groups = session.query(CustomGroup).all()

        # Get member counts for each group in a single query
        count_results = session.query(
            UserGroupMembership.group_id,
            func.count(UserGroupMembership.id)
        ).group_by(UserGroupMembership.group_id).all()
        count_map = {group_id: count for group_id, count in count_results}

        # Prefetch all usernames for created_by to avoid N+1 queries
        creator_ids = {g.created_by for g in groups if g.created_by is not None}
        if creator_ids:
            creators = session.query(User.id, User.username).filter(User.id.in_(creator_ids)).all()
            username_map = {user_id: username for user_id, username in creators}
        else:
            username_map = {}

        group_responses = []
        for group in groups:
            group_responses.append(GroupResponse(
                id=group.id,
                name=group.name,
                description=group.description,
                is_system=group.is_system,
                member_count=count_map.get(group.id, 0),
                created_at=_format_datetime(group.created_at),
                created_by=username_map.get(group.created_by) if group.created_by else None,
                updated_at=_format_datetime(group.updated_at),
            ))

        return GroupListResponse(
            groups=group_responses,
            total=len(group_responses)
        )


@router.post("", response_model=GroupResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def create_group(
    request: CreateGroupRequest,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Create a new custom group.

    Requires groups.manage capability.
    """
    # Validate and sanitize inputs
    sanitized_name = _validate_group_name(request.name)
    sanitized_description = _validate_group_description(request.description)

    with db.get_session() as session:
        # Check if group name already exists
        existing = session.query(CustomGroup).filter(
            func.lower(CustomGroup.name) == func.lower(sanitized_name)
        ).first()

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Group with name '{sanitized_name}' already exists"
            )

        now = datetime.now(timezone.utc)
        user_id, display_name = _get_auditable_user_info(current_user)

        new_group = CustomGroup(
            name=sanitized_name,
            description=sanitized_description,
            created_by=user_id,
            updated_by=user_id,
            created_at=now,
            updated_at=now,
        )

        session.add(new_group)
        session.flush()

        # Audit log (before commit for atomicity)
        log_audit(
            session,
            user_id=user_id,
            username=display_name,
            action='create',
            entity_type='custom_group',
            entity_id=str(new_group.id),
            entity_name=new_group.name,
            details={'description': new_group.description},
        )

        session.commit()
        session.refresh(new_group)

        return GroupResponse(
            id=new_group.id,
            name=new_group.name,
            description=new_group.description,
            is_system=new_group.is_system,
            member_count=0,
            created_at=_format_datetime(new_group.created_at),
            created_by=display_name,
            updated_at=_format_datetime(new_group.updated_at),
        )


@router.get("/{group_id}", response_model=GroupDetailResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def get_group(
    group_id: int,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Get a group with its members.

    Requires groups.manage capability.
    """
    with db.get_session() as session:
        # Fetch group with creator username in one query
        Creator = aliased(User)
        result = session.query(CustomGroup, Creator.username).outerjoin(
            Creator, CustomGroup.created_by == Creator.id
        ).filter(CustomGroup.id == group_id).first()

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID {group_id} not found"
            )

        group, creator_username = result

        return GroupDetailResponse(
            id=group.id,
            name=group.name,
            description=group.description,
            is_system=group.is_system,
            members=_get_group_members(session, group_id),
            created_at=_format_datetime(group.created_at),
            created_by=creator_username,
            updated_at=_format_datetime(group.updated_at),
        )


@router.put("/{group_id}", response_model=GroupResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def update_group(
    group_id: int,
    request: UpdateGroupRequest,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Update a group.

    Requires groups.manage capability.
    """
    # Validate and sanitize inputs
    sanitized_name = _validate_group_name(request.name) if request.name is not None else None
    sanitized_description = _validate_group_description(request.description) if request.description is not None else None

    with db.get_session() as session:
        group = session.query(CustomGroup).filter(CustomGroup.id == group_id).first()

        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID {group_id} not found"
            )

        # Check name uniqueness if changing
        if sanitized_name and sanitized_name.lower() != group.name.lower():
            existing = session.query(CustomGroup).filter(
                func.lower(CustomGroup.name) == func.lower(sanitized_name),
                CustomGroup.id != group_id
            ).first()

            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Group with name '{sanitized_name}' already exists"
                )

        # Update fields
        changes = {}
        if sanitized_name is not None:
            changes['name'] = {'old': group.name, 'new': sanitized_name}
            group.name = sanitized_name

        if request.description is not None:
            changes['description'] = {'old': group.description, 'new': sanitized_description}
            group.description = sanitized_description

        now = datetime.now(timezone.utc)
        user_id, display_name = _get_auditable_user_info(current_user)

        group.updated_by = user_id
        group.updated_at = now

        # Get member count
        member_count = session.query(UserGroupMembership).filter(
            UserGroupMembership.group_id == group_id
        ).count()

        # Audit log (before commit for atomicity)
        if changes:
            log_audit(
                session,
                user_id=user_id,
                username=display_name,
                action='update',
                entity_type='custom_group',
                entity_id=str(group.id),
                entity_name=group.name,
                details={'changes': changes},
            )

        session.commit()
        session.refresh(group)

        return GroupResponse(
            id=group.id,
            name=group.name,
            description=group.description,
            is_system=group.is_system,
            member_count=member_count,
            created_at=_format_datetime(group.created_at),
            created_by=_get_username_by_id(session, group.created_by),
            updated_at=_format_datetime(group.updated_at),
        )


@router.delete("/{group_id}", response_model=DeleteGroupResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def delete_group(
    group_id: int,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Delete a group.

    All memberships are automatically removed (cascade).
    Requires groups.manage capability.

    Blocked if:
    - Group is a system group (is_system=True)
    - Group has API keys assigned (would violate FK constraint)
    - Any user would be left with no groups after deletion
    """
    with db.get_session() as session:
        group = session.query(CustomGroup).filter(CustomGroup.id == group_id).first()

        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID {group_id} not found"
            )

        # Phase 4: Prevent deletion of system groups
        if group.is_system:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete system group '{group.name}'"
            )

        # Phase 4: Check for API keys (gives friendly error vs raw DB constraint)
        api_key_count = session.query(ApiKey).filter_by(group_id=group_id).count()
        if api_key_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete group with {api_key_count} API key(s) assigned. "
                       "Reassign or delete the API keys first."
            )

        # Phase 4: Check for users who would be left with zero groups
        memberships = session.query(UserGroupMembership).filter_by(group_id=group_id).all()
        users_with_only_this_group = []

        for membership in memberships:
            other_groups = session.query(UserGroupMembership).filter(
                UserGroupMembership.user_id == membership.user_id,
                UserGroupMembership.group_id != group_id
            ).count()
            if other_groups == 0:
                user = session.query(User).filter(User.id == membership.user_id).first()
                if user:
                    users_with_only_this_group.append(user.username)

        if users_with_only_this_group:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete group - these users would have no groups: "
                       f"{', '.join(users_with_only_this_group)}. "
                       "Assign them to another group first."
            )

        group_name = group.name
        member_count = len(memberships)
        user_id, display_name = _get_auditable_user_info(current_user)

        # Audit log (before commit for atomicity)
        log_audit(
            session,
            user_id=user_id,
            username=display_name,
            action='delete',
            entity_type='custom_group',
            entity_id=str(group_id),
            entity_name=group_name,
            details={'member_count': member_count},
        )

        # Delete group (memberships cascade)
        session.delete(group)
        session.commit()

        # Phase 4: Invalidate caches
        invalidate_group_permissions_cache()
        invalidate_user_groups_cache()  # All users, since we don't know who was affected

        return DeleteGroupResponse(
            success=True,
            message=f"Deleted group '{group_name}' with {member_count} member(s)"
        )


@router.post("/{group_id}/members", response_model=AddMemberResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def add_member(
    group_id: int,
    request: AddMemberRequest,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Add a user to a group.

    Requires groups.manage capability.
    """
    with db.get_session() as session:
        # Check group exists
        group = session.query(CustomGroup).filter(CustomGroup.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID {group_id} not found"
            )

        # Check user exists and is not deleted
        user = session.query(User).filter(
            User.id == request.user_id,
            User.deleted_at.is_(None)
        ).first()

        if not user:
            raise HTTPException(
                status_code=404,
                detail=f"User with ID {request.user_id} not found or is deactivated"
            )

        # Check if already a member
        existing = session.query(UserGroupMembership).filter(
            UserGroupMembership.group_id == group_id,
            UserGroupMembership.user_id == request.user_id
        ).first()

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"User '{user.username}' is already a member of group '{group.name}'"
            )

        # Add membership
        now = datetime.now(timezone.utc)
        user_id, display_name = _get_auditable_user_info(current_user)
        membership = UserGroupMembership(
            user_id=request.user_id,
            group_id=group_id,
            added_by=user_id,
            added_at=now,
        )

        session.add(membership)

        # Audit log (before commit for atomicity)
        log_audit(
            session,
            user_id=user_id,
            username=display_name,
            action='add_member',
            entity_type='custom_group',
            entity_id=str(group_id),
            entity_name=group.name,
            details={'member_user_id': request.user_id, 'member_username': user.username},
        )

        session.commit()

        # Phase 4: Invalidate user's group cache
        invalidate_user_groups_cache(request.user_id)

        return AddMemberResponse(
            success=True,
            message=f"Added user '{user.username}' to group '{group.name}'"
        )


@router.delete("/{group_id}/members/{user_id}", response_model=RemoveMemberResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def remove_member(
    group_id: int,
    user_id: int,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Remove a user from a group.

    Requires groups.manage capability.

    Blocked if this is the user's last group (would leave them with no groups).
    """
    with db.get_session() as session:
        # Check group exists
        group = session.query(CustomGroup).filter(CustomGroup.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID {group_id} not found"
            )

        # Check membership exists
        membership = session.query(UserGroupMembership).filter(
            UserGroupMembership.group_id == group_id,
            UserGroupMembership.user_id == user_id
        ).first()

        if not membership:
            raise HTTPException(
                status_code=404,
                detail=f"User is not a member of group '{group.name}'"
            )

        # Phase 4: Check if this is the user's last group
        group_count = session.query(UserGroupMembership).filter_by(user_id=user_id).count()
        if group_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove user from their last group"
            )

        # Get username for audit
        user = session.query(User).filter(User.id == user_id).first()
        member_username = user.username if user else f"user_{user_id}"
        user_id, display_name = _get_auditable_user_info(current_user)

        # Audit log (before commit for atomicity)
        log_audit(
            session,
            user_id=user_id,
            username=display_name,
            action='remove_member',
            entity_type='custom_group',
            entity_id=str(group_id),
            entity_name=group.name,
            details={'member_user_id': user_id, 'member_username': member_username},
        )

        # Remove membership
        session.delete(membership)
        session.commit()

        # Phase 4: Invalidate user's group cache
        invalidate_user_groups_cache(user_id)

        return RemoveMemberResponse(
            success=True,
            message=f"Removed user '{member_username}' from group '{group.name}'"
        )


@router.get("/{group_id}/members", response_model=list[GroupMemberResponse], dependencies=[Depends(require_capability("groups.manage"))])
async def list_group_members(
    group_id: int,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    List all members of a group.

    Requires groups.manage capability.
    """
    with db.get_session() as session:
        # Check group exists
        group = session.query(CustomGroup).filter(CustomGroup.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID {group_id} not found"
            )

        return _get_group_members(session, group_id)


# =============================================================================
# Group Permission Endpoints (Phase 4)
# =============================================================================

@router.get("/{group_id}/permissions", response_model=GroupPermissionsListResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def get_group_permissions(
    group_id: int,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Get all permissions for a group.

    Returns all capabilities with their allowed status.
    Includes capability metadata (category, display_name, description).

    Requires groups.manage capability.
    """
    with db.get_session() as session:
        # Check group exists
        group = session.query(CustomGroup).filter(CustomGroup.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID {group_id} not found"
            )

        # Get existing permissions for this group
        existing_perms = session.query(GroupPermission).filter_by(group_id=group_id).all()
        perm_map = {p.capability: p.allowed for p in existing_perms}

        # Build response with all capabilities and their status
        permissions = []
        for cap in sorted(ALL_CAPABILITIES):
            cap_info = CAPABILITY_INFO.get(cap, {})
            permissions.append(GroupPermissionResponse(
                capability=cap,
                allowed=perm_map.get(cap, False),  # Default to False if not set
                category=cap_info.get('category', 'Other'),
                display_name=cap_info.get('name', cap),
                description=cap_info.get('description', ''),
            ))

        return GroupPermissionsListResponse(
            group_id=group.id,
            group_name=group.name,
            permissions=permissions,
        )


@router.put("/{group_id}/permissions", response_model=UpdatePermissionsResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def update_group_permissions(
    group_id: int,
    request: UpdatePermissionsRequest,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Update permissions for a group.

    Accepts a list of permission updates. Each update specifies a capability
    and whether it should be allowed or denied.

    Requires groups.manage capability.
    """
    with db.get_session() as session:
        # Check group exists
        group = session.query(CustomGroup).filter(CustomGroup.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=404,
                detail=f"Group with ID {group_id} not found"
            )

        # Validate all capabilities exist
        for perm_update in request.permissions:
            if perm_update.capability not in ALL_CAPABILITIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown capability: {perm_update.capability}"
                )

        now = datetime.now(timezone.utc)
        updated_count = 0
        changes = []

        for perm_update in request.permissions:
            # Check if permission exists
            existing = session.query(GroupPermission).filter_by(
                group_id=group_id,
                capability=perm_update.capability
            ).first()

            if existing:
                if existing.allowed != perm_update.allowed:
                    changes.append({
                        'capability': perm_update.capability,
                        'old': existing.allowed,
                        'new': perm_update.allowed
                    })
                    existing.allowed = perm_update.allowed
                    existing.updated_at = now
                    updated_count += 1
            else:
                # Create new permission
                new_perm = GroupPermission(
                    group_id=group_id,
                    capability=perm_update.capability,
                    allowed=perm_update.allowed,
                    created_at=now,
                    updated_at=now,
                )
                session.add(new_perm)
                changes.append({
                    'capability': perm_update.capability,
                    'old': None,
                    'new': perm_update.allowed
                })
                updated_count += 1

        if changes:
            # Audit log
            user_id, display_name = _get_auditable_user_info(current_user)
            log_audit(
                session,
                user_id=user_id,
                username=display_name,
                action='update_permissions',
                entity_type='custom_group',
                entity_id=str(group_id),
                entity_name=group.name,
                details={'changes': changes},
            )

        session.commit()

        # Invalidate cache after permission changes
        invalidate_group_permissions_cache()

        return UpdatePermissionsResponse(
            updated=updated_count,
            message=f"Updated {updated_count} permission(s) for group '{group.name}'"
        )
