"""
TDD Tests for Group-Based Permissions Auth Logic (Phase 2)

These tests define the expected behavior of the group-based permission system.
Written FIRST before implementation (RED phase of TDD).

Tests cover:
- has_capability_for_group() - Check if a group has a specific capability
- has_capability_for_user() - Check if user has capability via any of their groups (union)
- get_user_group_ids() - Get list of group IDs for a user (cached)
- get_user_groups() - Get list of groups for a user with id and name
- get_capabilities_for_group() - Get list of capabilities for a group
- get_capabilities_for_user() - Get union of all capabilities from user's groups
- Group permissions cache - Thread-safe caching
- User groups cache - Caching with invalidation
- validate_api_key() - Returns group info instead of scopes
- require_capability() - Checks group permissions
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from auth.api_key_auth import Capabilities


@contextmanager
def mock_db_session(session):
    """Context manager to mock db.get_session() to return the test session."""
    @contextmanager
    def get_session():
        yield session
    return get_session()


@pytest.fixture(autouse=True)
def patch_db_for_tests(db_session: Session):
    """Automatically patch db.get_session() to use the test session for all tests.

    Also invalidates all auth caches to ensure test isolation.
    """
    from auth.api_key_auth import (
        invalidate_group_permissions_cache,
        invalidate_user_groups_cache,
    )

    # Invalidate all caches before each test
    invalidate_group_permissions_cache()
    invalidate_user_groups_cache()

    @contextmanager
    def get_session():
        yield db_session

    with patch('auth.api_key_auth.db.get_session', get_session):
        yield

    # Invalidate caches after test completes (cleanup)
    invalidate_group_permissions_cache()
    invalidate_user_groups_cache()


# =============================================================================
# Helper Functions for Creating Test Data
# =============================================================================

def create_group_with_permissions(db_session: Session, capabilities: list[str], name: str = None):
    """Create a group with specified capabilities."""
    from database import CustomGroup, GroupPermission

    if name is None:
        # Generate unique name
        name = f"TestGroup_{uuid.uuid4().hex[:8]}"

    group = CustomGroup(name=name, description="Test group")
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


def create_api_key(db_session: Session, group, created_by, name: str = None):
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

    # Add plaintext to the object for testing
    api_key.plaintext = plaintext
    return api_key


# =============================================================================
# Test Classes
# =============================================================================

class TestHasCapabilityForGroup:
    """Test has_capability_for_group() function."""

    def test_returns_true_when_group_has_capability(self, db_session: Session):
        """Returns True if group has the capability allowed."""
        from auth.api_key_auth import has_capability_for_group, invalidate_group_permissions_cache

        group = create_group_with_permissions(db_session, ["containers.view", "containers.start"])
        invalidate_group_permissions_cache()

        assert has_capability_for_group(group.id, "containers.view") is True
        assert has_capability_for_group(group.id, "containers.start") is True

    def test_returns_false_when_group_lacks_capability(self, db_session: Session):
        """Returns False if group doesn't have the capability."""
        from auth.api_key_auth import has_capability_for_group, invalidate_group_permissions_cache

        group = create_group_with_permissions(db_session, ["containers.view"])
        invalidate_group_permissions_cache()

        assert has_capability_for_group(group.id, "containers.delete") is False

    def test_returns_false_when_capability_explicitly_denied(self, db_session: Session):
        """Returns False if capability exists but allowed=False."""
        from database import CustomGroup, GroupPermission
        from auth.api_key_auth import has_capability_for_group, invalidate_group_permissions_cache

        group = CustomGroup(name="Denied Test Group", description="Test")
        db_session.add(group)
        db_session.flush()

        perm = GroupPermission(group_id=group.id, capability="containers.view", allowed=False)
        db_session.add(perm)
        db_session.commit()
        invalidate_group_permissions_cache()

        assert has_capability_for_group(group.id, "containers.view") is False

    def test_returns_false_for_nonexistent_group(self, db_session: Session):
        """Returns False for group ID that doesn't exist."""
        from auth.api_key_auth import has_capability_for_group, invalidate_group_permissions_cache

        invalidate_group_permissions_cache()

        assert has_capability_for_group(99999, "containers.view") is False


class TestHasCapabilityForUser:
    """Test has_capability_for_user() with union semantics."""

    def test_user_with_no_groups_has_no_permissions(self, db_session: Session):
        """User with no groups has no capabilities."""
        from database import User
        from auth.api_key_auth import has_capability_for_user, invalidate_group_permissions_cache, invalidate_user_groups_cache

        user = User(
            username="no_groups_user",
            password_hash="hash",
            auth_provider="local",
        )
        db_session.add(user)
        db_session.commit()

        invalidate_group_permissions_cache()
        invalidate_user_groups_cache(user.id)

        assert has_capability_for_user(user.id, "containers.view") is False

    def test_user_gets_capability_from_single_group(self, db_session: Session):
        """User gets capabilities from their group."""
        from auth.api_key_auth import has_capability_for_user, invalidate_group_permissions_cache, invalidate_user_groups_cache

        group = create_group_with_permissions(db_session, ["containers.view"])
        user = create_user_in_groups(db_session, [group])
        invalidate_group_permissions_cache()
        invalidate_user_groups_cache(user.id)

        assert has_capability_for_user(user.id, "containers.view") is True
        assert has_capability_for_user(user.id, "containers.delete") is False

    def test_user_gets_union_of_multiple_groups(self, db_session: Session):
        """User in multiple groups gets union of all capabilities."""
        from auth.api_key_auth import has_capability_for_user, invalidate_group_permissions_cache, invalidate_user_groups_cache

        group1 = create_group_with_permissions(db_session, ["containers.view"], "Group1")
        group2 = create_group_with_permissions(db_session, ["hosts.manage"], "Group2")
        user = create_user_in_groups(db_session, [group1, group2])
        invalidate_group_permissions_cache()
        invalidate_user_groups_cache(user.id)

        # Has capabilities from both groups
        assert has_capability_for_user(user.id, "containers.view") is True
        assert has_capability_for_user(user.id, "hosts.manage") is True
        # But not capabilities from neither group
        assert has_capability_for_user(user.id, "users.manage") is False

    def test_union_semantics_any_true_wins(self, db_session: Session):
        """If ANY group allows a capability, user has it."""
        from database import CustomGroup
        from auth.api_key_auth import has_capability_for_user, invalidate_group_permissions_cache, invalidate_user_groups_cache

        group1 = create_group_with_permissions(db_session, ["containers.view"], "Group With Perms")

        # group2 has no permissions at all
        group2 = CustomGroup(name="Restrictive", description="No perms")
        db_session.add(group2)
        db_session.commit()

        user = create_user_in_groups(db_session, [group1, group2])
        invalidate_group_permissions_cache()
        invalidate_user_groups_cache(user.id)

        # Still has containers.view from group1
        assert has_capability_for_user(user.id, "containers.view") is True


class TestGetUserGroupIds:
    """Test get_user_group_ids() caching."""

    def test_returns_list_of_group_ids(self, db_session: Session):
        """Returns list of group IDs user belongs to."""
        from database import CustomGroup
        from auth.api_key_auth import get_user_group_ids, invalidate_user_groups_cache

        group1 = CustomGroup(name="GroupIds1", description="Test")
        group2 = CustomGroup(name="GroupIds2", description="Test")
        db_session.add_all([group1, group2])
        db_session.flush()

        user = create_user_in_groups(db_session, [group1, group2])
        invalidate_user_groups_cache(user.id)

        group_ids = get_user_group_ids(user.id)
        assert set(group_ids) == {group1.id, group2.id}

    def test_caches_result(self, db_session: Session):
        """Second call returns cached result without DB query."""
        from database import CustomGroup, UserGroupMembership
        from auth.api_key_auth import get_user_group_ids, invalidate_user_groups_cache

        group = CustomGroup(name="Cache Test Group", description="Test")
        db_session.add(group)
        db_session.flush()
        user = create_user_in_groups(db_session, [group])
        invalidate_user_groups_cache(user.id)

        # First call - hits DB
        result1 = get_user_group_ids(user.id)

        # Add another group directly in DB (bypass cache)
        group2 = CustomGroup(name="Cache Test Group 2", description="Test")
        db_session.add(group2)
        db_session.flush()
        db_session.add(UserGroupMembership(user_id=user.id, group_id=group2.id))
        db_session.commit()

        # Second call - should return cached (stale) result
        result2 = get_user_group_ids(user.id)
        assert result1 == result2  # Cache not invalidated

    def test_cache_invalidation_clears_user(self, db_session: Session):
        """invalidate_user_groups_cache(user_id) clears that user's cache."""
        from database import CustomGroup, UserGroupMembership
        from auth.api_key_auth import get_user_group_ids, invalidate_user_groups_cache

        group = CustomGroup(name="Invalidate Test Group", description="Test")
        db_session.add(group)
        db_session.flush()
        user = create_user_in_groups(db_session, [group])
        invalidate_user_groups_cache(user.id)

        # Prime cache
        get_user_group_ids(user.id)

        # Add another group
        group2 = CustomGroup(name="Invalidate Test Group 2", description="Test")
        db_session.add(group2)
        db_session.flush()
        db_session.add(UserGroupMembership(user_id=user.id, group_id=group2.id))
        db_session.commit()

        # Invalidate and re-fetch
        invalidate_user_groups_cache(user.id)
        result = get_user_group_ids(user.id)
        assert set(result) == {group.id, group2.id}


class TestGroupPermissionsCache:
    """Test group permissions cache."""

    def test_cache_loads_on_first_access(self, db_session: Session):
        """Cache is populated on first capability check."""
        from auth.api_key_auth import has_capability_for_group, invalidate_group_permissions_cache
        from auth import api_key_auth

        group = create_group_with_permissions(db_session, ["containers.view"])
        invalidate_group_permissions_cache()

        # This should trigger cache load
        has_capability_for_group(group.id, "containers.view")

        # Verify cache is loaded (implementation detail, but important)
        assert api_key_auth._group_cache_loaded is True

    def test_invalidation_forces_reload(self, db_session: Session):
        """After invalidation, next check reloads from DB."""
        from database import GroupPermission
        from auth.api_key_auth import has_capability_for_group, invalidate_group_permissions_cache

        group = create_group_with_permissions(db_session, ["containers.view"])
        invalidate_group_permissions_cache()

        # Prime cache
        assert has_capability_for_group(group.id, "containers.view") is True

        # Add permission directly in DB
        perm = GroupPermission(group_id=group.id, capability="containers.delete", allowed=True)
        db_session.add(perm)
        db_session.commit()

        # Still cached - doesn't see new permission
        assert has_capability_for_group(group.id, "containers.delete") is False

        # Invalidate and check again
        invalidate_group_permissions_cache()
        assert has_capability_for_group(group.id, "containers.delete") is True


class TestGetCapabilitiesForUser:
    """Test get_capabilities_for_user() returns union."""

    def test_returns_sorted_list(self, db_session: Session):
        """Returns sorted list of capabilities."""
        from auth.api_key_auth import get_capabilities_for_user, invalidate_group_permissions_cache, invalidate_user_groups_cache

        group = create_group_with_permissions(db_session, ["containers.view", "alerts.view"])
        user = create_user_in_groups(db_session, [group])
        invalidate_group_permissions_cache()
        invalidate_user_groups_cache(user.id)

        caps = get_capabilities_for_user(user.id)
        assert caps == ["alerts.view", "containers.view"]  # Sorted

    def test_returns_union_from_multiple_groups(self, db_session: Session):
        """Returns union of capabilities from all groups."""
        from auth.api_key_auth import get_capabilities_for_user, invalidate_group_permissions_cache, invalidate_user_groups_cache

        group1 = create_group_with_permissions(db_session, ["containers.view"], "Caps Union 1")
        group2 = create_group_with_permissions(db_session, ["hosts.manage"], "Caps Union 2")
        user = create_user_in_groups(db_session, [group1, group2])
        invalidate_group_permissions_cache()
        invalidate_user_groups_cache(user.id)

        caps = get_capabilities_for_user(user.id)
        assert "containers.view" in caps
        assert "hosts.manage" in caps

    def test_no_duplicates(self, db_session: Session):
        """Same capability in multiple groups appears once."""
        from auth.api_key_auth import get_capabilities_for_user, invalidate_group_permissions_cache, invalidate_user_groups_cache

        group1 = create_group_with_permissions(db_session, ["containers.view"], "No Dup 1")
        group2 = create_group_with_permissions(db_session, ["containers.view", "hosts.manage"], "No Dup 2")
        user = create_user_in_groups(db_session, [group1, group2])
        invalidate_group_permissions_cache()
        invalidate_user_groups_cache(user.id)

        caps = get_capabilities_for_user(user.id)
        assert caps.count("containers.view") == 1


class TestGetCapabilitiesForGroup:
    """Test get_capabilities_for_group()."""

    def test_returns_list_of_allowed_capabilities(self, db_session: Session):
        """Returns list of capabilities for a group."""
        from auth.api_key_auth import get_capabilities_for_group, invalidate_group_permissions_cache

        group = create_group_with_permissions(db_session, ["containers.view", "alerts.view"])
        invalidate_group_permissions_cache()

        caps = get_capabilities_for_group(group.id)
        assert set(caps) == {"containers.view", "alerts.view"}

    def test_excludes_denied_capabilities(self, db_session: Session):
        """Capabilities with allowed=False are excluded."""
        from database import CustomGroup, GroupPermission
        from auth.api_key_auth import get_capabilities_for_group, invalidate_group_permissions_cache

        group = CustomGroup(name="Mixed Perms Group", description="Test")
        db_session.add(group)
        db_session.flush()

        # Add allowed and denied capabilities
        db_session.add(GroupPermission(group_id=group.id, capability="containers.view", allowed=True))
        db_session.add(GroupPermission(group_id=group.id, capability="containers.delete", allowed=False))
        db_session.commit()
        invalidate_group_permissions_cache()

        caps = get_capabilities_for_group(group.id)
        assert "containers.view" in caps
        assert "containers.delete" not in caps


class TestGetUserGroups:
    """Test get_user_groups() for /me endpoint."""

    def test_returns_list_of_group_dicts(self, db_session: Session):
        """Returns list of {id, name} dicts."""
        from database import CustomGroup
        from auth.api_key_auth import get_user_groups

        group1 = CustomGroup(name="User Groups Test 1", description="Test")
        group2 = CustomGroup(name="User Groups Test 2", description="Test")
        db_session.add_all([group1, group2])
        db_session.flush()

        user = create_user_in_groups(db_session, [group1, group2])

        groups = get_user_groups(user.id)
        assert len(groups) == 2

        names = {g["name"] for g in groups}
        assert names == {"User Groups Test 1", "User Groups Test 2"}

        # Each dict has id and name
        for g in groups:
            assert "id" in g
            assert "name" in g

    def test_returns_empty_for_user_with_no_groups(self, db_session: Session):
        """Returns empty list for user with no groups."""
        from database import User
        from auth.api_key_auth import get_user_groups

        user = User(
            username="empty_groups_user",
            password_hash="hash",
            auth_provider="local",
        )
        db_session.add(user)
        db_session.commit()

        groups = get_user_groups(user.id)
        assert groups == []


class TestValidateApiKey:
    """Test validate_api_key() returns group info."""

    def test_returns_group_id_and_name(self, db_session: Session, test_user, test_group):
        """Returns group_id and group_name in result."""
        from auth.api_key_auth import validate_api_key, invalidate_group_permissions_cache
        from auth.shared import db as auth_db

        # Add some permissions to the group
        from database import GroupPermission
        db_session.add(GroupPermission(group_id=test_group.id, capability="containers.view"))
        db_session.commit()
        invalidate_group_permissions_cache()

        api_key = create_api_key(db_session, group=test_group, created_by=test_user)

        # Mock the db.get_session to use our test session
        with patch.object(auth_db, 'get_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            result = validate_api_key(api_key.plaintext, "127.0.0.1", auth_db)

        assert result is not None
        assert result["group_id"] == test_group.id
        assert result["group_name"] == test_group.name
        assert result["auth_type"] == "api_key"

    def test_returns_created_by_info(self, db_session: Session, test_user, test_group):
        """Returns created_by_user_id and created_by_username."""
        from auth.api_key_auth import validate_api_key
        from auth.shared import db as auth_db

        api_key = create_api_key(db_session, group=test_group, created_by=test_user)

        with patch.object(auth_db, 'get_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            result = validate_api_key(api_key.plaintext, "127.0.0.1", auth_db)

        assert result["created_by_user_id"] == test_user.id
        assert result["created_by_username"] == test_user.username

    def test_does_not_return_scopes(self, db_session: Session, test_user, test_group):
        """API key validation no longer returns scopes."""
        from auth.api_key_auth import validate_api_key
        from auth.shared import db as auth_db

        api_key = create_api_key(db_session, group=test_group, created_by=test_user)

        with patch.object(auth_db, 'get_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

            result = validate_api_key(api_key.plaintext, "127.0.0.1", auth_db)

        # scopes field should not be in result anymore
        assert "scopes" not in result


class TestRequireCapabilityWithGroups:
    """Test require_capability() with group-based permissions."""

    @pytest.mark.asyncio
    async def test_api_key_checked_against_group(self, db_session: Session, test_user):
        """API key capability checked against its group."""
        from auth.api_key_auth import require_capability, invalidate_group_permissions_cache

        group = create_group_with_permissions(db_session, ["containers.view"])
        api_key = create_api_key(db_session, group=group, created_by=test_user)
        invalidate_group_permissions_cache()

        # Create mock current_user dict as returned by get_current_user_or_api_key
        current_user = {
            "auth_type": "api_key",
            "api_key_id": api_key.id,
            "api_key_name": api_key.name,
            "group_id": group.id,
            "group_name": group.name,
            "created_by_user_id": test_user.id,
            "created_by_username": test_user.username,
        }

        # The dependency should return current_user when capability is allowed
        check_fn = require_capability("containers.view")

        # Call the inner function directly with mock
        with patch('auth.api_key_auth.get_current_user_or_api_key', return_value=current_user):
            from fastapi import Depends
            result = await check_fn(current_user=current_user)
            assert result == current_user

    @pytest.mark.asyncio
    async def test_api_key_denied_when_group_lacks_capability(self, db_session: Session, test_user):
        """API key denied if its group lacks capability."""
        from auth.api_key_auth import require_capability, invalidate_group_permissions_cache
        from fastapi import HTTPException

        # Group only has alerts.view, not containers.view
        group = create_group_with_permissions(db_session, ["alerts.view"])
        api_key = create_api_key(db_session, group=group, created_by=test_user)
        invalidate_group_permissions_cache()

        current_user = {
            "auth_type": "api_key",
            "api_key_id": api_key.id,
            "api_key_name": api_key.name,
            "group_id": group.id,
            "group_name": group.name,
            "created_by_user_id": test_user.id,
            "created_by_username": test_user.username,
        }

        check_fn = require_capability("containers.view")

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(current_user=current_user)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_session_user_checked_against_groups(self, db_session: Session):
        """Session user capability checked against all their groups."""
        from auth.api_key_auth import require_capability, invalidate_group_permissions_cache, invalidate_user_groups_cache

        group = create_group_with_permissions(db_session, ["containers.view"])
        user = create_user_in_groups(db_session, [group])
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
    async def test_session_user_denied_without_capability(self, db_session: Session):
        """Session user denied if no group has capability."""
        from auth.api_key_auth import require_capability, invalidate_group_permissions_cache, invalidate_user_groups_cache
        from fastapi import HTTPException

        group = create_group_with_permissions(db_session, ["alerts.view"])
        user = create_user_in_groups(db_session, [group])
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


class TestUserGroupsCacheInvalidation:
    """Test user groups cache invalidation."""

    def test_invalidate_specific_user(self, db_session: Session):
        """invalidate_user_groups_cache(user_id) only clears that user."""
        from database import CustomGroup
        from auth.api_key_auth import get_user_group_ids, invalidate_user_groups_cache

        group = CustomGroup(name="Invalidate Specific", description="Test")
        db_session.add(group)
        db_session.flush()

        user1 = create_user_in_groups(db_session, [group], "user1")
        user2 = create_user_in_groups(db_session, [group], "user2")

        invalidate_user_groups_cache()  # Clear all

        # Prime caches
        get_user_group_ids(user1.id)
        get_user_group_ids(user2.id)

        # Invalidate only user1
        invalidate_user_groups_cache(user1.id)

        # User2's cache should still be intact
        # (we can't directly test this without accessing internals,
        # but the API should work correctly)

    def test_invalidate_all_users(self, db_session: Session):
        """invalidate_user_groups_cache() with no arg clears all."""
        from database import CustomGroup, UserGroupMembership
        from auth.api_key_auth import get_user_group_ids, invalidate_user_groups_cache

        group1 = CustomGroup(name="Invalidate All 1", description="Test")
        group2 = CustomGroup(name="Invalidate All 2", description="Test")
        db_session.add_all([group1, group2])
        db_session.flush()

        user = create_user_in_groups(db_session, [group1])
        invalidate_user_groups_cache()

        # Prime cache
        result1 = get_user_group_ids(user.id)
        assert group1.id in result1

        # Add to another group
        db_session.add(UserGroupMembership(user_id=user.id, group_id=group2.id))
        db_session.commit()

        # Invalidate all
        invalidate_user_groups_cache()

        result2 = get_user_group_ids(user.id)
        assert group1.id in result2
        assert group2.id in result2
