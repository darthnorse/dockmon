"""
Shared authentication utilities and database instance
Used across both V1 legacy endpoints and V2 cookie-based auth
"""

import logging
from typing import Optional
from fastapi import Request, HTTPException

from config.paths import DATABASE_PATH
from database import DatabaseManager
from audit.audit_logger import log_audit

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


def safe_audit_log(session, *args, **kwargs) -> None:
    """
    Execute audit logging with error handling.

    IMPORTANT: This function does NOT commit the session. The caller is
    responsible for committing both the main operation and the audit log
    together in a single transaction. This ensures atomicity - if the main
    operation fails, the audit log is also rolled back.

    Args:
        session: Database session (already in a transaction)
        *args, **kwargs: Arguments passed to log_audit()

    Usage:
        # Good - audit log committed with main operation
        session.add(some_record)
        safe_audit_log(session, user_id, username, action, ...)
        session.commit()  # Commits both record and audit log

        # Bad - don't call this after commit
        session.commit()
        safe_audit_log(session, ...)  # Audit log in separate transaction
    """
    try:
        log_audit(session, *args, **kwargs)
    except Exception as e:
        # Log at ERROR level - audit failures are significant
        logger.error(f"Failed to create audit entry: {e}")
