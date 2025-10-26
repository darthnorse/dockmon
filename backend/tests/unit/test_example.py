"""
Example test to verify test infrastructure is working.

This file can be deleted once real tests are added.
"""

import pytest


@pytest.mark.unit
def test_example_passes():
    """Verify pytest is working."""
    assert True


@pytest.mark.unit
def test_fixtures_available(test_db, test_host, mock_docker_client):
    """Verify that fixtures are available and working."""
    assert test_db is not None
    assert test_host is not None
    assert test_host.id == '7be442c9-24bc-4047-b33a-41bbf51ea2f9'
    assert mock_docker_client is not None


@pytest.mark.unit
def test_container_data_fixture(test_container_data):
    """Verify container data fixture creates correct data."""
    assert test_container_data['short_id'] == 'abc123def456'  # SHORT ID
    assert len(test_container_data['short_id']) == 12
    assert test_container_data['name'] == 'test-nginx'
    assert test_container_data['state'] == 'running'


@pytest.mark.unit
def test_container_desired_state_fixture(test_db, test_container_desired_state):
    """Verify ContainerDesiredState fixture works."""
    # This is what DockMon actually stores - user preferences
    assert test_container_desired_state.container_id == '7be442c9-24bc-4047-b33a-41bbf51ea2f9:abc123def456'
    assert ':' in test_container_desired_state.container_id  # Composite key
    
    # Verify can be retrieved from database
    from database import ContainerDesiredState
    retrieved = test_db.query(ContainerDesiredState).filter_by(
        container_id=test_container_desired_state.container_id
    ).first()
    assert retrieved is not None
    assert retrieved.host_id == test_container_desired_state.host_id
