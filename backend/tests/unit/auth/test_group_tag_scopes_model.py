"""GroupTagScope model: a group's host visibility restricted to hosts carrying any listed tag.

Zero rows for a group = unrestricted. A scope tag cannot be deleted while
referenced (RESTRICT FK + cleanup exclusion) - losing a scope must be an explicit
admin action, never a tag-cleanup side effect.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import CustomGroup, DatabaseManager, GroupTagScope, Tag, TagAssignment


def _tag(session: Session, name: str, last_used_days_ago: int | None = None) -> Tag:
    tag = Tag(id=str(uuid.uuid4()), name=name, color="#3b82f6")
    if last_used_days_ago is not None:
        tag.last_used_at = datetime.now(timezone.utc) - timedelta(days=last_used_days_ago)
    session.add(tag)
    session.flush()
    return tag


def _group(session: Session, name: str) -> CustomGroup:
    group = CustomGroup(name=name, description="scope test")
    session.add(group)
    session.flush()
    return group


def _cleanup_unused_tags(session: Session, days_unused: int) -> int:
    """Run DatabaseManager.cleanup_unused_tags against the test session without
    touching the process-wide DatabaseManager singleton."""
    @contextmanager
    def get_session():
        yield session

    stand_in = SimpleNamespace(get_session=get_session)
    return DatabaseManager.cleanup_unused_tags(stand_in, days_unused=days_unused)


class TestGroupTagScopeModel:
    def test_created_with_required_fields(self, db_session: Session):
        group = _group(db_session, "Scoped")
        tag = _tag(db_session, "dev")

        scope = GroupTagScope(group_id=group.id, tag_id=tag.id)
        db_session.add(scope)
        db_session.commit()

        assert scope.id is not None
        assert scope.created_at is not None
        assert scope.group.id == group.id
        assert scope.tag.id == tag.id
        assert [s.tag_id for s in group.tag_scopes] == [tag.id]

    def test_group_tag_pair_is_unique(self, db_session: Session):
        group = _group(db_session, "Scoped")
        tag = _tag(db_session, "dev")
        db_session.add(GroupTagScope(group_id=group.id, tag_id=tag.id))
        db_session.commit()

        db_session.add(GroupTagScope(group_id=group.id, tag_id=tag.id))
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_group_delete_cascades_to_scopes(self, db_session: Session):
        group = _group(db_session, "Scoped")
        tag = _tag(db_session, "dev")
        db_session.add(GroupTagScope(group_id=group.id, tag_id=tag.id))
        db_session.commit()

        db_session.delete(group)
        db_session.commit()

        assert db_session.query(GroupTagScope).count() == 0
        assert db_session.query(Tag).filter_by(id=tag.id).one() is not None

    def test_tag_delete_is_refused_while_scoped(self, db_session: Session):
        group = _group(db_session, "Scoped")
        tag = _tag(db_session, "dev")
        db_session.add(GroupTagScope(group_id=group.id, tag_id=tag.id))
        db_session.commit()
        tag_id = tag.id
        db_session.expunge_all()

        with pytest.raises(IntegrityError):
            db_session.execute(Tag.__table__.delete().where(Tag.__table__.c.id == tag_id))
        db_session.rollback()

        assert db_session.query(GroupTagScope).count() == 1


class TestCleanupExcludesScopedTags:
    def test_cleanup_keeps_scoped_tag_without_assignments(self, db_session: Session):
        group = _group(db_session, "Scoped")
        scoped = _tag(db_session, "dev", last_used_days_ago=90)
        _tag(db_session, "stale", last_used_days_ago=90)
        db_session.add(GroupTagScope(group_id=group.id, tag_id=scoped.id))
        db_session.commit()

        deleted = _cleanup_unused_tags(db_session, days_unused=1)

        assert deleted == 1
        remaining = {t.name for t in db_session.query(Tag).all()}
        assert remaining == {"dev"}

    def test_cleanup_still_deletes_truly_unused_and_keeps_assigned(self, db_session: Session):
        assigned = _tag(db_session, "assigned", last_used_days_ago=90)
        _tag(db_session, "stale", last_used_days_ago=90)
        db_session.add(TagAssignment(tag_id=assigned.id, subject_type="host", subject_id="h1"))
        db_session.commit()

        deleted = _cleanup_unused_tags(db_session, days_unused=1)

        assert deleted == 1
        assert {t.name for t in db_session.query(Tag).all()} == {"assigned"}
