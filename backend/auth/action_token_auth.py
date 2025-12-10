"""
Action Token Authentication for DockMon

Provides one-time action tokens for notification links (e.g., Pushover, Telegram).
Enables users to trigger container updates directly from mobile notifications.

SECURITY FEATURES:
- SHA256 token hashing (never stores plaintext)
- Single-use enforcement (token invalidated after use)
- Time-limited (24-hour default expiration)
- Scoped to specific action and parameters
- Full audit logging

USAGE:
1. Generate token when sending update notification
2. Include token in notification URL
3. User clicks link -> validation endpoint
4. User confirms -> execute endpoint
5. Token automatically invalidated
"""

import hashlib
import json
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

from database import ActionToken, User, DatabaseManager
from security.audit import security_audit

logger = logging.getLogger(__name__)

# Token configuration
ACTION_TOKEN_PREFIX = "dockmon_action_"
ACTION_TOKEN_TTL_HOURS = 24
ACTION_TOKEN_MAX_PER_USER = 100  # Prevent token table bloat


def generate_action_token(
    db: DatabaseManager,
    user_id: int,
    action_type: str,
    action_params: Dict[str, Any],
    ttl_hours: int = ACTION_TOKEN_TTL_HOURS
) -> Tuple[str, int]:
    """
    Generate a one-time action token.

    Args:
        db: Database manager
        user_id: Owner of the token
        action_type: Type of action ('container_update', 'container_restart', etc.)
        action_params: Action-specific parameters (host_id, container_id, etc.)
        ttl_hours: Token validity period in hours

    Returns:
        Tuple of (plaintext_token, token_id)

    SECURITY:
    - 32 bytes (256 bits) of entropy
    - SHA256 hashing for storage
    - Prefix for log identification (first 12 chars of hash)
    """
    # Generate cryptographically secure random token
    random_bytes = secrets.token_urlsafe(32)
    plaintext_token = f"{ACTION_TOKEN_PREFIX}{random_bytes}"

    # Hash for storage (NEVER store plaintext!)
    token_hash = hashlib.sha256(plaintext_token.encode()).hexdigest()

    # Prefix for logging (first 12 chars)
    token_prefix = token_hash[:12]

    # Calculate expiration
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=ttl_hours)

    # Serialize action params
    action_params_json = json.dumps(action_params)

    with db.get_session() as session:
        # Check token limit per user (prevent bloat)
        active_count = session.query(ActionToken).filter(
            ActionToken.user_id == user_id,
            ActionToken.used_at.is_(None),
            ActionToken.revoked_at.is_(None),
            ActionToken.expires_at > now
        ).count()

        if active_count >= ACTION_TOKEN_MAX_PER_USER:
            # Clean up oldest tokens for this user
            oldest_tokens = session.query(ActionToken).filter(
                ActionToken.user_id == user_id,
                ActionToken.used_at.is_(None),
                ActionToken.revoked_at.is_(None)
            ).order_by(ActionToken.created_at.asc()).limit(10).all()

            for old_token in oldest_tokens:
                old_token.revoked_at = now
            session.flush()
            logger.info(f"Revoked {len(oldest_tokens)} old action tokens for user {user_id} (limit reached)")

        # Create token record
        token_record = ActionToken(
            token_hash=token_hash,
            token_prefix=token_prefix,
            user_id=user_id,
            action_type=action_type,
            action_params=action_params_json,
            created_at=now,
            expires_at=expires_at
        )
        session.add(token_record)
        session.commit()

        token_id = token_record.id

    logger.debug(f"Generated action token {token_prefix}... for user {user_id}, action={action_type}")

    return (plaintext_token, token_id)


def validate_action_token(
    db: DatabaseManager,
    token: str,
    client_ip: str,
    mark_used: bool = False
) -> Dict[str, Any]:
    """
    Validate an action token and return action details.

    Args:
        db: Database manager
        token: Plaintext token from URL
        client_ip: Client IP address
        mark_used: If True, mark token as used (for execute endpoint)

    Returns:
        Dict with validation result:
        - valid: bool
        - reason: str (if invalid)
        - action_type: str (if valid)
        - action_params: dict (if valid)
        - user_id: int (if valid)
        - token_id: int (if valid)
        - created_at: str (if valid)
        - expires_at: str (if valid)
    """
    # Basic format validation
    if not token or not token.startswith(ACTION_TOKEN_PREFIX):
        logger.warning(f"Invalid action token format from {client_ip}")
        security_audit.log_event(
            event_type="action_token_invalid_format",
            severity="warning",
            client_ip=client_ip,
            details={"reason": "Invalid token format or missing prefix"}
        )
        return {"valid": False, "reason": "invalid_format"}

    # Hash the provided token
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    with db.get_session() as session:
        # Look up token by hash
        token_record = session.query(ActionToken).filter(
            ActionToken.token_hash == token_hash
        ).first()

        if not token_record:
            logger.warning(f"Action token not found (hash: {token_hash[:12]}...) from {client_ip}")
            security_audit.log_event(
                event_type="action_token_not_found",
                severity="warning",
                client_ip=client_ip,
                details={"token_hash_prefix": token_hash[:12]}
            )
            return {"valid": False, "reason": "not_found"}

        # Check if revoked
        if token_record.revoked_at is not None:
            logger.warning(f"Revoked action token used from {client_ip}")
            security_audit.log_event(
                event_type="action_token_revoked_used",
                severity="warning",
                client_ip=client_ip,
                details={
                    "token_id": token_record.id,
                    "token_prefix": token_record.token_prefix,
                    "revoked_at": token_record.revoked_at.isoformat()
                }
            )
            return {"valid": False, "reason": "revoked"}

        # Check if already used
        if token_record.used_at is not None:
            logger.warning(f"Already-used action token attempted from {client_ip}")
            security_audit.log_event(
                event_type="action_token_replay_attempt",
                severity="warning",
                client_ip=client_ip,
                details={
                    "token_id": token_record.id,
                    "token_prefix": token_record.token_prefix,
                    "original_use_ip": token_record.used_from_ip,
                    "used_at": token_record.used_at.isoformat()
                }
            )
            return {"valid": False, "reason": "already_used"}

        # Check if expired
        now = datetime.now(timezone.utc)
        expires_at = token_record.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now > expires_at:
            logger.warning(f"Expired action token used from {client_ip}")
            security_audit.log_event(
                event_type="action_token_expired_used",
                severity="warning",
                client_ip=client_ip,
                details={
                    "token_id": token_record.id,
                    "token_prefix": token_record.token_prefix,
                    "expired_at": expires_at.isoformat()
                }
            )
            return {"valid": False, "reason": "expired"}

        # Verify user still exists
        user = session.query(User).filter(User.id == token_record.user_id).first()
        if not user:
            logger.warning(f"Action token for deleted user from {client_ip}")
            return {"valid": False, "reason": "user_deleted"}

        # Parse action params
        try:
            action_params = json.loads(token_record.action_params)
        except json.JSONDecodeError:
            logger.error(f"Invalid action_params JSON for token {token_record.id}")
            return {"valid": False, "reason": "invalid_params"}

        # Mark as used if requested (execute endpoint)
        if mark_used:
            token_record.used_at = now
            token_record.used_from_ip = client_ip
            session.commit()

            logger.info(f"Action token {token_record.token_prefix}... used from {client_ip}")
            security_audit.log_event(
                event_type="action_token_used",
                severity="info",
                user_id=token_record.user_id,
                client_ip=client_ip,
                details={
                    "token_id": token_record.id,
                    "token_prefix": token_record.token_prefix,
                    "action_type": token_record.action_type,
                    "action_params": action_params
                }
            )

        # Calculate time remaining
        time_remaining = expires_at - now
        hours_remaining = time_remaining.total_seconds() / 3600

        return {
            "valid": True,
            "token_id": token_record.id,
            "user_id": token_record.user_id,
            "username": user.username,
            "action_type": token_record.action_type,
            "action_params": action_params,
            "created_at": token_record.created_at.isoformat() + "Z",
            "expires_at": expires_at.isoformat() + "Z",
            "hours_remaining": round(hours_remaining, 1)
        }


def cleanup_expired_action_tokens(db: DatabaseManager) -> int:
    """
    Clean up expired and used action tokens.

    Called by periodic_jobs.py during daily maintenance.

    Cleanup policy:
    - Expired unused tokens: deleted immediately
    - Used tokens: kept 7 days for audit trail, then deleted
    - Revoked tokens: deleted immediately

    Returns:
        Number of tokens deleted
    """
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    with db.get_session() as session:
        # Count before deletion for logging
        expired_unused = session.query(ActionToken).filter(
            ActionToken.expires_at < now,
            ActionToken.used_at.is_(None)
        ).count()

        old_used = session.query(ActionToken).filter(
            ActionToken.used_at.isnot(None),
            ActionToken.used_at < seven_days_ago
        ).count()

        revoked = session.query(ActionToken).filter(
            ActionToken.revoked_at.isnot(None)
        ).count()

        # Delete expired unused tokens
        session.query(ActionToken).filter(
            ActionToken.expires_at < now,
            ActionToken.used_at.is_(None)
        ).delete(synchronize_session=False)

        # Delete old used tokens (past audit retention)
        session.query(ActionToken).filter(
            ActionToken.used_at.isnot(None),
            ActionToken.used_at < seven_days_ago
        ).delete(synchronize_session=False)

        # Delete revoked tokens
        session.query(ActionToken).filter(
            ActionToken.revoked_at.isnot(None)
        ).delete(synchronize_session=False)

        session.commit()

        total_deleted = expired_unused + old_used + revoked

        if total_deleted > 0:
            logger.info(
                f"Cleaned up {total_deleted} action tokens "
                f"(expired: {expired_unused}, old_used: {old_used}, revoked: {revoked})"
            )

        return total_deleted
