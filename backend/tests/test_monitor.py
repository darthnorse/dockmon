"""
Unit tests for Docker monitor logic
Tests for issues like reconnection bugs and state management
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import uuid


class TestDockerMonitor:
    """Test Docker monitor functionality"""

    @patch('docker_monitor.monitor.docker')
    def test_add_host_new(self, mock_docker, temp_db):
        """Test adding a new Docker host"""
        from docker_monitor.monitor import DockerMonitor

        # Setup mock
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_docker.DockerClient.return_value = mock_client

        monitor = DockerMonitor(temp_db)

        from models.docker_models import DockerHostConfig
        config = DockerHostConfig(
            name="TestHost",
            url="tcp://localhost:2376"
        )

        host = monitor.add_host(config)
        assert host.name == "TestHost"
        assert host.id in monitor.hosts
        assert host.id in monitor.clients

    @patch('docker_monitor.monitor.docker')
    def test_add_host_with_existing_id_skip_db(self, mock_docker, temp_db):
        """Test reconnecting to existing host doesn't duplicate in DB (the bug we fixed)"""
        from docker_monitor.monitor import DockerMonitor

        # Setup mock
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_docker.DockerClient.return_value = mock_client

        monitor = DockerMonitor(temp_db)

        from models.docker_models import DockerHostConfig
        config = DockerHostConfig(
            name="TestHost",
            url="tcp://localhost:2376"
        )

        # First add
        host1 = monitor.add_host(config)
        host_id = host1.id

        # Simulate reconnection with skip_db_save=True
        host2 = monitor.add_host(config, existing_id=host_id, skip_db_save=True)

        # Should reuse same ID and not crash
        assert host2.id == host_id
        # Verify only one host in DB
        hosts = temp_db.get_hosts()
        assert len(hosts) == 1

    @patch('docker_monitor.monitor.docker')
    def test_remove_host(self, mock_docker, temp_db):
        """Test removing a Docker host"""
        from docker_monitor.monitor import DockerMonitor

        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_docker.DockerClient.return_value = mock_client

        monitor = DockerMonitor(temp_db)

        from models.docker_models import DockerHostConfig
        config = DockerHostConfig(
            name="TestHost",
            url="tcp://localhost:2376"
        )

        host = monitor.add_host(config)
        host_id = host.id

        # Remove host
        monitor.remove_host(host_id)

        # Verify it's removed
        assert host_id not in monitor.hosts
        assert host_id not in monitor.clients

    def test_auto_restart_toggle(self, temp_db):
        """Test auto-restart functionality"""
        from docker_monitor.monitor import DockerMonitor

        monitor = DockerMonitor(temp_db)

        host_id = str(uuid.uuid4())
        container_id = "test_container_123"
        container_name = "test_container"

        # Enable auto-restart
        monitor.toggle_auto_restart(host_id, container_id, container_name, True)
        assert monitor.auto_restart_status.get(container_id) is True

        # Disable auto-restart
        monitor.toggle_auto_restart(host_id, container_id, container_name, False)
        assert monitor.auto_restart_status.get(container_id) is False

    @patch('docker_monitor.monitor.docker')
    def test_get_all_containers(self, mock_docker, temp_db):
        """Test getting containers from all hosts"""
        from docker_monitor.monitor import DockerMonitor

        # Setup mock containers
        container1 = MagicMock()
        container1.id = 'container1'
        container1.short_id = 'cont1'
        container1.name = 'app1'
        container1.status = 'running'
        container1.attrs = {
            'State': {'Status': 'running'},
            'Config': {'Image': 'app:latest'}
        }

        container2 = MagicMock()
        container2.id = 'container2'
        container2.short_id = 'cont2'
        container2.name = 'app2'
        container2.status = 'exited'
        container2.attrs = {
            'State': {'Status': 'exited', 'ExitCode': 1},
            'Config': {'Image': 'app:latest'}
        }

        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.containers.list.return_value = [container1, container2]
        mock_docker.DockerClient.return_value = mock_client

        monitor = DockerMonitor(temp_db)

        from models.docker_models import DockerHostConfig
        config = DockerHostConfig(
            name="TestHost",
            url="tcp://localhost:2376"
        )
        host = monitor.add_host(config)

        containers = monitor.get_all_containers()
        assert len(containers) == 2
        assert containers[0]['name'] == 'app1'
        assert containers[0]['status'] == 'running'
        assert containers[1]['name'] == 'app2'
        assert containers[1]['status'] == 'exited'

    @patch('docker_monitor.monitor.docker')
    def test_connection_failure_handling(self, mock_docker, temp_db):
        """Test handling of Docker connection failures"""
        from docker_monitor.monitor import DockerMonitor

        # Setup mock to fail
        mock_docker.DockerClient.side_effect = Exception("Connection refused")

        monitor = DockerMonitor(temp_db)

        from models.docker_models import DockerHostConfig
        config = DockerHostConfig(
            name="TestHost",
            url="tcp://localhost:2376"
        )

        with pytest.raises(Exception) as exc_info:
            monitor.add_host(config)
        assert "Connection refused" in str(exc_info.value)

    def test_validate_host_security(self, temp_db):
        """Test host security validation"""
        from docker_monitor.monitor import DockerMonitor

        monitor = DockerMonitor(temp_db)

        from models.docker_models import DockerHostConfig

        # Insecure host
        insecure_config = DockerHostConfig(
            name="InsecureHost",
            url="tcp://192.168.1.100:2376"
        )
        status = monitor._validate_host_security(insecure_config)
        assert status == "insecure"

        # Secure host with TLS
        secure_config = DockerHostConfig(
            name="SecureHost",
            url="tcp://192.168.1.100:2376",
            tls_cert="cert",
            tls_key="key",
            tls_ca="ca"
        )
        status = monitor._validate_host_security(secure_config)
        assert status == "secure"

    @patch('docker_monitor.monitor.docker')
    def test_restart_container(self, mock_docker, temp_db):
        """Test container restart functionality"""
        from docker_monitor.monitor import DockerMonitor

        mock_container = MagicMock()
        mock_container.restart = MagicMock()

        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_client.containers.get.return_value = mock_container
        mock_docker.DockerClient.return_value = mock_client

        monitor = DockerMonitor(temp_db)

        from models.docker_models import DockerHostConfig
        config = DockerHostConfig(
            name="TestHost",
            url="tcp://localhost:2376"
        )
        host = monitor.add_host(config)

        # Restart container
        monitor.restart_container(host.id, "container123")

        # Verify restart was called
        mock_container.restart.assert_called_once()