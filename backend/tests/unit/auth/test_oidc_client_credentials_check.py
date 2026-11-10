"""Test Connection's client_credentials probe: only invalid_client means the secret is wrong."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from auth.oidc_config_routes import _validate_client_credentials

TOKEN_ENDPOINT = "https://provider.example.com/token"


def _client_returning(status_code, body):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


async def _probe(status_code, body):
    with patch("auth.oidc_config_routes.httpx.AsyncClient", return_value=_client_returning(status_code, body)):
        return await _validate_client_credentials(TOKEN_ENDPOINT, "client-id", "secret")


@pytest.mark.asyncio
async def test_success_is_valid():
    validated, _ = await _probe(200, {"access_token": "x"})
    assert validated is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,body", [
    (400, {"error": "invalid_client"}),
    (401, {"error": "invalid_client", "error_description": "Client authentication failed"}),
    (401, {}),
])
async def test_client_authentication_failure_is_invalid(status_code, body):
    validated, message = await _probe(status_code, body)
    assert validated is False
    assert "Invalid client credentials" in message


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", [
    "invalid_grant",
    "unauthorized_client",
    "unsupported_grant_type",
    "invalid_scope",
    "access_denied",
])
async def test_other_provider_errors_are_inconclusive(error_code):
    # Authentik answers invalid_grant when client_credentials isn't enabled on the provider.
    validated, message = await _probe(400, {"error": error_code, "error_description": "nope"})
    assert validated is None
    assert error_code in message


@pytest.mark.asyncio
async def test_non_json_error_body_is_inconclusive():
    with patch("auth.oidc_config_routes.httpx.AsyncClient", return_value=_client_returning(500, None)) as factory:
        factory.return_value.post.return_value.json.side_effect = ValueError("not json")
        validated, _ = await _validate_client_credentials(TOKEN_ENDPOINT, "client-id", "secret")
    assert validated is None
