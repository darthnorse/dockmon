"""
Authentication Routes for DockMon
Handles login, logout, API key access, and session management endpoints
"""

import os
import secrets
import logging
from typing import Optional

from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse

from models.auth_models import LoginRequest, ChangePasswordRequest
from security.rate_limiting import rate_limit_auth
from security.audit import security_audit
from auth.session_manager import session_manager
from database import DatabaseManager


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/auth", tags=["authentication"])


def _is_localhost_or_internal(client_ip: str) -> bool:
    """Check if request is from localhost or internal network"""
    import ipaddress
    try:
        addr = ipaddress.ip_address(client_ip)

        # Allow localhost
        if addr.is_loopback:
            return True

        # Allow private networks (RFC 1918) - for Docker networks and internal deployments
        if addr.is_private:
            return True

        return False
    except ValueError:
        # Invalid IP format
        return False


from config.paths import DATABASE_PATH

# Initialize database for user management - use centralized path config
db = DatabaseManager(DATABASE_PATH)

# Ensure default user exists on startup
db.get_or_create_default_user()


def _get_session_from_cookie(request: Request) -> Optional[str]:
    """Extract session ID from cookie"""
    return request.cookies.get("dockmon_session")


async def verify_frontend_session(request: Request) -> bool:
    """Dependency to verify frontend session authentication"""
    session_id = _get_session_from_cookie(request)

    if not session_manager.validate_session(session_id, request):
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )

    return True


# Note: This endpoint will be implemented in main.py since it needs monitor instance
# @router.get("/key") - implemented directly in main.py


@router.post("/login")
async def login(login_data: LoginRequest, request: Request, response: Response, rate_limit_check: bool = rate_limit_auth):
    """Frontend login endpoint"""
    client_ip = request.client.host
    user_agent = request.headers.get("user-agent", "Unknown")

    # Verify credentials using database
    user_info = db.verify_user_credentials(login_data.username, login_data.password)
    if not user_info:
        security_audit.log_login_failure(client_ip, user_agent, "Invalid credentials")
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    # Create session with username
    session_id = session_manager.create_session(request, user_info["username"])

    # Set secure cookie
    # Detect if we're using HTTPS based on common headers
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"

    response.set_cookie(
        key="dockmon_session",
        value=session_id,
        httponly=True,  # Prevent XSS access to cookie
        secure=is_https,   # Use secure flag when on HTTPS
        samesite="lax", # CSRF protection
        max_age=24*60*60  # 24 hours
    )

    return {
        "success": True,
        "message": "Login successful",
        "username": user_info["username"],
        "must_change_password": user_info["must_change_password"],
        "is_first_login": user_info["is_first_login"]
    }


@router.post("/logout")
async def logout(request: Request, response: Response, authenticated: bool = Depends(verify_frontend_session)):
    """Frontend logout endpoint"""
    session_id = _get_session_from_cookie(request)

    if session_id:
        session_manager.delete_session(session_id)

    # Clear cookie
    response.delete_cookie("dockmon_session")

    return {"success": True, "message": "Logout successful"}


@router.get("/status")
async def auth_status(request: Request):
    """Check authentication status"""
    session_id = _get_session_from_cookie(request)
    authenticated = session_manager.validate_session(session_id, request) if session_id else False

    response = {
        "authenticated": authenticated,
        "session_valid": authenticated
    }

    # If authenticated, include username and password change requirement
    if authenticated:
        username = session_manager.get_session_username(session_id)
        if username:
            response["username"] = username
            # Check if user must change password
            with db.get_session() as session:
                from database import User
                user = session.query(User).filter(User.username == username).first()
                if user:
                    response["must_change_password"] = user.must_change_password
                    response["is_first_login"] = user.is_first_login

    return response


@router.post("/change-password")
async def change_password(password_data: ChangePasswordRequest, request: Request, authenticated: bool = Depends(verify_frontend_session)):
    """Change user password"""
    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    if not username:
        raise HTTPException(
            status_code=401,
            detail="Session invalid"
        )

    # Verify current password
    user_info = db.verify_user_credentials(username, password_data.current_password)
    if not user_info:
        raise HTTPException(
            status_code=401,
            detail="Current password is incorrect"
        )

    # Change password
    success = db.change_user_password(username, password_data.new_password)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to change password"
        )

    # Log security event
    client_ip = request.client.host
    user_agent = request.headers.get("user-agent", "Unknown")
    security_audit.log_password_change(client_ip, user_agent, username)

    return {
        "success": True,
        "message": "Password changed successfully"
    }


@router.post("/change-username")
async def change_username(username_data: dict, request: Request, authenticated: bool = Depends(verify_frontend_session)):
    """Change username"""
    session_id = _get_session_from_cookie(request)
    current_username = session_manager.get_session_username(session_id)

    if not current_username:
        raise HTTPException(
            status_code=401,
            detail="Session invalid"
        )

    # Verify current password
    current_password = username_data.get("current_password")
    new_username = username_data.get("new_username", "").strip()

    if not current_password or not new_username:
        raise HTTPException(
            status_code=400,
            detail="Current password and new username required"
        )

    # Verify current credentials
    user_info = db.verify_user_credentials(current_username, current_password)
    if not user_info:
        raise HTTPException(
            status_code=401,
            detail="Current password is incorrect"
        )

    # Validate new username
    if len(new_username) < 3 or len(new_username) > 50:
        raise HTTPException(
            status_code=400,
            detail="Username must be between 3 and 50 characters"
        )

    # Check if new username already exists
    if db.username_exists(new_username):
        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    # Change username
    if not db.change_username(current_username, new_username):
        raise HTTPException(
            status_code=500,
            detail="Failed to change username"
        )

    # Update session with new username
    session_manager.update_session_username(session_id, new_username)

    # Log security event
    client_ip = request.client.host
    user_agent = request.headers.get("user-agent", "Unknown")
    security_audit.log_username_change(client_ip, user_agent, current_username, new_username)

    return {
        "success": True,
        "message": "Username changed successfully"
    }