"""Tag-based host visibility on the primary read surfaces.

Three hosts: h1 carries tag `dev`, h2 carries tag `test`, h3 is untagged.
Principals: unrestricted (group without scope rows), dev-scoped (group scoped to
`dev`), orphan (group scoped to a tag no host carries -> sees nothing).
"""

import hashlib
import json
import secrets
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import main as main_module
from auth.api_key_auth import invalidate_group_permissions_cache
from auth.capabilities import ALL_CAPABILITIES
from database import (
    Agent, AlertRuleV2, AlertV2, ApiKey, ContainerHttpHealthCheck, ContainerUpdate, CustomGroup, DatabaseManager,
    Deployment, DeploymentMetadata, DockerHostDB, EventLog, GroupPermission, GroupTagScope, Tag, TagAssignment,
    User, UserGroupMembership,
)
from agent.manager import AgentManager
from deployment import routes as deployment_routes, stack_storage
from main import app
from models.docker_models import Container, DockerHost

HOSTS = {
    "h1": DockerHost(id="h1", name="Dev Host", url="tcp://h1:2376", status="online"),
    "h2": DockerHost(id="h2", name="Test Host", url="tcp://h2:2376", status="online"),
    "h3": DockerHost(id="h3", name="Untagged Host", url="tcp://h3:2376", status="offline"),
}


def _container(cid: str, host_id: str, state: str = "running", host_name: str | None = None) -> Container:
    return Container(
        id=cid, short_id=cid, name=f"c-{cid}", image="nginx:latest", state=state,
        status="Up", host_id=host_id, host_name=host_name or HOSTS[host_id].name, created="2026-09-16T00:00:00Z",
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

    def put(self, url: str, **kwargs):
        return self._client.put(url, headers=self._headers, **kwargs)

    def patch(self, url: str, **kwargs):
        return self._client.patch(url, headers=self._headers, **kwargs)

    def delete(self, url: str, **kwargs):
        return self._client.delete(url, headers=self._headers, **kwargs)


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
class TestHostUrlRebinding:
    """A host keeps its tags when edited, so its URL must not be re-pointed at a daemon the
    caller cannot see, and no host may take another host's URL."""

    def test_scoped_caller_cannot_change_a_visible_hosts_url(self, dev_scoped_client, db_session, monkeypatch):
        calls = []
        monkeypatch.setattr(main_module.monitor, "update_host", lambda host_id, config: calls.append(config.url) or HOSTS["h1"])
        body = {"name": "Dev Host", "url": "unix:///var/run/docker.sock"}
        # No persisted record yet: fail closed rather than trusting the in-memory map
        assert dev_scoped_client.put("/api/hosts/h1", json={"name": "Dev Host", "url": HOSTS["h1"].url}).status_code == 404
        db_session.add(DockerHostDB(id="h1", name="Dev Host", url=HOSTS["h1"].url))
        db_session.commit()
        assert dev_scoped_client.put("/api/hosts/h1", json=body).status_code == 404
        assert calls == []
        assert dev_scoped_client.put("/api/hosts/h1", json={"name": "Renamed", "url": HOSTS["h1"].url}).status_code == 200
        assert calls == [HOSTS["h1"].url]

    def test_agent_placeholder_url_is_not_a_duplicate(self, unrestricted_client, monkeypatch):
        from models.docker_models import DockerHostConfig
        from docker_monitor.monitor import DockerMonitor
        agents = {"a1": DockerHost(id="a1", name="agent 1", url="agent://", status="online"),
                  "a2": DockerHost(id="a2", name="agent 2", url="agent://", status="online")}
        monkeypatch.setattr(main_module.monitor, "hosts", agents)
        assert DockerMonitor._url_in_use(main_module.monitor, "agent://", exclude_host_id="a1") is False

    def test_update_refuses_another_hosts_url(self, unrestricted_client, monkeypatch):
        from models.docker_models import DockerHostConfig
        from docker_monitor.monitor import DockerMonitor
        with pytest.raises(HTTPException) as exc:
            DockerMonitor.update_host(main_module.monitor, "h1", DockerHostConfig(name="Dev Host", url=HOSTS["h2"].url))
        assert exc.value.status_code == 400
        assert "Test Host" not in exc.value.detail

    def test_add_host_duplicate_error_does_not_name_the_existing_host(self, unrestricted_client):
        response = unrestricted_client.post("/api/hosts", json={"name": "probe", "url": HOSTS["h2"].url})
        assert response.status_code == 400
        assert "Test Host" not in response.text


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

    def test_dev_scoped_query_for_hidden_host_is_empty_without_touching_it(self, dev_scoped_client, monkeypatch):
        touched = []
        original = main_module.monitor.get_containers

        async def spy(host_id=None):
            touched.append(host_id)
            return await original(host_id)

        monkeypatch.setattr(main_module.monitor, "get_containers", spy)
        response = dev_scoped_client.get("/api/containers?host_id=h2")
        assert response.status_code == 200
        assert response.json() == []
        assert touched == []

    def test_orphan_sees_no_containers(self, orphan_client):
        response = orphan_client.get("/api/containers")
        assert response.status_code == 200
        assert response.json() == []


@pytest.fixture
def seeded_agents(db_session, seeded_hosts):
    for host_id, host in HOSTS.items():
        db_session.add(DockerHostDB(id=host_id, name=host.name, url=host.url, connection_type="agent"))
    db_session.flush()
    for host_id in ("h1", "h2"):
        db_session.add(Agent(
            id=f"agent-{host_id}", host_id=host_id, engine_id=f"engine-{host_id}", version="1.0.0",
            proto_version="1", capabilities={}, status="online",
        ))
    db_session.commit()


@pytest.mark.integration
class TestDashboardHostsEndpoint:
    def test_unrestricted_sees_all_hosts(self, unrestricted_client):
        response = unrestricted_client.get("/api/dashboard/hosts")
        assert response.status_code == 200
        data = response.json()
        assert {h["id"] for h in data["groups"]["All Hosts"]} == {"h1", "h2", "h3"}
        assert data["total_hosts"] == 3

    def test_dev_scoped_sees_only_dev_host(self, dev_scoped_client):
        response = dev_scoped_client.get("/api/dashboard/hosts")
        assert response.status_code == 200
        data = response.json()
        assert {h["id"] for h in data["groups"]["All Hosts"]} == {"h1"}
        assert data["total_hosts"] == 1

    def test_orphan_sees_no_hosts(self, orphan_client):
        response = orphan_client.get("/api/dashboard/hosts")
        assert response.status_code == 200
        assert response.json()["groups"]["All Hosts"] == []
        assert response.json()["total_hosts"] == 0


@pytest.mark.integration
class TestAgentListEndpoint:
    def test_unrestricted_sees_all_agents(self, unrestricted_client, seeded_agents):
        response = unrestricted_client.get("/api/agent/list")
        assert response.status_code == 200
        assert {a["host_id"] for a in response.json()["agents"]} == {"h1", "h2"}
        assert response.json()["total"] == 2

    def test_dev_scoped_sees_only_dev_agent(self, dev_scoped_client, seeded_agents):
        response = dev_scoped_client.get("/api/agent/list")
        assert response.status_code == 200
        assert [a["host_id"] for a in response.json()["agents"]] == ["h1"]
        assert response.json()["total"] == 1

    def test_orphan_sees_no_agents(self, orphan_client, seeded_agents):
        response = orphan_client.get("/api/agent/list")
        assert response.status_code == 200
        assert response.json()["agents"] == []
        assert response.json()["total"] == 0
        assert response.json()["connected_count"] == 0


@pytest.mark.integration
class TestHostPathRoutesGuarded:
    """require_host_access on real routes: hidden host -> 404, visible host -> not 404,
    missing capability -> 403 regardless of visibility."""

    def test_hidden_host_is_404_on_read_and_mutation_routes(self, dev_scoped_client):
        assert dev_scoped_client.get("/api/hosts/h2/metrics").status_code == 404
        assert dev_scoped_client.get("/api/hosts/h2/containers/ccc333333333/logs").status_code == 404
        assert dev_scoped_client.post("/api/hosts/h2/containers/ccc333333333/restart").status_code == 404
        assert dev_scoped_client.post("/api/deployments/scan-compose-dirs/h2", json={"path": "/tmp"}).status_code == 404

    def test_visible_host_passes_the_guard(self, dev_scoped_client):
        assert dev_scoped_client.get("/api/hosts/h1/metrics").status_code != 404

    def test_orphan_gets_404_everywhere(self, orphan_client):
        assert orphan_client.get("/api/hosts/h1/metrics").status_code == 404
        assert orphan_client.get("/api/hosts/h3/metrics").status_code == 404

    def test_unrestricted_reaches_every_host(self, unrestricted_client):
        for host_id in ("h1", "h2", "h3"):
            assert unrestricted_client.get(f"/api/hosts/{host_id}/metrics").status_code != 404

    def test_missing_capability_is_403_even_for_hidden_host(self, client, db_session, seeded_hosts):
        group = CustomGroup(name="NoCaps", description="scope test")
        db_session.add(group)
        db_session.flush()
        db_session.add(GroupTagScope(group_id=group.id, tag_id=seeded_hosts["dev"].id))
        db_session.flush()
        nocaps = ScopedClient(client, _api_key_for(db_session, "nocaps_user", group))
        assert nocaps.get("/api/hosts/h2/metrics").status_code == 403
        assert nocaps.get("/api/hosts/h1/metrics").status_code == 403

    def test_migrate_requires_both_ends_visible(self, dev_scoped_client, unrestricted_client, seeded_agents):
        assert dev_scoped_client.post("/api/agent/agent-h2/migrate-from/h1").status_code == 404
        assert dev_scoped_client.post("/api/agent/agent-h1/migrate-from/h2").status_code == 404
        assert dev_scoped_client.post("/api/agent/agent-h1/migrate-from/h1").status_code != 404
        assert unrestricted_client.post("/api/agent/agent-h2/migrate-from/h1").status_code != 404


@pytest.fixture
def seeded_events(db_session, seeded_hosts):
    """One event per visibility class. Keys name the class; values are the event ids."""
    rows = {
        "dev_host": EventLog(category="host", event_type="connected", host_id="h1", title="h1 up", correlation_id="corr-1"),
        "test_host": EventLog(category="host", event_type="connected", host_id="h2", title="h2 up", correlation_id="corr-1"),
        "untagged_host": EventLog(category="host", event_type="connected", host_id="h3", title="h3 up"),
        "dev_alert_composite": EventLog(category="container", event_type="alert", host_id=None,
                                        container_id="h1:aaa111111111", title="dev container alert"),
        "test_alert_composite": EventLog(category="container", event_type="alert", host_id=None,
                                         container_id="h2:ccc333333333", title="test container alert"),
        "hostless_container": EventLog(category="container", event_type="state_change", host_id=None,
                                       container_id="aaa111111111", title="orphan container event"),
        "system": EventLog(category="system", event_type="startup", title="DockMon started"),
        "rule_created": EventLog(category="alert", event_type="rule_created", title="Alert rule 'High CPU' created"),
        "system_alert_fired": EventLog(category="alert", event_type="rule_triggered",
                                       title="Alert triggered: evaluation failed. Affected: Test Host"),
        "channel_created": EventLog(category="notification", event_type="channel_created", title="Channel created"),
        "user_login": EventLog(category="user", event_type="login", title="admin logged in"),
        "empty_host_composite": EventLog(category="container", event_type="alert", host_id="",
                                         container_id="h1:bbb222222222", title="empty-host dev alert"),
        "empty_both_global": EventLog(category="notification", event_type="sent", host_id="", container_id="",
                                      title="notification sent"),
    }
    for row in rows.values():
        db_session.add(row)
    db_session.commit()
    return {name: row.id for name, row in rows.items()}


@pytest.mark.integration
class TestEventsScoped:
    def _titles(self, client, **params):
        response = client.get("/api/events", params={"limit": 100, **params})
        assert response.status_code == 200
        return {e["title"] for e in response.json()["events"]}, response.json()["total_count"]

    def test_unrestricted_sees_everything(self, unrestricted_client, seeded_events):
        titles, total = self._titles(unrestricted_client)
        assert total == len(seeded_events)

    def test_dev_scoped_sees_own_host_composite_and_global_admin_events(self, dev_scoped_client, seeded_events):
        titles, total = self._titles(dev_scoped_client)
        assert titles == {
            "h1 up", "dev container alert", "DockMon started",
            "Alert rule 'High CPU' created", "Channel created", "admin logged in",
            "empty-host dev alert", "notification sent",
        }
        assert total == 8

    def test_total_count_is_computed_over_the_scoped_set(self, dev_scoped_client, seeded_events):
        response = dev_scoped_client.get("/api/events", params={"limit": 2, "offset": 0})
        assert response.json()["total_count"] == 8
        assert response.json()["has_more"] is True

    def test_orphan_sees_only_global_admin_events(self, orphan_client, seeded_events):
        titles, total = self._titles(orphan_client)
        assert titles == {"DockMon started", "Alert rule 'High CPU' created", "Channel created", "admin logged in",
                          "notification sent"}

    def test_statistics_count_the_scoped_set(self, dev_scoped_client, unrestricted_client, orphan_client, seeded_events):
        assert unrestricted_client.get("/api/events/statistics").json()["total_events"] == len(seeded_events)
        assert dev_scoped_client.get("/api/events/statistics").json()["total_events"] == 8
        assert orphan_client.get("/api/events/statistics").json()["total_events"] == 5

    def test_single_event_on_hidden_host_is_404(self, dev_scoped_client, unrestricted_client, seeded_events):
        assert dev_scoped_client.get(f"/api/events/{seeded_events['test_host']}").status_code == 404
        assert dev_scoped_client.get(f"/api/events/{seeded_events['hostless_container']}").status_code == 404
        assert dev_scoped_client.get(f"/api/events/{seeded_events['dev_host']}").status_code == 200
        assert dev_scoped_client.get(f"/api/events/{seeded_events['dev_alert_composite']}").status_code == 200
        assert dev_scoped_client.get(f"/api/events/{seeded_events['rule_created']}").status_code == 200
        assert dev_scoped_client.get(f"/api/events/{seeded_events['system_alert_fired']}").status_code == 404
        assert unrestricted_client.get(f"/api/events/{seeded_events['system_alert_fired']}").status_code == 200

    def test_correlation_group_is_filtered(self, dev_scoped_client, unrestricted_client, seeded_events):
        assert {e["title"] for e in unrestricted_client.get("/api/events/correlation/corr-1").json()["events"]} == {"h1 up", "h2 up"}
        scoped = dev_scoped_client.get("/api/events/correlation/corr-1").json()
        assert [e["title"] for e in scoped["events"]] == ["h1 up"]
        assert scoped["count"] == 1


@pytest.fixture
def seeded_container_configs(db_session, seeded_hosts):
    """A ContainerUpdate, DeploymentMetadata and ContainerHttpHealthCheck row for one container per host."""
    for host_id, host in HOSTS.items():
        db_session.add(DockerHostDB(id=host_id, name=host.name, url=host.url))
    db_session.flush()
    for c in CONTAINERS[:1] + CONTAINERS[2:]:
        key = f"{c.host_id}:{c.short_id}"
        db_session.add(ContainerUpdate(container_id=key, host_id=c.host_id, current_image="nginx:latest",
                                       current_digest="sha256:x", update_available=True))
        db_session.add(DeploymentMetadata(container_id=key, host_id=c.host_id, is_managed=True))
        db_session.add(ContainerHttpHealthCheck(container_id=key, host_id=c.host_id, url="http://x"))
    db_session.commit()


@pytest.mark.integration
class TestCompositeKeyDictsScoped:
    @pytest.mark.parametrize("path", ["/api/auto-update-configs", "/api/deployment-metadata", "/api/health-check-configs"])
    def test_dict_keys_pruned_to_visible_hosts(self, path, dev_scoped_client, unrestricted_client, seeded_container_configs):
        assert {k.split(":")[0] for k in unrestricted_client.get(path).json()} == {"h1", "h2", "h3"}
        assert {k.split(":")[0] for k in dev_scoped_client.get(path).json()} == {"h1"}

    def test_updates_summary_counts_only_visible(self, dev_scoped_client, unrestricted_client, seeded_container_configs):
        assert unrestricted_client.get("/api/updates/summary").json()["total_updates"] == 3
        scoped = dev_scoped_client.get("/api/updates/summary").json()
        assert scoped["total_updates"] == 1
        assert scoped["containers_with_updates"] == ["h1:aaa111111111"]


@pytest.mark.integration
class TestBatchScoped:
    def test_create_with_hidden_host_key_is_404(self, dev_scoped_client):
        body = {"scope": "container", "action": "restart", "ids": ["h1:aaa111111111", "h2:ccc333333333"]}
        assert dev_scoped_client.post("/api/batch", json=body).status_code == 404
        body["ids"] = ["h1:aaa111111111"]
        assert dev_scoped_client.post("/api/batch", json=body).status_code != 404

    def test_validate_update_with_hidden_host_key_is_404(self, dev_scoped_client):
        assert dev_scoped_client.post("/api/batch/validate-update", json={"container_ids": ["h2:ccc333333333"]}).status_code == 404
        assert dev_scoped_client.post("/api/batch/validate-update", json={"container_ids": ["h1:aaa111111111"]}).status_code != 404

    def test_job_items_pruned_to_visible_hosts(self, dev_scoped_client, unrestricted_client, orphan_client, monkeypatch):
        job = {"job_id": "j1", "status": "completed", "total_items": 2, "completed_items": 2, "success_items": 2,
               "error_items": 0, "skipped_items": 0, "items": [
            {"id": 1, "container_id": "aaa111111111", "host_id": "h1", "status": "success"},
            {"id": 2, "container_id": "ccc333333333", "host_id": "h2", "status": "success"},
        ]}
        monkeypatch.setattr(main_module, "batch_manager", SimpleNamespace(get_job_status=lambda job_id: dict(job, items=[dict(i) for i in job["items"]])))
        assert [i["host_id"] for i in unrestricted_client.get("/api/batch/j1").json()["items"]] == ["h1", "h2"]
        scoped = dev_scoped_client.get("/api/batch/j1").json()
        assert [i["host_id"] for i in scoped["items"]] == ["h1"]
        assert (scoped["total_items"], scoped["completed_items"], scoped["success_items"]) == (1, 1, 1)
        assert orphan_client.get("/api/batch/j1").status_code == 404


@pytest.mark.integration
class TestDashboardSummaryScoped:
    def test_counts_over_visible_hosts_and_cache_bypassed(self, dev_scoped_client, unrestricted_client, seeded_container_configs):
        admin = unrestricted_client.get("/api/dashboard/summary").json()
        assert admin["hosts"]["total"] == 3
        assert admin["containers"]["total"] == 4
        assert admin["updates"]["available"] == 3

        scoped = dev_scoped_client.get("/api/dashboard/summary").json()
        assert scoped["hosts"] == {"online": 1, "total": 1, "offline": 0}
        assert scoped["containers"]["total"] == 2
        assert scoped["containers"]["running"] == 1
        assert scoped["updates"]["available"] == 1
        assert scoped["hosts_summary"] == "1/1"

        assert unrestricted_client.get("/api/dashboard/summary").json()["hosts"]["total"] == 3

    def test_orphan_sees_zero_everything(self, orphan_client, seeded_container_configs):
        scoped = orphan_client.get("/api/dashboard/summary").json()
        assert scoped["hosts"]["total"] == 0
        assert scoped["containers"]["total"] == 0
        assert scoped["updates"]["available"] == 0


@pytest.mark.integration
class TestGlobalOpsScoped:
    """Fleet-wide operations run over the caller's visible hosts only."""

    def test_prune_and_check_all_receive_the_visible_set(self, dev_scoped_client, unrestricted_client, monkeypatch):
        calls = []

        async def cleanup_old_images(host_ids=None):
            calls.append(("prune", host_ids))
            return 0

        async def check_updates_now(host_ids=None):
            calls.append(("check", host_ids))
            return {"total": 0, "checked": 0, "updates_found": 0, "errors": 0}

        monkeypatch.setattr(main_module.monitor, "periodic_jobs",
                            SimpleNamespace(cleanup_old_images=cleanup_old_images, check_updates_now=check_updates_now))
        assert dev_scoped_client.post("/api/images/prune").status_code == 200
        assert dev_scoped_client.post("/api/updates/check-all").status_code == 200
        assert unrestricted_client.post("/api/images/prune").status_code == 200
        assert calls == [("prune", {"h1"}), ("check", {"h1"}), ("prune", None)]


def _rule_body(**overrides):
    body = {"name": "r", "scope": "host", "kind": "host_down", "severity": "warning"}
    body.update(overrides)
    return body


@pytest.mark.integration
class TestAlertRuleSelectorsScoped:
    """Explicit host ids in a rule's selectors must be visible; tag/all selectors stay global."""

    def test_create_with_hidden_host_in_selector_is_404(self, dev_scoped_client):
        assert dev_scoped_client.post("/api/alerts/rules", json=_rule_body(
            host_selector_json=json.dumps({"include": ["h1", "h2"]}))).status_code == 404
        assert dev_scoped_client.post("/api/alerts/rules", json=_rule_body(
            host_selector_json=json.dumps({"host_id": "h2"}))).status_code == 404
        # A bare string include would be a substring match in the engine: rejected at the door
        assert dev_scoped_client.post("/api/alerts/rules", json=_rule_body(
            host_selector_json=json.dumps({"include": "h1"}))).status_code == 400
        assert dev_scoped_client.post("/api/alerts/rules", json=_rule_body(
            scope="container", kind="container_stopped",
            container_selector_json=json.dumps({"include": ["h2:web"]}))).status_code == 404

    def test_create_with_visible_or_global_selectors_passes(self, dev_scoped_client):
        assert dev_scoped_client.post("/api/alerts/rules", json=_rule_body(
            host_selector_json=json.dumps({"include": ["h1"]}))).status_code == 200
        assert dev_scoped_client.post("/api/alerts/rules", json=_rule_body(
            host_selector_json=json.dumps({"include_all": True}))).status_code == 200
        assert dev_scoped_client.post("/api/alerts/rules", json=_rule_body(
            host_selector_json=json.dumps({"tags": ["prod"]}))).status_code == 200

    def test_update_delete_toggle_on_rule_naming_hidden_host(self, dev_scoped_client, unrestricted_client, db_session):
        db_session.add(AlertRuleV2(id="rule-hidden", name="hidden", scope="host", kind="host_down", severity="warning",
                                   host_selector_json=json.dumps({"include": ["h2"]})))
        db_session.add(AlertRuleV2(id="rule-visible", name="visible", scope="host", kind="host_down", severity="warning",
                                   host_selector_json=json.dumps({"include": ["h1"]})))
        db_session.commit()
        assert dev_scoped_client.patch("/api/alerts/rules/rule-hidden/toggle").status_code == 404
        assert dev_scoped_client.delete("/api/alerts/rules/rule-hidden").status_code == 404
        assert dev_scoped_client.put("/api/alerts/rules/rule-hidden", json={"name": "x"}).status_code == 404
        assert dev_scoped_client.put("/api/alerts/rules/rule-visible",
                                     json={"host_selector_json": json.dumps({"include": ["h2"]})}).status_code == 404
        assert dev_scoped_client.patch("/api/alerts/rules/rule-visible/toggle").status_code == 200
        assert unrestricted_client.patch("/api/alerts/rules/rule-hidden/toggle").status_code == 200
        assert db_session.query(AlertRuleV2).filter_by(id="rule-hidden").count() == 1


def _alert(alert_id, scope_type, scope_id, host_id=None, state="open"):
    now = datetime.now(timezone.utc)
    return AlertV2(id=alert_id, dedup_key=f"k|{scope_type}:{scope_id}|{alert_id}", scope_type=scope_type,
                   scope_id=scope_id, host_id=host_id, kind="cpu_high", severity="warning", state=state,
                   title=alert_id, message="m", first_seen=now, last_seen=now)


@pytest.fixture
def seeded_alerts(db_session, seeded_hosts):
    for alert in (
        _alert("a-host-h1", "host", "h1", host_id="h1"),
        _alert("a-host-h2", "host", "h2", host_id="h2"),
        _alert("a-cont-h1", "container", "h1:aaa111111111"),
        _alert("a-cont-h2", "container", "h2:ccc333333333", state="resolved"),
        _alert("a-system", "system", "alert_service"),
        _alert("a-orphan", "container", "aaa111111111"),
    ):
        db_session.add(alert)
    db_session.commit()


@pytest.mark.integration
class TestAlertsScoped:
    def test_list_and_total_are_scoped(self, dev_scoped_client, unrestricted_client, seeded_alerts):
        assert unrestricted_client.get("/api/alerts/").json()["total"] == 6
        scoped = dev_scoped_client.get("/api/alerts/").json()
        assert {a["id"] for a in scoped["alerts"]} == {"a-host-h1", "a-cont-h1"}
        assert scoped["total"] == 2

    def test_stats_are_scoped(self, dev_scoped_client, unrestricted_client, seeded_alerts):
        assert unrestricted_client.get("/api/alerts/stats/").json()["total"] == 6
        scoped = dev_scoped_client.get("/api/alerts/stats/").json()
        assert scoped["total"] == 2
        assert scoped["by_state"]["open"] == 2
        assert scoped["by_severity"]["warning"] == 2

    @pytest.mark.parametrize("path,method", [
        ("/api/alerts/{id}", "get"), ("/api/alerts/{id}/annotations", "get"),
        ("/api/alerts/{id}/resolve", "post"), ("/api/alerts/{id}/snooze", "post"),
        ("/api/alerts/{id}/unsnooze", "post"), ("/api/alerts/{id}/annotations", "post"),
    ])
    def test_alert_routes_404_on_hidden_and_underivable_hosts(self, path, method, dev_scoped_client, seeded_alerts):
        bodies = {"resolve": {"reason": "x"}, "snooze": {"duration_minutes": 5}, "annotations": {"text": "note"}}
        kwargs = {"json": bodies.get(path.rsplit("/", 1)[-1], {})} if method == "post" else {}
        for hidden in ("a-host-h2", "a-cont-h2", "a-orphan", "a-system"):
            response = getattr(dev_scoped_client, method)(path.format(id=hidden), **kwargs)
            assert response.status_code == 404, (path, hidden, response.text)
        visible = getattr(dev_scoped_client, method)(path.format(id="a-host-h1"), **kwargs)
        assert visible.status_code != 404, (path, visible.text)

    def test_metric_capabilities_lists_only_visible_hosts(self, dev_scoped_client, unrestricted_client, monkeypatch):
        import alerts.api as alerts_api
        monkeypatch.setattr(alerts_api, "get_stats_client",
                            lambda: SimpleNamespace(get_host_stats=AsyncMock(return_value={})))
        assert {h["host_id"] for h in unrestricted_client.get("/api/alerts/metrics/capabilities").json()["hosts"]} == {"h1", "h2", "h3"}
        assert [h["host_id"] for h in dev_scoped_client.get("/api/alerts/metrics/capabilities").json()["hosts"]] == ["h1"]


def _compose_container(cid, host_id, project, service):
    c = _container(cid, host_id)
    c.labels = {"com.docker.compose.project": project, "com.docker.compose.service": service}
    return c


COMPOSE_CONTAINERS = [
    _compose_container("aaa111111111", "h1", "web", "nginx"),
    _compose_container("ccc333333333", "h2", "web", "nginx"),
    _compose_container("ddd444444444", "h3", "db", "postgres"),
]


@pytest.fixture
def deployment_deps(db_session, seeded_hosts, monkeypatch):
    """Point the deployment/stack routers at the test monitor + database and seed
    compose-labelled containers on every host."""
    for host_id, host in HOSTS.items():
        db_session.add(DockerHostDB(id=host_id, name=host.name, url=host.url))
    db_session.commit()
    monkeypatch.setattr(deployment_routes, "_docker_monitor", main_module.monitor)
    monkeypatch.setattr(deployment_routes, "_database_manager", main_module.monitor.db)
    monkeypatch.setattr(main_module.monitor, "get_last_containers", lambda: list(COMPOSE_CONTAINERS))
    monkeypatch.setattr(stack_storage, "stack_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(stack_storage, "list_stacks", AsyncMock(return_value=["web", "db"]))
    monkeypatch.setattr(stack_storage, "read_stack", AsyncMock(return_value=("services:\n  nginx:\n    image: nginx\n", {})))
    monkeypatch.setattr(deployment_routes, "_deployment_executor", SimpleNamespace(
        create_deployment=AsyncMock(return_value="h1:dep000000009"),
        execute_deployment=AsyncMock(),
    ))


def _seed_deployments(db_session, user_id):
    for host_id, stack in (("h1", "web"), ("h2", "db")):
        db_session.add(Deployment(id=f"{host_id}:dep000000001", host_id=host_id, user_id=user_id,
                                  stack_name=stack, status="planning"))
    db_session.commit()


def _api_key_user_id(db_session, username):
    return db_session.query(User).filter_by(username=username).one().id


@pytest.mark.integration
class TestDeploymentsScoped:
    def test_body_host_ids_must_be_visible(self, dev_scoped_client, deployment_deps):
        hidden = {"detail": "Host not found"}
        assert dev_scoped_client.post("/api/deployments/deploy", json={"stack_name": "web", "host_id": "h2", "action": "up"}).json() == hidden
        assert dev_scoped_client.post("/api/deployments", json={"stack_name": "web", "host_id": "h2"}).json() == hidden
        assert dev_scoped_client.post("/api/deployments/generate-from-containers",
                                      json={"project_name": "web", "host_id": "h2"}).json() == hidden
        assert dev_scoped_client.post("/api/stacks/web/validate-ports", json={"host_id": "h2"}).json() == hidden
        assert dev_scoped_client.post("/api/deployments/generate-from-containers",
                                      json={"project_name": "web", "host_id": "h1"}).status_code == 200

    def test_list_and_record_routes_are_scoped(self, dev_scoped_client, deployment_deps, db_session):
        _seed_deployments(db_session, _api_key_user_id(db_session, "dev_user"))
        assert [d["host_id"] for d in dev_scoped_client.get("/api/deployments").json()] == ["h1"]
        assert dev_scoped_client.get("/api/deployments/h1:dep000000001").status_code == 200
        for method, path, body in (
            ("get", "/api/deployments/h2:dep000000001", None),
            ("get", "/api/deployments/h2:dep000000001/compose-preview", None),
            ("put", "/api/deployments/h2:dep000000001", {"stack_name": "web"}),
            ("delete", "/api/deployments/h2:dep000000001", None),
            ("post", "/api/deployments/h2:dep000000001/execute", None),
        ):
            kwargs = {"json": body} if body is not None else {}
            assert getattr(dev_scoped_client, method)(path, **kwargs).status_code == 404, (method, path)
        assert db_session.query(Deployment).filter_by(id="h2:dep000000001").count() == 1

    def test_put_cannot_move_a_deployment_to_a_hidden_host(self, dev_scoped_client, deployment_deps, db_session):
        _seed_deployments(db_session, _api_key_user_id(db_session, "dev_user"))
        response = dev_scoped_client.put("/api/deployments/h1:dep000000001", json={"host_id": "h2"})
        assert response.status_code == 404
        db_session.expire_all()
        assert db_session.query(Deployment).filter_by(id="h1:dep000000001").one().host_id == "h1"

    def test_known_stacks_and_running_projects_are_scoped(self, dev_scoped_client, unrestricted_client, deployment_deps):
        known = {k["name"]: k["hosts"] for k in unrestricted_client.get("/api/deployments/known-stacks").json()}
        assert known == {"web": ["h1", "h2"], "db": ["h3"]}
        known = {k["name"]: k["hosts"] for k in dev_scoped_client.get("/api/deployments/known-stacks").json()}
        assert known == {"web": ["h1"]}
        projects = dev_scoped_client.get("/api/deployments/running-projects").json()
        assert [(p["project_name"], p["host_id"]) for p in projects] == [("web", "h1")]

    def test_import_creates_records_only_for_visible_hosts(self, dev_scoped_client, deployment_deps, db_session, monkeypatch):
        monkeypatch.setattr(stack_storage, "stack_exists", AsyncMock(return_value=False))
        monkeypatch.setattr(stack_storage, "write_stack", AsyncMock())
        compose = "name: web\nservices:\n  nginx:\n    image: nginx\n"
        response = dev_scoped_client.post("/api/deployments/import", json={"compose_content": compose})
        assert response.status_code == 201, response.text
        assert {d["host_id"] for d in response.json()["deployments_created"]} == {"h1"}
        assert {d.host_id for d in db_session.query(Deployment).all()} == {"h1"}

    def test_import_as_stopped_on_hidden_host_is_404(self, dev_scoped_client, deployment_deps, monkeypatch):
        monkeypatch.setattr(main_module.monitor, "get_last_containers", lambda: [])
        compose = "name: web\nservices:\n  nginx:\n    image: nginx\n"
        assert dev_scoped_client.post("/api/deployments/import", json={"compose_content": compose, "host_id": "h2"}).status_code == 404


@pytest.mark.integration
class TestStacksScoped:
    def test_deployed_to_is_scoped_everywhere(self, dev_scoped_client, unrestricted_client, deployment_deps):
        admin = {s["name"]: [h["host_id"] for h in s["deployed_to"]] for s in unrestricted_client.get("/api/stacks").json()}
        assert admin == {"web": ["h1", "h2"], "db": ["h3"]}
        scoped = {s["name"]: [h["host_id"] for h in s["deployed_to"]] for s in dev_scoped_client.get("/api/stacks").json()}
        assert scoped == {"web": ["h1"], "db": []}
        assert [h["host_id"] for h in dev_scoped_client.get("/api/stacks/web").json()["deployed_to"]] == ["h1"]


@pytest.mark.integration
class TestAgentStatusScoped:
    def test_hidden_agent_host_is_404(self, dev_scoped_client, unrestricted_client, seeded_agents):
        assert dev_scoped_client.get("/api/agent/agent-h2/status").status_code == 404
        assert dev_scoped_client.get("/api/agent/agent-h1/status").status_code == 200
        assert unrestricted_client.get("/api/agent/agent-h2/status").status_code == 200


@pytest.mark.integration
class TestTestConnectionScoped:
    """The stored-cert fallback may only reuse certificates of a host the caller can see."""

    def _stub_client(self, monkeypatch, seen):
        class FakeClient:
            def __init__(self, **kwargs):
                seen.append(kwargs)
            def ping(self):
                return True
            def version(self):
                return {"Version": "1"}
            def close(self):
                pass
        monkeypatch.setattr(main_module.docker, "DockerClient", FakeClient)

    def test_hidden_host_certs_are_not_loaded(self, dev_scoped_client, unrestricted_client, db_session, seeded_hosts, monkeypatch):
        db_session.add(DockerHostDB(id="h2", name="Test Host", url="tcp://h2:2376",
                                    tls_ca="CA", tls_cert="CERT", tls_key="KEY"))
        db_session.commit()
        seen = []
        self._stub_client(monkeypatch, seen)

        dev_scoped_client.post("/api/hosts/test-connection", json={"name": "probe", "url": "tcp://h2:2376"})
        assert seen and "tls" not in seen[-1]

        unrestricted_client.post("/api/hosts/test-connection", json={"name": "probe", "url": "tcp://h2:2376"})
        assert "tls" in seen[-1]


# ---------------------------------------------------------------------------
# WebSocket /ws: session-cookie auth, per-connection visible set
# ---------------------------------------------------------------------------

def _session_user(session, username: str, group: CustomGroup) -> User:
    user = User(username=username, password_hash="$2b$12$test_hash_not_real", created_at=datetime.now(timezone.utc))
    session.add(user)
    session.flush()
    session.add(UserGroupMembership(user_id=user.id, group_id=group.id))
    session.commit()
    return user


@pytest.fixture
def ws_sessions(db_session, seeded_hosts, monkeypatch):
    """Map cookie value -> session dict for the users below; monkeypatches session validation."""
    admin = _session_user(db_session, "ws_admin", _group_with_all_caps(db_session, "WS Unrestricted"))
    dev = _session_user(db_session, "ws_dev", _group_with_all_caps(db_session, "WS Dev", seeded_hosts["dev"]))
    sessions = {
        "admin-cookie": {"user_id": admin.id, "username": admin.username},
        "dev-cookie": {"user_id": dev.id, "username": dev.username},
    }
    monkeypatch.setattr(
        "auth.cookie_sessions.cookie_session_manager.validate_session",
        lambda session_id, client_ip: sessions.get(session_id),
    )
    # The first viewer would start stats streams against the stats service; stub that, not the list
    monkeypatch.setattr(main_module.monitor.stats_manager, "sync_container_streams", AsyncMock())
    monkeypatch.setattr(main_module.monitor.stats_manager, "stop_all_streams", AsyncMock())
    return {"admin": admin, "dev": dev}


def _connect(client: TestClient, cookie: str):
    return client.websocket_connect("/ws", cookies={"session_id": cookie})


def _drain_until(ws, msg_type: str, limit: int = 5):
    for _ in range(limit):
        message = ws.receive_json()
        if message["type"] == msg_type:
            return message
    raise AssertionError(f"no {msg_type} message received")


@pytest.mark.integration
class TestWebSocketVisibility:
    def test_initial_state_and_immediate_update_are_scoped(self, client, ws_sessions):
        with _connect(client, "dev-cookie") as ws:
            initial = _drain_until(ws, "initial_state")
            assert [h["id"] for h in initial["data"]["hosts"]] == ["h1"]
            assert {c["host_id"] for c in initial["data"]["containers"]} == {"h1"}
            update = _drain_until(ws, "containers_update")
            assert {c["host_id"] for c in update["data"]["containers"]} == {"h1"}
            assert all(k.startswith("h1:") for k in update["data"]["container_sparklines"])

    def test_unrestricted_initial_state_has_everything(self, client, ws_sessions):
        with _connect(client, "admin-cookie") as ws:
            initial = _drain_until(ws, "initial_state")
            assert {h["id"] for h in initial["data"]["hosts"]} == {"h1", "h2", "h3"}
            assert {c["host_id"] for c in initial["data"]["containers"]} == {"h1", "h2", "h3"}

    def test_broadcasts_for_hidden_hosts_are_not_delivered(self, client, ws_sessions):
        manager = main_module.monitor.manager
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.portal.call(manager.broadcast, {"type": "host_status_changed", "data": {"host_id": "h2", "status": "offline"}})
            ws.portal.call(manager.broadcast, {"type": "new_event", "event": {"category": "container", "host_id": "h2", "container_id": "x"}})
            ws.portal.call(manager.broadcast, {"type": "host_status_changed", "data": {"host_id": "h1", "status": "offline"}})
            delivered = ws.receive_json()
            assert delivered == {"type": "host_status_changed", "data": {"host_id": "h1", "status": "offline"}}

    def test_subscribe_stats_for_hidden_container_is_refused(self, client, ws_sessions):
        realtime = main_module.monitor.realtime
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": "ccc333333333"})
            ws.send_json({"type": "subscribe_stats", "container_id": "aaa111111111"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert set(realtime.stats_subscribers) == {"h1:aaa111111111"}

    def test_subscribe_with_explicit_host_must_match_the_pair(self, client, ws_sessions):
        realtime = main_module.monitor.realtime
        with _connect(client, "admin-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": "aaa111111111", "host_id": "h2"})
            ws.send_json({"type": "subscribe_stats", "container_id": "ccc333333333", "host_id": "h2"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert set(realtime.stats_subscribers) == {"h2:ccc333333333"}
            ws.send_json({"type": "unsubscribe_stats", "container_id": "ccc333333333", "host_id": "h1"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert set(realtime.stats_subscribers) == {"h2:ccc333333333"}

    def test_user_deleted_during_accept_is_closed(self, client, ws_sessions, db_session, monkeypatch):
        """connect() awaits accept() before the socket is registered; a delete in that window
        bumps the generation, and the endpoint must re-run its connect-time checks."""
        from starlette.websockets import WebSocketDisconnect
        manager = main_module.monitor.manager
        original_connect = manager.connect

        async def connect_after_delete(websocket, **kwargs):
            db_session.query(UserGroupMembership).filter_by(user_id=ws_sessions["dev"].id).delete()
            db_session.query(User).filter_by(id=ws_sessions["dev"].id).delete()
            db_session.commit()
            await manager.disconnect_user(ws_sessions["dev"].id)
            await original_connect(websocket, **kwargs)

        monkeypatch.setattr(manager, "connect", connect_after_delete)
        with pytest.raises(WebSocketDisconnect) as exc:
            with _connect(client, "dev-cookie") as ws:
                ws.receive_json()
        assert exc.value.code == 1008

    def test_capability_revoked_during_accept_is_not_used_for_initial_state(self, client, ws_sessions, db_session, monkeypatch):
        """user_caps is computed before connect(); after a refresh the endpoint must use the
        socket's current capabilities for the direct sends."""
        manager = main_module.monitor.manager
        original_connect = manager.connect
        dev_group_id = db_session.query(UserGroupMembership).filter_by(user_id=ws_sessions["dev"].id).one().group_id

        async def connect_after_revoke(websocket, **kwargs):
            db_session.query(GroupPermission).filter_by(group_id=dev_group_id, capability="hosts.view").delete()
            db_session.commit()
            invalidate_group_permissions_cache()
            await manager.refresh_capabilities_for_user(ws_sessions["dev"].id)
            await original_connect(websocket, **kwargs)

        monkeypatch.setattr(manager, "connect", connect_after_revoke)
        with _connect(client, "dev-cookie") as ws:
            initial = _drain_until(ws, "initial_state")
            assert initial["data"]["hosts"] == []
            assert {c["host_id"] for c in initial["data"]["containers"]} == {"h1"}

    def test_subscribe_falls_back_to_live_discovery_on_a_cache_miss(self, client, ws_sessions, monkeypatch):
        realtime = main_module.monitor.realtime
        monkeypatch.setattr(main_module.monitor, "get_last_containers", lambda: [])
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": "aaa111111111"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert set(realtime.stats_subscribers) == {"h1:aaa111111111"}

    def test_subscribe_prefers_a_visible_clone_over_a_hidden_one(self, client, ws_sessions, monkeypatch):
        realtime = main_module.monitor.realtime
        clones = [_container("eee555555555", "h2"), _container("eee555555555", "h1")]
        monkeypatch.setattr(main_module.monitor, "get_last_containers", lambda: clones)
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": "eee555555555"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert set(realtime.stats_subscribers) == {"h1:eee555555555"}

    def test_non_string_container_id_does_not_close_the_socket(self, client, ws_sessions):
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": 123})
            ws.send_json({"type": "unsubscribe_stats", "container_id": ["x"]})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_scope_tightened_while_subscribed_revokes_stream(self, client, ws_sessions, db_session):
        realtime = main_module.monitor.realtime
        manager = main_module.monitor.manager
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            ws.send_json({"type": "subscribe_stats", "container_id": "aaa111111111"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert "h1:aaa111111111" in realtime.stats_subscribers

            db_session.query(TagAssignment).filter_by(subject_id="h1").delete()
            db_session.commit()
            ws.portal.call(manager.refresh_visible_hosts_for_user, ws_sessions["dev"].id)

            assert "h1:aaa111111111" not in realtime.stats_subscribers
            ws.send_json({"type": "subscribe_stats", "container_id": "aaa111111111"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            assert "h1:aaa111111111" not in realtime.stats_subscribers


@pytest.mark.integration
class TestMigrationVisibility:
    def test_scoped_user_keeps_seeing_a_migrated_host_and_gets_host_migrated(
        self, client, ws_sessions, seeded_agents, db_session, monkeypatch
    ):
        """h1 (tag dev) migrates to the agent host h9: its tag follows, the dev user's
        socket is refreshed, and the host_migrated message (both ids) is delivered."""
        db_session.add(DockerHostDB(id="h9", name="Agent Host", url="agent://", connection_type="agent"))
        db_session.add(Agent(id="agent-h9", host_id="h9", engine_id="engine-h9", version="1.0.0",
                             proto_version="1", capabilities={}, status="online"))
        db_session.commit()

        def fake_migrate(self, agent_id, source_host_id):
            AgentManager._transfer_tag_assignments(db_session, source_host_id, "h9")
            db_session.commit()
            return {"success": True, "host_id": "h9", "migrated_from": {"host_id": source_host_id, "host_name": "Dev Host"}}

        monkeypatch.setattr("agent.manager.AgentManager.migrate_from_host", fake_migrate)
        manager = main_module.monitor.manager
        with _connect(client, "dev-cookie") as ws:
            _drain_until(ws, "containers_update")
            assert manager.get_visible_hosts(next(iter(manager.active_connections))) == {"h1"}

            # The admin runs the migration (the dev user cannot see the target agent host yet).
            # Invoked on the socket's own loop: the handler broadcasts to this socket.
            admin = {"auth_type": "session", "user_id": ws_sessions["admin"].id, "username": "ws_admin"}
            http_request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1), "method": "POST", "path": "/"})
            result = ws.portal.call(
                lambda: main_module.migrate_agent_from_host("agent-h9", "h1", http_request, admin)
            )
            assert result["success"] is True

            message = ws.receive_json()
            assert message["type"] == "host_migrated"
            assert message["data"] == {"old_host_id": "h1", "old_host_name": "Dev Host", "new_host_id": "h9", "new_host_name": None}
            assert manager.get_visible_hosts(next(iter(manager.active_connections))) == {"h9"}


@pytest.mark.integration
class TestShellWebSocketVisibility:
    def test_hidden_host_closes_with_4404(self, client, ws_sessions):
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/shell/h2/ccc333333333", cookies={"session_id": "dev-cookie"}):
                pass
        assert exc.value.code == 4404

    def test_open_shell_is_registered_and_closed_when_its_host_becomes_hidden(self, client, ws_sessions, db_session, monkeypatch):
        """A shell the manager cannot see would survive a scope change; it must be tracked."""
        from starlette.websockets import WebSocketDisconnect
        manager = main_module.monitor.manager

        async def fake_session(websocket, host_id, container_id, session_data):
            await websocket.accept()
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass

        monkeypatch.setattr(main_module, "_handle_direct_shell_session", fake_session)
        with client.websocket_connect("/ws/shell/h1/aaa111111111", cookies={"session_id": "dev-cookie"}) as ws:
            assert [(uid, host) for (uid, host) in manager._shell_sockets.values()] == [(ws_sessions["dev"].id, "h1")]
            db_session.query(TagAssignment).filter_by(subject_id="h1").delete()
            db_session.commit()
            ws.portal.call(manager.refresh_visible_hosts_for_user, ws_sessions["dev"].id)
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            assert exc.value.code == 4404
        assert manager._shell_sockets == {}

    def test_revoke_racing_the_shell_registration_is_not_missed(self, client, ws_sessions, db_session, monkeypatch):
        """A scope change between the connect-time checks and register_shell() would leave
        the shell untracked; the generation guard re-runs the checks after registering."""
        from starlette.websockets import WebSocketDisconnect
        manager = main_module.monitor.manager
        original_register = manager.register_shell

        async def register_after_revoke(websocket, user_id, host_id):
            db_session.query(TagAssignment).filter_by(subject_id="h1").delete()
            db_session.commit()
            await manager.refresh_visible_hosts_for_user(user_id)
            await original_register(websocket, user_id, host_id)

        monkeypatch.setattr(manager, "register_shell", register_after_revoke)
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/ws/shell/h1/aaa111111111", cookies={"session_id": "dev-cookie"}):
                pass
        assert exc.value.code == 4404
        assert manager._shell_sockets == {}


# ---------------------------------------------------------------------------
# Issue #214 end to end: two OIDC-style tenants and an admin on one install
# ---------------------------------------------------------------------------

@pytest.fixture
def two_tenants(db_session, client, monkeypatch):
    """5 hosts tagged dev, 5 tagged test1; user A -> dev group, user B -> test1 group, admin unscoped.
    Sessions are cookie-based (OIDC users have no API key)."""
    hosts = {}
    for tag_name, prefix in (("dev", "dev"), ("test1", "t1")):
        for i in range(5):
            host_id = f"{prefix}-{i}"
            hosts[host_id] = DockerHost(id=host_id, name=f"{tag_name} host {i}", url=f"tcp://{host_id}:2376", status="online")
    monkeypatch.setattr(main_module.monitor, "hosts", hosts)
    for host_id, host in hosts.items():
        db_session.add(DockerHostDB(id=host_id, name=host.name, url=host.url))
    dev, test1 = _tag(db_session, "dev"), _tag(db_session, "test1")
    for host_id in hosts:
        tag = dev if host_id.startswith("dev") else test1
        db_session.add(TagAssignment(tag_id=tag.id, subject_type="host", subject_id=host_id))
    db_session.flush()
    containers = [_container(f"{'a' if h.startswith('dev') else 'b'}{i:011d}", h, host_name=hosts[h].name)
                  for i, h in enumerate(hosts)]

    async def get_containers(host_id=None):
        return [c for c in containers if host_id is None or c.host_id == host_id]

    monkeypatch.setattr(main_module.monitor, "get_containers", get_containers)
    monkeypatch.setattr(main_module.monitor, "get_last_containers", lambda: list(containers))

    user_a = _session_user(db_session, "alice", _group_with_all_caps(db_session, "Dev Team", dev))
    user_b = _session_user(db_session, "bob", _group_with_all_caps(db_session, "Test1 Team", test1))
    admin = _session_user(db_session, "root", _group_with_all_caps(db_session, "Admins"))
    sessions = {
        "a": {"user_id": user_a.id, "username": "alice"},
        "b": {"user_id": user_b.id, "username": "bob"},
        "admin": {"user_id": admin.id, "username": "root"},
    }
    monkeypatch.setattr("auth.cookie_sessions.cookie_session_manager.validate_session",
                        lambda session_id, client_ip: sessions.get(session_id))
    monkeypatch.setattr(deployment_routes, "_docker_monitor", main_module.monitor)
    monkeypatch.setattr(deployment_routes, "_database_manager", main_module.monitor.db)
    monkeypatch.setattr(stack_storage, "stack_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(stack_storage, "read_stack", AsyncMock(return_value=("services:\n  web:\n    image: nginx\n", {})))
    import alerts.api as alerts_api
    monkeypatch.setattr(alerts_api, "get_stats_client", lambda: SimpleNamespace(get_host_stats=AsyncMock(return_value={})))

    class Cookie:
        def __init__(self, name):
            self.cookies = {"session_id": name}

        def get(self, url, **kw):
            return client.get(url, cookies=self.cookies, **kw)

        def post(self, url, **kw):
            return client.post(url, cookies=self.cookies, **kw)

    return SimpleNamespace(a=Cookie("a"), b=Cookie("b"), admin=Cookie("admin"), dev=dev, test1=test1,
                           session=db_session, user_a=user_a)


@pytest.mark.integration
class TestOIDCUserScopeFlow:
    DEV = {f"dev-{i}" for i in range(5)}
    TEST1 = {f"t1-{i}" for i in range(5)}

    def _hosts(self, caller):
        response = caller.get("/api/hosts")
        assert response.status_code == 200, response.text
        return {h["id"] for h in response.json()}

    def test_each_tenant_sees_only_its_hosts_and_admin_sees_all(self, two_tenants):
        assert self._hosts(two_tenants.a) == self.DEV
        assert self._hosts(two_tenants.b) == self.TEST1
        assert self._hosts(two_tenants.admin) == self.DEV | self.TEST1
        assert {c["host_id"] for c in two_tenants.a.get("/api/containers").json()} == self.DEV
        assert {h["id"] for h in two_tenants.a.get("/api/dashboard/hosts").json()["groups"]["All Hosts"]} == self.DEV

    def test_cross_tenant_reads_and_actions_are_404(self, two_tenants):
        assert two_tenants.a.get("/api/hosts/t1-0/metrics").status_code == 404
        assert two_tenants.a.get("/api/hosts/dev-0/metrics").status_code != 404
        assert two_tenants.b.post("/api/hosts/dev-0/containers/a00000000000/restart").status_code == 404
        assert two_tenants.a.post("/api/deployments/deploy",
                                  json={"stack_name": "web", "host_id": "t1-2", "action": "up"}).json() == {"detail": "Host not found"}

    def test_alert_metric_capabilities_lists_only_own_hosts(self, two_tenants):
        caps = two_tenants.a.get("/api/alerts/metrics/capabilities").json()["hosts"]
        assert {h["host_id"] for h in caps} == self.DEV
        assert {h["host_id"] for h in two_tenants.admin.get("/api/alerts/metrics/capabilities").json()["hosts"]} == self.DEV | self.TEST1

    def test_untagging_every_dev_host_leaves_alice_seeing_nothing_not_everything(self, two_tenants):
        """The scope tag must survive tag cleanup: a cascade would silently make the group unrestricted."""
        s = two_tenants.session
        s.query(TagAssignment).filter_by(tag_id=two_tenants.dev.id).delete()
        two_tenants.dev.last_used_at = datetime.now(timezone.utc) - timedelta(days=90)
        s.commit()

        stand_in = SimpleNamespace(get_session=lambda: nullcontext(s))
        assert DatabaseManager.cleanup_unused_tags(stand_in, days_unused=1) == 0
        assert s.query(Tag).filter_by(id=two_tenants.dev.id).count() == 1

        assert self._hosts(two_tenants.a) == set()
        assert two_tenants.a.get("/api/containers").json() == []
        assert self._hosts(two_tenants.b) == self.TEST1
