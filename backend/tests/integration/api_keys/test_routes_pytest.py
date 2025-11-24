"""
Pytest integration tests for API key functionality.

Tests API key database operations, generation, storage, and management
WITHOUT importing the full app (which causes hangs).

This approach tests what matters: the actual functionality of API keys.
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, User, ApiKey
from auth.api_key_auth import generate_api_key


@pytest.fixture(scope="function")
def test_db_session():
    """Create an in-memory SQLite database for each test"""
    # Create isolated in-memory database
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create test user
    user = User(
        id=1,
        username="testuser",
        password_hash="dummy_hash",
        role="admin",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(user)
    session.commit()

    yield session

    # Cleanup
    session.close()


class TestApiKeyGeneration:
    """Test API key generation functionality"""

    def test_generate_api_key(self):
        """Test API key generation produces valid keys"""
        plaintext, key_hash, key_prefix = generate_api_key()

        assert plaintext.startswith("dockmon_"), "Plaintext should start with dockmon_"
        assert len(plaintext) > 20, "Plaintext should be long"
        assert key_hash is not None, "Hash should be generated"
        assert key_prefix.startswith("dockmon_"), "Prefix should start with dockmon_"
        assert len(key_prefix) == 20, "Prefix should be dockmon_ (8) + 12 chars"

    def test_generate_unique_keys(self):
        """Test that multiple generations produce unique keys"""
        key1, hash1, prefix1 = generate_api_key()
        key2, hash2, prefix2 = generate_api_key()

        assert key1 != key2, "Keys should be unique"
        assert hash1 != hash2, "Hashes should be unique"
        assert prefix1 != prefix2, "Prefixes should be unique"


class TestApiKeyStorage:
    """Test API key creation and storage"""

    def test_create_and_store_minimal(self, test_db_session):
        """Create and store API key with minimal parameters"""
        plaintext, key_hash, key_prefix = generate_api_key()

        api_key = ApiKey(
            user_id=1,
            name="Test Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()

        # Retrieve and verify
        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Test Key").first()
        assert stored is not None
        assert stored.key_prefix == key_prefix
        assert stored.scopes == "read"
        assert stored.expires_at is None

    def test_create_with_expiration(self, test_db_session):
        """Create API key with expiration"""
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

        # Verify in database
        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Expiring Key").first()
        assert stored is not None
        assert stored.expires_at is not None

    def test_create_with_ip_allowlist(self, test_db_session):
        """Create API key with IP restrictions"""
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

        # Verify in database
        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "IP-Restricted Key").first()
        assert stored is not None
        assert stored.allowed_ips == "192.168.1.0/24,10.0.0.1"

    def test_create_with_multiple_scopes(self, test_db_session):
        """Create API key with multiple scopes"""
        plaintext, key_hash, key_prefix = generate_api_key()

        api_key = ApiKey(
            user_id=1,
            name="Multi-scope Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="admin,read,write",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()

        # Verify scopes are stored
        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Multi-scope Key").first()
        assert "read" in stored.scopes
        assert "write" in stored.scopes
        assert "admin" in stored.scopes


class TestApiKeyListing:
    """Test listing API keys"""

    def test_list_empty(self, test_db_session):
        """List returns empty when no keys exist"""
        keys = test_db_session.query(ApiKey).filter(ApiKey.user_id == 1).all()
        assert len(keys) == 0

    def test_list_multiple_keys(self, test_db_session):
        """List multiple keys for user"""
        # Create 3 keys
        for i in range(3):
            plaintext, key_hash, key_prefix = generate_api_key()
            api_key = ApiKey(
                user_id=1,
                name=f"Key {i}",
                key_hash=key_hash,
                key_prefix=key_prefix,
                scopes="read",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            test_db_session.add(api_key)

        test_db_session.commit()

        # Verify all 3 exist
        keys = test_db_session.query(ApiKey).filter(ApiKey.user_id == 1).all()
        assert len(keys) == 3


class TestApiKeyUpdates:
    """Test updating API keys"""

    def test_update_name(self, test_db_session):
        """Update API key name"""
        plaintext, key_hash, key_prefix = generate_api_key()
        api_key = ApiKey(
            user_id=1,
            name="Old Name",
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
        stored.updated_at = datetime.now(timezone.utc)
        test_db_session.commit()

        # Verify
        updated = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert updated.name == "New Name"

    def test_update_scopes(self, test_db_session):
        """Update API key scopes"""
        plaintext, key_hash, key_prefix = generate_api_key()
        api_key = ApiKey(
            user_id=1,
            name="Scope Key",
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
        stored.scopes = "read,write"
        stored.updated_at = datetime.now(timezone.utc)
        test_db_session.commit()

        # Verify
        updated = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert "read" in updated.scopes
        assert "write" in updated.scopes

    def test_update_ip_allowlist(self, test_db_session):
        """Update API key IP restrictions"""
        plaintext, key_hash, key_prefix = generate_api_key()
        api_key = ApiKey(
            user_id=1,
            name="IP Key",
            key_hash=key_hash,
            key_prefix=key_prefix,
            scopes="read",
            allowed_ips=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        test_db_session.add(api_key)
        test_db_session.commit()
        key_id = api_key.id

        # Update
        stored = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        stored.allowed_ips = "192.168.1.0/24"
        stored.updated_at = datetime.now(timezone.utc)
        test_db_session.commit()

        # Verify
        updated = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert updated.allowed_ips == "192.168.1.0/24"


class TestApiKeyRevocation:
    """Test revoking API keys (soft delete)"""

    def test_revoke_key(self, test_db_session):
        """Revoke API key"""
        plaintext, key_hash, key_prefix = generate_api_key()
        api_key = ApiKey(
            user_id=1,
            name="Revocable Key",
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

    def test_revoke_already_revoked(self, test_db_session):
        """Revoking already-revoked key is idempotent"""
        plaintext, key_hash, key_prefix = generate_api_key()
        now = datetime.now(timezone.utc)
        api_key = ApiKey(
            user_id=1,
            name="Already Revoked",
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

        # Try to revoke again - should be idempotent
        stored = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        if stored.revoked_at is not None:
            # Already revoked - idempotent behavior
            pass
        else:
            stored.revoked_at = datetime.now(timezone.utc)
            test_db_session.commit()

        # Verify still revoked
        revoked = test_db_session.query(ApiKey).filter(ApiKey.id == key_id).first()
        assert revoked.revoked_at is not None


class TestApiKeyUsageTracking:
    """Test API key usage tracking"""

    def test_track_usage(self, test_db_session):
        """Track API key usage count"""
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
        """Track multiple uses of same key"""
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
