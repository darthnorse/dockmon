"""
Integration tests for backup container cleanup periodic job

Tests verify:
- Only containers with -dockmon-backup- suffix are cleaned up (Issue #75, PR #76)
- Containers with generic -backup- suffix are NOT deleted (user containers)
- 24-hour age threshold is respected
- Containers younger than 24 hours are preserved
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from docker_monitor.periodic_jobs import PeriodicJobsManager


@pytest.fixture
def mock_settings():
    """Mock GlobalSettings"""
    settings = Mock()
    return settings


@pytest.fixture
def jobs_manager(mock_settings):
    """Create PeriodicJobsManager with mocked dependencies"""
    mock_db = Mock()
    mock_db.get_settings.return_value = mock_settings

    mock_event_logger = Mock()

    mock_monitor = Mock()
    mock_monitor.clients = {}  # Will be populated by tests

    manager = PeriodicJobsManager(mock_db, mock_event_logger)
    manager.monitor = mock_monitor

    return manager


def create_mock_backup_container(name: str, created_hours_ago: int = 48):
    """
    Helper to create mock Docker container for backup cleanup tests

    Args:
        name: Container name (e.g., 'nginx-dockmon-backup-1732531200')
        created_hours_ago: How old the container is
    """
    container = Mock()
    container.name = name
    container.id = f"abc{hash(name) % 1000000:06d}def456"
    container.short_id = container.id[:12]

    # Set created timestamp
    created_dt = datetime.now(timezone.utc) - timedelta(hours=created_hours_ago)
    container.attrs = {
        'Created': created_dt.isoformat().replace('+00:00', 'Z')
    }

    # Mock remove method (sync method wrapped by async_docker_call)
    container.remove = Mock()

    return container


class TestBackupContainerCleanup:
    """Tests for cleanup_old_backup_containers()"""

    @pytest.mark.asyncio
    async def test_removes_old_dockmon_backup_containers(self, jobs_manager):
        """
        Should remove containers with -dockmon-backup- suffix older than 24 hours

        This is the primary use case - DockMon creates backup containers during
        updates with pattern: {name}-dockmon-backup-{timestamp}
        """
        # Create old dockmon backup container (48 hours old)
        old_backup = create_mock_backup_container(
            'nginx-dockmon-backup-1732531200',
            created_hours_ago=48
        )

        mock_client = Mock()
        mock_client.containers.list = Mock(return_value=[old_backup])
        jobs_manager.monitor.clients = {'host1': mock_client}

        # Run cleanup
        removed_count = await jobs_manager.cleanup_old_backup_containers()

        # Verify: old dockmon backup removed
        assert removed_count == 1
        old_backup.remove.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_preserves_recent_dockmon_backup_containers(self, jobs_manager):
        """
        Should NOT remove dockmon backup containers younger than 24 hours

        Recent backups may still be needed for rollback if an update is
        in progress or just completed.
        """
        # Create recent dockmon backup container (12 hours old)
        recent_backup = create_mock_backup_container(
            'nginx-dockmon-backup-1732531200',
            created_hours_ago=12
        )

        mock_client = Mock()
        mock_client.containers.list = Mock(return_value=[recent_backup])
        jobs_manager.monitor.clients = {'host1': mock_client}

        # Run cleanup
        removed_count = await jobs_manager.cleanup_old_backup_containers()

        # Verify: recent backup preserved
        assert removed_count == 0
        recent_backup.remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_user_backup_containers(self, jobs_manager):
        """
        Should NOT remove containers with generic -backup- suffix (Issue #75)

        Users may have containers like 'server-backup-automator' or
        'db-backup-daily' that contain '-backup-' but are NOT DockMon backups.
        These must never be deleted.
        """
        # Create user's backup-related containers (old, but NOT dockmon backups)
        user_backup1 = create_mock_backup_container(
            'server-backup-automator',  # The exact case from Issue #75
            created_hours_ago=72
        )
        user_backup2 = create_mock_backup_container(
            'db-backup-daily',
            created_hours_ago=100
        )
        user_backup3 = create_mock_backup_container(
            'backup-manager',
            created_hours_ago=200
        )

        mock_client = Mock()
        mock_client.containers.list = Mock(return_value=[
            user_backup1, user_backup2, user_backup3
        ])
        jobs_manager.monitor.clients = {'host1': mock_client}

        # Run cleanup
        removed_count = await jobs_manager.cleanup_old_backup_containers()

        # Verify: NO user containers removed
        assert removed_count == 0
        user_backup1.remove.assert_not_called()
        user_backup2.remove.assert_not_called()
        user_backup3.remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_containers_only_removes_dockmon_backups(self, jobs_manager):
        """
        Combined test: With mixed container types, only old dockmon backups removed

        Scenario:
        - Old dockmon backup (should be removed)
        - Recent dockmon backup (should be preserved)
        - Old user backup container (should be preserved)
        - Regular container (should be preserved)
        """
        # Old dockmon backup - SHOULD be removed
        old_dockmon_backup = create_mock_backup_container(
            'nginx-dockmon-backup-1732400000',
            created_hours_ago=48
        )

        # Recent dockmon backup - should be preserved (too new)
        recent_dockmon_backup = create_mock_backup_container(
            'redis-dockmon-backup-1732500000',
            created_hours_ago=6
        )

        # User's backup container - should be preserved (not dockmon)
        user_backup = create_mock_backup_container(
            'server-backup-automator',
            created_hours_ago=100
        )

        # Regular container - should be preserved
        regular_container = create_mock_backup_container(
            'nginx',
            created_hours_ago=500
        )

        mock_client = Mock()
        mock_client.containers.list = Mock(return_value=[
            old_dockmon_backup,
            recent_dockmon_backup,
            user_backup,
            regular_container
        ])
        jobs_manager.monitor.clients = {'host1': mock_client}

        # Run cleanup
        removed_count = await jobs_manager.cleanup_old_backup_containers()

        # Verify: only old dockmon backup removed
        assert removed_count == 1
        old_dockmon_backup.remove.assert_called_once_with(force=True)
        recent_dockmon_backup.remove.assert_not_called()
        user_backup.remove.assert_not_called()
        regular_container.remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_across_multiple_hosts(self, jobs_manager):
        """
        Should clean up backup containers from all connected hosts
        """
        # Host 1: old dockmon backup
        backup_host1 = create_mock_backup_container(
            'app1-dockmon-backup-1732400000',
            created_hours_ago=48
        )
        mock_client1 = Mock()
        mock_client1.containers.list = Mock(return_value=[backup_host1])

        # Host 2: old dockmon backup
        backup_host2 = create_mock_backup_container(
            'app2-dockmon-backup-1732400000',
            created_hours_ago=72
        )
        mock_client2 = Mock()
        mock_client2.containers.list = Mock(return_value=[backup_host2])

        jobs_manager.monitor.clients = {
            'host1': mock_client1,
            'host2': mock_client2
        }

        # Run cleanup
        removed_count = await jobs_manager.cleanup_old_backup_containers()

        # Verify: both backups removed
        assert removed_count == 2
        backup_host1.remove.assert_called_once_with(force=True)
        backup_host2.remove.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_handles_container_without_created_timestamp(self, jobs_manager):
        """
        Should skip containers missing Created timestamp without crashing
        """
        # Container with missing Created attribute
        container_no_timestamp = Mock()
        container_no_timestamp.name = 'nginx-dockmon-backup-1732400000'
        container_no_timestamp.attrs = {}  # No Created field
        container_no_timestamp.remove = Mock()  # Sync method wrapped by async_docker_call

        mock_client = Mock()
        mock_client.containers.list = Mock(return_value=[container_no_timestamp])
        jobs_manager.monitor.clients = {'host1': mock_client}

        # Run cleanup - should not crash
        removed_count = await jobs_manager.cleanup_old_backup_containers()

        # Verify: container skipped (not removed)
        assert removed_count == 0
        container_no_timestamp.remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_monitor(self, jobs_manager):
        """
        Should return 0 when monitor is not available
        """
        jobs_manager.monitor = None

        removed_count = await jobs_manager.cleanup_old_backup_containers()

        assert removed_count == 0

    @pytest.mark.asyncio
    async def test_boundary_24_hour_threshold(self, jobs_manager):
        """
        Test exact 24-hour boundary behavior

        Implementation uses `created_dt < cutoff_time` where cutoff is 24 hours ago.
        - Containers older than 24 hours: removed
        - Containers younger than 24 hours: preserved
        """
        # Container just under 24 hours - should be preserved
        under_threshold = create_mock_backup_container(
            'app1-dockmon-backup-1732400000',
            created_hours_ago=23
        )

        # Container over 24 hours - should be removed
        over_threshold = create_mock_backup_container(
            'app2-dockmon-backup-1732300000',
            created_hours_ago=25
        )

        mock_client = Mock()
        mock_client.containers.list = Mock(return_value=[under_threshold, over_threshold])
        jobs_manager.monitor.clients = {'host1': mock_client}

        # Run cleanup
        removed_count = await jobs_manager.cleanup_old_backup_containers()

        # Verify: only over-threshold removed
        assert removed_count == 1
        under_threshold.remove.assert_not_called()
        over_threshold.remove.assert_called_once_with(force=True)
