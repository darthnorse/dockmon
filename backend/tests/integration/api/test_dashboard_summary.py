"""
Integration tests for /api/dashboard/summary endpoint.

Tests verify the endpoint actually works end-to-end:
- Calls real endpoint code
- Returns proper JSON structure
- Handles authentication
- Aggregates data correctly
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from main import app
from database import ContainerUpdate, DockerHostDB
from docker_monitor.monitor import DockerMonitor


@pytest.fixture
def client():
    """Test client for FastAPI app"""
    return TestClient(app)


@pytest.fixture
def mock_monitor(monkeypatch):
    """Mock the monitor instance with test data"""
    from models.docker_models import DockerHost, Container
    from datetime import datetime, timezone

    # Create mock host data - NOTE: hosts is Dict[str, DockerHost] (Pydantic models)
    mock_host1 = DockerHost(id='host1', name='Test Host 1', url='tcp://host1:2376', status='online')
    mock_host2 = DockerHost(id='host2', name='Test Host 2', url='tcp://host2:2376', status='online')
    mock_host3 = DockerHost(id='host3', name='Test Host 3', url='tcp://host3:2376', status='offline')

    mock_hosts = {
        'host1': mock_host1,
        'host2': mock_host2,
        'host3': mock_host3
    }

    # Create mock container data - NOTE: Container models, not dicts
    mock_container1 = Container(
        id='aaa111', short_id='aaa111', name='container1', image='nginx:latest', state='running',
        status='Up 2 hours', host_id='host1', host_name='Test Host 1', created='2025-11-14T12:00:00Z'
    )
    mock_container2 = Container(
        id='bbb222', short_id='bbb222', name='container2', image='postgres:14', state='running',
        status='Up 5 hours', host_id='host1', host_name='Test Host 1', created='2025-11-14T08:00:00Z'
    )
    mock_container3 = Container(
        id='ccc333', short_id='ccc333', name='container3', image='redis:7', state='running',
        status='Up 1 day', host_id='host2', host_name='Test Host 2', created='2025-11-13T12:00:00Z'
    )
    mock_container4 = Container(
        id='ddd444', short_id='ddd444', name='container4', image='alpine:latest', state='exited',
        status='Exited (0) 2 hours ago', host_id='host2', host_name='Test Host 2', created='2025-11-14T10:00:00Z'
    )
    mock_container5 = Container(
        id='eee555', short_id='eee555', name='container5', image='ubuntu:22.04', state='exited',
        status='Exited (1) 1 day ago', host_id='host2', host_name='Test Host 2', created='2025-11-13T12:00:00Z'
    )
    mock_container6 = Container(
        id='fff666', short_id='fff666', name='container6', image='mysql:8', state='paused',
        status='Paused', host_id='host3', host_name='Test Host 3', created='2025-11-14T06:00:00Z'
    )

    mock_containers = [
        mock_container1, mock_container2, mock_container3,
        mock_container4, mock_container5, mock_container6
    ]

    # Patch monitor.hosts
    import main as main_module
    monkeypatch.setattr(main_module.monitor, 'hosts', mock_hosts)

    # Patch monitor.get_last_containers (not get_all_containers!)
    monkeypatch.setattr(main_module.monitor, 'get_last_containers', lambda: mock_containers)

    return mock_hosts, mock_containers


@pytest.mark.integration
class TestDashboardSummaryEndpoint:
    """Integration tests for dashboard summary endpoint"""

    def test_endpoint_requires_authentication(self, client):
        """Endpoint should return 401 without authentication"""
        response = client.get("/api/dashboard/summary")
        assert response.status_code == 401

    def test_endpoint_returns_correct_structure(
        self,
        client,
        mock_monitor,
        db_session,
        monkeypatch,
        test_api_key_read
    ):
        """
        Endpoint should return JSON with correct structure.

        This is the CRITICAL test that should have caught the bug.
        """
        # Call endpoint with read-only API key
        response = client.get(
            "/api/dashboard/summary",
            headers={"Authorization": f"Bearer {test_api_key_read}"}
        )

        # Assert response
        assert response.status_code == 200
        data = response.json()

        # Verify structure
        assert 'hosts' in data
        assert 'containers' in data
        assert 'updates' in data
        assert 'alerts' in data  # Added in recent update
        assert 'timestamp' in data

        # Should NOT have health
        assert 'health' not in data

    def test_endpoint_counts_hosts_correctly(
        self,
        client,
        mock_monitor,
        db_session,
        monkeypatch,
        test_api_key_read
    ):
        """Endpoint should count online/offline hosts correctly"""
        # Call endpoint with read-only API key
        response = client.get(
            "/api/dashboard/summary",
            headers={"Authorization": f"Bearer {test_api_key_read}"}
        )
        assert response.status_code == 200

        data = response.json()

        # Verify host counts (from mock_monitor fixture)
        assert data['hosts']['online'] == 2
        assert data['hosts']['offline'] == 1
        assert data['hosts']['total'] == 3

    def test_endpoint_counts_containers_correctly(
        self,
        client,
        mock_monitor,
        db_session,
        monkeypatch,
        test_api_key_read
    ):
        """Endpoint should count containers by state correctly"""
        # Call endpoint with read-only API key
        response = client.get(
            "/api/dashboard/summary",
            headers={"Authorization": f"Bearer {test_api_key_read}"}
        )
        assert response.status_code == 200

        data = response.json()

        # Verify container counts (from mock_monitor fixture)
        assert data['containers']['running'] == 3
        assert data['containers']['stopped'] == 2  # 'exited' state
        assert data['containers']['paused'] == 1
        assert data['containers']['total'] == 6

    def test_endpoint_counts_updates_correctly(
        self,
        client,
        mock_monitor,
        db_session,
        test_host,
        monkeypatch,
        test_api_key_read
    ):
        """Endpoint should count available updates from database"""
        import main as main_module
        from contextlib import contextmanager

        # Mock monitor.db.get_session() to use test database
        @contextmanager
        def mock_get_session():
            yield db_session

        monkeypatch.setattr(main_module.monitor.db, 'get_session', mock_get_session)

        # Add some container updates to database
        update1 = ContainerUpdate(
            container_id=f"{test_host.id}:aaa111",
            host_id=test_host.id,  # Required field
            current_image="nginx:1.20",
            current_digest="sha256:abc123",
            update_available=True,
            latest_image="nginx:1.21",
            latest_digest="sha256:def456",
            floating_tag_mode="latest",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        update2 = ContainerUpdate(
            container_id=f"{test_host.id}:bbb222",
            host_id=test_host.id,  # Required field
            current_image="postgres:14",
            current_digest="sha256:xyz789",
            update_available=True,
            latest_image="postgres:15",
            latest_digest="sha256:uvw456",
            floating_tag_mode="latest",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        update3 = ContainerUpdate(
            container_id=f"{test_host.id}:ccc333",
            host_id=test_host.id,  # Required field
            current_image="redis:7",
            current_digest="sha256:red123",
            update_available=False,  # No update available
            latest_image="redis:7",
            latest_digest="sha256:red123",
            floating_tag_mode="exact",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        db_session.add_all([update1, update2, update3])
        db_session.commit()

        # Clear cache to force fresh query
        main_module._dashboard_summary_cache["data"] = None
        main_module._dashboard_summary_cache["timestamp"] = None

        # Call endpoint with read-only API key
        response = client.get(
            "/api/dashboard/summary",
            headers={"Authorization": f"Bearer {test_api_key_read}"}
        )
        assert response.status_code == 200

        data = response.json()

        # Should count only updates where update_available=True
        assert data['updates']['available'] == 2

    def test_endpoint_timestamp_format(
        self,
        client,
        mock_monitor,
        db_session,
        monkeypatch,
        test_api_key_read
    ):
        """Timestamp should be ISO 8601 with 'Z' suffix"""
        # Call endpoint with read-only API key
        response = client.get(
            "/api/dashboard/summary",
            headers={"Authorization": f"Bearer {test_api_key_read}"}
        )
        assert response.status_code == 200

        data = response.json()
        timestamp = data['timestamp']

        # Should end with 'Z' (UTC indicator)
        assert timestamp.endswith('Z')

        # Should be valid ISO 8601
        # Remove 'Z' and parse
        parsed = datetime.fromisoformat(timestamp[:-1])
        assert isinstance(parsed, datetime)

    def test_endpoint_handles_no_containers(
        self,
        client,
        db_session,
        monkeypatch,
        test_api_key_read
    ):
        """Endpoint should handle zero containers gracefully"""
        import main as main_module
        from contextlib import contextmanager

        # Mock empty hosts and containers
        monkeypatch.setattr(main_module.monitor, 'hosts', {})
        monkeypatch.setattr(main_module.monitor, 'get_last_containers', lambda: [])

        # Mock database session to return clean session with no data
        @contextmanager
        def mock_get_session():
            yield db_session

        monkeypatch.setattr(main_module.monitor.db, 'get_session', mock_get_session)

        # Clear cache to force fresh query
        main_module._dashboard_summary_cache["data"] = None
        main_module._dashboard_summary_cache["timestamp"] = None

        # Call endpoint with read-only API key
        response = client.get(
            "/api/dashboard/summary",
            headers={"Authorization": f"Bearer {test_api_key_read}"}
        )
        assert response.status_code == 200

        data = response.json()

        # All counts should be zero
        assert data['hosts']['total'] == 0
        assert data['hosts']['online'] == 0
        assert data['hosts']['offline'] == 0
        assert data['containers']['total'] == 0
        assert data['containers']['running'] == 0
        assert data['containers']['stopped'] == 0
        assert data['containers']['paused'] == 0
        assert data['updates']['available'] == 0
        assert data['alerts']['active'] == 0
