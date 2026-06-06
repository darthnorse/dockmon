"""
Lockout guard on PUT /api/v2/oidc/config: a config save must not make OIDC
unusable while local login is effectively disabled (SSO-only), because that
would leave no working web login path. Break-glass (CLI / env override) still
applies, but the UI must not create the lockout.
"""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import auth.oidc_config_routes as oidc_routes
from config.settings import AppConfig
from database import OIDCConfig

ADMIN_USER = {"user_id": None, "username": "admin", "display_name": "Admin"}


@pytest.fixture
def cfg_env(db_session, monkeypatch):
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(oidc_routes.db, "get_session", fake_get_session)
    return db_session


def _add_config(session, *, enabled=True, disabled=False):
    session.add(OIDCConfig(
        id=1, enabled=enabled,
        provider_url="https://idp.example.com", client_id="dockmon",
        local_login_disabled=disabled,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ))
    session.commit()


@pytest.mark.asyncio
async def test_disabling_oidc_blocked_when_local_login_disabled(cfg_env):
    _add_config(cfg_env, enabled=True, disabled=True)
    body = oidc_routes.OIDCConfigUpdateRequest(enabled=False)

    with pytest.raises(HTTPException) as exc:
        await oidc_routes.update_oidc_config(body, None, ADMIN_USER)

    assert exc.value.status_code == 409
    # Production rolls back on exception; mirror that here, then verify unchanged.
    cfg_env.rollback()
    enabled = cfg_env.query(OIDCConfig.enabled).filter(OIDCConfig.id == 1).scalar()
    assert enabled is True


@pytest.mark.asyncio
async def test_clearing_provider_url_blocked_when_local_login_disabled(cfg_env):
    _add_config(cfg_env, enabled=True, disabled=True)
    body = oidc_routes.OIDCConfigUpdateRequest(provider_url="")

    with pytest.raises(HTTPException) as exc:
        await oidc_routes.update_oidc_config(body, None, ADMIN_USER)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_harmless_change_allowed_when_local_login_disabled(cfg_env):
    _add_config(cfg_env, enabled=True, disabled=True)
    body = oidc_routes.OIDCConfigUpdateRequest(sso_default=True)

    result = await oidc_routes.update_oidc_config(body, None, ADMIN_USER)
    assert result.sso_default is True


@pytest.mark.asyncio
async def test_disabling_oidc_allowed_when_local_login_enabled(cfg_env):
    _add_config(cfg_env, enabled=True, disabled=False)
    body = oidc_routes.OIDCConfigUpdateRequest(enabled=False)

    result = await oidc_routes.update_oidc_config(body, None, ADMIN_USER)
    assert result.enabled is False


@pytest.mark.asyncio
async def test_disabling_oidc_allowed_under_env_override(cfg_env, monkeypatch):
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", True, raising=False)
    _add_config(cfg_env, enabled=True, disabled=True)
    body = oidc_routes.OIDCConfigUpdateRequest(enabled=False)

    result = await oidc_routes.update_oidc_config(body, None, ADMIN_USER)
    assert result.enabled is False
