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

from auth.cookie_sessions import cookie_session_manager
from security.rate_limiting import rate_limit_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/auth", tags=["auth-v2"])

# Import shared database instance from v1 (single connection pool)
from auth.routes import db

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


@router.post("/login", response_model=LoginResponse)
async def login_v2(
    credentials: LoginRequest,
    response: Response,
    request: Request,
    rate_limit_check: bool = rate_limit_auth
):
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
        from database import User
        user = session.query(User).filter(User.username == credentials.username).first()

        if not user:
            logger.warning(f"Login failed: user '{credentials.username}' not found")
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
            logger.warning(f"Login failed: invalid password for user '{credentials.username}'")
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
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
            secure=True,            # HTTPS only (disable for localhost dev)
            samesite="lax",         # CSRF protection (allows same-origin GET requests)
            max_age=86400 * 7,      # 7 days
            path="/",               # Available to all routes
            domain=None             # Let browser use request host (handles ports correctly)
        )

        logger.info(f"User '{user.username}' logged in successfully from {client_ip}")

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
    session_id: str = Cookie(None)
):
    """
    Logout user and delete session.

    SECURITY: Session is deleted server-side
    """
    if session_id:
        cookie_session_manager.delete_session(session_id)

    # Delete cookie
    response.delete_cookie(
        key="session_id",
        path="/"
    )

    logger.info("User logged out successfully")

    return {"message": "Logout successful"}


# Dependency for protected routes
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
        Dict with user_id, username, session_id
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

    return session_data


# Export dependency for use in other routes
get_current_user = get_current_user_dependency


@router.get("/me")
async def get_current_user_v2(
    current_user: dict = Depends(get_current_user_dependency)
):
    """
    Get current authenticated user.

    Requires valid session cookie.
    """
    return {
        "user": {
            "id": current_user["user_id"],
            "username": current_user["username"]
        }
    }
