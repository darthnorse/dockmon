"""
DockMon v2 Authentication Routes - Cookie-Based Sessions

SECURITY IMPROVEMENTS over v1:
1. HttpOnly cookies (XSS protection - JS can't access)
2. Secure flag (HTTPS only in production)
3. SameSite=lax (CSRF protection)
4. Argon2id password hashing (better than bcrypt)
5. IP validation (prevent session hijacking)
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import httpx
from fastapi import APIRouter, HTTPException, Response, Cookie, Request, Depends
from pydantic import BaseModel, Field, field_validator
import argon2
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from auth.password import ph

from auth.cookie_sessions import cookie_session_manager, get_session_cookie_max_age, should_set_secure_cookie
from utils.client_ip import get_client_ip, get_request_scheme
from security.rate_limiting import rate_limit_auth, get_rate_limit_dependency
from audit import log_login, log_logout, log_login_failure, AuditAction
from audit.audit_logger import get_client_info, log_audit, AuditEntityType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/auth", tags=["auth-v2"])


def _sanitize_for_log(value: str, max_length: int = 100) -> str:
    """
    Sanitize user input for safe logging.

    Prevents log injection attacks by:
    - Removing newlines and carriage returns
    - Limiting length to prevent log spam
    - Replacing control characters
    """
    if not value:
        return ""
    # Remove newlines and carriage returns, replace with space
    sanitized = value.replace('\n', ' ').replace('\r', ' ')
    # Truncate to max length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."
    return sanitized

# Import shared database instance (single connection pool)
from auth.shared import db
from database import User, OIDCConfig
from auth.api_key_auth import (
    get_current_user_or_api_key,
    get_user_groups,
    get_capabilities_for_user,
    get_capabilities_for_group,
)
from config.settings import AppConfig
from utils.base_path import get_base_path

# Account lockout constants (higher threshold + shorter lockout to mitigate DoS)
MAX_FAILED_ATTEMPTS = 10
LOCKOUT_DURATION_MINUTES = 5


# Dummy hash for constant-time rejection of unknown/OIDC users
_DUMMY_HASH = ph.hash("dummy-timing-constant")


def _verify_dummy(password: str) -> None:
    """Verify against dummy hash to maintain constant timing."""
    try:
        ph.verify(_DUMMY_HASH, password)
    except (VerifyMismatchError, InvalidHashError):
        pass


def verify_password(password: str, password_hash: str) -> tuple[bool, bool]:
    """Verify a password against an Argon2id or legacy bcrypt hash.

    Returns (is_valid, needs_rehash) tuple.
    """
    try:
        ph.verify(password_hash, password)
        return True, ph.check_needs_rehash(password_hash)
    except (VerifyMismatchError, InvalidHashError):
        pass

    # Fall back to bcrypt (v1 compatibility)
    try:
        import bcrypt
        if bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
            logger.info("User authenticated with legacy bcrypt hash")
            return True, True  # Always upgrade bcrypt -> Argon2id
    except Exception as bcrypt_error:
        logger.debug(f"bcrypt verification failed: {bcrypt_error}")

    return False, False


class LoginRequest(BaseModel):
    """Login credentials"""
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    """Login response"""
    user: dict
    message: str


class ChangePasswordRequest(BaseModel):
    """Change password request with validation"""
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class UpdateProfileRequest(BaseModel):
    """Update profile request with validation"""
    display_name: str | None = Field(None, max_length=128)
    username: str | None = None

    @field_validator('username')
    @classmethod
    def validate_username(cls, v):
        if v is None:
            return v
        if len(v) < 2 or len(v) > 64:
            raise ValueError('Username must be between 2 and 64 characters')
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', v):
            raise ValueError('Username must start with a letter and contain only letters, numbers, underscores, and hyphens')
        return v


class LogoutResponse(BaseModel):
    """Logout response"""
    message: str
    oidc_logout_url: str | None = None


class UserGroupInfo(BaseModel):
    """User's group membership info"""
    id: int
    name: str


class SessionUserInfo(BaseModel):
    """User info for session auth"""
    id: int
    username: str
    display_name: str | None = None
    is_first_login: bool = False
    must_change_password: bool = False
    auth_provider: str = 'local'
    groups: list[UserGroupInfo]


class ApiKeyInfo(BaseModel):
    """API key info for API key auth"""
    id: int
    name: str
    group_id: int
    group_name: str
    created_by_username: str | None = None


class CurrentUserSessionResponse(BaseModel):
    """Response for /me endpoint with session auth"""
    auth_type: str = "session"
    user: SessionUserInfo
    capabilities: list[str]


class CurrentUserApiKeyResponse(BaseModel):
    """Response for /me endpoint with API key auth"""
    auth_type: str = "api_key"
    api_key: ApiKeyInfo
    capabilities: list[str]


class ChangePasswordResponse(BaseModel):
    """Change password response"""
    success: bool
    message: str


class UpdateProfileResponse(BaseModel):
    """Update profile response"""
    success: bool
    message: str
    changes: dict | None = None


@router.post("/login", response_model=LoginResponse)
async def login_v2(
    credentials: LoginRequest,
    response: Response,
    request: Request,
    rate_limit_check: bool = rate_limit_auth
) -> LoginResponse:
    """
    Authenticate user and create session cookie.

    SECURITY:
    - Argon2id password verification (GPU-resistant)
    - HttpOnly cookie (XSS protection)
    - Secure flag for HTTPS (in production)
    - SameSite=lax (CSRF protection for cross-site POST)
    - IP binding (session hijack prevention)

    Returns:
        User data and session cookie
    """
    with db.get_session() as session:
        user = session.query(User).filter(
            User.username == credentials.username,
        ).first()

        if not user:
            _verify_dummy(credentials.password)
            safe_username = _sanitize_for_log(credentials.username)
            reason = "user_not_found"
            logger.warning(f"Login failed: user '{safe_username}' not found")

            try:
                log_login_failure(session, credentials.username, request, reason)
                session.commit()
            except Exception as audit_err:
                logger.warning(f"Failed to log audit entry: {audit_err}")
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        # Block OIDC users from local login (constant-time rejection)
        if user.auth_provider == 'oidc':
            _verify_dummy(credentials.password)
            safe_username = _sanitize_for_log(credentials.username)
            logger.warning(f"Login failed: OIDC user '{safe_username}' attempted local login")
            try:
                log_login_failure(session, credentials.username, request, "oidc_user_local_attempt")
                session.commit()
            except Exception as audit_err:
                logger.warning(f"Failed to log audit entry: {audit_err}")
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        # Check account lockout
        if user.locked_until and user.locked_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
            _verify_dummy(credentials.password)
            safe_username = _sanitize_for_log(credentials.username)
            logger.warning(f"Login failed: account '{safe_username}' is locked")
            try:
                log_login_failure(session, credentials.username, request, "account_locked")
                session.commit()
            except Exception as audit_err:
                logger.warning(f"Failed to log audit entry: {audit_err}")
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        # Verify password (with backward compatibility for bcrypt)
        password_valid, needs_upgrade = verify_password(credentials.password, user.password_hash)

        if not password_valid:
            # Increment failed login attempts + audit in single commit
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                logger.warning(f"Account '{user.username}' locked after {user.failed_login_attempts} failed attempts")

            safe_username = _sanitize_for_log(credentials.username)
            logger.warning(f"Login failed: invalid password for user '{safe_username}'")
            try:
                log_login_failure(session, credentials.username, request, "invalid_password")
            except Exception as audit_err:
                logger.warning(f"Failed to log audit entry: {audit_err}")
            session.commit()
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        # Successful login - reset failed attempts and upgrade hash if needed
        if user.failed_login_attempts or user.locked_until:
            user.failed_login_attempts = 0
            user.locked_until = None

        # Upgrade to Argon2id if needed (bcrypt -> Argon2id or old Argon2id params)
        if needs_upgrade:
            user.password_hash = ph.hash(credentials.password)
            logger.info(f"Password hash upgraded to Argon2id for user '{user.username}'")
            # Flag weak legacy passwords for mandatory change
            if len(credentials.password) < 8:
                user.must_change_password = True
                logger.info(f"User '{user.username}' flagged to change sub-policy-length password")

        # Commit counter reset + hash upgrade atomically (before session creation)
        session.commit()

        # Create session
        client_ip = get_client_ip(request)
        signed_token = cookie_session_manager.create_session(
            user_id=user.id,
            username=user.username,
            client_ip=client_ip,
            display_name=user.effective_display_name
        )

        response.set_cookie(
            key="session_id",
            value=signed_token,
            httponly=True,
            secure=should_set_secure_cookie(request),
            samesite="lax",
            max_age=get_session_cookie_max_age(),
            path="/",
            domain=None
        )

        logger.info(f"User '{user.username}' logged in successfully from {client_ip}")

        # Audit: Log successful login
        try:
            log_login(session, user.id, user.effective_display_name, request, auth_method='local')
            session.commit()
        except Exception as audit_err:
            logger.warning(f"Failed to log audit entry: {audit_err}")

        return LoginResponse(
            user={
                "id": user.id,
                "username": user.username,
                "is_first_login": user.is_first_login
            },
            message="Login successful"
        )


@router.post("/logout", response_model=LogoutResponse,
             dependencies=[Depends(get_rate_limit_dependency("auth"))])
async def logout_v2(
    response: Response,
    request: Request,
    session_id: str = Cookie(None)
) -> LogoutResponse:
    """
    Logout user and delete session.

    SECURITY: Session is deleted server-side.
    For OIDC users, returns the provider's end_session_endpoint URL
    so the frontend can redirect to end the provider session too.
    """
    user_id = None
    username = "unknown"
    is_oidc_user = False

    if session_id:
        # Get user info from session before deleting
        client_ip = get_client_ip(request)
        session_data = cookie_session_manager.validate_session(session_id, client_ip)
        if session_data:
            user_id = session_data.get("user_id")
            username = session_data.get("display_name") or session_data.get("username", "unknown")

        cookie_session_manager.delete_session(session_id)

    # Delete cookie (must match attributes from set_cookie for browser to recognize it)
    response.delete_cookie(
        key="session_id",
        path="/",
        secure=should_set_secure_cookie(request),
        samesite="lax",
        httponly=True,
    )

    # Check if OIDC user and build provider logout URL
    oidc_logout_url = None
    if user_id:
        with db.get_session() as session:
            try:
                log_logout(session, user_id, username, request)
                session.commit()
            except Exception as audit_err:
                logger.warning(f"Failed to log audit entry: {audit_err}")

            user = session.query(User).filter(User.id == user_id).first()
            if user and user.auth_provider == 'oidc':
                is_oidc_user = True
                config = session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()
                if config and config.enabled and config.provider_url:
                    try:
                        provider_url = config.provider_url.rstrip('/')
                        if provider_url.endswith('/.well-known/openid-configuration'):
                            provider_url = provider_url[:-len('/.well-known/openid-configuration')]
                        discovery_url = f"{provider_url}/.well-known/openid-configuration"
                        async with httpx.AsyncClient(timeout=5.0) as client:
                            resp = await client.get(discovery_url)
                            if resp.status_code == 200:
                                end_session = resp.json().get('end_session_endpoint')
                                if end_session and not end_session.startswith('https://'):
                                    logger.warning(f"Ignoring non-HTTPS end_session_endpoint: {end_session}")
                                    end_session = None
                                if end_session:
                                    scheme = get_request_scheme(request)
                                    if AppConfig.REVERSE_PROXY_MODE:
                                        host = request.headers.get('X-Forwarded-Host', request.headers.get('Host', request.url.netloc))
                                    else:
                                        host = request.headers.get('Host', request.url.netloc)
                                    base_path = get_base_path().rstrip('/')
                                    post_logout_uri = f"{scheme}://{host}{base_path}/login"
                                    oidc_logout_url = f"{end_session}?post_logout_redirect_uri={quote(post_logout_uri, safe='')}"
                    except Exception as e:
                        logger.warning(f"Failed to fetch OIDC end_session_endpoint: {e}")

    logger.info(f"User '{username}' logged out successfully (oidc={is_oidc_user})")

    return LogoutResponse(message="Logout successful", oidc_logout_url=oidc_logout_url)


# Dependency for protected routes (legacy - prefer get_current_user_or_api_key from api_key_auth)
async def get_current_user_dependency(
    request: Request,
    session_id: str = Cookie(None),
) -> dict:
    """
    Validate session and return user data.

    SECURITY CHECKS:
    1. Cookie exists
    2. Signature is valid (tamper-proof)
    3. Session exists server-side
    4. Session not expired
    5. IP matches (prevent hijacking)

    Raises:
        HTTPException: 401 if authentication fails

    Returns:
        Dict with user_id, username, auth_type
    """
    if not session_id:
        logger.warning("No session cookie provided")
        raise HTTPException(
            status_code=401,
            detail="Not authenticated - no session cookie"
        )

    client_ip = get_client_ip(request)
    session_data = cookie_session_manager.validate_session(session_id, client_ip)

    if not session_data:
        logger.warning(f"Session validation failed for IP: {client_ip}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session"
        )

    return {
        **session_data,
        "auth_type": "session",
    }


# Export dependency for use in other routes
get_current_user = get_current_user_dependency


@router.get("/me", response_model=CurrentUserSessionResponse | CurrentUserApiKeyResponse)
async def get_current_user_v2(
    current_user: dict = Depends(get_current_user_or_api_key)
) -> CurrentUserSessionResponse | CurrentUserApiKeyResponse:
    """
    Get current authenticated user or API key info.

    Supports both session cookie auth and API key auth.

    For session auth returns:
    {
        "auth_type": "session",
        "user": { id, username, display_name, groups: [...], ... },
        "capabilities": [...]
    }

    For API key auth returns:
    {
        "auth_type": "api_key",
        "api_key": { id, name, group_id, group_name, created_by_username },
        "capabilities": [...]
    }
    """
    if current_user.get("auth_type") == "api_key":
        # API key auth - return key info and its group's capabilities
        group_id = current_user["group_id"]
        capabilities = get_capabilities_for_group(group_id)

        return CurrentUserApiKeyResponse(
            auth_type="api_key",
            api_key=ApiKeyInfo(
                id=current_user["api_key_id"],
                name=current_user["api_key_name"],
                group_id=group_id,
                group_name=current_user["group_name"],
                created_by_username=current_user["created_by_username"],
            ),
            capabilities=capabilities,
        )

    else:
        # Session auth - return user info and union of all group capabilities
        user_id = current_user["user_id"]
        groups = get_user_groups(user_id)  # Returns [{id, name}, ...]
        capabilities = get_capabilities_for_user(user_id)  # Union of all groups

        # Get additional user info from database
        with db.get_session() as session:
            user = session.query(User).filter(User.id == user_id).first()

            return CurrentUserSessionResponse(
                auth_type="session",
                user=SessionUserInfo(
                    id=user_id,
                    username=current_user["username"],
                    display_name=user.display_name if user else None,
                    is_first_login=user.is_first_login if user else False,
                    must_change_password=user.must_change_password if user else False,
                    auth_provider=user.auth_provider if user else 'local',
                    groups=[UserGroupInfo(id=g["id"], name=g["name"]) for g in groups],
                ),
                capabilities=capabilities,
            )


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password_v2(
    password_data: ChangePasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_dependency),
    rate_limit_check: bool = rate_limit_auth,
) -> ChangePasswordResponse:
    """
    Change user password (v2 cookie-based auth).

    SECURITY:
    - Requires valid session cookie
    - Verifies current password before changing
    - Sets is_first_login=False after successful change
    - Input validation via Pydantic (prevents empty/missing fields)

    Request body:
        {
            "current_password": "old_password",
            "new_password": "new_password"
        }
    """
    # SECURITY FIX: Use validated Pydantic model fields instead of dict.get()
    current_password = password_data.current_password
    new_password = password_data.new_password

    user_id = current_user["user_id"]
    username = current_user["username"]

    # Reject same-password change (defeats must_change_password)
    if current_password == new_password:
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    # Single session: guard checks + verify + change (prevents TOCTOU race)
    with db.get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        if user.auth_provider == 'oidc':
            raise HTTPException(status_code=400, detail="Password change not available for this account")
        if user.locked_until and user.locked_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="Account is locked")

        password_valid, _ = verify_password(current_password, user.password_hash)
        if not password_valid:
            raise HTTPException(status_code=401, detail="Current password is incorrect")

        user.password_hash = ph.hash(new_password)
        user.is_first_login = False
        user.must_change_password = False
        user.updated_at = datetime.now(timezone.utc)
        session.commit()

    # Invalidate all OTHER sessions for this user (keep current session alive)
    current_session_id = current_user.get("session_id")
    cookie_session_manager.delete_sessions_for_user(user_id, exclude_session_id=current_session_id)

    logger.info(f"Password changed successfully for user: {username}")

    # Audit: Log password change
    with db.get_session() as session:
        try:
            log_audit(
                session, user_id, username,
                AuditAction.PASSWORD_CHANGE, AuditEntityType.USER,
                entity_id=str(user_id), entity_name=username,
                **get_client_info(request)
            )
            session.commit()
        except Exception as audit_err:
            logger.warning(f"Failed to log audit entry: {audit_err}")

    return ChangePasswordResponse(
        success=True,
        message="Password changed successfully"
    )


@router.post("/update-profile", response_model=UpdateProfileResponse)
async def update_profile_v2(
    profile_data: UpdateProfileRequest,
    request: Request,
    session_id: str = Cookie(None),
    current_user: dict = Depends(get_current_user_dependency)
) -> UpdateProfileResponse:
    """
    Update user profile (display name, username).

    SECURITY:
    - Requires valid session cookie (API key auth not supported)
    - Enforces must_change_password (user must change password first)
    - Username must be unique
    - Input validation via Pydantic
    - Atomic: all changes in single DB transaction
    """
    user_id = current_user["user_id"]

    # Enforce must_change_password — user must change password before other profile updates
    with db.get_session() as check_session:
        check_user = check_session.query(User).filter(User.id == user_id).first()
        if check_user and check_user.must_change_password:
            raise HTTPException(status_code=403, detail="Password change required")
    username = current_user["username"]
    new_display_name = profile_data.display_name
    new_username = profile_data.username

    changes = {}

    with db.get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Update display name if provided
        if new_display_name is not None:
            user.display_name = new_display_name
            changes['display_name'] = new_display_name

        # Update username if provided and different
        if new_username and new_username != username:
            conflict = session.query(User).filter(
                User.username == new_username,
                User.id != user_id,
            ).first()
            if conflict:
                raise HTTPException(status_code=400, detail="Username already taken")

            user.username = new_username
            changes['username'] = {'old': username, 'new': new_username}

        if changes:
            user.updated_at = datetime.now(timezone.utc)

            # Audit log (before commit for atomicity)
            log_audit(
                session, user_id, username,
                AuditAction.UPDATE, AuditEntityType.USER,
                entity_id=str(user_id), entity_name=username,
                details={'changes': changes},
                **get_client_info(request)
            )

            session.commit()

            # Update session username after commit
            if 'username' in changes and session_id:
                cookie_session_manager.update_session_username(session_id, new_username)

    logger.info(f"Profile updated for user: {username}")

    return UpdateProfileResponse(
        success=True,
        message="Profile updated successfully",
        changes=changes if changes else None
    )
