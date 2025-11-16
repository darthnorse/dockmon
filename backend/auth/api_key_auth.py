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
