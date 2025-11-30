"""
Unit tests for API key authentication and validation.

Tests cover:
- API key generation
- API key validation
- IP allowlist filtering (single IP, CIDR ranges, multiple entries)
- Expiration and revocation checking
- Scope-based authorization
"""

import pytest
import hashlib
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
from fastapi import HTTPException, Request

from auth.api_key_auth import (
    generate_api_key,
    validate_api_key,
    _check_ip_allowed,
    _get_user_scopes,
    get_current_user_or_api_key,
    require_scope
)
from database import ApiKey, User


class TestApiKeyGeneration:
    """Test API key generation"""

    def test_generate_api_key_format(self):
        """Generated key has correct format"""
        plaintext_key, key_hash, key_prefix = generate_api_key()

        # Check plaintext key format
        assert plaintext_key.startswith("dockmon_")
        assert len(plaintext_key) > 20  # Should be ~50+ chars with base64

        # Check hash is SHA256 (64 hex chars)
        assert len(key_hash) == 64
        assert all(c in '0123456789abcdef' for c in key_hash)

        # Check prefix is first 20 chars
        assert key_prefix == plaintext_key[:20]
        assert key_prefix.startswith("dockmon_")

    def test_generate_api_key_unique(self):
        """Each generated key is unique"""
        key1, hash1, prefix1 = generate_api_key()
        key2, hash2, prefix2 = generate_api_key()

        assert key1 != key2
        assert hash1 != hash2
        # Prefixes might overlap in first 20 chars but unlikely

    def test_generate_api_key_hash_matches(self):
        """Hash matches SHA256 of plaintext key"""
        plaintext_key, key_hash, _ = generate_api_key()

        expected_hash = hashlib.sha256(plaintext_key.encode()).hexdigest()
        assert key_hash == expected_hash


class TestIpAllowlist:
    """Test IP allowlist checking"""

    def test_check_ip_allowed_single_ip_match(self):
        """Single IP match allows access"""
        assert _check_ip_allowed("192.168.1.100", "192.168.1.100") is True

    def test_check_ip_allowed_single_ip_no_match(self):
        """Single IP mismatch denies access"""
        assert _check_ip_allowed("192.168.1.100", "192.168.1.101") is False

    def test_check_ip_allowed_cidr_match(self):
        """CIDR range match allows access"""
        assert _check_ip_allowed("192.168.1.100", "192.168.1.0/24") is True
        assert _check_ip_allowed("192.168.1.1", "192.168.1.0/24") is True
        assert _check_ip_allowed("192.168.1.254", "192.168.1.0/24") is True

    def test_check_ip_allowed_cidr_no_match(self):
        """CIDR range mismatch denies access"""
        assert _check_ip_allowed("192.168.2.100", "192.168.1.0/24") is False
        assert _check_ip_allowed("10.0.0.1", "192.168.1.0/24") is False

    def test_check_ip_allowed_multiple_entries_first_match(self):
        """Multiple entries: first entry matches"""
        allowed_ips = "192.168.1.0/24,10.0.0.1"
        assert _check_ip_allowed("192.168.1.100", allowed_ips) is True

    def test_check_ip_allowed_multiple_entries_second_match(self):
        """Multiple entries: second entry matches"""
        allowed_ips = "192.168.1.0/24,10.0.0.1"
        assert _check_ip_allowed("10.0.0.1", allowed_ips) is True

    def test_check_ip_allowed_multiple_entries_no_match(self):
        """Multiple entries: no match denies access"""
        allowed_ips = "192.168.1.0/24,10.0.0.1"
        assert _check_ip_allowed("172.16.0.1", allowed_ips) is False

    def test_check_ip_allowed_whitespace_handling(self):
        """Whitespace in allowed_ips is handled correctly"""
        allowed_ips = " 192.168.1.100 , 10.0.0.1 "
        assert _check_ip_allowed("192.168.1.100", allowed_ips) is True
        assert _check_ip_allowed("10.0.0.1", allowed_ips) is True

    def test_check_ip_allowed_invalid_client_ip(self):
        """Invalid client IP denies access"""
        assert _check_ip_allowed("not-an-ip", "192.168.1.0/24") is False

    def test_check_ip_allowed_invalid_allowed_ip_skipped(self):
        """Invalid entry in allowed_ips is skipped"""
        allowed_ips = "invalid,192.168.1.100"
        # Should skip 'invalid' and check '192.168.1.100'
        assert _check_ip_allowed("192.168.1.100", allowed_ips) is True
        assert _check_ip_allowed("10.0.0.1", allowed_ips) is False

    def test_check_ip_allowed_ipv6_support(self):
        """IPv6 addresses are supported"""
        assert _check_ip_allowed("2001:db8::1", "2001:db8::/32") is True
        assert _check_ip_allowed("2001:db8::1", "2001:db8::1") is True
        assert _check_ip_allowed("2001:db9::1", "2001:db8::/32") is False


class TestValidateApiKey:
    """Test API key validation logic"""

    def setup_method(self):
        """Setup mock database and API key"""
        self.db = Mock()
        self.session = MagicMock()
        self.db.get_session.return_value.__enter__ = Mock(return_value=self.session)
        self.db.get_session.return_value.__exit__ = Mock(return_value=False)

        # Generate test key
        self.plaintext_key, self.key_hash, self.key_prefix = generate_api_key()

        # Create mock API key record
        self.api_key = ApiKey(
            id=1,
            user_id=1,
            name="Test Key",
            key_hash=self.key_hash,
            key_prefix=self.key_prefix,
            scopes="read,write",
            allowed_ips=None,
            expires_at=None,
            revoked_at=None,
            last_used_at=None,
            usage_count=0
        )

        # Create mock user
        self.user = User(
            id=1,
            username="testuser",
            role="admin"
        )

    def test_validate_api_key_success(self):
        """Valid API key returns user context"""
        self.session.query.return_value.filter.return_value.first.side_effect = [
            self.api_key,
            self.user
        ]

        result = validate_api_key(self.plaintext_key, "192.168.1.100", self.db)

        assert result is not None
        assert result["user_id"] == 1
        assert result["username"] == "testuser"
        assert result["api_key_id"] == 1
        assert result["api_key_name"] == "Test Key"
        assert result["scopes"] == ["read", "write"]
        assert result["auth_type"] == "api_key"

        # Check usage tracking updated
        assert self.api_key.usage_count == 1
        assert self.api_key.last_used_at is not None

    def test_validate_api_key_invalid_format(self):
        """Invalid key format returns None"""
        result = validate_api_key("invalid_key", "192.168.1.100", self.db)
        assert result is None

    def test_validate_api_key_missing_prefix(self):
        """Key missing 'dockmon_' prefix returns None"""
        result = validate_api_key("someotherprefix_abc123", "192.168.1.100", self.db)
        assert result is None

    def test_validate_api_key_not_found(self):
        """Key not in database returns None"""
        self.session.query.return_value.filter.return_value.first.return_value = None

        result = validate_api_key(self.plaintext_key, "192.168.1.100", self.db)
        assert result is None

    def test_validate_api_key_revoked(self):
        """Revoked key returns None"""
        self.api_key.revoked_at = datetime.now(timezone.utc)
        self.session.query.return_value.filter.return_value.first.return_value = self.api_key

        result = validate_api_key(self.plaintext_key, "192.168.1.100", self.db)
        assert result is None

    def test_validate_api_key_expired(self):
        """Expired key returns None"""
        self.api_key.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        self.session.query.return_value.filter.return_value.first.return_value = self.api_key

        result = validate_api_key(self.plaintext_key, "192.168.1.100", self.db)
        assert result is None

    def test_validate_api_key_not_expired(self):
        """Not-yet-expired key succeeds"""
        self.api_key.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        self.session.query.return_value.filter.return_value.first.side_effect = [
            self.api_key,
            self.user
        ]

        result = validate_api_key(self.plaintext_key, "192.168.1.100", self.db)
        assert result is not None

    def test_validate_api_key_ip_allowed(self):
        """IP in allowlist succeeds"""
        self.api_key.allowed_ips = "192.168.1.0/24"
        self.session.query.return_value.filter.return_value.first.side_effect = [
            self.api_key,
            self.user
        ]

        result = validate_api_key(self.plaintext_key, "192.168.1.100", self.db)
        assert result is not None

    def test_validate_api_key_ip_blocked(self):
        """IP not in allowlist returns None"""
        self.api_key.allowed_ips = "192.168.1.0/24"
        self.session.query.return_value.filter.return_value.first.return_value = self.api_key

        result = validate_api_key(self.plaintext_key, "10.0.0.1", self.db)
        assert result is None

    def test_validate_api_key_user_not_found(self):
        """API key with missing user returns None"""
        self.session.query.return_value.filter.return_value.first.side_effect = [
            self.api_key,
            None  # User not found
        ]

        result = validate_api_key(self.plaintext_key, "192.168.1.100", self.db)
        assert result is None


class TestGetUserScopes:
    """Test user role to scope mapping"""

    def test_get_user_scopes_admin(self):
        """Admin role gets admin scope"""
        assert _get_user_scopes("admin") == ["admin"]

    def test_get_user_scopes_user(self):
        """User role gets read and write scopes"""
        assert _get_user_scopes("user") == ["read", "write"]

    def test_get_user_scopes_readonly(self):
        """Readonly role gets only read scope"""
        assert _get_user_scopes("readonly") == ["read"]

    def test_get_user_scopes_unknown(self):
        """Unknown role defaults to read scope"""
        assert _get_user_scopes("unknown") == ["read"]
        assert _get_user_scopes("") == ["read"]


class TestRequireScope:
    """Test scope-based authorization decorator"""

    @pytest.mark.asyncio
    async def test_require_scope_admin_has_all_permissions(self):
        """Admin scope grants access to all operations"""
        current_user = {
            "user_id": 1,
            "username": "admin",
            "scopes": ["admin"]
        }

        # Admin can access write operations
        check_write = require_scope("write")
        result = await check_write(current_user)
        assert result == current_user

        # Admin can access admin operations
        check_admin = require_scope("admin")
        result = await check_admin(current_user)
        assert result == current_user

    @pytest.mark.asyncio
    async def test_require_scope_user_has_read_write(self):
        """User with read,write scopes can access read and write"""
        current_user = {
            "user_id": 2,
            "username": "user",
            "scopes": ["read", "write"]
        }

        # Can access read
        check_read = require_scope("read")
        result = await check_read(current_user)
        assert result == current_user

        # Can access write
        check_write = require_scope("write")
        result = await check_write(current_user)
        assert result == current_user

    @pytest.mark.asyncio
    async def test_require_scope_user_denied_admin(self):
        """User without admin scope denied admin access"""
        current_user = {
            "user_id": 2,
            "username": "user",
            "scopes": ["read", "write"]
        }

        check_admin = require_scope("admin")

        with pytest.raises(HTTPException) as exc_info:
            await check_admin(current_user)

        assert exc_info.value.status_code == 403
        assert "admin" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_scope_readonly_denied_write(self):
        """Readonly user denied write access"""
        current_user = {
            "user_id": 3,
            "username": "readonly",
            "scopes": ["read"]
        }

        check_write = require_scope("write")

        with pytest.raises(HTTPException) as exc_info:
            await check_write(current_user)

        assert exc_info.value.status_code == 403
        assert "write" in exc_info.value.detail


class TestGetCurrentUserOrApiKey:
    """Test hybrid authentication dependency"""

    @pytest.mark.asyncio
    async def test_get_current_user_session_auth(self):
        """Session cookie authentication succeeds"""
        request = Mock(spec=Request)
        request.client.host = "192.168.1.100"

        with patch('auth.api_key_auth.cookie_session_manager') as mock_session_mgr, \
             patch('auth.api_key_auth.db') as mock_db:

            # Mock session validation
            mock_session_mgr.validate_session.return_value = {
                "user_id": 1,
                "username": "testuser"
            }

            # Mock user lookup
            mock_session = MagicMock()
            mock_user = User(id=1, username="testuser", role="admin")
            mock_session.query.return_value.filter.return_value.first.return_value = mock_user
            mock_db.get_session.return_value.__enter__ = Mock(return_value=mock_session)
            mock_db.get_session.return_value.__exit__ = Mock(return_value=False)

            result = await get_current_user_or_api_key(
                request=request,
                session_id="valid-session-id",
                authorization=None
            )

            assert result["user_id"] == 1
            assert result["username"] == "testuser"
            assert result["auth_type"] == "session"
            assert result["scopes"] == ["admin"]

    @pytest.mark.asyncio
    async def test_get_current_user_api_key_auth(self):
        """API key authentication succeeds"""
        request = Mock(spec=Request)
        request.client.host = "192.168.1.100"

        with patch('auth.api_key_auth.validate_api_key') as mock_validate:
            mock_validate.return_value = {
                "user_id": 1,
                "username": "testuser",
                "api_key_id": 1,
                "api_key_name": "Test Key",
                "scopes": ["read", "write"],
                "auth_type": "api_key"
            }

            result = await get_current_user_or_api_key(
                request=request,
                session_id=None,
                authorization="Bearer dockmon_abc123"
            )

            assert result["user_id"] == 1
            assert result["auth_type"] == "api_key"
            assert result["scopes"] == ["read", "write"]

    @pytest.mark.asyncio
    async def test_get_current_user_no_auth(self):
        """No authentication raises 401"""
        request = Mock(spec=Request)
        request.client.host = "192.168.1.100"

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_or_api_key(
                request=request,
                session_id=None,
                authorization=None
            )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_authorization_header(self):
        """Invalid Authorization header format raises 401"""
        request = Mock(spec=Request)
        request.client.host = "192.168.1.100"

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_or_api_key(
                request=request,
                session_id=None,
                authorization="InvalidFormat abc123"
            )

        assert exc_info.value.status_code == 401
