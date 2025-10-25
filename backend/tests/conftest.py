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
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import Base
from event_bus import EventBus


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
        latest_image='nginx:alpine',
        update_available=True,
        last_checked_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(update)
    test_db.commit()
    test_db.refresh(update)

    return update


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
def test_deployment(test_db: Session, test_host):
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
        deployment_type='container',
        name='test-nginx',
        display_name='Test Nginx Container',
        status='pending',
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
def test_stack_deployment(test_db: Session, test_host):
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
        deployment_type='stack',
        name='wordpress-stack',
        display_name='WordPress Stack',
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
