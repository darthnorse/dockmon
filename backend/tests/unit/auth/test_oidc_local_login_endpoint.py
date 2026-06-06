"""
Tests for PUT /api/v2/oidc/local-login (set SSO-only enforcement from the UI).

The endpoint enforces the SAME lockout guard as the manage_auth CLI, server-side:
disabling local login is refused unless OIDC is usable AND an approved OIDC admin
exists. There is no --force equivalent in the UI. Re-enabling is always allowed.
The DOCKMON_FORCE_LOCAL_LOGIN env override blocks writes (it controls the
effective state).
"""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import auth.oidc_config_routes as oidc_routes
from config.settings import AppConfig
from database import (
    AuditLog, CustomGroup, GroupPermission, OIDCConfig, User, UserGroupMembership,
)

ADMIN_USER = {"user_id": None, "username": "admin", "display_name": "Admin"}


@pytest.fixture
def endpoint_env(db_session, monkeypatch):
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(oidc_routes.db, "get_session", fake_get_session)
    return db_session


def _add_config(session, *, enabled=True, configured=True, disabled=False):
    session.add(OIDCConfig(
        id=1, enabled=enabled,
        provider_url="https://idp.example.com" if configured else None,
        client_id="dockmon" if configured else None,
        local_login_disabled=disabled,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ))
    session.commit()


def _add_oidc_admin(session):
    group = CustomGroup(name="Admins", is_system=False)
    session.add(group)
    session.flush()
    session.add(GroupPermission(group_id=group.id, capability="users.manage", allowed=True))
    user = User(username="oidc-admin", password_hash="!OIDC_NO_PASSWORD", role="admin",
                auth_provider="oidc", oidc_subject="sub-1", approved=True,
                created_at=datetime.now(timezone.utc))
    session.add(user)
    session.flush()
    session.add(UserGroupMembership(user_id=user.id, group_id=group.id))
    session.commit()


def _flag(session) -> bool:
    return bool(session.query(OIDCConfig.local_login_disabled).filter(OIDCConfig.id == 1).scalar())


@pytest.mark.asyncio
async def test_disable_succeeds_with_oidc_admin(endpoint_env):
    _add_config(endpoint_env)
    _add_oidc_admin(endpoint_env)
    body = oidc_routes.LocalLoginUpdateRequest(disabled=True)

    result = await oidc_routes.set_local_login(body, None, ADMIN_USER)

    assert result.local_login_disabled is True
    assert _flag(endpoint_env) is True
    rows = endpoint_env.query(AuditLog).filter(AuditLog.entity_type == "oidc_config").all()
    assert any("local_login_disabled" in (r.details or "") for r in rows)


@pytest.mark.asyncio
async def test_disable_refused_without_oidc_admin(endpoint_env):
    _add_config(endpoint_env)
    body = oidc_routes.LocalLoginUpdateRequest(disabled=True)

    with pytest.raises(HTTPException) as exc:
        await oidc_routes.set_local_login(body, None, ADMIN_USER)

    assert exc.value.status_code == 409
    assert "admin" in exc.value.detail.lower()
    assert _flag(endpoint_env) is False


@pytest.mark.asyncio
async def test_disable_refused_when_oidc_not_usable(endpoint_env):
    _add_config(endpoint_env, enabled=False)
    _add_oidc_admin(endpoint_env)
    body = oidc_routes.LocalLoginUpdateRequest(disabled=True)

    with pytest.raises(HTTPException) as exc:
        await oidc_routes.set_local_login(body, None, ADMIN_USER)

    assert exc.value.status_code == 409
    assert _flag(endpoint_env) is False


@pytest.mark.asyncio
async def test_disable_refused_when_env_override_active(endpoint_env, monkeypatch):
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", True, raising=False)
    _add_config(endpoint_env)
    _add_oidc_admin(endpoint_env)
    body = oidc_routes.LocalLoginUpdateRequest(disabled=True)

    with pytest.raises(HTTPException) as exc:
        await oidc_routes.set_local_login(body, None, ADMIN_USER)

    assert exc.value.status_code == 409
    assert "DOCKMON_FORCE_LOCAL_LOGIN" in exc.value.detail
    assert _flag(endpoint_env) is False


@pytest.mark.asyncio
async def test_enable_always_allowed_even_without_oidc_admin(endpoint_env):
    _add_config(endpoint_env, enabled=False, disabled=True)
    body = oidc_routes.LocalLoginUpdateRequest(disabled=False)

    result = await oidc_routes.set_local_login(body, None, ADMIN_USER)

    assert result.local_login_disabled is False
    assert _flag(endpoint_env) is False
