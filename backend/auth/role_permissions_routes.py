"""
Role Permissions Management API (v2.3.0 Phase 5)

Provides endpoints for managing role-based permission customization.
Admin-only endpoints for viewing and modifying what each role can do.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.api_key_auth import require_capability, get_current_user_or_api_key, invalidate_role_permissions_cache
from auth.capabilities import CAPABILITY_INFO, ALL_CAPABILITIES
from auth.shared import db
from database import RolePermission
from audit.audit_logger import log_audit


router = APIRouter(prefix="/api/v2/roles", tags=["roles"])


# =============================================================================
# Constants
# =============================================================================

VALID_ROLES = ['admin', 'user', 'readonly']

# Default permissions for reset functionality (same as migration)
DEFAULT_PERMISSIONS = [
    # Admin capabilities (all allowed)
    ('admin', 'hosts.manage', True),
    ('admin', 'hosts.view', True),
    ('admin', 'stacks.edit', True),
    ('admin', 'stacks.deploy', True),
    ('admin', 'stacks.view', True),
    ('admin', 'stacks.view_env', True),
    ('admin', 'containers.operate', True),
    ('admin', 'containers.shell', True),
    ('admin', 'containers.update', True),
    ('admin', 'containers.view', True),
    ('admin', 'containers.logs', True),
    ('admin', 'containers.view_env', True),
    ('admin', 'healthchecks.manage', True),
    ('admin', 'healthchecks.test', True),
    ('admin', 'healthchecks.view', True),
    ('admin', 'batch.create', True),
    ('admin', 'batch.view', True),
    ('admin', 'policies.manage', True),
    ('admin', 'policies.view', True),
    ('admin', 'alerts.manage', True),
    ('admin', 'alerts.view', True),
    ('admin', 'notifications.manage', True),
    ('admin', 'notifications.view', True),
    ('admin', 'registry.manage', True),
    ('admin', 'registry.view', True),
    ('admin', 'agents.manage', True),
    ('admin', 'agents.view', True),
    ('admin', 'settings.manage', True),
    ('admin', 'users.manage', True),
    ('admin', 'oidc.manage', True),
    ('admin', 'groups.manage', True),
    ('admin', 'audit.view', True),
    ('admin', 'apikeys.manage_own', True),
    ('admin', 'apikeys.manage_other', True),
    ('admin', 'tags.manage', True),
    ('admin', 'tags.view', True),
    ('admin', 'events.view', True),

    # User capabilities (operators - can use, limited config)
    ('user', 'hosts.view', True),
    ('user', 'stacks.deploy', True),
    ('user', 'stacks.view', True),
    ('user', 'stacks.view_env', True),
    ('user', 'containers.operate', True),
    ('user', 'containers.view', True),
    ('user', 'containers.logs', True),
    ('user', 'containers.view_env', True),
    ('user', 'healthchecks.test', True),
    ('user', 'healthchecks.view', True),
    ('user', 'batch.create', True),
    ('user', 'batch.view', True),
    ('user', 'policies.view', True),
    ('user', 'alerts.view', True),
    ('user', 'notifications.view', True),
    ('user', 'agents.view', True),
    ('user', 'apikeys.manage_own', True),
    ('user', 'tags.manage', True),
    ('user', 'tags.view', True),
    ('user', 'events.view', True),

    # Readonly capabilities (view only)
    ('readonly', 'hosts.view', True),
    ('readonly', 'stacks.view', True),
    ('readonly', 'containers.view', True),
    ('readonly', 'containers.logs', True),
    ('readonly', 'healthchecks.view', True),
    ('readonly', 'batch.view', True),
    ('readonly', 'policies.view', True),
    ('readonly', 'alerts.view', True),
    ('readonly', 'notifications.view', True),
    ('readonly', 'agents.view', True),
    ('readonly', 'tags.view', True),
    ('readonly', 'events.view', True),
]

# Build default permissions lookup for quick access
DEFAULT_PERMISSIONS_SET = {(role, cap): allowed for role, cap, allowed in DEFAULT_PERMISSIONS}

# Pre-group default permissions by role for efficient reset
DEFAULT_PERMISSIONS_BY_ROLE: dict[str, list[tuple[str, bool]]] = {}
for _role, _cap, _allowed in DEFAULT_PERMISSIONS:
    if _role not in DEFAULT_PERMISSIONS_BY_ROLE:
        DEFAULT_PERMISSIONS_BY_ROLE[_role] = []
    DEFAULT_PERMISSIONS_BY_ROLE[_role].append((_cap, _allowed))

# ALL_CAPABILITIES imported from auth.capabilities


# =============================================================================
# Request/Response Models
# =============================================================================

class RolePermissionsResponse(BaseModel):
    """All role permissions grouped by role"""
    permissions: dict[str, dict[str, bool]]  # role -> capability -> allowed


class CapabilityInfo(BaseModel):
    """Capability metadata for UI display"""
    name: str
    capability: str
    category: str
    description: str


class CapabilitiesResponse(BaseModel):
    """All capabilities with metadata"""
    capabilities: list[CapabilityInfo]
    categories: list[str]


class PermissionUpdate(BaseModel):
    """Single permission update"""
    role: str
    capability: str
    allowed: bool


class UpdatePermissionsRequest(BaseModel):
    """Batch permission update request"""
    permissions: list[PermissionUpdate]


class UpdatePermissionsResponse(BaseModel):
    """Response for permission update"""
    updated: int
    message: str


class ResetPermissionsResponse(BaseModel):
    """Response for permissions reset"""
    deleted_count: int  # Number of old permissions deleted before reinserting defaults
    message: str


class ResetPermissionsRequest(BaseModel):
    """Request to reset permissions"""
    role: str | None = None  # If None, reset all roles


# =============================================================================
# Helper Functions
# =============================================================================

def _fill_missing_capabilities(permissions: dict[str, dict[str, bool]]) -> None:
    """Fill in missing capabilities with False for completeness."""
    for role in VALID_ROLES:
        for cap in ALL_CAPABILITIES:
            if cap not in permissions[role]:
                permissions[role][cap] = False


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Get all available capabilities with metadata.

    Returns capability names, categories, and descriptions for UI display.
    Available to all authenticated users (for feature visibility checks).
    """
    capabilities = []
    categories_set = set()

    for cap_name, info in CAPABILITY_INFO.items():
        capabilities.append(CapabilityInfo(
            name=info['name'],
            capability=cap_name,
            category=info['category'],
            description=info['description'],
        ))
        categories_set.add(info['category'])

    # Sort capabilities by category then name
    capabilities.sort(key=lambda c: (c.category, c.name))

    # Sort categories alphabetically
    categories = sorted(categories_set)

    return CapabilitiesResponse(
        capabilities=capabilities,
        categories=categories,
    )


@router.get("/permissions", response_model=RolePermissionsResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def get_role_permissions(
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Get all role permissions.

    Returns a mapping of role -> capability -> allowed for all roles.
    Admin only.
    """
    with db.get_session() as session:
        permissions: dict[str, dict[str, bool]] = {role: {} for role in VALID_ROLES}

        # Query all permissions
        all_perms = session.query(RolePermission).all()

        for perm in all_perms:
            if perm.role in permissions:
                permissions[perm.role][perm.capability] = perm.allowed

        _fill_missing_capabilities(permissions)

        return RolePermissionsResponse(permissions=permissions)


@router.put("/permissions", response_model=UpdatePermissionsResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def update_role_permissions(
    request: UpdatePermissionsRequest,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Update role permissions (batch).

    Updates multiple role-capability permissions at once.
    Admin only.
    """
    with db.get_session() as session:
        updated_count = 0

        for update in request.permissions:
            # Validate role
            if update.role not in VALID_ROLES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid role: {update.role}. Valid roles: {VALID_ROLES}"
                )

            # Validate capability
            if update.capability not in ALL_CAPABILITIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid capability: {update.capability}"
                )

            # Check if permission exists
            existing = session.query(RolePermission).filter(
                RolePermission.role == update.role,
                RolePermission.capability == update.capability
            ).first()

            if existing:
                # Update existing
                if existing.allowed != update.allowed:
                    existing.allowed = update.allowed
                    updated_count += 1
            else:
                # Create new
                new_perm = RolePermission(
                    role=update.role,
                    capability=update.capability,
                    allowed=update.allowed
                )
                session.add(new_perm)
                updated_count += 1

        # Audit log (before commit for atomicity)
        if updated_count > 0:
            log_audit(
                session,
                user_id=current_user.get('user_id'),
                username=current_user.get('username', 'unknown'),
                action='update',
                entity_type='role_permissions',
                entity_id=None,
                entity_name=f'{updated_count} permissions',
                details={'changes': [p.model_dump() for p in request.permissions]},
            )

        session.commit()

        # Invalidate cache so permission changes take effect immediately
        invalidate_role_permissions_cache()

        return UpdatePermissionsResponse(
            updated=updated_count,
            message=f"Updated {updated_count} permission(s)"
        )


@router.post("/permissions/reset", response_model=ResetPermissionsResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def reset_role_permissions(
    request: ResetPermissionsRequest,
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Reset role permissions to defaults.

    If role is specified in request body, only reset that role's permissions.
    If role is None, reset ALL permissions to defaults.
    Admin only.
    """
    role = request.role

    # Validate role if specified
    if role and role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role: {role}. Valid roles: {VALID_ROLES}"
        )

    # Determine which roles to reset
    roles_to_reset = [role] if role else VALID_ROLES

    with db.get_session() as session:
        deleted_count = 0

        for r in roles_to_reset:
            # Delete existing permissions for this role
            deleted = session.query(RolePermission).filter(RolePermission.role == r).delete()
            deleted_count += deleted

            # Re-insert default permissions using pre-grouped lookup
            for cap, allowed in DEFAULT_PERMISSIONS_BY_ROLE.get(r, []):
                new_perm = RolePermission(
                    role=r,
                    capability=cap,
                    allowed=allowed
                )
                session.add(new_perm)

        # Audit log (before commit for atomicity)
        log_audit(
            session,
            user_id=current_user.get('user_id'),
            username=current_user.get('username', 'unknown'),
            action='reset',
            entity_type='role_permissions',
            entity_id=None,
            entity_name=role or 'all roles',
            details={'roles_reset': roles_to_reset},
        )

        session.commit()

        # Invalidate cache so permission changes take effect immediately
        invalidate_role_permissions_cache()

        message = f"Reset permissions for role '{role}'" if role else "Reset all permissions to defaults"

        return ResetPermissionsResponse(
            deleted_count=deleted_count,
            message=message
        )


@router.get("/permissions/defaults", response_model=RolePermissionsResponse, dependencies=[Depends(require_capability("groups.manage"))])
async def get_default_permissions(
    current_user: dict = Depends(get_current_user_or_api_key)
):
    """
    Get default role permissions.

    Returns the default permission matrix (what reset would restore).
    Useful for comparing current state to defaults.
    Admin only.
    """
    permissions: dict[str, dict[str, bool]] = {role: {} for role in VALID_ROLES}

    # Build from default permissions
    for role, cap, allowed in DEFAULT_PERMISSIONS:
        permissions[role][cap] = allowed

    _fill_missing_capabilities(permissions)

    return RolePermissionsResponse(permissions=permissions)
