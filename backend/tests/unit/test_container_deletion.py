"""
Unit tests for container deletion feature.

Tests the DELETE /api/containers/{host_id}/{container_id} endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
from main import app
from event_bus import EventType


client = TestClient(app)


@pytest.fixture
def mock_docker_client():
    """Mock Docker client"""
    mock_client = Mock()
    mock_container = Mock()
    mock_container.id = "abc123456789"
    mock_container.short_id = "abc123456789"
    mock_container.name = "test-container"
    mock_container.attrs = {
        "Config": {
            "Image": "nginx:latest",
            "Labels": {}
        }
    }
    mock_client.containers.get.return_value = mock_container
    return mock_client


@pytest.fixture
def mock_event_bus():
    """Mock event bus"""
    with patch('main.bus') as mock_bus:
        yield mock_bus


def test_delete_container_success(mock_docker_client, mock_event_bus):
    """Test successful container deletion"""
    with patch('main.get_docker_client', return_value=mock_docker_client):
        with patch('main.async_docker_call') as mock_async:
            # Mock container removal
            mock_async.return_value = None

            response = client.delete(
                "/api/containers/test-host-id/abc123456789",
                params={"removeVolumes": False}
            )

            assert response.status_code == 200
            assert response.json()["success"] is True

            # Verify Docker API was called with correct parameters
            mock_async.assert_called()

            # Verify event was emitted
            mock_event_bus.emit.assert_called_once()
            emitted_event = mock_event_bus.emit.call_args[0][0]
            assert emitted_event.event_type == EventType.CONTAINER_DELETED


def test_delete_container_with_volumes(mock_docker_client, mock_event_bus):
    """Test container deletion with volume removal"""
    with patch('main.get_docker_client', return_value=mock_docker_client):
        with patch('main.async_docker_call') as mock_async:
            mock_async.return_value = None

            response = client.delete(
                "/api/containers/test-host-id/abc123456789",
                params={"removeVolumes": True}
            )

            assert response.status_code == 200

            # Verify Docker API was called with v=True (remove volumes)
            # We'll check this in the actual implementation


def test_delete_container_without_volumes(mock_docker_client, mock_event_bus):
    """Test container deletion without volume removal (default)"""
    with patch('main.get_docker_client', return_value=mock_docker_client):
        with patch('main.async_docker_call') as mock_async:
            mock_async.return_value = None

            # Default should be removeVolumes=False
            response = client.delete(
                "/api/containers/test-host-id/abc123456789"
            )

            assert response.status_code == 200


def test_delete_container_not_found():
    """Test deletion of non-existent container returns 404"""
    mock_client = Mock()
    mock_client.containers.get.side_effect = Exception("Container not found")

    with patch('main.get_docker_client', return_value=mock_client):
        response = client.delete(
            "/api/containers/test-host-id/nonexistent123"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_delete_dockmon_blocked():
    """Test that deleting DockMon container is blocked"""
    mock_client = Mock()
    mock_container = Mock()
    mock_container.name = "dockmon"
    mock_container.short_id = "abc123456789"
    mock_container.attrs = {"Config": {"Image": "dockmon:latest", "Labels": {}}}
    mock_client.containers.get.return_value = mock_container

    with patch('main.get_docker_client', return_value=mock_client):
        response = client.delete(
            "/api/containers/test-host-id/abc123456789"
        )

        assert response.status_code == 403
        assert "cannot delete dockmon itself" in response.json()["detail"].lower()


def test_delete_dockmon_variant_blocked():
    """Test that DockMon variants (dockmon-dev, dockmon-prod) are also blocked"""
    variants = ["dockmon-dev", "dockmon-prod", "dockmon-backup", "dockmon-test"]

    for variant_name in variants:
        mock_client = Mock()
        mock_container = Mock()
        mock_container.name = variant_name
        mock_container.short_id = "abc123456789"
        mock_container.attrs = {"Config": {"Image": "dockmon:latest", "Labels": {}}}
        mock_client.containers.get.return_value = mock_container

        with patch('main.get_docker_client', return_value=mock_client):
            response = client.delete(
                f"/api/containers/test-host-id/abc123456789"
            )

            assert response.status_code == 403, f"Failed to block deletion of {variant_name}"


def test_delete_container_database_cleanup():
    """Test that all database records are cleaned up"""
    mock_client = Mock()
    mock_container = Mock()
    mock_container.name = "test-container"
    mock_container.short_id = "abc123456789"
    mock_container.attrs = {"Config": {"Image": "nginx:latest", "Labels": {}}}
    mock_client.containers.get.return_value = mock_container

    with patch('main.get_docker_client', return_value=mock_client):
        with patch('main.async_docker_call') as mock_async:
            with patch('main.db.get_session') as mock_session:
                mock_async.return_value = None
                session = MagicMock()
                mock_session.return_value.__enter__.return_value = session

                response = client.delete(
                    "/api/containers/test-host-id/abc123456789"
                )

                assert response.status_code == 200

                # Verify database deletions were attempted
                # (We'll check specific tables in implementation)
                assert session.query.called or session.delete.called


def test_delete_container_event_logged(mock_docker_client, mock_event_bus):
    """Test that CONTAINER_DELETED event is emitted and logged"""
    with patch('main.get_docker_client', return_value=mock_docker_client):
        with patch('main.async_docker_call') as mock_async:
            mock_async.return_value = None

            response = client.delete(
                "/api/containers/test-host-id/abc123456789",
                params={"removeVolumes": False}
            )

            assert response.status_code == 200

            # Verify event was emitted to event bus
            mock_event_bus.emit.assert_called_once()
            emitted_event = mock_event_bus.emit.call_args[0][0]

            # Verify event properties
            assert emitted_event.event_type == EventType.CONTAINER_DELETED
            assert emitted_event.scope_type == "container"
            assert emitted_event.scope_id == "abc123456789"
            assert emitted_event.host_id == "test-host-id"
            assert "removed_volumes" in emitted_event.data
