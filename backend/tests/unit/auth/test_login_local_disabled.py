"""
Enforcement tests for SSO-only (disable local login) at POST /api/v2/auth/login.

When local login is effectively disabled, login_v2 must reject EVERY local
password login with the same generic 401 used elsewhere (no account-existence
leak) and audit the failure with reason 'local_login_disabled'. The
DOCKMON_FORCE_LOCAL_LOGIN env override is a break-glass that lets local login
through again.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

import auth.v2_routes as v2
from auth.password import ph
from config.settings import AppConfig
from database import AuditLog, OIDCConfig, User


KNOWN_PASSWORD = "correct-horse-battery"


def _make_login_request() -> Request:
    """Build a minimal ASGI Request for the login handler."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/v2/auth/login",
        "raw_path": b"/api/v2/auth/login",
        "query_string": b"",
        "headers": [(b"host", b"dockmon.example.com")],
        "client": ("203.0.113.5", 12345),
        "server": ("dockmon.example.com", 443),
    }
    return Request(scope)


@pytest.fixture
def local_login_env(db_session, monkeypatch):
    """Local user + OIDCConfig with local login disabled, endpoint deps wired."""
    monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", False, raising=False)
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)

    user = User(
        username="alice",
        password_hash=ph.hash(KNOWN_PASSWORD),
        role="admin",
        auth_provider="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)

    config = OIDCConfig(
        id=1,
        enabled=True,
        provider_url="https://idp.example.com",
        client_id="dockmon",
        local_login_disabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(config)
    db_session.commit()

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(v2.db, "get_session", fake_get_session)
    return db_session


def _last_failure_reason(db_session) -> str | None:
    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "login_failed")
        .order_by(AuditLog.id.desc())
        .first()
    )
    return entry.details if entry else None


@pytest.mark.asyncio
async def test_disabled_rejects_valid_local_login(local_login_env):
    """A correct username/password is still rejected when local login is off."""
    with pytest.raises(HTTPException) as exc_info:
        await v2.login_v2(
            credentials=v2.LoginRequest(username="alice", password=KNOWN_PASSWORD),
            response=Response(),
            request=_make_login_request(),
            rate_limit_check=True,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid username or password"
    assert "local_login_disabled" in (_last_failure_reason(local_login_env) or "")


@pytest.mark.asyncio
async def test_disabled_rejects_before_user_lookup(local_login_env):
    """An unknown username gets the same disabled rejection (no existence leak)."""
    with pytest.raises(HTTPException) as exc_info:
        await v2.login_v2(
            credentials=v2.LoginRequest(username="ghost", password="whatever"),
            response=Response(),
            request=_make_login_request(),
            rate_limit_check=True,
        )

    assert exc_info.value.status_code == 401
    reason = _last_failure_reason(local_login_env) or ""
    assert "local_login_disabled" in reason
    assert "user_not_found" not in reason


@pytest.mark.asyncio
async def test_env_override_lets_local_login_proceed(local_login_env, monkeypatch):
    """DOCKMON_FORCE_LOCAL_LOGIN bypasses the gate; a valid login succeeds."""
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", True, raising=False)
    monkeypatch.setattr(
        v2.cookie_session_manager, "create_session",
        lambda **kwargs: "signed-token",
    )

    result = await v2.login_v2(
        credentials=v2.LoginRequest(username="alice", password=KNOWN_PASSWORD),
        response=Response(),
        request=_make_login_request(),
        rate_limit_check=True,
    )

    assert result.message == "Login successful"
    assert result.user["username"] == "alice"


@pytest.mark.asyncio
async def test_override_with_wrong_password_falls_through_to_credential_check(
    local_login_env, monkeypatch
):
    """With the override on, a bad password fails as 'invalid_password', proving
    the disable gate was bypassed rather than short-circuiting the request."""
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", True, raising=False)

    with pytest.raises(HTTPException) as exc_info:
        await v2.login_v2(
            credentials=v2.LoginRequest(username="alice", password="wrong-password"),
            response=Response(),
            request=_make_login_request(),
            rate_limit_check=True,
        )

    assert exc_info.value.status_code == 401
    assert "invalid_password" in (_last_failure_reason(local_login_env) or "")


# ----------------- _reject_login parity across the non-disabled failure paths
# These lock in that the shared rejection helper keeps the generic 401 + the
# correct audit reason for each branch (regression guard for the refactor).

@pytest.fixture
def login_enabled_env(db_session, monkeypatch):
    """Local login enabled (flag off); endpoint deps wired."""
    monkeypatch.setattr(AppConfig, "REVERSE_PROXY_MODE", False, raising=False)
    monkeypatch.setattr(AppConfig, "FORCE_LOCAL_LOGIN", False, raising=False)

    config = OIDCConfig(
        id=1,
        enabled=False,
        local_login_disabled=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(config)
    db_session.commit()

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(v2.db, "get_session", fake_get_session)
    return db_session


@pytest.mark.asyncio
async def test_unknown_user_rejected_generically(login_enabled_env):
    with pytest.raises(HTTPException) as exc_info:
        await v2.login_v2(
            credentials=v2.LoginRequest(username="ghost", password="x"),
            response=Response(),
            request=_make_login_request(),
            rate_limit_check=True,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid username or password"
    assert "user_not_found" in (_last_failure_reason(login_enabled_env) or "")


@pytest.mark.asyncio
async def test_oidc_user_rejected_from_local_login(login_enabled_env):
    login_enabled_env.add(User(
        username="ous", password_hash="!OIDC_NO_PASSWORD", role="user",
        auth_provider="oidc", oidc_subject="s", created_at=datetime.now(timezone.utc),
    ))
    login_enabled_env.commit()

    with pytest.raises(HTTPException) as exc_info:
        await v2.login_v2(
            credentials=v2.LoginRequest(username="ous", password="x"),
            response=Response(),
            request=_make_login_request(),
            rate_limit_check=True,
        )
    assert exc_info.value.status_code == 401
    assert "oidc_user_local_attempt" in (_last_failure_reason(login_enabled_env) or "")


@pytest.mark.asyncio
async def test_locked_account_rejected(login_enabled_env):
    login_enabled_env.add(User(
        username="locked", password_hash=ph.hash(KNOWN_PASSWORD), role="user",
        auth_provider="local",
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=5),
        created_at=datetime.now(timezone.utc),
    ))
    login_enabled_env.commit()

    with pytest.raises(HTTPException) as exc_info:
        await v2.login_v2(
            credentials=v2.LoginRequest(username="locked", password=KNOWN_PASSWORD),
            response=Response(),
            request=_make_login_request(),
            rate_limit_check=True,
        )
    assert exc_info.value.status_code == 401
    assert "account_locked" in (_last_failure_reason(login_enabled_env) or "")
