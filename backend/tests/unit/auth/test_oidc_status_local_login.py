"""
Tests for the local_login_disabled field on the public OIDC status endpoint
(GET /api/v2/oidc/status). The login page reads this to hide the local form.

The status endpoint returns the *effective* value (DB flag AND NOT env override).
"""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

import auth.oidc_config_routes as oidc_routes
from config.settings import AppConfig
from database import OIDCConfig


@pytest.fixture
def status_env(db_session, monkeypatch):
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(oidc_routes.db, "get_session", fake_get_session)
    return db_session


def _add_config(db_session, **kwargs):
    config = OIDCConfig(
        id=1,
        enabled=kwargs.pop("enabled", True),
        provider_url=kwargs.pop("provider_url", "https://idp.example.com"),
        client_id=kwargs.pop("client_id", "dockmon"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        **kwargs,
    )
    db_session.add(config)
    db_session.commit()


@pytest.mark.asyncio
async def test_status_reports_local_login_disabled(status_env):
    _add_config(status_env, local_login_disabled=True)
    result = await oidc_routes.get_oidc_status()
    assert result.local_login_disabled is True


@pytest.mark.asyncio
async def test_status_local_login_enabled_by_default(status_env):
    _add_config(status_env, local_login_disabled=False)
    result = await oidc_routes.get_oidc_status()
    assert result.local_login_disabled is False


@pytest.mark.asyncio
async def test_status_env_override_reports_enabled(status_env, monkeypatch):
    """Even with the DB flag set, the override makes the effective value False."""
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", True, raising=False)
    _add_config(status_env, local_login_disabled=True)
    result = await oidc_routes.get_oidc_status()
    assert result.local_login_disabled is False


@pytest.mark.asyncio
async def test_status_no_config_defaults_to_enabled(status_env):
    result = await oidc_routes.get_oidc_status()
    assert result.local_login_disabled is False
