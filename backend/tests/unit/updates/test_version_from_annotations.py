"""Versions published only as OCI annotations: the latest one from the registry, the running one kept in the record."""
import pytest

from checker_fakes import (
    CURRENT,
    LATEST,
    VERSION_LABEL,
    FakeClient,
    container_dict,
    digest,
    make_checker,
    registry_result,
    update_record,
)
from database import ContainerUpdate, DockerHostDB
from updates.database_updater import update_container_records_after_update

HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"


def annotated(result_digest, version, labels=None):
    """What resolve_tag returns for an image whose version is an annotation."""
    result = registry_result(result_digest, labels=labels)
    result["manifest"]["annotated_version"] = version
    return result


def repo_digests(*digests):
    return [f"app@{value}" for value in digests]


async def run_check(checker, container):
    result = await checker._check_container_update(container)
    assert checker.registry.unexpected == []
    return result


def versions(result):
    return result["update_available"], result["current_version"], result["latest_version"]


@pytest.mark.usefixtures("changelog_stub", "credentials_stub")
class TestCheck:
    async def test_running_the_latest_image_takes_the_registry_version(self):
        client = FakeClient(repo_digests=repo_digests(LATEST))
        checker = make_checker({"app:stable": annotated(LATEST, "28.4.0")}, client=client)

        result = await run_check(checker, container_dict())

        assert versions(result) == (False, "28.4.0", "28.4.0")

    async def test_the_annotation_wins_over_a_label_inherited_from_the_base_image(self):
        # mongo:7 carries Ubuntu's version label; its annotation has the real version
        ubuntu = {VERSION_LABEL: "22.04"}
        client = FakeClient(repo_digests=repo_digests(LATEST), image_labels=ubuntu)
        checker = make_checker({"app:stable": annotated(LATEST, "7.0.48-jammy", labels=ubuntu)}, client=client)

        result = await run_check(checker, container_dict())

        assert versions(result) == (False, "7.0.48-jammy", "7.0.48-jammy")

    async def test_an_unchanged_digest_keeps_the_stored_version(self):
        client = FakeClient(repo_digests=repo_digests(CURRENT))
        record = update_record(current_digest=CURRENT, current_version="28.3.0")
        checker = make_checker({"app:stable": annotated(LATEST, "28.4.0")}, client=client, record=record)

        result = await run_check(checker, container_dict())

        assert versions(result) == (True, "28.3.0", "28.4.0")

    async def test_a_changed_digest_does_not_reuse_the_stored_version(self):
        client = FakeClient(repo_digests=repo_digests(CURRENT))
        record = update_record(current_digest=digest("7"), current_version="27.0.0")
        checker = make_checker({"app:stable": annotated(LATEST, "28.4.0")}, client=client, record=record)

        result = await run_check(checker, container_dict())

        assert versions(result) == (True, None, "28.4.0")

    async def test_a_version_from_the_tag_does_not_replace_the_local_label(self):
        # No version from the registry (no annotation, no label): the tag's "1.25" is cruder than the label
        client = FakeClient(repo_digests=repo_digests(LATEST), image_labels={VERSION_LABEL: "1.25.3"})
        checker = make_checker({"app:1.25": registry_result(LATEST)}, client=client)

        result = await run_check(checker, container_dict("app:1.25"))

        assert versions(result) == (False, "1.25.3", "1.25")


def add_record(db, new_digest_seen_by_check):
    with db.get_session() as session:
        session.add(DockerHostDB(id=HOST_ID, name="docker-1", url="unix:///var/run/docker.sock", is_active=True))
        session.flush()
        session.add(ContainerUpdate(
            container_id=f"{HOST_ID}:aaaaaaaaaaaa", host_id=HOST_ID, current_image="app:stable",
            current_digest="sha256:old", current_version="1.0.0",
            latest_digest=new_digest_seen_by_check, latest_version="1.1.0", update_available=True,
        ))
        session.commit()


def stored_current_version(db):
    with db.get_session() as session:
        return session.query(ContainerUpdate).one().current_version


def test_an_update_records_the_installed_version(db):
    add_record(db, new_digest_seen_by_check="sha256:new")

    assert update_container_records_after_update(db, HOST_ID, "aaaaaaaaaaaa", "bbbbbbbbbbbb", "app:stable",
                                                 "sha256:new", invalidate_cache=False)

    assert stored_current_version(db) == "1.1.0"


def test_an_update_to_another_digest_forgets_the_old_version(db):
    add_record(db, new_digest_seen_by_check="sha256:new")

    assert update_container_records_after_update(db, HOST_ID, "aaaaaaaaaaaa", "bbbbbbbbbbbb", "app:stable",
                                                 "sha256:other", invalidate_cache=False)

    assert stored_current_version(db) is None
