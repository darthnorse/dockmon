"""
Unit tests for tag management functionality.

Tests verify:
- Tag reattachment after container recreation (sticky tags)
- Compose identity matching (primary strategy)
- Container name matching (fallback strategy)
- Duplicate tag prevention
- Empty/null tag handling
- Composite key correctness
- Edge cases and error scenarios

NOTE: These tests use DatabaseManager with a test database.
They are borderline integration tests and may be moved to
integration test suite in Week 2.
"""

import pytest
import tempfile
import os
from datetime import datetime, timezone
from database import Tag, TagAssignment, DatabaseManager, make_composite_key, DockerHostDB


# Global test database manager
_test_db_manager = None


@pytest.fixture(scope="function")
def test_db_manager():
    """
    Create a fresh DatabaseManager for each test with a temporary database.

    This fixture handles the singleton pattern by creating a test database
    that DatabaseManager can use.
    """
    global _test_db_manager

    # Create temporary database file
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_dockmon_tags_")
    os.close(fd)

    try:
        # Reset singleton before creating new instance
        import database
        database._database_manager_instance = None

        # Create DatabaseManager with test database
        db_manager = DatabaseManager(db_path=db_path)
        _test_db_manager = db_manager

        yield db_manager

    finally:
        # Cleanup: Close connections and remove test database
        if _test_db_manager and hasattr(_test_db_manager, 'engine'):
            _test_db_manager.engine.dispose()

        try:
            os.unlink(db_path)
        except:
            pass

        # Reset singleton for next test
        database._database_manager_instance = None
        _test_db_manager = None


@pytest.fixture(scope="function")
def test_host(test_db_manager):
    """Create a test Docker host in the database"""
    with test_db_manager.get_session() as session:
        host = DockerHostDB(
            id="test-host-123",
            name="Test Host",
            url="unix:///var/run/docker.sock",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(host)
        session.commit()
        session.refresh(host)
        return host


class TestTagReattachmentComposeIdentity:
    """Test tag reattachment using compose project/service identity"""

    def test_reattach_tags_by_compose_identity_success(self, test_db_manager, test_host):
        """
        Tags should reattach to rebuilt container via compose identity.

        Scenario:
        - Container with compose labels has tags
        - Container is destroyed and recreated with new Docker ID
        - Same compose labels (project + service)
        - Tags should reattach to new container
        """
        # Setup: Old container with tags
        old_container_id = "abc123def456"
        old_composite_key = make_composite_key(test_host.id, old_container_id)

        # Store tag ID before session closes
        tag_id = "tag-1"

        with test_db_manager.get_session() as session:
            # Create tag
            tag = Tag(
                id=tag_id,
                name="production",
                color="#ff0000",
                kind="user",
                created_at=datetime.now(timezone.utc)
            )
            session.add(tag)

            # Create tag assignment for old container
            old_assignment = TagAssignment(
                tag_id=tag_id,
                subject_type="container",
                subject_id=old_composite_key,
                compose_project="myapp",
                compose_service="web",
                host_id_at_attach=test_host.id,
                container_name_at_attach="myapp-web-1",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(old_assignment)
            session.commit()

        # Action: Reattach tags to new container (same compose identity)
        new_container_id = "def456ghi789"
        reattached_tags = test_db_manager.reattach_tags_for_container(
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="myapp-web-1",
            compose_project="myapp",
            compose_service="web"
        )

        # Assert: Tag reattached
        assert len(reattached_tags) == 1
        assert "production" in reattached_tags

        # Verify: New assignment exists
        with test_db_manager.get_session() as session:
            new_composite_key = make_composite_key(test_host.id, new_container_id)
            new_assignment = session.query(TagAssignment).filter(
                TagAssignment.tag_id == tag_id,
                TagAssignment.subject_id == new_composite_key
            ).first()

            assert new_assignment is not None
            assert new_assignment.compose_project == "myapp"
            assert new_assignment.compose_service == "web"
            assert new_assignment.container_name_at_attach == "myapp-web-1"

    def test_reattach_multiple_tags_by_compose_identity(self, test_db_manager, test_host):
        """
        Multiple tags should all reattach via compose identity.

        Scenario:
        - Container has 3 tags
        - Container recreated with new ID
        - All 3 tags should reattach
        """
        old_container_id = "abc123def456"
        old_composite_key = make_composite_key(test_host.id, old_container_id)

        with test_db_manager.get_session() as session:
            # Create 3 tags
            tags = [
                Tag(id="tag-1", name="production", color="#ff0000", kind="user", created_at=datetime.now(timezone.utc)),
                Tag(id="tag-2", name="critical", color="#ff6600", kind="user", created_at=datetime.now(timezone.utc)),
                Tag(id="tag-3", name="monitored", color="#00ff00", kind="user", created_at=datetime.now(timezone.utc))
            ]
            for tag in tags:
                session.add(tag)

            # Create assignments for old container
            for tag in tags:
                assignment = TagAssignment(
                    tag_id=tag.id,
                    subject_type="container",
                    subject_id=old_composite_key,
                    compose_project="myapp",
                    compose_service="web",
                    host_id_at_attach=test_host.id,
                    container_name_at_attach="myapp-web-1",
                    created_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc)
                )
                session.add(assignment)
            session.commit()

        # Action: Reattach tags
        new_container_id = "def456ghi789"
        reattached_tags = test_db_manager.reattach_tags_for_container(
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="myapp-web-1",
            compose_project="myapp",
            compose_service="web"
        )

        # Assert: All 3 tags reattached
        assert len(reattached_tags) == 3
        assert "production" in reattached_tags
        assert "critical" in reattached_tags
        assert "monitored" in reattached_tags

    def test_reattach_tags_different_compose_service_no_match(self, test_db_manager, test_host):
        """
        Tags should NOT reattach if compose service differs.

        Scenario:
        - Old container: myapp/web
        - New container: myapp/db (different service)
        - Tags should NOT reattach
        """
        old_container_id = "abc123def456"
        old_composite_key = make_composite_key(test_host.id, old_container_id)

        with test_db_manager.get_session() as session:
            tag = Tag(id="tag-1", name="production", color="#ff0000", kind="user", created_at=datetime.now(timezone.utc))
            session.add(tag)

            assignment = TagAssignment(
                tag_id=tag.id,
                subject_type="container",
                subject_id=old_composite_key,
                compose_project="myapp",
                compose_service="web",  # Old service
                host_id_at_attach=test_host.id,
                container_name_at_attach="myapp-web-1",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(assignment)
            session.commit()

        # Action: Try to reattach to different service
        new_container_id = "def456ghi789"
        reattached_tags = test_db_manager.reattach_tags_for_container(
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="myapp-db-1",
            compose_project="myapp",
            compose_service="db"  # Different service
        )

        # Assert: No tags reattached (compose identity doesn't match)
        # Falls back to name matching, but name is different too
        assert len(reattached_tags) == 0


class TestTagReattachmentNameFallback:
    """Test tag reattachment using container name (fallback strategy)"""

    def test_reattach_tags_by_name_when_no_compose_labels(self, test_db_manager, test_host):
        """
        Tags should reattach by name when compose labels absent.

        Scenario:
        - Non-compose container with tags
        - Container recreated (no compose labels)
        - Tags should reattach by name match
        """
        old_container_id = "abc123def456"
        old_composite_key = make_composite_key(test_host.id, old_container_id)

        with test_db_manager.get_session() as session:
            tag = Tag(id="tag-1", name="custom-app", color="#ff0000", kind="user", created_at=datetime.now(timezone.utc))
            session.add(tag)

            # No compose project/service (non-compose container)
            assignment = TagAssignment(
                tag_id=tag.id,
                subject_type="container",
                subject_id=old_composite_key,
                compose_project=None,
                compose_service=None,
                host_id_at_attach=test_host.id,
                container_name_at_attach="my-custom-app",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(assignment)
            session.commit()

        # Action: Reattach by name (no compose labels)
        new_container_id = "def456ghi789"
        reattached_tags = test_db_manager.reattach_tags_for_container(
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="my-custom-app",  # Same name
            compose_project=None,
            compose_service=None
        )

        # Assert: Tag reattached by name
        assert len(reattached_tags) == 1
        assert "custom-app" in reattached_tags

    def test_reattach_tags_by_name_different_name_no_match(self, test_db_manager, test_host):
        """
        Tags should NOT reattach if name differs and no compose labels.

        Scenario:
        - Container name changed
        - No compose labels to match on
        - Tags should NOT reattach
        """
        old_container_id = "abc123def456"
        old_composite_key = make_composite_key(test_host.id, old_container_id)

        with test_db_manager.get_session() as session:
            tag = Tag(id="tag-1", name="custom-app", color="#ff0000", kind="user", created_at=datetime.now(timezone.utc))
            session.add(tag)

            assignment = TagAssignment(
                tag_id=tag.id,
                subject_type="container",
                subject_id=old_composite_key,
                host_id_at_attach=test_host.id,
                container_name_at_attach="old-app-name",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(assignment)
            session.commit()

        # Action: Different name
        new_container_id = "def456ghi789"
        reattached_tags = test_db_manager.reattach_tags_for_container(
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="new-app-name",  # Different name
            compose_project=None,
            compose_service=None
        )

        # Assert: No reattachment
        assert len(reattached_tags) == 0


class TestTagReattachmentEdgeCases:
    """Test edge cases and error scenarios"""

    def test_reattach_tags_no_previous_tags_returns_empty(self, test_db_manager, test_host):
        """
        Reattachment should return empty list when no previous tags exist.
        """
        new_container_id = "abc123def456"
        reattached_tags = test_db_manager.reattach_tags_for_container(
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="new-container",
            compose_project="myapp",
            compose_service="web"
        )

        assert len(reattached_tags) == 0

    def test_reattach_tags_prevents_duplicates(self, test_db_manager, test_host):
        """
        Reattachment should not create duplicate assignments.

        Scenario:
        - Container already has tag assigned
        - Reattachment called again
        - Should not create duplicate
        """
        container_id = "abc123def456"
        composite_key = make_composite_key(test_host.id, container_id)
        tag_id = "tag-1"

        with test_db_manager.get_session() as session:
            tag = Tag(id=tag_id, name="production", color="#ff0000", kind="user", created_at=datetime.now(timezone.utc))
            session.add(tag)

            # Create assignment for container
            assignment = TagAssignment(
                tag_id=tag_id,
                subject_type="container",
                subject_id=composite_key,
                compose_project="myapp",
                compose_service="web",
                host_id_at_attach=test_host.id,
                container_name_at_attach="myapp-web-1",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(assignment)
            session.commit()

        # Action: Call reattachment (should detect existing assignment)
        reattached_tags = test_db_manager.reattach_tags_for_container(
            host_id=test_host.id,
            container_id=container_id,
            container_name="myapp-web-1",
            compose_project="myapp",
            compose_service="web"
        )

        # Assert: No reattachment (already assigned)
        assert len(reattached_tags) == 0

        # Verify: Only one assignment exists
        with test_db_manager.get_session() as session:
            count = session.query(TagAssignment).filter(
                TagAssignment.tag_id == tag_id,
                TagAssignment.subject_id == composite_key
            ).count()
            assert count == 1

    def test_reattach_tags_different_host_no_match(self, test_db_manager):
        """
        Tags should NOT reattach to containers on different hosts.

        Scenario:
        - Container on host A has tags
        - Container on host B with same name/compose
        - Tags should NOT reattach (different host)
        """
        # Store IDs before session closes
        host_a_id = "host-a"
        host_b_id = "host-b"
        tag_id = "tag-1"

        with test_db_manager.get_session() as session:
            host_a = DockerHostDB(
                id=host_a_id,
                name="Host A",
                url="unix:///var/run/docker.sock",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            host_b = DockerHostDB(
                id=host_b_id,
                name="Host B",
                url="unix:///var/run/docker.sock",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            session.add(host_a)
            session.add(host_b)
            session.commit()

            # Tag on host A
            tag = Tag(id=tag_id, name="production", color="#ff0000", kind="user", created_at=datetime.now(timezone.utc))
            session.add(tag)

            old_composite_key = make_composite_key(host_a_id, "abc123def456")
            assignment = TagAssignment(
                tag_id=tag_id,
                subject_type="container",
                subject_id=old_composite_key,
                compose_project="myapp",
                compose_service="web",
                host_id_at_attach=host_a_id,
                container_name_at_attach="myapp-web-1",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(assignment)
            session.commit()

        # Action: Try to reattach on host B (different host)
        reattached_tags = test_db_manager.reattach_tags_for_container(
            host_id=host_b_id,  # Different host
            container_id="def456ghi789",
            container_name="myapp-web-1",
            compose_project="myapp",
            compose_service="web"
        )

        # Assert: No reattachment (different host)
        assert len(reattached_tags) == 0


class TestCompositeKeyFormatting:
    """Test composite key formatting utilities"""

    def test_make_composite_key_format(self):
        """Composite key should use {host_id}:{container_id} format"""
        host_id = "host-123"
        container_id = "abc123def456"

        key = make_composite_key(host_id, container_id)

        assert key == "host-123:abc123def456"
        assert ":" in key
        parts = key.split(":")
        assert len(parts) == 2
        assert parts[0] == host_id
        assert parts[1] == container_id

    def test_tag_assignments_use_composite_keys(self, test_db_manager, test_host):
        """Tag assignments should store composite keys, not just container ID"""
        container_id = "abc123def456"
        composite_key = make_composite_key(test_host.id, container_id)

        with test_db_manager.get_session() as session:
            tag = Tag(id="tag-1", name="test", color="#ff0000", kind="user", created_at=datetime.now(timezone.utc))
            session.add(tag)

            assignment = TagAssignment(
                tag_id=tag.id,
                subject_type="container",
                subject_id=composite_key,  # Composite key, not just container_id
                host_id_at_attach=test_host.id,
                container_name_at_attach="test-container",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(assignment)
            session.commit()

            # Verify stored correctly
            retrieved = session.query(TagAssignment).filter(
                TagAssignment.tag_id == tag.id
            ).first()

            assert retrieved.subject_id == composite_key
            assert ":" in retrieved.subject_id


class TestTagValidation:
    """Test tag database constraints and validation"""

    def test_tag_name_unique_constraint(self, test_db_manager):
        """Tag names must be unique (database constraint)"""
        with test_db_manager.get_session() as session:
            tag1 = Tag(id="tag-1", name="production", color="#ff0000", kind="user", created_at=datetime.now(timezone.utc))
            session.add(tag1)
            session.commit()

            # Try to create duplicate tag name
            tag2 = Tag(id="tag-2", name="production", color="#00ff00", kind="user", created_at=datetime.now(timezone.utc))
            session.add(tag2)

            # Should raise IntegrityError
            with pytest.raises(Exception):  # SQLAlchemy will raise IntegrityError
                session.commit()

    def test_tag_assignment_composite_primary_key(self, test_db_manager, test_host):
        """Tag assignment should prevent duplicate (tag_id, subject_id) pairs"""
        container_id = "abc123def456"
        composite_key = make_composite_key(test_host.id, container_id)

        # First session: create initial tag and assignment
        with test_db_manager.get_session() as session:
            tag = Tag(id="tag-1", name="production", color="#ff0000", kind="user", created_at=datetime.now(timezone.utc))
            session.add(tag)

            assignment1 = TagAssignment(
                tag_id=tag.id,
                subject_type="container",
                subject_id=composite_key,
                host_id_at_attach=test_host.id,
                container_name_at_attach="test-container",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(assignment1)
            session.commit()

        # Second session: try to create duplicate assignment (avoids identity map conflict warning)
        with test_db_manager.get_session() as session:
            assignment2 = TagAssignment(
                tag_id="tag-1",
                subject_type="container",
                subject_id=composite_key,  # Same tag + subject
                host_id_at_attach=test_host.id,
                container_name_at_attach="test-container",
                created_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc)
            )
            session.add(assignment2)

            # Should raise IntegrityError
            with pytest.raises(Exception):
                session.commit()
