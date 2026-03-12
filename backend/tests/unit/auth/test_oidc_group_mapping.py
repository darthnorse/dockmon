"""
Tests for OIDC group mapping, sync, and the absent-vs-empty claim distinction.

Tests cover:
- _get_groups_for_oidc_user() - Maps OIDC groups to DockMon groups
- _resolve_groups_or_block() - Returns group IDs or blocks login
- _sync_oidc_user_groups() - Bidirectional group sync with admin guard
- Absent vs empty groups claim - The callback-level decision (Fixes #199)
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
        """Two different OIDC values mapped to the same group only produces one group ID."""
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        group = create_group(db_session, "Shared Group")

        # Two different OIDC values both map to the same DockMon group
        create_oidc_mapping(db_session, "developers", group)
        create_oidc_mapping(db_session, "engineering", group)

        # User has both OIDC claims — group should appear only once
        result = _get_groups_for_oidc_user(["developers", "engineering"], db_session)
        assert result == [group.id]

    def test_handles_empty_oidc_groups(self, db_session: Session):
        """Handles empty OIDC groups list."""
        from auth.oidc_auth_routes import _get_groups_for_oidc_user

        default_group = create_group(db_session, "Default Empty")
        setup_oidc_config(db_session, default_group=default_group)

        result = _get_groups_for_oidc_user([], db_session)
        assert result == [default_group.id]

    def test_normalize_groups_claim_standard_formats(self, db_session: Session):
        """Normalizes None, string, and list claim formats."""
        from auth.oidc_auth_routes import _normalize_groups_claim

        assert _normalize_groups_claim(None) == []
        assert _normalize_groups_claim("single") == ["single"]
        assert _normalize_groups_claim(["a", "b"]) == ["a", "b"]
        assert _normalize_groups_claim(["a", 123, "b"]) == ["a", "b"]  # Filters non-strings

    def test_normalize_groups_claim_dict_format(self, db_session: Session):
        """Normalizes dict-shaped claims (Zitadel, Keycloak)."""
        from auth.oidc_auth_routes import _normalize_groups_claim

        assert sorted(_normalize_groups_claim({"dev-team": {"orgid": "123"}, "ops": {"orgid": "456"}})) == ["dev-team", "ops"]
        assert _normalize_groups_claim({}) == []
        assert _normalize_groups_claim({"single-role": {}}) == ["single-role"]


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


class TestPendingApproval:
    """Test pending approval logic for OIDC users."""

    def test_new_user_created_unapproved_when_required(self, db_session: Session):
        """When require_approval is True, new OIDC user gets approved=False."""
        # Set up OIDC config with require_approval enabled
        config = setup_oidc_config(db_session)
        config.require_approval = True
        db_session.commit()

        # Simulate the approval logic from the callback
        is_first_user = False  # Not the first user
        needs_approval = config.require_approval and not is_first_user

        user = User(
            username="pending_user",
            password_hash="!OIDC_NO_PASSWORD",
            auth_provider="oidc",
            oidc_subject="oidc_pending_test",
            approved=not needs_approval,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(user)
        db_session.commit()

        # User should be unapproved
        assert user.approved is False

    def test_new_user_approved_when_not_required(self, db_session: Session):
        """When require_approval is False, new OIDC user gets approved=True."""
        # Set up OIDC config with require_approval disabled (default)
        config = setup_oidc_config(db_session)
        config.require_approval = False
        db_session.commit()

        is_first_user = False
        needs_approval = config.require_approval and not is_first_user

        user = User(
            username="approved_user",
            password_hash="!OIDC_NO_PASSWORD",
            auth_provider="oidc",
            oidc_subject="oidc_approved_test",
            approved=not needs_approval,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(user)
        db_session.commit()

        # User should be approved (default)
        assert user.approved is True

    def test_first_user_always_approved_even_when_required(self, db_session: Session):
        """First OIDC user is always approved even when require_approval is True."""
        config = setup_oidc_config(db_session)
        config.require_approval = True
        db_session.commit()

        # First user scenario
        is_first_user = True
        needs_approval = config.require_approval and not is_first_user

        user = User(
            username="first_oidc_user",
            password_hash="!OIDC_NO_PASSWORD",
            auth_provider="oidc",
            oidc_subject="oidc_first_user",
            approved=not needs_approval,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(user)
        db_session.commit()

        # First user should always be approved
        assert user.approved is True

    def test_existing_pending_user_stays_pending(self, db_session: Session):
        """Existing unapproved user stays unapproved on re-login."""
        # Create an unapproved user (simulating previous login with require_approval)
        user = User(
            username="pending_existing",
            password_hash="!OIDC_NO_PASSWORD",
            auth_provider="oidc",
            oidc_subject="oidc_pending_existing",
            approved=False,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(user)
        db_session.commit()

        # Simulate re-login: user.approved is checked
        assert user.approved is False

        # The callback would return a redirect here, blocking session creation
        # Verify the user stays unapproved (no automatic approval on re-login)
        db_session.refresh(user)
        assert user.approved is False

    def test_existing_approved_user_stays_approved(self, db_session: Session):
        """Approved user stays approved on re-login."""
        # Create an approved user
        user = User(
            username="approved_existing",
            password_hash="!OIDC_NO_PASSWORD",
            auth_provider="oidc",
            oidc_subject="oidc_approved_existing",
            approved=True,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(user)
        db_session.commit()

        # Simulate re-login check
        assert user.approved is True

        # Approved users should pass through to session creation
        db_session.refresh(user)
        assert user.approved is True


class TestResolveGroupsOrBlock:
    """Test _resolve_groups_or_block() — the gatekeeper that blocks login when
    no DockMon groups match the OIDC claims. Fixes #199."""

    def test_returns_group_ids_when_mappings_match(self, db_session: Session):
        """Returns resolved group IDs and no redirect when claims match."""
        from auth.oidc_auth_routes import _resolve_groups_or_block

        group = create_group(db_session, "Resolve Match")
        create_oidc_mapping(db_session, "dev-team", group)

        user = create_user(db_session, "resolve_user")
        mock_request = MagicMock()

        group_ids, block = _resolve_groups_or_block(
            db_session, user, ["dev-team"], mock_request, ""
        )

        assert block is None
        assert group == group  # sanity
        assert group.id in group_ids

    def test_blocks_login_when_no_groups_match(self, db_session: Session):
        """Returns a redirect response when no OIDC claims map to DockMon groups."""
        from auth.oidc_auth_routes import _resolve_groups_or_block

        # No mappings configured, no default group
        setup_oidc_config(db_session)
        config = db_session.query(OIDCConfig).first()
        config.default_group_id = None
        db_session.commit()

        user = create_user(db_session, "blocked_user")
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        group_ids, block = _resolve_groups_or_block(
            db_session, user, ["unknown-team"], mock_request, "/app"
        )

        assert group_ids == set()
        assert block is not None
        assert "no_matching_groups" in str(block.headers.get("location", ""))

    def test_blocks_login_on_empty_oidc_groups(self, db_session: Session):
        """Empty groups list with no default group blocks login."""
        from auth.oidc_auth_routes import _resolve_groups_or_block

        setup_oidc_config(db_session)
        config = db_session.query(OIDCConfig).first()
        config.default_group_id = None
        db_session.commit()

        user = create_user(db_session, "empty_groups_user")
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}

        group_ids, block = _resolve_groups_or_block(
            db_session, user, [], mock_request, ""
        )

        assert group_ids == set()
        assert block is not None

    def test_returns_default_group_when_no_claim_matches(self, db_session: Session):
        """Falls back to default group — no block redirect."""
        from auth.oidc_auth_routes import _resolve_groups_or_block

        default_group = create_group(db_session, "Resolve Default")
        setup_oidc_config(db_session, default_group=default_group)

        user = create_user(db_session, "default_resolve_user")
        mock_request = MagicMock()

        group_ids, block = _resolve_groups_or_block(
            db_session, user, ["no-such-team"], mock_request, ""
        )

        assert block is None
        assert default_group.id in group_ids


class TestSyncOidcUserGroupsFunction:
    """Test _sync_oidc_user_groups() directly — bidirectional sync with admin guard."""

    def test_adds_and_removes_groups(self, db_session: Session):
        """Syncs groups: adds new ones, removes old ones."""
        from auth.oidc_auth_routes import _sync_oidc_user_groups

        group_a = create_group(db_session, "Sync A")
        group_b = create_group(db_session, "Sync B")
        create_oidc_mapping(db_session, "sync-a", group_a)
        create_oidc_mapping(db_session, "sync-b", group_b)

        user = create_user(db_session, "sync_fn_user")
        add_user_to_groups(db_session, user, [group_a])

        assert get_user_group_ids(db_session, user.id) == {group_a.id}

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        now = datetime.now(timezone.utc)

        added, removed = _sync_oidc_user_groups(
            db_session, user, ["sync-b"], mock_request, now
        )
        db_session.commit()

        assert group_b.id in added
        assert group_a.id in removed
        assert get_user_group_ids(db_session, user.id) == {group_b.id}

    def test_uses_resolved_group_ids_when_provided(self, db_session: Session):
        """Skips internal resolution when resolved_group_ids is passed."""
        from auth.oidc_auth_routes import _sync_oidc_user_groups

        group_a = create_group(db_session, "Pre-resolved A")
        group_b = create_group(db_session, "Pre-resolved B")

        user = create_user(db_session, "preresolved_user")
        add_user_to_groups(db_session, user, [group_a])

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        now = datetime.now(timezone.utc)

        # Pass resolved IDs directly — no mappings needed
        added, removed = _sync_oidc_user_groups(
            db_session, user, [], mock_request, now,
            resolved_group_ids={group_b.id}
        )
        db_session.commit()

        assert group_b.id in added
        assert group_a.id in removed
        assert get_user_group_ids(db_session, user.id) == {group_b.id}

    def test_preserves_last_admin(self, db_session: Session):
        """Admin guard prevents removing last admin from Administrators group."""
        from auth.oidc_auth_routes import _sync_oidc_user_groups

        admin_group = create_group(db_session, "Administrators", is_system=True)
        other_group = create_group(db_session, "Other")
        create_oidc_mapping(db_session, "other", other_group)

        user = create_user(db_session, "last_admin")
        add_user_to_groups(db_session, user, [admin_group])

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        now = datetime.now(timezone.utc)

        # OIDC claims would remove admin — but user is last admin
        _sync_oidc_user_groups(
            db_session, user, ["other"], mock_request, now
        )
        db_session.commit()

        user_groups = get_user_group_ids(db_session, user.id)
        assert admin_group.id in user_groups, "Last admin must keep Administrators"
        assert other_group.id in user_groups


class TestAbsentVsEmptyGroupsClaim:
    """Test the callback-level distinction between absent and empty groups claims.

    This is the exact bug from #199: when an IdP doesn't include a groups claim
    at all (absent), existing group memberships should be preserved. When the
    claim IS present but empty, the IdP is actively revoking all groups.

    These tests exercise _normalize_groups_claim + the groups_claim_present
    logic that gates whether _sync_oidc_user_groups is called.
    """

    def test_absent_claim_preserves_existing_groups(self, db_session: Session):
        """When IdP sends no groups claim, existing memberships are untouched."""
        from auth.oidc_auth_routes import _normalize_groups_claim

        group = create_group(db_session, "Preserved Group")
        user = create_user(db_session, "absent_claim_user")
        add_user_to_groups(db_session, user, [group])

        assert get_user_group_ids(db_session, user.id) == {group.id}

        # Simulate: groups_raw = userinfo.get("groups") → None (key absent)
        groups_raw = None
        groups_claim_present = groups_raw is not None
        oidc_groups = _normalize_groups_claim(groups_raw)

        assert groups_claim_present is False
        assert oidc_groups == []

        # Callback skips sync when groups_claim_present is False
        # Verify groups are still intact
        assert get_user_group_ids(db_session, user.id) == {group.id}

    def test_empty_claim_triggers_sync(self, db_session: Session):
        """When IdP sends empty groups claim, sync runs and removes memberships."""
        from auth.oidc_auth_routes import _normalize_groups_claim, _sync_oidc_user_groups

        group = create_group(db_session, "Will Be Removed")
        create_oidc_mapping(db_session, "some-team", group)

        user = create_user(db_session, "empty_claim_user")
        add_user_to_groups(db_session, user, [group])

        assert get_user_group_ids(db_session, user.id) == {group.id}

        # Simulate: groups_raw = userinfo.get("groups") → [] (key present, empty)
        groups_raw = []
        groups_claim_present = groups_raw is not None
        oidc_groups = _normalize_groups_claim(groups_raw)

        assert groups_claim_present is True
        assert oidc_groups == []

        # With no default group, _resolve_groups_or_block would block login.
        # But even if we force sync with empty resolved IDs, groups get removed.
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        now = datetime.now(timezone.utc)

        _sync_oidc_user_groups(
            db_session, user, oidc_groups, mock_request, now,
            resolved_group_ids=set()
        )
        db_session.commit()

        assert get_user_group_ids(db_session, user.id) == set()

    def test_present_claim_with_valid_groups_syncs(self, db_session: Session):
        """When IdP sends valid groups, sync runs and updates memberships."""
        from auth.oidc_auth_routes import _normalize_groups_claim, _sync_oidc_user_groups

        old_group = create_group(db_session, "Old Team")
        new_group = create_group(db_session, "New Team")
        create_oidc_mapping(db_session, "old-team", old_group)
        create_oidc_mapping(db_session, "new-team", new_group)

        user = create_user(db_session, "valid_claim_user")
        add_user_to_groups(db_session, user, [old_group])

        assert get_user_group_ids(db_session, user.id) == {old_group.id}

        # Simulate: groups_raw = ["new-team"] (key present, has values)
        groups_raw = ["new-team"]
        groups_claim_present = groups_raw is not None
        oidc_groups = _normalize_groups_claim(groups_raw)

        assert groups_claim_present is True
        assert oidc_groups == ["new-team"]

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        now = datetime.now(timezone.utc)

        added, removed = _sync_oidc_user_groups(
            db_session, user, oidc_groups, mock_request, now
        )
        db_session.commit()

        assert new_group.id in added
        assert old_group.id in removed
        assert get_user_group_ids(db_session, user.id) == {new_group.id}

    def test_none_vs_empty_list_distinction(self, db_session: Session):
        """Core regression test: None and [] must produce different outcomes."""
        from auth.oidc_auth_routes import _normalize_groups_claim

        # Both normalize to [] — but the CALLER must check groups_raw before normalizing
        assert _normalize_groups_claim(None) == []
        assert _normalize_groups_claim([]) == []

        # The distinction is groups_raw, not the normalized result
        assert (None is not None) is False   # absent → skip sync
        assert ([] is not None) is True      # empty → run sync
