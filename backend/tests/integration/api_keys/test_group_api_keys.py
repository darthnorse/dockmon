"""
Integration tests for group-based API key model (v2.3.0+).

Tests API key CRUD operations with the new group_id/created_by_user_id schema,
replacing the old user_id/scopes model.
"""

from datetime import datetime, timezone, timedelta

import pytest

from database import ApiKey, GroupPermission
from auth.api_key_auth import generate_api_key


def _make_api_key(name: str, group_id: int = 1, **overrides) -> ApiKey:
    """Create an ApiKey instance with sensible defaults."""
    _, key_hash, key_prefix = generate_api_key()
    now = datetime.now(timezone.utc)
    defaults = dict(
        created_by_user_id=1,
        group_id=group_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return ApiKey(**defaults)


class TestApiKeyCreation:
    """Test creating API keys with group-based permissions."""

    def test_create_api_key_with_admin_group(self, test_db_session):
        api_key = _make_api_key("Admin Key")
        test_db_session.add(api_key)
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Admin Key").first()
        assert stored is not None
        assert stored.created_by_user_id == 1
        assert stored.group_id == 1
        assert stored.key_hash == api_key.key_hash
        assert stored.key_prefix == api_key.key_prefix
        assert stored.revoked_at is None

    def test_create_api_key_with_operator_group(self, test_db_session):
        test_db_session.add(_make_api_key("Operator Key", group_id=2))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Operator Key").first()
        assert stored is not None
        assert stored.group_id == 2

    def test_create_api_key_with_readonly_group(self, test_db_session):
        test_db_session.add(_make_api_key("ReadOnly Key", group_id=3))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "ReadOnly Key").first()
        assert stored is not None
        assert stored.group_id == 3

    def test_create_api_key_with_expiration(self, test_db_session):
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        test_db_session.add(_make_api_key("Expiring Key", expires_at=expires))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Expiring Key").first()
        assert stored.expires_at is not None

    def test_create_api_key_with_ip_restrictions(self, test_db_session):
        test_db_session.add(_make_api_key("IP Restricted Key", allowed_ips="192.168.1.0/24,10.0.0.1"))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "IP Restricted Key").first()
        assert stored.allowed_ips == "192.168.1.0/24,10.0.0.1"


class TestApiKeyListing:
    """Test listing and querying API keys."""

    def test_list_keys_by_creator(self, test_db_session):
        for i in range(3):
            test_db_session.add(_make_api_key(f"Key {i}"))
        test_db_session.commit()

        keys = test_db_session.query(ApiKey).filter(ApiKey.created_by_user_id == 1).all()
        assert len(keys) == 3

    def test_list_keys_by_group(self, test_db_session):
        for group_id, name in [(1, "Admin"), (2, "Operator"), (3, "Reader")]:
            test_db_session.add(_make_api_key(name, group_id=group_id))
        test_db_session.commit()

        admin_keys = test_db_session.query(ApiKey).filter(ApiKey.group_id == 1).all()
        assert len(admin_keys) == 1
        assert admin_keys[0].name == "Admin"


class TestApiKeyUpdates:
    """Test updating API key properties."""

    def test_update_name(self, test_db_session):
        test_db_session.add(_make_api_key("Original Name"))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Original Name").first()
        stored.name = "Updated Name"
        test_db_session.commit()

        updated = test_db_session.query(ApiKey).filter(ApiKey.id == stored.id).first()
        assert updated.name == "Updated Name"

    def test_update_group(self, test_db_session):
        """API key can be reassigned to a different group."""
        test_db_session.add(_make_api_key("Reassigned Key"))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Reassigned Key").first()
        stored.group_id = 3  # Downgrade to read-only
        test_db_session.commit()

        updated = test_db_session.query(ApiKey).filter(ApiKey.id == stored.id).first()
        assert updated.group_id == 3


class TestApiKeyRevocation:
    """Test revoking API keys."""

    def test_revoke_key(self, test_db_session):
        test_db_session.add(_make_api_key("Revoke Me"))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Revoke Me").first()
        assert stored.revoked_at is None

        stored.revoked_at = datetime.now(timezone.utc)
        test_db_session.commit()

        revoked = test_db_session.query(ApiKey).filter(ApiKey.id == stored.id).first()
        assert revoked.revoked_at is not None

    def test_revoke_idempotent(self, test_db_session):
        test_db_session.add(_make_api_key("Already Revoked", revoked_at=datetime.now(timezone.utc)))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Already Revoked").first()
        assert stored.revoked_at is not None


class TestApiKeyUsageTracking:
    """Test usage tracking fields."""

    def test_track_usage(self, test_db_session):
        test_db_session.add(_make_api_key("Usage Key"))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Usage Key").first()
        assert stored.usage_count == 0
        assert stored.last_used_at is None

        stored.usage_count += 1
        stored.last_used_at = datetime.now(timezone.utc)
        test_db_session.commit()

        updated = test_db_session.query(ApiKey).filter(ApiKey.id == stored.id).first()
        assert updated.usage_count == 1
        assert updated.last_used_at is not None


class TestApiKeyExpiration:
    """Test API key expiration."""

    def test_expired_key(self, test_db_session):
        expired_time = datetime.now(timezone.utc) - timedelta(days=1)
        test_db_session.add(_make_api_key("Expired Key", expires_at=expired_time))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Expired Key").first()
        assert stored.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)

    def test_non_expired_key(self, test_db_session):
        future_time = datetime.now(timezone.utc) + timedelta(days=30)
        test_db_session.add(_make_api_key("Valid Key", expires_at=future_time))
        test_db_session.commit()

        stored = test_db_session.query(ApiKey).filter(ApiKey.name == "Valid Key").first()
        assert stored.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


class TestGroupPermissionIntegration:
    """Test that group permissions are correctly stored and queryable."""

    def test_admin_group_has_all_capabilities(self, test_db_session):
        from auth.capabilities import ALL_CAPABILITIES
        perms = test_db_session.query(GroupPermission).filter(
            GroupPermission.group_id == 1,
            GroupPermission.allowed == True,
        ).all()
        perm_caps = {p.capability for p in perms}
        for cap in ALL_CAPABILITIES:
            assert cap in perm_caps, f"Admin group missing capability: {cap}"

    def test_readonly_group_cannot_operate(self, test_db_session):
        perms = test_db_session.query(GroupPermission).filter(
            GroupPermission.group_id == 3,
            GroupPermission.allowed == True,
        ).all()
        perm_caps = {p.capability for p in perms}
        assert 'containers.operate' not in perm_caps
        assert 'settings.manage' not in perm_caps
        assert 'containers.view' in perm_caps

    def test_api_key_inherits_group_permissions(self, test_db_session):
        """Verify the FK relationship between API key and group."""
        test_db_session.add(_make_api_key("Operator Check", group_id=2))
        test_db_session.commit()

        api_key = test_db_session.query(ApiKey).filter(ApiKey.name == "Operator Check").first()
        perms = test_db_session.query(GroupPermission).filter(
            GroupPermission.group_id == api_key.group_id,
            GroupPermission.allowed == True,
        ).all()
        perm_caps = {p.capability for p in perms}
        assert 'containers.operate' in perm_caps
        assert 'containers.view' in perm_caps
        assert 'settings.manage' not in perm_caps
