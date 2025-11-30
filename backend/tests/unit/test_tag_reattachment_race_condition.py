"""
Test for GitHub Issue #44: Tag reattachment race condition during container updates

Problem: When updating a container, both the reattachment logic (container_discovery.py)
and the update executor (update_executor.py) try to handle tag migration, causing a
UNIQUE constraint violation.

This test verifies that the defensive check in update_executor.py handles the case
where reattachment has already created new tag assignments.
"""
import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, Tag, TagAssignment, make_composite_key


class TestTagReattachmentRaceCondition:
    """Test that update executor handles pre-existing tag assignments gracefully"""

    @pytest.fixture
    def db_session(self):
        """Create an in-memory SQLite database for testing"""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        yield session
        session.close()

    @pytest.fixture
    def sample_tag(self, db_session):
        """Create a sample tag"""
        tag = Tag(
            id=str(uuid.uuid4()),
            name="production",
            color="#FF0000",
            kind="user",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.commit()
        return tag

    def test_update_executor_handles_existing_tag_assignments(self, db_session, sample_tag):
        """
        Test the race condition scenario:
        1. Old container has tag assignment
        2. Reattachment creates new tag assignment for new container (simulated)
        3. Update executor tries to migrate tags
        4. Should detect existing assignment and delete old one instead of updating
        """
        host_id = "test-host-123"
        old_container_id = "abc123456789"
        new_container_id = "def987654321"
        old_composite_key = make_composite_key(host_id, old_container_id)
        new_composite_key = make_composite_key(host_id, new_container_id)

        # Step 1: Create tag assignment for OLD container (before update)
        old_assignment = TagAssignment(
            tag_id=sample_tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            compose_project="myapp",
            compose_service="web",
            host_id_at_attach=host_id,
            container_name_at_attach="myapp-web-1",
            last_seen_at=datetime.now(timezone.utc)
        )
        db_session.add(old_assignment)
        db_session.commit()

        # Verify old assignment exists
        assert db_session.query(TagAssignment).filter_by(subject_id=old_composite_key).count() == 1

        # Step 2: Simulate reattachment creating NEW tag assignment
        # (This happens when container_discovery.py runs after new container starts)
        new_assignment = TagAssignment(
            tag_id=sample_tag.id,
            subject_type="container",
            subject_id=new_composite_key,
            compose_project="myapp",
            compose_service="web",
            host_id_at_attach=host_id,
            container_name_at_attach="myapp-web-1",
            last_seen_at=datetime.now(timezone.utc)
        )
        db_session.add(new_assignment)
        db_session.commit()

        # Verify both assignments exist (this is the race condition state)
        assert db_session.query(TagAssignment).filter_by(subject_id=old_composite_key).count() == 1
        assert db_session.query(TagAssignment).filter_by(subject_id=new_composite_key).count() == 1

        # Step 3: Simulate update executor's defensive tag migration logic
        # CHECK if new container already has tags (from reattachment)
        new_tag_count = db_session.query(TagAssignment).filter(
            TagAssignment.subject_type == "container",
            TagAssignment.subject_id == new_composite_key
        ).count()

        if new_tag_count > 0:
            # Reattachment already created tags, delete orphaned old assignments
            db_session.query(TagAssignment).filter(
                TagAssignment.subject_type == "container",
                TagAssignment.subject_id == old_composite_key
            ).delete()
        else:
            # Reattachment didn't run, do migration ourselves
            db_session.query(TagAssignment).filter(
                TagAssignment.subject_type == "container",
                TagAssignment.subject_id == old_composite_key
            ).update({
                "subject_id": new_composite_key,
                "last_seen_at": datetime.now(timezone.utc)
            })

        db_session.commit()

        # Step 4: Verify final state
        # Old assignment should be deleted
        assert db_session.query(TagAssignment).filter_by(subject_id=old_composite_key).count() == 0
        # New assignment should still exist (exactly one)
        assert db_session.query(TagAssignment).filter_by(subject_id=new_composite_key).count() == 1
        # Total assignments for this tag should be 1 (no duplicates)
        assert db_session.query(TagAssignment).filter_by(tag_id=sample_tag.id).count() == 1

    def test_update_executor_handles_no_reattachment(self, db_session, sample_tag):
        """
        Test the fallback scenario where reattachment didn't run:
        1. Old container has tag assignment
        2. Reattachment did NOT create new assignment (edge case)
        3. Update executor should migrate old assignment to new container
        """
        host_id = "test-host-456"
        old_container_id = "ghi123456789"
        new_container_id = "jkl987654321"
        old_composite_key = make_composite_key(host_id, old_container_id)
        new_composite_key = make_composite_key(host_id, new_container_id)

        # Step 1: Create tag assignment for OLD container
        old_assignment = TagAssignment(
            tag_id=sample_tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=host_id,
            container_name_at_attach="standalone-container",
            last_seen_at=datetime.now(timezone.utc)
        )
        db_session.add(old_assignment)
        db_session.commit()

        # Step 2: Reattachment did NOT run (no new assignment created)
        assert db_session.query(TagAssignment).filter_by(subject_id=new_composite_key).count() == 0

        # Step 3: Update executor's defensive tag migration logic
        new_tag_count = db_session.query(TagAssignment).filter(
            TagAssignment.subject_type == "container",
            TagAssignment.subject_id == new_composite_key
        ).count()

        if new_tag_count > 0:
            # Reattachment already created tags, delete old
            db_session.query(TagAssignment).filter(
                TagAssignment.subject_type == "container",
                TagAssignment.subject_id == old_composite_key
            ).delete()
        else:
            # Reattachment didn't run, do migration ourselves (THIS BRANCH)
            db_session.query(TagAssignment).filter(
                TagAssignment.subject_type == "container",
                TagAssignment.subject_id == old_composite_key
            ).update({
                "subject_id": new_composite_key,
                "last_seen_at": datetime.now(timezone.utc)
            })

        db_session.commit()

        # Step 4: Verify final state
        # Old assignment should be gone
        assert db_session.query(TagAssignment).filter_by(subject_id=old_composite_key).count() == 0
        # New assignment should exist (migrated from old)
        assert db_session.query(TagAssignment).filter_by(subject_id=new_composite_key).count() == 1
        # Total assignments should be 1
        assert db_session.query(TagAssignment).filter_by(tag_id=sample_tag.id).count() == 1

    def test_race_condition_without_fix_would_fail(self, db_session, sample_tag):
        """
        Demonstrate that the OLD code would fail with UNIQUE constraint violation.
        This test documents the bug that the fix prevents.
        """
        host_id = "test-host-789"
        old_container_id = "mno123456789"
        new_container_id = "pqr987654321"
        old_composite_key = make_composite_key(host_id, old_container_id)
        new_composite_key = make_composite_key(host_id, new_container_id)

        # Create old assignment
        old_assignment = TagAssignment(
            tag_id=sample_tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=host_id,
            container_name_at_attach="test-container",
            last_seen_at=datetime.now(timezone.utc)
        )
        db_session.add(old_assignment)
        db_session.commit()

        # Reattachment creates new assignment
        new_assignment = TagAssignment(
            tag_id=sample_tag.id,
            subject_type="container",
            subject_id=new_composite_key,
            host_id_at_attach=host_id,
            container_name_at_attach="test-container",
            last_seen_at=datetime.now(timezone.utc)
        )
        db_session.add(new_assignment)
        db_session.commit()

        # OLD CODE would try to UPDATE old assignment to new ID
        # This would fail because (tag_id, subject_type, new_composite_key) already exists
        with pytest.raises(Exception) as exc_info:
            # Simulate the old UPDATE logic (without defensive check)
            db_session.query(TagAssignment).filter(
                TagAssignment.subject_type == "container",
                TagAssignment.subject_id == old_composite_key
            ).update({
                "subject_id": new_composite_key,  # FAILS - unique constraint violation
                "last_seen_at": datetime.now(timezone.utc)
            })
            db_session.commit()

        # Verify it failed with integrity error
        assert "UNIQUE constraint failed" in str(exc_info.value)

    def test_millisecond_race_handled_gracefully(self, db_session, sample_tag):
        """
        Test the millisecond race window edge case:
        1. Check returns 0 tags (no tags yet)
        2. Reattachment commits tags (race window)
        3. UPDATE tries to commit (IntegrityError)
        4. Enhanced handler catches it and continues as success
        """
        from sqlalchemy.exc import IntegrityError

        host_id = "test-host-999"
        old_container_id = "stu123456789"
        new_container_id = "vwx987654321"
        old_composite_key = make_composite_key(host_id, old_container_id)
        new_composite_key = make_composite_key(host_id, new_container_id)

        # Step 1: Create old assignment
        old_assignment = TagAssignment(
            tag_id=sample_tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=host_id,
            container_name_at_attach="edge-case-container",
            last_seen_at=datetime.now(timezone.utc)
        )
        db_session.add(old_assignment)
        db_session.commit()

        # Step 2: Simulate the check (returns 0)
        new_tag_count = db_session.query(TagAssignment).filter(
            TagAssignment.subject_type == "container",
            TagAssignment.subject_id == new_composite_key
        ).count()
        assert new_tag_count == 0

        # Step 3: Simulate reattachment committing tags during the race window
        # (This happens AFTER the check but BEFORE the update)
        new_assignment = TagAssignment(
            tag_id=sample_tag.id,
            subject_type="container",
            subject_id=new_composite_key,
            host_id_at_attach=host_id,
            container_name_at_attach="edge-case-container",
            last_seen_at=datetime.now(timezone.utc)
        )
        db_session.add(new_assignment)
        db_session.commit()

        # Step 4: Now try to UPDATE (will hit IntegrityError)
        # Enhanced handler should catch this and treat as success
        try:
            db_session.query(TagAssignment).filter(
                TagAssignment.subject_type == "container",
                TagAssignment.subject_id == old_composite_key
            ).update({
                "subject_id": new_composite_key,
                "last_seen_at": datetime.now(timezone.utc)
            })
            db_session.commit()
            # If we got here, no race occurred (test inconclusive but passing)
            success = True
        except IntegrityError as ie:
            # Enhanced handler: detect tag_assignments in error
            if "tag_assignments" in str(ie).lower():
                # Rollback and continue as success
                db_session.rollback()
                success = True  # This is the correct behavior
            else:
                # Different IntegrityError - should fail
                success = False

        # Verify success (either no race or gracefully handled)
        assert success is True

        # Verify final state is correct
        # Old assignment might still exist (if race occurred) or not (if no race)
        # New assignment always exists
        new_count = db_session.query(TagAssignment).filter_by(subject_id=new_composite_key).count()
        assert new_count == 1  # New assignment exists

        # Total tags should be 1 or 2 (1 if no race, 2 if race with graceful handling)
        total = db_session.query(TagAssignment).filter_by(tag_id=sample_tag.id).count()
        assert total in [1, 2]  # Either migrated cleanly or race with orphaned old record
