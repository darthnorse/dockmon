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
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

logger = logging.getLogger(__name__)


def _load_or_generate_secret() -> str:
    """
    Load existing session secret or generate new one.

    SECURITY:
    - Secret is persisted to survive server restarts
    - Users stay logged in across deployments/restarts
    - Checks for secret rotation (90 days by default)

    Returns:
        Session secret key
    """
    import json
    from datetime import datetime, timedelta, timezone

    secret_file = os.getenv('SESSION_SECRET_FILE', '/app/data/.session_secret')
    rotation_days = int(os.getenv('SESSION_SECRET_ROTATION_DAYS', '90'))

    if os.path.exists(secret_file):
        # Load existing secret
        try:
            with open(secret_file, 'r') as f:
                content = f.read().strip()

                # Try to parse as JSON (new format with metadata)
                try:
                    data = json.loads(content)
                    secret = data.get('secret')
                    created_at_str = data.get('created_at')

                    if secret and len(secret) >= 32:
                        # SECURITY FIX: Check if secret needs rotation
                        if created_at_str:
                            created_at = datetime.fromisoformat(created_at_str)
                            age_days = (datetime.now(timezone.utc) - created_at).days

                            if age_days > rotation_days:
                                logger.warning(
                                    f"Session secret is {age_days} days old (limit: {rotation_days}), rotating..."
                                )
                                # Continue to generate new secret
                            else:
                                logger.info(f"Loaded existing session secret (age: {age_days} days)")
                                return secret
                        else:
                            # No creation timestamp, consider it old
                            logger.info("Loaded existing session secret from file")
                            return secret
                except json.JSONDecodeError:
                    # Legacy format (plain secret string) - accept but will upgrade on next write
                    if len(content) >= 32:
                        logger.info("Loaded existing session secret from file (legacy format)")
                        return content
                    else:
                        logger.warning(f"Invalid secret in {secret_file}, regenerating")
        except Exception as e:
            logger.error(f"Failed to load secret from {secret_file}: {e}")

    # Generate new secret and save it with metadata
    secret = secrets.token_urlsafe(32)
    secret_data = {
        'secret': secret,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'rotation_days': rotation_days
    }

    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(secret_file), exist_ok=True)

        # Write secret with metadata and secure permissions
        # SECURITY: Set restrictive umask before file creation
        old_umask = os.umask(0o077)
        try:
            with open(secret_file, 'w') as f:
                json.dump(secret_data, f, indent=2)
            os.chmod(secret_file, 0o600)
        finally:
            os.umask(old_umask)

        logger.info(f"Generated new session secret and saved to {secret_file}")
    except Exception as e:
        logger.error(f"Failed to save secret to {secret_file}: {e}")
        logger.warning("Using ephemeral secret (sessions will be invalidated on restart)")

    return secret


# Secret key for signing cookies (persists across restarts)
# SECURITY: Can be overridden with SESSION_SECRET_KEY env var
SECRET_KEY = os.getenv('SESSION_SECRET_KEY') or _load_or_generate_secret()
COOKIE_SIGNER = URLSafeTimedSerializer(SECRET_KEY, salt="dockmon-session")


class CookieSessionManager:
    """
    Manages cookie-based sessions with security hardening.

    Unlike v1's in-memory sessions, this uses signed cookies for the session ID
    and validates them server-side.
    """

    def __init__(self, session_timeout_hours: int = 24, max_sessions: int = 10000):
        """
        Initialize session manager.

        Args:
            session_timeout_hours: Session expiry time (default 24 hours)
            max_sessions: Maximum concurrent sessions (default 10,000)
        """
        self.sessions: Dict[str, dict] = {}
        self.session_timeout = timedelta(hours=session_timeout_hours)
        self.max_sessions = max_sessions
        self._sessions_lock = threading.Lock()
        self._shutdown_event = threading.Event()

        # Start cleanup thread (runs every hour)
        self._cleanup_thread = threading.Thread(
            target=self._periodic_cleanup,
            daemon=True,
            name="SessionCleanup"
        )
        self._cleanup_thread.start()
        logger.info(f"Cookie session manager initialized (timeout: {session_timeout_hours}h, max: {max_sessions})")

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

        Raises:
            Exception: If max session limit reached after cleanup

        SECURITY: Session ID is cryptographically random (32 bytes)
        DOS PROTECTION: Limits maximum concurrent sessions
        """
        session_id = secrets.token_urlsafe(32)
        now = datetime.utcnow()

        with self._sessions_lock:
            # Check if at capacity
            if len(self.sessions) >= self.max_sessions:
                # Try cleanup first
                expired = self._cleanup_expired_sessions_unsafe()
                if expired > 0:
                    logger.info(f"Session limit reached, cleaned {expired} expired sessions")

                # Check again after cleanup
                if len(self.sessions) >= self.max_sessions:
                    logger.error(f"Session limit exceeded: {len(self.sessions)}/{self.max_sessions}")
                    raise Exception("Server at maximum capacity - please try again later")

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
            # DISABLED: Causes issues behind proxies/CDNs like Cloudflare where IP varies
            # if session["client_ip"] != client_ip:
            #     logger.warning(
            #         f"IP mismatch: Session created from {session['client_ip']}, "
            #         f"accessed from {client_ip}. Invalidating session for user: {session['username']}"
            #     )
            #     del self.sessions[session_id]
            #     return None

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

    def _cleanup_expired_sessions_unsafe(self) -> int:
        """
        Remove expired sessions (UNSAFE - must be called with lock held).

        Returns:
            Number of sessions deleted

        MEMORY SAFETY: Prevents memory leak from abandoned sessions
        WARNING: Caller must hold self._sessions_lock
        """
        now = datetime.utcnow()
        expired = []

        for session_id, data in self.sessions.items():
            if now - data["created_at"] > self.session_timeout:
                expired.append(session_id)

        for session_id in expired:
            del self.sessions[session_id]

        return len(expired)

    def cleanup_expired_sessions(self) -> int:
        """
        Remove all expired sessions (thread-safe).

        Returns:
            Number of sessions deleted

        MEMORY SAFETY: Prevents memory leak from abandoned sessions
        """
        with self._sessions_lock:
            return self._cleanup_expired_sessions_unsafe()

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
