"""
Audit logging module for DockMon v2.3.0 Multi-User Support.

Provides helper functions for recording user actions to the audit log.
"""

from .audit_logger import (
    AuditAction,
    AuditEntityType,
    log_audit,
    log_login,
    log_logout,
    log_login_failure,
    log_host_change,
    log_user_change,
    log_container_action,
    log_stack_change,
    log_settings_change,
    get_client_info,
)

__all__ = [
    'AuditAction',
    'AuditEntityType',
    'log_audit',
    'log_login',
    'log_logout',
    'log_login_failure',
    'log_host_change',
    'log_user_change',
    'log_container_action',
    'log_stack_change',
    'log_settings_change',
    'get_client_info',
]
