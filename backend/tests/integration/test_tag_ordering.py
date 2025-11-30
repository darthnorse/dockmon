"""
Unit tests for tag ordering functionality

Tests verify:
- order_index column exists in tag_assignments table
- Tags are returned in order_index order (not alphabetically)
- Tags can be updated with ordered list
- Order indices are sequential and sanitized
- Backwards compatibility with add/remove operations
"""

import pytest
import uuid
from datetime import datetime, timezone
from database import DatabaseManager, Tag, TagAssignment, Base
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database for testing"""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    yield session

    session.close()


@pytest.fixture
def db_manager(in_memory_db):
    """Create DatabaseManager with in-memory database"""
    db = DatabaseManager()
    # Override the session method to use our in-memory DB
    db._test_session = in_memory_db
    original_get_session = db.get_session

    from contextlib import contextmanager
    @contextmanager
    def test_get_session():
        yield in_memory_db

    db.get_session = test_get_session

    yield db

    db.get_session = original_get_session


def test_tag_assignments_have_order_index(in_memory_db):
    """Verify order_index column exists in tag_assignments table"""
    inspector = inspect(in_memory_db.bind)
    columns = [col['name'] for col in inspector.get_columns('tag_assignments')]

    assert 'order_index' in columns, "order_index column should exist in tag_assignments table"


def test_get_tags_returns_ordered_list_not_alphabetical(db_manager, in_memory_db):
    """
    Tags should be returned in order_index order, NOT alphabetically

    This is the core bug fix - currently tags are sorted alphabetically,
    but they should preserve user-defined order.
    """
    # Arrange: Create tags in specific order (not alphabetical)
    tag_ids = {}
    for name in ["zebra", "apple", "mango"]:
        tag_id = str(uuid.uuid4())
        tag = Tag(
            id=tag_id,
            name=name,
            kind="host",
            color="#FF0000",
            last_used_at=datetime.now(timezone.utc)
        )
        in_memory_db.add(tag)
        in_memory_db.flush()
        tag_ids[name] = tag_id

    # Assign in order: zebra (0), apple (1), mango (2)
    host_id = "test-host-123"
    for idx, name in enumerate(["zebra", "apple", "mango"]):
        assignment = TagAssignment(
            tag_id=tag_ids[name],
            subject_type="host",
            subject_id=host_id,
            order_index=idx,
            host_id_at_attach=host_id,
            container_name_at_attach="test-host"
        )
        in_memory_db.add(assignment)
    in_memory_db.commit()

    # Act: Get tags for host
    tags = db_manager.get_tags_for_subject("host", host_id)

    # Assert: Tags in order_index order, NOT alphabetical
    assert tags == ["zebra", "apple", "mango"], \
        "Tags should be in order_index order (zebra, apple, mango)"
    assert tags != ["apple", "mango", "zebra"], \
        "Tags should NOT be alphabetically sorted"


def test_update_tags_with_ordered_list(db_manager, in_memory_db):
    """
    Send ordered list via ordered_tags parameter, verify order persists
    """
    # Arrange: Create some initial tags
    host_id = "test-host-456"
    initial_tags = ["prod", "us-west", "critical"]

    # First, create the tags in database
    for tag_name in initial_tags:
        tag = Tag(
            id=str(uuid.uuid4()),
            name=tag_name,
            kind="host",
            color="#00FF00",
            last_used_at=datetime.now(timezone.utc)
        )
        in_memory_db.add(tag)
    in_memory_db.commit()

    # Act: Update with ordered list
    result = db_manager.update_subject_tags(
        subject_type="host",
        subject_id=host_id,
        ordered_tags=initial_tags,
        host_id_at_attach=host_id,
        container_name_at_attach="test-host"
    )

    # Assert: Returned tags match input order
    assert result == initial_tags, "Returned tags should match input order"

    # Verify order persists in database
    stored_tags = db_manager.get_tags_for_subject("host", host_id)
    assert stored_tags == initial_tags, "Stored tags should preserve order"

    # Verify order indices are sequential (0, 1, 2)
    assignments = in_memory_db.query(TagAssignment).filter(
        TagAssignment.subject_type == "host",
        TagAssignment.subject_id == host_id
    ).order_by(TagAssignment.order_index).all()

    assert len(assignments) == 3, "Should have 3 tag assignments"
    assert assignments[0].order_index == 0, "First assignment should have order_index 0"
    assert assignments[1].order_index == 1, "Second assignment should have order_index 1"
    assert assignments[2].order_index == 2, "Third assignment should have order_index 2"


def test_reorder_existing_tags(db_manager, in_memory_db):
    """
    User reorders existing tags - verify new order persists
    """
    # Arrange: Start with tags in one order
    host_id = "test-host-789"
    initial_order = ["prod", "dev", "staging"]

    # Create tags
    for tag_name in initial_order:
        tag = Tag(id=str(uuid.uuid4()), name=tag_name, kind="host", color="#0000FF", last_used_at=datetime.now(timezone.utc))
        in_memory_db.add(tag)
    in_memory_db.commit()

    # Set initial order
    db_manager.update_subject_tags(
        "host", host_id,
        ordered_tags=initial_order,
        host_id_at_attach=host_id,
        container_name_at_attach="test-host"
    )

    # Act: Reorder to different sequence
    new_order = ["staging", "prod", "dev"]
    result = db_manager.update_subject_tags(
        "host", host_id,
        ordered_tags=new_order,
        host_id_at_attach=host_id,
        container_name_at_attach="test-host"
    )

    # Assert: New order persists
    assert result == new_order, "Should return new order"
    stored_tags = db_manager.get_tags_for_subject("host", host_id)
    assert stored_tags == new_order, "New order should persist in database"


def test_backwards_compatibility_add_remove(db_manager, in_memory_db):
    """
    Verify add/remove mode still works (backwards compatibility)

    When using tags_to_add/tags_to_remove, new tags should be appended
    to the end with sequential order_index values.
    """
    # Arrange: Start with existing tags
    host_id = "test-host-compat"

    # Create initial tags
    for tag_name in ["prod", "dev"]:
        tag = Tag(id=str(uuid.uuid4()), name=tag_name, kind="host", color="#FF00FF", last_used_at=datetime.now(timezone.utc))
        in_memory_db.add(tag)
    in_memory_db.commit()

    db_manager.update_subject_tags(
        "host", host_id,
        ordered_tags=["prod", "dev"],
        host_id_at_attach=host_id,
        container_name_at_attach="test-host"
    )

    # Act: Add a tag using add/remove mode
    result = db_manager.update_subject_tags(
        "host", host_id,
        tags_to_add=["staging"],
        tags_to_remove=[],
        host_id_at_attach=host_id,
        container_name_at_attach="test-host"
    )

    # Assert: New tag appended to end
    stored_tags = db_manager.get_tags_for_subject("host", host_id)
    assert "staging" in stored_tags, "New tag should be added"
    assert stored_tags.index("staging") == 2, "New tag should be at the end (index 2)"

    # Verify order indices
    assignments = in_memory_db.query(TagAssignment).filter(
        TagAssignment.subject_type == "host",
        TagAssignment.subject_id == host_id
    ).order_by(TagAssignment.order_index).all()

    assert len(assignments) == 3, "Should have 3 tag assignments"
    assert assignments[2].order_index == 2, "New tag should have order_index 2"


def test_empty_ordered_list_removes_all_tags(db_manager, in_memory_db):
    """
    Sending empty ordered_tags list should remove all tags
    """
    # Arrange: Create host with tags
    host_id = "test-host-empty"

    for tag_name in ["tag1", "tag2", "tag3"]:
        tag = Tag(id=str(uuid.uuid4()), name=tag_name, kind="host", color="#00FFFF", last_used_at=datetime.now(timezone.utc))
        in_memory_db.add(tag)
    in_memory_db.commit()

    db_manager.update_subject_tags(
        "host", host_id,
        ordered_tags=["tag1", "tag2", "tag3"],
        host_id_at_attach=host_id,
        container_name_at_attach="test-host"
    )

    # Act: Send empty list
    result = db_manager.update_subject_tags(
        "host", host_id,
        ordered_tags=[],
        host_id_at_attach=host_id,
        container_name_at_attach="test-host"
    )

    # Assert: All tags removed
    assert result == [], "Should return empty list"
    stored_tags = db_manager.get_tags_for_subject("host", host_id)
    assert stored_tags == [], "All tags should be removed from database"


def test_ordered_tags_and_add_remove_are_mutually_exclusive(db_manager, in_memory_db):
    """
    Cannot use ordered_tags with tags_to_add/tags_to_remove simultaneously

    This test verifies the API contract - should raise ValueError if
    both modes are used together.
    """
    host_id = "test-host-exclusive"

    # Act & Assert: Should raise error when mixing modes
    with pytest.raises(ValueError, match="Cannot use both ordered_tags and tags_to_add/tags_to_remove"):
        db_manager.update_subject_tags(
            "host", host_id,
            tags_to_add=["tag1"],
            ordered_tags=["tag2", "tag3"],
            host_id_at_attach=host_id,
            container_name_at_attach="test-host"
        )


def test_primary_tag_is_first_in_order(db_manager, in_memory_db):
    """
    First tag in ordered list should be the primary tag

    This is the user-facing feature - when user drags a tag to first position,
    it becomes the "primary tag" for that host.
    """
    # Arrange: Create tags with specific order
    host_id = "test-host-primary"
    ordered_tags = ["critical", "prod", "us-west"]

    for tag_name in ordered_tags:
        tag = Tag(id=str(uuid.uuid4()), name=tag_name, kind="host", color="#FFFF00", last_used_at=datetime.now(timezone.utc))
        in_memory_db.add(tag)
    in_memory_db.commit()

    db_manager.update_subject_tags(
        "host", host_id,
        ordered_tags=ordered_tags,
        host_id_at_attach=host_id,
        container_name_at_attach="test-host"
    )

    # Act: Get tags
    tags = db_manager.get_tags_for_subject("host", host_id)

    # Assert: First tag is "critical"
    assert tags[0] == "critical", "First tag should be 'critical' (the primary tag)"

    # Reorder: Make "us-west" primary
    new_order = ["us-west", "critical", "prod"]
    db_manager.update_subject_tags(
        "host", host_id,
        ordered_tags=new_order,
        host_id_at_attach=host_id,
        container_name_at_attach="test-host"
    )

    tags = db_manager.get_tags_for_subject("host", host_id)
    assert tags[0] == "us-west", "After reordering, 'us-west' should be primary"
