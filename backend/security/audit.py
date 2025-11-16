"""
Security Audit Logging System for DockMon
Tracks all security-relevant events for incident response
"""

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional


class SecurityAuditLogger:
    """
    Comprehensive security audit logging system
    Tracks all security-relevant events for incident response
    """
    def __init__(self, event_logger=None):
        self.security_logger = logging.getLogger('security_audit')
        self.event_logger = event_logger

        # Create separate log file for security events in persistent volume
        from config.paths import DATA_DIR
        log_dir = os.path.join(DATA_DIR, 'logs')
        os.makedirs(log_dir, mode=0o700, exist_ok=True)

        # Rotating file handler for security audit logs
        # Max 10MB per file, keep 14 backups (total max 150MB with current + 14 backups)
        security_handler = RotatingFileHandler(
            os.path.join(log_dir, 'security_audit.log'),
            maxBytes=10*1024*1024,  # 10MB
            backupCount=14,  # Keep 14 old files
            encoding='utf-8'
        )
        security_handler.setLevel(logging.INFO)

        # Structured logging format for security events
        security_formatter = logging.Formatter(
            '%(asctime)s - SECURITY - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S UTC'
        )
        security_handler.setFormatter(security_formatter)
        self.security_logger.addHandler(security_handler)
        self.security_logger.setLevel(logging.INFO)
        self.security_logger.propagate = False  # Don't propagate to root logger

    def set_event_logger(self, event_logger):
        """Set the event logger instance for logging to Event Viewer"""
        self.event_logger = event_logger

    def _log_security_event(self, level: str, event_type: str, client_ip: str,
                           endpoint: str = None, user_agent: str = None,
                           details: dict = None, risk_level: str = "LOW"):
        """Internal method to log structured security events"""
        log_data = {
            "event_type": event_type,
            "client_ip": client_ip,
            "endpoint": endpoint,
            "user_agent": user_agent or "unknown",
            "risk_level": risk_level,
            "details": details or {}
        }

        # Convert to JSON for structured logging
        message = json.dumps(log_data, default=str)

        if level.upper() == "ERROR":
            self.security_logger.error(message)
        elif level.upper() == "WARNING":
            self.security_logger.warning(message)
        else:
            self.security_logger.info(message)

    def log_authentication_attempt(self, client_ip: str, success: bool, endpoint: str, user_agent: str = None):
        """Log authentication attempts (both success and failure)"""
        event_type = "AUTH_SUCCESS" if success else "AUTH_FAILURE"
        risk_level = "LOW" if success else "MEDIUM"
        level = "INFO" if success else "WARNING"

        self._log_security_event(
            level=level,
            event_type=event_type,
            client_ip=client_ip,
            endpoint=endpoint,
            user_agent=user_agent,
            risk_level=risk_level
        )

    def log_rate_limit_violation(self, client_ip: str, endpoint: str, violations: int, banned: bool = False):
        """Log rate limiting violations and bans"""
        event_type = "RATE_LIMIT_BAN" if banned else "RATE_LIMIT_VIOLATION"
        risk_level = "HIGH" if banned else "MEDIUM"

        self._log_security_event(
            level="ERROR" if banned else "WARNING",
            event_type=event_type,
            client_ip=client_ip,
            endpoint=endpoint,
            details={"violation_count": violations, "banned": banned},
            risk_level=risk_level
        )

    def log_input_validation_failure(self, client_ip: str, endpoint: str, field: str,
                                   attempted_value: str, user_agent: str = None):
        """Log input validation failures (potential attacks)"""
        self._log_security_event(
            level="WARNING",
            event_type="INPUT_VALIDATION_FAILURE",
            client_ip=client_ip,
            endpoint=endpoint,
            user_agent=user_agent,
            details={
                "field": field,
                "attempted_value": attempted_value[:100] if attempted_value else None,  # Limit log size
                "attack_indicators": self._detect_attack_patterns(attempted_value)
            },
            risk_level="HIGH"
        )

    def log_cors_violation(self, client_ip: str, origin: str, endpoint: str):
        """Log CORS policy violations"""
        self._log_security_event(
            level="WARNING",
            event_type="CORS_VIOLATION",
            client_ip=client_ip,
            endpoint=endpoint,
            details={"blocked_origin": origin},
            risk_level="MEDIUM"
        )

    def log_privileged_action(self, client_ip: str, action: str, target: str, success: bool, user_agent: str = None):
        """Log privileged actions (host management, container control, etc.)"""
        event_type = f"PRIVILEGED_ACTION_{action.upper()}"
        risk_level = "MEDIUM" if success else "HIGH"

        self._log_security_event(
            level="INFO" if success else "ERROR",
            event_type=event_type,
            client_ip=client_ip,
            user_agent=user_agent,
            details={
                "action": action,
                "target": target,
                "success": success
            },
            risk_level=risk_level
        )

    def log_suspicious_activity(self, client_ip: str, activity_type: str, details: dict, endpoint: str = None):
        """Log suspicious activities that don't fit other categories"""
        self._log_security_event(
            level="ERROR",
            event_type="SUSPICIOUS_ACTIVITY",
            client_ip=client_ip,
            endpoint=endpoint,
            details={
                "activity_type": activity_type,
                **details
            },
            risk_level="HIGH"
        )

    def _detect_attack_patterns(self, value: str) -> list:
        """Detect common attack patterns in input"""
        if not value:
            return []

        patterns = []
        value_lower = value.lower()

        # XSS patterns
        if any(pattern in value_lower for pattern in ['<script', 'javascript:', 'onerror=', 'onload=']):
            patterns.append("XSS")

        # SQL injection patterns
        if any(pattern in value_lower for pattern in [' or ', ' union ', ' select ', "'; drop", '1=1']):
            patterns.append("SQL_INJECTION")

        # Command injection patterns
        if any(pattern in value_lower for pattern in ['; rm ', '| cat ', '&& curl', 'wget ', '`whoami`']):
            patterns.append("COMMAND_INJECTION")

        # Path traversal patterns
        if any(pattern in value for pattern in ['../../../', '..\\..\\', '/etc/passwd', 'c:\\windows']):
            patterns.append("PATH_TRAVERSAL")

        # SSRF patterns
        if any(pattern in value_lower for pattern in ['localhost', '127.0.0.1', '169.254.169.254']):
            patterns.append("SSRF")

        return patterns

    def get_security_stats(self, hours: int = 24) -> dict:
        """Get security statistics for the last N hours"""
        # This is a simplified version - in production you'd query actual log files
        return {
            "timeframe_hours": hours,
            "total_security_events": "N/A - check logs/security_audit.log",
            "log_location": "logs/security_audit.log",
            "note": "Parse JSON logs for detailed statistics"
        }

    def log_login_success(self, client_ip: str, user_agent: str, session_id: str):
        """Log successful login attempt"""
        self._log_security_event(
            level="INFO",
            event_type="LOGIN_SUCCESS",
            client_ip=client_ip,
            user_agent=user_agent,
            details={"session_id": session_id[:8] + "..."},  # Don't log full session ID
            risk_level="LOW"
        )

    def log_login_failure(self, client_ip: str, user_agent: str, reason: str):
        """Log failed login attempt"""
        self._log_security_event(
            level="WARNING",
            event_type="LOGIN_FAILURE",
            client_ip=client_ip,
            user_agent=user_agent,
            details={"reason": reason},
            risk_level="MEDIUM"
        )

    def log_session_expired(self, client_ip: str, session_id: str):
        """Log session expiration"""
        self._log_security_event(
            level="INFO",
            event_type="SESSION_EXPIRED",
            client_ip=client_ip,
            details={"session_id": session_id[:8] + "..."},
            risk_level="LOW"
        )

    def log_session_hijack_attempt(self, original_ip: str, attempted_ip: str, session_id: str):
        """Log potential session hijacking attempt"""
        self._log_security_event(
            level="ERROR",
            event_type="SESSION_HIJACK_ATTEMPT",
            client_ip=attempted_ip,
            details={
                "original_ip": original_ip,
                "attempted_ip": attempted_ip,
                "session_id": session_id[:8] + "..."
            },
            risk_level="HIGH"
        )

    def log_authentication_failure(self, client_ip: str, user_agent: str, reason: str):
        """Log authentication failure"""
        self._log_security_event(
            level="WARNING",
            event_type="AUTH_FAILURE",
            client_ip=client_ip,
            user_agent=user_agent,
            details={"reason": reason},
            risk_level="MEDIUM"
        )

    def log_password_change(self, client_ip: str, user_agent: str, username: str):
        """Log password change event"""
        self._log_security_event(
            level="INFO",
            event_type="PASSWORD_CHANGE",
            client_ip=client_ip,
            user_agent=user_agent,
            details={"username": username, "message": f"Password changed for user: {username}"},
            risk_level="LOW"
        )

        # Also log to event logger for Event Viewer
        if self.event_logger:
            from event_logger import EventCategory, EventType, EventSeverity
            self.event_logger.log_event(
                category=EventCategory.USER,
                event_type=EventType.CONFIG_CHANGED,
                title="Password Changed",
                message=f"User '{username}' changed their password from IP: {client_ip}",
                severity=EventSeverity.INFO,
                details={"username": username, "client_ip": client_ip, "user_agent": user_agent}
            )

    def log_username_change(self, client_ip: str, user_agent: str, old_username: str, new_username: str):
        """Log username change event"""
        self._log_security_event(
            level="INFO",
            event_type="USERNAME_CHANGE",
            client_ip=client_ip,
            user_agent=user_agent,
            details={
                "old_username": old_username,
                "new_username": new_username,
                "message": f"Username changed from {old_username} to {new_username}"
            },
            risk_level="LOW"
        )

        # Also log to event logger for Event Viewer
        if self.event_logger:
            from event_logger import EventCategory, EventType, EventSeverity
            self.event_logger.log_event(
                category=EventCategory.USER,
                event_type=EventType.CONFIG_CHANGED,
                title="Username Changed",
                message=f"Username changed from '{old_username}' to '{new_username}' from IP: {client_ip}",
                severity=EventSeverity.INFO,
                details={"old_username": old_username, "new_username": new_username, "client_ip": client_ip, "user_agent": user_agent}
            )

    def log_event(self, event_type: str, severity: str = "info", user_id: int = None,
                  client_ip: str = "unknown", endpoint: str = None, user_agent: str = None,
                  details: dict = None):
        """
        General-purpose security event logging method for API key authentication.

        Args:
            event_type: Type of security event (e.g., "api_key_invalid_format", "scope_violation")
            severity: Event severity ("info", "warning", "error")
            user_id: User ID if applicable
            client_ip: Client IP address
            endpoint: API endpoint if applicable
            user_agent: User agent string if applicable
            details: Additional event details as dict
        """
        # Map severity to risk level
        risk_level_map = {
            "info": "LOW",
            "warning": "MEDIUM",
            "error": "HIGH"
        }
        risk_level = risk_level_map.get(severity.lower(), "MEDIUM")

        # Add user_id to details if provided
        event_details = details or {}
        if user_id:
            event_details["user_id"] = user_id

        # Log the event
        self._log_security_event(
            level=severity,
            event_type=event_type,
            client_ip=client_ip,
            endpoint=endpoint,
            user_agent=user_agent,
            details=event_details,
            risk_level=risk_level
        )


# Global security audit logger instance
security_audit = SecurityAuditLogger()