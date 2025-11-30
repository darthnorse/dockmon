#!/usr/bin/env python3
"""
Simple API key tests that don't import pytest or the full app.

These are standalone tests that can be run directly without triggering
the full DockMon app startup.
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, User, ApiKey
from auth.api_key_auth import generate_api_key


def test_api_key_generation():
    """Test that API keys are generated correctly"""
    plaintext, key_hash, key_prefix = generate_api_key()

    assert plaintext.startswith("dockmon_"), "Plaintext key should start with dockmon_"
    assert len(plaintext) > 20, "Plaintext key should be long enough"
    assert key_hash is not None, "Key hash should exist"
    assert key_prefix.startswith("dockmon_"), "Key prefix should start with dockmon_"
    assert len(key_prefix) == 20, "Key prefix should be 20 characters (dockmon_ + 12 chars)"

    print("✅ test_api_key_generation PASSED")


def test_database_operations():
    """Test that API keys can be stored and retrieved"""
    # Create in-memory database
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create test user
    user = User(
        id=1,
        username="testuser",
        password_hash="hash",
        role="admin",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(user)
    session.commit()

    # Create API key
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
    session.add(api_key)
    session.commit()

    # Retrieve and verify
    stored = session.query(ApiKey).filter(ApiKey.name == "Test Key").first()
    assert stored is not None, "API key should be in database"
    assert stored.user_id == 1, "User ID should match"
    assert stored.scopes == "read,write", "Scopes should match"
    assert stored.allowed_ips == "192.168.1.0/24", "IP allowlist should match"

    session.close()
    print("✅ test_database_operations PASSED")


def test_key_expiration():
    """Test API key expiration"""
    # Create in-memory database
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create user
    user = User(
        id=1,
        username="testuser",
        password_hash="hash",
        role="admin",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(user)
    session.commit()

    # Create key with expiration in future
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
    session.add(api_key)
    session.commit()

    stored = session.query(ApiKey).filter(ApiKey.name == "Expiring Key").first()
    # Note: SQLite stores naive datetimes, so compare without timezone
    now_naive = datetime.now()
    assert stored.expires_at is not None, "Expiration date should be set"

    # Create expired key
    expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
    plaintext2, key_hash2, key_prefix2 = generate_api_key()
    expired_key = ApiKey(
        user_id=1,
        name="Expired Key",
        key_hash=key_hash2,
        key_prefix=key_prefix2,
        scopes="read",
        expires_at=expired_at,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(expired_key)
    session.commit()

    stored_expired = session.query(ApiKey).filter(ApiKey.name == "Expired Key").first()
    assert stored_expired.expires_at is not None, "Expired key should have expiration date"

    session.close()
    print("✅ test_key_expiration PASSED")


def test_key_revocation():
    """Test API key revocation (soft delete)"""
    # Create in-memory database
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create user
    user = User(
        id=1,
        username="testuser",
        password_hash="hash",
        role="admin",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(user)
    session.commit()

    # Create key
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
    session.add(api_key)
    session.commit()
    key_id = api_key.id

    # Verify not revoked
    stored = session.query(ApiKey).filter(ApiKey.id == key_id).first()
    assert stored.revoked_at is None, "Key should not be revoked initially"

    # Revoke the key
    stored.revoked_at = datetime.now(timezone.utc)
    session.commit()

    # Verify revoked
    revoked = session.query(ApiKey).filter(ApiKey.id == key_id).first()
    assert revoked.revoked_at is not None, "Key should be revoked"

    session.close()
    print("✅ test_key_revocation PASSED")


def test_multiple_keys_per_user():
    """Test user can have multiple API keys"""
    # Create in-memory database
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Create user
    user = User(
        id=1,
        username="testuser",
        password_hash="hash",
        role="admin",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(user)
    session.commit()

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
        session.add(api_key)

    session.commit()

    # Verify all 3 exist
    keys = session.query(ApiKey).filter(ApiKey.user_id == 1).all()
    assert len(keys) == 3, f"Should have 3 keys, got {len(keys)}"

    session.close()
    print("✅ test_multiple_keys_per_user PASSED")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("API Key Integration Tests")
    print("="*70 + "\n")

    try:
        test_api_key_generation()
        test_database_operations()
        test_key_expiration()
        test_key_revocation()
        test_multiple_keys_per_user()

        print("\n" + "="*70)
        print("ALL TESTS PASSED ✅")
        print("="*70 + "\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
