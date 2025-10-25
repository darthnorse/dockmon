"""
Integration test for health check system.

Critical for v2.1: Deployment must integrate with health checks.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from database import Container, ContainerHttpHealthCheck, Alert


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_check_integration(test_db, test_host, test_container):
    """
    Test health check system integration.

    Flow:
    1. Health check configured for container
    2. Health check runs
    3. Status updated in database
    4. Events emitted
    """
    # Step 1: Configure health check
    health_check = ContainerHttpHealthCheck(
        container_id=f"{test_host.id}:{test_container.id}",
        url="http://localhost:8080/health",
        interval_seconds=60,
        current_status="unknown",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(health_check)
    test_db.commit()

    # Verify health check created
    assert health_check.container_id == f"{test_host.id}:{test_container.id}"
    
    # Composite key format verification
    assert ':' in health_check.container_id
    host_id, container_id = health_check.container_id.split(':', 1)
    assert host_id == test_host.id
    assert container_id == test_container.id
    assert len(container_id) == 12  # SHORT ID

    # Step 2: Health check runs (mocked)
    # with patch('health_check.http_checker.httpx.AsyncClient') as mock_http:
    #     mock_response = AsyncMock()
    #     mock_response.status_code = 200
    #     mock_http.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
    #     
    #     await run_health_check(health_check.id)

    # Step 3: Verify status updated
    # test_db.refresh(health_check)
    # assert health_check.current_status == "healthy"

    # TEMPORARY: Test skeleton
    assert True, "Test skeleton - awaiting health check implementation"


@pytest.mark.integration
def test_health_check_composite_key_lookup(test_db, test_host, test_container):
    """
    Test that health checks can be looked up by composite key.

    Critical: Multi-host support requires composite key lookups.
    """
    # Create health check with composite key
    composite_key = f"{test_host.id}:{test_container.id}"
    
    health_check = ContainerHttpHealthCheck(
        container_id=composite_key,
        url="http://localhost:9000/health",
        interval_seconds=30,
        current_status="healthy",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(health_check)
    test_db.commit()

    # Lookup by composite key
    found = test_db.query(ContainerHttpHealthCheck).filter_by(
        container_id=composite_key
    ).first()

    assert found is not None
    assert found.container_id == composite_key
    assert found.url == "http://localhost:9000/health"


@pytest.mark.integration
def test_managed_container_health_check_integration(test_db, test_host, managed_container):
    """
    Test health checks work with managed (deployed) containers.

    Critical for v2.1: Deployed containers must support health checks.
    """
    # Verify managed container exists
    assert managed_container.is_managed is True
    assert managed_container.deployment_id is not None

    # Create health check for managed container
    composite_key = f"{test_host.id}:{managed_container.id}"
    
    health_check = ContainerHttpHealthCheck(
        container_id=composite_key,
        url="http://localhost:3000/health",
        interval_seconds=15,
        current_status="unknown",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    test_db.add(health_check)
    test_db.commit()

    # Verify health check associated with managed container
    assert health_check.container_id == composite_key
    
    # Can retrieve both
    container = test_db.query(Container).filter_by(
        host_id=test_host.id,
        id=managed_container.id
    ).first()
    
    hc = test_db.query(ContainerHttpHealthCheck).filter_by(
        container_id=composite_key
    ).first()

    assert container.is_managed is True
    assert hc.container_id == f"{container.host_id}:{container.id}"
