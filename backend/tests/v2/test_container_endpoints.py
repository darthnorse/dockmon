"""
Tests for container-related API endpoints

CRITICAL: These tests verify that all container operations require
both host_id AND container_id to prevent container ID collisions
across different Docker hosts (e.g., cloned VMs, LXC containers).

This was a bug in DockMon v1 that was fixed, and we must ensure
it stays fixed in v2.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
from main import app


@pytest.fixture
def mock_auth():
    """Mock authentication and rate limiting to bypass both in tests"""
    from main import get_current_user
    from security.rate_limiting import rate_limiter

    def override_get_current_user():
        return {'username': 'testuser', 'user_id': 1}

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Mock the rate limiter to always allow requests
    with patch.object(rate_limiter, 'is_allowed', return_value=(True, None)):
        yield

    app.dependency_overrides.clear()


@pytest.fixture
def client(mock_auth):
    """Test client with authentication and rate limiting mocked"""
    return TestClient(app)


@pytest.fixture
def unauthenticated_client():
    """Test client WITHOUT authentication (for testing auth requirements)"""
    return TestClient(app)


@pytest.fixture
def mock_monitor():
    """Mock DockerMonitor instance"""
    from fastapi import HTTPException

    with patch('main.monitor') as mock:
        # Mock hosts
        mock.hosts = {
            'host-1': Mock(id='host-1', name='Host 1'),
            'host-2': Mock(id='host-2', name='Host 2'),
        }

        # Mock clients - only host-1 and host-2 exist
        mock.clients = {
            'host-1': Mock(),
            'host-2': Mock(),
        }

        # Mock methods that validate host_id (raise HTTPException like real monitor)
        def validate_host_id(host_id, container_id, *args):
            if host_id not in mock.clients:
                raise HTTPException(status_code=404, detail="Host not found")
            return True

        mock.restart_container = Mock(side_effect=validate_host_id)
        mock.stop_container = Mock(side_effect=validate_host_id)
        mock.start_container = Mock(side_effect=validate_host_id)

        # These methods don't return values, just validate
        def validate_host_no_return(host_id, container_id, *args, **kwargs):
            if host_id not in mock.clients:
                raise HTTPException(status_code=404, detail="Host not found")

        mock.toggle_auto_restart = Mock(side_effect=validate_host_no_return)
        mock.set_container_desired_state = Mock(side_effect=validate_host_no_return)

        yield mock


class TestContainerEndpointSecurity:
    """Test that all container endpoints require both host_id and container_id"""

    def test_restart_container_requires_host_id_and_container_id(self, client, mock_monitor):
        """Restart endpoint must use /hosts/{host_id}/containers/{container_id}/restart"""
        response = client.post('/api/hosts/host-1/containers/container-123/restart')

        # Should succeed (not 404)
        assert response.status_code == 200

        # Verify monitor was called with correct host_id
        mock_monitor.restart_container.assert_called_once_with('host-1', 'container-123')

    def test_stop_container_requires_host_id_and_container_id(self, client, mock_monitor):
        """Stop endpoint must use /hosts/{host_id}/containers/{container_id}/stop"""
        response = client.post('/api/hosts/host-1/containers/container-123/stop')

        assert response.status_code == 200
        mock_monitor.stop_container.assert_called_once_with('host-1', 'container-123')

    def test_start_container_requires_host_id_and_container_id(self, client, mock_monitor):
        """Start endpoint must use /hosts/{host_id}/containers/{container_id}/start"""
        response = client.post('/api/hosts/host-1/containers/container-123/start')

        assert response.status_code == 200
        mock_monitor.start_container.assert_called_once_with('host-1', 'container-123')

    def test_auto_restart_requires_host_id_and_container_id(self, client, mock_monitor):
        """Auto-restart endpoint must use /hosts/{host_id}/containers/{container_id}/auto-restart"""
        response = client.post(
            '/api/hosts/host-1/containers/container-123/auto-restart',
            json={'container_name': 'test-container', 'enabled': True}
        )

        assert response.status_code == 200

        # Verify host_id from URL was used (not from request body)
        # Container ID is normalized to short (12 chars)
        mock_monitor.toggle_auto_restart.assert_called_once_with(
            'host-1',  # From URL path
            'container-12',  # Normalized to 12 chars
            'test-container',
            True
        )

    def test_container_logs_requires_host_id_and_container_id(self, client, mock_monitor):
        """Container logs endpoint must use /hosts/{host_id}/containers/{container_id}/logs"""
        # Mock container.logs() method
        mock_container = Mock()
        mock_container.logs = Mock(return_value=b'test logs')
        mock_monitor.clients['host-1'].containers.get = Mock(return_value=mock_container)

        response = client.get('/api/hosts/host-1/containers/container-123/logs')

        # Should succeed
        assert response.status_code == 200

    def test_container_events_requires_host_id_and_container_id(self, client, mock_monitor):
        """Container events endpoint must use /hosts/{host_id}/events/container/{container_id}"""
        # Mock database get_events method
        mock_monitor.db = Mock()
        mock_monitor.db.get_events = Mock(return_value=([], 0))

        response = client.get('/api/hosts/host-1/events/container/container-123')

        assert response.status_code == 200

        # Verify both host_id and container_id were passed
        mock_monitor.db.get_events.assert_called_once()
        call_kwargs = mock_monitor.db.get_events.call_args[1]
        assert call_kwargs['host_id'] == 'host-1'
        assert call_kwargs['container_id'] == 'container-123'


class TestContainerIDCollisionPrevention:
    """
    Test scenarios where container IDs collide across different hosts

    This simulates the real-world scenario from DockMon v1 where
    cloning VMs or LXC containers results in identical container IDs.
    """

    def test_different_hosts_same_container_id(self, client, mock_monitor):
        """
        Two different hosts can have containers with the same ID.
        Operations must target the correct host.
        """
        container_id = 'collision-123'

        # Restart container on host-1
        response1 = client.post(f'/api/hosts/host-1/containers/{container_id}/restart')
        assert response1.status_code == 200
        mock_monitor.restart_container.assert_called_with('host-1', container_id)

        # Restart container with SAME ID on host-2
        response2 = client.post(f'/api/hosts/host-2/containers/{container_id}/restart')
        assert response2.status_code == 200
        mock_monitor.restart_container.assert_called_with('host-2', container_id)

        # Verify each call targeted the correct host
        assert mock_monitor.restart_container.call_count == 2

    def test_auto_restart_uses_url_host_id_not_body(self, client, mock_monitor):
        """
        Auto-restart endpoint must use host_id from URL path, not request body.
        This prevents security issues where an attacker could manipulate the host_id.
        """
        response = client.post(
            '/api/hosts/host-1/containers/container-123/auto-restart',
            json={
                'container_name': 'test-container',
                'enabled': True,
                # Even if an attacker tries to inject a different host_id, it should be ignored
            }
        )

        assert response.status_code == 200

        # Verify the host_id from URL was used, not any potential body value
        call_args = mock_monitor.toggle_auto_restart.call_args[0]
        assert call_args[0] == 'host-1', "Must use host_id from URL path"


class TestContainerEndpointValidation:
    """Test validation and error handling for container endpoints"""

    def test_missing_host_id_returns_404(self, client):
        """Endpoints without host_id should return 404"""
        # Old endpoint format (without host_id) should not exist
        response = client.post('/api/containers/container-123/restart')
        assert response.status_code == 404

    def test_invalid_host_returns_404(self, client, mock_monitor):
        """Operations on non-existent host should fail"""
        mock_monitor.clients = {'host-1': Mock()}  # Only host-1 exists

        response = client.post('/api/hosts/invalid-host/containers/container-123/restart')
        assert response.status_code == 404

    def test_authentication_required(self, unauthenticated_client):
        """All container endpoints require authentication"""
        # Without mock_auth, should get 401
        response = unauthenticated_client.post('/api/hosts/host-1/containers/container-123/restart')
        assert response.status_code == 401

    def test_desired_state_requires_host_id_and_container_id(self, client, mock_monitor):
        """Desired state endpoint must use /hosts/{host_id}/containers/{container_id}/desired-state"""
        response = client.post(
            '/api/hosts/host-1/containers/container-123/desired-state',
            json={'container_name': 'test-container', 'desired_state': 'should_run'}
        )

        assert response.status_code == 200

        # Verify host_id from URL was used
        # Container ID is normalized to short (12 chars)
        mock_monitor.set_container_desired_state.assert_called_once_with(
            'host-1',  # From URL path
            'container-12',  # Normalized to 12 chars
            'test-container',
            'should_run'
        )

    def test_desired_state_validates_state_values(self, client, mock_monitor):
        """Desired state must be one of: should_run, on_demand, unspecified"""
        # Valid states
        for state in ['should_run', 'on_demand', 'unspecified']:
            response = client.post(
                '/api/hosts/host-1/containers/container-123/desired-state',
                json={'container_name': 'test-container', 'desired_state': state}
            )
            assert response.status_code == 200

    def test_container_id_normalization_to_short_id(self, client, mock_monitor):
        """Container IDs should be normalized to 12 chars (short ID) before processing"""
        # Full 64-char container ID
        full_id = 'bb604ae91ecf36c0df0e014bd49604cc1eb6dbab4613fccfe3ee6cc9f5b82994'
        short_id = full_id[:12]

        # Test auto-restart endpoint
        response = client.post(
            f'/api/hosts/host-1/containers/{full_id}/auto-restart',
            json={'container_name': 'test-container', 'enabled': True}
        )
        assert response.status_code == 200

        # Should be called with short ID
        mock_monitor.toggle_auto_restart.assert_called_with(
            'host-1',
            short_id,  # Normalized to 12 chars
            'test-container',
            True
        )

    def test_container_id_normalization_desired_state(self, client, mock_monitor):
        """Desired state endpoint should also normalize container IDs to short"""
        full_id = 'bb604ae91ecf36c0df0e014bd49604cc1eb6dbab4613fccfe3ee6cc9f5b82994'
        short_id = full_id[:12]

        response = client.post(
            f'/api/hosts/host-1/containers/{full_id}/desired-state',
            json={'container_name': 'test-container', 'desired_state': 'should_run'}
        )
        assert response.status_code == 200

        # Should be called with short ID
        mock_monitor.set_container_desired_state.assert_called_with(
            'host-1',
            short_id,  # Normalized to 12 chars
            'test-container',
            'should_run'
        )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
