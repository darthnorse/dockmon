"""
Unit tests for agent migration from mTLS to agent-based connection.

Tests the automatic migration workflow when an agent registers with an
engine_id that matches an existing mTLS host.

RED Phase: These tests should FAIL until migration feature is implemented.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
from database import DatabaseManager, DockerHostDB, Agent, RegistrationToken
from agent.manager import AgentManager


@pytest.fixture
def db_manager():
    """Create a test database manager with in-memory SQLite."""
    # Reset the singleton to allow creating a new instance for testing
    import database
    database._database_manager_instance = None  # Reset singleton
    manager = DatabaseManager(db_path=':memory:')
    # Tables are created automatically in __init__ via Base.metadata.create_all()
    yield manager
    # Cleanup: reset singleton after test
    database._database_manager_instance = None


@pytest.fixture
def agent_manager(db_manager):
    """Create an AgentManager with test database."""
    manager = AgentManager()
    manager.db_manager = db_manager
    return manager


@pytest.fixture
def registration_token(db_manager):
    """Create a valid registration token."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        token = RegistrationToken(
            token="test-token-12345",
            created_by_user_id=1,
            created_at=now,
            expires_at=now.replace(year=now.year + 1),  # Far future
            used=False
        )
        session.add(token)
        session.commit()
        return token.token


@pytest.fixture
def existing_mtls_host(db_manager):
    """Create an existing mTLS host with engine_id."""
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as session:
        host = DockerHostDB(
            id="existing-host-id",
            name="Local Docker",
            url="tcp://192.168.1.100:2376",
            connection_type="remote",
            engine_id="engine-12345",  # This will match agent registration
            is_active=True,
            created_at=now,
            updated_at=now
        )
        session.add(host)
        session.commit()
        return host


def test_agent_migration_success(agent_manager, registration_token, existing_mtls_host):
    """
    Test successful migration when agent with duplicate engine_id registers.

    Expected behavior:
    - New agent host created
    - Old host status set to 'migrated'
    - Old host.replaced_by_host_id points to new host
    - Event emitted via event bus
    """
    registration_data = {
        "token": registration_token,
        "engine_id": "engine-12345",  # Matches existing host
        "hostname": "remote-agent",
        "version": "1.0.0",
        "proto_version": "1.0",
        "capabilities": {"container_operations": True},
        "os_type": "linux",
        "os_version": "Ubuntu 22.04",
        "docker_version": "24.0.0",
    }

    result = agent_manager.register_agent(registration_data)

    # Should succeed
    assert result["success"] is True
    assert result["migration_detected"] is True
    assert "migrated_from" in result
    assert result["migrated_from"]["host_name"] == "Local Docker"

    # Check old host is marked as migrated
    with agent_manager.db_manager.get_session() as session:
        old_host = session.query(DockerHostDB).filter_by(id="existing-host-id").first()
        assert old_host.is_active == False  # Migrated hosts are marked inactive
        assert old_host.replaced_by_host_id == result["host_id"]

    # Check new agent host created
    with agent_manager.db_manager.get_session() as session:
        new_host = session.query(DockerHostDB).filter_by(id=result["host_id"]).first()
        assert new_host.connection_type == "agent"
        assert new_host.engine_id == "engine-12345"
        assert new_host.name == "remote-agent"

    # Note: Migration notifications are handled by WebSocket broadcast in websocket_handler.py
    # Event bus is not used for migration events after refactor phase


def test_agent_migration_preserves_settings(agent_manager, registration_token, existing_mtls_host, db_manager):
    """
    Test that container settings are transferred during migration.

    Settings to migrate:
    - Container auto-restart configs
    - Container tags
    - Container desired states
    """
    # Create container settings for old host
    with db_manager.get_session() as session:
        from database import AutoRestartConfig, Tag, TagAssignment, ContainerDesiredState
        import uuid

        # Auto-restart config
        auto_restart = AutoRestartConfig(
            container_id="existing-host-id:abc123456789",  # Composite key
            host_id="existing-host-id",
            enabled=True
        )
        session.add(auto_restart)

        # Container tag (create Tag and TagAssignment)
        tag = Tag(
            id=str(uuid.uuid4()),
            name="production",
            color="#ff0000",
            kind="user"
        )
        session.add(tag)
        session.flush()  # Ensure tag has an ID

        tag_assignment = TagAssignment(
            tag_id=tag.id,
            subject_type="container",
            subject_id="existing-host-id:abc123456789",
            host_id_at_attach="existing-host-id",
            container_name_at_attach="test_container"
        )
        session.add(tag_assignment)

        # Desired state
        desired_state = ContainerDesiredState(
            container_id="existing-host-id:abc123456789",
            host_id="existing-host-id",
            container_name="test_container",
            desired_state="should_run"  # Valid values: 'should_run', 'on_demand', 'unspecified'
        )
        session.add(desired_state)
        session.commit()

    # Register agent with same engine_id
    registration_data = {
        "token": registration_token,
        "engine_id": "engine-12345",
        "hostname": "remote-agent",
        "version": "1.0.0",
        "proto_version": "1.0",
        "capabilities": {},
        "os_type": "linux",
    }

    result = agent_manager.register_agent(registration_data)
    assert result["success"] is True

    new_host_id = result["host_id"]

    # Verify settings were migrated with new composite keys
    with db_manager.get_session() as session:
        from database import AutoRestartConfig, TagAssignment, ContainerDesiredState

        # Auto-restart should use new host_id in composite key
        auto_restart = session.query(AutoRestartConfig).filter_by(
            container_id=f"{new_host_id}:abc123456789"
        ).first()
        assert auto_restart is not None
        assert auto_restart.enabled is True

        # Tag assignment should use new composite key
        tag_assignment = session.query(TagAssignment).filter_by(
            subject_type="container",
            subject_id=f"{new_host_id}:abc123456789"
        ).first()
        assert tag_assignment is not None
        # Verify the tag itself still exists and has the right name
        from database import Tag
        tag = session.query(Tag).filter_by(id=tag_assignment.tag_id).first()
        assert tag.name == "production"

        # Desired state should use new composite key
        desired_state = session.query(ContainerDesiredState).filter_by(
            container_id=f"{new_host_id}:abc123456789"
        ).first()
        assert desired_state is not None
        assert desired_state.desired_state == "should_run"

        # Old settings should be deleted
        old_auto_restart = session.query(AutoRestartConfig).filter_by(
            container_id="existing-host-id:abc123456789"
        ).first()
        assert old_auto_restart is None


def test_agent_migration_rollback_on_failure(agent_manager, registration_token, existing_mtls_host, db_manager):
    """
    Test that failed migration rolls back all changes.

    Simulate failure during migration and verify:
    - Old host unchanged
    - No new host created
    - No settings migrated
    """
    # Patch session.commit to raise an exception
    with patch.object(db_manager, 'get_session') as mock_session:
        session_mock = MagicMock()
        mock_session.return_value.__enter__.return_value = session_mock
        session_mock.commit.side_effect = Exception("Database error")

        registration_data = {
            "token": registration_token,
            "engine_id": "engine-12345",
            "hostname": "remote-agent",
            "version": "1.0.0",
            "proto_version": "1.0",
            "capabilities": {},
            "os_type": "linux",
        }

        result = agent_manager.register_agent(registration_data)

        # Should fail
        assert result["success"] is False
        assert "error" in result

    # Verify old host unchanged
    with db_manager.get_session() as session:
        old_host = session.query(DockerHostDB).filter_by(id="existing-host-id").first()
        assert old_host.is_active == True  # Still active (not migrated)
        assert old_host.replaced_by_host_id is None


def test_no_migration_for_unique_engine_id(agent_manager, registration_token):
    """
    Test normal registration when engine_id doesn't match any existing host.

    Should perform normal registration without migration.
    """
    registration_data = {
        "token": registration_token,
        "engine_id": "unique-engine-id",  # Doesn't match any existing host
        "hostname": "new-agent",
        "version": "1.0.0",
        "proto_version": "1.0",
        "capabilities": {},
        "os_type": "linux",
    }

    result = agent_manager.register_agent(registration_data)

    # Should succeed without migration
    assert result["success"] is True
    assert "migration_detected" not in result or result["migration_detected"] is False

    # Check new host created normally
    with agent_manager.db_manager.get_session() as session:
        new_host = session.query(DockerHostDB).filter_by(id=result["host_id"]).first()
        assert new_host.connection_type == "agent"
        assert new_host.is_active == True  # New host is active
        assert new_host.replaced_by_host_id is None


def test_migration_rejects_already_migrated_host(agent_manager, registration_token, db_manager):
    """
    Test that migration is rejected if existing host is already migrated.

    Prevents cascading migrations.
    """
    now = datetime.now(timezone.utc)

    # Create an already-migrated host
    with db_manager.get_session() as session:
        migrated_host = DockerHostDB(
            id="migrated-host-id",
            name="Already Migrated",
            url="tcp://192.168.1.100:2376",
            connection_type="remote",
            engine_id="engine-67890",
            is_active=False,  # Already migrated (inactive)
            replaced_by_host_id="some-other-host",
            created_at=now,
            updated_at=now
        )
        session.add(migrated_host)
        session.commit()

    registration_data = {
        "token": registration_token,
        "engine_id": "engine-67890",  # Matches migrated host
        "hostname": "another-agent",
        "version": "1.0.0",
        "proto_version": "1.0",
        "capabilities": {},
        "os_type": "linux",
    }

    result = agent_manager.register_agent(registration_data)

    # Should reject
    assert result["success"] is False
    assert "already migrated" in result["error"].lower()


def test_migration_result_contains_proper_details(agent_manager, registration_token, existing_mtls_host):
    """
    Test that migration result contains all necessary information.

    Note: Migration notifications are sent via WebSocket broadcast in websocket_handler.py,
    not via event bus. This test verifies the return value contains migration details.
    """
    registration_data = {
        "token": registration_token,
        "engine_id": "engine-12345",
        "hostname": "remote-agent",
        "version": "1.0.0",
        "proto_version": "1.0",
        "capabilities": {},
        "os_type": "linux",
        "os_version": "Ubuntu 22.04",
    }

    result = agent_manager.register_agent(registration_data)
    assert result["success"] is True
    assert result["migration_detected"] is True

    # Check migration details in result
    assert "migrated_from" in result
    assert result["migrated_from"]["host_id"] == "existing-host-id"
    assert result["migrated_from"]["host_name"] == "Local Docker"
    assert result["host_id"] is not None
    assert result["agent_id"] is not None


def test_migration_rejects_local_connection(agent_manager, registration_token, db_manager):
    """
    Test that migration is REJECTED if existing host is a local connection.

    Local Docker socket management is the only way to manage localhost.
    Agents are ONLY for remote hosts.
    """
    now = datetime.now(timezone.utc)

    # Create a local connection host
    with db_manager.get_session() as session:
        local_host = DockerHostDB(
            id="local-host-id",
            name="Local Docker",
            url="unix:///var/run/docker.sock",
            connection_type="local",  # LOCAL connection
            engine_id="engine-local-123",
            created_at=now,
            updated_at=now
        )
        session.add(local_host)
        session.commit()

    # Try to register agent with same engine_id
    registration_data = {
        "token": registration_token,
        "engine_id": "engine-local-123",  # Matches local host
        "hostname": "attempt-agent",
        "version": "1.0.0",
        "proto_version": "1.0",
        "capabilities": {},
        "os_type": "linux",
    }

    result = agent_manager.register_agent(registration_data)

    # Should REJECT
    assert result["success"] is False
    assert "local" in result["error"].lower()
    assert "not supported" in result["error"].lower()

    # Verify local host unchanged
    with db_manager.get_session() as session:
        local_host = session.query(DockerHostDB).filter_by(id="local-host-id").first()
        assert local_host.connection_type == "local"
        assert local_host.replaced_by_host_id is None

    # Verify no agent created
    with agent_manager.db_manager.get_session() as session:
        agents = session.query(Agent).filter_by(engine_id="engine-local-123").all()
        assert len(agents) == 0
