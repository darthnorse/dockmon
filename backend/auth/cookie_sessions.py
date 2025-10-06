"""
Secure Cookie-Based Session Management for DockMon v2.0

SECURITY FEATURES:
- HttpOnly cookies (XSS protection)
- Secure flag (HTTPS only in production)
- SameSite=strict (CSRF protection)
- Signed cookies with itsdangerous (tamper-proof)
- Session expiry with automatic cleanup
- IP validation to prevent session hijacking

MEMORY SAFETY:
- Thread-safe session storage with locks
- Automatic cleanup of expired sessions
- Graceful shutdown with cleanup thread termination
"""

import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

logger = logging.getLogger(__name__)

# Secret key for signing cookies (should be from environment in production)
# SECURITY: This should be loaded from env var in production
SECRET_KEY = secrets.token_urlsafe(32)
COOKIE_SIGNER = URLSafeTimedSerializer(SECRET_KEY, salt="dockmon-session")


class CookieSessionManager:
    """
    Manages cookie-based sessions with security hardening.

    Unlike v1's in-memory sessions, this uses signed cookies for the session ID
    and validates them server-side.
    """

    def __init__(self, session_timeout_hours: int = 24):
        """
        Initialize session manager.

        Args:
            session_timeout_hours: Session expiry time (default 24 hours)
        """
        self.sessions: Dict[str, dict] = {}
        self.session_timeout = timedelta(hours=session_timeout_hours)
        self._sessions_lock = threading.Lock()
        self._shutdown_event = threading.Event()

        # Start cleanup thread (runs every hour)
        self._cleanup_thread = threading.Thread(
            target=self._periodic_cleanup,
            daemon=True,
            name="SessionCleanup"
        )
        self._cleanup_thread.start()
        logger.info(f"Cookie session manager initialized (timeout: {session_timeout_hours}h)")

    def _periodic_cleanup(self):
        """
        Periodic cleanup of expired sessions.

        MEMORY SAFETY: Prevents unbounded memory growth from abandoned sessions.
        """
        while not self._shutdown_event.wait(timeout=3600):  # Run every hour
            try:
                deleted = self.cleanup_expired_sessions()
                if deleted > 0:
                    logger.info(f"Session cleanup: removed {deleted} expired sessions")
            except Exception as e:
                logger.error(f"Session cleanup failed: {e}", exc_info=True)

    def create_session(self, user_id: int, username: str, client_ip: str) -> str:
        """
        Create a new session and return signed cookie value.

        Args:
            user_id: Database user ID
            username: Username
            client_ip: Client IP address for validation

        Returns:
            Signed session token for cookie

        SECURITY: Session ID is cryptographically random (32 bytes)
        """
        session_id = secrets.token_urlsafe(32)
        now = datetime.utcnow()

        with self._sessions_lock:
            self.sessions[session_id] = {
                "user_id": user_id,
                "username": username,
                "client_ip": client_ip,
                "created_at": now,
                "last_accessed": now,
            }

        # Sign the session ID for tamper-proof cookie
        signed_token = COOKIE_SIGNER.dumps(session_id)

        logger.info(f"Session created for user '{username}' (ID: {user_id}) from {client_ip}")
        return signed_token

    def validate_session(
        self,
        signed_token: str,
        client_ip: str,
        max_age_seconds: Optional[int] = None
    ) -> Optional[Dict]:
        """
        Validate session token and return session data.

        Args:
            signed_token: Signed cookie value
            client_ip: Current client IP
            max_age_seconds: Optional max age override

        Returns:
            Session data dict or None if invalid

        SECURITY CHECKS:
        1. Signature validation (prevents tampering)
        2. Session existence check
        3. Expiry check
        4. IP validation (prevents hijacking)
        """
        if not signed_token:
            return None

        # 1. Verify signature and extract session ID
        try:
            max_age = max_age_seconds or int(self.session_timeout.total_seconds())
            session_id = COOKIE_SIGNER.loads(
                signed_token,
                max_age=max_age
            )
        except SignatureExpired:
            logger.warning(f"Session token expired for IP {client_ip}")
            return None
        except BadSignature:
            logger.warning(f"Invalid session signature from IP {client_ip} (possible tampering)")
            return None

        # 2. Check session exists
        with self._sessions_lock:
            if session_id not in self.sessions:
                logger.warning(f"Session {session_id[:8]}... not found for IP {client_ip}")
                return None

            session = self.sessions[session_id]
            now = datetime.utcnow()

            # 3. Check expiry (belt and suspenders with cookie max_age)
            if now - session["created_at"] > self.session_timeout:
                del self.sessions[session_id]
                logger.info(f"Session {session_id[:8]}... expired for user '{session['username']}'")
                return None

            # 4. Validate IP consistency (prevent session hijacking)
            if session["client_ip"] != client_ip:
                logger.error(
                    f"Session hijack attempt detected! Session from {session['client_ip']} "
                    f"accessed from {client_ip}. User: {session['username']}"
                )
                del self.sessions[session_id]
                return None

            # Update last accessed time
            session["last_accessed"] = now

            return {
                "user_id": session["user_id"],
                "username": session["username"],
                "session_id": session_id,
            }

    def delete_session(self, signed_token: str) -> bool:
        """
        Delete a session (logout).

        Args:
            signed_token: Signed cookie value

        Returns:
            True if session was deleted, False if not found
        """
        try:
            session_id = COOKIE_SIGNER.loads(signed_token)
        except (SignatureExpired, BadSignature):
            return False

        with self._sessions_lock:
            if session_id in self.sessions:
                username = self.sessions[session_id].get("username", "unknown")
                del self.sessions[session_id]
                logger.info(f"Session deleted for user '{username}'")
                return True

        return False

    def cleanup_expired_sessions(self) -> int:
        """
        Remove all expired sessions.

        Returns:
            Number of sessions deleted

        MEMORY SAFETY: Prevents memory leak from abandoned sessions
        """
        now = datetime.utcnow()
        expired = []

        with self._sessions_lock:
            for session_id, data in self.sessions.items():
                if now - data["created_at"] > self.session_timeout:
                    expired.append(session_id)

            for session_id in expired:
                del self.sessions[session_id]

        return len(expired)

    def get_active_session_count(self) -> int:
        """Get number of active sessions."""
        with self._sessions_lock:
            return len(self.sessions)

    def shutdown(self):
        """
        Gracefully shutdown session manager.

        MEMORY SAFETY: Ensures cleanup thread terminates properly
        """
        logger.info("Shutting down cookie session manager...")
        self._shutdown_event.set()
        self._cleanup_thread.join(timeout=5)
        logger.info(f"Session manager shutdown complete ({self.get_active_session_count()} active sessions)")


# Global instance
cookie_session_manager = CookieSessionManager(session_timeout_hours=24)
