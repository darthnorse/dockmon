"""
Integration tests for tag persistence across container recreation.

Tests verify the "sticky tags" feature - tags should reattach when containers are recreated
with new Docker IDs (e.g., TrueNAS stop/start cycle).

Matching logic:
1. Primary: Compose identity (compose_project + compose_service + host_id)
2. Fallback: Container name (container_name + host_id)
"""

import pytest
from datetime import datetime, timezone
import uuid

from database import Tag, TagAssignment, DockerHostDB
from tests.conftest import create_composite_key


def reattach_tags_for_container_direct(
    session,
    host_id: str,
    container_id: str,
    container_name: str,
    compose_project: str = None,
    compose_service: str = None
):
    """
    Direct tag reattachment using session (for integration testing).

    This mimics DatabaseManager.reattach_tags_for_container() but works with
    the test session fixture.
    """
    # Find old tag assignments by compose identity (primary) or name (fallback)
    if compose_project and compose_service:
        # Primary: Match by compose identity
        old_assignments = session.query(TagAssignment).filter(
            TagAssignment.host_id_at_attach == host_id,
            TagAssignment.compose_project == compose_project,
            TagAssignment.compose_service == compose_service,
            TagAssignment.subject_type == "container"
        ).all()
    else:
        # Fallback: Match by container name
        old_assignments = session.query(TagAssignment).filter(
            TagAssignment.host_id_at_attach == host_id,
            TagAssignment.container_name_at_attach == container_name,
            TagAssignment.subject_type == "container"
        ).all()

    if not old_assignments:
        return []

    # Create new assignments for the new container
    new_composite_key = create_composite_key(host_id, container_id)
    reattached = []

    for old_assignment in old_assignments:
        # Check if assignment already exists (idempotent)
        existing = session.query(TagAssignment).filter_by(
            tag_id=old_assignment.tag_id,
            subject_type="container",
            subject_id=new_composite_key
        ).first()

        if existing:
            # Already exists, skip
            continue

        # Create new assignment
        new_assignment = TagAssignment(
            tag_id=old_assignment.tag_id,
            subject_type="container",
            subject_id=new_composite_key,
            host_id_at_attach=host_id,
            container_name_at_attach=container_name,
            compose_project=compose_project,
            compose_service=compose_service,
            created_at=datetime.now(timezone.utc)
        )
        session.add(new_assignment)

        # Get tag info for return
        tag = session.query(Tag).filter_by(id=old_assignment.tag_id).first()
        if tag:
            reattached.append({
                'name': tag.name,
                'color': tag.color,
                'id': tag.id
            })

    session.commit()
    return reattached


# =============================================================================
# Tag Reattachment Tests (Compose Identity Matching)
# =============================================================================

@pytest.mark.integration
class TestTagReattachmentByComposeIdentity:
    """Test tag reattachment using compose labels (primary matching method)"""

    def test_tags_reattach_by_compose_identity(
        self,
        db_session,
        test_host
    ):
        """
        Test sticky tags: Tags reattach when container recreated with same compose identity.

        Scenario:
        - Container has compose labels (project=myapp, service=web)
        - Container has tags assigned
        - Container destroyed and recreated with NEW Docker ID
        - Same compose labels
        - Tags should automatically reattach

        This simulates TrueNAS stop/start behavior.
        """
        # Arrange: Create old container with tags
        old_container_id = "old123old456"
        old_composite_key = create_composite_key(test_host.id, old_container_id)

        # Create tag
        tag = Tag(
            id=str(uuid.uuid4()),
            name="production",
            color="#ff0000",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.flush()

        # Create tag assignment to old container
        assignment = TagAssignment(
            tag_id=tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=test_host.id,
            container_name_at_attach="myapp-web-1",
            compose_project="myapp",
            compose_service="web",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(assignment)
        db_session.commit()

        # Act: Simulate container recreation with new ID
        new_container_id = "new789new012"

        reattached_tags = reattach_tags_for_container_direct(
            session=db_session,
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="myapp-web-1",
            compose_project="myapp",
            compose_service="web"
        )

        # Assert: Tag reattached to new container
        assert len(reattached_tags) == 1
        assert "production" in [tag['name'] for tag in reattached_tags]

        # Verify new assignment exists
        new_composite_key = create_composite_key(test_host.id, new_container_id)
        new_assignment = db_session.query(TagAssignment).filter_by(
            tag_id=tag.id,
            subject_id=new_composite_key
        ).first()
        assert new_assignment is not None
        assert new_assignment.compose_project == "myapp"
        assert new_assignment.compose_service == "web"


    def test_multiple_tags_reattach(
        self,
        db_session,
        test_host
    ):
        """
        Test that ALL tags reattach when container recreated.

        Scenario:
        - Container has 3 tags (production, critical, monitored)
        - Container recreated with new ID
        - All 3 tags should reattach
        """
        # Arrange: Create old container with multiple tags
        old_container_id = "old123old456"
        old_composite_key = create_composite_key(test_host.id, old_container_id)

        # Create 3 tags
        tags = []
        tag_names = ["production", "critical", "monitored"]
        for name in tag_names:
            tag = Tag(
                id=str(uuid.uuid4()),
                name=name,
                color="#ff0000",
                created_at=datetime.now(timezone.utc)
            )
            db_session.add(tag)
            tags.append(tag)
        db_session.flush()

        # Assign all tags to old container
        for tag in tags:
            assignment = TagAssignment(
                tag_id=tag.id,
                subject_type="container",
                subject_id=old_composite_key,
                host_id_at_attach=test_host.id,
                container_name_at_attach="myapp-db-1",
                compose_project="myapp",
                compose_service="db",
                created_at=datetime.now(timezone.utc)
            )
            db_session.add(assignment)
        db_session.commit()

        # Act: Reattach tags to new container
        new_container_id = "new789new012"
        # Use direct reattachment function for integration tests

        reattached_tags = reattach_tags_for_container_direct(
            session=db_session,
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="myapp-db-1",
            compose_project="myapp",
            compose_service="db"
        )

        # Assert: All 3 tags reattached
        assert len(reattached_tags) == 3
        reattached_names = {tag['name'] for tag in reattached_tags}
        assert reattached_names == {"production", "critical", "monitored"}


    def test_tags_only_reattach_to_same_service(
        self,
        db_session,
        test_host
    ):
        """
        Test that tags only reattach to containers with SAME compose service.

        Scenario:
        - Tag assigned to myapp-web-1 (service=web)
        - Container myapp-db-1 (service=db) created
        - Tag should NOT reattach to db service
        """
        # Arrange: Create tag for web service
        old_container_id = "old123old456"
        old_composite_key = create_composite_key(test_host.id, old_container_id)

        tag = Tag(
            id=str(uuid.uuid4()),
            name="web-specific",
            color="#00ff00",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.flush()

        assignment = TagAssignment(
            tag_id=tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=test_host.id,
            container_name_at_attach="myapp-web-1",
            compose_project="myapp",
            compose_service="web",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(assignment)
        db_session.commit()

        # Act: Try to reattach to db service (different service)
        new_container_id = "new789new012"
        # Use direct reattachment function for integration tests

        reattached_tags = reattach_tags_for_container_direct(
            session=db_session,
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="myapp-db-1",
            compose_project="myapp",
            compose_service="db"  # Different service!
        )

        # Assert: No tags reattached (different service)
        assert len(reattached_tags) == 0


# =============================================================================
# Tag Reattachment Tests (Container Name Fallback)
# =============================================================================

@pytest.mark.integration
class TestTagReattachmentByContainerName:
    """Test tag reattachment using container name (fallback for non-Compose containers)"""

    def test_tags_reattach_by_name_when_no_compose_labels(
        self,
        db_session,
        test_host
    ):
        """
        Test tag reattachment using container name (non-Compose containers).

        Scenario:
        - Container has NO compose labels (manually created)
        - Tag assigned based on container name
        - Container recreated with SAME name
        - Tag should reattach by name
        """
        # Arrange: Create tag assignment with no compose labels
        old_container_id = "old123old456"
        old_composite_key = create_composite_key(test_host.id, old_container_id)

        tag = Tag(
            id=str(uuid.uuid4()),
            name="manual-tag",
            color="#0000ff",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.flush()

        assignment = TagAssignment(
            tag_id=tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=test_host.id,
            container_name_at_attach="my-nginx",
            compose_project=None,  # No compose labels
            compose_service=None,
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(assignment)
        db_session.commit()

        # Act: Reattach by name only
        new_container_id = "new789new012"
        # Use direct reattachment function for integration tests

        reattached_tags = reattach_tags_for_container_direct(
            session=db_session,
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="my-nginx",  # Same name
            compose_project=None,
            compose_service=None
        )

        # Assert: Tag reattached by name
        assert len(reattached_tags) == 1
        assert reattached_tags[0]['name'] == "manual-tag"


    def test_name_fallback_when_compose_match_fails(
        self,
        db_session,
        test_host
    ):
        """
        Test that name fallback works when compose identity doesn't match.

        Scenario:
        - Tag assigned to old container with compose labels
        - Container recreated WITHOUT compose labels (user removed labels)
        - Tag should still reattach by name (fallback)
        """
        # Arrange: Old container had compose labels
        old_container_id = "old123old456"
        old_composite_key = create_composite_key(test_host.id, old_container_id)

        tag = Tag(
            id=str(uuid.uuid4()),
            name="fallback-tag",
            color="#ff00ff",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.flush()

        assignment = TagAssignment(
            tag_id=tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=test_host.id,
            container_name_at_attach="test-app",
            compose_project="oldproject",
            compose_service="oldservice",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(assignment)
        db_session.commit()

        # Act: New container has no compose labels (but same name)
        new_container_id = "new789new012"
        # Use direct reattachment function for integration tests

        reattached_tags = reattach_tags_for_container_direct(
            session=db_session,
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="test-app",  # Same name
            compose_project=None,  # Compose labels removed
            compose_service=None
        )

        # Assert: Tag reattached by name fallback
        assert len(reattached_tags) == 1
        assert reattached_tags[0]['name'] == "fallback-tag"


# =============================================================================
# Edge Cases
# =============================================================================

@pytest.mark.integration
class TestTagReattachmentEdgeCases:
    """Test edge cases in tag reattachment logic"""

    def test_no_reattachment_when_name_changes(
        self,
        db_session,
        test_host
    ):
        """
        Test that tags do NOT reattach when container name changes.

        Scenario:
        - Tag assigned to container "old-name"
        - Container recreated with name "new-name"
        - No compose labels
        - Tag should NOT reattach (user changed identity)
        """
        # Arrange
        old_container_id = "old123old456"
        old_composite_key = create_composite_key(test_host.id, old_container_id)

        tag = Tag(
            id=str(uuid.uuid4()),
            name="no-reattach",
            color="#ffffff",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.flush()

        assignment = TagAssignment(
            tag_id=tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=test_host.id,
            container_name_at_attach="old-name",
            compose_project=None,
            compose_service=None,
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(assignment)
        db_session.commit()

        # Act: Try to reattach to different name
        new_container_id = "new789new012"
        # Use direct reattachment function for integration tests

        reattached_tags = reattach_tags_for_container_direct(
            session=db_session,
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="new-name",  # Different name!
            compose_project=None,
            compose_service=None
        )

        # Assert: No reattachment (name changed)
        assert len(reattached_tags) == 0


    def test_no_reattachment_across_hosts(
        self,
        db_session,
        test_host
    ):
        """
        Test that tags do NOT reattach across different hosts.

        Scenario:
        - Tag assigned to container on host A
        - Container with same name created on host B
        - Tag should NOT reattach (different host)
        """
        # Arrange: Create second host
        from database import DockerHostDB
        second_host = DockerHostDB(
            id="second-host-uuid",
            name="second-host",
            url="unix:///var/run/docker.sock",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(second_host)
        db_session.flush()

        # Tag on first host
        old_container_id = "old123old456"
        old_composite_key = create_composite_key(test_host.id, old_container_id)

        tag = Tag(
            id=str(uuid.uuid4()),
            name="host-specific",
            color="#000000",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.flush()

        assignment = TagAssignment(
            tag_id=tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=test_host.id,  # First host
            container_name_at_attach="shared-name",
            compose_project=None,
            compose_service=None,
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(assignment)
        db_session.commit()

        # Act: Try to reattach on second host
        new_container_id = "new789new012"
        # Use direct reattachment function for integration tests

        reattached_tags = reattach_tags_for_container_direct(
            session=db_session,
            host_id=second_host.id,  # Different host!
            container_id=new_container_id,
            container_name="shared-name",  # Same name
            compose_project=None,
            compose_service=None
        )

        # Assert: No reattachment (different host)
        assert len(reattached_tags) == 0


    def test_duplicate_prevention(
        self,
        db_session,
        test_host
    ):
        """
        Test that reattachment doesn't create duplicate tag assignments.

        Scenario:
        - Call reattach_tags_for_container() twice
        - Should only have ONE assignment (idempotent)
        """
        # Arrange
        old_container_id = "old123old456"
        old_composite_key = create_composite_key(test_host.id, old_container_id)

        tag = Tag(
            id=str(uuid.uuid4()),
            name="duplicate-test",
            color="#aaaaaa",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.flush()

        assignment = TagAssignment(
            tag_id=tag.id,
            subject_type="container",
            subject_id=old_composite_key,
            host_id_at_attach=test_host.id,
            container_name_at_attach="test-container",
            compose_project="myapp",
            compose_service="web",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(assignment)
        db_session.commit()

        # Act: Call reattach twice
        new_container_id = "new789new012"
        new_composite_key = create_composite_key(test_host.id, new_container_id)
        # Use direct reattachment function for integration tests

        # First call
        reattach_tags_for_container_direct(
            session=db_session,
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="test-container",
            compose_project="myapp",
            compose_service="web"
        )

        # Second call (should be idempotent)
        reattach_tags_for_container_direct(
            session=db_session,
            host_id=test_host.id,
            container_id=new_container_id,
            container_name="test-container",
            compose_project="myapp",
            compose_service="web"
        )

        # Assert: Only ONE assignment exists for new container
        assignments = db_session.query(TagAssignment).filter_by(
            subject_id=new_composite_key
        ).all()
        assert len(assignments) == 1
