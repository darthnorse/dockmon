"""
Unit tests for Cookie Session Manager

SECURITY TESTS:
- Session creation and validation
- Signature tampering detection
- Session expiry enforcement
- IP validation (anti-hijacking)
- Concurrent access safety
- Memory leak prevention
"""

import pytest
import time
from datetime import timedelta
from auth.cookie_sessions import CookieSessionManager, COOKIE_SIGNER


class TestCookieSessionManager:
    """Test suite for secure cookie-based session management"""

    @pytest.fixture
    def session_manager(self):
        """Create a fresh session manager for each test"""
        manager = CookieSessionManager(session_timeout_hours=1)
        yield manager
        manager.shutdown()  # Cleanup

    def test_create_session(self, session_manager):
        """Test session creation returns signed token"""
        token = session_manager.create_session(
            user_id=1,
            username="testuser",
            client_ip="192.168.1.100"
        )

        # Token should be a non-empty string
        assert isinstance(token, str)
        assert len(token) > 0

        # Should be a valid signed token
        session_id = COOKIE_SIGNER.loads(token)
        assert isinstance(session_id, str)

    def test_validate_session_success(self, session_manager):
        """Test successful session validation"""
        token = session_manager.create_session(
            user_id=1,
            username="testuser",
            client_ip="192.168.1.100"
        )

        # Validate with same IP
        session_data = session_manager.validate_session(
            token,
            client_ip="192.168.1.100"
        )

        assert session_data is not None
        assert session_data["user_id"] == 1
        assert session_data["username"] == "testuser"

    def test_session_ip_validation_prevents_hijacking(self, session_manager):
        """SECURITY: Session should be invalidated if IP changes"""
        token = session_manager.create_session(
            user_id=1,
            username="testuser",
            client_ip="192.168.1.100"
        )

        # Try to validate from different IP (hijack attempt)
        session_data = session_manager.validate_session(
            token,
            client_ip="10.0.0.50"  # Different IP
        )

        # Should fail validation
        assert session_data is None

        # Session should be deleted (security measure)
        session_data = session_manager.validate_session(
            token,
            client_ip="192.168.1.100"  # Even original IP
        )
        assert session_data is None

    def test_signature_tampering_detection(self, session_manager):
        """SECURITY: Detect tampered session tokens"""
        token = session_manager.create_session(
            user_id=1,
            username="testuser",
            client_ip="192.168.1.100"
        )

        # Tamper with token
        tampered_token = token[:-5] + "XXXXX"

        # Should fail validation (bad signature)
        session_data = session_manager.validate_session(
            tampered_token,
            client_ip="192.168.1.100"
        )

        assert session_data is None

    def test_session_expiry(self, session_manager):
        """SECURITY: Expired sessions should be rejected"""
        # Create manager with 1 second timeout
        short_timeout_manager = CookieSessionManager(session_timeout_hours=1/3600)  # 1 second

        token = short_timeout_manager.create_session(
            user_id=1,
            username="testuser",
            client_ip="192.168.1.100"
        )

        # Wait for expiry
        time.sleep(1.5)

        # Should fail validation (expired)
        session_data = short_timeout_manager.validate_session(
            token,
            client_ip="192.168.1.100",
            max_age_seconds=1
        )

        assert session_data is None

        short_timeout_manager.shutdown()

    def test_session_deletion(self, session_manager):
        """Test logout deletes session"""
        token = session_manager.create_session(
            user_id=1,
            username="testuser",
            client_ip="192.168.1.100"
        )

        # Delete session
        result = session_manager.delete_session(token)
        assert result is True

        # Should fail validation after deletion
        session_data = session_manager.validate_session(
            token,
            client_ip="192.168.1.100"
        )
        assert session_data is None

    def test_cleanup_expired_sessions(self, session_manager):
        """MEMORY SAFETY: Test automatic cleanup of expired sessions"""
        # Create multiple sessions
        for i in range(5):
            session_manager.create_session(
                user_id=i,
                username=f"user{i}",
                client_ip="192.168.1.100"
            )

        # Verify sessions exist
        assert session_manager.get_active_session_count() == 5

        # Manually expire all sessions
        for session_data in session_manager.sessions.values():
            session_data["created_at"] = session_data["created_at"] - timedelta(hours=25)

        # Run cleanup
        deleted_count = session_manager.cleanup_expired_sessions()

        # All sessions should be deleted
        assert deleted_count == 5
        assert session_manager.get_active_session_count() == 0

    def test_concurrent_session_access(self, session_manager):
        """THREAD SAFETY: Test concurrent access doesn't corrupt state"""
        import threading

        tokens = []
        errors = []

        def create_sessions():
            try:
                for i in range(10):
                    token = session_manager.create_session(
                        user_id=i,
                        username=f"user{i}",
                        client_ip="192.168.1.100"
                    )
                    tokens.append(token)
            except Exception as e:
                errors.append(e)

        # Create multiple threads
        threads = [threading.Thread(target=create_sessions) for _ in range(5)]

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # No errors should occur
        assert len(errors) == 0

        # All tokens should be valid
        assert len(tokens) == 50  # 5 threads * 10 sessions

    def test_empty_token_handling(self, session_manager):
        """Test handling of None/empty tokens"""
        assert session_manager.validate_session(None, "192.168.1.100") is None
        assert session_manager.validate_session("", "192.168.1.100") is None

    def test_graceful_shutdown(self, session_manager):
        """MEMORY SAFETY: Test cleanup thread terminates properly"""
        # Create some sessions
        for i in range(3):
            session_manager.create_session(
                user_id=i,
                username=f"user{i}",
                client_ip="192.168.1.100"
            )

        # Shutdown should complete without hanging
        session_manager.shutdown()

        # Cleanup thread should be stopped
        assert not session_manager._cleanup_thread.is_alive()

    def test_session_count_limit(self):
        """DOS PROTECTION: Test maximum session limit enforcement"""
        # Create manager with small limit
        manager = CookieSessionManager(session_timeout_hours=1, max_sessions=5)

        try:
            # Create 5 sessions (should succeed)
            tokens = []
            for i in range(5):
                token = manager.create_session(
                    user_id=i,
                    username=f"user{i}",
                    client_ip="192.168.1.100"
                )
                tokens.append(token)

            # All 5 should be valid
            assert manager.get_active_session_count() == 5

            # 6th session should fail (at capacity)
            with pytest.raises(Exception) as exc_info:
                manager.create_session(
                    user_id=999,
                    username="overflow_user",
                    client_ip="192.168.1.100"
                )

            assert "maximum capacity" in str(exc_info.value).lower()

        finally:
            manager.shutdown()

    def test_session_limit_with_cleanup(self):
        """DOS PROTECTION: Test session limit triggers cleanup"""
        # Create manager with small limit and short timeout
        manager = CookieSessionManager(session_timeout_hours=0.0001, max_sessions=3)  # ~0.36 seconds

        try:
            # Create 3 sessions
            for i in range(3):
                manager.create_session(
                    user_id=i,
                    username=f"user{i}",
                    client_ip="192.168.1.100"
                )

            # Wait for sessions to expire
            time.sleep(1)

            # 4th session should succeed (triggers cleanup of expired sessions)
            token = manager.create_session(
                user_id=999,
                username="new_user",
                client_ip="192.168.1.100"
            )

            # Should have only 1 active session (old ones cleaned up)
            assert manager.get_active_session_count() == 1

        finally:
            manager.shutdown()


class TestSessionSecurity:
    """Additional security-focused tests"""

    def test_session_id_randomness(self):
        """SECURITY: Session IDs should be cryptographically random"""
        manager = CookieSessionManager()

        # Create multiple sessions
        tokens = [
            manager.create_session(i, f"user{i}", "192.168.1.100")
            for i in range(100)
        ]

        # All tokens should be unique (no collisions)
        assert len(set(tokens)) == 100

        # Tokens should have sufficient entropy (length check)
        for token in tokens:
            assert len(token) > 40  # Signed tokens are longer than raw session IDs

        manager.shutdown()

    def test_session_metadata_isolation(self):
        """SECURITY: Session data should be isolated per user"""
        manager = CookieSessionManager()

        token1 = manager.create_session(1, "alice", "192.168.1.100")
        token2 = manager.create_session(2, "bob", "192.168.1.101")

        # Each session should have correct user data
        alice_session = manager.validate_session(token1, "192.168.1.100")
        bob_session = manager.validate_session(token2, "192.168.1.101")

        assert alice_session["user_id"] == 1
        assert alice_session["username"] == "alice"

        assert bob_session["user_id"] == 2
        assert bob_session["username"] == "bob"

        # Sessions should not interfere with each other
        assert alice_session != bob_session

        manager.shutdown()

    def test_session_fixation_prevention(self):
        """SECURITY: New session ID on each login (prevent fixation attacks)"""
        manager = CookieSessionManager()

        # Login twice as same user
        token1 = manager.create_session(1, "testuser", "192.168.1.100")
        token2 = manager.create_session(1, "testuser", "192.168.1.100")

        # Tokens should be different (new session each time)
        assert token1 != token2

        manager.shutdown()
