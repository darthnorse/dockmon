"""The unverified_image mark reaches the container table, and a marked update still counts as an update."""

import pytest

import main as main_module
from database import ContainerUpdate, DockerHostDB
from tests.integration.api.test_host_scope_filtering import (  # noqa: F401 - fixtures
    HOSTS,
    client,
    seeded_hosts,
    unrestricted_client,
)
from updates.update_checker import UpdateChecker

MARKED = "h1:aaa111111111"
PLAIN = "h2:ccc333333333"


@pytest.fixture
def update_rows(db_session, seeded_hosts):
    for host_id, host in HOSTS.items():
        db_session.add(DockerHostDB(id=host_id, name=host.name, url=host.url))
    db_session.flush()
    for key, status in ((MARKED, "unverified_image"), (PLAIN, None)):
        db_session.add(ContainerUpdate(container_id=key, host_id=key.split(":")[0], current_image="nginx:1.25.3",
                                       current_digest="sha256:x", latest_image="nginx:1", latest_digest="sha256:y",
                                       update_available=True, auto_update_enabled=True, floating_tag_mode="minor",
                                       check_status=status))
    db_session.commit()


def proven_check(key):
    host_id, container_id = key.split(":")
    UpdateChecker(db=main_module.monitor.db)._store_update_info(
        {"host_id": host_id, "id": container_id, "name": "c"},
        {"current_image": "nginx:1.25.3", "current_digest": "sha256:x", "latest_image": "nginx:1",
         "latest_digest": "sha256:y", "update_available": True, "registry_url": "docker.io",
         "platform": "linux/amd64", "floating_tag_mode": "minor", "check_status": None},
    )


@pytest.mark.integration
class TestUnverifiedImageApi:
    def test_auto_update_configs_carry_the_mark(self, unrestricted_client, update_rows):
        configs = unrestricted_client.get("/api/auto-update-configs").json()

        assert configs[MARKED] == {"auto_update_enabled": True, "floating_tag_mode": "minor",
                                   "check_status": "unverified_image"}
        assert configs[PLAIN]["check_status"] is None

    def test_mark_round_trip(self, unrestricted_client, update_rows):
        assert unrestricted_client.get("/api/auto-update-configs").json()[MARKED]["check_status"] == "unverified_image"

        proven_check(MARKED)

        assert unrestricted_client.get("/api/auto-update-configs").json()[MARKED]["check_status"] is None

    def test_marked_update_still_counts(self, unrestricted_client, update_rows):
        summary = unrestricted_client.get("/api/updates/summary").json()
        assert summary["total_updates"] == 2
        assert set(summary["containers_with_updates"]) == {MARKED, PLAIN}

        assert unrestricted_client.get("/api/dashboard/summary").json()["updates"]["available"] == 2

    def test_update_status_reports_the_mark(self, unrestricted_client, update_rows):
        status = unrestricted_client.get("/api/hosts/h1/containers/aaa111111111/update-status").json()

        assert status["status"] == "unverified_image"
        assert status["update_available"] is True
