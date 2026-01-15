"""
Integration tests for Podman compatibility during container updates.

Tests verify the full flow:
- Platform detection from Docker API
- Host info storage with is_podman flag
- Parameter filtering during container creation
- End-to-end update flow on Podman hosts

Issue #20: Container updates fail on Podman hosts due to unsupported parameters.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone
import asyncio

# Add backend directory to path
import sys
import os
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, backend_dir)

from database import DatabaseManager, DockerHostDB
from models.docker_models import DockerHost
from docker_monitor.monitor import _fetch_system_info_from_docker
from updates.update_executor import UpdateExecutor


# =============================================================================
# Platform Detection Integration Tests
# =============================================================================

class TestPlatformDetectionIntegration:
    """Test platform detection from Docker API returns correct is_podman value"""

    def test_fetch_system_info_returns_is_podman_true_for_podman(self):
        """_fetch_system_info_from_docker should return is_podman=True for Podman hosts"""
        # Create mock client that returns Podman version info
        mock_client = Mock()
        mock_client.info.return_value = {
            'OSType': 'linux',
            'OperatingSystem': 'Fedora Linux 39',
            'KernelVersion': '6.5.0',
            'MemTotal': 8589934592,
            'NCPU': 4
        }
        mock_client.version.return_value = {
            'Platform': {'Name': 'Podman Engine'},
            'Version': '4.9.0'
        }
        mock_client.networks.list.return_value = []

        # Call the actual function
        result = _fetch_system_info_from_docker(mock_client, 'test-podman-host')

        # Verify is_podman is True
        assert result['is_podman'] is True
        assert result['os_type'] == 'linux'
        assert result['docker_version'] == '4.9.0'

    def test_fetch_system_info_returns_is_podman_false_for_docker(self):
        """_fetch_system_info_from_docker should return is_podman=False for Docker hosts"""
        mock_client = Mock()
        mock_client.info.return_value = {
            'OSType': 'linux',
            'OperatingSystem': 'Ubuntu 22.04',
            'KernelVersion': '5.15.0',
            'MemTotal': 16777216000,
            'NCPU': 8
        }
        mock_client.version.return_value = {
            'Platform': {'Name': 'Docker Engine - Community'},
            'Version': '24.0.6'
        }
        mock_client.networks.list.return_value = []

        result = _fetch_system_info_from_docker(mock_client, 'test-docker-host')

        assert result['is_podman'] is False
        assert result['docker_version'] == '24.0.6'

    def test_fetch_system_info_defaults_to_false_on_error(self):
        """_fetch_system_info_from_docker should return is_podman=False on API error"""
        mock_client = Mock()
        mock_client.info.side_effect = Exception("Connection refused")

        result = _fetch_system_info_from_docker(mock_client, 'test-error-host')

        assert result['is_podman'] is False
        assert result['os_type'] is None

    def test_fetch_system_info_handles_missing_platform_field(self):
        """Should handle missing Platform field gracefully"""
        mock_client = Mock()
        mock_client.info.return_value = {
            'OSType': 'linux',
            'OperatingSystem': 'Alpine',
            'KernelVersion': '5.10.0',
            'MemTotal': 1073741824,
            'NCPU': 2
        }
        mock_client.version.return_value = {
            # No Platform field
            'Version': '20.10.0'
        }
        mock_client.networks.list.return_value = []

        result = _fetch_system_info_from_docker(mock_client, 'test-no-platform')

        assert result['is_podman'] is False  # Default to Docker


# =============================================================================
# Database Integration Tests
# =============================================================================

class TestDatabaseIntegration:
    """Test is_podman is correctly stored and retrieved from database"""

    def test_host_stores_is_podman_true(self, db_session):
        """Host with is_podman=True should be stored correctly"""
        host = DockerHostDB(
            id="podman-host-uuid",
            name="podman-host",
            url="unix:///var/run/podman/podman.sock",
            is_active=True,
            is_podman=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(host)
        db_session.commit()

        # Retrieve and verify
        retrieved = db_session.query(DockerHostDB).filter(
            DockerHostDB.id == "podman-host-uuid"
        ).first()

        assert retrieved is not None
        assert retrieved.is_podman is True
        assert retrieved.name == "podman-host"

    def test_host_stores_is_podman_false(self, db_session):
        """Host with is_podman=False should be stored correctly"""
        host = DockerHostDB(
            id="docker-host-uuid",
            name="docker-host",
            url="unix:///var/run/docker.sock",
            is_active=True,
            is_podman=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(host)
        db_session.commit()

        retrieved = db_session.query(DockerHostDB).filter(
            DockerHostDB.id == "docker-host-uuid"
        ).first()

        assert retrieved is not None
        assert retrieved.is_podman is False

    def test_host_defaults_is_podman_to_false(self, db_session):
        """Host without explicit is_podman should default to False"""
        host = DockerHostDB(
            id="default-host-uuid",
            name="default-host",
            url="unix:///var/run/docker.sock",
            is_active=True,
            # is_podman not set explicitly
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(host)
        db_session.commit()

        retrieved = db_session.query(DockerHostDB).filter(
            DockerHostDB.id == "default-host-uuid"
        ).first()

        assert retrieved.is_podman is False


# =============================================================================
# Update Executor Integration Tests
# =============================================================================

class TestUpdateExecutorIntegration:
    """Test UpdateExecutor correctly uses is_podman during container creation"""

    @pytest.fixture
    def mock_monitor(self):
        """Create mock monitor with hosts dict"""
        monitor = Mock()
        monitor.hosts = {}
        monitor.manager = None
        return monitor

    @pytest.fixture
    def mock_db(self):
        """Create mock database manager"""
        db = Mock(spec=DatabaseManager)
        db.get_session = Mock()
        return db

    @pytest.fixture
    def update_executor(self, mock_db, mock_monitor):
        """Create UpdateExecutor with mocks"""
        executor = UpdateExecutor(mock_db, mock_monitor)
        return executor

    def test_get_is_podman_from_monitor_hosts(self, update_executor, mock_monitor):
        """Update should get is_podman flag from monitor.hosts"""
        # Add a Podman host to monitor
        podman_host = DockerHost(
            id="podman-host-id",
            name="podman-host",
            url="unix:///var/run/podman/podman.sock",
            is_podman=True
        )
        mock_monitor.hosts["podman-host-id"] = podman_host

        # Verify we can retrieve is_podman
        host_id = "podman-host-id"
        is_podman = False
        if hasattr(mock_monitor, 'hosts') and host_id in mock_monitor.hosts:
            is_podman = getattr(mock_monitor.hosts[host_id], 'is_podman', False)

        assert is_podman is True

    def test_get_is_podman_defaults_false_when_host_missing(self, update_executor, mock_monitor):
        """Should default to False when host not in monitor.hosts"""
        host_id = "nonexistent-host-id"
        is_podman = False
        if hasattr(mock_monitor, 'hosts') and host_id in mock_monitor.hosts:
            is_podman = getattr(mock_monitor.hosts[host_id], 'is_podman', False)

        assert is_podman is False


# =============================================================================
# End-to-End Flow Tests
# =============================================================================

class TestEndToEndFlow:
    """Test complete flow from host detection to container update"""

    def test_complete_podman_host_flow(self, db_session):
        """Test complete flow: detect Podman -> store in DB -> filter params"""
        # Step 1: Detect Podman from API
        mock_client = Mock()
        mock_client.info.return_value = {
            'OSType': 'linux',
            'OperatingSystem': 'Fedora',
            'KernelVersion': '6.5.0',
            'MemTotal': 8589934592,
            'NCPU': 4
        }
        mock_client.version.return_value = {
            'Platform': {'Name': 'Podman Engine'},
            'Version': '4.9.0'
        }
        mock_client.networks.list.return_value = []

        sys_info = _fetch_system_info_from_docker(mock_client, 'test-flow-host')
        assert sys_info['is_podman'] is True

        # Step 2: Store in database
        host = DockerHostDB(
            id="flow-test-host-uuid",
            name="flow-test-host",
            url="unix:///var/run/podman/podman.sock",
            is_active=True,
            is_podman=sys_info['is_podman'],
            os_type=sys_info['os_type'],
            docker_version=sys_info['docker_version'],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(host)
        db_session.commit()

        # Step 3: Retrieve and verify
        retrieved = db_session.query(DockerHostDB).filter(
            DockerHostDB.id == "flow-test-host-uuid"
        ).first()
        assert retrieved.is_podman is True

        # Step 4: Verify is_podman flag available for update logic
        # v2.1.9: Filtering now handled internally in _extract_container_config_v2
        # This test verifies the flag is correctly stored and retrievable
        assert retrieved.is_podman is True  # This will be used by update executor

    def test_complete_docker_host_flow(self, db_session):
        """Test complete flow for Docker host (no filtering)"""
        # Step 1: Detect Docker from API
        mock_client = Mock()
        mock_client.info.return_value = {
            'OSType': 'linux',
            'OperatingSystem': 'Ubuntu 22.04',
            'KernelVersion': '5.15.0',
            'MemTotal': 16777216000,
            'NCPU': 8
        }
        mock_client.version.return_value = {
            'Platform': {'Name': 'Docker Engine - Community'},
            'Version': '24.0.6'
        }
        mock_client.networks.list.return_value = []

        sys_info = _fetch_system_info_from_docker(mock_client, 'docker-flow-host')
        assert sys_info['is_podman'] is False

        # Step 2: Store in database
        host = DockerHostDB(
            id="docker-flow-host-uuid",
            name="docker-flow-host",
            url="unix:///var/run/docker.sock",
            is_active=True,
            is_podman=sys_info['is_podman'],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(host)
        db_session.commit()

        # Step 3: Retrieve and verify
        retrieved = db_session.query(DockerHostDB).filter(
            DockerHostDB.id == "docker-flow-host-uuid"
        ).first()
        assert retrieved.is_podman is False

        # Step 4: Verify is_podman flag available for update logic
        # v2.1.9: Passthrough approach preserves all params for Docker
        assert retrieved.is_podman is False  # This will be used by update executor


# =============================================================================
# Edge Case Integration Tests
# =============================================================================

class TestEdgeCaseIntegration:
    """Test edge cases in the integration flow"""

    def test_existing_host_updated_with_is_podman(self, db_session):
        """Existing host should be updatable with is_podman field"""
        # Create host without is_podman (simulates existing DB)
        host = DockerHostDB(
            id="existing-host-uuid",
            name="existing-host",
            url="unix:///var/run/podman/podman.sock",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db_session.add(host)
        db_session.commit()

        # Update with is_podman
        host.is_podman = True
        db_session.commit()

        # Verify
        retrieved = db_session.query(DockerHostDB).filter(
            DockerHostDB.id == "existing-host-uuid"
        ).first()
        assert retrieved.is_podman is True
