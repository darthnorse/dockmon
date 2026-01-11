"""
Secure Cookie-Based Session Management for DockMon v2.0

STATELESS JWT-STYLE TOKENS:
- User data embedded directly in signed token (no server-side state)
- Tokens survive container restarts (secret key persisted to disk)
- HttpOnly cookies (XSS protection)
- Secure flag (HTTPS only in production)
- SameSite=lax (CSRF protection)
- Signed with itsdangerous (tamper-proof)
- Time-based expiry built into signature
"""

import logging
import os
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

logger = logging.getLogger(__name__)


def _load_or_generate_secret() -> str:
    """
    Load existing session secret or generate new one.
    Secret is persisted to /app/data/.session_secret to survive restarts.
    """
    secret_file = os.getenv('SESSION_SECRET_FILE', '/app/data/.session_secret')
    rotation_days = int(os.getenv('SESSION_SECRET_ROTATION_DAYS', '90'))

    if os.path.exists(secret_file):
        try:
            with open(secret_file, 'r') as f:
                content = f.read().strip()

                try:
                    data = json.loads(content)
                    secret = data.get('secret')
                    created_at_str = data.get('created_at')

                    if secret and len(secret) >= 32 and created_at_str:
                        created_at = datetime.fromisoformat(created_at_str)
                        age_days = (datetime.now(timezone.utc) - created_at).days

                        if age_days <= rotation_days:
                            logger.info(f"Loaded session secret (age: {age_days} days)")
                            return secret
                        else:
                            logger.warning(f"Session secret is {age_days} days old, rotating...")
                except json.JSONDecodeError:
                    pass  # Legacy or invalid format, regenerate

                logger.warning(f"Regenerating session secret (invalid or expired)")
        except Exception as e:
            logger.error(f"Failed to load secret from {secret_file}: {e}")

    # Generate new secret
    secret = secrets.token_urlsafe(32)
    secret_data = {
        'secret': secret,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'rotation_days': rotation_days
    }

    try:
        os.makedirs(os.path.dirname(secret_file), exist_ok=True)
        old_umask = os.umask(0o077)
        try:
            with open(secret_file, 'w') as f:
                json.dump(secret_data, f, indent=2)
            os.chmod(secret_file, 0o600)
        finally:
            os.umask(old_umask)
        logger.info(f"Generated new session secret")
    except Exception as e:
        logger.error(f"Failed to save secret: {e}")
        logger.warning("Using ephemeral secret (sessions won't survive restart)")

    return secret


SECRET_KEY = os.getenv('SESSION_SECRET_KEY') or _load_or_generate_secret()
COOKIE_SIGNER = URLSafeTimedSerializer(SECRET_KEY, salt="dockmon-session")


class CookieSessionManager:
    """
    Stateless cookie-based session manager.
    User data is embedded directly in the signed token - no server-side storage needed.
    """

    def __init__(self, session_timeout_hours: int = 24 * 30, **kwargs):
        self.session_timeout = timedelta(hours=session_timeout_hours)
        logger.info(f"Stateless session manager initialized (timeout: {session_timeout_hours}h)")

    def create_session(self, user_id: int, username: str, client_ip: str) -> str:
        """Create a signed token with embedded user data."""
        token_data = {"uid": user_id, "usr": username}
        signed_token = COOKIE_SIGNER.dumps(token_data)
        logger.info(f"Session created for user '{username}' (ID: {user_id}) from {client_ip}")
        return signed_token

    def validate_session(
        self,
        signed_token: str,
        client_ip: str,
        max_age_seconds: Optional[int] = None
    ) -> Optional[Dict]:
        """Validate token signature/expiry and extract user data."""
        if not signed_token:
            return None

        try:
            max_age = max_age_seconds or int(self.session_timeout.total_seconds())
            token_data = COOKIE_SIGNER.loads(signed_token, max_age=max_age)
        except SignatureExpired:
            logger.warning(f"Session token expired for IP {client_ip}")
            return None
        except BadSignature:
            logger.warning(f"Invalid session signature from IP {client_ip}")
            return None

        # Validate token structure and types
        user_id = token_data.get("uid")
        username = token_data.get("usr")

        if not isinstance(user_id, int) or not isinstance(username, str) or not username:
            logger.warning(f"Malformed session token from IP {client_ip}")
            return None

        return {
            "user_id": user_id,
            "username": username,
            "session_id": signed_token[:16],
        }

    def delete_session(self, signed_token: str) -> bool:
        """Log the logout (cookie cleared client-side)."""
        try:
            max_age = int(self.session_timeout.total_seconds())
            token_data = COOKIE_SIGNER.loads(signed_token, max_age=max_age)
            logger.info(f"Session deleted for user '{token_data.get('usr', 'unknown')}'")
            return True
        except (SignatureExpired, BadSignature):
            return False


from config.settings import AppConfig
cookie_session_manager = CookieSessionManager(session_timeout_hours=AppConfig.SESSION_TIMEOUT_HOURS)
