"""
Integration tests for /api/batch/validate-update endpoint.

Tests pre-flight validation for bulk container updates.
Endpoint should return categorized list of containers: allowed, warned, blocked.
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from main import app
from database import ContainerUpdate, UpdatePolicy


@pytest.fixture
def client():
    """Test client for FastAPI app"""
    return TestClient(app)


@pytest.mark.integration
class TestBatchValidateUpdateEndpoint:
    """Integration tests for batch update validation endpoint"""

    def test_endpoint_requires_authentication(self, client):
        """Endpoint should return 401 without authentication"""
        response = client.post(
            "/api/batch/validate-update",
            json={"container_ids": ["host1:abc123"]},
        )
        assert response.status_code == 401

    def test_validate_all_allowed_containers(
        self,
        client,
        db_session,
        test_host,
        test_api_key_write,
        monkeypatch
    ):
        """Test validation when all containers are allowed"""
        # Clear any existing validation patterns to ensure clean test
        # Use monitor.db (production session) since endpoint uses it
        import main as main_module
        with main_module.monitor.db.get_session() as session:
            session.query(UpdatePolicy).delete()
            session.commit()

        # Create update records for containers with no restrictions
        update1 = ContainerUpdate(
            container_id=f"{test_host.id}:abc123def456",
            host_id=test_host.id,
            current_image="nginx:1.25",
            current_digest="sha256:abc123",
            update_available=True,
            latest_image="nginx:1.26",
            latest_digest="sha256:def456",
            floating_tag_mode="latest",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        update2 = ContainerUpdate(
            container_id=f"{test_host.id}:def456abc123",
            host_id=test_host.id,
            current_image="redis:7.0",
            current_digest="sha256:xyz789",
            update_available=True,
            latest_image="redis:7.2",
            latest_digest="sha256:uvw456",
            floating_tag_mode="latest",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add_all([update1, update2])
        db_session.commit()

        # Mock monitor to return containers
        from models.docker_models import Container
        mock_containers = [
            Container(
                id='abc123def456', short_id='abc123def456', name='nginx', image='nginx:1.25',
                state='running', status='Up', host_id=test_host.id, host_name='Test Host',
                created='2025-01-01T00:00:00Z', labels={}
            ),
            Container(
                id='def456abc123', short_id='def456abc123', name='redis', image='redis:7.0',
                state='running', status='Up', host_id=test_host.id, host_name='Test Host',
                created='2025-01-01T00:00:00Z', labels={}
            ),
        ]

        import main as main_module
        monkeypatch.setattr(main_module.monitor, 'get_last_containers', lambda: mock_containers)

        # Call validation endpoint
        response = client.post(
            "/api/batch/validate-update",
            json={"container_ids": [
                f"{test_host.id}:abc123def456",
                f"{test_host.id}:def456abc123"
            ]},
            headers={"Authorization": f"Bearer {test_api_key_write}"}
        )

        assert response.status_code == 200
        data = response.json()

        # All containers should be allowed
        assert len(data['allowed']) == 2
        assert len(data['warned']) == 0
        assert len(data['blocked']) == 0
        assert data['summary']['total'] == 2
        assert data['summary']['allowed'] == 2
        assert data['summary']['warned'] == 0
        assert data['summary']['blocked'] == 0

        # Check structure of allowed containers
        assert data['allowed'][0]['container_id'] == f"{test_host.id}:abc123def456"
        assert data['allowed'][0]['container_name'] == 'nginx'
        assert 'reason' in data['allowed'][0]

    def test_validate_warned_containers(
        self,
        client,
        db_session,
        test_host,
        test_api_key_write,
        monkeypatch
    ):
        """Test validation when containers match warning patterns"""
        # Clear any existing validation patterns to ensure clean test
        # Use monitor.db (production session) since endpoint uses it
        import main as main_module
        with main_module.monitor.db.get_session() as session:
            session.query(UpdatePolicy).delete()

            # Create warning pattern for traefik
            pattern = UpdatePolicy(
                pattern="traefik",
                category="critical",
                enabled=True,
                created_at=datetime.now(timezone.utc)
            )
            session.add(pattern)
            session.commit()

        # Create update record
        update1 = ContainerUpdate(
            container_id=f"{test_host.id}:abc123def456",
            host_id=test_host.id,
            current_image="traefik:2.10",
            current_digest="sha256:abc123",
            update_available=True,
            latest_image="traefik:2.11",
            latest_digest="sha256:def456",
            floating_tag_mode="latest",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(update1)
        db_session.commit()

        # Mock monitor
        from models.docker_models import Container
        mock_containers = [
            Container(
                id='abc123def456', short_id='abc123def456', name='traefik', image='traefik:2.10',
                state='running', status='Up', host_id=test_host.id, host_name='Test Host',
                created='2025-01-01T00:00:00Z', labels={}
            ),
        ]
        import main as main_module
        monkeypatch.setattr(main_module.monitor, 'get_last_containers', lambda: mock_containers)

        # Call validation endpoint
        response = client.post(
            "/api/batch/validate-update",
            json={"container_ids": [f"{test_host.id}:abc123def456"]},
            headers={"Authorization": f"Bearer {test_api_key_write}"}
        )

        assert response.status_code == 200
        data = response.json()

        # Container should be warned
        assert len(data['allowed']) == 0
        assert len(data['warned']) == 1
        assert len(data['blocked']) == 0

        # Check warned container details
        warned = data['warned'][0]
        assert warned['container_id'] == f"{test_host.id}:abc123def456"
        assert warned['container_name'] == 'traefik'
        assert 'traefik' in warned['reason'].lower()
        assert warned['matched_pattern'] == 'traefik'

    def test_validate_blocked_containers(
        self,
        client,
        db_session,
        test_host,
        test_api_key_write,
        monkeypatch
    ):
        """Test validation when containers are blocked (e.g., DockMon self-update)"""
        # Create update record for DockMon itself
        update1 = ContainerUpdate(
            container_id=f"{test_host.id}:abc123def456",
            host_id=test_host.id,
            current_image="dockmon:2.0",
            current_digest="sha256:abc123",
            update_available=True,
            latest_image="dockmon:2.1",
            latest_digest="sha256:def456",
            floating_tag_mode="latest",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(update1)
        db_session.commit()

        # Mock monitor
        from models.docker_models import Container
        mock_containers = [
            Container(
                id='abc123def456', short_id='abc123def456', name='dockmon', image='dockmon:2.0',
                state='running', status='Up', host_id=test_host.id, host_name='Test Host',
                created='2025-01-01T00:00:00Z', labels={}
            ),
        ]
        import main as main_module
        monkeypatch.setattr(main_module.monitor, 'get_last_containers', lambda: mock_containers)

        # Call validation endpoint
        response = client.post(
            "/api/batch/validate-update",
            json={"container_ids": [f"{test_host.id}:abc123def456"]},
            headers={"Authorization": f"Bearer {test_api_key_write}"}
        )

        assert response.status_code == 200
        data = response.json()

        # Container should be blocked
        assert len(data['allowed']) == 0
        assert len(data['warned']) == 0
        assert len(data['blocked']) == 1

        # Check blocked container details
        blocked = data['blocked'][0]
        assert blocked['container_id'] == f"{test_host.id}:abc123def456"
        assert blocked['container_name'] == 'dockmon'
        assert 'cannot update itself' in blocked['reason'].lower()

    def test_validate_mixed_containers(
        self,
        client,
        db_session,
        test_host,
        test_api_key_write,
        monkeypatch
    ):
        """Test validation with mix of allowed, warned, and blocked containers"""
        # Clear any existing validation patterns to ensure clean test
        # Use monitor.db (production session) since endpoint uses it
        import main as main_module
        with main_module.monitor.db.get_session() as session:
            session.query(UpdatePolicy).delete()

            # Create warning pattern
            pattern = UpdatePolicy(
                pattern="traefik",
                category="critical",
                enabled=True,
                created_at=datetime.now(timezone.utc)
            )
            session.add(pattern)
            session.commit()

        # Create update records (use proper 12-char IDs)
        updates = [
            ContainerUpdate(
                container_id=f"{test_host.id}:aaaaaa111111",
                host_id=test_host.id,
                current_image="nginx:1.25",
                current_digest="sha256:abc",
                update_available=True,
                latest_image="nginx:1.26",
                latest_digest="sha256:def",
                floating_tag_mode="latest",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            ),
            ContainerUpdate(
                container_id=f"{test_host.id}:bbbbbb222222",
                host_id=test_host.id,
                current_image="traefik:2.10",
                current_digest="sha256:xyz",
                update_available=True,
                latest_image="traefik:2.11",
                latest_digest="sha256:uvw",
                floating_tag_mode="latest",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            ),
            ContainerUpdate(
                container_id=f"{test_host.id}:cccccc333333",
                host_id=test_host.id,
                current_image="dockmon:2.0",
                current_digest="sha256:ddd",
                update_available=True,
                latest_image="dockmon:2.1",
                latest_digest="sha256:eee",
                floating_tag_mode="latest",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            ),
        ]
        db_session.add_all(updates)
        db_session.commit()

        # Mock monitor
        from models.docker_models import Container
        mock_containers = [
            Container(
                id='aaaaaa111111', short_id='aaaaaa111111', name='nginx', image='nginx:1.25',
                state='running', status='Up', host_id=test_host.id, host_name='Test Host',
                created='2025-01-01T00:00:00Z', labels={}
            ),
            Container(
                id='bbbbbb222222', short_id='bbbbbb222222', name='traefik', image='traefik:2.10',
                state='running', status='Up', host_id=test_host.id, host_name='Test Host',
                created='2025-01-01T00:00:00Z', labels={}
            ),
            Container(
                id='cccccc333333', short_id='cccccc333333', name='dockmon', image='dockmon:2.0',
                state='running', status='Up', host_id=test_host.id, host_name='Test Host',
                created='2025-01-01T00:00:00Z', labels={}
            ),
        ]
        import main as main_module
        monkeypatch.setattr(main_module.monitor, 'get_last_containers', lambda: mock_containers)

        # Call validation endpoint
        response = client.post(
            "/api/batch/validate-update",
            json={"container_ids": [
                f"{test_host.id}:aaaaaa111111",
                f"{test_host.id}:bbbbbb222222",
                f"{test_host.id}:cccccc333333"
            ]},
            headers={"Authorization": f"Bearer {test_api_key_write}"}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify categorization
        assert len(data['allowed']) == 1  # nginx
        assert len(data['warned']) == 1   # traefik
        assert len(data['blocked']) == 1  # dockmon

        assert data['summary']['total'] == 3
        assert data['summary']['allowed'] == 1
        assert data['summary']['warned'] == 1
        assert data['summary']['blocked'] == 1

        # Verify containers are in correct categories
        assert data['allowed'][0]['container_name'] == 'nginx'
        assert data['warned'][0]['container_name'] == 'traefik'
        assert data['blocked'][0]['container_name'] == 'dockmon'
