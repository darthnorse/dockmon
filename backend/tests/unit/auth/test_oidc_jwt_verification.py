"""
Tests for OIDC ID token JWT verification.

Covers:
- _verify_id_token() - JWT signature verification and claim validation
- _fetch_jwks() - JWKS fetching with caching
- Nonce validation within JWT verification
- Issuer mismatch rejection (strict with trailing-slash normalization)
- Audience validation (string and list formats)
- Key matching by kid header
- Error handling for invalid/malformed tokens
"""

import json
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


# ==================== Test Fixtures ====================

def _generate_rsa_keypair():
    """Generate an RSA key pair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key


def _private_key_to_jwk(private_key, kid="test-key-1"):
    """Convert an RSA private key to a JWK dict (public key only)."""
    public_key = private_key.public_key()
    public_numbers = public_key.public_numbers()

    # Convert to base64url-encoded values
    import base64

    def _int_to_base64url(n, length=None):
        n_bytes = n.to_bytes((n.bit_length() + 7) // 8, byteorder='big')
        return base64.urlsafe_b64encode(n_bytes).rstrip(b'=').decode('ascii')

    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _int_to_base64url(public_numbers.n),
        "e": _int_to_base64url(public_numbers.e),
    }


def _create_signed_id_token(private_key, claims, kid="test-key-1"):
    """Create a signed JWT ID token for testing."""
    return pyjwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


@pytest.fixture
def rsa_keypair():
    """Generate a fresh RSA key pair for each test."""
    return _generate_rsa_keypair()


@pytest.fixture
def jwks_data(rsa_keypair):
    """Create JWKS data from the test key pair."""
    jwk = _private_key_to_jwk(rsa_keypair, kid="test-key-1")
    return {"keys": [jwk]}


@pytest.fixture
def valid_claims():
    """Standard valid ID token claims."""
    now = datetime.now(timezone.utc)
    return {
        "iss": "https://provider.example.com",
        "sub": "user-12345",
        "aud": "my-client-id",
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "iat": int(now.timestamp()),
        "nonce": "expected-nonce-value",
        "email": "user@example.com",
    }


# ==================== _verify_id_token Tests ====================

class TestVerifyIdToken:
    """Test _verify_id_token() JWT verification."""

    def test_valid_token_verified_successfully(self, rsa_keypair, jwks_data, valid_claims):
        """Valid signed token with correct claims passes verification."""
        from auth.oidc_auth_routes import _verify_id_token

        id_token = _create_signed_id_token(rsa_keypair, valid_claims)

        result = _verify_id_token(
            id_token=id_token,
            jwks_data=jwks_data,
            provider_url="https://provider.example.com",
            client_id="my-client-id",
            expected_nonce="expected-nonce-value",
        )

        assert result["sub"] == "user-12345"
        assert result["email"] == "user@example.com"
        assert result["nonce"] == "expected-nonce-value"

    def test_expired_token_rejected(self, rsa_keypair, jwks_data, valid_claims):
        """Token with expired 'exp' claim is rejected."""
        from auth.oidc_auth_routes import _verify_id_token

        # Set expiration to 1 hour ago
        valid_claims["exp"] = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        id_token = _create_signed_id_token(rsa_keypair, valid_claims)

        with pytest.raises(pyjwt.InvalidTokenError):
            _verify_id_token(
                id_token=id_token,
                jwks_data=jwks_data,
                provider_url="https://provider.example.com",
                client_id="my-client-id",
                expected_nonce="expected-nonce-value",
            )

    def test_wrong_audience_rejected(self, rsa_keypair, jwks_data, valid_claims):
        """Token with wrong audience is rejected."""
        from auth.oidc_auth_routes import _verify_id_token

        id_token = _create_signed_id_token(rsa_keypair, valid_claims)

        with pytest.raises(pyjwt.InvalidTokenError):
            _verify_id_token(
                id_token=id_token,
                jwks_data=jwks_data,
                provider_url="https://provider.example.com",
                client_id="wrong-client-id",
                expected_nonce="expected-nonce-value",
            )

    def test_nonce_mismatch_rejected(self, rsa_keypair, jwks_data, valid_claims):
        """Token with wrong nonce is rejected."""
        from auth.oidc_auth_routes import _verify_id_token

        id_token = _create_signed_id_token(rsa_keypair, valid_claims)

        with pytest.raises(pyjwt.InvalidTokenError, match="Nonce mismatch"):
            _verify_id_token(
                id_token=id_token,
                jwks_data=jwks_data,
                provider_url="https://provider.example.com",
                client_id="my-client-id",
                expected_nonce="wrong-nonce-value",
            )

    def test_issuer_trailing_slash_tolerance(self, rsa_keypair, jwks_data, valid_claims):
        """Issuer comparison is lenient about trailing slashes."""
        from auth.oidc_auth_routes import _verify_id_token

        # Token has issuer without trailing slash
        valid_claims["iss"] = "https://provider.example.com"
        id_token = _create_signed_id_token(rsa_keypair, valid_claims)

        # Provider URL has trailing slash - should still work
        result = _verify_id_token(
            id_token=id_token,
            jwks_data=jwks_data,
            provider_url="https://provider.example.com/",
            client_id="my-client-id",
            expected_nonce="expected-nonce-value",
        )

        assert result["sub"] == "user-12345"

    def test_issuer_mismatch_rejected(self, rsa_keypair, jwks_data, valid_claims):
        """Non-conformant issuer is rejected (strict validation)."""
        from auth.oidc_auth_routes import _verify_id_token

        # Token has different issuer format
        valid_claims["iss"] = "https://provider.example.com/realms/main"
        id_token = _create_signed_id_token(rsa_keypair, valid_claims)

        # Provider URL is different from issuer - should be rejected
        with pytest.raises(pyjwt.InvalidTokenError, match="Issuer mismatch"):
            _verify_id_token(
                id_token=id_token,
                jwks_data=jwks_data,
                provider_url="https://provider.example.com",
                client_id="my-client-id",
                expected_nonce="expected-nonce-value",
            )

    def test_audience_as_list(self, rsa_keypair, jwks_data, valid_claims):
        """Audience claim as a list is handled correctly."""
        from auth.oidc_auth_routes import _verify_id_token

        # Some providers return aud as a list
        valid_claims["aud"] = ["my-client-id", "other-client"]
        id_token = _create_signed_id_token(rsa_keypair, valid_claims)

        result = _verify_id_token(
            id_token=id_token,
            jwks_data=jwks_data,
            provider_url="https://provider.example.com",
            client_id="my-client-id",
            expected_nonce="expected-nonce-value",
        )

        assert result["sub"] == "user-12345"

    def test_wrong_signing_key_rejected(self, jwks_data, valid_claims):
        """Token signed with a different key is rejected."""
        from auth.oidc_auth_routes import _verify_id_token

        # Sign with a DIFFERENT key than what's in the JWKS
        different_key = _generate_rsa_keypair()
        id_token = _create_signed_id_token(different_key, valid_claims)

        with pytest.raises(pyjwt.InvalidTokenError):
            _verify_id_token(
                id_token=id_token,
                jwks_data=jwks_data,
                provider_url="https://provider.example.com",
                client_id="my-client-id",
                expected_nonce="expected-nonce-value",
            )

    def test_no_matching_kid_rejected(self, rsa_keypair, jwks_data, valid_claims):
        """Token with unrecognized kid is rejected."""
        from auth.oidc_auth_routes import _verify_id_token

        # Sign with kid that doesn't exist in JWKS
        id_token = _create_signed_id_token(rsa_keypair, valid_claims, kid="unknown-key-id")

        with pytest.raises(pyjwt.InvalidTokenError, match="No matching key"):
            _verify_id_token(
                id_token=id_token,
                jwks_data=jwks_data,
                provider_url="https://provider.example.com",
                client_id="my-client-id",
                expected_nonce="expected-nonce-value",
            )

    def test_malformed_token_rejected(self, jwks_data):
        """Completely malformed token is rejected."""
        from auth.oidc_auth_routes import _verify_id_token

        with pytest.raises(pyjwt.InvalidTokenError):
            _verify_id_token(
                id_token="not-a-jwt",
                jwks_data=jwks_data,
                provider_url="https://provider.example.com",
                client_id="my-client-id",
                expected_nonce="some-nonce",
            )

    def test_empty_jwks_rejected(self, rsa_keypair, valid_claims):
        """Token verification fails when JWKS has no keys."""
        from auth.oidc_auth_routes import _verify_id_token

        id_token = _create_signed_id_token(rsa_keypair, valid_claims)

        with pytest.raises(pyjwt.InvalidTokenError, match="No matching key"):
            _verify_id_token(
                id_token=id_token,
                jwks_data={"keys": []},
                provider_url="https://provider.example.com",
                client_id="my-client-id",
                expected_nonce="expected-nonce-value",
            )

    def test_no_kid_in_header_uses_first_key(self, rsa_keypair, jwks_data, valid_claims):
        """Token without kid header uses the first JWKS key."""
        from auth.oidc_auth_routes import _verify_id_token

        # Create token without kid header
        id_token = pyjwt.encode(
            valid_claims,
            rsa_keypair,
            algorithm="RS256",
            headers={},  # No kid
        )

        result = _verify_id_token(
            id_token=id_token,
            jwks_data=jwks_data,
            provider_url="https://provider.example.com",
            client_id="my-client-id",
            expected_nonce="expected-nonce-value",
        )

        assert result["sub"] == "user-12345"

    def test_returns_all_claims(self, rsa_keypair, jwks_data, valid_claims):
        """Verified claims dict includes all token claims."""
        from auth.oidc_auth_routes import _verify_id_token

        valid_claims["custom_claim"] = "custom_value"
        id_token = _create_signed_id_token(rsa_keypair, valid_claims)

        result = _verify_id_token(
            id_token=id_token,
            jwks_data=jwks_data,
            provider_url="https://provider.example.com",
            client_id="my-client-id",
            expected_nonce="expected-nonce-value",
        )

        assert result["custom_claim"] == "custom_value"
        assert result["iss"] == "https://provider.example.com"
        assert result["aud"] == "my-client-id"


# ==================== _fetch_jwks Tests ====================

class TestFetchJwks:
    """Test _fetch_jwks() with caching."""

    @pytest.mark.asyncio
    async def test_fetches_jwks_from_uri(self):
        """Fetches JWKS from the provided URI."""
        from auth.oidc_auth_routes import _fetch_jwks, _jwks_cache

        # Clear cache
        _jwks_cache.clear()

        mock_jwks = {"keys": [{"kty": "RSA", "kid": "key1"}]}

        mock_response = MagicMock()
        mock_response.json.return_value = mock_jwks
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("auth.oidc_auth_routes.httpx.AsyncClient", return_value=mock_client):
            result = await _fetch_jwks("https://provider.example.com/.well-known/jwks.json")

        assert result == mock_jwks
        mock_client.get.assert_called_once_with("https://provider.example.com/.well-known/jwks.json")

    @pytest.mark.asyncio
    async def test_caches_jwks(self):
        """Second call returns cached JWKS without HTTP request."""
        from auth.oidc_auth_routes import _fetch_jwks, _jwks_cache

        # Clear cache
        _jwks_cache.clear()

        mock_jwks = {"keys": [{"kty": "RSA", "kid": "cached-key"}]}

        mock_response = MagicMock()
        mock_response.json.return_value = mock_jwks
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        jwks_uri = "https://provider.example.com/.well-known/jwks-cache-test.json"

        with patch("auth.oidc_auth_routes.httpx.AsyncClient", return_value=mock_client):
            result1 = await _fetch_jwks(jwks_uri)
            result2 = await _fetch_jwks(jwks_uri)

        # Should only have been called once (second call served from cache)
        mock_client.get.assert_called_once()
        assert result1 == result2 == mock_jwks

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self):
        """Cache entry is refreshed after TTL expires."""
        from auth.oidc_auth_routes import _fetch_jwks, _jwks_cache, _JWKS_CACHE_TTL_SECONDS

        # Clear cache
        _jwks_cache.clear()

        mock_jwks = {"keys": [{"kty": "RSA", "kid": "expired-key"}]}

        mock_response = MagicMock()
        mock_response.json.return_value = mock_jwks
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        jwks_uri = "https://provider.example.com/.well-known/jwks-ttl-test.json"

        with patch("auth.oidc_auth_routes.httpx.AsyncClient", return_value=mock_client):
            result1 = await _fetch_jwks(jwks_uri)

            # Simulate cache expiry by adjusting the fetched_at timestamp
            _jwks_cache[jwks_uri]["fetched_at"] -= (_JWKS_CACHE_TTL_SECONDS + 1)

            result2 = await _fetch_jwks(jwks_uri)

        # Should have been called twice (cache expired)
        assert mock_client.get.call_count == 2
