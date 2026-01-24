"""
API Key Authentication for DockMon

Provides API key generation, validation, and hybrid authentication
supporting both cookie sessions (browsers) and API keys (automation).

SECURITY FEATURES:
- SHA256 key hashing (never stores plaintext)
- Mandatory scope enforcement (read/write/admin)
- Optional IP allowlists (with reverse proxy support)
- Optional expiration dates
- Usage tracking and audit logging
"""

import hashlib
import secrets
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Tuple
from ipaddress import ip_address, ip_network

from fastapi import Header, Cookie, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from database import ApiKey, User, DatabaseManager, RolePermission, GroupPermission, UserGroupMembership, CustomGroup
from sqlalchemy.orm import joinedload
from auth.cookie_sessions import cookie_session_manager
from auth.shared import db
from utils.client_ip import get_client_ip
from security.audit import security_audit

logger = logging.getLogger(__name__)

# Constants
BEARER_PREFIX = "Bearer "


def generate_api_key() -> Tuple[str, str, str]:
    """
    Generate cryptographically secure API key.

    Format: dockmon_<base64url>  (e.g., "dockmon_7xK9pQ2mL...")

    Returns:
        Tuple of (plaintext_key, key_hash, key_prefix)

    SECURITY:
    - 32 bytes (256 bits) of entropy
    - URL-safe base64 encoding
    - SHA256 hashing for storage
    - Prefix for UI display (first 20 chars)
    """
    # Generate 32 random bytes (256 bits of entropy)
    random_token = secrets.token_urlsafe(32)

    # Create full key with prefix
    plaintext_key = f"dockmon_{random_token}"

    # Hash for storage (NEVER store plaintext!)
    key_hash = hashlib.sha256(plaintext_key.encode()).hexdigest()

    # Prefix for identification (first 20 chars)
    key_prefix = plaintext_key[:20]  # "dockmon_7xK9pQ2mL..."

    return (plaintext_key, key_hash, key_prefix)


def validate_api_key(
    api_key: str,
    client_ip: str,
    db: DatabaseManager
) -> Optional[dict]:
    """
    Validate API key and return user context.

    Args:
        api_key: Plaintext API key from Authorization header
        client_ip: Client IP address (from get_client_ip())
        db: Database manager

    Returns:
        Dict with user context if valid, None otherwise

    Validation checks:
    1. Key format is valid (starts with "dockmon_")
    2. Hash exists in database
    3. Key not revoked
    4. Key not expired
    5. IP address allowed (if IP restrictions set)
    6. User account exists and active
    """
    # Basic format validation
    if not api_key or not api_key.startswith("dockmon_"):
        logger.warning(f"Invalid API key format from {client_ip}")
        security_audit.log_event(
            event_type="api_key_invalid_format",
            severity="warning",
            client_ip=client_ip,
            details={"reason": "Invalid API key format or missing dockmon_ prefix"}
        )
        return None

    # Hash the provided key
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Look up key in database
    with db.get_session() as session:
        api_key_record = session.query(ApiKey).filter(
            ApiKey.key_hash == key_hash
        ).first()

        if not api_key_record:
            logger.warning(f"API key not found (hash: {key_hash[:16]}...) from {client_ip}")
            security_audit.log_event(
                event_type="api_key_not_found",
                severity="warning",
                client_ip=client_ip,
                details={"key_hash_prefix": key_hash[:16]}
            )
            return None

        # Check if revoked
        if api_key_record.revoked_at is not None:
            logger.warning(f"Revoked API key used: {api_key_record.name} from {client_ip}")
            security_audit.log_event(
                event_type="api_key_revoked_used",
                severity="warning",
                client_ip=client_ip,
                details={
                    "api_key_id": api_key_record.id,
                    "api_key_name": api_key_record.name,
                    "revoked_at": api_key_record.revoked_at.isoformat() if api_key_record.revoked_at else None
                }
            )
            return None

        # Check if expired
        if api_key_record.expires_at is not None:
            # SQLite stores naive datetimes - make it timezone-aware for comparison
            expires_at_aware = api_key_record.expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires_at_aware:
                logger.warning(f"Expired API key used: {api_key_record.name} from {client_ip}")
                security_audit.log_event(
                    event_type="api_key_expired_used",
                    severity="warning",
                    client_ip=client_ip,
                    details={
                        "api_key_id": api_key_record.id,
                        "api_key_name": api_key_record.name,
                        "expired_at": api_key_record.expires_at.isoformat()
                    }
                )
                return None

        # Check IP restrictions (if configured)
        if api_key_record.allowed_ips:
            if not _check_ip_allowed(client_ip, api_key_record.allowed_ips):
                logger.warning(
                    f"API key {api_key_record.name} used from unauthorized IP: {client_ip}"
                )
                security_audit.log_event(
                    event_type="api_key_ip_blocked",
                    severity="warning",
                    client_ip=client_ip,
                    details={
                        "api_key_id": api_key_record.id,
                        "api_key_name": api_key_record.name,
                        "allowed_ips": api_key_record.allowed_ips
                    }
                )
                return None

        # Get group information (v2.4.0: API keys belong to groups, not users)
        if not api_key_record.group_id:
            logger.error(f"API key {api_key_record.id} has no group assigned")
            return None

        # Eager load group and created_by relationships
        group = session.query(CustomGroup).filter(CustomGroup.id == api_key_record.group_id).first()
        if not group:
            logger.error(f"API key {api_key_record.id} references non-existent group {api_key_record.group_id}")
            return None

        # Get created_by user info for audit trail
        created_by = session.query(User).filter(User.id == api_key_record.created_by_user_id).first()
        created_by_username = created_by.username if created_by else "unknown"

        # Update usage statistics
        api_key_record.last_used_at = datetime.now(timezone.utc)
        api_key_record.usage_count += 1
        session.commit()

        logger.info(f"API key validated: {api_key_record.name} (group: {group.name})")

        return {
            "api_key_id": api_key_record.id,
            "api_key_name": api_key_record.name,
            "group_id": group.id,
            "group_name": group.name,
            "created_by_user_id": api_key_record.created_by_user_id,
            "created_by_username": created_by_username,
            "auth_type": "api_key",
        }


def _check_ip_allowed(client_ip: str, allowed_ips: str) -> bool:
    """
    Check if client IP is in allowed list.

    Args:
        client_ip: Client IP address (e.g., "192.168.1.100")
        allowed_ips: Comma-separated IPs/CIDRs (e.g., "192.168.1.0/24,10.0.0.1")

    Returns:
        True if IP is allowed, False otherwise

    Examples:
        _check_ip_allowed("192.168.1.100", "192.168.1.0/24") → True
        _check_ip_allowed("10.0.0.5", "192.168.1.0/24") → False
        _check_ip_allowed("192.168.1.100", "192.168.1.100,10.0.0.1") → True
    """
    try:
        client_addr = ip_address(client_ip)
    except ValueError:
        logger.warning(f"Invalid client IP format: {client_ip}")
        return False

    for allowed in allowed_ips.split(','):
        allowed = allowed.strip()

        try:
            # Check if it's a CIDR range or single IP
            if '/' in allowed:
                network = ip_network(allowed, strict=False)
                if client_addr in network:
                    return True
            else:
                allowed_addr = ip_address(allowed)
                if client_addr == allowed_addr:
                    return True
        except ValueError:
            logger.warning(f"Invalid IP/CIDR in allowed_ips: {allowed}")
            continue

    return False


def _get_user_scopes(user_role: str) -> list[str]:
    """
    Map user role to scopes.

    Args:
        user_role: User role from User.role column

    Returns:
        List of scopes for this role

    Scope mapping:
        admin → ["admin"] (full access)
        user → ["read", "write"] (can manage containers)
        readonly → ["read"] (view-only)
        default → ["read"] (safe fallback)
    """
    role_map = {
        "admin": ["admin"],
        "user": ["read", "write"],
        "readonly": ["read"]
    }
    return role_map.get(user_role, ["read"])  # Safe default


async def get_current_user_or_api_key(
    request: Request,
    session_id: str = Cookie(None),
    authorization: str = Header(None)
) -> dict:
    """
    Hybrid authentication dependency - supports BOTH cookies and API keys.

    Priority:
    1. Try cookie session (existing browser auth)
    2. Try Authorization: Bearer header (API key)
    3. Raise 401 if both fail

    Args:
        request: FastAPI request object (for IP address)
        session_id: Session cookie (optional)
        authorization: Authorization header (optional)

    Returns:
        For session auth:
        - user_id: int
        - username: str
        - auth_type: "session"
        - groups: List[{id, name}] (v2.4.0: user's groups for UI)

        For API key auth:
        - api_key_id: int
        - api_key_name: str
        - group_id: int
        - group_name: str
        - created_by_user_id: int
        - created_by_username: str
        - auth_type: "api_key"

    Raises:
        HTTPException: 401 if authentication fails
    """
    # Get client IP (handles reverse proxy correctly)
    client_ip = get_client_ip(request)

    # Priority 1: Try cookie session (existing browser auth)
    if session_id:
        session_data = cookie_session_manager.validate_session(session_id, client_ip)
        if session_data:
            # Get user info for return value
            user_id = None
            username = None
            with db.get_session() as session:
                user = session.query(User).filter(User.id == session_data["user_id"]).first()
                if user:
                    user_id = user.id
                    username = user.username

            if user_id:
                # Get user's groups outside session (for API symmetry with API key auth)
                user_groups = get_user_groups(user_id)
                return {
                    "user_id": user_id,
                    "username": username,
                    "auth_type": "session",
                    "groups": user_groups,  # v2.4.0: Include groups for UI
                }

    # Priority 2: Try API key from Authorization header
    if authorization:
        if authorization.startswith(BEARER_PREFIX):
            api_key = authorization[len(BEARER_PREFIX):]  # Remove prefix

            # Validate API key
            key_data = validate_api_key(api_key, client_ip, db)
            if key_data:
                return key_data
        else:
            logger.warning(f"Invalid Authorization header format from {client_ip}")

    # Both methods failed
    logger.warning(f"Authentication failed from {client_ip}")
    raise HTTPException(
        status_code=401,
        detail="Not authenticated - provide session cookie or API key"
    )


def _check_auth_capability(current_user: dict, capability: str) -> bool:
    """
    Check if the authenticated user/API key has a specific capability.

    Handles both auth types:
    - API key: Checks the single group's permissions
    - Session: Checks union of all user's groups (union semantics)

    Args:
        current_user: Auth context from get_current_user_or_api_key()
        capability: Capability to check (e.g., 'containers.view')

    Returns:
        True if the auth context has the capability, False otherwise
    """
    if current_user.get("auth_type") == "api_key":
        group_id = current_user.get("group_id")
        if group_id:
            return has_capability_for_group(group_id, capability)
    else:
        user_id = current_user.get("user_id")
        if user_id:
            return has_capability_for_user(user_id, capability)
    return False


def _get_auth_identifier(current_user: dict, include_group: bool = False) -> str:
    """
    Build a human-readable identifier for logging/audit.

    Args:
        current_user: Auth context from get_current_user_or_api_key()
        include_group: Whether to include group name for API keys

    Returns:
        Identifier string like "User 'admin'" or "API key 'my-key' (group: operators)"
    """
    if current_user.get("auth_type") == "api_key":
        api_key_name = current_user.get("api_key_name", "unknown")
        if include_group:
            group_name = current_user.get("group_name", "unknown")
            return f"API key '{api_key_name}' (group: {group_name})"
        return f"API key '{api_key_name}'"
    return f"User '{current_user.get('username', 'unknown')}'"


def require_scope(required_scope: str):
    """
    Dependency factory for scope-based authorization.

    DEPRECATED: Use require_capability() instead for fine-grained control.
    This function is maintained for backwards compatibility.

    v2.4.0: Now uses group-based permissions internally.
    - "admin" scope maps to users.manage capability
    - "write" scope maps to containers.operate capability
    - "read" scope maps to containers.view capability

    Usage:
        Read operations (GET):
            No extra dependency needed - authentication is sufficient

        Write operations (POST/PUT/PATCH/DELETE):
            @app.post("/api/...", dependencies=[Depends(require_scope("write"))])

        Admin operations:
            @app.post("/api/...", dependencies=[Depends(require_scope("admin"))])

    Args:
        required_scope: Required scope ("read", "write", or "admin")

    Returns:
        Dependency function that checks scopes

    Raises:
        HTTPException: 403 if user lacks required scope
    """
    # Map scopes to representative capabilities for backwards compatibility
    SCOPE_TO_CAPABILITY = {
        "admin": "users.manage",
        "write": "containers.operate",
        "read": "containers.view",
    }

    async def check_scope(current_user: dict = Depends(get_current_user_or_api_key)):
        # Get the capability to check based on scope
        capability = SCOPE_TO_CAPABILITY.get(required_scope)
        if not capability:
            logger.warning(f"Unknown scope requested: {required_scope}")
            raise HTTPException(
                status_code=403,
                detail=f"Unknown scope: '{required_scope}'"
            )

        # Check capability using helper
        if _check_auth_capability(current_user, capability):
            return current_user

        # Get identifier for logging
        identifier = _get_auth_identifier(current_user)
        logger.warning(f"{identifier} denied scope {required_scope} (capability: {capability})")

        # Audit log scope violation
        security_audit.log_event(
            event_type="scope_violation",
            severity="warning",
            user_id=current_user.get("user_id") or current_user.get("created_by_user_id"),
            details={
                "identifier": identifier,
                "required_scope": required_scope,
                "mapped_capability": capability,
                "auth_type": current_user.get("auth_type"),
                "group_id": current_user.get("group_id"),
            }
        )

        raise HTTPException(
            status_code=403,
            detail=f"Insufficient permissions - requires '{required_scope}' scope"
        )

    return check_scope


# ==================== Capability-Based Authorization (v2.3.0) ====================
#
# Granular capability system for multi-user support.
# Maps capabilities to existing scope system for backward compatibility.
#


class Capabilities:
    """
    Capability name constants for type-safe authorization checks.

    Using these constants instead of string literals enables IDE autocomplete
    and catches typos at import time rather than runtime.

    Usage:
        from auth.api_key_auth import Capabilities, has_capability
        if has_capability(user_scopes, Capabilities.CONTAINERS_VIEW_ENV):
            ...
    """
    # Admin-only capabilities
    HOSTS_MANAGE = 'hosts.manage'
    GROUPS_MANAGE = 'groups.manage'
    STACKS_EDIT = 'stacks.edit'
    STACKS_VIEW_ENV = 'stacks.view_env'
    ALERTS_MANAGE = 'alerts.manage'
    NOTIFICATIONS_MANAGE = 'notifications.manage'
    REGISTRY_MANAGE = 'registry.manage'
    REGISTRY_VIEW = 'registry.view'
    AGENTS_MANAGE = 'agents.manage'
    SETTINGS_MANAGE = 'settings.manage'
    USERS_MANAGE = 'users.manage'
    AUDIT_VIEW = 'audit.view'
    CONTAINERS_SHELL = 'containers.shell'
    CONTAINERS_UPDATE = 'containers.update'
    CONTAINERS_VIEW_ENV = 'containers.view_env'
    HEALTHCHECKS_MANAGE = 'healthchecks.manage'
    POLICIES_MANAGE = 'policies.manage'
    APIKEYS_MANAGE_OTHER = 'apikeys.manage_other'

    # User capabilities (write scope)
    STACKS_DEPLOY = 'stacks.deploy'
    CONTAINERS_OPERATE = 'containers.operate'
    BATCH_CREATE = 'batch.create'
    TAGS_MANAGE = 'tags.manage'
    HEALTHCHECKS_TEST = 'healthchecks.test'
    APIKEYS_MANAGE_OWN = 'apikeys.manage_own'

    # Read-only capabilities
    HOSTS_VIEW = 'hosts.view'
    STACKS_VIEW = 'stacks.view'
    CONTAINERS_VIEW = 'containers.view'
    CONTAINERS_LOGS = 'containers.logs'
    ALERTS_VIEW = 'alerts.view'
    NOTIFICATIONS_VIEW = 'notifications.view'
    HEALTHCHECKS_VIEW = 'healthchecks.view'
    POLICIES_VIEW = 'policies.view'
    EVENTS_VIEW = 'events.view'
    BATCH_VIEW = 'batch.view'
    TAGS_VIEW = 'tags.view'
    AGENTS_VIEW = 'agents.view'


# Capability to minimum scope mapping
# 'admin' = admin only
# 'write' = user role and above (can manage containers)
# 'read' = readonly role and above (view-only)
CAPABILITY_SCOPES = {
    # Admin-only capabilities
    'hosts.manage': 'admin',
    'stacks.edit': 'admin',
    'stacks.view_env': 'write',          # .env files - User can view, Read-only cannot
    'alerts.manage': 'admin',
    'notifications.manage': 'admin',
    'registry.manage': 'admin',
    'registry.view': 'admin',           # Contains passwords
    'agents.manage': 'admin',
    'settings.manage': 'admin',
    'users.manage': 'admin',
    'groups.manage': 'admin',
    'audit.view': 'admin',
    'containers.shell': 'admin',
    'containers.update': 'admin',
    'containers.view_env': 'write',     # Env vars - User can view, Read-only cannot
    'healthchecks.manage': 'admin',
    'policies.manage': 'admin',
    'apikeys.manage_other': 'admin',

    # User capabilities (write scope)
    'stacks.deploy': 'write',
    'containers.operate': 'write',
    'batch.create': 'write',
    'tags.manage': 'write',
    'healthchecks.test': 'write',
    'apikeys.manage_own': 'write',

    # Read-only capabilities
    'hosts.view': 'read',
    'stacks.view': 'read',
    'containers.view': 'read',
    'containers.logs': 'read',
    'alerts.view': 'read',
    'notifications.view': 'read',       # Names only, not configs
    'healthchecks.view': 'read',
    'policies.view': 'read',
    'events.view': 'read',
    'batch.view': 'read',
    'tags.view': 'read',
    'agents.view': 'read',
}


# Role permissions cache for performance (invalidated on permission updates)
# Maps role -> {capability -> allowed}
# Thread-safe with lock to prevent race conditions in multi-threaded environment
_role_permissions_cache: dict[str, dict[str, bool]] = {}
_cache_loaded = False
_cache_lock = threading.Lock()


def _load_role_permissions_cache() -> None:
    """
    Load all role permissions into memory cache.

    Called once on first permission check, then cached.
    Cache should be invalidated when permissions are updated.
    Thread-safe: uses lock to prevent concurrent cache updates.
    """
    global _role_permissions_cache, _cache_loaded

    with _cache_lock:
        # Double-check after acquiring lock (another thread may have loaded)
        if _cache_loaded:
            return

        with db.get_session() as session:
            all_perms = session.query(RolePermission).all()
            new_cache: dict[str, dict[str, bool]] = {}

            for perm in all_perms:
                if perm.role not in new_cache:
                    new_cache[perm.role] = {}
                new_cache[perm.role][perm.capability] = perm.allowed

            _role_permissions_cache = new_cache
            _cache_loaded = True
            logger.debug(f"Loaded role permissions cache: {len(all_perms)} entries")


def invalidate_role_permissions_cache() -> None:
    """
    Invalidate the role permissions cache.

    Call this after updating role permissions in the database.
    Thread-safe: uses lock to prevent race conditions.
    """
    global _role_permissions_cache, _cache_loaded

    with _cache_lock:
        _role_permissions_cache = {}
        _cache_loaded = False
        logger.debug("Role permissions cache invalidated")


def has_capability_for_role(role: str, capability: str) -> bool:
    """
    Check if a role has a specific capability using database.

    Uses in-memory cache for performance.
    Thread-safe: cache access is protected by lock during load.

    Args:
        role: User's role ('admin', 'user', 'readonly')
        capability: Capability to check (e.g., 'hosts.manage')

    Returns:
        True if the role has the capability, False otherwise
    """
    # Load cache if not loaded (thread-safe check inside function)
    if not _cache_loaded:
        _load_role_permissions_cache()

    # Read from cache (safe after load completes)
    role_perms = _role_permissions_cache.get(role, {})
    return role_perms.get(capability, False)


def has_capability(user_scopes: list[str], capability: str, role: str = None) -> bool:
    """
    Check if user has a specific capability.

    Priority:
    1. If role is provided, use database-backed permission check (customizable)
    2. Otherwise, fall back to static scope-based check (backward compatibility)

    Args:
        user_scopes: List of user's scopes (e.g., ['admin'], ['read', 'write'], ['read'])
        capability: Capability to check (e.g., 'hosts.manage', 'containers.operate')
        role: Optional user role for database-backed check

    Returns:
        True if user has the capability, False otherwise
    """
    # If role is provided, use database-backed permission check
    if role:
        return has_capability_for_role(role, capability)

    # Fallback to static scope-based check (backward compatibility)
    # Admin scope grants all permissions
    if 'admin' in user_scopes:
        return True

    # Get required scope for this capability
    required_scope = CAPABILITY_SCOPES.get(capability)

    if required_scope is None:
        # Unknown capability - deny by default for security
        logger.warning(f"Unknown capability requested: {capability}")
        return False

    # Check scope hierarchy
    if required_scope == 'admin':
        # Only admin scope can access admin capabilities
        return False  # Already checked admin above
    elif required_scope == 'write':
        # Write scope required
        return 'write' in user_scopes
    elif required_scope == 'read':
        # Read scope required - write includes read
        return 'read' in user_scopes or 'write' in user_scopes

    return False


def require_capability(capability: str):
    """
    Dependency factory for capability-based authorization.

    v2.4.0: Now uses group-based permissions instead of role-based.

    Usage:
        @app.post("/api/...", dependencies=[Depends(require_capability("hosts.manage"))])

    Args:
        capability: Required capability (e.g., 'hosts.manage', 'containers.operate')

    Returns:
        Dependency function that checks capabilities

    Raises:
        HTTPException: 403 if user lacks required capability
    """
    async def check_capability(current_user: dict = Depends(get_current_user_or_api_key)):
        # Check capability using helper
        if _check_auth_capability(current_user, capability):
            return current_user

        # Get identifier for logging (include group for capability violations)
        identifier = _get_auth_identifier(current_user, include_group=True)
        logger.warning(f"{identifier} denied capability {capability}")

        security_audit.log_event(
            event_type="capability_violation",
            severity="warning",
            user_id=current_user.get("user_id") or current_user.get("created_by_user_id"),
            details={
                "identifier": identifier,
                "required_capability": capability,
                "auth_type": current_user.get("auth_type"),
                "group_id": current_user.get("group_id"),
            }
        )

        raise HTTPException(
            status_code=403,
            detail=f"Insufficient permissions - requires '{capability}' capability"
        )

    return check_capability


def get_user_capabilities(user_scopes: list[str], role: str = None) -> list[str]:
    """
    Get all capabilities available to a user based on their role/scopes.

    Useful for UI to know what features to show/hide.

    Args:
        user_scopes: List of user's scopes
        role: Optional user role for database-backed lookup

    Returns:
        List of capability names the user has access to
    """
    capabilities = []
    for capability in CAPABILITY_SCOPES:
        if has_capability(user_scopes, capability, role=role):
            capabilities.append(capability)
    return capabilities


# ==================== Group-Based Permissions (v2.4.0) ====================
#
# New group-based permission system replacing role-based permissions.
# Users can belong to multiple groups, getting union of all capabilities.
# API keys belong to exactly one group.
#

# Group permissions cache
# Maps group_id -> {capability -> allowed}
# Thread-safe: all reads and writes protected by RLock
_group_permissions_cache: dict[int, dict[str, bool]] = {}
_group_cache_loaded = False
_group_cache_lock = threading.RLock()  # RLock allows reentrant acquisition

# User groups cache
# Maps user_id -> [group_ids]
# Thread-safe: all reads and writes protected by RLock
_user_groups_cache: dict[int, list[int]] = {}
_user_groups_lock = threading.RLock()  # RLock allows reentrant acquisition


def _load_group_permissions_cache() -> None:
    """
    Load all group permissions into memory cache.

    Called once on first permission check, then cached.
    Cache should be invalidated when permissions are updated.
    Thread-safe: uses lock to prevent concurrent cache updates.
    """
    global _group_permissions_cache, _group_cache_loaded

    with _group_cache_lock:
        # Double-check after acquiring lock (another thread may have loaded)
        if _group_cache_loaded:
            return

        with db.get_session() as session:
            all_perms = session.query(GroupPermission).all()
            new_cache: dict[int, dict[str, bool]] = {}

            for perm in all_perms:
                if perm.group_id not in new_cache:
                    new_cache[perm.group_id] = {}
                new_cache[perm.group_id][perm.capability] = perm.allowed

            _group_permissions_cache = new_cache
            _group_cache_loaded = True
            logger.debug(f"Loaded group permissions cache: {len(all_perms)} entries")


def invalidate_group_permissions_cache() -> None:
    """
    Invalidate the group permissions cache.

    Call this after updating group permissions in the database.
    Thread-safe: uses lock to prevent race conditions.
    """
    global _group_permissions_cache, _group_cache_loaded

    with _group_cache_lock:
        _group_permissions_cache = {}
        _group_cache_loaded = False
        logger.debug("Group permissions cache invalidated")


def invalidate_user_groups_cache(user_id: int = None) -> None:
    """
    Invalidate user groups cache.

    Args:
        user_id: If provided, only invalidate that user's cache.
                 If None, invalidate all users' cache.

    Call this after:
    - User added to group
    - User removed from group
    - OIDC user groups synced
    """
    global _user_groups_cache

    with _user_groups_lock:
        if user_id is None:
            _user_groups_cache.clear()
            logger.debug("User groups cache invalidated (all users)")
        elif user_id in _user_groups_cache:
            del _user_groups_cache[user_id]
            logger.debug(f"User groups cache invalidated for user {user_id}")


def has_capability_for_group(group_id: int, capability: str) -> bool:
    """
    Check if a group has a specific capability.

    Uses in-memory cache for performance.
    Thread-safe: all cache access protected by RLock.

    Args:
        group_id: The group ID to check
        capability: Capability to check (e.g., 'hosts.manage')

    Returns:
        True if the group has the capability allowed, False otherwise
    """
    with _group_cache_lock:
        # Load cache if not loaded
        if not _group_cache_loaded:
            _load_group_permissions_cache()

        # Read from cache (protected by lock)
        group_perms = _group_permissions_cache.get(group_id, {})
        return group_perms.get(capability, False)


def get_user_group_ids(user_id: int) -> list[int]:
    """
    Get list of group IDs for a user (cached).

    Thread-safe: all cache access protected by RLock.

    Args:
        user_id: The user's ID

    Returns:
        List of group IDs the user belongs to
    """
    global _user_groups_cache

    with _user_groups_lock:
        # Check cache first (protected by lock)
        if user_id in _user_groups_cache:
            return _user_groups_cache[user_id].copy()  # Return copy to prevent external mutation

        # Load from database
        with db.get_session() as session:
            memberships = session.query(UserGroupMembership).filter_by(user_id=user_id).all()
            group_ids = [m.group_id for m in memberships]
            _user_groups_cache[user_id] = group_ids
            return group_ids.copy()  # Return copy to prevent external mutation


def has_capability_for_user(user_id: int, capability: str) -> bool:
    """
    Check if user has capability via any of their groups.

    Returns True if ANY group the user belongs to allows the capability.
    This implements union semantics - user gets combined permissions from all groups.

    Thread-safe: delegates to has_capability_for_group() which handles locking.

    Args:
        user_id: The user's ID
        capability: Capability to check (e.g., 'containers.view')

    Returns:
        True if any of the user's groups has the capability, False otherwise
    """
    # Get user's groups (thread-safe)
    group_ids = get_user_group_ids(user_id)

    # Check each group - if ANY allows, return True (union semantics)
    # has_capability_for_group() handles cache loading with proper locking
    for group_id in group_ids:
        if has_capability_for_group(group_id, capability):
            return True

    return False


def get_capabilities_for_group(group_id: int) -> list[str]:
    """
    Get list of capabilities for a group.

    Thread-safe: all cache access protected by RLock.

    Args:
        group_id: The group's ID

    Returns:
        List of capability names that are allowed for this group
    """
    with _group_cache_lock:
        # Load cache if not loaded
        if not _group_cache_loaded:
            _load_group_permissions_cache()

        group_perms = _group_permissions_cache.get(group_id, {})
        return [cap for cap, allowed in group_perms.items() if allowed]


def get_capabilities_for_user(user_id: int) -> list[str]:
    """
    Get union of all capabilities from user's groups.

    Thread-safe: delegates to get_capabilities_for_group() which handles locking.

    Args:
        user_id: The user's ID

    Returns:
        Sorted list of capability names the user has access to (union of all groups)
    """
    capabilities = set()
    # get_user_group_ids() and get_capabilities_for_group() handle locking
    for group_id in get_user_group_ids(user_id):
        capabilities.update(get_capabilities_for_group(group_id))

    return sorted(capabilities)


def get_user_groups(user_id: int) -> list[dict]:
    """
    Get list of groups for a user with id and name.

    Used for /me endpoint to return user's group information.

    Args:
        user_id: The user's ID

    Returns:
        List of dicts with 'id' and 'name' keys for each group
    """
    with db.get_session() as session:
        memberships = (
            session.query(UserGroupMembership)
            .options(joinedload(UserGroupMembership.group))
            .filter_by(user_id=user_id)
            .all()
        )
        return [{"id": m.group.id, "name": m.group.name} for m in memberships]
