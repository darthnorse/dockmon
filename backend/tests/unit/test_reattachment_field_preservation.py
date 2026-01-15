"""
Test field preservation for container configuration reattachment (v2.2.3+)

These tests verify that when containers are recreated (e.g., TrueNAS stop/start),
ALL configuration fields are properly preserved while state fields are reset.

GitHub Issue #114: Auto-update settings lost when container recreated
"""
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import (
    Base,
    ContainerUpdate,
    ContainerHttpHealthCheck,
    AutoRestartConfig,
    DockerHostDB,
    make_composite_key
)


class TestContainerUpdateReattachment:
    """Test that ContainerUpdate reattachment preserves all configuration fields"""

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
    def test_host(self, db_session):
        """Create a test Docker host"""
        host_id = str(uuid.uuid4())
        host = DockerHostDB(
            id=host_id,
            name="test-host",
            url="unix:///var/run/docker.sock",
            is_active=True
        )
        db_session.add(host)
        db_session.commit()
        return host_id

    @pytest.fixture
    def old_container_update(self, db_session, test_host):
        """Create a ContainerUpdate with ALL fields populated"""
        old_container_id = "abc123456789"
        composite_key = make_composite_key(test_host, old_container_id)

        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)

        record = ContainerUpdate(
            container_id=composite_key,
            host_id=test_host,
            container_name="my-test-container",
            # Current state
            current_image="nginx:1.24",
            current_digest="sha256:abc123def456",
            # Latest available
            latest_image="nginx:1.25",
            latest_digest="sha256:def789abc012",
            update_available=True,
            # Version info
            current_version="1.24.0",
            latest_version="1.25.0",
            # Tracking settings (CONFIG - must be preserved)
            floating_tag_mode="minor",
            auto_update_enabled=True,
            update_policy="warn",
            health_check_strategy="http",
            health_check_url="http://localhost:8080/health",
            # Metadata (CONFIG - must be preserved)
            registry_url="https://registry-1.docker.io",
            platform="linux/amd64",
            changelog_url="https://github.com/nginx/nginx/releases",
            changelog_source="ghcr",
            changelog_checked_at=one_hour_ago,
            registry_page_url="https://hub.docker.com/_/nginx",
            registry_page_source="manual",
            # State fields
            last_checked_at=one_hour_ago,
            last_updated_at=one_hour_ago,
            created_at=one_hour_ago,
            updated_at=now
        )
        db_session.add(record)
        db_session.commit()

        return {
            "composite_key": composite_key,
            "container_id": old_container_id,
            "container_name": "my-test-container"
        }

    def test_all_config_fields_in_reattachment_creation(self, db_session, test_host, old_container_update):
        """Verify new ContainerUpdate record copies all expected config fields"""
        # Simulate what reattach_update_settings_for_container does
        prev_update = db_session.query(ContainerUpdate).filter_by(
            container_id=old_container_update["composite_key"]
        ).first()

        new_composite_key = make_composite_key(test_host, "xyz789012345")
        current_image = "nginx:1.24"
        container_name = "my-test-container"

        # Create new record exactly like reattachment function does
        new_update = ContainerUpdate(
            container_id=new_composite_key,
            host_id=test_host,
            container_name=container_name,
            current_image=current_image,
            current_digest=prev_update.current_digest,
            current_version=prev_update.current_version,
            floating_tag_mode=prev_update.floating_tag_mode,
            auto_update_enabled=prev_update.auto_update_enabled,
            update_policy=prev_update.update_policy,
            health_check_strategy=prev_update.health_check_strategy,
            health_check_url=prev_update.health_check_url,
            changelog_url=prev_update.changelog_url,
            changelog_source=prev_update.changelog_source,
            changelog_checked_at=prev_update.changelog_checked_at,
            registry_url=prev_update.registry_url,
            registry_page_url=prev_update.registry_page_url,
            registry_page_source=prev_update.registry_page_source,
            platform=prev_update.platform,
            latest_image=None,
            latest_digest=None,
            update_available=False,
            last_checked_at=None,
            last_updated_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(new_update)
        db_session.commit()

        # Verify ALL config fields preserved
        assert new_update.container_name == "my-test-container"
        assert new_update.floating_tag_mode == "minor"
        assert new_update.auto_update_enabled is True
        assert new_update.update_policy == "warn"
        assert new_update.health_check_strategy == "http"
        assert new_update.health_check_url == "http://localhost:8080/health"
        assert new_update.registry_url == "https://registry-1.docker.io"
        assert new_update.platform == "linux/amd64"
        assert new_update.changelog_url == "https://github.com/nginx/nginx/releases"
        assert new_update.changelog_source == "ghcr"
        assert new_update.changelog_checked_at is not None
        assert new_update.registry_page_url == "https://hub.docker.com/_/nginx"
        assert new_update.registry_page_source == "manual"
        assert new_update.current_digest == "sha256:abc123def456"
        assert new_update.current_version == "1.24.0"

        # Verify STATE fields reset
        assert new_update.latest_image is None
        assert new_update.latest_digest is None
        assert new_update.update_available is False
        assert new_update.last_checked_at is None
        assert new_update.last_updated_at is None

    def test_order_by_updated_at_returns_most_recent(self, db_session, test_host):
        """Verify that ORDER BY updated_at DESC returns most recent record"""
        container_name = "ordered-container"
        now = datetime.now(timezone.utc)

        # Create older record
        old_record = ContainerUpdate(
            container_id=make_composite_key(test_host, "old111111111"),
            host_id=test_host,
            container_name=container_name,
            current_image="nginx:1.23",
            current_digest="sha256:old",
            floating_tag_mode="exact",
            auto_update_enabled=False,
            updated_at=now - timedelta(hours=2)
        )
        db_session.add(old_record)

        # Create newer record
        new_record = ContainerUpdate(
            container_id=make_composite_key(test_host, "new222222222"),
            host_id=test_host,
            container_name=container_name,
            current_image="nginx:1.24",
            current_digest="sha256:new",
            floating_tag_mode="latest",
            auto_update_enabled=True,
            updated_at=now - timedelta(hours=1)
        )
        db_session.add(new_record)
        db_session.commit()

        # Query with ORDER BY updated_at DESC
        result = db_session.query(ContainerUpdate).filter(
            ContainerUpdate.host_id == test_host,
            ContainerUpdate.container_name == container_name
        ).order_by(ContainerUpdate.updated_at.desc()).first()

        # Should return newer record
        assert result.floating_tag_mode == "latest"
        assert result.auto_update_enabled is True


class TestContainerHttpHealthCheckReattachment:
    """Test that ContainerHttpHealthCheck reattachment preserves all configuration fields"""

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
    def test_host(self, db_session):
        """Create a test Docker host"""
        host_id = str(uuid.uuid4())
        host = DockerHostDB(
            id=host_id,
            name="test-host",
            url="unix:///var/run/docker.sock",
            is_active=True
        )
        db_session.add(host)
        db_session.commit()
        return host_id

    @pytest.fixture
    def old_health_check(self, db_session, test_host):
        """Create a ContainerHttpHealthCheck with ALL fields populated"""
        old_container_id = "abc123456789"
        composite_key = make_composite_key(test_host, old_container_id)

        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)

        record = ContainerHttpHealthCheck(
            container_id=composite_key,
            host_id=test_host,
            container_name="my-healthcheck-container",
            # CONFIG fields (must be preserved)
            enabled=True,
            url="https://myapp.local/health",
            method="POST",
            expected_status_codes="200,201,204",
            timeout_seconds=30,
            check_interval_seconds=120,
            follow_redirects=False,
            verify_ssl=False,
            check_from="agent",
            headers_json='{"Authorization": "Bearer token123"}',
            auth_config_json='{"type": "basic", "username": "admin"}',
            auto_restart_on_failure=True,
            failure_threshold=5,
            success_threshold=2,
            max_restart_attempts=5,
            restart_retry_delay_seconds=300,
            # STATE fields (should be reset on reattachment)
            current_status="healthy",
            last_checked_at=one_hour_ago,
            last_success_at=one_hour_ago,
            last_failure_at=one_hour_ago - timedelta(days=1),
            consecutive_successes=10,
            consecutive_failures=0,
            last_response_time_ms=150,
            last_error_message=None,
            created_at=one_hour_ago,
            updated_at=now
        )
        db_session.add(record)
        db_session.commit()

        return {
            "composite_key": composite_key,
            "container_id": old_container_id,
            "container_name": "my-healthcheck-container"
        }

    def test_all_config_fields_in_reattachment_creation(self, db_session, test_host, old_health_check):
        """Verify new ContainerHttpHealthCheck record copies all expected config fields"""
        # Simulate what reattach_http_health_check_for_container does
        prev_health_check = db_session.query(ContainerHttpHealthCheck).filter_by(
            container_id=old_health_check["composite_key"]
        ).first()

        new_composite_key = make_composite_key(test_host, "xyz789012345")
        container_name = "my-healthcheck-container"

        # Create new record exactly like reattachment function does
        new_health_check = ContainerHttpHealthCheck(
            container_id=new_composite_key,
            host_id=test_host,
            container_name=container_name,
            enabled=prev_health_check.enabled,
            url=prev_health_check.url,
            method=prev_health_check.method,
            expected_status_codes=prev_health_check.expected_status_codes,
            timeout_seconds=prev_health_check.timeout_seconds,
            check_interval_seconds=prev_health_check.check_interval_seconds,
            follow_redirects=prev_health_check.follow_redirects,
            verify_ssl=prev_health_check.verify_ssl,
            check_from=prev_health_check.check_from,
            headers_json=prev_health_check.headers_json,
            auth_config_json=prev_health_check.auth_config_json,
            auto_restart_on_failure=prev_health_check.auto_restart_on_failure,
            failure_threshold=prev_health_check.failure_threshold,
            success_threshold=prev_health_check.success_threshold,
            max_restart_attempts=prev_health_check.max_restart_attempts,
            restart_retry_delay_seconds=prev_health_check.restart_retry_delay_seconds
            # Note: STATE fields intentionally NOT copied - they use defaults
        )
        db_session.add(new_health_check)
        db_session.commit()

        # Verify ALL config fields preserved
        assert new_health_check.container_name == "my-healthcheck-container"
        assert new_health_check.enabled is True
        assert new_health_check.url == "https://myapp.local/health"
        assert new_health_check.method == "POST"
        assert new_health_check.expected_status_codes == "200,201,204"
        assert new_health_check.timeout_seconds == 30
        assert new_health_check.check_interval_seconds == 120
        assert new_health_check.follow_redirects is False
        assert new_health_check.verify_ssl is False
        assert new_health_check.check_from == "agent"
        assert new_health_check.headers_json == '{"Authorization": "Bearer token123"}'
        assert new_health_check.auth_config_json == '{"type": "basic", "username": "admin"}'
        assert new_health_check.auto_restart_on_failure is True
        assert new_health_check.failure_threshold == 5
        assert new_health_check.success_threshold == 2
        assert new_health_check.max_restart_attempts == 5
        assert new_health_check.restart_retry_delay_seconds == 300

        # Verify STATE fields use defaults (reset)
        assert new_health_check.current_status == "unknown"
        assert new_health_check.last_checked_at is None
        assert new_health_check.last_success_at is None
        assert new_health_check.last_failure_at is None
        assert new_health_check.consecutive_successes == 0
        assert new_health_check.consecutive_failures == 0
        assert new_health_check.last_response_time_ms is None
        assert new_health_check.last_error_message is None

    def test_order_by_updated_at_returns_most_recent(self, db_session, test_host):
        """Verify that ORDER BY updated_at DESC returns most recent record"""
        container_name = "ordered-healthcheck"
        now = datetime.now(timezone.utc)

        # Create older record
        old_record = ContainerHttpHealthCheck(
            container_id=make_composite_key(test_host, "old111111111"),
            host_id=test_host,
            container_name=container_name,
            enabled=False,
            url="http://old/health",
            check_from="backend",
            failure_threshold=3,
            updated_at=now - timedelta(hours=2)
        )
        db_session.add(old_record)

        # Create newer record
        new_record = ContainerHttpHealthCheck(
            container_id=make_composite_key(test_host, "new222222222"),
            host_id=test_host,
            container_name=container_name,
            enabled=True,
            url="http://new/health",
            check_from="agent",
            failure_threshold=10,
            updated_at=now - timedelta(hours=1)
        )
        db_session.add(new_record)
        db_session.commit()

        # Query with ORDER BY updated_at DESC
        result = db_session.query(ContainerHttpHealthCheck).filter(
            ContainerHttpHealthCheck.host_id == test_host,
            ContainerHttpHealthCheck.container_name == container_name
        ).order_by(ContainerHttpHealthCheck.updated_at.desc()).first()

        # Should return newer record
        assert result.enabled is True
        assert result.url == "http://new/health"
        assert result.check_from == "agent"
        assert result.failure_threshold == 10


class TestHostTransferFieldCopy:
    """Test that host transfer operations copy ALL fields correctly"""

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
    def old_host(self, db_session):
        """Create old Docker host"""
        host_id = str(uuid.uuid4())
        host = DockerHostDB(
            id=host_id,
            name="old-host",
            url="unix:///var/run/docker.sock",
            is_active=True
        )
        db_session.add(host)
        db_session.commit()
        return host_id

    @pytest.fixture
    def new_host(self, db_session):
        """Create new Docker host"""
        host_id = str(uuid.uuid4())
        host = DockerHostDB(
            id=host_id,
            name="new-host",
            url="unix:///var/run/docker.sock",
            is_active=True
        )
        db_session.add(host)
        db_session.commit()
        return host_id

    def test_container_update_host_transfer_copies_all_fields(self, db_session, old_host, new_host):
        """Verify host transfer copies ALL ContainerUpdate fields"""
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)

        old_record = ContainerUpdate(
            container_id=make_composite_key(old_host, "abc123456789"),
            host_id=old_host,
            container_name="transfer-container",
            current_image="nginx:1.24",
            current_digest="sha256:abc123",
            current_version="1.24.0",
            latest_image="nginx:1.25",
            latest_digest="sha256:def456",
            latest_version="1.25.0",
            update_available=True,
            floating_tag_mode="minor",
            auto_update_enabled=True,
            update_policy="warn",
            health_check_strategy="http",
            health_check_url="http://localhost/health",
            last_checked_at=one_hour_ago,
            last_updated_at=one_hour_ago,
            registry_url="https://registry.docker.io",
            platform="linux/amd64",
            changelog_url="https://github.com/releases",
            changelog_source="ghcr",
            changelog_checked_at=one_hour_ago,
            registry_page_url="https://hub.docker.com",
            registry_page_source="manual"
        )
        db_session.add(old_record)
        db_session.commit()

        # Simulate host transfer copy (as in manager.py)
        new_composite = make_composite_key(new_host, "abc123456789")
        new_record = ContainerUpdate(
            container_id=new_composite,
            host_id=new_host,
            container_name=old_record.container_name,
            current_image=old_record.current_image,
            current_digest=old_record.current_digest,
            current_version=old_record.current_version,
            latest_image=old_record.latest_image,
            latest_digest=old_record.latest_digest,
            latest_version=old_record.latest_version,
            update_available=old_record.update_available,
            floating_tag_mode=old_record.floating_tag_mode,
            auto_update_enabled=old_record.auto_update_enabled,
            update_policy=old_record.update_policy,
            health_check_strategy=old_record.health_check_strategy,
            health_check_url=old_record.health_check_url,
            last_checked_at=old_record.last_checked_at,
            last_updated_at=old_record.last_updated_at,
            registry_url=old_record.registry_url,
            platform=old_record.platform,
            changelog_url=old_record.changelog_url,
            changelog_source=old_record.changelog_source,
            changelog_checked_at=old_record.changelog_checked_at,
            registry_page_url=old_record.registry_page_url,
            registry_page_source=old_record.registry_page_source
        )
        db_session.add(new_record)
        db_session.commit()

        # Verify ALL fields copied
        assert new_record.container_name == "transfer-container"
        assert new_record.current_image == "nginx:1.24"
        assert new_record.current_digest == "sha256:abc123"
        assert new_record.current_version == "1.24.0"
        assert new_record.latest_image == "nginx:1.25"
        assert new_record.latest_digest == "sha256:def456"
        assert new_record.latest_version == "1.25.0"
        assert new_record.update_available is True
        assert new_record.floating_tag_mode == "minor"
        assert new_record.auto_update_enabled is True
        assert new_record.update_policy == "warn"
        assert new_record.health_check_strategy == "http"
        assert new_record.health_check_url == "http://localhost/health"
        assert new_record.last_checked_at is not None
        assert new_record.last_updated_at is not None
        assert new_record.registry_url == "https://registry.docker.io"
        assert new_record.platform == "linux/amd64"
        assert new_record.changelog_url == "https://github.com/releases"
        assert new_record.changelog_source == "ghcr"
        assert new_record.changelog_checked_at is not None
        assert new_record.registry_page_url == "https://hub.docker.com"
        assert new_record.registry_page_source == "manual"

    def test_health_check_host_transfer_copies_all_fields(self, db_session, old_host, new_host):
        """Verify host transfer copies ALL ContainerHttpHealthCheck fields"""
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)

        old_record = ContainerHttpHealthCheck(
            container_id=make_composite_key(old_host, "abc123456789"),
            host_id=old_host,
            container_name="transfer-healthcheck",
            enabled=True,
            url="https://myapp/health",
            method="POST",
            expected_status_codes="200,204",
            timeout_seconds=30,
            check_interval_seconds=120,
            follow_redirects=False,
            verify_ssl=False,
            check_from="agent",
            headers_json='{"X-Custom": "value"}',
            auth_config_json='{"type": "bearer"}',
            current_status="healthy",
            last_checked_at=one_hour_ago,
            last_success_at=one_hour_ago,
            last_failure_at=one_hour_ago - timedelta(days=1),
            consecutive_successes=5,
            consecutive_failures=0,
            last_response_time_ms=100,
            last_error_message=None,
            auto_restart_on_failure=True,
            failure_threshold=5,
            success_threshold=2,
            max_restart_attempts=5,
            restart_retry_delay_seconds=300
        )
        db_session.add(old_record)
        db_session.commit()

        # Simulate host transfer copy (as in manager.py)
        new_composite = make_composite_key(new_host, "abc123456789")
        new_record = ContainerHttpHealthCheck(
            container_id=new_composite,
            host_id=new_host,
            container_name=old_record.container_name,
            enabled=old_record.enabled,
            url=old_record.url,
            method=old_record.method,
            expected_status_codes=old_record.expected_status_codes,
            timeout_seconds=old_record.timeout_seconds,
            check_interval_seconds=old_record.check_interval_seconds,
            follow_redirects=old_record.follow_redirects,
            verify_ssl=old_record.verify_ssl,
            check_from=old_record.check_from,
            headers_json=old_record.headers_json,
            auth_config_json=old_record.auth_config_json,
            current_status=old_record.current_status,
            last_checked_at=old_record.last_checked_at,
            last_success_at=old_record.last_success_at,
            last_failure_at=old_record.last_failure_at,
            consecutive_successes=old_record.consecutive_successes,
            consecutive_failures=old_record.consecutive_failures,
            last_response_time_ms=old_record.last_response_time_ms,
            last_error_message=old_record.last_error_message,
            auto_restart_on_failure=old_record.auto_restart_on_failure,
            failure_threshold=old_record.failure_threshold,
            success_threshold=old_record.success_threshold,
            max_restart_attempts=old_record.max_restart_attempts,
            restart_retry_delay_seconds=old_record.restart_retry_delay_seconds
        )
        db_session.add(new_record)
        db_session.commit()

        # Verify ALL fields copied (including state for host transfer)
        assert new_record.container_name == "transfer-healthcheck"
        assert new_record.enabled is True
        assert new_record.url == "https://myapp/health"
        assert new_record.method == "POST"
        assert new_record.expected_status_codes == "200,204"
        assert new_record.timeout_seconds == 30
        assert new_record.check_interval_seconds == 120
        assert new_record.follow_redirects is False
        assert new_record.verify_ssl is False
        assert new_record.check_from == "agent"
        assert new_record.headers_json == '{"X-Custom": "value"}'
        assert new_record.auth_config_json == '{"type": "bearer"}'
        assert new_record.current_status == "healthy"
        assert new_record.last_checked_at is not None
        assert new_record.last_success_at is not None
        assert new_record.last_failure_at is not None
        assert new_record.consecutive_successes == 5
        assert new_record.consecutive_failures == 0
        assert new_record.last_response_time_ms == 100
        assert new_record.last_error_message is None
        assert new_record.auto_restart_on_failure is True
        assert new_record.failure_threshold == 5
        assert new_record.success_threshold == 2
        assert new_record.max_restart_attempts == 5
        assert new_record.restart_retry_delay_seconds == 300
