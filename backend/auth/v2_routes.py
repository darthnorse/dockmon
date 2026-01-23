"""
DockMon v2 Authentication Routes - Cookie-Based Sessions

SECURITY IMPROVEMENTS over v1:
1. HttpOnly cookies (XSS protection - JS can't access)
2. Secure flag (HTTPS only in production)
3. SameSite=strict (CSRF protection)
4. Argon2id password hashing (better than bcrypt)
5. IP validation (prevent session hijacking)
"""

import logging
from fastapi import APIRouter, HTTPException, Response, Cookie, Request, Depends
from pydantic import BaseModel
import argon2
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from typing import Callable

from auth.cookie_sessions import cookie_session_manager
from security.rate_limiting import rate_limit_auth
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
from database import User
from config.settings import AppConfig


def safe_audit_log(audit_func: Callable, *args, **kwargs) -> None:
    """
    Execute an audit logging function with error handling.

    Audit logging should never block the main operation. If logging fails,
    we log a warning but allow the operation to proceed.

    Args:
        audit_func: The audit logging function to call
        *args: Positional arguments for the audit function
        **kwargs: Keyword arguments for the audit function
    """
    try:
        audit_func(*args, **kwargs)
        # Get session from first arg (all audit functions take db session as first param)
        if args and hasattr(args[0], 'commit'):
            args[0].commit()
    except Exception as audit_err:
        logger.warning(f"Failed to log audit entry: {audit_err}")

# Argon2 password hasher (more secure than bcrypt)
# SECURITY: Argon2id is resistant to GPU attacks
ph = PasswordHasher(
    time_cost=2,        # Number of iterations
    memory_cost=65536,  # 64 MB memory
    parallelism=1,      # Number of threads
    hash_len=32,        # Hash length in bytes
    salt_len=16         # Salt length in bytes
)


class LoginRequest(BaseModel):
    """Login credentials"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response"""
    user: dict
    message: str


class ChangePasswordRequest(BaseModel):
    """Change password request with validation"""
    current_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    """Update profile request with validation"""
    display_name: str | None = None
    username: str | None = None


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
    - SameSite=strict (CSRF protection)
    - IP binding (session hijack prevention)

    Returns:
        User data and session cookie
    """
    # Get user from database
    with db.get_session() as session:
        user = session.query(User).filter(User.username == credentials.username).first()

        if not user:
            safe_username = _sanitize_for_log(credentials.username)
            logger.warning(f"Login failed: user '{safe_username}' not found")
            safe_audit_log(log_login_failure, session, credentials.username, request, "user_not_found")
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        # Verify password (with backward compatibility for bcrypt)
        password_valid = False
        needs_upgrade = False

        try:
            # Try Argon2id first (v2 default)
            ph.verify(user.password_hash, credentials.password)
            password_valid = True

            # Check if password needs rehashing (security upgrade)
            if ph.check_needs_rehash(user.password_hash):
                needs_upgrade = True

        except (VerifyMismatchError, InvalidHashError):
            # Fall back to bcrypt (v1 compatibility)
            try:
                import bcrypt
                if bcrypt.checkpw(
                    credentials.password.encode('utf-8'),
                    user.password_hash.encode('utf-8')
                ):
                    password_valid = True
                    needs_upgrade = True  # Upgrade bcrypt -> Argon2id
                    logger.info(f"User '{user.username}' authenticated with legacy bcrypt hash")
            except Exception as bcrypt_error:
                logger.debug(f"bcrypt verification failed: {bcrypt_error}")

        if not password_valid:
            safe_username = _sanitize_for_log(credentials.username)
            logger.warning(f"Login failed: invalid password for user '{safe_username}'")
            safe_audit_log(log_login_failure, session, credentials.username, request, "invalid_password")
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        # Check for soft-deleted user (v2.3.0+)
        if user.is_deleted:
            safe_username = _sanitize_for_log(credentials.username)
            logger.warning(f"Login failed: user '{safe_username}' is deactivated")
            safe_audit_log(log_login_failure, session, credentials.username, request, "user_deactivated")
            raise HTTPException(
                status_code=401,
                detail="Account is deactivated"
            )

        # Upgrade to Argon2id if needed (bcrypt -> Argon2id or old Argon2id params)
        if needs_upgrade:
            user.password_hash = ph.hash(credentials.password)
            session.commit()
            logger.info(f"Password hash upgraded to Argon2id for user '{user.username}'")

        # Create session
        client_ip = request.client.host if request.client else "unknown"
        signed_token = cookie_session_manager.create_session(
            user_id=user.id,
            username=user.username,
            client_ip=client_ip
        )

        # Set HttpOnly cookie (XSS protection)
        # SECURITY: JavaScript cannot access this cookie
        # NOTE: Domain is not set, letting browser use the request host
        response.set_cookie(
            key="session_id",
            value=signed_token,
            httponly=True,          # Prevents XSS
            secure=not AppConfig.REVERSE_PROXY_MODE,  # HTTPS mode unless reverse proxy
            samesite="lax",         # CSRF protection (allows same-origin GET requests)
            max_age=86400 * 7,      # 7 days
            path="/",               # Available to all routes
            domain=None             # Let browser use request host (handles ports correctly)
        )

        logger.info(f"User '{user.username}' logged in successfully from {client_ip}")

        # Audit: Log successful login
        safe_audit_log(log_login, session, user.id, user.username, request, auth_method='local')

        return LoginResponse(
            user={
                "id": user.id,
                "username": user.username,
                "is_first_login": user.is_first_login
            },
            message="Login successful"
        )


@router.post("/logout")
async def logout_v2(
    response: Response,
    request: Request,
    session_id: str = Cookie(None)
) -> dict:
    """
    Logout user and delete session.

    SECURITY: Session is deleted server-side
    """
    user_id = None
    username = "unknown"

    if session_id:
        # Get user info from session before deleting
        client_ip = request.client.host if request.client else "unknown"
        session_data = cookie_session_manager.validate_session(session_id, client_ip)
        if session_data:
            user_id = session_data.get("user_id")
            username = session_data.get("username", "unknown")

        cookie_session_manager.delete_session(session_id)

    # Delete cookie
    response.delete_cookie(
        key="session_id",
        path="/"
    )

    # Audit: Log logout
    if user_id:
        with db.get_session() as session:
            safe_audit_log(log_logout, session, user_id, username, request)

    logger.info(f"User '{username}' logged out successfully")

    return {"message": "Logout successful"}


# Helper function to map user role to scopes
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


# Dependency for protected routes
async def get_current_user_dependency(
    request: Request,
    session_id: str = Cookie(None),
) -> dict:
    """
    Validate session and return user data with scopes.

    SECURITY CHECKS:
    1. Cookie exists
    2. Signature is valid (tamper-proof)
    3. Session exists server-side
    4. Session not expired
    5. IP matches (prevent hijacking)

    Raises:
        HTTPException: 401 if authentication fails

    Returns:
        Dict with user_id, username, session_id, scopes (derived from role)
    """
    if not session_id:
        logger.warning("No session cookie provided")
        raise HTTPException(
            status_code=401,
            detail="Not authenticated - no session cookie"
        )

    client_ip = request.client.host if request.client else "unknown"
    session_data = cookie_session_manager.validate_session(session_id, client_ip)

    if not session_data:
        logger.warning(f"Session validation failed for IP: {client_ip}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session"
        )

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

    # Fallback if user not found (shouldn't happen)
    logger.warning(f"User {session_data['user_id']} not found in database")
    return {
        **session_data,
        "auth_type": "session",
        "scopes": ["read"]  # Safe default
    }


# Export dependency for use in other routes
get_current_user = get_current_user_dependency


@router.get("/me")
async def get_current_user_v2(
    current_user: dict = Depends(get_current_user_dependency)
) -> dict:
    """
    Get current authenticated user.

    Requires valid session cookie.
    """
    # Get user from database to include is_first_login status
    with db.get_session() as session:
        user = session.query(User).filter(User.id == current_user["user_id"]).first()

        return {
            "user": {
                "id": current_user["user_id"],
                "username": current_user["username"],
                "display_name": user.display_name if user else None,
                "is_first_login": user.is_first_login if user else False,
                "must_change_password": user.must_change_password if user else False,
                "role": user.role if user else "user"
            }
        }


@router.post("/change-password")
async def change_password_v2(
    password_data: ChangePasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_dependency)
) -> dict:
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

    # Verify current password
    user_info = db.verify_user_credentials(username, current_password)
    if not user_info:
        raise HTTPException(
            status_code=401,
            detail="Current password is incorrect"
        )

    # Change password (also sets is_first_login=False)
    success = db.change_user_password(username, new_password)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to change password"
        )

    logger.info(f"Password changed successfully for user: {username}")

    # Audit: Log password change
    with db.get_session() as session:
        safe_audit_log(
            log_audit, session, user_id, username,
            AuditAction.PASSWORD_CHANGE, AuditEntityType.USER,
            entity_id=str(user_id), entity_name=username,
            **get_client_info(request)
        )

    return {
        "success": True,
        "message": "Password changed successfully"
    }


@router.post("/update-profile")
async def update_profile_v2(
    profile_data: UpdateProfileRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_dependency)
) -> dict:
    """
    Update user profile (display name, username).

    SECURITY:
    - Requires valid session cookie
    - Username must be unique
    - Input validation via Pydantic
    """
    user_id = current_user["user_id"]
    username = current_user["username"]
    # SECURITY FIX: Use validated Pydantic model fields instead of dict.get()
    new_display_name = profile_data.display_name
    new_username = profile_data.username

    try:
        changes = {}

        # Update display name if provided
        if new_display_name is not None:
            db.update_display_name(username, new_display_name)
            changes['display_name'] = new_display_name

        # Update username if provided and different
        if new_username and new_username != username:
            # Check if new username already exists
            if db.username_exists(new_username):
                raise HTTPException(
                    status_code=400,
                    detail="Username already taken"
                )

            if not db.change_username(username, new_username):
                raise HTTPException(
                    status_code=500,
                    detail="Failed to update username"
                )
            changes['username'] = {'old': username, 'new': new_username}

        logger.info(f"Profile updated for user: {username}")

        # Audit: Log profile update
        if changes:
            with db.get_session() as session:
                safe_audit_log(
                    log_audit, session, user_id, username,
                    AuditAction.UPDATE, AuditEntityType.USER,
                    entity_id=str(user_id), entity_name=username,
                    details={'changes': changes},
                    **get_client_info(request)
                )

        return {
            "success": True,
            "message": "Profile updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update profile: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to update profile"
        )
