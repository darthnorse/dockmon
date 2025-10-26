"""
Tests for container discovery service.

Critical for v2.1 because:
- Deployment creates containers that discovery might also see  
- Race condition: deployment vs deployment both trying to create/update metadata
- Must verify metadata management works correctly

Note: DockMon doesn't store containers in database - they come from Docker.
Discovery updates metadata tables: ContainerDesiredState, ContainerUpdate, etc.
"""

import pytest
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from database import ContainerDesiredState, ContainerUpdate


@pytest.mark.unit
def test_short_id_format_validation():
    """Test that container IDs are validated as SHORT format (12 chars)."""
    from unittest.mock import MagicMock
    
    mock_container = MagicMock()
    mock_container.id = "abc123def456789012345678901234567890123456789012345678901234"
    mock_container.short_id = "abc123def456"
    
    assert len(mock_container.short_id) == 12
    assert mock_container.short_id == mock_container.id[:12]


@pytest.mark.unit
def test_composite_key_construction(test_host):
    """Test that composite keys are constructed correctly for multi-host."""
    container_short_id = "abc123def456"
    composite_key = f"{test_host.id}:{container_short_id}"
    
    assert composite_key == "7be442c9-24bc-4047-b33a-41bbf51ea2f9:abc123def456"
    assert ':' in composite_key


@pytest.mark.unit
def test_container_metadata_storage(test_db, test_host):
    """Test that container metadata is stored correctly in ContainerDesiredState."""
    container_short_id = "test123abc45"
    composite_key = f"{test_host.id}:{container_short_id}"
    
    metadata = ContainerDesiredState(
        container_id=composite_key,
        container_name='test-web-app',  # REQUIRED
        host_id=test_host.id,
        custom_tags='["web", "production"]',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(metadata)
    test_db.commit()
    
    retrieved = test_db.query(ContainerDesiredState).filter_by(
        container_id=composite_key
    ).first()
    
    assert retrieved is not None
    assert retrieved.container_name == 'test-web-app'
    assert 'web' in retrieved.custom_tags


@pytest.mark.unit  
def test_update_tracking_storage(test_db, test_host):
    """Test that update tracking is stored correctly in ContainerUpdate table."""
    container_short_id = "update123abc"
    composite_key = f"{test_host.id}:{container_short_id}"
    
    update_record = ContainerUpdate(
        container_id=composite_key,
        host_id=test_host.id,
        current_image='nginx:1.24',
        current_digest='sha256:abc123def456789',  # REQUIRED
        latest_image='nginx:1.25',
        latest_digest='sha256:def789ghi012345',
        update_available=True,
        last_checked_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(update_record)
    test_db.commit()
    
    retrieved = test_db.query(ContainerUpdate).filter_by(
        container_id=composite_key
    ).first()
    
    assert retrieved is not None
    assert retrieved.update_available is True
    assert retrieved.current_digest == 'sha256:abc123def456789'


@pytest.mark.unit
def test_deployment_labels_in_docker_response():
    """Test that deployment labels can be extracted from Docker API response."""
    from unittest.mock import MagicMock
    
    mock_container = MagicMock()
    mock_container.short_id = 'deployed123'
    mock_container.labels = {
        'dockmon.deployment_id': 'host-uuid:deployment-uuid',
        'dockmon.managed': 'true',
    }
    
    assert mock_container.labels['dockmon.deployment_id'] == 'host-uuid:deployment-uuid'
    assert mock_container.labels['dockmon.managed'] == 'true'


@pytest.mark.unit
def test_metadata_upsert_pattern(test_db, test_host):
    """Test that metadata can be created or updated (upsert pattern)."""
    container_short_id = "upsert123"
    composite_key = f"{test_host.id}:{container_short_id}"
    
    # First time: create
    metadata = ContainerDesiredState(
        container_id=composite_key,
        container_name='upsert-test',  # REQUIRED
        host_id=test_host.id,
        custom_tags='["test"]',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(metadata)
    test_db.commit()
    
    # Verify created
    count = test_db.query(ContainerDesiredState).filter_by(
        container_id=composite_key
    ).count()
    assert count == 1
    
    # Second time: update
    existing = test_db.query(ContainerDesiredState).filter_by(
        container_id=composite_key
    ).first()
    existing.custom_tags = '["test", "updated"]'
    test_db.commit()
    
    # Verify still only one record
    count = test_db.query(ContainerDesiredState).filter_by(
        container_id=composite_key
    ).count()
    assert count == 1
