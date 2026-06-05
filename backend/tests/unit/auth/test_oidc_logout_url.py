"""
Tests for the OIDC provider logout URL built by the /api/v2/auth/logout endpoint.

Keycloak 18+ (and 26) enforce the OIDC RP-Initiated Logout rule that a
post_logout_redirect_uri must be accompanied by either an id_token_hint or a
client_id. DockMon does not retain the id_token, so it must send client_id;
otherwise Keycloak rejects the logout with "Missing parameters: id_token_hint".

Regression coverage for issue #225.
"""

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import Response
from starlette.requests import Request

import auth.v2_routes as v2
from config.settings import AppConfig
from database import OIDCConfig, User


END_SESSION_ENDPOINT = (
    "https://keycloak.example.com/realms/myrealm/protocol/openid-connect/logout"
)


def _make_logout_request(scheme: str = "https", host: str = "dockmon.example.com") -> Request:
    """Build a minimal ASGI Request without standing up the whole app."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": scheme,
        "path": "/api/v2/auth/logout",
        "raw_path": b"/api/v2/auth/logout",
        "query_string": b"",
        "headers": [(b"host", host.encode())],
        "client": ("203.0.113.5", 12345),
        "server": (host, 443 if scheme == "https" else 80),
    }
    return Request(scope)


class _DiscoveryResponse:
    status_code = 200

    def json(self):
        return {"end_session_endpoint": END_SESSION_ENDPOINT}


class _MockAsyncClient:
    """Stand-in for httpx.AsyncClient that returns the discovery document."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        return _DiscoveryResponse()


@pytest.fixture
def oidc_logout_env(db_session, monkeypatch):
    """Arrange an OIDC user + enabled OIDC config and wire up the endpoint deps."""
    monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", False, raising=False)

    user = User(
        username="oidcuser",
        password_hash="!OIDC_NO_PASSWORD",
        role="user",
        auth_provider="oidc",
        oidc_subject="sub-123",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    config = OIDCConfig(
        id=1,
        enabled=True,
        provider_url="https://keycloak.example.com/realms/myrealm",
        client_id="dockmon-client",
    )
    db_session.add(config)
    db_session.commit()

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(v2.db, "get_session", fake_get_session)
    monkeypatch.setattr(
        v2.cookie_session_manager,
        "validate_session",
        lambda token, ip: {
            "user_id": user.id,
            "username": "oidcuser",
            "display_name": "OIDC User",
        },
    )
    monkeypatch.setattr(v2.cookie_session_manager, "delete_session", lambda token: True)
    monkeypatch.setattr(v2, "log_logout", lambda *a, **k: None)
    monkeypatch.setattr(v2.httpx, "AsyncClient", _MockAsyncClient)

    return user


@pytest.mark.asyncio
async def test_oidc_logout_url_includes_client_id(oidc_logout_env):
    """Keycloak requires client_id alongside post_logout_redirect_uri."""
    result = await v2.logout_v2(
        response=Response(),
        request=_make_logout_request(),
        session_id="signed-token",
    )

    assert result.oidc_logout_url is not None
    assert "client_id=dockmon-client" in result.oidc_logout_url
    # The redirect target must still be present (it is what triggers the requirement).
    assert "post_logout_redirect_uri=" in result.oidc_logout_url
    # The redirect URI must be percent-encoded so it survives as a single query value.
    assert "https%3A%2F%2Fdockmon.example.com%2Flogin" in result.oidc_logout_url


@pytest.mark.asyncio
async def test_oidc_logout_url_omits_client_id_and_warns_when_unconfigured(
    oidc_logout_env, db_session, monkeypatch
):
    """A misconfigured OIDC provider (no client_id) must not emit an empty
    client_id= and should log a diagnosable warning."""
    config = db_session.query(OIDCConfig).filter_by(id=1).first()
    config.client_id = None
    db_session.commit()

    # Spy on the module logger directly so the assertion does not depend on
    # global logging propagation state left behind by other tests.
    warnings: list[str] = []
    monkeypatch.setattr(v2.logger, "warning", lambda msg, *a, **k: warnings.append(str(msg)))

    result = await v2.logout_v2(
        response=Response(),
        request=_make_logout_request(),
        session_id="signed-token",
    )

    assert result.oidc_logout_url is not None
    assert "client_id=" not in result.oidc_logout_url
    assert any("client_id not configured" in w for w in warnings)
