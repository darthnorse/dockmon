"""
Integration tests for DeploymentExecutor using HostConnector abstraction.

TDD Phase 2.2: Verify executor uses HostConnector instead of direct Docker SDK calls.
"""

import pytest
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Set environment variable to prevent audit logger from creating /app directories
os.environ['DOCKMON_DATA_DIR'] = '/tmp/dockmon_test_data'

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from deployment.executor import DeploymentExecutor
from deployment.host_connector import HostConnector


class MockHostConnector(HostConnector):
    """Mock connector for testing executor integration"""

    def __init__(self, host_id: str):
        super().__init__(host_id)
        # Track all method calls
        self.ping_called = False
        self.create_container_called = False
        self.create_container_args = None
        self.start_container_called = False
        self.start_container_id = None
        self.pull_image_called = False
        self.pull_image_name = None
        self.verify_running_called = False
        self.stop_container_called = False
        self.remove_container_called = False

        # Mock return values
        self.mock_container_id = "abc123def456"  # SHORT ID (12 chars)
        self.mock_ping_result = True
        self.mock_running_status = True

    async def ping(self) -> bool:
        self.ping_called = True
        return self.mock_ping_result

    async def create_container(self, config: dict, labels: dict) -> str:
        self.create_container_called = True
        self.create_container_args = {'config': config, 'labels': labels}
        return self.mock_container_id

    async def start_container(self, container_id: str) -> None:
        self.start_container_called = True
        self.start_container_id = container_id

    async def stop_container(self, container_id: str, timeout: int = 10) -> None:
        self.stop_container_called = True

    async def remove_container(self, container_id: str, force: bool = False, volumes: bool = False) -> None:
        self.remove_container_called = True

    async def get_container_status(self, container_id: str) -> dict:
        return {'State': {'Running': True, 'Status': 'running'}}

    async def get_container_logs(self, container_id: str, tail: int = 100, follow: bool = False) -> str:
        return "mock logs"

    async def pull_image(self, image: str, progress_callback=None) -> None:
        self.pull_image_called = True
        self.pull_image_name = image

    async def list_networks(self) -> list:
        return []

    async def create_network(self, name: str, driver: str = "bridge") -> str:
        return "network123"

    async def list_volumes(self) -> list:
        return []

    async def create_volume(self, name: str) -> str:
        return "volume123"

    async def validate_port_availability(self, ports: dict) -> None:
        pass

    async def verify_container_running(self, container_id: str, max_wait_seconds: int = 30) -> bool:
        self.verify_running_called = True
        return self.mock_running_status


@pytest.mark.asyncio
async def test_executor_uses_connector_not_docker_sdk(test_database_manager, test_host):
    """
    RED TEST: Executor should use HostConnector instead of Docker SDK directly.

    This test will FAIL initially because executor still uses:
    - self.docker_monitor.clients.get(host_id)
    - await async_docker_call(client.containers.create, ...)

    After refactoring to use get_host_connector(host_id), this test will PASS.
    """
    # Setup
    event_bus = MagicMock()
    docker_monitor = MagicMock()
    docker_monitor.clients = MagicMock()
    docker_monitor.manager = None

    executor = DeploymentExecutor(event_bus, docker_monitor, test_database_manager)

    # Create mock connector
    mock_connector = MockHostConnector(test_host.id)

    # Patch get_host_connector to return our mock
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        # Create deployment
        deployment_id = await executor.create_deployment(
            host_id=test_host.id,
            name="test-nginx",
            deployment_type="container",
            definition={
                "image": "nginx:alpine",
                "ports": {"80/tcp": 8080},
                "environment": {"ENV": "test"}
            },
            rollback_on_failure=True
        )

        # Execute deployment
        await executor.execute_deployment(deployment_id)

    # Verify HostConnector was used (NOT Docker SDK)
    assert mock_connector.pull_image_called, "Executor should use connector.pull_image()"
    assert mock_connector.pull_image_name == "nginx:alpine"

    assert mock_connector.create_container_called, "Executor should use connector.create_container()"
    assert mock_connector.create_container_args is not None
    assert "nginx:alpine" in str(mock_connector.create_container_args['config'].get('image', ''))

    assert mock_connector.start_container_called, "Executor should use connector.start_container()"
    assert mock_connector.start_container_id == mock_connector.mock_container_id

    assert mock_connector.verify_running_called, "Executor should verify container is running via connector"


@pytest.mark.asyncio
async def test_executor_rollback_uses_connector(test_database_manager, test_host):
    """
    RED TEST: Rollback should also use HostConnector.

    When deployment fails, rollback logic should use connector methods
    instead of direct Docker SDK calls.
    """
    # Setup
    event_bus = MagicMock()
    docker_monitor = MagicMock()
    docker_monitor.clients = MagicMock()
    docker_monitor.manager = None

    executor = DeploymentExecutor(event_bus, docker_monitor, test_database_manager)

    # Create mock connector that fails to start container
    mock_connector = MockHostConnector(test_host.id)

    # Make start_container fail to trigger rollback
    async def failing_start(container_id: str):
        mock_connector.start_container_called = True
        raise Exception("Failed to start container")

    mock_connector.start_container = failing_start

    # Patch get_host_connector
    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        deployment_id = await executor.create_deployment(
            host_id=test_host.id,
            name="test-failing",
            deployment_type="container",
            definition={"image": "nginx:alpine"},
            rollback_on_failure=True
        )

        # Execute should fail and trigger rollback
        try:
            await executor.execute_deployment(deployment_id)
        except Exception:
            pass  # Expected to fail

    # Verify rollback used connector methods
    assert mock_connector.stop_container_called, "Rollback should use connector.stop_container()"
    assert mock_connector.remove_container_called, "Rollback should use connector.remove_container()"


def test_executor_no_direct_docker_sdk_imports():
    """
    RED TEST: Executor should NOT import Docker SDK directly.

    After refactoring, executor should only import:
    - from deployment.host_connector import get_host_connector

    NOT:
    - from utils.async_docker import async_docker_call (used with client.containers)
    """
    import deployment.executor as executor_module
    import inspect

    source = inspect.getsource(executor_module)

    # These patterns should NOT appear in refactored code
    forbidden_patterns = [
        "self.docker_monitor.clients.get(",  # Direct client access
        "client.containers.create",          # Direct Docker SDK call
        "client.containers.get",             # Direct Docker SDK call
    ]

    for pattern in forbidden_patterns:
        assert pattern not in source, f"Executor should not use '{pattern}' - use HostConnector instead"

    # This pattern SHOULD appear
    assert "get_host_connector" in source, "Executor should use get_host_connector()"


@pytest.mark.asyncio
async def test_executor_connector_receives_correct_labels(test_database_manager, test_host):
    """
    RED TEST: Verify connector receives deployment tracking labels.

    Labels must include:
    - dockmon.deployed_by=deployment
    - dockmon.deployment_id={deployment_id}
    - User-provided labels merged correctly
    """
    event_bus = MagicMock()
    docker_monitor = MagicMock()
    docker_monitor.clients = MagicMock()
    docker_monitor.manager = None

    executor = DeploymentExecutor(event_bus, docker_monitor, test_database_manager)
    mock_connector = MockHostConnector(test_host.id)

    with patch('deployment.executor.get_host_connector', return_value=mock_connector):
        deployment_id = await executor.create_deployment(
            host_id=test_host.id,
            name="test-labels",
            deployment_type="container",
            definition={
                "image": "nginx:alpine",
                "labels": {
                    "com.example.custom": "value",
                    "version": "1.0"
                }
            }
        )

        await executor.execute_deployment(deployment_id)

    # Verify labels were passed to connector
    labels = mock_connector.create_container_args['labels']

    assert labels["dockmon.deployed_by"] == "deployment", "Should mark as deployed by deployment system"
    assert deployment_id in labels["dockmon.deployment_id"], "Should include deployment ID"
    assert labels["com.example.custom"] == "value", "Should preserve user-provided labels"
    assert labels["version"] == "1.0", "Should preserve all user labels"
