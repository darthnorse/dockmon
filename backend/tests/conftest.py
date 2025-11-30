"""
Shared pytest fixtures for DockMon tests.

Fixtures provided:
- test_db: Temporary SQLite database for testing
- mock_docker_client: Mock Docker SDK client
- test_host: Test Docker host record
- test_container_data: Sample container data (from Docker, not database)
- mock_monitor: Mock DockerMonitor for EventBus
- event_bus: Test event bus instance

Note: DockMon doesn't store containers in database - they come from Docker API.
The database only stores metadata: ContainerDesiredState, ContainerUpdate, ContainerHttpHealthCheck.
"""

import pytest
import tempfile
import os
import logging
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import docker

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import Base
from event_bus import EventBus

logger = logging.getLogger(__name__)


# =============================================================================
# Docker Image Management
# =============================================================================

# Required Docker images for integration tests
# These are checked/pulled once per test session
REQUIRED_IMAGES = [
    "alpine:latest",
    "nginx:latest",
    "grafana/grafana:latest",  # Official grafana image
    "redis:latest",
    "postgres:latest",
]


@pytest.fixture(scope="session", autouse=True)
def ensure_docker_images():
    """
    Ensure required Docker images are available before running tests.

    Pulls images only if missing - never re-pulls or deletes.
    Runs once per pytest session (not per test).
    Images persist on the system for future test runs.

    This prevents:
    - Test failures due to missing images
    - Redundant image pulls (rate limit protection)
    - Manual setup steps before running tests

    Benefits:
    - First run: Auto-pulls missing images (~30-60s one-time cost)
    - Subsequent runs: Instant (images already cached)
    - Multiple test runs: No additional downloads
    - Rate limit safe: Only pulls when actually missing
    """
    try:
        client = docker.from_env()

        for image_name in REQUIRED_IMAGES:
            try:
                client.images.get(image_name)
                logger.debug(f"✓ Image {image_name} available")
            except docker.errors.ImageNotFound:
                logger.info(f"Pulling {image_name}...")
                client.images.pull(image_name)
                logger.info(f"✓ Pulled {image_name}")

        client.close()

    except Exception as e:
        logger.warning(f"Could not ensure Docker images: {e}")
        # Don't fail here - let individual tests fail if needed


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def test_db():
    """
    Create a temporary SQLite database for testing.

    Yields a session that is rolled back after the test.
    Ensures tests don't affect each other.
    """
    # Create temporary database file
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    engine = create_engine(f'sqlite:///{db_path}')

    # Enable foreign key constraints in SQLite (required for CASCADE/SET NULL)
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create all tables
    Base.metadata.create_all(engine)

    # Create session
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    # Cleanup
    session.close()
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def db_session(test_db):
    """
    Alias for test_db to support tests that use db_session naming.

    Some tests use 'db_session', others use 'test_db' - this provides compatibility.
    """
    return test_db


@pytest.fixture(scope="function")
def db_engine():
    """
    Create a temporary SQLite database engine for testing.

    Yields the engine directly for tests that need to create their own sessions.
    Used by tests that need database-level access (e.g., cache tests).
    """
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    engine = create_engine(f'sqlite:///{db_path}')

    # Enable foreign key constraints in SQLite
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create all tables
    Base.metadata.create_all(engine)

    yield engine

    # Cleanup
    engine.dispose()
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def test_database_manager(test_db):
    """
    Create a mock DatabaseManager for testing.

    Wraps the test_db session in an object that implements DatabaseManager interface.
    """
    from unittest.mock import Mock
    from contextlib import contextmanager

    mock_db = Mock()

    # get_session() should return a context manager that yields the test session
    @contextmanager
    def get_session_cm():
        yield test_db

    mock_db.get_session = get_session_cm
    return mock_db


@pytest.fixture
def mock_docker_client():
    """
    Mock Docker SDK client for testing without real Docker daemon.

    Returns a MagicMock with common Docker SDK methods stubbed.
    """
    client = MagicMock()

    # Mock containers.list()
    client.containers.list = MagicMock(return_value=[])

    # Mock containers.get()
    mock_container = MagicMock()
    mock_container.short_id = "abc123def456"
    mock_container.id = "abc123def456789012345678901234567890123456789012345678901234"
    mock_container.name = "test-container"
    mock_container.status = "running"
    mock_container.attrs = {
        'State': {'Status': 'running'},
        'Config': {
            'Image': 'nginx:latest',
            'Labels': {}
        }
    }
    client.containers.get = MagicMock(return_value=mock_container)

    # Mock images.pull()
    client.images.pull = MagicMock()

    # Mock ping()
    client.ping = MagicMock(return_value=True)

    return client


@pytest.fixture
def test_host(test_db: Session):
    """
    Create a test Docker host in the database.

    Returns:
        DockerHostDB: Test host with ID '7be442c9-24bc-4047-b33a-41bbf51ea2f9'
    """
    from database import DockerHostDB

    host = DockerHostDB(
        id='7be442c9-24bc-4047-b33a-41bbf51ea2f9',
        name='test-host',
        url='unix:///var/run/docker.sock',
        is_active=True,
        created_at=datetime.utcnow()
    )
    test_db.add(host)
    test_db.commit()
    test_db.refresh(host)

    return host


@pytest.fixture
def test_user(test_db: Session):
    """
    Create a test user in the database.

    Required for tests that create Deployments or other records with user_id FK.

    Returns:
        User: Test user with id=1
    """
    from database import User

    user = User(
        username='testuser',
        password_hash='$2b$12$test_hash_not_real',
        role='admin',
        created_at=datetime.utcnow()
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)

    return user


@pytest.fixture
def test_container_data():
    """
    Sample container data as it comes from Docker API.
    
    Note: Containers are NOT stored in database - they're retrieved from Docker.
    Use this fixture to mock Docker API responses.

    Returns:
        dict: Container data in the format DockMon expects from Docker
    """
    return {
        'short_id': 'abc123def456',  # 12 chars
        'id': 'abc123def456789012345678901234567890123456789012345678901234',
        'name': 'test-nginx',
        'image': 'nginx:latest',
        'state': 'running',
        'status': 'Up 5 minutes',
        'created': datetime.utcnow().isoformat(),
    }


@pytest.fixture
def test_container_desired_state(test_db: Session, test_host):
    """
    Create container desired state (user preferences) in database.
    
    This is what DockMon actually stores - user preferences for containers,
    not the containers themselves.

    Returns:
        ContainerDesiredState: User preferences for a container
    """
    from database import ContainerDesiredState

    # Composite key format: {host_id}:{container_id}
    composite_key = f"{test_host.id}:abc123def456"

    state = ContainerDesiredState(
        container_id=composite_key,
        container_name='test-nginx',  # REQUIRED field
        host_id=test_host.id,
        custom_tags='["test", "nginx"]',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(state)
    test_db.commit()
    test_db.refresh(state)

    return state


@pytest.fixture
def test_container_update(test_db: Session, test_host):
    """
    Create container update record in database.

    Tracks update availability for a container.

    Returns:
        ContainerUpdate: Update tracking record
    """
    from database import ContainerUpdate

    # Composite key format: {host_id}:{container_id}
    composite_key = f"{test_host.id}:abc123def456"

    update = ContainerUpdate(
        container_id=composite_key,
        host_id=test_host.id,
        current_image='nginx:latest',
        current_digest='sha256:abc123def456789',  # Required field
        latest_image='nginx:alpine',
        latest_digest='sha256:def456abc789012',  # Required field
        update_available=True,
        floating_tag_mode='latest',  # For tracking mode tests
        last_checked_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(update)
    test_db.commit()
    test_db.refresh(update)

    return update


@pytest.fixture
def test_container_metadata(test_host):
    """
    Create container metadata dict for tests.

    Returns a dict representing container metadata with composite key format.
    This is NOT stored in database - it's just test data.

    Returns:
        dict: Container metadata with id (composite key), name, image
    """
    composite_key = f"{test_host.id}:abc123def456"

    return {
        "id": composite_key,
        "name": "test-container",
        "image": "nginx:1.25.0",
        "host_id": test_host.id,
        "short_id": "abc123def456"
    }


@pytest.fixture
def test_api_key_read(test_db: Session):
    """
    Create a read-only API key for testing authenticated endpoints.

    Returns:
        str: The raw API key token (unhashed) for use in Authorization header
    """
    from database import ApiKey, User
    import secrets
    import hashlib

    # First create a test user (ApiKey requires user_id)
    user = User(
        username="test_api_user",
        password_hash="$2b$12$test_hash_not_real",
        created_at=datetime.utcnow()
    )
    test_db.add(user)
    test_db.flush()  # Get user.id without committing

    # Generate a test API key (must start with "dockmon_" prefix)
    raw_key = f"dockmon_{secrets.token_hex(16)}"

    # Hash it for storage (same as production)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    api_key = ApiKey(
        user_id=user.id,
        name="Test Read Key",
        key_hash=key_hash,
        key_prefix=raw_key[:12],  # First 12 chars for UI display ("dockmon_xxxx")
        scopes="read",  # Comma-separated string, not list
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        revoked_at=None  # None means active
    )
    test_db.add(api_key)
    test_db.commit()

    return raw_key


@pytest.fixture
def test_api_key_write(test_db: Session):
    """
    Create a write-enabled API key for testing authenticated endpoints.

    Returns:
        str: The raw API key token (unhashed) for use in Authorization header
    """
    from database import ApiKey, User
    import secrets
    import hashlib

    # First create a test user (ApiKey requires user_id)
    user = User(
        username="test_api_write_user",
        password_hash="$2b$12$test_hash_not_real",
        created_at=datetime.utcnow()
    )
    test_db.add(user)
    test_db.flush()  # Get user.id without committing

    # Generate a test API key (must start with "dockmon_" prefix)
    raw_key = f"dockmon_{secrets.token_hex(16)}"

    # Hash it for storage (same as production)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    api_key = ApiKey(
        user_id=user.id,
        name="Test Write Key",
        key_hash=key_hash,
        key_prefix=raw_key[:12],  # First 12 chars for UI display
        scopes="read,write",  # Write-enabled
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        revoked_at=None
    )
    test_db.add(api_key)
    test_db.commit()

    return raw_key


@pytest.fixture
def mock_monitor():
    """
    Mock DockerMonitor for EventBus initialization.

    EventBus requires a monitor instance, so we mock it for tests.
    """
    monitor = MagicMock()
    monitor.hosts = {}
    return monitor


@pytest.fixture
def event_bus(mock_monitor):
    """
    Create a fresh EventBus instance for testing.

    Useful for testing event emission and subscribers.
    """
    bus = EventBus(mock_monitor)
    return bus


@pytest.fixture
def freeze_time():
    """
    Freeze time for deterministic testing.

    Usage:
        def test_something(freeze_time):
            freeze_time('2025-10-24 10:00:00')
            # Now datetime.utcnow() always returns this time
    """
    from freezegun import freeze_time as _freeze_time
    return _freeze_time


@pytest.fixture
def sample_docker_container_response():
    """
    Sample Docker container data as returned by Docker SDK.

    Returns:
        dict: Container data in Docker SDK format
    """
    return {
        'Id': 'abc123def456789012345678901234567890123456789012345678901234',
        'Name': '/test-nginx',
        'State': {
            'Status': 'running',
            'Running': True,
            'Paused': False,
            'Restarting': False,
            'OOMKilled': False,
            'Dead': False,
            'Pid': 12345,
            'ExitCode': 0
        },
        'Config': {
            'Image': 'nginx:latest',
            'Labels': {
                'com.docker.compose.project': 'test',
                'dockmon.managed': 'false'
            },
            'Env': ['PATH=/usr/local/bin']
        },
        'NetworkSettings': {
            'Ports': {
                '80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8080'}]
            }
        }
    }


@pytest.fixture
def managed_container_data(test_host):
    """
    Sample managed container data (for v2.1 deployment testing).

    Returns container data with deployment metadata.

    Returns:
        dict: Managed container data with deployment_id
    """
    return {
        'short_id': 'managed123',
        'id': 'managed123456789012345678901234567890123456789012345678901234',
        'name': 'managed-app',
        'image': 'myapp:v1',
        'state': 'running',
        'status': 'Up 2 minutes',
        'labels': {
            'dockmon.deployment_id': f'{test_host.id}:deploy-uuid',
            'dockmon.managed': 'true'
        }
    }


# ============================================================================
# v2.1 Deployment Fixtures
# ============================================================================

@pytest.fixture
def mock_event_bus():
    """Mock EventBus for deployment executor testing"""
    bus = MagicMock()
    bus.emit = AsyncMock()
    return bus


@pytest.fixture
def mock_docker_monitor(mock_docker_client):
    """Mock DockerMonitor for deployment executor testing"""
    monitor = MagicMock()
    monitor.clients = {}
    monitor.manager = MagicMock()
    monitor.manager.broadcast = AsyncMock()
    return monitor

@pytest.fixture
def test_deployment(test_db: Session, test_host, test_user):
    """
    Create a test Deployment in the database.

    For v2.1 deployment feature testing.
    Uses composite key format: {host_id}:{deployment_id}

    Returns:
        Deployment: Test deployment instance
    """
    from database import Deployment

    # Composite key: host UUID + 12-char deployment ID
    deployment_short_id = "abc123def456"  # 12 chars (SHORT ID)
    composite_key = f"{test_host.id}:{deployment_short_id}"

    deployment = Deployment(
        id=composite_key,
        host_id=test_host.id,
        user_id=test_user.id,  # FK to users table
        deployment_type='container',
        name='test-nginx',
        status='planning',  # Valid status per CHECK constraint
        definition='{"container": {"image": "nginx:alpine", "ports": {"80/tcp": 8080}}}',
        progress_percent=0,
        current_stage='Initializing',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        created_by='test_user'
    )
    test_db.add(deployment)
    test_db.commit()
    test_db.refresh(deployment)

    return deployment


@pytest.fixture
def test_deployment_container(test_db: Session, test_deployment, test_container_desired_state):
    """
    Create a DeploymentContainer link (junction table).

    Links a deployment to a container using composite keys.

    Returns:
        DeploymentContainer: Link between deployment and container
    """
    from database import DeploymentContainer

    link = DeploymentContainer(
        deployment_id=test_deployment.id,
        container_id=test_container_desired_state.container_id,  # Uses composite key
        service_name=None,  # NULL for single container deployments
        created_at=datetime.utcnow()
    )
    test_db.add(link)
    test_db.commit()
    test_db.refresh(link)

    return link


@pytest.fixture
def test_deployment_template(test_db: Session):
    """
    Create a test deployment template.

    Templates store pre-configured deployments for common applications.

    Returns:
        DeploymentTemplate: Test template instance
    """
    from database import DeploymentTemplate
    import json

    template = DeploymentTemplate(
        id='tpl_test_nginx',
        name='test-nginx-template',
        category='web',
        description='Test Nginx template for testing',
        deployment_type='container',
        template_definition=json.dumps({
            'container': {
                'image': 'nginx:${VERSION}',
                'ports': {'80/tcp': '${PORT}'}
            }
        }),
        variables=json.dumps({
            'VERSION': {'default': 'latest', 'type': 'string', 'description': 'Nginx version'},
            'PORT': {'default': 8080, 'type': 'integer', 'description': 'Host port'}
        }),
        is_builtin=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(template)
    test_db.commit()
    test_db.refresh(template)

    return template


@pytest.fixture
def test_stack_deployment(test_db: Session, test_host, test_user):
    """
    Create a test stack deployment (multi-container).

    For testing Docker Compose stack deployments.

    Returns:
        Deployment: Test stack deployment instance
    """
    from database import Deployment

    deployment_short_id = "stack1234567"  # 12 chars
    composite_key = f"{test_host.id}:{deployment_short_id}"

    deployment = Deployment(
        id=composite_key,
        host_id=test_host.id,
        user_id=test_user.id,  # FK to users table
        deployment_type='stack',
        name='wordpress-stack',
        status='running',
        definition='{"stack": {"compose_file_path": "/app/data/stacks/wordpress/docker-compose.yml"}}',
        progress_percent=100,
        current_stage='Running',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        created_by='test_user'
    )
    test_db.add(deployment)
    test_db.commit()
    test_db.refresh(deployment)

    return deployment

@pytest.fixture
def client(test_db, monkeypatch):
    """
    FastAPI TestClient for API endpoint testing.

    Uses test_db fixture and overrides database dependency to use in-memory test database.
    Enables integration testing of API endpoints without real database.
    """
    from fastapi.testclient import TestClient
    from contextlib import contextmanager

    # Import main app
    import main

    # Override get_db dependency to use test_db
    @contextmanager
    def override_get_db():
        yield test_db

    # Mock DatabaseManager for the app
    mock_db_manager = MagicMock()
    mock_db_manager.get_session = override_get_db

    # Replace app's database manager with test database (if it exists)
    if hasattr(main, "db"):
        monkeypatch.setattr(main, "db", mock_db_manager)

    # Also override deployment routes' database manager dependency
    from deployment import routes as deployment_routes
    monkeypatch.setattr(deployment_routes, "_database_manager", mock_db_manager)

    # Bypass authentication for tests
    from auth.v2_routes import get_current_user
    def mock_get_current_user():
        return {"username": "test_user"}

    main.app.dependency_overrides[get_current_user] = mock_get_current_user

    # Create test client
    with TestClient(main.app) as test_client:
        yield test_client

    # Clean up overrides
    main.app.dependency_overrides.clear()


# =============================================================================
# Helper Functions (Not Fixtures)
# =============================================================================

def create_composite_key(host_id: str, container_id: str) -> str:
    """
    Create composite key for multi-host container identification.
    
    Format: {host_id}:{container_id}
    """
    return f"{host_id}:{container_id}"


def create_mock_container(container_id: str = "abc123def456", name: str = "test-container", image: str = "nginx:latest", state: str = "running", labels: dict = None):
    """
    Create a mock container object for testing.

    Args:
        container_id: Container ID (12 chars, SHORT ID)
        name: Container name
        image: Container image
        state: Container state
        labels: Container labels dict (optional)

    Returns:
        Mock container with standard attributes
    """
    from unittest.mock import Mock

    if labels is None:
        labels = {}

    container = Mock()
    container.short_id = container_id
    container.id = container_id + "0" * 52  # Pad to 64 chars for full ID
    container.name = name
    container.status = state
    container.labels = labels
    container.attrs = {
        'State': {'Status': state},
        'Config': {
            'Image': image,
            'Labels': labels
        }
    }
    return container
