"""
Tests for credential-lifecycle security:
- API keys created by a user are revoked when that user is deleted.
- The first-run admin account does not use a static, well-known password.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session


def _make_user(db_session, username=None):
    from database import User
    user = User(
        username=username or f"u_{uuid.uuid4().hex[:8]}",
        password_hash="hash",
        auth_provider="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    return user


def _make_group(db_session):
    from database import CustomGroup
    g = CustomGroup(name=f"G_{uuid.uuid4().hex[:8]}", description="test")
    db_session.add(g)
    db_session.flush()
    return g


def _make_api_key(db_session, group, creator):
    from database import ApiKey
    key = ApiKey(
        key_hash=f"h_{uuid.uuid4().hex}",
        key_prefix="dockmon_test",
        name=f"k_{uuid.uuid4().hex[:8]}",
        group_id=group.id,
        created_by_user_id=creator.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(key)
    db_session.flush()
    return key


class TestRevokeApiKeysForUser:
    def test_revokes_active_keys_created_by_user(self, db_session: Session):
        from auth.utils import revoke_api_keys_for_user
        creator = _make_user(db_session)
        group = _make_group(db_session)
        k1 = _make_api_key(db_session, group, creator)
        k2 = _make_api_key(db_session, group, creator)

        count = revoke_api_keys_for_user(db_session, creator.id)

        assert count == 2
        db_session.refresh(k1)
        db_session.refresh(k2)
        assert k1.revoked_at is not None
        assert k2.revoked_at is not None

    def test_does_not_touch_other_users_keys(self, db_session: Session):
        from auth.utils import revoke_api_keys_for_user
        creator = _make_user(db_session)
        other = _make_user(db_session)
        group = _make_group(db_session)
        other_key = _make_api_key(db_session, group, other)

        count = revoke_api_keys_for_user(db_session, creator.id)

        assert count == 0
        db_session.refresh(other_key)
        assert other_key.revoked_at is None

    def test_already_revoked_keys_are_not_recounted(self, db_session: Session):
        from auth.utils import revoke_api_keys_for_user
        creator = _make_user(db_session)
        group = _make_group(db_session)
        key = _make_api_key(db_session, group, creator)
        key.revoked_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db_session.flush()

        count = revoke_api_keys_for_user(db_session, creator.id)

        assert count == 0


class TestFirstRunAdminPassword:
    def test_generated_password_is_not_the_legacy_default(self, db):
        """With no env override, the seeded admin must not use 'dockmon123'."""
        from database import User
        from auth.password import ph
        from argon2.exceptions import VerifyMismatchError

        db.get_or_create_default_user()
        with db.get_session() as session:
            admin = session.query(User).filter_by(username="admin").first()
            assert admin is not None
            assert admin.must_change_password is True
            # argon2 raises on mismatch; the legacy default must NOT verify.
            with pytest.raises(VerifyMismatchError):
                ph.verify(admin.password_hash, "dockmon123")

    def test_env_override_sets_admin_password(self, db, monkeypatch):
        from database import User
        from auth.password import ph

        monkeypatch.setenv("DOCKMON_INITIAL_ADMIN_PASSWORD", "Sup3r-Secret-Init!")
        db.get_or_create_default_user()
        with db.get_session() as session:
            admin = session.query(User).filter_by(username="admin").first()
            assert admin is not None
            assert ph.verify(admin.password_hash, "Sup3r-Secret-Init!")
