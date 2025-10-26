"""
Unit tests for HostConnector abstraction layer (TDD RED Phase)

Tests the abstraction layer that allows deployment system to work with:
- v2.1: DirectDockerConnector (local socket or TCP+TLS)
- v2.2: AgentRPCConnector (agent-based remote hosts)

These tests will FAIL until HostConnector is implemented (expected in TDD).
"""

import pytest
import sys
from pathlib import Path
import importlib.util

# Load host_connector module directly without importing deployment package
# This avoids the deployment/__init__.py imports that trigger audit logger
backend_path = Path(__file__).parent.parent.parent
host_connector_path = backend_path / "deployment" / "host_connector.py"

spec = importlib.util.spec_from_file_location("host_connector", host_connector_path)
host_connector_module = importlib.util.module_from_spec(spec)
sys.modules["host_connector"] = host_connector_module
spec.loader.exec_module(host_connector_module)

# Import from loaded module
HostConnector = host_connector_module.HostConnector
DirectDockerConnector = host_connector_module.DirectDockerConnector
get_host_connector = host_connector_module.get_host_connector


class TestHostConnectorInterface:
    """Test that HostConnector is a proper abstract base class"""

    def test_host_connector_is_abstract(self):
        """HostConnector cannot be instantiated directly"""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            HostConnector("host123")

    def test_host_connector_has_required_methods(self):
        """HostConnector interface defines all required methods"""
        # Check that abstract methods are defined
        required_methods = [
            'ping',
            'create_container',
            'start_container',
            'stop_container',
            'remove_container',
            'get_container_status',
            'get_container_logs',
            'pull_image',
            'list_networks',
            'create_network',
            'list_volumes',
            'create_volume',
            'validate_port_availability',
            'verify_container_running',
        ]

        for method_name in required_methods:
            assert hasattr(HostConnector, method_name), \
                f"HostConnector missing required method: {method_name}"


class TestDirectDockerConnector:
    """Test DirectDockerConnector implementation"""

    def test_direct_connector_implements_interface(self):
        """DirectDockerConnector implements all HostConnector methods"""
        connector = DirectDockerConnector("test-host-id")

        # Verify all methods exist and are callable
        required_methods = [
            'ping',
            'create_container',
            'start_container',
            'stop_container',
            'remove_container',
            'get_container_status',
            'get_container_logs',
            'pull_image',
            'list_networks',
            'create_network',
            'list_volumes',
            'create_volume',
            'validate_port_availability',
            'verify_container_running',
        ]

        for method_name in required_methods:
            assert hasattr(connector, method_name), \
                f"DirectDockerConnector missing method: {method_name}"
            assert callable(getattr(connector, method_name)), \
                f"DirectDockerConnector.{method_name} is not callable"

    def test_direct_connector_stores_host_id(self):
        """DirectDockerConnector stores host_id"""
        connector = DirectDockerConnector("my-host-123")
        assert connector.host_id == "my-host-123"

    @pytest.mark.asyncio
    async def test_ping_returns_boolean(self, mock_docker_client):
        """DirectDockerConnector.ping() returns True if Docker daemon reachable"""
        mock_client, mock_monitor = mock_docker_client
        connector = DirectDockerConnector("test-host", docker_monitor=mock_monitor)

        # Mock successful ping
        mock_client.ping.return_value = True

        result = await connector.ping()
        assert isinstance(result, bool)
        assert result is True

    @pytest.mark.asyncio
    async def test_create_container_returns_short_id(self, mock_docker_client):
        """DirectDockerConnector.create_container() returns SHORT ID (12 chars)"""
        mock_client, mock_monitor = mock_docker_client
        connector = DirectDockerConnector("test-host", docker_monitor=mock_monitor)

        # Mock container creation
        mock_container = type('obj', (object,), {
            'short_id': 'a1b2c3d4e5f6',  # 12 chars
            'id': 'a1b2c3d4e5f6' + '0' * 52  # 64 chars
        })()
        mock_client.containers.create.return_value = mock_container

        config = {"image": "nginx:alpine", "name": "test"}
        labels = {"deployed_by": "dockmon"}

        container_id = await connector.create_container(config, labels)

        # CRITICAL: Must return SHORT ID (12 chars)
        assert container_id == 'a1b2c3d4e5f6'
        assert len(container_id) == 12

    @pytest.mark.asyncio
    async def test_create_container_merges_labels(self, mock_docker_client):
        """DirectDockerConnector.create_container() merges provided labels into config"""
        mock_client, mock_monitor = mock_docker_client
        connector = DirectDockerConnector("test-host", docker_monitor=mock_monitor)

        mock_container = type('obj', (object,), {'short_id': 'abc123def456'})()
        mock_client.containers.create.return_value = mock_container

        config = {
            "image": "nginx:alpine",
            "name": "test",
            "labels": {"existing": "label"}
        }
        labels = {"deployment_id": "deploy-123"}

        await connector.create_container(config, labels)

        # Verify labels were merged
        call_args = mock_client.containers.create.call_args
        assert call_args is not None
        final_labels = call_args[1].get('labels', {})
        assert final_labels.get('existing') == 'label'
        assert final_labels.get('deployment_id') == 'deploy-123'

    @pytest.mark.asyncio
    async def test_start_container_calls_docker_api(self, mock_docker_client):
        """DirectDockerConnector.start_container() starts container by SHORT ID"""
        from unittest.mock import MagicMock

        mock_client, mock_monitor = mock_docker_client
        connector = DirectDockerConnector("test-host", docker_monitor=mock_monitor)

        mock_container = MagicMock()
        mock_container.start = MagicMock()
        mock_client.containers.get.return_value = mock_container

        await connector.start_container("abc123def456")

        mock_client.containers.get.assert_called_once_with("abc123def456")

    @pytest.mark.asyncio
    async def test_verify_container_running_checks_status(self, mock_docker_client):
        """DirectDockerConnector.verify_container_running() checks container state"""
        from unittest.mock import MagicMock

        mock_client, mock_monitor = mock_docker_client
        connector = DirectDockerConnector("test-host", docker_monitor=mock_monitor)

        # Mock running container
        mock_container = MagicMock()
        mock_container.status = 'running'
        mock_container.reload = MagicMock()
        mock_client.containers.get.return_value = mock_container

        is_running = await connector.verify_container_running("abc123def456")

        assert is_running is True

    @pytest.mark.asyncio
    async def test_validate_port_availability_checks_conflicts(self, mock_docker_client):
        """DirectDockerConnector.validate_port_availability() checks for port conflicts"""
        mock_client, mock_monitor = mock_docker_client
        connector = DirectDockerConnector("test-host", docker_monitor=mock_monitor)

        # Mock no containers using port 80
        mock_client.containers.list.return_value = []

        ports = {"80/tcp": 80}

        # Should not raise exception (port available)
        await connector.validate_port_availability(ports)


class TestHostConnectorFactory:
    """Test get_host_connector() factory function"""

    def test_factory_returns_direct_connector_for_v2_1(self, test_db):
        """get_host_connector() returns DirectDockerConnector for all hosts in v2.1"""
        # In v2.1, all hosts use DirectDockerConnector
        connector = get_host_connector("test-host-id")

        assert isinstance(connector, DirectDockerConnector)
        assert connector.host_id == "test-host-id"

    def test_factory_returns_new_instance_each_time(self):
        """get_host_connector() returns new instance each call (not singleton)"""
        connector1 = get_host_connector("test-host")
        connector2 = get_host_connector("test-host")

        # Different instances
        assert connector1 is not connector2

        # But same host_id
        assert connector1.host_id == connector2.host_id


@pytest.fixture
def mock_docker_client():
    """Mock Docker client and monitor for testing"""
    from unittest.mock import MagicMock

    # Create mock Docker client
    mock_client = MagicMock()
    mock_client.ping.return_value = True
    mock_client.containers.create.return_value = type('obj', (object,), {
        'short_id': 'abc123def456',
        'id': 'abc123def456' + '0' * 52
    })()
    mock_client.containers.list.return_value = []
    mock_client.containers.get.return_value = type('obj', (object,), {
        'start': MagicMock(),
        'stop': MagicMock(),
        'remove': MagicMock(),
        'reload': MagicMock(),
        'status': 'running',
        'logs': MagicMock(return_value=b'test logs'),
    })()

    # Create mock docker_monitor with clients dict
    mock_monitor = MagicMock()
    mock_monitor.clients = {'test-host': mock_client, 'test-host-id': mock_client}

    return mock_client, mock_monitor
