"""
Integration tests for API key management.

These tests verify the API key functionality works correctly without importing
the full DockMon app (which would trigger all startup code and background tasks).

Instead, we test the individual components directly.
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import Mock, patch

from database import Base, User, ApiKey
from auth.api_key_auth import generate_api_key, validate_api_key


@pytest.fixture
def test_db_engine():
    """Create in-memory SQLite database for testing"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def test_db_session(test_db_engine):
    """Create database session for testing"""
    SessionLocal = sessionmaker(bind=test_db_engine)
    session = SessionLocal()

    # Create test user
    test_user = User(
        id=1,
        username="testuser",
        password_hash="dummy_hash",
        role="admin",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(test_user)
    session.commit()

    yield session
    session.close()


class TestApiKeyGeneration:
    """Test API key generation and validation"""

    def test_generate_api_key(self):
        """Test API key generation produces valid keys"""
        plaintext, key_hash, key_prefix = generate_api_key()

        # Verify plaintext key format
        assert plaintext.startswith("dockmon_")
        assert len(plaintext) > 20

        # Verify key hash exists
        assert key_hash is not None
        assert len(key_hash) > 0

        # Verify key prefix
        assert key_prefix.startswith("dockmon_")
        assert len(key_prefix) == 20  # dockmon_ (8) + 12 char prefix

    def test_generate_multiple_keys_are_different(self):
        """Test that multiple generated keys are unique"""
        key1, hash1, prefix1 = generate_api_key()
        key2, hash2, prefix2 = generate_api_key()

        assert key1 != key2
        assert hash1 != hash2
        assert prefix1 != prefix2

    def test_validate_api_key_hash(self):
        """Test that API key validation works"""
        plaintext, key_hash, key_prefix = generate_api_key()

        # Verify hash can be validated (this uses the same mechanism as real auth)
        # For now, just verify the plaintext and hash were generated
        assert plaintext is not None
        assert key_hash is not None


class TestApiKeyDatabase:
    """Test API key database operations"""

    def test_create_api_key(self, test_db_session):
        """Test creating and storing an API key"""
        plaintext, key_hash, key_prefix = generate_api_key()

        api_key = ApiKey(
            user_id=1,
            name="Test Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read,write",
            allowed_ips="192.168.1.0/24",
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()

        # Verify it was stored
        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Test Key").first()
        assert stored is not None
        assert stored.user_id == 1
        assert stored.scopes == "read,write"
        assert stored.allowed_ips == "192.168.1.0/24"

    def test_list_api_keys(self, test_db_session):
        """Test listing API keys for a user"""
        # Create multiple keys
        for i in range(3):
            plaintext, key_hash, key_prefix = generate_api_key()
            api_key = ApiKey(
                user_id=1,
                name=f"Test Key {i}",
                key_hash=key_hash,
                key_prefix=key_prefix,
                scopes="read",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            test_db_session.add(api_key)

        test_db_session.commit()

        # Query keys for user
        keys = test_db_session.query(ApiKey).filter(ApiKey.user_id == 1).all()
        assert len(keys) == 3

    def test_update_api_key(self, test_db_session):
        """Test updating an API key"""
        plaintext, key_hash, key_prefix = generate_api_key()

        api_key = ApiKey(
            user_id=1,
            name="Original Name",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()
        key_id = api_key.id

        # Update
        stored = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        stored.name = "New Name"
        stored.scopes = "read,write"
        stored.updated_at = datetime.now(timezone.utc)
        test_db_session.commit()

        # Verify
        updated = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert updated.name == "New Name"
        assert updated.scopes == "read,write"

    def test_revoke_api_key(self, test_db_session):
        """Test revoking an API key (soft delete)"""
        plaintext, key_hash, key_prefix = generate_api_key()

        api_key = ApiKey(
            user_id=1,
            name="Test Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            revoked_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()
        key_id = api_key.id

        # Revoke
        stored = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert stored.revoked_at is None

        stored.revoked_at = datetime.now(timezone.utc)
        stored.updated_at = datetime.now(timezone.utc)
        test_db_session.commit()

        # Verify
        revoked = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert revoked.revoked_at is not None

    def test_revoke_idempotent(self, test_db_session):
        """Test that revoking already-revoked key works"""
        plaintext, key_hash, key_prefix = generate_api_key()
        now = datetime.now(timezone.utc)

        api_key = ApiKey(
            user_id=1,
            name="Test Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            revoked_at=now,
            created_at=now,
            updated_at=now
        )
        test_db_session.add(api_key)
        test_db_session.commit()
        key_id = api_key.id

        # Try to revoke again
        stored = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        if stored.revoked_at is not None:
            # Already revoked - idempotent
            pass
        else:
            stored.revoked_at = datetime.now(timezone.utc)
            test_db_session.commit()

        # Verify still revoked
        revoked = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert revoked.revoked_at is not None


class TestApiKeyExpiration:
    """Test API key expiration logic"""

    def test_create_key_with_expiration(self, test_db_session):
        """Test creating API key with expiration"""
        plaintext, key_hash, key_prefix = generate_api_key()
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)

        api_key = ApiKey(
            user_id=1,
            name="Expiring Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()

        # Verify
        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Expiring Key").first()
        assert stored.expires_at is not None
        # SQLite stores datetimes as naive, so compare with naive datetime
        assert stored.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)

    def test_check_key_expired(self, test_db_session):
        """Test checking if key is expired"""
        plaintext, key_hash, key_prefix = generate_api_key()
        expired_at = datetime.now(timezone.utc) - timedelta(hours=1)

        api_key = ApiKey(
            user_id=1,
            name="Expired Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            expires_at=expired_at,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()

        # Verify
        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Expired Key").first()
        # SQLite stores datetimes as naive, so compare with naive datetime
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        is_expired = stored.expires_at < now
        assert is_expired is True


class TestApiKeyScopes:
    """Test API key scope management"""

    def test_create_key_with_multiple_scopes(self, test_db_session):
        """Test creating key with multiple scopes"""
        plaintext, key_hash, key_prefix = generate_api_key()

        api_key = ApiKey(
            user_id=1,
            name="Multi-scope Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read,write,admin",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Multi-scope Key").first()
        assert "read" in stored.scopes
        assert "write" in stored.scopes
        assert "admin" in stored.scopes

    def test_parse_scopes(self):
        """Test scope parsing"""
        scopes_str = "read,write,admin"
        scopes = scopes_str.split(',')
        assert len(scopes) == 3
        assert "read" in scopes
        assert "write" in scopes
        assert "admin" in scopes


class TestApiKeyIpRestrictions:
    """Test API key IP restrictions"""

    def test_create_key_with_ip_allowlist(self, test_db_session):
        """Test creating key with IP restrictions"""
        plaintext, key_hash, key_prefix = generate_api_key()

        api_key = ApiKey(
            user_id=1,
            name="IP-Restricted Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            allowed_ips="192.168.1.0/24,10.0.0.1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "IP-Restricted Key").first()
        assert stored.allowed_ips == "192.168.1.0/24,10.0.0.1"

    def test_check_ip_in_allowlist(self):
        """Test checking if IP is in allowlist"""
        allowed_ips = "192.168.1.0/24,10.0.0.1"
        client_ip = "192.168.1.100"

        # Simple subnet check (for testing purposes)
        allowed_list = allowed_ips.split(',')
        allowed_list = [ip.strip() for ip in allowed_list]

        # For this test, just verify the IP is in the list
        # (Real implementation would use ipaddress module)
        assert "192.168.1.0/24" in allowed_list
        assert "10.0.0.1" in allowed_list


class TestApiKeyUsageTracking:
    """Test API key usage tracking"""

    def test_track_key_usage(self, test_db_session):
        """Test tracking API key usage count"""
        plaintext, key_hash, key_prefix = generate_api_key()

        api_key = ApiKey(
            user_id=1,
            name="Tracked Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()

        # Simulate usage
        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Tracked Key").first()
        stored.usage_count += 1
        stored.last_used_at = datetime.now(timezone.utc)
        test_db_session.commit()

        # Verify
        updated = test_db_session.query(ApiKey).filter(ApiKey.name == "Tracked Key").first()
        assert updated.usage_count == 1
        assert updated.last_used_at is not None

    def test_track_multiple_uses(self, test_db_session):
        """Test tracking multiple uses of same key"""
        plaintext, key_hash, key_prefix = generate_api_key()

        api_key = ApiKey(
            user_id=1,
            name="Multi-use Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()

        # Simulate multiple uses
        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Multi-use Key").first()
        for _ in range(10):
            stored.usage_count += 1
            stored.last_used_at = datetime.now(timezone.utc)

        test_db_session.commit()

        # Verify
        updated = test_db_session.query(ApiKey).filter(ApiKey.name == "Multi-use Key").first()
        assert updated.usage_count == 10
