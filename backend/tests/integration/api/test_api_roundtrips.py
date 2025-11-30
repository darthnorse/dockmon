"""
Integration tests for API round-trips.

Tests verify data symmetry: what you POST/PUT is what you GET back.
This ensures frontend state persistence after page refreshes.

Critical for user experience:
- User creates/updates data
- Data persisted to database
- GET returns ALL fields the frontend needs
- User refreshes page → data still there
"""

import pytest
from datetime import datetime, timezone
import uuid

from database import (
    AutoRestartConfig,
    ContainerDesiredState,
    ContainerUpdate,
    ContainerHttpHealthCheck,
    Tag
)
from tests.conftest import create_composite_key


# =============================================================================
# Auto-Restart Config Round-Trip Tests
# =============================================================================

@pytest.mark.integration
class TestAutoRestartConfigRoundTrip:
    """Test POST → GET round-trip for auto-restart configuration"""

    def test_auto_restart_enable_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test enabling auto-restart persists through round-trip.

        Flow: POST enable → GET config → verify enabled=True
        """
        # Arrange
        container_id = "abc123def456"

        # Act: Enable auto-restart (simulate API POST)
        config = AutoRestartConfig(
            host_id=test_host.id,
            container_id=container_id,
            container_name="test-nginx",
            enabled=True,
            max_retries=3,
            retry_delay=10,
            restart_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(config)
        db_session.commit()

        # Assert: Retrieve config (simulate API GET)
        retrieved = db_session.query(AutoRestartConfig).filter_by(
            host_id=test_host.id,
            container_id=container_id
        ).first()

        assert retrieved is not None
        assert retrieved.enabled is True
        assert retrieved.max_retries == 3
        assert retrieved.retry_delay == 10
        assert retrieved.restart_count == 0


    def test_auto_restart_config_update_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test updating auto-restart config persists.

        Flow: POST create → PUT update → GET config → verify updated values
        """
        # Arrange: Create initial config
        container_id = "abc123def456"
        config = AutoRestartConfig(
            host_id=test_host.id,
            container_id=container_id,
            container_name="test-nginx",
            enabled=True,
            max_retries=3,
            retry_delay=10,
            restart_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(config)
        db_session.commit()

        # Act: Update config (simulate API PUT)
        config.max_retries = 5
        config.retry_delay = 30
        config.updated_at = datetime.now(timezone.utc)
        db_session.commit()

        # Assert: Retrieve updated config
        retrieved = db_session.query(AutoRestartConfig).filter_by(
            host_id=test_host.id,
            container_id=container_id
        ).first()

        assert retrieved.max_retries == 5
        assert retrieved.retry_delay == 30


# =============================================================================
# Desired State Round-Trip Tests
# =============================================================================

@pytest.mark.integration
class TestDesiredStateRoundTrip:
    """Test POST → GET round-trip for container desired state"""

    def test_desired_state_create_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test setting desired state persists.

        Flow: POST desired_state=should_run → GET → verify should_run
        """
        # Arrange
        container_id = "abc123def456"

        # Act: Set desired state (simulate API POST)
        state = ContainerDesiredState(
            host_id=test_host.id,
            container_id=container_id,
            container_name="test-app",
            desired_state="should_run",
            web_ui_url="http://localhost:8080/admin",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(state)
        db_session.commit()

        # Assert: Retrieve state
        retrieved = db_session.query(ContainerDesiredState).filter_by(
            host_id=test_host.id,
            container_id=container_id
        ).first()

        assert retrieved is not None
        assert retrieved.desired_state == "should_run"
        assert retrieved.web_ui_url == "http://localhost:8080/admin"


    def test_web_ui_url_persists(
        self,
        db_session,
        test_host
    ):
        """
        Test web UI URL persists through round-trip.

        This is a common user preference that must survive page refresh.
        """
        # Arrange
        container_id = "abc123def456"

        # Act: Set web UI URL
        state = ContainerDesiredState(
            host_id=test_host.id,
            container_id=container_id,
            container_name="test-app",
            desired_state="should_run",
            web_ui_url="http://192.168.1.100:9000/dashboard",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(state)
        db_session.commit()

        # Assert: URL persists
        retrieved = db_session.query(ContainerDesiredState).filter_by(
            host_id=test_host.id,
            container_id=container_id
        ).first()

        assert retrieved.web_ui_url == "http://192.168.1.100:9000/dashboard"


# =============================================================================
# Update Settings Round-Trip Tests
# =============================================================================

@pytest.mark.integration
class TestUpdateSettingsRoundTrip:
    """Test POST → GET round-trip for container update settings"""

    def test_floating_tag_mode_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test floating tag mode setting persists.

        User sets mode to 'patch' → page refresh → mode still 'patch'
        """
        # Arrange
        container_id = "abc123def456"
        composite_key = create_composite_key(test_host.id, container_id)

        # Act: Set floating tag mode
        update = ContainerUpdate(
            container_id=composite_key,
            host_id=test_host.id,
            current_image="nginx:1.21.0",
            current_digest="sha256:abc123",
            floating_tag_mode="patch",  # User preference
            auto_update_enabled=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(update)
        db_session.commit()

        # Assert: Retrieve and verify mode persists
        retrieved = db_session.query(ContainerUpdate).filter_by(
            container_id=composite_key
        ).first()

        assert retrieved is not None
        assert retrieved.floating_tag_mode == "patch"


    def test_auto_update_enabled_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test auto-update enabled flag persists.

        Critical: User enables auto-update → must persist after refresh
        """
        # Arrange
        container_id = "abc123def456"
        composite_key = create_composite_key(test_host.id, container_id)

        # Act: Enable auto-update
        update = ContainerUpdate(
            container_id=composite_key,
            host_id=test_host.id,
            current_image="nginx:latest",
            current_digest="sha256:abc123",
            auto_update_enabled=True,  # User enabled
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(update)
        db_session.commit()

        # Assert: Flag persists
        retrieved = db_session.query(ContainerUpdate).filter_by(
            container_id=composite_key
        ).first()

        assert retrieved.auto_update_enabled is True


    def test_update_policy_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test update policy setting persists.

        User sets policy to 'warn' → page refresh → policy still 'warn'
        """
        # Arrange
        container_id = "abc123def456"
        composite_key = create_composite_key(test_host.id, container_id)

        # Act: Set update policy
        update = ContainerUpdate(
            container_id=composite_key,
            host_id=test_host.id,
            current_image="nginx:latest",
            current_digest="sha256:abc123",
            update_policy="warn",  # User preference
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(update)
        db_session.commit()

        # Assert: Policy persists
        retrieved = db_session.query(ContainerUpdate).filter_by(
            container_id=composite_key
        ).first()

        assert retrieved.update_policy == "warn"


    def test_health_check_strategy_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test health check strategy persists.

        User chooses 'http' strategy → must persist
        """
        # Arrange
        container_id = "abc123def456"
        composite_key = create_composite_key(test_host.id, container_id)

        # Act: Set health check strategy
        update = ContainerUpdate(
            container_id=composite_key,
            host_id=test_host.id,
            current_image="myapp:v1.0",
            current_digest="sha256:abc123",
            health_check_strategy="http",  # User preference
            health_check_url="http://localhost:8080/health",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(update)
        db_session.commit()

        # Assert: Strategy and URL persist
        retrieved = db_session.query(ContainerUpdate).filter_by(
            container_id=composite_key
        ).first()

        assert retrieved.health_check_strategy == "http"
        assert retrieved.health_check_url == "http://localhost:8080/health"


# =============================================================================
# HTTP Health Check Round-Trip Tests
# =============================================================================

@pytest.mark.integration
class TestHttpHealthCheckRoundTrip:
    """Test POST → GET round-trip for HTTP health check configuration"""

    def test_http_health_check_complete_config_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test complete HTTP health check config persists.

        User configures all fields → must all persist after refresh
        """
        # Arrange
        container_id = "abc123def456"
        composite_key = create_composite_key(test_host.id, container_id)

        # Act: Create complete health check config
        health_check = ContainerHttpHealthCheck(
            container_id=composite_key,
            host_id=test_host.id,
            enabled=True,
            url="http://localhost:8080/api/health",
            method="POST",
            expected_status_codes="200,201,204",
            timeout_seconds=15,
            check_interval_seconds=120,
            follow_redirects=False,
            verify_ssl=True,
            headers_json='{"Authorization": "Bearer token123"}',
            auth_config_json='{"username": "admin"}',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(health_check)
        db_session.commit()

        # Assert: ALL fields persist
        retrieved = db_session.query(ContainerHttpHealthCheck).filter_by(
            container_id=composite_key
        ).first()

        assert retrieved is not None
        assert retrieved.enabled is True
        assert retrieved.url == "http://localhost:8080/api/health"
        assert retrieved.method == "POST"
        assert retrieved.expected_status_codes == "200,201,204"
        assert retrieved.timeout_seconds == 15
        assert retrieved.check_interval_seconds == 120
        assert retrieved.follow_redirects is False
        assert retrieved.verify_ssl is True
        assert retrieved.headers_json == '{"Authorization": "Bearer token123"}'
        assert retrieved.auth_config_json == '{"username": "admin"}'


    def test_http_health_check_update_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test updating HTTP health check config persists.

        User creates config → updates timeout → new timeout persists
        """
        # Arrange: Create initial config
        container_id = "abc123def456"
        composite_key = create_composite_key(test_host.id, container_id)

        health_check = ContainerHttpHealthCheck(
            container_id=composite_key,
            host_id=test_host.id,
            enabled=True,
            url="http://localhost/health",
            method="GET",
            timeout_seconds=10,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(health_check)
        db_session.commit()

        # Act: Update timeout
        health_check.timeout_seconds = 30
        health_check.check_interval_seconds = 180
        health_check.updated_at = datetime.now(timezone.utc)
        db_session.commit()

        # Assert: Updates persist
        retrieved = db_session.query(ContainerHttpHealthCheck).filter_by(
            container_id=composite_key
        ).first()

        assert retrieved.timeout_seconds == 30
        assert retrieved.check_interval_seconds == 180


# =============================================================================
# Tag Round-Trip Tests
# =============================================================================

@pytest.mark.integration
class TestTagRoundTrip:
    """Test POST → GET round-trip for tag creation and assignment"""

    def test_tag_creation_roundtrip(
        self,
        db_session
    ):
        """
        Test creating tag persists with all fields.

        User creates tag with name and color → must persist
        """
        # Act: Create tag
        tag = Tag(
            id=str(uuid.uuid4()),
            name="production",
            color="#ff0000",
            kind="user",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.commit()

        # Assert: Tag persists with all fields
        retrieved = db_session.query(Tag).filter_by(name="production").first()

        assert retrieved is not None
        assert retrieved.name == "production"
        assert retrieved.color == "#ff0000"
        assert retrieved.kind == "user"


    def test_tag_assignment_roundtrip(
        self,
        db_session,
        test_host
    ):
        """
        Test tag assignment persists.

        User assigns tag to container → assignment persists after refresh
        """
        # Arrange: Create tag
        tag = Tag(
            id=str(uuid.uuid4()),
            name="critical",
            color="#ff0000",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(tag)
        db_session.flush()

        # Act: Assign to container
        from database import TagAssignment
        container_id = "abc123def456"
        composite_key = create_composite_key(test_host.id, container_id)

        assignment = TagAssignment(
            tag_id=tag.id,
            subject_type="container",
            subject_id=composite_key,
            host_id_at_attach=test_host.id,
            container_name_at_attach="test-app",
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(assignment)
        db_session.commit()

        # Assert: Assignment persists
        retrieved = db_session.query(TagAssignment).filter_by(
            tag_id=tag.id,
            subject_id=composite_key
        ).first()

        assert retrieved is not None
        assert retrieved.subject_type == "container"


# =============================================================================
# Composite Key Round-Trip Tests
# =============================================================================

@pytest.mark.integration
class TestCompositeKeyRoundTrip:
    """Test that composite keys work correctly in round-trips"""

    def test_composite_key_format_consistency(
        self,
        db_session,
        test_host
    ):
        """
        Test composite key format is consistent across round-trips.

        Format: {host_id}:{container_id}
        Must work for all tables using composite keys
        """
        # Arrange
        container_id = "abc123def456"
        composite_key = create_composite_key(test_host.id, container_id)

        # Act: Create records with composite key
        update = ContainerUpdate(
            container_id=composite_key,
            host_id=test_host.id,
            current_image="nginx:latest",
            current_digest="sha256:abc123",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(update)

        health_check = ContainerHttpHealthCheck(
            container_id=composite_key,
            host_id=test_host.id,
            enabled=True,
            url="http://localhost/health",
            method="GET",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(health_check)
        db_session.commit()

        # Assert: Both records use same composite key format
        retrieved_update = db_session.query(ContainerUpdate).filter_by(
            container_id=composite_key
        ).first()
        retrieved_health = db_session.query(ContainerHttpHealthCheck).filter_by(
            container_id=composite_key
        ).first()

        assert retrieved_update is not None
        assert retrieved_health is not None
        assert retrieved_update.container_id == composite_key
        assert retrieved_health.container_id == composite_key
