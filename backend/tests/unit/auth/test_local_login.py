"""
Unit tests for the SSO-only (disable local login) effective-state helper.

The effective disabled state is the DB flag AND NOT the env override:
    DOCKMON_FORCE_LOCAL_LOGIN=true is a break-glass that forces local login on
    regardless of what the database says.
"""

import pytest
from datetime import datetime, timezone

from auth.local_login import local_login_effective_disabled, oidc_usable, has_approved_oidc_admin
from config.settings import AppConfig
from database import CustomGroup, GroupPermission, OIDCConfig, User, UserGroupMembership


def test_disabled_when_db_flag_set_and_no_override(monkeypatch):
    """DB flag on + no env override => local login is effectively disabled."""
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)
    assert local_login_effective_disabled(True) is True


def test_env_override_forces_local_login_on(monkeypatch):
    """The env override wins over the DB flag (break-glass)."""
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", True, raising=False)
    assert local_login_effective_disabled(True) is False


def test_not_disabled_when_db_flag_unset(monkeypatch):
    """DB flag off => local login stays enabled."""
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)
    assert local_login_effective_disabled(False) is False


def test_oidc_usable_true_when_enabled_and_configured():
    config = OIDCConfig(id=1, enabled=True, provider_url="https://idp.example.com", client_id="dockmon")
    assert oidc_usable(config) is True


def test_oidc_usable_false_when_disabled_or_unconfigured():
    assert oidc_usable(None) is False
    assert oidc_usable(OIDCConfig(id=1, enabled=False, provider_url="https://i", client_id="d")) is False
    assert oidc_usable(OIDCConfig(id=1, enabled=True, provider_url=None, client_id="d")) is False
    assert oidc_usable(OIDCConfig(id=1, enabled=True, provider_url="https://i", client_id=None)) is False


def test_has_approved_oidc_admin_true(db_session):
    group = CustomGroup(name="Admins", is_system=False)
    db_session.add(group)
    db_session.flush()
    db_session.add(GroupPermission(group_id=group.id, capability="users.manage", allowed=True))
    user = User(username="oidc-admin", password_hash="!OIDC_NO_PASSWORD", role="admin",
                auth_provider="oidc", oidc_subject="sub-1", approved=True,
                created_at=datetime.now(timezone.utc))
    db_session.add(user)
    db_session.flush()
    db_session.add(UserGroupMembership(user_id=user.id, group_id=group.id))
    db_session.commit()
    assert has_approved_oidc_admin(db_session) is True


def test_has_approved_oidc_admin_false_for_local_admin(db_session):
    group = CustomGroup(name="LocalAdmins", is_system=False)
    db_session.add(group)
    db_session.flush()
    db_session.add(GroupPermission(group_id=group.id, capability="users.manage", allowed=True))
    user = User(username="local-admin", password_hash="x", role="admin",
                auth_provider="local", approved=True, created_at=datetime.now(timezone.utc))
    db_session.add(user)
    db_session.flush()
    db_session.add(UserGroupMembership(user_id=user.id, group_id=group.id))
    db_session.commit()
    assert has_approved_oidc_admin(db_session) is False
