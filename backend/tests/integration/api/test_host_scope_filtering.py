"""Tag-based host visibility on the primary read surfaces.

Three hosts: h1 carries tag `dev`, h2 carries tag `test`, h3 is untagged.
Principals: unrestricted (group without scope rows), dev-scoped (group scoped to
`dev`), orphan (group scoped to a tag no host carries -> sees nothing).
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main as main_module
from auth.api_key_auth import (
    invalidate_group_permissions_cache,
    invalidate_group_tag_scopes_cache,
    invalidate_user_groups_cache,
)
from auth.capabilities import ALL_CAPABILITIES
from database import ApiKey, CustomGroup, GroupPermission, GroupTagScope, Tag, TagAssignment, User
from main import app
from models.docker_models import Container, DockerHost

HOSTS = {
    "h1": DockerHost(id="h1", name="Dev Host", url="tcp://h1:2376", status="online"),
    "h2": DockerHost(id="h2", name="Test Host", url="tcp://h2:2376", status="online"),
    "h3": DockerHost(id="h3", name="Untagged Host", url="tcp://h3:2376", status="offline"),
}


def _container(cid: str, host_id: str, state: str = "running") -> Container:
    return Container(
        id=cid, short_id=cid, name=f"c-{cid}", image="nginx:latest", state=state,
        status="Up", host_id=host_id, host_name=HOSTS[host_id].name, created="2026-09-16T00:00:00Z",
    )


CONTAINERS = [
    _container("aaa111111111", "h1"),
    _container("bbb222222222", "h1", state="exited"),
    _container("ccc333333333", "h2"),
    _container("ddd444444444", "h3"),
]


def _tag(session, name: str) -> Tag:
    tag = Tag(id=str(uuid.uuid4()), name=name)
    session.add(tag)
    session.flush()
    return tag


def _group_with_all_caps(session, name: str, *scope_tags: Tag) -> CustomGroup:
    group = CustomGroup(name=name, description="scope test")
    session.add(group)
    session.flush()
    for cap in ALL_CAPABILITIES:
        session.add(GroupPermission(group_id=group.id, capability=cap, allowed=True))
    for tag in scope_tags:
        session.add(GroupTagScope(group_id=group.id, tag_id=tag.id))
    session.flush()
    return group


def _api_key_for(session, username: str, group: CustomGroup) -> str:
    user = User(username=username, password_hash="$2b$12$test_hash_not_real", created_at=datetime.now(timezone.utc))
    session.add(user)
    session.flush()
    raw_key = f"dockmon_{secrets.token_hex(16)}"
    session.add(ApiKey(
        created_by_user_id=user.id, group_id=group.id, name=f"{username}-key",
        key_hash=hashlib.sha256(raw_key.encode()).hexdigest(), key_prefix=raw_key[:12],
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return raw_key


class ScopedClient:
    def __init__(self, client: TestClient, api_key: str):
        self._client = client
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def get(self, url: str, **kwargs):
        return self._client.get(url, headers=self._headers, **kwargs)

    def post(self, url: str, **kwargs):
        return self._client.post(url, headers=self._headers, **kwargs)


@pytest.fixture(autouse=True)
def reset_auth_caches():
    invalidate_group_permissions_cache()
    invalidate_user_groups_cache()
    invalidate_group_tag_scopes_cache()
    yield
    invalidate_group_permissions_cache()
    invalidate_user_groups_cache()
    invalidate_group_tag_scopes_cache()


@pytest.fixture
def seeded_hosts(db_session, monkeypatch):
    dev, test, unused = _tag(db_session, "dev"), _tag(db_session, "test"), _tag(db_session, "unused")
    db_session.add(TagAssignment(tag_id=dev.id, subject_type="host", subject_id="h1"))
    db_session.add(TagAssignment(tag_id=test.id, subject_type="host", subject_id="h2"))
    db_session.commit()

    monkeypatch.setattr(main_module.monitor, "hosts", dict(HOSTS))

    async def get_containers(host_id=None):
        return [c for c in CONTAINERS if host_id is None or c.host_id == host_id]

    monkeypatch.setattr(main_module.monitor, "get_containers", get_containers)
    monkeypatch.setattr(main_module.monitor, "get_last_containers", lambda: list(CONTAINERS))
    return {"dev": dev, "test": test, "unused": unused}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def unrestricted_client(client, db_session, seeded_hosts):
    group = _group_with_all_caps(db_session, "Unrestricted")
    return ScopedClient(client, _api_key_for(db_session, "admin", group))


@pytest.fixture
def dev_scoped_client(client, db_session, seeded_hosts):
    group = _group_with_all_caps(db_session, "Dev", seeded_hosts["dev"])
    return ScopedClient(client, _api_key_for(db_session, "dev_user", group))


@pytest.fixture
def orphan_client(client, db_session, seeded_hosts):
    group = _group_with_all_caps(db_session, "Orphan", seeded_hosts["unused"])
    return ScopedClient(client, _api_key_for(db_session, "orphan_user", group))


@pytest.mark.integration
class TestHostsEndpoint:
    def test_unrestricted_sees_all_hosts(self, unrestricted_client):
        response = unrestricted_client.get("/api/hosts")
        assert response.status_code == 200
        assert {h["id"] for h in response.json()} == {"h1", "h2", "h3"}

    def test_dev_scoped_sees_only_dev_host(self, dev_scoped_client):
        response = dev_scoped_client.get("/api/hosts")
        assert response.status_code == 200
        assert {h["id"] for h in response.json()} == {"h1"}

    def test_orphan_sees_no_hosts(self, orphan_client):
        response = orphan_client.get("/api/hosts")
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.integration
class TestContainersEndpoint:
    def test_unrestricted_sees_all_containers(self, unrestricted_client):
        response = unrestricted_client.get("/api/containers")
        assert response.status_code == 200
        assert {c["host_id"] for c in response.json()} == {"h1", "h2", "h3"}

    def test_dev_scoped_sees_only_dev_containers(self, dev_scoped_client):
        response = dev_scoped_client.get("/api/containers")
        assert response.status_code == 200
        assert {c["host_id"] for c in response.json()} == {"h1"}
        assert len(response.json()) == 2

    def test_dev_scoped_query_for_hidden_host_is_empty(self, dev_scoped_client):
        response = dev_scoped_client.get("/api/containers?host_id=h2")
        assert response.status_code == 200
        assert response.json() == []

    def test_orphan_sees_no_containers(self, orphan_client):
        response = orphan_client.get("/api/containers")
        assert response.status_code == 200
        assert response.json() == []
