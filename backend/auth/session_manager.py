"""
Session Management System for DockMon
Provides secure session tokens with IP validation and automatic cleanup
"""

import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from fastapi import Request

from security.audit import security_audit


class SessionManager:
    """
    Custom session management for frontend authentication
    Provides secure session tokens with configurable expiry
    """
    def __init__(self):
        self.sessions: Dict[str, dict] = {}
        self.session_timeout = timedelta(hours=24)  # 24 hour sessions
        self._cleanup_thread = threading.Thread(target=self._periodic_cleanup, daemon=True)
        self._cleanup_thread.start()

    def _periodic_cleanup(self):
        """Run cleanup every hour"""
        while True:
            time.sleep(3600)  # Run every hour
            try:
                self.cleanup_expired_sessions()
            except Exception:
                pass  # Silent failure for background thread

    def create_session(self, request: Request, username: str = None) -> str:
        """Create a new session token"""
        session_id = secrets.token_urlsafe(32)
        client_ip = request.client.host
        user_agent = request.headers.get("user-agent", "Unknown")

        self.sessions[session_id] = {
            "created_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
            "client_ip": client_ip,
            "user_agent": user_agent,
            "authenticated": True,
            "username": username
        }

        # Security audit log
        security_audit.log_login_success(client_ip, user_agent, session_id)

        return session_id

    def validate_session(self, session_id: Optional[str], request: Request) -> bool:
        """Validate session token and update last accessed time"""
        if not session_id or session_id not in self.sessions:
            return False

        session = self.sessions[session_id]
        current_time = datetime.utcnow()
        client_ip = request.client.host

        # Check if session has expired
        if current_time - session["created_at"] > self.session_timeout:
            self.delete_session(session_id)
            security_audit.log_session_expired(client_ip, session_id)
            return False

        # Validate IP consistency for security
        if session["client_ip"] != client_ip:
            security_audit.log_session_hijack_attempt(
                original_ip=session["client_ip"],
                attempted_ip=client_ip,
                session_id=session_id
            )
            self.delete_session(session_id)
            return False

        # Update last accessed time
        session["last_accessed"] = current_time
        return True

    def delete_session(self, session_id: str):
        """Delete a session (logout)"""
        if session_id in self.sessions:
            del self.sessions[session_id]

    def get_session_username(self, session_id: str) -> Optional[str]:
        """Get username from session"""
        if session_id in self.sessions:
            return self.sessions[session_id].get("username")
        return None

    def update_session_username(self, session_id: str, new_username: str):
        """Update username in session"""
        if session_id in self.sessions:
            self.sessions[session_id]["username"] = new_username

    def cleanup_expired_sessions(self):
        """Clean up expired sessions periodically"""
        current_time = datetime.utcnow()
        expired_sessions = []

        for session_id, session_data in self.sessions.items():
            if current_time - session_data["created_at"] > self.session_timeout:
                expired_sessions.append(session_id)

        for session_id in expired_sessions:
            self.delete_session(session_id)

        return len(expired_sessions)


# Global session manager instance
session_manager = SessionManager()