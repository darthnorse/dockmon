"""
Integration tests for image cleanup periodic job

Tests verify:
- retention_count=0 keeps only images in use by containers
- retention_count=N keeps N tagged versions per repository
- Grace period is respected (recent images not deleted)
- Dangling images (<none>:<none>) are cleaned up
- Images in use by containers are never deleted
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from docker_monitor.periodic_jobs import PeriodicJobsManager


@pytest.fixture
def mock_settings():
    """Mock GlobalSettings with image pruning enabled"""
    settings = Mock()
    settings.prune_images_enabled = True
    settings.image_retention_count = 2  # Default
    settings.image_prune_grace_hours = 48  # Default
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


def create_mock_image(image_id, tags, created_hours_ago=100):
    """Helper to create mock Docker image"""
    image = Mock()
    image.id = image_id
    image.short_id = image_id[:12]
    image.tags = tags

    # Set created timestamp
    created_dt = datetime.now(timezone.utc) - timedelta(hours=created_hours_ago)
    image.attrs = {
        'Created': created_dt.isoformat().replace('+00:00', 'Z')
    }

    # Mock remove method
    image.remove = AsyncMock()

    return image


def create_mock_container(container_id, image_id):
    """Helper to create mock Docker container"""
    container = Mock()
    container.id = container_id
    container.short_id = container_id[:12]

    # Container's image reference
    mock_image = Mock()
    mock_image.id = image_id
    container.image = mock_image

    return container


@pytest.mark.asyncio
async def test_retention_count_0_keeps_only_in_use_images(jobs_manager, mock_settings):
    """
    Test retention_count=0: Only keep images actively used by containers

    Setup:
    - 3 nginx images: old (100h), current (75h), older (50h) - all past grace period
    - Container running current image
    - retention_count=0, grace_hours=48

    Expected:
    - Current image preserved (in use)
    - Old and older images deleted (not in use, past grace period)
    """
    mock_settings.image_retention_count = 0
    mock_settings.image_prune_grace_hours = 48

    # Create images (all past grace period of 48h)
    old_image = create_mock_image('aaa111', ['nginx:1.23'], created_hours_ago=100)
    current_image = create_mock_image('bbb222', ['nginx:1.24'], created_hours_ago=75)
    older_image = create_mock_image('ccc333', ['nginx:1.25'], created_hours_ago=50)

    # Container using current image
    container = create_mock_container('container1', 'bbb222')

    # Mock Docker client (containers.list and images.list are sync methods wrapped by async_docker_call)
    mock_client = Mock()
    mock_client.containers.list = Mock(return_value=[container])
    mock_client.images.list = Mock(return_value=[old_image, current_image, older_image])

    jobs_manager.monitor.clients = {'host1': mock_client}

    # Run cleanup
    removed_count = await jobs_manager.cleanup_old_images()

    # Verify: old and older images deleted, current preserved
    assert removed_count == 2
    old_image.remove.assert_called_once()
    current_image.remove.assert_not_called()  # In use - protected
    older_image.remove.assert_called_once()


@pytest.mark.asyncio
async def test_retention_count_0_respects_grace_period(jobs_manager, mock_settings):
    """
    Test retention_count=0: Respects grace period even when trying to delete all

    Setup:
    - 2 nginx images: old (100h), recent (24h - within grace period)
    - No containers using either
    - retention_count=0, grace_hours=48

    Expected:
    - Old image deleted (past grace period)
    - Recent image preserved (within grace period)
    """
    mock_settings.image_retention_count = 0
    mock_settings.image_prune_grace_hours = 48

    # Create images
    old_image = create_mock_image('aaa111', ['nginx:1.23'], created_hours_ago=100)
    recent_image = create_mock_image('bbb222', ['nginx:1.24'], created_hours_ago=24)

    # No containers
    mock_client = Mock()
    mock_client.containers.list = Mock(return_value=[])
    mock_client.images.list = Mock(return_value=[old_image, recent_image])

    jobs_manager.monitor.clients = {'host1': mock_client}

    # Run cleanup
    removed_count = await jobs_manager.cleanup_old_images()

    # Verify: only old image deleted
    assert removed_count == 1
    old_image.remove.assert_called_once()
    recent_image.remove.assert_not_called()  # Within grace period


@pytest.mark.asyncio
async def test_retention_count_2_keeps_two_versions(jobs_manager, mock_settings):
    """
    Test retention_count=2: Keeps 2 most recent tagged versions per repository

    Setup:
    - 5 nginx images (100h, 75h, 50h, 25h, 10h)
    - Container using newest (10h)
    - retention_count=2

    Expected:
    - Newest 2 kept: 10h (in use) + 25h
    - Older 3 deleted: 50h, 75h, 100h
    """
    mock_settings.image_retention_count = 2
    mock_settings.image_prune_grace_hours = 48

    # Create 5 images (sorted newest to oldest internally)
    img1 = create_mock_image('aaa111', ['nginx:1.21'], created_hours_ago=100)
    img2 = create_mock_image('bbb222', ['nginx:1.22'], created_hours_ago=75)
    img3 = create_mock_image('ccc333', ['nginx:1.23'], created_hours_ago=50)
    img4 = create_mock_image('ddd444', ['nginx:1.24'], created_hours_ago=25)
    img5 = create_mock_image('eee555', ['nginx:latest'], created_hours_ago=10)

    # Container using newest
    container = create_mock_container('container1', 'eee555')

    # Mock Docker client
    mock_client = Mock()
    mock_client.containers.list = Mock(return_value=[container])
    mock_client.images.list = Mock(return_value=[img1, img2, img3, img4, img5])

    jobs_manager.monitor.clients = {'host1': mock_client}

    # Run cleanup
    removed_count = await jobs_manager.cleanup_old_images()

    # Verify: Keep 2 newest (img5 in use, img4 kept), delete 3 oldest
    assert removed_count == 3
    img1.remove.assert_called_once()
    img2.remove.assert_called_once()
    img3.remove.assert_called_once()
    img4.remove.assert_not_called()  # Within retention count
    img5.remove.assert_not_called()  # In use


@pytest.mark.asyncio
async def test_dangling_images_always_cleaned(jobs_manager, mock_settings):
    """
    Test dangling images (<none>:<none>) are cleaned regardless of retention_count

    Setup:
    - 1 tagged nginx image
    - 1 dangling image (no tags) - old enough to clean
    - retention_count=2 (doesn't affect dangling images)

    Expected:
    - Dangling image deleted (no tags, past grace period)
    - Tagged image preserved
    """
    mock_settings.image_retention_count = 2
    mock_settings.image_prune_grace_hours = 48

    # Create images
    tagged_image = create_mock_image('aaa111', ['nginx:latest'], created_hours_ago=50)
    dangling_image = create_mock_image('bbb222', [], created_hours_ago=100)  # No tags

    # No containers
    mock_client = Mock()
    mock_client.containers.list = Mock(return_value=[])
    mock_client.images.list = Mock(return_value=[tagged_image, dangling_image])

    jobs_manager.monitor.clients = {'host1': mock_client}

    # Run cleanup
    removed_count = await jobs_manager.cleanup_old_images()

    # Verify: dangling deleted, tagged preserved
    assert removed_count == 1
    tagged_image.remove.assert_not_called()
    dangling_image.remove.assert_called_once()


@pytest.mark.asyncio
async def test_multiple_repositories_independent_retention(jobs_manager, mock_settings):
    """
    Test retention_count applies independently to each repository

    Setup:
    - 3 nginx images (100h, 75h, 50h)
    - 3 postgres images (100h, 75h, 50h)
    - retention_count=1

    Expected:
    - Keep 1 newest per repo: nginx:50h + postgres:50h
    - Delete 4 old versions total
    """
    mock_settings.image_retention_count = 1
    mock_settings.image_prune_grace_hours = 48

    # Create nginx images
    nginx1 = create_mock_image('aaa111', ['nginx:1.23'], created_hours_ago=100)
    nginx2 = create_mock_image('bbb222', ['nginx:1.24'], created_hours_ago=75)
    nginx3 = create_mock_image('ccc333', ['nginx:latest'], created_hours_ago=50)

    # Create postgres images
    pg1 = create_mock_image('ddd444', ['postgres:14'], created_hours_ago=100)
    pg2 = create_mock_image('eee555', ['postgres:15'], created_hours_ago=75)
    pg3 = create_mock_image('fff666', ['postgres:16'], created_hours_ago=50)

    # No containers
    mock_client = Mock()
    mock_client.containers.list = Mock(return_value=[])
    mock_client.images.list = Mock(return_value=[nginx1, nginx2, nginx3, pg1, pg2, pg3])

    jobs_manager.monitor.clients = {'host1': mock_client}

    # Run cleanup
    removed_count = await jobs_manager.cleanup_old_images()

    # Verify: 4 old images deleted (2 nginx + 2 postgres), 2 newest kept
    assert removed_count == 4
    nginx1.remove.assert_called_once()
    nginx2.remove.assert_called_once()
    nginx3.remove.assert_not_called()  # Newest nginx
    pg1.remove.assert_called_once()
    pg2.remove.assert_called_once()
    pg3.remove.assert_not_called()  # Newest postgres


@pytest.mark.asyncio
async def test_images_in_use_never_deleted(jobs_manager, mock_settings):
    """
    Test images in use by ANY container (running or stopped) are never deleted

    Setup:
    - 2 nginx images: old, new
    - Stopped container using old image
    - retention_count=0 (try to delete everything)

    Expected:
    - Old image preserved (in use by stopped container)
    - New image deleted (not in use, past grace period)
    """
    mock_settings.image_retention_count = 0
    mock_settings.image_prune_grace_hours = 48

    # Create images
    old_image = create_mock_image('aaa111', ['nginx:1.23'], created_hours_ago=100)
    new_image = create_mock_image('bbb222', ['nginx:1.24'], created_hours_ago=50)

    # Stopped container using OLD image
    container = create_mock_container('container1', 'aaa111')

    # Mock Docker client (containers.list with all=True includes stopped)
    mock_client = Mock()
    mock_client.containers.list = Mock(return_value=[container])
    mock_client.images.list = Mock(return_value=[old_image, new_image])

    jobs_manager.monitor.clients = {'host1': mock_client}

    # Run cleanup
    removed_count = await jobs_manager.cleanup_old_images()

    # Verify: old preserved (in use), new deleted
    assert removed_count == 1
    old_image.remove.assert_not_called()  # Protected - in use
    new_image.remove.assert_called_once()


@pytest.mark.asyncio
async def test_pruning_disabled_skips_cleanup(jobs_manager, mock_settings):
    """
    Test cleanup skipped when prune_images_enabled=False

    Setup:
    - prune_images_enabled=False
    - 5 old images available to clean

    Expected:
    - No images deleted
    - removed_count=0
    """
    mock_settings.prune_images_enabled = False

    # Create old images
    img1 = create_mock_image('aaa111', ['nginx:1.23'], created_hours_ago=100)
    img2 = create_mock_image('bbb222', ['nginx:1.24'], created_hours_ago=100)

    # Mock Docker client
    mock_client = Mock()
    mock_client.containers.list = Mock(return_value=[])
    mock_client.images.list = Mock(return_value=[img1, img2])

    jobs_manager.monitor.clients = {'host1': mock_client}

    # Run cleanup
    removed_count = await jobs_manager.cleanup_old_images()

    # Verify: nothing deleted
    assert removed_count == 0
    img1.remove.assert_not_called()
    img2.remove.assert_not_called()
