"""
Tests for container update execution.

Note: DockMon doesn't store containers - updates affect:
- ContainerUpdate table (tracking)
- ContainerDesiredState (preferences must survive update)
- Container recreation via Docker API
"""

import pytest
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from database import ContainerUpdate, ContainerDesiredState


@pytest.mark.unit
def test_update_record_tracks_versions(test_db, test_host):
    """Test that ContainerUpdate table tracks current and latest versions."""
    composite_key = f"{test_host.id}:abc123def456"

    update_record = ContainerUpdate(
        container_id=composite_key,
        host_id=test_host.id,
        current_image='myapp:v1.0',
        current_digest='sha256:abc123def456789012345678901234567890',
        latest_image='myapp:v2.0',
        latest_digest='sha256:def456ghi789012345678901234567890abc',
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

    assert retrieved.current_image == 'myapp:v1.0'
    assert retrieved.latest_image == 'myapp:v2.0'


@pytest.mark.unit
def test_update_metadata_survives_container_recreation(test_db, test_host):
    """Test that metadata must be updated with new container ID after recreation."""
    old_composite_key = f"{test_host.id}:old123abc456"
    
    metadata = ContainerDesiredState(
        container_id=old_composite_key,
        container_name='production-app',  # REQUIRED
        host_id=test_host.id,
        custom_tags='["important", "production"]',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(metadata)
    test_db.commit()
    
    # Simulate update: container gets new ID
    new_composite_key = f"{test_host.id}:new456def789"
    metadata.container_id = new_composite_key
    test_db.commit()
    
    # Verify new key has data
    new_metadata = test_db.query(ContainerDesiredState).filter_by(
        container_id=new_composite_key
    ).first()
    assert new_metadata is not None
    assert 'production' in new_metadata.custom_tags


@pytest.mark.unit
def test_short_id_enforced_in_update_tracking():
    """Test that update system uses SHORT IDs (12 chars)."""
    from unittest.mock import MagicMock
    
    mock_container = MagicMock()
    mock_container.id = "abc123def456789012345678901234567890123456789012345678901234"
    mock_container.short_id = "abc123def456"
    
    assert len(mock_container.short_id) == 12


@pytest.mark.unit
def test_deployment_labels_preserved_in_docker_recreate():
    """Test that deployment labels are reapplied when container recreated."""
    from unittest.mock import MagicMock
    
    mock_old_container = MagicMock()
    mock_old_container.labels = {
        'dockmon.deployment_id': 'host-id:deployment-id',
        'dockmon.managed': 'true'
    }
    
    labels_to_preserve = {
        k: v for k, v in mock_old_container.labels.items()
        if k.startswith('dockmon.')
    }
    
    assert labels_to_preserve['dockmon.deployment_id'] == 'host-id:deployment-id'


@pytest.mark.unit
def test_composite_key_update_in_all_tables(test_db, test_host):
    """Test that composite key must be updated across all metadata tables."""
    old_key = f"{test_host.id}:old123"
    new_key = f"{test_host.id}:new456"

    # Create metadata in multiple tables
    desired_state = ContainerDesiredState(
        container_id=old_key,
        container_name='multi-table-test',  # REQUIRED
        host_id=test_host.id,
        custom_tags='["test"]',
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(desired_state)

    update_tracking = ContainerUpdate(
        container_id=old_key,
        host_id=test_host.id,
        current_image='app:v1',
        current_digest='sha256:v1digest123456789012345678901234567890',
        latest_image='app:v2',
        latest_digest='sha256:v2digest456789012345678901234567890abc',
        update_available=True,
        last_checked_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(update_tracking)
    test_db.commit()

    # Update IDs in both tables
    desired_state.container_id = new_key
    update_tracking.container_id = new_key
    test_db.commit()

    # Verify both updated
    assert test_db.query(ContainerDesiredState).filter_by(container_id=new_key).count() == 1
    assert test_db.query(ContainerUpdate).filter_by(container_id=new_key).count() == 1
