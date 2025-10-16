"""
Shared authentication utilities and database instance
Used across both V1 legacy endpoints and V2 cookie-based auth
"""

import logging
from typing import Optional
from fastapi import Request, HTTPException

from config.paths import DATABASE_PATH
from database import DatabaseManager

logger = logging.getLogger(__name__)

# Initialize shared database instance for user management
# IMPORTANT: Single connection pool shared across all auth routes
db = DatabaseManager(DATABASE_PATH)

# Ensure default user exists on startup
db.get_or_create_default_user()


def get_session_from_cookie(request: Request) -> Optional[str]:
    """
    Extract session ID from cookie.

    Used by legacy V1 endpoints that haven't been migrated to V2 auth.
    New code should use V2 cookie auth directly.
    """
    return request.cookies.get("dockmon_session")
