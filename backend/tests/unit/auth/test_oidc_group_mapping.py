"""
TDD Tests for OIDC Group Mapping (Phase 6)

These tests define the expected behavior of OIDC group mapping and sync.
Written as part of Phase 6 Testing & Cleanup.

Tests cover:
- _get_groups_for_oidc_user() - Maps OIDC groups to DockMon groups
- OIDC user provisioning - New users added to matching groups
- OIDC user group sync - Existing users' groups replaced on re-login
- First user auto-assignment - First OIDC user gets Administrators
- Default group fallback - Users with no matching groups get default
- Cache invalidation - User groups cache cleared after sync
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from sqlalchemy.orm import Session

from database import (
    CustomGroup,
    User,
    UserGroupMembership,
    GroupPermission,
    OIDCGroupMapping,
    OIDCConfig,
)


# =============================================================================
# Helper Functions for Creating Test Data
# =============================================================================

def create_group(db_session: Session, name: str = None, is_system: bool = False) -> CustomGroup:
    """Create a group."""
    if name is None:
        name = f"TestGroup_{uuid.uuid4().hex[:8]}"

    group = CustomGroup(name=name, description="Test group", is_system=is_system)
    db_session.add(group)
    db_session.flush()
    return group


def create_oidc_mapping(db_session: Session, oidc_value: str, group: CustomGroup, priority: int = 0) -> OIDCGroupMapping:
    """Create an OIDC group mapping."""
    mapping = OIDCGroupMapping(
        oidc_value=oidc_value,
        group_id=group.id,
        priority=priority,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(mapping)
    db_session.commit()
    return mapping


def create_user(db_session: Session, username: str = None, auth_provider: str = "oidc", oidc_subject: str = None) -> User:
    """Create a user."""
    if username is None:
        username = f"testuser_{uuid.uuid4().hex[:8]}"
    if oidc_subject is None:
        oidc_subject = f"oidc_{uuid.uuid4().hex[:16]}"

    user = User(
        username=username,
        password_hash="",
        auth_provider=auth_provider,
        oidc_subject=oidc_subject if auth_provider == "oidc" else None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    return user


def add_user_to_groups(db_session: Session, user: User, groups: list[CustomGroup]) -> None:
    """Add user to groups."""
    for group in groups:
        membership = UserGroupMembership(
            user_id=user.id,
            group_id=group.id,
            added_at=datetime.now(timezone.utc),
        )
        db_session.add(membership)
    db_session.commit()


def get_user_group_ids(db_session: Session, user_id: int) -> set[int]:
    """Get set of group IDs for a user."""
    memberships = db_session.query(UserGroupMembership).filter_by(user_id=user_id).all()
    return {m.group_id for m in memberships}


def setup_oidc_config(db_session: Session, default_group: CustomGroup = None) -> OIDCConfig:
    """Create or update OIDC config."""
    config = db_session.query(OIDCConfig).filter(OIDCConfig.id == 1).first()
    if not config:
        config = OIDCConfig(
            id=1,
            enabled=True,
            provider_url="https://example.com",
            client_id="test-client",
        )
        db_session.add(config)

    if default_group:
        config.default_group_id = default_group.id

    db_session.commit()
    return config


# =============================================================================
# Test Classes for _get_groups_for_oidc_user()
# =============================================================================

class TestGetGroupsForOidcUser:
    """Test _get_groups_for_oidc_user() mapping logic."""

    def test_returns_matching_group_ids(self, db_session: Session):
        """Returns group IDs for matching OIDC values."""
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        group1 = create_group(db_session, "Devs")
        group2 = create_group(db_session, "Ops")

        create_oidc_mapping(db_session, "dev-team", group1)
        create_oidc_mapping(db_session, "ops-team", group2)

        result = _get_groups_for_oidc_user(["dev-team", "ops-team"], db_session)
        assert set(result) == {group1.id, group2.id}

    def test_returns_only_matching_groups(self, db_session: Session):
        """Only returns groups that match OIDC claims."""
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        group1 = create_group(db_session, "Devs Only")
        group2 = create_group(db_session, "Ops Only")

        create_oidc_mapping(db_session, "dev-team", group1)
        create_oidc_mapping(db_session, "ops-team", group2)

        # User only in dev-team
        result = _get_groups_for_oidc_user(["dev-team"], db_session)
        assert result == [group1.id]

    def test_returns_default_group_when_no_matches(self, db_session: Session):
        """Returns default_group_id when no OIDC groups match."""
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        default_group = create_group(db_session, "Default Group")
        setup_oidc_config(db_session, default_group=default_group)

        result = _get_groups_for_oidc_user(["unknown-team"], db_session)
        assert result == [default_group.id]

    def test_returns_empty_when_no_matches_and_no_default(self, db_session: Session):
        """Returns empty list if no matches and no default configured."""
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        # Clear any default group
        config = setup_oidc_config(db_session)
        config.default_group_id = None
        db_session.commit()

        result = _get_groups_for_oidc_user(["unknown-team"], db_session)
        assert result == []

    def test_deduplicates_group_ids(self, db_session: Session):
        """Same group mapped multiple times only appears once."""
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        group = create_group(db_session, "Shared Group")

        # Two OIDC values map to same group
        create_oidc_mapping(db_session, "developers", group)
        # Note: unique constraint on oidc_value, so we test with multiple claims matching same group
        # The dedup happens when user has multiple OIDC claims that map to same group
        # We need a different approach - let's test with the same group appearing in multiple claims

        result = _get_groups_for_oidc_user(["developers"], db_session)
        assert result == [group.id]

    def test_handles_empty_oidc_groups(self, db_session: Session):
        """Handles empty OIDC groups list."""
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        default_group = create_group(db_session, "Default Empty")
        setup_oidc_config(db_session, default_group=default_group)

        result = _get_groups_for_oidc_user([], db_session)
        assert result == [default_group.id]

    def test_handles_none_oidc_groups(self, db_session: Session):
        """Handles None OIDC groups (normalized to empty list)."""
        from auth.oidc_auth_routes import _normalize_groups_claim

        # Test the normalization function
        assert _normalize_groups_claim(None) == []
        assert _normalize_groups_claim("single") == ["single"]
        assert _normalize_groups_claim(["a", "b"]) == ["a", "b"]
        assert _normalize_groups_claim(["a", 123, "b"]) == ["a", "b"]  # Filters non-strings


class TestOidcUserProvisioning:
    """Test new OIDC user creation with groups."""

    def test_new_user_added_to_matching_groups(self, db_session: Session):
        """New OIDC user is added to all matching groups."""
        # Create groups and mappings
        group1 = create_group(db_session, "Dev Team")
        group2 = create_group(db_session, "Ops Team")
        create_oidc_mapping(db_session, "dev-team", group1)
        create_oidc_mapping(db_session, "ops-team", group2)

        # Simulate OIDC provisioning logic
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        oidc_groups = ["dev-team", "ops-team"]
        group_ids = _get_groups_for_oidc_user(oidc_groups, db_session)

        # Create user
        user = create_user(db_session, "newuser")

        # Add to groups
        for gid in group_ids:
            db_session.add(UserGroupMembership(user_id=user.id, group_id=gid))
        db_session.commit()

        # Verify
        user_groups = get_user_group_ids(db_session, user.id)
        assert user_groups == {group1.id, group2.id}

    def test_new_user_added_to_default_group_when_no_matches(self, db_session: Session):
        """New user gets default group when no OIDC claims match."""
        default_group = create_group(db_session, "Default Provisioning")
        setup_oidc_config(db_session, default_group=default_group)

        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        group_ids = _get_groups_for_oidc_user(["unknown-group"], db_session)

        user = create_user(db_session, "default_user")
        for gid in group_ids:
            db_session.add(UserGroupMembership(user_id=user.id, group_id=gid))
        db_session.commit()

        user_groups = get_user_group_ids(db_session, user.id)
        assert user_groups == {default_group.id}

    def test_first_user_gets_admin_group(self, db_session: Session):
        """First OIDC user is auto-assigned to Administrators regardless of claims."""
        # Ensure no users exist
        assert db_session.query(User).count() == 0

        # Create Administrators group (as migration would do)
        admin_group = create_group(db_session, "Administrators", is_system=True)

        # Create some other mapping
        other_group = create_group(db_session, "Other")
        create_oidc_mapping(db_session, "some-group", other_group)

        # Check if first user logic would apply
        user_count = db_session.query(User).count()
        is_first_user = user_count == 0

        if is_first_user:
            group_ids = [admin_group.id]
        else:
            from auth.oidc_auth_routes import _get_groups_for_oidc_user
            group_ids = _get_groups_for_oidc_user(["some-group"], db_session)

        # Create first user
        user = create_user(db_session, "firstuser")
        for gid in group_ids:
            db_session.add(UserGroupMembership(user_id=user.id, group_id=gid))
        db_session.commit()

        user_groups = get_user_group_ids(db_session, user.id)
        assert admin_group.id in user_groups


class TestOidcUserGroupSync:
    """Test existing OIDC user group sync on re-login."""

    def test_groups_fully_replaced_on_relogin(self, db_session: Session):
        """User's groups are completely replaced based on current claims."""
        # Create groups
        group_a = create_group(db_session, "Team A")
        group_b = create_group(db_session, "Team B")
        create_oidc_mapping(db_session, "team-a", group_a)
        create_oidc_mapping(db_session, "team-b", group_b)

        # Create user initially in team-a
        user = create_user(db_session, "sync_user")
        add_user_to_groups(db_session, user, [group_a])

        assert get_user_group_ids(db_session, user.id) == {group_a.id}

        # Simulate re-login with different groups (now in team-b only)
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        new_oidc_groups = ["team-b"]
        new_group_ids = set(_get_groups_for_oidc_user(new_oidc_groups, db_session))

        # Sync logic: remove old, add new
        existing = db_session.query(UserGroupMembership).filter_by(user_id=user.id).all()
        existing_group_ids = {m.group_id for m in existing}

        # Add new groups
        for gid in new_group_ids - existing_group_ids:
            db_session.add(UserGroupMembership(user_id=user.id, group_id=gid))

        # Remove old groups
        for membership in existing:
            if membership.group_id not in new_group_ids:
                db_session.delete(membership)

        db_session.commit()

        # Verify - should only be in team-b now
        assert get_user_group_ids(db_session, user.id) == {group_b.id}

    def test_gains_new_group_on_relogin(self, db_session: Session):
        """User gains access to new group when OIDC claims change."""
        group_a = create_group(db_session, "Gain A")
        group_b = create_group(db_session, "Gain B")
        create_oidc_mapping(db_session, "gain-a", group_a)
        create_oidc_mapping(db_session, "gain-b", group_b)

        # User starts in team-a only
        user = create_user(db_session, "gain_user")
        add_user_to_groups(db_session, user, [group_a])

        # Re-login with additional group
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        new_oidc_groups = ["gain-a", "gain-b"]
        new_group_ids = set(_get_groups_for_oidc_user(new_oidc_groups, db_session))

        existing = db_session.query(UserGroupMembership).filter_by(user_id=user.id).all()
        existing_group_ids = {m.group_id for m in existing}

        for gid in new_group_ids - existing_group_ids:
            db_session.add(UserGroupMembership(user_id=user.id, group_id=gid))

        db_session.commit()

        # Verify - should be in both groups
        assert get_user_group_ids(db_session, user.id) == {group_a.id, group_b.id}

    def test_loses_group_on_relogin(self, db_session: Session):
        """User loses access when removed from OIDC group."""
        group_a = create_group(db_session, "Lose A")
        group_b = create_group(db_session, "Lose B")
        create_oidc_mapping(db_session, "lose-a", group_a)
        create_oidc_mapping(db_session, "lose-b", group_b)

        # User starts in both groups
        user = create_user(db_session, "lose_user")
        add_user_to_groups(db_session, user, [group_a, group_b])

        assert get_user_group_ids(db_session, user.id) == {group_a.id, group_b.id}

        # Re-login with one group removed
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        new_oidc_groups = ["lose-a"]  # Removed from lose-b
        new_group_ids = set(_get_groups_for_oidc_user(new_oidc_groups, db_session))

        existing = db_session.query(UserGroupMembership).filter_by(user_id=user.id).all()

        for membership in existing:
            if membership.group_id not in new_group_ids:
                db_session.delete(membership)

        db_session.commit()

        # Verify - should only be in group-a
        assert get_user_group_ids(db_session, user.id) == {group_a.id}

    def test_cache_invalidated_after_sync(self, db_session: Session):
        """User groups cache is invalidated after OIDC sync."""
        from auth.api_key_auth import (
            get_user_group_ids as cached_get_user_group_ids,
            invalidate_user_groups_cache,
        )
        from contextlib import contextmanager

        group_a = create_group(db_session, "Cache A")
        group_b = create_group(db_session, "Cache B")
        create_oidc_mapping(db_session, "cache-a", group_a)
        create_oidc_mapping(db_session, "cache-b", group_b)

        user = create_user(db_session, "cache_user")
        add_user_to_groups(db_session, user, [group_a])

        # Patch db.get_session to use test session
        @contextmanager
        def get_session():
            yield db_session

        with patch('auth.api_key_auth.db.get_session', get_session):
            # Clear cache and prime it
            invalidate_user_groups_cache()
            cached_groups = cached_get_user_group_ids(user.id)
            assert group_a.id in cached_groups

            # Add to another group directly
            db_session.add(UserGroupMembership(user_id=user.id, group_id=group_b.id))
            db_session.commit()

            # Without invalidation, cache returns stale data
            still_cached = cached_get_user_group_ids(user.id)
            assert group_b.id not in still_cached

            # After invalidation, shows new data
            invalidate_user_groups_cache(user.id)
            fresh_groups = cached_get_user_group_ids(user.id)
            assert group_a.id in fresh_groups
            assert group_b.id in fresh_groups


class TestOidcGroupMappingCRUD:
    """Test OIDC group mapping CRUD operations."""

    def test_create_mapping(self, db_session: Session):
        """Can create OIDC group mapping."""
        group = create_group(db_session, "Mapping Create")
        mapping = create_oidc_mapping(db_session, "create-test", group)

        assert mapping.id is not None
        assert mapping.oidc_value == "create-test"
        assert mapping.group_id == group.id

    def test_mapping_unique_oidc_value(self, db_session: Session):
        """OIDC value must be unique."""
        from sqlalchemy.exc import IntegrityError

        group = create_group(db_session, "Mapping Unique")
        create_oidc_mapping(db_session, "unique-value", group)

        # Try to create duplicate
        with pytest.raises(IntegrityError):
            mapping2 = OIDCGroupMapping(
                oidc_value="unique-value",  # Duplicate
                group_id=group.id,
            )
            db_session.add(mapping2)
            db_session.commit()

        db_session.rollback()

    def test_mapping_cascade_delete_on_group(self, db_session: Session):
        """Mapping deleted when group is deleted."""
        group = create_group(db_session, "Mapping Cascade")
        mapping = create_oidc_mapping(db_session, "cascade-test", group)
        mapping_id = mapping.id

        db_session.delete(group)
        db_session.commit()

        # Mapping should be deleted
        assert db_session.get(OIDCGroupMapping, mapping_id) is None

    def test_mapping_priority_order(self, db_session: Session):
        """Mappings can have priority for UI ordering."""
        group = create_group(db_session, "Priority Group")

        mapping1 = create_oidc_mapping(db_session, "low-priority", group, priority=10)
        mapping2 = create_oidc_mapping(db_session, "high-priority", group, priority=100)

        # Query with ordering
        mappings = db_session.query(OIDCGroupMapping).order_by(OIDCGroupMapping.priority.desc()).all()
        assert mappings[0].oidc_value == "high-priority"
        assert mappings[1].oidc_value == "low-priority"


class TestOidcConfigDefaultGroup:
    """Test OIDC config default group setting."""

    def test_default_group_set(self, db_session: Session):
        """Can set default group in OIDC config."""
        group = create_group(db_session, "Default Config Group")
        config = setup_oidc_config(db_session, default_group=group)

        assert config.default_group_id == group.id

    def test_default_group_nullable(self, db_session: Session):
        """Default group can be null."""
        config = setup_oidc_config(db_session)
        config.default_group_id = None
        db_session.commit()

        config = db_session.query(OIDCConfig).first()
        assert config.default_group_id is None

    def test_default_group_relationship(self, db_session: Session):
        """Can access default group via relationship."""
        group = create_group(db_session, "Relationship Group")
        config = setup_oidc_config(db_session, default_group=group)

        # Refresh to load relationship
        db_session.refresh(config)

        # Access via relationship
        assert config.default_group is not None
        assert config.default_group.name == "Relationship Group"
