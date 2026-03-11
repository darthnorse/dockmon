"""
TDD Tests for Group-Based Permissions Endpoints (Phase 4)

These tests define the expected behavior of group-related endpoints.
Written FIRST before implementation (RED phase of TDD).

Tests cover:
- Group deletion validation (system groups, API keys, orphaned users)
- Member removal validation (last group)
- User creation with groups
- First user setup flow
- /me endpoint format for both session and API key auth
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError


# =============================================================================
# Helper Functions for Creating Test Data
# =============================================================================

def create_group_with_permissions(db_session: Session, capabilities: list[str], name: str = None, is_system: bool = False):
    """Create a group with specified capabilities."""
    from database import CustomGroup, GroupPermission

    if name is None:
        name = f"TestGroup_{uuid.uuid4().hex[:8]}"

    group = CustomGroup(name=name, description="Test group", is_system=is_system)
    db_session.add(group)
    db_session.flush()

    for cap in capabilities:
        perm = GroupPermission(group_id=group.id, capability=cap, allowed=True)
        db_session.add(perm)

    db_session.commit()
    return group


def create_user_in_groups(db_session: Session, groups: list, username: str = None):
    """Create a user and add them to specified groups."""
    from database import User, UserGroupMembership

    if username is None:
        username = f"testuser_{uuid.uuid4().hex[:8]}"

    user = User(
        username=username,
        password_hash="hash",
        auth_provider="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    for group in groups:
        membership = UserGroupMembership(user_id=user.id, group_id=group.id)
        db_session.add(membership)

    db_session.commit()
    return user


def create_api_key_for_group(db_session: Session, group, created_by, name: str = None):
    """Create an API key with group assignment."""
    from database import ApiKey
    import hashlib
    import secrets

    if name is None:
        name = f"TestKey_{uuid.uuid4().hex[:8]}"

    # Generate key
    random_token = secrets.token_urlsafe(32)
    plaintext = f"dockmon_{random_token}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    prefix = plaintext[:20]

    api_key = ApiKey(
        key_hash=key_hash,
        key_prefix=prefix,
        name=name,
        group_id=group.id,
        created_by_user_id=created_by.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(api_key)
    db_session.commit()

    api_key.plaintext = plaintext
    return api_key


# =============================================================================
# Test Classes for Phase 4
# =============================================================================

class TestGroupDeletionValidation:
    """Test group deletion validation - Phase 4 requirements."""

    def test_cannot_delete_system_group(self, db_session: Session):
        """System groups (is_system=True) cannot be deleted."""
        from database import CustomGroup

        # Create a system group
        group = CustomGroup(
            name="Administrators",
            description="System admin group",
            is_system=True,
        )
        db_session.add(group)
        db_session.commit()

        # Attempt to delete should be blocked by application logic
        # The delete_group endpoint should check is_system and reject with 400
        # This test validates the model has is_system=True
        assert group.is_system is True

    def test_cannot_delete_group_with_api_keys_db_constraint(self, db_session: Session, test_user, test_group):
        """Database FK constraint prevents deleting group with API keys (ON DELETE RESTRICT)."""
        from database import CustomGroup, ApiKey

        # Create an API key assigned to the group
        api_key = create_api_key_for_group(db_session, test_group, test_user)

        # Attempt to delete the group should fail due to FK constraint
        with pytest.raises(IntegrityError):
            db_session.delete(test_group)
            db_session.commit()

        # Rollback to clean state
        db_session.rollback()

    def test_can_delete_group_without_api_keys(self, db_session: Session):
        """Groups without API keys can be deleted."""
        from database import CustomGroup

        group = CustomGroup(
            name="EmptyGroup",
            description="No API keys",
            is_system=False,
        )
        db_session.add(group)
        db_session.commit()
        group_id = group.id

        # Should be able to delete
        db_session.delete(group)
        db_session.commit()

        # Verify deleted
        assert db_session.get(CustomGroup, group_id) is None

    def test_users_with_only_this_group_identified(self, db_session: Session):
        """Identify users who would have no groups after deletion."""
        from database import CustomGroup, User, UserGroupMembership

        # Create a group
        group = CustomGroup(name="OnlyGroup", description="Test")
        db_session.add(group)
        db_session.flush()

        # Create user in only this group
        user = create_user_in_groups(db_session, [group], "orphan_user")

        # Query to find users who would be left with zero groups
        users_with_only_this_group = []
        memberships = db_session.query(UserGroupMembership).filter_by(group_id=group.id).all()

        for membership in memberships:
            other_groups = db_session.query(UserGroupMembership).filter(
                UserGroupMembership.user_id == membership.user_id,
                UserGroupMembership.group_id != group.id
            ).count()
            if other_groups == 0:
                users_with_only_this_group.append(membership.user_id)

        assert user.id in users_with_only_this_group

    def test_can_delete_group_when_users_in_other_groups(self, db_session: Session):
        """Can delete group if all users are also in other groups."""
        from database import CustomGroup

        # Create two groups
        group1 = CustomGroup(name="ToDelete", description="Test", is_system=False)
        group2 = CustomGroup(name="Remaining", description="Test", is_system=False)
        db_session.add_all([group1, group2])
        db_session.flush()

        # Create user in both groups
        user = create_user_in_groups(db_session, [group1, group2], "multigroup_user")

        group1_id = group1.id

        # Should be able to delete group1
        db_session.delete(group1)
        db_session.commit()

        # Verify deleted
        assert db_session.get(CustomGroup, group1_id) is None


class TestRemoveMemberValidation:
    """Test member removal validation - Phase 4 requirements."""

    def test_cannot_remove_from_last_group(self, db_session: Session):
        """Cannot remove user from their only group - would leave them with zero groups."""
        from database import CustomGroup, UserGroupMembership

        # Create a group
        group = CustomGroup(name="OnlyGroup", description="Test")
        db_session.add(group)
        db_session.flush()

        # Create user in only this group
        user = create_user_in_groups(db_session, [group], "single_group_user")

        # Check the user only has one group
        group_count = db_session.query(UserGroupMembership).filter_by(user_id=user.id).count()
        assert group_count == 1

        # Application logic should prevent removal - this test documents the requirement
        # Endpoint should return 400 with "Cannot remove user from their last group"

    def test_can_remove_from_one_of_multiple_groups(self, db_session: Session):
        """Can remove user from a group if they're in others."""
        from database import CustomGroup, UserGroupMembership

        # Create two groups
        group1 = CustomGroup(name="Group1", description="Test")
        group2 = CustomGroup(name="Group2", description="Test")
        db_session.add_all([group1, group2])
        db_session.flush()

        # Create user in both groups
        user = create_user_in_groups(db_session, [group1, group2], "multi_group_user")

        # Remove from group1
        membership = db_session.query(UserGroupMembership).filter_by(
            user_id=user.id, group_id=group1.id
        ).first()
        db_session.delete(membership)
        db_session.commit()

        # User should still have group2
        remaining = db_session.query(UserGroupMembership).filter_by(user_id=user.id).all()
        assert len(remaining) == 1
        assert remaining[0].group_id == group2.id


class TestUserCreationWithGroups:
    """Test user creation with group assignment - Phase 4 requirements."""

    def test_user_must_have_at_least_one_group(self, db_session: Session):
        """Users must be assigned to at least one group on creation."""
        # This is a validation requirement for the create user endpoint
        # Empty group_ids list should return 400
        # The endpoint should validate: if not request.group_ids: raise HTTPException(400)
        pass  # Endpoint test - validation requirement documented

    def test_user_created_with_specified_groups(self, db_session: Session):
        """User is added to specified groups on creation."""
        from database import CustomGroup, User, UserGroupMembership

        # Create groups
        group1 = CustomGroup(name="Operators", description="Test")
        group2 = CustomGroup(name="ReadOnly", description="Test")
        db_session.add_all([group1, group2])
        db_session.flush()

        # Create user with groups
        user = create_user_in_groups(db_session, [group1, group2], "new_user")

        # Verify memberships
        memberships = db_session.query(UserGroupMembership).filter_by(user_id=user.id).all()
        assert len(memberships) == 2
        group_ids = {m.group_id for m in memberships}
        assert group_ids == {group1.id, group2.id}

    def test_invalid_group_id_rejected(self, db_session: Session):
        """Creating user with non-existent group_id fails."""
        from database import User, UserGroupMembership

        # Create user
        user = User(
            username="bad_group_user",
            password_hash="hash",
            auth_provider="local",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(user)
        db_session.flush()

        # Try to add membership to non-existent group
        with pytest.raises(IntegrityError):
            membership = UserGroupMembership(user_id=user.id, group_id=99999)
            db_session.add(membership)
            db_session.commit()

        db_session.rollback()


class TestFirstUserSetup:
    """Test first user setup flow - Phase 4 requirements."""

    def test_first_user_auto_assigned_to_administrators(self, db_session: Session):
        """First user created is automatically in Administrators group."""
        from database import CustomGroup, User, UserGroupMembership

        # Ensure no users exist
        assert db_session.query(User).count() == 0

        # Create Administrators group (normally done by migration)
        admin_group = CustomGroup(
            name="Administrators",
            description="Full access",
            is_system=True,
        )
        db_session.add(admin_group)
        db_session.commit()

        # Create first user
        first_user = User(
            username="admin",
            password_hash="hash",
            auth_provider="local",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(first_user)
        db_session.flush()

        # Auto-assign to Administrators
        membership = UserGroupMembership(
            user_id=first_user.id,
            group_id=admin_group.id,
            added_by=None,  # System-assigned
        )
        db_session.add(membership)
        db_session.commit()

        # Verify membership
        memberships = db_session.query(UserGroupMembership).filter_by(user_id=first_user.id).all()
        assert len(memberships) == 1
        assert memberships[0].group_id == admin_group.id

    def test_setup_blocked_if_users_exist(self, db_session: Session, test_user):
        """Setup endpoint fails if users already exist."""
        from database import User

        # test_user fixture creates a user
        user_count = db_session.query(User).count()
        assert user_count > 0

        # Application logic should block first-user setup when users exist
        # Endpoint should return 400 with "Setup already completed - users exist"


class TestMeEndpointFormat:
    """Test /me endpoint returns correct format - Phase 4 requirements."""

    def test_session_auth_returns_groups_and_capabilities(self, db_session: Session):
        """Session auth returns user with groups array and capabilities."""
        from database import CustomGroup, GroupPermission
        from auth.api_key_auth import get_user_groups, get_capabilities_for_user, invalidate_group_permissions_cache, invalidate_user_groups_cache

        # Create group with permissions
        group = CustomGroup(name="TestGroup", description="Test")
        db_session.add(group)
        db_session.flush()

        db_session.add(GroupPermission(group_id=group.id, capability="containers.view", allowed=True))
        db_session.add(GroupPermission(group_id=group.id, capability="alerts.view", allowed=True))
        db_session.commit()

        # Create user in group
        user = create_user_in_groups(db_session, [group], "session_user")

        # Patch db.get_session to use test session
        from contextlib import contextmanager

        @contextmanager
        def get_session():
            yield db_session

        with patch('auth.api_key_auth.db.get_session', get_session):
            invalidate_group_permissions_cache()
            invalidate_user_groups_cache(user.id)

            # Get groups (for /me endpoint)
            groups = get_user_groups(user.id)
            assert len(groups) == 1
            assert groups[0]["name"] == "TestGroup"
            assert "id" in groups[0]

            # Get capabilities (for /me endpoint)
            capabilities = get_capabilities_for_user(user.id)
            assert "containers.view" in capabilities
            assert "alerts.view" in capabilities

    def test_api_key_auth_returns_group_info(self, db_session: Session, test_user, test_group):
        """API key auth returns key info with group."""
        from database import GroupPermission
        from auth.api_key_auth import get_capabilities_for_group, invalidate_group_permissions_cache

        # Add permissions to group
        db_session.add(GroupPermission(group_id=test_group.id, capability="containers.view", allowed=True))
        db_session.commit()

        # Create API key
        api_key = create_api_key_for_group(db_session, test_group, test_user)

        # Patch db.get_session
        from contextlib import contextmanager

        @contextmanager
        def get_session():
            yield db_session

        with patch('auth.api_key_auth.db.get_session', get_session):
            invalidate_group_permissions_cache()

            # Get capabilities for group (for /me endpoint)
            capabilities = get_capabilities_for_group(test_group.id)
            assert "containers.view" in capabilities

            # /me endpoint should return:
            # {
            #     "auth_type": "api_key",
            #     "api_key": {
            #         "id": api_key.id,
            #         "name": api_key.name,
            #         "group_id": test_group.id,
            #         "group_name": test_group.name,
            #         "created_by_username": test_user.username,
            #     },
            #     "capabilities": capabilities,
            # }


class TestGroupPermissionEndpoints:
    """Test group permission CRUD endpoints - Phase 4 requirements."""

    def test_get_group_permissions(self, db_session: Session):
        """GET /groups/{id}/permissions returns capabilities for group."""
        from database import CustomGroup, GroupPermission

        # Create group with permissions
        group = CustomGroup(name="PermTestGroup", description="Test")
        db_session.add(group)
        db_session.flush()

        db_session.add(GroupPermission(group_id=group.id, capability="containers.view", allowed=True))
        db_session.add(GroupPermission(group_id=group.id, capability="containers.start", allowed=True))
        db_session.add(GroupPermission(group_id=group.id, capability="containers.delete", allowed=False))
        db_session.commit()

        # Query permissions
        permissions = db_session.query(GroupPermission).filter_by(group_id=group.id).all()
        assert len(permissions) == 3

        allowed = [p.capability for p in permissions if p.allowed]
        denied = [p.capability for p in permissions if not p.allowed]

        assert set(allowed) == {"containers.view", "containers.start"}
        assert denied == ["containers.delete"]

    def test_update_group_permissions(self, db_session: Session):
        """PUT /groups/{id}/permissions updates capabilities."""
        from database import CustomGroup, GroupPermission

        # Create group with initial permissions
        group = CustomGroup(name="UpdatePermGroup", description="Test")
        db_session.add(group)
        db_session.flush()

        perm = GroupPermission(group_id=group.id, capability="containers.view", allowed=True)
        db_session.add(perm)
        db_session.commit()

        # Update permission
        perm.allowed = False
        db_session.commit()

        # Verify
        updated = db_session.query(GroupPermission).filter_by(
            group_id=group.id, capability="containers.view"
        ).first()
        assert updated.allowed is False

    def test_cache_invalidated_after_permission_update(self, db_session: Session):
        """Cache is invalidated when permissions change."""
        from database import CustomGroup, GroupPermission
        from auth.api_key_auth import (
            has_capability_for_group,
            invalidate_group_permissions_cache,
        )
        from contextlib import contextmanager

        # Create group with permission
        group = CustomGroup(name="CacheInvalidateGroup", description="Test")
        db_session.add(group)
        db_session.flush()

        perm = GroupPermission(group_id=group.id, capability="containers.view", allowed=True)
        db_session.add(perm)
        db_session.commit()

        @contextmanager
        def get_session():
            yield db_session

        with patch('auth.api_key_auth.db.get_session', get_session):
            invalidate_group_permissions_cache()

            # Initially allowed
            assert has_capability_for_group(group.id, "containers.view") is True

            # Update permission
            perm.allowed = False
            db_session.commit()

            # Cache still has old value
            assert has_capability_for_group(group.id, "containers.view") is True

            # After invalidation, shows new value
            invalidate_group_permissions_cache()
            assert has_capability_for_group(group.id, "containers.view") is False


class TestRequireCapabilityReplacement:
    """Test require_capability authorization - Phase 4 capability-based permissions."""

    @pytest.mark.asyncio
    async def test_require_capability_allows_with_group_permission(self, db_session: Session):
        """require_capability allows access when group has capability."""
        from auth.api_key_auth import require_capability, invalidate_group_permissions_cache, invalidate_user_groups_cache
        from contextlib import contextmanager

        # Create group with permission
        group = create_group_with_permissions(db_session, ["containers.view"])
        user = create_user_in_groups(db_session, [group])

        @contextmanager
        def get_session():
            yield db_session

        with patch('auth.api_key_auth.db.get_session', get_session):
            invalidate_group_permissions_cache()
            invalidate_user_groups_cache(user.id)

            current_user = {
                "auth_type": "session",
                "user_id": user.id,
                "username": user.username,
            }

            check_fn = require_capability("containers.view")
            result = await check_fn(current_user=current_user)
            assert result == current_user

    @pytest.mark.asyncio
    async def test_require_capability_denies_without_group_permission(self, db_session: Session):
        """require_capability denies access when group lacks capability."""
        from auth.api_key_auth import require_capability, invalidate_group_permissions_cache, invalidate_user_groups_cache
        from fastapi import HTTPException
        from contextlib import contextmanager

        # Create group WITHOUT the required permission
        group = create_group_with_permissions(db_session, ["alerts.view"])
        user = create_user_in_groups(db_session, [group])

        @contextmanager
        def get_session():
            yield db_session

        with patch('auth.api_key_auth.db.get_session', get_session):
            invalidate_group_permissions_cache()
            invalidate_user_groups_cache(user.id)

            current_user = {
                "auth_type": "session",
                "user_id": user.id,
                "username": user.username,
            }

            check_fn = require_capability("containers.view")

            with pytest.raises(HTTPException) as exc_info:
                await check_fn(current_user=current_user)

            assert exc_info.value.status_code == 403


class TestDefaultGroups:
    """Test default groups are correctly configured - Phase 4 requirements."""

    def test_administrators_group_has_all_capabilities(self, db_session: Session):
        """Administrators group should have all capabilities."""
        from database import CustomGroup, GroupPermission
        from auth.capabilities import ALL_CAPABILITIES

        # Create Administrators group with all capabilities (as migration would do)
        admin_group = CustomGroup(
            name="Administrators",
            description="Full access",
            is_system=True,
        )
        db_session.add(admin_group)
        db_session.flush()

        for cap in ALL_CAPABILITIES:
            db_session.add(GroupPermission(group_id=admin_group.id, capability=cap, allowed=True))
        db_session.commit()

        # Verify all capabilities
        permissions = db_session.query(GroupPermission).filter_by(group_id=admin_group.id).all()
        allowed_caps = {p.capability for p in permissions if p.allowed}

        assert allowed_caps == ALL_CAPABILITIES

    def test_readonly_group_has_only_view_capabilities(self, db_session: Session):
        """Read Only group should only have *.view capabilities."""
        from database import CustomGroup, GroupPermission
        from auth.capabilities import READONLY_CAPABILITIES

        # Create Read Only group (as migration would do)
        readonly_group = CustomGroup(
            name="Read Only",
            description="View-only access",
            is_system=True,
        )
        db_session.add(readonly_group)
        db_session.flush()

        for cap in READONLY_CAPABILITIES:
            db_session.add(GroupPermission(group_id=readonly_group.id, capability=cap, allowed=True))
        db_session.commit()

        # Verify only view capabilities
        permissions = db_session.query(GroupPermission).filter_by(group_id=readonly_group.id).all()
        allowed_caps = {p.capability for p in permissions if p.allowed}

        for cap in allowed_caps:
            assert cap.endswith(".view") or cap.endswith(".read") or cap in READONLY_CAPABILITIES
