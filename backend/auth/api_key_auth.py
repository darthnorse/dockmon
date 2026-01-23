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
from datetime import datetime, timezone
from typing import Optional, Tuple
from ipaddress import ip_address, ip_network

from fastapi import Header, Cookie, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from database import ApiKey, User, DatabaseManager
from auth.cookie_sessions import cookie_session_manager
from auth.shared import db
from utils.client_ip import get_client_ip
from security.audit import security_audit

logger = logging.getLogger(__name__)


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

        # Get user information
        user = session.query(User).filter(User.id == api_key_record.user_id).first()
        if not user:
            logger.error(f"API key {api_key_record.id} references non-existent user {api_key_record.user_id}")
            return None

        # Update usage statistics
        api_key_record.last_used_at = datetime.now(timezone.utc)
        api_key_record.usage_count += 1
        session.commit()

        # Parse scopes
        scopes = [s.strip() for s in api_key_record.scopes.split(',')]

        logger.info(f"API key validated: {api_key_record.name} (user: {user.username})")

        return {
            "user_id": user.id,
            "username": user.username,
            "api_key_id": api_key_record.id,
            "api_key_name": api_key_record.name,
            "scopes": scopes,
            "auth_type": "api_key"
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
       - Derive scopes from User.role (not hardcoded)
    2. Try Authorization: Bearer header (API key)
    3. Raise 401 if both fail

    Args:
        request: FastAPI request object (for IP address)
        session_id: Session cookie (optional)
        authorization: Authorization header (optional)

    Returns:
        Dict with user context:
        - user_id: int
        - username: str
        - auth_type: "session" | "api_key"
        - scopes: List[str] (derived from role or API key)
        - api_key_id: int (for API keys only)
        - api_key_name: str (for API keys only)

    Raises:
        HTTPException: 401 if authentication fails
    """
    # Get client IP (handles reverse proxy correctly)
    client_ip = get_client_ip(request)

    # Priority 1: Try cookie session (existing browser auth)
    if session_id:
        session_data = cookie_session_manager.validate_session(session_id, client_ip)
        if session_data:
            # Derive scopes from User.role (not hardcoded)
            with db.get_session() as session:
                user = session.query(User).filter(User.id == session_data["user_id"]).first()
                if user:
                    user_scopes = _get_user_scopes(user.role)

                    return {
                        **session_data,
                        "auth_type": "session",
                        "scopes": user_scopes
                    }

    # Priority 2: Try API key from Authorization header
    if authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]  # Remove "Bearer " prefix

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


def require_scope(required_scope: str):
    """
    Dependency factory for scope-based authorization.

    SECURITY: This enforces scope requirements on endpoints.

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
    async def check_scope(current_user: dict = Depends(get_current_user_or_api_key)):
        user_scopes = current_user.get("scopes", [])

        # Admin scope grants all permissions
        if "admin" in user_scopes:
            return current_user

        # Check if user has required scope
        if required_scope not in user_scopes:
            logger.warning(
                f"User {current_user['username']} attempted {required_scope} operation "
                f"with scopes: {user_scopes}"
            )

            # Audit log scope violation
            security_audit.log_event(
                event_type="scope_violation",
                severity="warning",
                user_id=current_user.get("user_id"),
                details={
                    "username": current_user["username"],
                    "required_scope": required_scope,
                    "user_scopes": user_scopes,
                    "auth_type": current_user.get("auth_type")
                }
            )

            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions - requires '{required_scope}' scope"
            )

        return current_user

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


def has_capability(user_scopes: list[str], capability: str) -> bool:
    """
    Check if user has a specific capability.

    Uses scope hierarchy:
    - 'admin' scope grants ALL capabilities
    - 'write' scope grants write and read capabilities
    - 'read' scope grants only read capabilities

    Args:
        user_scopes: List of user's scopes (e.g., ['admin'], ['read', 'write'], ['read'])
        capability: Capability to check (e.g., 'hosts.manage', 'containers.operate')

    Returns:
        True if user has the capability, False otherwise
    """
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
        user_scopes = current_user.get("scopes", [])

        if has_capability(user_scopes, capability):
            return current_user

        # Log and audit the violation
        logger.warning(
            f"User {current_user['username']} denied capability {capability} "
            f"with scopes: {user_scopes}"
        )

        security_audit.log_event(
            event_type="capability_violation",
            severity="warning",
            user_id=current_user.get("user_id"),
            details={
                "username": current_user["username"],
                "required_capability": capability,
                "user_scopes": user_scopes,
                "auth_type": current_user.get("auth_type")
            }
        )

        raise HTTPException(
            status_code=403,
            detail=f"Insufficient permissions - requires '{capability}' capability"
        )

    return check_capability


def get_user_capabilities(user_scopes: list[str]) -> list[str]:
    """
    Get all capabilities available to a user based on their scopes.

    Useful for UI to know what features to show/hide.

    Args:
        user_scopes: List of user's scopes

    Returns:
        List of capability names the user has access to
    """
    capabilities = []
    for capability in CAPABILITY_SCOPES:
        if has_capability(user_scopes, capability):
            capabilities.append(capability)
    return capabilities
