"""
Tests for privilege-escalation guards on user/group management.

Written FIRST (RED phase). These capture the security property that a principal
holding users.manage / groups.manage cannot use it to grant or reach capabilities
it does not itself hold (self-escalation / account takeover).

Covers:
- get_effective_capabilities() - actor's effective capability set (session or API key)
- ensure_no_privilege_escalation() - raises 403 when a target/requested capability
  set exceeds the actor's own capabilities.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def patch_db_for_tests(db_session: Session):
    """Patch db.get_session() in auth modules and reset caches for isolation."""
    from auth.api_key_auth import (
        invalidate_group_permissions_cache,
        invalidate_user_groups_cache,
    )

    invalidate_group_permissions_cache()
    invalidate_user_groups_cache()

    @contextmanager
    def get_session():
        yield db_session

    with patch('auth.api_key_auth.db.get_session', get_session):
        yield

    invalidate_group_permissions_cache()
    invalidate_user_groups_cache()


def _group(db_session, capabilities, name=None):
    from database import CustomGroup, GroupPermission
    group = CustomGroup(name=name or f"G_{uuid.uuid4().hex[:8]}", description="test")
    db_session.add(group)
    db_session.flush()
    for cap in capabilities:
        db_session.add(GroupPermission(group_id=group.id, capability=cap, allowed=True))
    db_session.commit()
    return group


def _user_in_groups(db_session, groups):
    from database import User, UserGroupMembership
    user = User(
        username=f"u_{uuid.uuid4().hex[:8]}",
        password_hash="hash",
        auth_provider="local",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    for g in groups:
        db_session.add(UserGroupMembership(user_id=user.id, group_id=g.id))
    db_session.commit()
    return user


class TestGetEffectiveCapabilities:
    def test_session_user_gets_union_of_all_groups(self, db_session: Session):
        from auth.api_key_auth import get_effective_capabilities
        g1 = _group(db_session, ["containers.view", "users.manage"])
        g2 = _group(db_session, ["hosts.view"])
        user = _user_in_groups(db_session, [g1, g2])

        caps = get_effective_capabilities({"auth_type": "session", "user_id": user.id})

        assert caps == {"containers.view", "users.manage", "hosts.view"}

    def test_api_key_gets_its_single_group_capabilities(self, db_session: Session):
        from auth.api_key_auth import get_effective_capabilities
        g = _group(db_session, ["containers.view", "containers.operate"])

        caps = get_effective_capabilities({"auth_type": "api_key", "group_id": g.id})

        assert caps == {"containers.view", "containers.operate"}

    def test_missing_identity_returns_empty(self, db_session: Session):
        from auth.api_key_auth import get_effective_capabilities
        assert get_effective_capabilities({"auth_type": "session"}) == set()
        assert get_effective_capabilities({"auth_type": "api_key"}) == set()


class TestEnsureNoPrivilegeEscalation:
    def test_raises_when_target_has_capabilities_actor_lacks(self):
        from auth.utils import ensure_no_privilege_escalation
        actor = {"users.manage", "containers.view"}
        target = {"containers.view", "hosts.manage"}  # hosts.manage not held by actor

        with pytest.raises(HTTPException) as exc:
            ensure_no_privilege_escalation(actor, target, "reset this user's password")
        assert exc.value.status_code == 403

    def test_allows_when_target_is_subset(self):
        from auth.utils import ensure_no_privilege_escalation
        actor = {"users.manage", "containers.view", "hosts.manage"}
        target = {"containers.view"}
        # Should not raise
        ensure_no_privilege_escalation(actor, target, "reset this user's password")

    def test_allows_equal_capability_sets(self):
        from auth.utils import ensure_no_privilege_escalation
        caps = {"users.manage", "containers.view"}
        ensure_no_privilege_escalation(caps, set(caps), "assign these groups")
