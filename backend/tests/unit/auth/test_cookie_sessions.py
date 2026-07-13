"""
Cookie session manager tests.

Regression guard: sessions must NOT be invalidated when the client IP changes.
Exact-IP session binding was removed in 2.4.5 because it logged out legitimate
users behind Cloudflare/CDNs, reverse proxies, mobile networks, and dual-stack
IPv6 (the client-facing IP legitimately rotates between requests). See #237.
"""

import pytest

from auth.cookie_sessions import CookieSessionManager


@pytest.fixture
def manager(monkeypatch):
    # Pin the timeout so tests don't hit the DB-backed getter.
    monkeypatch.setattr("auth.cookie_sessions.get_session_timeout_hours", lambda: 24)
    mgr = CookieSessionManager()
    try:
        yield mgr
    finally:
        mgr.shutdown()


class TestIpChangeDoesNotInvalidate:
    """A session created from one IP stays valid when accessed from another."""

    def test_ip_change_still_validates(self, manager):
        token = manager.create_session(
            user_id=1, username="alice", client_ip="104.23.168.60"
        )

        # Same client, different Cloudflare egress IP on the next request.
        result = manager.validate_session(token, client_ip="172.71.183.137")

        assert result is not None
        assert result["username"] == "alice"

    def test_creation_ip_is_still_recorded(self, manager):
        """client_ip is retained on the session for audit purposes."""
        token = manager.create_session(
            user_id=1, username="alice", client_ip="104.23.168.60"
        )
        session_id = manager.validate_session(token, client_ip="172.71.183.137")[
            "session_id"
        ]
        assert manager.sessions[session_id]["client_ip"] == "104.23.168.60"


class TestSessionStillInvalidatesForRealFailures:
    """Removing IP binding must not weaken the other checks."""

    def test_empty_token_rejected(self, manager):
        assert manager.validate_session("", client_ip="1.2.3.4") is None

    def test_bad_signature_rejected(self, manager):
        assert (
            manager.validate_session("not-a-valid-token", client_ip="1.2.3.4") is None
        )

    def test_unknown_session_rejected(self, manager):
        # Valid signature over a session id that isn't in the store.
        from auth.cookie_sessions import COOKIE_SIGNER

        orphan = COOKIE_SIGNER.dumps("nonexistent-session-id")
        assert manager.validate_session(orphan, client_ip="1.2.3.4") is None
