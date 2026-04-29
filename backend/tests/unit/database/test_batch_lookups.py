"""
Unit tests for the batch lookup methods on DatabaseManager.

These methods collapse N per-container DB calls into one per host, used by
container_discovery to avoid the N+1 pattern that previously dominated the
Python side of /api/containers latency on hosts with hundreds of containers.

Covered:
- get_tags_for_host: returns dict[short_container_id, list[str]]
- get_desired_states_for_host: returns dict[short_container_id, (state, web_ui_url)]
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest

import database
from database import (
    ContainerDesiredState,
    DatabaseManager,
    DockerHostDB,
    Tag,
    TagAssignment,
    make_composite_key,
)


@pytest.fixture(scope="function")
def db_manager():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_batch_")
    os.close(fd)
    database._database_manager_instance = None
    db = DatabaseManager(db_path=db_path)
    try:
        yield db
    finally:
        if hasattr(db, "engine"):
            db.engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass
        database._database_manager_instance = None


@pytest.fixture
def host(db_manager):
    host_id = str(uuid.uuid4())
    with db_manager.get_session() as session:
        session.add(DockerHostDB(
            id=host_id,
            name="test-host",
            url="unix:///var/run/docker.sock",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        session.commit()
    return host_id


def _add_tag(session, tag_id: str, name: str) -> Tag:
    tag = Tag(id=tag_id, name=name, created_at=datetime.now(timezone.utc))
    session.add(tag)
    return tag


def _add_assignment(session, *, tag_id: str, host_id: str, container_id: str, order_index: int = 0) -> None:
    session.add(TagAssignment(
        tag_id=tag_id,
        subject_type="container",
        subject_id=make_composite_key(host_id, container_id),
        host_id_at_attach=host_id,
        order_index=order_index,
        last_seen_at=datetime.now(timezone.utc),
    ))


# -----------------------------------------------------------------------------
# get_tags_for_host
# -----------------------------------------------------------------------------

def test_get_tags_for_host_empty(db_manager, host):
    assert db_manager.get_tags_for_host(host) == {}


def test_get_tags_for_host_blank_host_id(db_manager):
    assert db_manager.get_tags_for_host("") == {}


def test_get_tags_for_host_returns_tags_per_container(db_manager, host):
    with db_manager.get_session() as session:
        _add_tag(session, "tag-prod", "production")
        _add_tag(session, "tag-web", "web")
        _add_tag(session, "tag-db", "db")
        _add_assignment(session, tag_id="tag-prod", host_id=host, container_id="aaaaaaaaaaaa", order_index=0)
        _add_assignment(session, tag_id="tag-web", host_id=host, container_id="aaaaaaaaaaaa", order_index=1)
        _add_assignment(session, tag_id="tag-db", host_id=host, container_id="bbbbbbbbbbbb", order_index=0)
        session.commit()

    tags = db_manager.get_tags_for_host(host)
    assert tags == {
        "aaaaaaaaaaaa": ["production", "web"],
        "bbbbbbbbbbbb": ["db"],
    }


def test_get_tags_for_host_preserves_order_index(db_manager, host):
    with db_manager.get_session() as session:
        _add_tag(session, "t-c", "c-tag")
        _add_tag(session, "t-a", "a-tag")
        _add_tag(session, "t-b", "b-tag")
        # Insert in reverse-of-display order to prove ordering is by
        # order_index, not insertion or alphabetical.
        _add_assignment(session, tag_id="t-c", host_id=host, container_id="aaaaaaaaaaaa", order_index=2)
        _add_assignment(session, tag_id="t-a", host_id=host, container_id="aaaaaaaaaaaa", order_index=0)
        _add_assignment(session, tag_id="t-b", host_id=host, container_id="aaaaaaaaaaaa", order_index=1)
        session.commit()

    tags = db_manager.get_tags_for_host(host)
    assert tags == {"aaaaaaaaaaaa": ["a-tag", "b-tag", "c-tag"]}


def test_get_tags_for_host_isolates_other_hosts(db_manager, host):
    other_host = str(uuid.uuid4())
    with db_manager.get_session() as session:
        session.add(DockerHostDB(
            id=other_host,
            name="other",
            url="unix:///var/run/docker.sock",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        _add_tag(session, "tag-x", "x")
        _add_assignment(session, tag_id="tag-x", host_id=host, container_id="aaaaaaaaaaaa")
        _add_assignment(session, tag_id="tag-x", host_id=other_host, container_id="cccccccccccc")
        session.commit()

    assert db_manager.get_tags_for_host(host) == {"aaaaaaaaaaaa": ["x"]}
    assert db_manager.get_tags_for_host(other_host) == {"cccccccccccc": ["x"]}


# -----------------------------------------------------------------------------
# get_desired_states_for_host
# -----------------------------------------------------------------------------

def test_get_desired_states_for_host_empty(db_manager, host):
    assert db_manager.get_desired_states_for_host(host) == {}


def test_get_desired_states_for_host_blank_host_id(db_manager):
    assert db_manager.get_desired_states_for_host("") == {}


def test_get_desired_states_for_host_returns_state_and_url(db_manager, host):
    with db_manager.get_session() as session:
        session.add(ContainerDesiredState(
            host_id=host,
            container_id="aaaaaaaaaaaa",
            container_name="web",
            desired_state="should_run",
            web_ui_url="https://example.test/web",
        ))
        session.add(ContainerDesiredState(
            host_id=host,
            container_id="bbbbbbbbbbbb",
            container_name="batch",
            desired_state="on_demand",
            web_ui_url=None,
        ))
        session.commit()

    states = db_manager.get_desired_states_for_host(host)
    assert states == {
        "aaaaaaaaaaaa": ("should_run", "https://example.test/web"),
        "bbbbbbbbbbbb": ("on_demand", None),
    }


def test_get_desired_states_for_host_isolates_other_hosts(db_manager, host):
    other_host = str(uuid.uuid4())
    with db_manager.get_session() as session:
        session.add(DockerHostDB(
            id=other_host,
            name="other",
            url="unix:///var/run/docker.sock",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        session.add(ContainerDesiredState(
            host_id=host,
            container_id="aaaaaaaaaaaa",
            container_name="a",
            desired_state="should_run",
        ))
        session.add(ContainerDesiredState(
            host_id=other_host,
            container_id="cccccccccccc",
            container_name="c",
            desired_state="on_demand",
        ))
        session.commit()

    assert db_manager.get_desired_states_for_host(host) == {
        "aaaaaaaaaaaa": ("should_run", None),
    }
    assert db_manager.get_desired_states_for_host(other_host) == {
        "cccccccccccc": ("on_demand", None),
    }
