"""The unverified_image mark is cleared by a successful update, and agent hosts prove against their own platform."""

import pytest

from database import Agent, ContainerUpdate, DockerHostDB
from updates.database_updater import update_container_records_after_update
from updates.update_checker import UpdateChecker

HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"


def test_successful_update_clears_the_mark(db):
    with db.get_session() as session:
        session.add(DockerHostDB(id=HOST_ID, name="docker-1", url="unix:///var/run/docker.sock", is_active=True))
        session.flush()
        session.add(ContainerUpdate(container_id=f"{HOST_ID}:aaaaaaaaaaaa", host_id=HOST_ID, current_image="app:1.0",
                                    current_digest="sha256:old", update_available=True, check_status="unverified_image"))
        session.commit()

    assert update_container_records_after_update(db, HOST_ID, "aaaaaaaaaaaa", "bbbbbbbbbbbb", "app:1.1",
                                                 "sha256:new", invalidate_cache=False)

    with db.get_session() as session:
        row = session.query(ContainerUpdate).one()
        assert (row.container_id, row.update_available, row.check_status) == (f"{HOST_ID}:bbbbbbbbbbbb", False, None)


@pytest.mark.parametrize("arch, platform", [("arm64", "linux/arm64"), (None, "linux/amd64")])
def test_agent_platform_comes_from_the_agent_record(db, arch, platform):
    with db.get_session() as session:
        session.add(DockerHostDB(id=HOST_ID, name="agent-1", url="agent://", connection_type="agent", is_active=True))
        session.flush()
        session.add(Agent(id="agent-1", host_id=HOST_ID, engine_id="engine-1", version="1.2.0", proto_version="1.0",
                          capabilities={}, status="online", agent_arch=arch))
        session.commit()

    assert UpdateChecker(db=db)._agent_platform(HOST_ID) == platform


def test_host_without_an_agent_defaults_to_amd64(db):
    assert UpdateChecker(db=db)._agent_platform(HOST_ID) == "linux/amd64"
