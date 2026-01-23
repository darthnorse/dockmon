"""
Audit logging helper functions for DockMon v2.3.0.

Records user actions to the audit_log table for security and compliance.
"""

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, Union

from fastapi import Request
from sqlalchemy.orm import Session

from database import AuditLog

logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Audit action types"""
    # Authentication
    LOGIN = 'login'
    LOGOUT = 'logout'
    LOGIN_FAILED = 'login_failed'
    PASSWORD_CHANGE = 'password_change'
    PASSWORD_RESET_REQUEST = 'password_reset_request'
    PASSWORD_RESET = 'password_reset'

    # CRUD operations
    CREATE = 'create'
    UPDATE = 'update'
    DELETE = 'delete'

    # Container operations
    START = 'start'
    STOP = 'stop'
    RESTART = 'restart'
    SHELL = 'shell'
    SHELL_END = 'shell_end'
    CONTAINER_UPDATE = 'container_update'

    # Stack operations
    DEPLOY = 'deploy'

    # Settings
    SETTINGS_CHANGE = 'settings_change'
    ROLE_CHANGE = 'role_change'


class AuditEntityType(str, Enum):
    """Audit entity types"""
    SESSION = 'session'
    USER = 'user'
    HOST = 'host'
    CONTAINER = 'container'
    STACK = 'stack'
    DEPLOYMENT = 'deployment'
    ALERT_RULE = 'alert_rule'
    NOTIFICATION_CHANNEL = 'notification_channel'
    TAG = 'tag'
    REGISTRY_CREDENTIAL = 'registry_credential'
    HEALTH_CHECK = 'health_check'
    UPDATE_POLICY = 'update_policy'
    API_KEY = 'api_key'
    SETTINGS = 'settings'
    ROLE_PERMISSION = 'role_permission'
    OIDC_CONFIG = 'oidc_config'


def get_client_info(request: Request) -> Dict[str, Optional[str]]:
    """
    Extract client information from request.

    Args:
        request: FastAPI request object

    Returns:
        Dict with ip_address and user_agent
    """
    # Get IP address - check X-Forwarded-For for reverse proxy setups
    ip_address = request.headers.get('X-Forwarded-For')
    if ip_address:
        # Take first IP if multiple (client -> proxies)
        ip_address = ip_address.split(',')[0].strip()
    else:
        ip_address = request.client.host if request.client else None

    user_agent = request.headers.get('User-Agent')

    return {
        'ip_address': ip_address,
        'user_agent': user_agent,
    }


def log_audit(
    db: Session,
    user_id: Optional[int],
    username: str,
    action: Union[AuditAction, str],
    entity_type: Union[AuditEntityType, str],
    entity_id: Optional[str] = None,
    entity_name: Optional[str] = None,
    host_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    auto_commit: bool = False,
) -> AuditLog:
    """
    Log an action to the audit log.

    IMPORTANT: This function does NOT commit by default. The caller is responsible
    for managing the transaction and calling commit() when appropriate. This allows
    audit logging to be part of larger transactions without causing unexpected commits.

    Args:
        db: Database session
        user_id: ID of user performing action (None for failed logins)
        username: Username (stored separately for audit trail preservation)
        action: Type of action being performed
        entity_type: Type of entity being acted upon
        entity_id: ID of the entity (optional)
        entity_name: Human-readable name of entity (optional)
        host_id: Host ID for container operations (optional)
        details: Additional context as JSON (optional)
        ip_address: Client IP address (optional)
        user_agent: Client user agent (optional)
        auto_commit: If True, commit after adding the audit entry (default: False)

    Returns:
        Created AuditLog entry
    """
    audit_entry = AuditLog(
        user_id=user_id,
        username=username,
        action=action.value if isinstance(action, AuditAction) else action,
        entity_type=entity_type.value if isinstance(entity_type, AuditEntityType) else entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        host_id=host_id,
        details=json.dumps(details) if details else None,
        ip_address=ip_address,
        user_agent=user_agent,
        created_at=datetime.now(timezone.utc),
    )

    db.add(audit_entry)

    if auto_commit:
        db.commit()

    logger.debug(
        f"Audit: {username} performed {action} on {entity_type}"
        f"{f':{entity_id}' if entity_id else ''}"
        f"{f' ({entity_name})' if entity_name else ''}"
    )

    return audit_entry


def log_login(
    db: Session,
    user_id: int,
    username: str,
    request: Request,
    auth_method: str = 'local',
) -> AuditLog:
    """
    Log a successful login.

    Args:
        db: Database session
        user_id: User ID
        username: Username
        request: FastAPI request
        auth_method: Authentication method ('local' or 'oidc')
    """
    client_info = get_client_info(request)
    return log_audit(
        db=db,
        user_id=user_id,
        username=username,
        action=AuditAction.LOGIN,
        entity_type=AuditEntityType.SESSION,
        details={'auth_method': auth_method},
        **client_info,
    )


def log_logout(
    db: Session,
    user_id: int,
    username: str,
    request: Request,
) -> AuditLog:
    """Log a logout."""
    client_info = get_client_info(request)
    return log_audit(
        db=db,
        user_id=user_id,
        username=username,
        action=AuditAction.LOGOUT,
        entity_type=AuditEntityType.SESSION,
        **client_info,
    )


def log_login_failure(
    db: Session,
    username: str,
    request: Request,
    reason: str,
) -> AuditLog:
    """
    Log a failed login attempt.

    Args:
        db: Database session
        username: Attempted username
        request: FastAPI request
        reason: Reason for failure
    """
    client_info = get_client_info(request)
    return log_audit(
        db=db,
        user_id=None,  # No user ID for failed logins
        username=username,
        action=AuditAction.LOGIN_FAILED,
        entity_type=AuditEntityType.SESSION,
        details={'reason': reason},
        **client_info,
    )


def log_host_change(
    db: Session,
    user_id: int,
    username: str,
    action: AuditAction,
    host_id: str,
    host_name: str,
    request: Request,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """
    Log a host create/update/delete action.

    Args:
        db: Database session
        user_id: User ID
        username: Username
        action: CREATE, UPDATE, or DELETE
        host_id: Host ID
        host_name: Host name
        request: FastAPI request
        details: Additional context (e.g., changed fields)
    """
    client_info = get_client_info(request)
    return log_audit(
        db=db,
        user_id=user_id,
        username=username,
        action=action,
        entity_type=AuditEntityType.HOST,
        entity_id=host_id,
        entity_name=host_name,
        details=details,
        **client_info,
    )


def log_user_change(
    db: Session,
    user_id: int,
    username: str,
    action: AuditAction,
    target_user_id: int,
    target_username: str,
    request: Request,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """
    Log a user create/update/delete action.

    Args:
        db: Database session
        user_id: User performing the action
        username: Username of actor
        action: CREATE, UPDATE, DELETE, or ROLE_CHANGE
        target_user_id: ID of affected user
        target_username: Username of affected user
        request: FastAPI request
        details: Additional context (e.g., role change details)
    """
    client_info = get_client_info(request)
    return log_audit(
        db=db,
        user_id=user_id,
        username=username,
        action=action,
        entity_type=AuditEntityType.USER,
        entity_id=str(target_user_id),
        entity_name=target_username,
        details=details,
        **client_info,
    )


def log_container_action(
    db: Session,
    user_id: int,
    username: str,
    action: AuditAction,
    host_id: str,
    container_id: str,
    container_name: str,
    request: Request,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """
    Log a container action (start, stop, restart, shell, update).

    Args:
        db: Database session
        user_id: User ID
        username: Username
        action: START, STOP, RESTART, SHELL, SHELL_END, CONTAINER_UPDATE
        host_id: Host ID
        container_id: Container ID (short, 12 chars)
        container_name: Container name
        request: FastAPI request
        details: Additional context
    """
    client_info = get_client_info(request)
    return log_audit(
        db=db,
        user_id=user_id,
        username=username,
        action=action,
        entity_type=AuditEntityType.CONTAINER,
        entity_id=container_id,
        entity_name=container_name,
        host_id=host_id,
        details=details,
        **client_info,
    )


def log_stack_change(
    db: Session,
    user_id: int,
    username: str,
    action: AuditAction,
    stack_name: str,
    request: Request,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """
    Log a stack create/update/delete/deploy action.

    Args:
        db: Database session
        user_id: User ID
        username: Username
        action: CREATE, UPDATE, DELETE, or DEPLOY
        stack_name: Stack name
        request: FastAPI request
        details: Additional context
    """
    client_info = get_client_info(request)
    return log_audit(
        db=db,
        user_id=user_id,
        username=username,
        action=action,
        entity_type=AuditEntityType.STACK,
        entity_id=stack_name,
        entity_name=stack_name,
        details=details,
        **client_info,
    )


def log_settings_change(
    db: Session,
    user_id: int,
    username: str,
    setting_name: str,
    request: Request,
    old_value: Optional[Any] = None,
    new_value: Optional[Any] = None,
) -> AuditLog:
    """
    Log a settings change.

    Args:
        db: Database session
        user_id: User ID
        username: Username
        setting_name: Name of setting changed
        request: FastAPI request
        old_value: Previous value (optional, for sensitive settings may be omitted)
        new_value: New value (optional, for sensitive settings may be omitted)
    """
    client_info = get_client_info(request)
    details = {'setting': setting_name}
    if old_value is not None:
        details['old_value'] = old_value
    if new_value is not None:
        details['new_value'] = new_value

    return log_audit(
        db=db,
        user_id=user_id,
        username=username,
        action=AuditAction.SETTINGS_CHANGE,
        entity_type=AuditEntityType.SETTINGS,
        entity_name=setting_name,
        details=details,
        **client_info,
    )
