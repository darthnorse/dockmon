"""
TDD Tests for Group-Based Permissions Models (Phase 1)

These tests define the expected behavior of the new group-based permission models.
Written FIRST before implementation (RED phase of TDD).

Tests cover:
- GroupPermission model (new)
- OIDCGroupMapping model (new)
- CustomGroup model updates (is_system field, permissions relationship)
- ApiKey model updates (group_id instead of user_id/scopes)
- Default groups seeding
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class TestGroupPermissionModel:
    """Test GroupPermission model and relationships."""

    def test_group_permission_created_with_required_fields(self, db_session: Session):
        """GroupPermission requires group_id and capability."""
        from database import CustomGroup, GroupPermission

        group = CustomGroup(name="Test Group", description="Test")
        db_session.add(group)
        db_session.flush()

        perm = GroupPermission(group_id=group.id, capability="containers.view", allowed=True)
        db_session.add(perm)
        db_session.commit()

        assert perm.id is not None
        assert perm.group_id == group.id
        assert perm.capability == "containers.view"
        assert perm.allowed is True

    def test_group_permission_allowed_defaults_to_true(self, db_session: Session):
        """GroupPermission.allowed defaults to True if not specified."""
        from database import CustomGroup, GroupPermission

        group = CustomGroup(name="Test Group 2", description="Test")
        db_session.add(group)
        db_session.flush()

        perm = GroupPermission(group_id=group.id, capability="containers.view")
        db_session.add(perm)
        db_session.commit()

        assert perm.allowed is True

    def test_group_permission_unique_constraint(self, db_session: Session):
        """Cannot add duplicate (group_id, capability) pairs."""
        from database import CustomGroup, GroupPermission

        group = CustomGroup(name="Test Group Unique", description="Test")
        db_session.add(group)
        db_session.flush()

        perm1 = GroupPermission(group_id=group.id, capability="containers.view")
        db_session.add(perm1)
        db_session.commit()

        perm2 = GroupPermission(group_id=group.id, capability="containers.view")
        db_session.add(perm2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_group_permission_cascade_delete(self, db_session: Session):
        """Deleting group cascades to permissions."""
        from database import CustomGroup, GroupPermission

        group = CustomGroup(name="Cascade Test Group", description="Test")
        db_session.add(group)
        db_session.flush()

        perm = GroupPermission(group_id=group.id, capability="containers.view")
        db_session.add(perm)
        db_session.commit()
        perm_id = perm.id

        db_session.delete(group)
        db_session.commit()

        assert db_session.get(GroupPermission, perm_id) is None

    def test_group_permission_has_timestamps(self, db_session: Session):
        """GroupPermission has created_at and updated_at timestamps."""
        from database import CustomGroup, GroupPermission

        group = CustomGroup(name="Timestamp Test Group", description="Test")
        db_session.add(group)
        db_session.flush()

        perm = GroupPermission(group_id=group.id, capability="containers.view")
        db_session.add(perm)
        db_session.commit()

        assert perm.created_at is not None
        assert perm.updated_at is not None


class TestCustomGroupModel:
    """Test CustomGroup model updates."""

    def test_custom_group_is_system_default_false(self, db_session: Session):
        """is_system defaults to False."""
        from database import CustomGroup

        group = CustomGroup(name="Custom User Group", description="User-created")
        db_session.add(group)
        db_session.commit()

        assert group.is_system is False

    def test_custom_group_is_system_can_be_true(self, db_session: Session):
        """is_system can be set to True for system groups."""
        from database import CustomGroup

        group = CustomGroup(name="System Group", description="System", is_system=True)
        db_session.add(group)
        db_session.commit()

        assert group.is_system is True

    def test_custom_group_permissions_relationship(self, db_session: Session):
        """Group.permissions returns related GroupPermission rows."""
        from database import CustomGroup, GroupPermission

        group = CustomGroup(name="Perms Relationship Test", description="Test", is_system=True)
        db_session.add(group)
        db_session.flush()

        perm1 = GroupPermission(group_id=group.id, capability="containers.view")
        perm2 = GroupPermission(group_id=group.id, capability="containers.start")
        db_session.add_all([perm1, perm2])
        db_session.commit()

        db_session.refresh(group)
        assert len(group.permissions) == 2
        caps = {p.capability for p in group.permissions}
        assert caps == {"containers.view", "containers.start"}

    def test_custom_group_permissions_cascade_delete(self, db_session: Session):
        """Deleting group cascades to permissions via relationship."""
        from database import CustomGroup, GroupPermission

        group = CustomGroup(name="Cascade Rel Test", description="Test")
        db_session.add(group)
        db_session.flush()

        perm = GroupPermission(group_id=group.id, capability="test.cap")
        db_session.add(perm)
        db_session.commit()
        perm_id = perm.id

        db_session.delete(group)
        db_session.commit()

        # Permission should be deleted via cascade
        assert db_session.get(GroupPermission, perm_id) is None


class TestOIDCGroupMappingModel:
    """Test OIDCGroupMapping model."""

    def test_oidc_group_mapping_created(self, db_session: Session):
        """OIDCGroupMapping can be created with required fields."""
        from database import CustomGroup, OIDCGroupMapping

        group = CustomGroup(name="OIDC Target Group", description="Test")
        db_session.add(group)
        db_session.flush()

        mapping = OIDCGroupMapping(oidc_value="dev-team", group_id=group.id)
        db_session.add(mapping)
        db_session.commit()

        assert mapping.id is not None
        assert mapping.oidc_value == "dev-team"
        assert mapping.group_id == group.id
        assert mapping.priority == 0  # Default

    def test_oidc_group_mapping_unique_oidc_value(self, db_session: Session):
        """oidc_value must be unique."""
        from database import CustomGroup, OIDCGroupMapping

        group = CustomGroup(name="OIDC Unique Test", description="Test")
        db_session.add(group)
        db_session.flush()

        mapping1 = OIDCGroupMapping(oidc_value="unique-team", group_id=group.id)
        db_session.add(mapping1)
        db_session.commit()

        mapping2 = OIDCGroupMapping(oidc_value="unique-team", group_id=group.id)
        db_session.add(mapping2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_oidc_group_mapping_cascade_delete(self, db_session: Session):
        """Deleting group cascades to OIDCGroupMapping."""
        from database import CustomGroup, OIDCGroupMapping

        group = CustomGroup(name="OIDC Cascade Test", description="Test")
        db_session.add(group)
        db_session.flush()

        mapping = OIDCGroupMapping(oidc_value="cascade-team", group_id=group.id)
        db_session.add(mapping)
        db_session.commit()
        mapping_id = mapping.id

        db_session.delete(group)
        db_session.commit()

        assert db_session.get(OIDCGroupMapping, mapping_id) is None

    def test_oidc_group_mapping_priority(self, db_session: Session):
        """OIDCGroupMapping supports priority for ordering."""
        from database import CustomGroup, OIDCGroupMapping

        group = CustomGroup(name="OIDC Priority Test", description="Test")
        db_session.add(group)
        db_session.flush()

        mapping = OIDCGroupMapping(oidc_value="priority-team", group_id=group.id, priority=10)
        db_session.add(mapping)
        db_session.commit()

        assert mapping.priority == 10

    def test_oidc_group_mapping_relationship(self, db_session: Session):
        """OIDCGroupMapping.group returns the related CustomGroup."""
        from database import CustomGroup, OIDCGroupMapping

        group = CustomGroup(name="OIDC Rel Test", description="Test")
        db_session.add(group)
        db_session.flush()

        mapping = OIDCGroupMapping(oidc_value="rel-team", group_id=group.id)
        db_session.add(mapping)
        db_session.commit()

        db_session.refresh(mapping)
        assert mapping.group is not None
        assert mapping.group.name == "OIDC Rel Test"


class TestOIDCConfigModel:
    """Test OIDCConfig model updates."""

    def test_oidc_config_default_group_id(self, db_session: Session):
        """OIDCConfig has default_group_id field."""
        from database import OIDCConfig, CustomGroup

        # Create a group to reference
        group = CustomGroup(name="Default OIDC Group", description="Default")
        db_session.add(group)
        db_session.flush()

        # Create OIDC config with default group
        config = OIDCConfig(id=1, default_group_id=group.id)
        db_session.add(config)
        db_session.commit()

        assert config.default_group_id == group.id

    def test_oidc_config_default_group_nullable(self, db_session: Session):
        """OIDCConfig.default_group_id can be null."""
        from database import OIDCConfig

        config = OIDCConfig(id=1, default_group_id=None)
        db_session.add(config)
        db_session.commit()

        assert config.default_group_id is None

    def test_oidc_config_default_group_relationship(self, db_session: Session):
        """OIDCConfig.default_group returns the related CustomGroup."""
        from database import OIDCConfig, CustomGroup

        group = CustomGroup(name="OIDC Default Rel", description="Default")
        db_session.add(group)
        db_session.flush()

        config = OIDCConfig(id=1, default_group_id=group.id)
        db_session.add(config)
        db_session.commit()

        db_session.refresh(config)
        assert config.default_group is not None
        assert config.default_group.name == "OIDC Default Rel"


class TestApiKeyModel:
    """Test ApiKey model with group_id instead of user_id/scopes."""

    def test_api_key_requires_group_id(self, db_session: Session):
        """ApiKey requires group_id (NOT NULL)."""
        from database import ApiKey, User

        # Create a user for created_by_user_id
        user = User(username="apikey_test_user", password_hash="hash", auth_provider="local")
        db_session.add(user)
        db_session.flush()

        # Try to create API key without group_id - should fail
        with pytest.raises((IntegrityError, TypeError)):
            api_key = ApiKey(
                key_hash="abc123",
                key_prefix="dm_abc123",
                name="Test Key",
                # group_id missing - should fail
                created_by_user_id=user.id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db_session.add(api_key)
            db_session.commit()

    def test_api_key_with_group_id(self, db_session: Session):
        """ApiKey can be created with group_id."""
        from database import ApiKey, User, CustomGroup

        user = User(username="apikey_group_user", password_hash="hash", auth_provider="local")
        db_session.add(user)

        group = CustomGroup(name="API Key Group", description="For API keys")
        db_session.add(group)
        db_session.flush()

        api_key = ApiKey(
            key_hash="def456",
            key_prefix="dm_def456",
            name="Test Key with Group",
            group_id=group.id,
            created_by_user_id=user.id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(api_key)
        db_session.commit()

        assert api_key.id is not None
        assert api_key.group_id == group.id
        assert api_key.created_by_user_id == user.id

    def test_api_key_group_restrict_delete(self, db_session: Session):
        """Cannot delete group if API keys reference it (ON DELETE RESTRICT)."""
        from database import ApiKey, User, CustomGroup

        user = User(username="restrict_test_user", password_hash="hash", auth_provider="local")
        db_session.add(user)

        group = CustomGroup(name="Restrict Delete Group", description="Test")
        db_session.add(group)
        db_session.flush()

        api_key = ApiKey(
            key_hash="ghi789",
            key_prefix="dm_ghi789",
            name="Test Key Restrict",
            group_id=group.id,
            created_by_user_id=user.id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(api_key)
        db_session.commit()

        # Trying to delete the group should fail due to RESTRICT
        with pytest.raises(IntegrityError):
            db_session.delete(group)
            db_session.commit()

    def test_api_key_created_by_relationship(self, db_session: Session):
        """ApiKey.created_by returns the User who created it."""
        from database import ApiKey, User, CustomGroup

        user = User(username="created_by_test", password_hash="hash", auth_provider="local")
        db_session.add(user)

        group = CustomGroup(name="Created By Group", description="Test")
        db_session.add(group)
        db_session.flush()

        api_key = ApiKey(
            key_hash="jkl012",
            key_prefix="dm_jkl012",
            name="Test Key Created By",
            group_id=group.id,
            created_by_user_id=user.id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(api_key)
        db_session.commit()

        db_session.refresh(api_key)
        assert api_key.created_by is not None
        assert api_key.created_by.id == user.id
        assert api_key.created_by.username == "created_by_test"

    def test_api_key_group_relationship(self, db_session: Session):
        """ApiKey.group returns the related CustomGroup."""
        from database import ApiKey, User, CustomGroup

        user = User(username="group_rel_test", password_hash="hash", auth_provider="local")
        db_session.add(user)

        group = CustomGroup(name="API Key Group Rel", description="Test")
        db_session.add(group)
        db_session.flush()

        api_key = ApiKey(
            key_hash="mno345",
            key_prefix="dm_mno345",
            name="Test Key Group Rel",
            group_id=group.id,
            created_by_user_id=user.id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(api_key)
        db_session.commit()

        db_session.refresh(api_key)
        assert api_key.group is not None
        assert api_key.group.name == "API Key Group Rel"


@pytest.mark.integration
class TestDefaultGroups:
    """Test default groups are seeded correctly by migration.

    These tests require the migration to have run, so they are marked as integration tests.
    In unit tests, you can manually seed the groups using fixtures.
    """

    def test_administrators_group_exists(self, db_session: Session):
        """Administrators group is created by migration."""
        from database import CustomGroup

        # Seed for test
        group = CustomGroup(name="Administrators", description="Full access", is_system=True)
        db_session.add(group)
        db_session.commit()

        fetched = db_session.query(CustomGroup).filter_by(name="Administrators").first()
        assert fetched is not None
        assert fetched.is_system is True

    def test_operators_group_exists(self, db_session: Session):
        """Operators group is created by migration."""
        from database import CustomGroup

        # Seed for test
        group = CustomGroup(name="Operators", description="Operators", is_system=True)
        db_session.add(group)
        db_session.commit()

        fetched = db_session.query(CustomGroup).filter_by(name="Operators").first()
        assert fetched is not None
        assert fetched.is_system is True

    def test_readonly_group_exists(self, db_session: Session):
        """Read Only group is created by migration."""
        from database import CustomGroup

        # Seed for test
        group = CustomGroup(name="Read Only", description="Read Only", is_system=True)
        db_session.add(group)
        db_session.commit()

        fetched = db_session.query(CustomGroup).filter_by(name="Read Only").first()
        assert fetched is not None
        assert fetched.is_system is True

    def test_administrators_has_all_capabilities(self, db_session: Session):
        """Administrators group has all capabilities enabled."""
        from database import CustomGroup, GroupPermission
        from auth.capabilities import ALL_CAPABILITIES

        # Seed group and permissions for test
        group = CustomGroup(name="Administrators Test", description="Test", is_system=True)
        db_session.add(group)
        db_session.flush()

        for cap in ALL_CAPABILITIES:
            db_session.add(GroupPermission(group_id=group.id, capability=cap, allowed=True))
        db_session.commit()

        perms = db_session.query(GroupPermission).filter_by(group_id=group.id, allowed=True).all()
        perm_caps = {p.capability for p in perms}

        assert perm_caps == ALL_CAPABILITIES

    def test_readonly_has_only_view_capabilities(self, db_session: Session):
        """Read Only group has only *.view and *.read capabilities."""
        from database import CustomGroup, GroupPermission
        from auth.capabilities import READONLY_CAPABILITIES

        # Seed group and permissions for test
        group = CustomGroup(name="Read Only Test", description="Test", is_system=True)
        db_session.add(group)
        db_session.flush()

        for cap in READONLY_CAPABILITIES:
            db_session.add(GroupPermission(group_id=group.id, capability=cap, allowed=True))
        db_session.commit()

        perms = db_session.query(GroupPermission).filter_by(group_id=group.id, allowed=True).all()
        perm_caps = {p.capability for p in perms}

        # All capabilities should be in READONLY_CAPABILITIES set
        assert perm_caps == READONLY_CAPABILITIES


class TestUserModelBackwardsCompatibility:
    """Test User model backwards compatibility.

    Note: User.role is kept for backwards compatibility during migration.
    It will be removed in a future version after all code paths use groups.
    """

    def test_user_can_still_have_role(self, db_session: Session):
        """User.role still exists for backwards compatibility."""
        from database import User

        user = User(
            username="role_compat_user",
            password_hash="hash",
            auth_provider="local",
            role="admin",  # Backwards compatibility
        )
        db_session.add(user)
        db_session.commit()

        assert user.id is not None
        assert user.role == "admin"  # Still works for backwards compat
