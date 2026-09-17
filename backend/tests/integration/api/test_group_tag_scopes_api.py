"""GET/PUT /api/v2/groups/{id}/tag-scopes and the WebSocket refresh wiring.

Every route that can change what a user may see (scope rows, memberships, user
edits/deletes, host re-tagging, OIDC membership sync) must invalidate the right
cache and refresh already-open WebSocket connections.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import main as main_module
from auth import custom_groups_routes, oidc_auth_routes
from auth.api_key_auth import get_visible_host_ids_for_groups
from auth.capabilities import ALL_CAPABILITIES
from database import ApiKey, CustomGroup, DockerHostDB, GroupPermission, GroupTagScope, Tag, TagAssignment, User, UserGroupMembership
from main import app
from models.docker_models import DockerHost


def _group(session, name, caps=ALL_CAPABILITIES):
    group = CustomGroup(name=name, description="t")
    session.add(group)
    session.flush()
    for cap in caps:
        session.add(GroupPermission(group_id=group.id, capability=cap, allowed=True))
    session.flush()
    return group


def _api_key(session, username, group):
    user = User(username=username, password_hash="$2b$12$test_hash_not_real", created_at=datetime.now(timezone.utc))
    session.add(user)
    session.flush()
    raw = f"dockmon_{secrets.token_hex(16)}"
    session.add(ApiKey(created_by_user_id=user.id, group_id=group.id, name=f"{username}-key",
                       key_hash=hashlib.sha256(raw.encode()).hexdigest(), key_prefix=raw[:12],
                       created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    session.commit()
    return raw, user


def _tag(session, name):
    tag = Tag(id=str(uuid.uuid4()), name=name)
    session.add(tag)
    session.flush()
    return tag


class Caller:
    def __init__(self, client, key):
        self.client, self.headers = client, {"Authorization": f"Bearer {key}"}

    def __getattr__(self, method):
        return lambda url, **kw: getattr(self.client, method)(url, headers=self.headers, **kw)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def world(db_session, client):
    admins = _group(db_session, "Administrators")
    viewers = _group(db_session, "Viewers", caps=["hosts.view"])
    scoped = _group(db_session, "Scoped")
    admin_key, admin_user = _api_key(db_session, "admin", admins)
    viewer_key, _ = _api_key(db_session, "viewer", viewers)
    dev, test = _tag(db_session, "dev"), _tag(db_session, "test")
    db_session.add(TagAssignment(tag_id=dev.id, subject_type="host", subject_id="h1"))
    db_session.add(DockerHostDB(id="h1", name="Dev Host", url="tcp://h1:2376"))
    member = User(username="member", password_hash="$2b$12$test_hash_not_real", created_at=datetime.now(timezone.utc))
    db_session.add(member)
    db_session.flush()
    db_session.add(UserGroupMembership(user_id=member.id, group_id=scoped.id))
    # The guardrails refuse any change that would leave no group WITH MEMBERS holding a critical capability
    db_session.add(UserGroupMembership(user_id=admin_user.id, group_id=admins.id))
    db_session.commit()
    return SimpleNamespace(
        admin=Caller(client, admin_key), viewer=Caller(client, viewer_key), admin_user=admin_user,
        scoped=scoped, admins=admins, dev=dev, test=test, member=member, session=db_session,
    )


@pytest.fixture
def ws_spy(monkeypatch):
    spy = SimpleNamespace(
        refresh_all_visible_hosts=AsyncMock(), refresh_visible_hosts_for_user=AsyncMock(),
        refresh_all_capabilities=AsyncMock(), refresh_capabilities_for_user=AsyncMock(),
        disconnect_user=AsyncMock(),
    )
    monkeypatch.setattr(main_module.monitor, "manager", spy)
    return spy


@pytest.mark.integration
class TestTagScopesEndpoints:
    def test_get_is_empty_for_an_unscoped_group(self, world):
        response = world.admin.get(f"/api/v2/groups/{world.scoped.id}/tag-scopes")
        assert response.status_code == 200
        assert response.json() == {"group_id": world.scoped.id, "tag_ids": []}

    def test_put_replaces_and_reads_back(self, world, ws_spy):
        body = {"tag_ids": [world.dev.id, world.test.id]}
        assert world.admin.put(f"/api/v2/groups/{world.scoped.id}/tag-scopes", json=body).status_code == 200
        assert set(world.admin.get(f"/api/v2/groups/{world.scoped.id}/tag-scopes").json()["tag_ids"]) == set(body["tag_ids"])

        assert world.admin.put(f"/api/v2/groups/{world.scoped.id}/tag-scopes", json={"tag_ids": [world.dev.id]}).status_code == 200
        assert world.admin.get(f"/api/v2/groups/{world.scoped.id}/tag-scopes").json()["tag_ids"] == [world.dev.id]
        assert get_visible_host_ids_for_groups([world.scoped.id]) == {"h1"}

    def test_put_empty_makes_the_group_unrestricted(self, world, ws_spy):
        world.admin.put(f"/api/v2/groups/{world.scoped.id}/tag-scopes", json={"tag_ids": [world.dev.id]})
        assert get_visible_host_ids_for_groups([world.scoped.id]) == {"h1"}
        world.admin.put(f"/api/v2/groups/{world.scoped.id}/tag-scopes", json={"tag_ids": []})
        assert get_visible_host_ids_for_groups([world.scoped.id]) is None
        assert world.session.query(GroupTagScope).count() == 0

    def test_unknown_tag_is_400_and_nothing_changes(self, world, ws_spy):
        response = world.admin.put(f"/api/v2/groups/{world.scoped.id}/tag-scopes", json={"tag_ids": [world.dev.id, "nope"]})
        assert response.status_code == 400
        assert world.session.query(GroupTagScope).count() == 0
        ws_spy.refresh_all_visible_hosts.assert_not_awaited()

    def test_unknown_group_is_404(self, world):
        assert world.admin.get("/api/v2/groups/9999/tag-scopes").status_code == 404
        assert world.admin.put("/api/v2/groups/9999/tag-scopes", json={"tag_ids": []}).status_code == 404

    def test_requires_groups_manage(self, world):
        assert world.viewer.get(f"/api/v2/groups/{world.scoped.id}/tag-scopes").status_code == 403
        assert world.viewer.put(f"/api/v2/groups/{world.scoped.id}/tag-scopes", json={"tag_ids": []}).status_code == 403

    def test_put_refreshes_open_sockets(self, world, ws_spy):
        world.admin.put(f"/api/v2/groups/{world.scoped.id}/tag-scopes", json={"tag_ids": [world.dev.id]})
        ws_spy.refresh_all_visible_hosts.assert_awaited()


@pytest.mark.integration
class TestRefreshWiring:
    def test_group_delete_refreshes_everyone(self, world, ws_spy):
        world.session.query(UserGroupMembership).filter_by(group_id=world.scoped.id).delete()
        world.session.commit()
        response = world.admin.delete(f"/api/v2/groups/{world.scoped.id}")
        assert response.status_code == 200, response.text
        ws_spy.refresh_all_capabilities.assert_awaited()
        ws_spy.refresh_all_visible_hosts.assert_awaited()

    def test_add_and_remove_member_refresh_that_user(self, world, ws_spy):
        world.admin.put(f"/api/v2/groups/{world.scoped.id}/tag-scopes", json={"tag_ids": [world.dev.id]})
        ws_spy.refresh_visible_hosts_for_user.reset_mock()
        assert world.admin.post(f"/api/v2/groups/{world.admins.id}/members", json={"user_id": world.member.id}).status_code == 200
        ws_spy.refresh_visible_hosts_for_user.assert_awaited_with(world.member.id)
        ws_spy.refresh_visible_hosts_for_user.reset_mock()
        assert world.admin.delete(f"/api/v2/groups/{world.admins.id}/members/{world.member.id}").status_code == 200
        ws_spy.refresh_visible_hosts_for_user.assert_awaited_with(world.member.id)

    def test_user_put_with_groups_refreshes_that_user(self, world, ws_spy):
        response = world.admin.put(f"/api/v2/users/{world.member.id}", json={"group_ids": [world.admins.id]})
        assert response.status_code == 200, response.text
        ws_spy.refresh_visible_hosts_for_user.assert_awaited_with(world.member.id)

    def test_user_delete_closes_their_sockets(self, world, ws_spy):
        response = world.admin.delete(f"/api/v2/users/{world.member.id}")
        assert response.status_code == 200, response.text
        ws_spy.disconnect_user.assert_awaited_with(world.member.id)

    def test_host_tags_patch_refreshes_everyone(self, world, ws_spy, monkeypatch):
        monkeypatch.setattr(main_module.monitor, "hosts", {"h1": DockerHost(id="h1", name="Dev Host", url="tcp://h1:2376", status="online")})
        response = world.admin.patch("/api/hosts/h1/tags", json={"tags_to_add": ["test"]})
        assert response.status_code == 200, response.text
        ws_spy.refresh_all_visible_hosts.assert_awaited()

    async def test_oidc_membership_sync_refreshes_that_user(self, world, ws_spy):
        await oidc_auth_routes._refresh_user_auth_state(world.member.id)
        ws_spy.refresh_capabilities_for_user.assert_awaited_with(world.member.id)
        ws_spy.refresh_visible_hosts_for_user.assert_awaited_with(world.member.id)

    def test_oidc_login_paths_use_the_refresh_helper(self):
        import inspect
        source = inspect.getsource(oidc_auth_routes)
        assert "invalidate_user_groups_cache(user.id)" not in source
        assert source.count("_refresh_user_auth_state(user.id)") >= 3


@pytest.mark.integration
class TestHostTagsForEditor:
    def test_lists_host_tags_and_scope_only_tags_with_ids(self, world, ws_spy):
        orphan_scope_tag = _tag(world.session, "legacy")
        _tag(world.session, "container-only")
        world.session.add(TagAssignment(tag_id=world.session.query(Tag).filter_by(name="container-only").one().id,
                                        subject_type="container", subject_id="h1:aaa111111111"))
        world.session.add(GroupTagScope(group_id=world.scoped.id, tag_id=orphan_scope_tag.id))
        world.session.commit()

        response = world.admin.get("/api/v2/groups/host-tags")
        assert response.status_code == 200, response.text
        tags = {t["name"]: t for t in response.json()}
        assert set(tags) == {"dev", "legacy"}
        assert tags["dev"]["id"] == world.dev.id
        assert set(tags["dev"]) >= {"id", "name", "color"}

    def test_requires_groups_manage(self, world):
        assert world.viewer.get("/api/v2/groups/host-tags").status_code == 403
