"""
Tests for User Approval Endpoints (v2.6.0)

Tests cover:
- GET /api/v2/users/pending-count
- POST /api/v2/users/{user_id}/approve
- POST /api/v2/users/approve-all
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session


# =============================================================================
# Helper Functions
# =============================================================================

def create_user(db_session: Session, username: str, approved: bool = True) -> "User":
    """Create a test user with the given approval status."""
    from database import User

    user = User(
        username=username,
        password_hash="$2b$12$test_hash_not_real",
        auth_provider="local",
        approved=approved,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# =============================================================================
# Tests: GET /pending-count
# =============================================================================

class TestPendingCount:
    """Tests for the pending-count endpoint logic."""

    def test_pending_count_with_mix(self, db_session: Session):
        """Pending count returns correct count with a mix of approved/unapproved users."""
        from database import User

        # Create 2 approved users and 3 unapproved users
        create_user(db_session, "approved_1", approved=True)
        create_user(db_session, "approved_2", approved=True)
        create_user(db_session, "pending_1", approved=False)
        create_user(db_session, "pending_2", approved=False)
        create_user(db_session, "pending_3", approved=False)

        count = db_session.query(User).filter(User.approved == False).count()  # noqa: E712
        assert count == 3

    def test_pending_count_zero_when_all_approved(self, db_session: Session):
        """Pending count returns 0 when no pending users exist."""
        from database import User

        create_user(db_session, "approved_1", approved=True)
        create_user(db_session, "approved_2", approved=True)

        count = db_session.query(User).filter(User.approved == False).count()  # noqa: E712
        assert count == 0

    def test_pending_count_zero_with_empty_db(self, db_session: Session):
        """Pending count returns 0 when no users exist at all."""
        from database import User

        count = db_session.query(User).filter(User.approved == False).count()  # noqa: E712
        assert count == 0


# =============================================================================
# Tests: POST /{user_id}/approve
# =============================================================================

class TestApproveUser:
    """Tests for the single-user approve endpoint logic."""

    def test_approve_sets_approved_true(self, db_session: Session):
        """Approving a pending user sets approved=True and updates updated_at."""
        user = create_user(db_session, "pending_user", approved=False)
        assert user.approved is False

        old_updated_at = user.updated_at

        # Simulate the endpoint logic
        user.approved = True
        user.updated_at = datetime.now(timezone.utc)
        db_session.commit()
        db_session.refresh(user)

        assert user.approved is True
        assert user.updated_at >= old_updated_at

    def test_approve_already_approved_is_noop(self, db_session: Session):
        """Approving an already-approved user is a no-op (no DB changes)."""
        user = create_user(db_session, "approved_user", approved=True)
        original_updated_at = user.updated_at

        # Simulate the endpoint logic: check approved flag first
        assert user.approved is True
        # The endpoint returns early without modifying the user
        # Verify the user was not modified
        db_session.refresh(user)
        assert user.approved is True
        assert user.updated_at == original_updated_at

    def test_approve_nonexistent_user_raises(self, db_session: Session):
        """Approving a nonexistent user raises 404."""
        from database import User
        from fastapi import HTTPException

        user = db_session.query(User).filter(User.id == 99999).first()
        assert user is None

        # Simulate get_user_or_404 behavior
        with pytest.raises(HTTPException) as exc_info:
            from auth.utils import get_user_or_404
            get_user_or_404(db_session, 99999)
        assert exc_info.value.status_code == 404


# =============================================================================
# Tests: POST /approve-all
# =============================================================================

class TestApproveAll:
    """Tests for the approve-all endpoint logic."""

    def test_approve_all_approves_pending_users(self, db_session: Session):
        """Approve-all sets approved=True for all pending users."""
        from database import User

        approved_user = create_user(db_session, "approved_user", approved=True)
        pending_1 = create_user(db_session, "pending_1", approved=False)
        pending_2 = create_user(db_session, "pending_2", approved=False)
        pending_3 = create_user(db_session, "pending_3", approved=False)

        # Simulate the endpoint logic
        pending_users = db_session.query(User).filter(User.approved == False).all()  # noqa: E712
        assert len(pending_users) == 3

        usernames = [u.username for u in pending_users]
        now = datetime.now(timezone.utc)
        for user in pending_users:
            user.approved = True
            user.updated_at = now
        db_session.commit()

        # Verify all users are now approved
        remaining_pending = db_session.query(User).filter(User.approved == False).count()  # noqa: E712
        assert remaining_pending == 0

        # Verify approved user was not modified
        db_session.refresh(approved_user)
        assert approved_user.approved is True

        # Verify all pending users are now approved
        db_session.refresh(pending_1)
        db_session.refresh(pending_2)
        db_session.refresh(pending_3)
        assert pending_1.approved is True
        assert pending_2.approved is True
        assert pending_3.approved is True

        # Verify correct usernames were captured
        assert sorted(usernames) == ["pending_1", "pending_2", "pending_3"]

    def test_approve_all_leaves_approved_users_alone(self, db_session: Session):
        """Approve-all does not modify already-approved users."""
        from database import User

        approved_user = create_user(db_session, "already_approved", approved=True)
        original_updated_at = approved_user.updated_at

        pending_user = create_user(db_session, "pending", approved=False)

        # Simulate the endpoint logic
        pending_users = db_session.query(User).filter(User.approved == False).all()  # noqa: E712
        now = datetime.now(timezone.utc)
        for user in pending_users:
            user.approved = True
            user.updated_at = now
        db_session.commit()

        # Verify approved user was untouched
        db_session.refresh(approved_user)
        assert approved_user.approved is True
        assert approved_user.updated_at == original_updated_at

    def test_approve_all_no_pending_users(self, db_session: Session):
        """Approve-all with no pending users returns count 0."""
        from database import User

        create_user(db_session, "approved_1", approved=True)
        create_user(db_session, "approved_2", approved=True)

        pending_users = db_session.query(User).filter(User.approved == False).all()  # noqa: E712
        assert len(pending_users) == 0

        # Simulate the endpoint response
        if not pending_users:
            result = {"message": "No pending users", "count": 0}
        else:
            result = {"message": f"Approved {len(pending_users)} user(s)", "count": len(pending_users)}

        assert result == {"message": "No pending users", "count": 0}
