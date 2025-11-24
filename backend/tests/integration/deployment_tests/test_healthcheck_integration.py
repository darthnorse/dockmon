"""
Integration tests for healthcheck deployment and preservation.

Tests that Docker Compose healthcheck directives are correctly applied
during deployment and preserved during container updates.
"""

import pytest
import docker
from deployment.stack_orchestrator import StackOrchestrator


@pytest.fixture
def docker_client():
    """Get Docker client for integration tests"""
    return docker.from_env()


@pytest.fixture
def orchestrator():
    """Get stack orchestrator instance"""
    return StackOrchestrator()


class TestHealthcheckDeployment:
    """Test healthcheck is applied during deployment"""

    def test_deploy_with_healthcheck_creates_working_healthcheck(self, orchestrator, docker_client):
        """Test that deployed container has working healthcheck"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': ['CMD', 'true'],  # Always succeeds
                'interval': '5s',
                'timeout': '3s',
                'retries': 2,
                'start_period': '5s'
            }
        }

        # Map config
        container_config = orchestrator.map_service_to_container_config(
            service_name='test-hc-deploy',
            service_config=service_config
        )

        # Create container
        container = docker_client.containers.create(
            name='test-hc-integration-1',
            **container_config
        )

        try:
            # Verify healthcheck was applied
            container.reload()
            hc = container.attrs['Config']['Healthcheck']

            assert hc is not None
            assert hc['Test'] == ['CMD', 'true']
            assert hc['Interval'] == 5_000_000_000  # 5s
            assert hc['Timeout'] == 3_000_000_000   # 3s
            assert hc['Retries'] == 2
            assert hc['StartPeriod'] == 5_000_000_000  # 5s

        finally:
            container.remove(force=True)

    def test_deploy_with_complex_healthcheck_command(self, orchestrator, docker_client):
        """Test healthcheck with realistic curl command"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': ['CMD', 'curl', '-f', 'http://localhost:80'],
                'interval': '10s',
                'timeout': '5s',
                'retries': 3
            }
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-hc-curl',
            service_config=service_config
        )

        container = docker_client.containers.create(
            name='test-hc-integration-2',
            **container_config
        )

        try:
            container.reload()
            hc = container.attrs['Config']['Healthcheck']

            assert hc['Test'] == ['CMD', 'curl', '-f', 'http://localhost:80']
            assert hc['Interval'] == 10_000_000_000

        finally:
            container.remove(force=True)

    def test_deploy_with_string_healthcheck_command(self, orchestrator, docker_client):
        """Test healthcheck with string command (shell format)"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': 'wget --spider http://localhost || exit 1',
                'interval': '15s'
            }
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-hc-string',
            service_config=service_config
        )

        container = docker_client.containers.create(
            name='test-hc-integration-3',
            **container_config
        )

        try:
            container.reload()
            hc = container.attrs['Config']['Healthcheck']

            # String format - should be wrapped by Docker in CMD-SHELL
            assert isinstance(hc['Test'], (str, list))
            if isinstance(hc['Test'], list):
                # Docker wrapped it
                assert 'wget' in str(hc['Test'])

        finally:
            container.remove(force=True)


class TestHealthcheckWithResources:
    """Test healthcheck combined with resource limits"""

    def test_deploy_with_healthcheck_and_memory_limit(self, orchestrator, docker_client):
        """Test healthcheck + deploy.resources together"""
        service_config = {
            'image': 'nginx:latest',
            'deploy': {
                'resources': {
                    'limits': {
                        'memory': '128M',
                        'cpus': '0.5'
                    }
                }
            },
            'healthcheck': {
                'test': ['CMD', 'true'],
                'interval': '10s',
                'timeout': '5s'
            }
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-hc-resources',
            service_config=service_config
        )

        container = docker_client.containers.create(
            name='test-hc-integration-4',
            **container_config
        )

        try:
            container.reload()

            # Verify both healthcheck and resources applied
            hc = container.attrs['Config']['Healthcheck']
            assert hc is not None
            assert hc['Test'] == ['CMD', 'true']

            host_config = container.attrs['HostConfig']
            assert host_config['Memory'] == 134217728  # 128MB
            assert host_config['NanoCpus'] == 500000000  # 0.5 CPU

        finally:
            container.remove(force=True)


class TestHealthcheckDisable:
    """Test healthcheck disable functionality"""

    def test_deploy_with_healthcheck_disabled(self, orchestrator, docker_client):
        """Test healthcheck with disable: true"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'disable': True
            }
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-hc-disabled',
            service_config=service_config
        )

        # When healthcheck is None, Docker SDK ignores it (no healthcheck)
        assert container_config.get('healthcheck') is None


class TestHealthcheckRealWorld:
    """Test real-world healthcheck scenarios"""

    def test_database_healthcheck_with_long_start_period(self, orchestrator, docker_client):
        """Test database-style healthcheck with long initialization time"""
        service_config = {
            'image': 'nginx:latest',  # Using nginx for test simplicity
            'healthcheck': {
                'test': ['CMD-SHELL', 'test -f /tmp/ready || exit 1'],
                'interval': '10s',
                'timeout': '5s',
                'retries': 5,
                'start_period': '60s'  # Database needs time to initialize
            }
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-db-hc',
            service_config=service_config
        )

        container = docker_client.containers.create(
            name='test-hc-integration-5',
            **container_config
        )

        try:
            container.reload()
            hc = container.attrs['Config']['Healthcheck']

            assert hc['Test'] == ['CMD-SHELL', 'test -f /tmp/ready || exit 1']
            assert hc['Interval'] == 10_000_000_000
            assert hc['Retries'] == 5
            assert hc['StartPeriod'] == 60_000_000_000  # 1 minute

        finally:
            container.remove(force=True)
