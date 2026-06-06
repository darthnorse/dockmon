"""
Tests for the manage_auth CLI core logic (status / disable / enable).

The CLI is the control surface for SSO-only enforcement. Its safety guard must
refuse to disable local login unless OIDC is usable AND an approved OIDC admin
exists, so an operator cannot lock themselves out. --force overrides the guard.
"""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

import manage_auth
from config.settings import AppConfig
from database import (
    AuditLog,
    CustomGroup,
    GroupPermission,
    OIDCConfig,
    User,
    UserGroupMembership,
)


class FakeDB:
    """Minimal DatabaseManager stand-in that yields the test session."""

    def __init__(self, session):
        self._session = session

    @contextmanager
    def get_session(self):
        yield self._session


@pytest.fixture
def db(db_session, monkeypatch):
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)
    return FakeDB(db_session)


def _add_oidc_config(session, *, enabled=True, configured=True, disabled=False):
    config = OIDCConfig(
        id=1,
        enabled=enabled,
        provider_url="https://idp.example.com" if configured else None,
        client_id="dockmon" if configured else None,
        local_login_disabled=disabled,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(config)
    session.commit()
    return config


def _add_approved_oidc_admin(session, capability="users.manage"):
    group = CustomGroup(name="Admins", description="admins", is_system=False)
    session.add(group)
    session.flush()
    session.add(GroupPermission(group_id=group.id, capability=capability, allowed=True))
    user = User(
        username="oidc-admin",
        password_hash="!OIDC_NO_PASSWORD",
        role="admin",
        auth_provider="oidc",
        oidc_subject="sub-1",
        approved=True,
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.flush()
    session.add(UserGroupMembership(user_id=user.id, group_id=group.id))
    session.commit()
    return user


def _flag(session) -> bool:
    return bool(
        session.query(OIDCConfig.local_login_disabled)
        .filter(OIDCConfig.id == 1)
        .scalar()
    )


def _audit_rows(session):
    return (
        session.query(AuditLog)
        .filter(AuditLog.entity_type == "oidc_config")
        .all()
    )


# ---------------------------------------------------------------- disable guard

def test_disable_refuses_when_oidc_not_enabled(db, db_session):
    _add_oidc_config(db_session, enabled=False)
    _add_approved_oidc_admin(db_session)

    with pytest.raises(manage_auth.GuardError):
        manage_auth.disable_local_login(db)

    assert _flag(db_session) is False


def test_disable_refuses_when_oidc_unconfigured(db, db_session):
    _add_oidc_config(db_session, enabled=True, configured=False)
    _add_approved_oidc_admin(db_session)

    with pytest.raises(manage_auth.GuardError):
        manage_auth.disable_local_login(db)

    assert _flag(db_session) is False


def test_disable_refuses_without_approved_oidc_admin(db, db_session):
    _add_oidc_config(db_session, enabled=True)
    # A local admin is not enough; the fallback path must be OIDC.
    session = db_session
    group = CustomGroup(name="LocalAdmins", is_system=False)
    session.add(group)
    session.flush()
    session.add(GroupPermission(group_id=group.id, capability="users.manage", allowed=True))
    local_admin = User(
        username="local-admin",
        password_hash="x",
        role="admin",
        auth_provider="local",
        approved=True,
        created_at=datetime.now(timezone.utc),
    )
    session.add(local_admin)
    session.flush()
    session.add(UserGroupMembership(user_id=local_admin.id, group_id=group.id))
    session.commit()

    with pytest.raises(manage_auth.GuardError):
        manage_auth.disable_local_login(db)

    assert _flag(db_session) is False


def test_disable_refuses_when_oidc_admin_not_approved(db, db_session):
    _add_oidc_config(db_session, enabled=True)
    admin = _add_approved_oidc_admin(db_session)
    admin.approved = False
    db_session.commit()

    with pytest.raises(manage_auth.GuardError):
        manage_auth.disable_local_login(db)

    assert _flag(db_session) is False


# ---------------------------------------------------------------- disable happy

def test_disable_succeeds_with_approved_oidc_admin(db, db_session):
    _add_oidc_config(db_session, enabled=True)
    _add_approved_oidc_admin(db_session)

    manage_auth.disable_local_login(db)

    assert _flag(db_session) is True
    assert any("local_login_disabled" in (r.details or "") for r in _audit_rows(db_session))


def test_disable_force_bypasses_guard(db, db_session):
    _add_oidc_config(db_session, enabled=False)  # guard would refuse

    manage_auth.disable_local_login(db, force=True)

    assert _flag(db_session) is True


# ---------------------------------------------------------------- enable

def test_enable_clears_flag(db, db_session):
    _add_oidc_config(db_session, enabled=True, disabled=True)

    manage_auth.enable_local_login(db)

    assert _flag(db_session) is False
    assert any("local_login_disabled" in (r.details or "") for r in _audit_rows(db_session))


def test_enable_when_no_config_is_safe(db, db_session):
    # No OIDCConfig row at all -> enabling local login is a no-op success.
    manage_auth.enable_local_login(db)
    assert _flag(db_session) is False


# ---------------------------------------------------------------- status

def test_status_reports_effective_state(db, db_session):
    _add_oidc_config(db_session, enabled=True, disabled=True)
    _add_approved_oidc_admin(db_session)

    status = manage_auth.get_status(db)

    assert status["db_flag"] is True
    assert status["env_override"] is False
    assert status["effective_disabled"] is True
    assert status["oidc_enabled"] is True
    assert status["has_oidc_admin"] is True


def test_status_env_override_makes_effective_enabled(db, db_session, monkeypatch):
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", True, raising=False)
    _add_oidc_config(db_session, enabled=True, disabled=True)

    status = manage_auth.get_status(db)

    assert status["db_flag"] is True
    assert status["env_override"] is True
    assert status["effective_disabled"] is False


# ----------------------------------------------------- --force lockout warning

def test_force_warns_when_oidc_not_usable():
    status = {"oidc_enabled": False, "has_oidc_admin": False}
    assert manage_auth._force_lockout_warning(status) is not None


def test_force_warns_when_no_oidc_admin():
    status = {"oidc_enabled": True, "has_oidc_admin": False}
    assert manage_auth._force_lockout_warning(status) is not None


def test_force_no_warning_when_oidc_usable_with_admin():
    status = {"oidc_enabled": True, "has_oidc_admin": True}
    assert manage_auth._force_lockout_warning(status) is None


# ----------------------------------------------------- container exec path

def test_enable_command_uses_backend_path():
    """The container WORKDIR is /app but the script is at /app/backend, so the
    documented break-glass command must reference backend/manage_auth.py."""
    assert "backend/manage_auth.py" in manage_auth.ENABLE_COMMAND
