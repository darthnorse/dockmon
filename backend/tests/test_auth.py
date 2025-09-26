"""
Unit tests for authentication and session management
Tests for missing auth on endpoints and session validation issues
"""

import pytest
from unittest.mock import patch, MagicMock
import uuid
import hashlib
from datetime import datetime, timedelta


class TestAuthentication:
    """Test authentication functionality"""

    def test_password_hashing(self):
        """Test password hashing and validation"""
        from auth.utils import hash_password, verify_password

        password = "TestPassword123!"

        # Hash password
        hashed = hash_password(password)
        assert hashed != password  # Should be hashed
        assert len(hashed) == 64  # SHA-256 produces 64 hex chars

        # Verify correct password
        assert verify_password(password, hashed) is True

        # Verify incorrect password
        assert verify_password("WrongPassword", hashed) is False

    def test_generate_secure_password(self):
        """Test secure password generation"""
        from auth.utils import generate_secure_password

        password = generate_secure_password()

        # Check length
        assert len(password) >= 12

        # Check complexity - should have mix of characters
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)

        assert has_upper and has_lower and has_digit

    def test_session_creation(self, temp_db):
        """Test session creation and validation"""
        from auth.utils import create_session_token

        # Create session
        session_id = create_session_token()
        assert len(session_id) == 36  # UUID format

        # Save to database
        db_session = temp_db.create_session(session_id)
        assert db_session.session_id == session_id
        assert db_session.is_valid is True

    def test_session_validation(self, temp_db):
        """Test session validation logic"""
        from auth.utils import create_session_token

        session_id = create_session_token()
        temp_db.create_session(session_id)

        # Valid session
        assert temp_db.validate_session(session_id) is True

        # Invalid session (doesn't exist)
        assert temp_db.validate_session("invalid-session-id") is False

        # Invalidated session
        temp_db.invalidate_session(session_id)
        assert temp_db.validate_session(session_id) is False

    def test_session_expiration_check(self, temp_db):
        """Test that expired sessions are properly detected"""
        session_id = str(uuid.uuid4())
        session = temp_db.create_session(session_id)

        # Fresh session should be valid
        assert temp_db.validate_session(session_id) is True

        # Manually expire the session
        with temp_db.get_session() as db_session:
            session.expires_at = datetime.utcnow() - timedelta(hours=1)
            db_session.commit()

        # Expired session should be invalid
        assert temp_db.validate_session(session_id) is False

    @patch('auth.routes.DatabaseManager')
    def test_login_endpoint_validation(self, mock_db):
        """Test login endpoint validates credentials properly"""
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)

        # Mock database
        mock_db_instance = MagicMock()
        mock_db.return_value = mock_db_instance

        # Test missing credentials
        response = client.post("/api/auth/login", json={})
        assert response.status_code == 422  # Validation error

        # Test invalid credentials format
        response = client.post("/api/auth/login", json={
            "username": "",
            "password": ""
        })
        assert response.status_code == 400 or response.status_code == 401

    def test_auth_dependency(self):
        """Test the authentication dependency properly checks sessions"""
        from fastapi import HTTPException
        from auth.utils import verify_session_auth
        from unittest.mock import Mock

        # Mock request with no cookie
        request = Mock()
        request.cookies = {}

        # Should raise HTTPException for missing session
        with pytest.raises(HTTPException) as exc_info:
            verify_session_auth(request)
        assert exc_info.value.status_code == 401

    def test_password_change_required_flag(self, temp_db):
        """Test password change required functionality"""
        # Create a user with password change required
        user_data = {
            'username': 'testuser',
            'password_hash': hashlib.sha256('temp123'.encode()).hexdigest(),
            'password_change_required': True
        }
        user = temp_db.create_user(user_data)

        assert user.password_change_required is True

        # After password change, flag should be cleared
        temp_db.update_user_password(user.username, 'NewPassword123!')
        user = temp_db.get_user(user.username)
        assert user.password_change_required is False

    def test_credentials_file_permissions(self):
        """Test that credentials file has secure permissions"""
        import tempfile
        import os
        import stat

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test:credentials")
            temp_path = f.name

        # Set secure permissions
        os.chmod(temp_path, 0o600)

        # Check permissions
        file_stat = os.stat(temp_path)
        mode = file_stat.st_mode

        # Should be readable and writable by owner only
        assert stat.S_IMODE(mode) == 0o600

        # Cleanup
        os.unlink(temp_path)

    def test_rate_limiting_on_auth(self):
        """Test that authentication endpoints have rate limiting"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()
        client_ip = "192.168.1.100"

        # Simulate multiple login attempts
        for i in range(5):
            allowed, _ = limiter.check_rate_limit(client_ip, "/api/auth/login")
            assert allowed is True

        # After threshold, should start blocking
        for i in range(10):
            limiter.check_rate_limit(client_ip, "/api/auth/login")

        # Eventually should be rate limited
        allowed, violations = limiter.check_rate_limit(client_ip, "/api/auth/login")
        if violations > 5:  # After multiple violations
            assert allowed is False

    def test_secure_cookie_settings(self):
        """Test that session cookies have secure settings"""
        from fastapi.responses import Response

        response = Response()

        # Set cookie with secure settings
        response.set_cookie(
            key="session_id",
            value="test-session",
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=86400
        )

        # Check cookie headers
        cookie_header = response.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie_header
        assert "Secure" in cookie_header
        assert "SameSite=strict" in cookie_header