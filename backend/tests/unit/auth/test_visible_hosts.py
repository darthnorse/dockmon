"""Host-visibility resolver: user/api-key -> groups -> union of tag scopes -> hosts.

Contract: None = unrestricted (skip filtering); set() = sees nothing; non-empty = filter.
A group with zero scope rows is unrestricted, and any unrestricted group makes the
whole principal unrestricted.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from auth.api_key_auth import (
    filter_visible_hosts,
    get_visible_host_ids_for_auth,
    get_visible_host_ids_for_groups,
    invalidate_group_tag_scopes_cache,
)
from auth.custom_groups_routes import delete_group
from database import CustomGroup, GroupTagScope, Tag, TagAssignment, User, UserGroupMembership


def _tag(session: Session, name: str) -> Tag:
    tag = Tag(id=str(uuid.uuid4()), name=name)
    session.add(tag)
    session.flush()
    return tag


def _group(session: Session, name: str, *tags: Tag) -> CustomGroup:
    group = CustomGroup(name=name)
    session.add(group)
    session.flush()
    for tag in tags:
        session.add(GroupTagScope(group_id=group.id, tag_id=tag.id))
    session.flush()
    return group


def _tag_host(session: Session, host_id: str, tag: Tag) -> None:
    session.add(TagAssignment(tag_id=tag.id, subject_type="host", subject_id=host_id))
    session.flush()


def _user(session: Session, name: str, *groups: CustomGroup) -> User:
    user = User(username=name, password_hash="x", role="user", auth_provider="local")
    session.add(user)
    session.flush()
    for group in groups:
        session.add(UserGroupMembership(user_id=user.id, group_id=group.id))
    session.commit()
    return user


@pytest.fixture
def fleet(patch_db_session: Session):
    s = patch_db_session
    dev, test = _tag(s, "dev"), _tag(s, "test")
    _tag_host(s, "h-dev-1", dev)
    _tag_host(s, "h-dev-2", dev)
    _tag_host(s, "h-test-1", test)
    _tag_host(s, "h-both", dev)
    _tag_host(s, "h-both", test)
    s.commit()
    return {"session": s, "dev": dev, "test": test}


class TestGroupResolution:
    def test_group_without_scope_rows_is_unrestricted(self, fleet):
        group = _group(fleet["session"], "Admins")
        assert get_visible_host_ids_for_groups([group.id]) is None

    def test_scoped_group_sees_tagged_hosts(self, fleet):
        group = _group(fleet["session"], "Dev", fleet["dev"])
        assert get_visible_host_ids_for_groups([group.id]) == {"h-dev-1", "h-dev-2", "h-both"}

    def test_multiple_scoped_groups_union(self, fleet):
        dev = _group(fleet["session"], "Dev", fleet["dev"])
        test = _group(fleet["session"], "Test", fleet["test"])
        assert get_visible_host_ids_for_groups([dev.id, test.id]) == {
            "h-dev-1", "h-dev-2", "h-test-1", "h-both",
        }

    def test_any_unscoped_group_makes_principal_unrestricted(self, fleet):
        dev = _group(fleet["session"], "Dev", fleet["dev"])
        admins = _group(fleet["session"], "Admins")
        assert get_visible_host_ids_for_groups([dev.id, admins.id]) is None

    def test_no_groups_sees_nothing(self, fleet):
        assert get_visible_host_ids_for_groups([]) == set()

    def test_scope_on_tag_no_host_carries_sees_nothing(self, fleet):
        orphan_tag = _tag(fleet["session"], "unused")
        group = _group(fleet["session"], "Lonely", orphan_tag)
        assert get_visible_host_ids_for_groups([group.id]) == set()

    def test_group_created_after_cache_load_is_unrestricted_without_invalidation(self, fleet):
        scoped = _group(fleet["session"], "Dev", fleet["dev"])
        assert get_visible_host_ids_for_groups([scoped.id]) is not None  # cache is now loaded
        newcomer = _group(fleet["session"], "New")
        fleet["session"].commit()
        assert get_visible_host_ids_for_groups([newcomer.id]) is None


class TestAuthResolution:
    def test_session_user_gets_union_of_groups(self, fleet):
        dev = _group(fleet["session"], "Dev", fleet["dev"])
        test = _group(fleet["session"], "Test", fleet["test"])
        user = _user(fleet["session"], "alice", dev, test)
        visible = get_visible_host_ids_for_auth({"auth_type": "session", "user_id": user.id})
        assert visible == {"h-dev-1", "h-dev-2", "h-test-1", "h-both"}

    def test_orphan_user_sees_nothing(self, fleet):
        user = _user(fleet["session"], "nobody")
        assert get_visible_host_ids_for_auth({"auth_type": "session", "user_id": user.id}) == set()

    def test_session_without_user_id_sees_nothing(self, fleet):
        assert get_visible_host_ids_for_auth({"auth_type": "session"}) == set()

    def test_api_key_uses_its_own_group_not_creators_union(self, fleet):
        dev = _group(fleet["session"], "Dev", fleet["dev"])
        admins = _group(fleet["session"], "Admins")
        creator = _user(fleet["session"], "admin", admins)
        visible = get_visible_host_ids_for_auth({
            "auth_type": "api_key", "group_id": dev.id, "created_by_user_id": creator.id,
        })
        assert visible == {"h-dev-1", "h-dev-2", "h-both"}

    def test_api_key_without_group_sees_nothing(self, fleet):
        assert get_visible_host_ids_for_auth({"auth_type": "api_key", "group_id": None}) == set()

    def test_api_key_in_unscoped_group_is_unrestricted(self, fleet):
        admins = _group(fleet["session"], "Admins")
        assert get_visible_host_ids_for_auth({"auth_type": "api_key", "group_id": admins.id}) is None


class TestFilterVisibleHosts:
    def test_none_passes_everything_through(self):
        items = [{"host_id": "a"}, {"host_id": "b"}]
        assert filter_visible_hosts(items, None, lambda i: i["host_id"]) is items

    def test_empty_set_filters_everything(self):
        assert filter_visible_hosts([{"host_id": "a"}], set(), lambda i: i["host_id"]) == []

    def test_keeps_only_visible(self):
        items = [{"host_id": "a"}, {"host_id": "b"}, {"host_id": "c"}]
        assert filter_visible_hosts(items, {"a", "c"}, lambda i: i["host_id"]) == [
            {"host_id": "a"}, {"host_id": "c"},
        ]


class TestScopeCacheInvalidation:
    """Scope rows are cached until invalidate_group_tag_scopes_cache(); host tag
    assignments are never cached."""

    def test_new_scope_row_is_stale_until_invalidated(self, fleet):
        s = fleet["session"]
        group = _group(s, "Grp")
        assert get_visible_host_ids_for_groups([group.id]) is None

        s.add(GroupTagScope(group_id=group.id, tag_id=fleet["dev"].id))
        s.commit()
        assert get_visible_host_ids_for_groups([group.id]) is None

        invalidate_group_tag_scopes_cache()
        assert get_visible_host_ids_for_groups([group.id]) == {"h-dev-1", "h-dev-2", "h-both"}

    def test_deleting_last_scope_row_makes_group_unrestricted_after_invalidation(self, fleet):
        s = fleet["session"]
        group = _group(s, "Grp", fleet["dev"])
        s.commit()
        assert get_visible_host_ids_for_groups([group.id]) == {"h-dev-1", "h-dev-2", "h-both"}

        s.query(GroupTagScope).filter_by(group_id=group.id).delete()
        s.commit()
        assert get_visible_host_ids_for_groups([group.id]) == {"h-dev-1", "h-dev-2", "h-both"}

        invalidate_group_tag_scopes_cache()
        assert get_visible_host_ids_for_groups([group.id]) is None

    def test_host_retagging_is_visible_without_invalidation(self, fleet):
        s = fleet["session"]
        group = _group(s, "Grp", fleet["dev"])
        s.commit()
        assert "h-new" not in get_visible_host_ids_for_groups([group.id])

        _tag_host(s, "h-new", fleet["dev"])
        s.query(TagAssignment).filter_by(subject_id="h-dev-1").delete()
        s.commit()

        assert get_visible_host_ids_for_groups([group.id]) == {"h-dev-2", "h-both", "h-new"}

    @pytest.mark.asyncio
    async def test_group_delete_route_invalidates_scope_cache(self, fleet):
        """custom_groups.id has no AUTOINCREMENT, so SQLite reuses the highest deleted
        rowid: without invalidation the next group created inherits the dead scope."""
        s = fleet["session"]
        doomed = _group(s, "Doomed", fleet["dev"])
        s.commit()
        assert get_visible_host_ids_for_groups([doomed.id]) == {"h-dev-1", "h-dev-2", "h-both"}

        admin = _user(s, "admin")
        with patch("auth.custom_groups_routes._refresh_ws_auth_state", AsyncMock()):
            await delete_group(doomed.id, current_user={"auth_type": "session", "user_id": admin.id, "username": "admin"})

        reborn = _group(s, "Reborn")
        s.commit()
        assert reborn.id == doomed.id
        assert get_visible_host_ids_for_groups([reborn.id]) is None
