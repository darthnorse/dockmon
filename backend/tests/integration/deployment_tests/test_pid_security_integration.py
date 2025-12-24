"""
Integration tests for PID mode and security options.

Tests that pid and security_opt directives work end-to-end through
the deployment system and are actually applied to containers.
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


class TestPidModeIntegration:
    """Test PID mode is actually applied to containers"""

    def test_pid_host_applied_to_container(self, orchestrator, docker_client):
        """Test pid: host creates container with host PID namespace"""
        service_config = {
            'image': 'nginx:latest',
            'pid': 'host',
            'command': 'sleep 3600'
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-pid-host',
            service_config=service_config
        )

        container = docker_client.containers.create(
            name='test-pid-integration-1',
            **container_config
        )

        try:
            container.reload()
            pid_mode = container.attrs['HostConfig']['PidMode']

            # Verify host PID mode was applied
            assert pid_mode == 'host'

        finally:
            container.remove(force=True)

    def test_pid_container_reference_applied(self, orchestrator, docker_client):
        """Test pid: container:name mapping (creation will fail without target container, but config is correct)"""
        service_config = {
            'image': 'nginx:latest',
            'pid': 'container:some-other-container',
            'command': 'sleep 3600'
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-pid-container',
            service_config=service_config
        )

        # Verify config has correct pid_mode (don't actually create container since target doesn't exist)
        assert container_config.get('pid_mode') == 'container:some-other-container'


class TestSecurityOptIntegration:
    """Test security options are actually applied to containers"""

    def test_apparmor_unconfined_applied(self, orchestrator, docker_client):
        """Test security_opt: apparmor:unconfined is applied"""
        service_config = {
            'image': 'nginx:latest',
            'security_opt': ['apparmor:unconfined'],
            'command': 'sleep 3600'
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-sec-apparmor',
            service_config=service_config
        )

        container = docker_client.containers.create(
            name='test-security-integration-1',
            **container_config
        )

        try:
            container.reload()
            security_opt = container.attrs['HostConfig']['SecurityOpt']

            # Verify security option was applied
            assert security_opt is not None
            assert 'apparmor:unconfined' in security_opt or 'apparmor=unconfined' in security_opt

        finally:
            container.remove(force=True)

    def test_multiple_security_options_applied(self, orchestrator, docker_client):
        """Test multiple security_opt values are applied"""
        service_config = {
            'image': 'nginx:latest',
            'security_opt': [
                'apparmor:unconfined',
                'seccomp:unconfined'
            ],
            'command': 'sleep 3600'
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-sec-multiple',
            service_config=service_config
        )

        container = docker_client.containers.create(
            name='test-security-integration-2',
            **container_config
        )

        try:
            container.reload()
            security_opt = container.attrs['HostConfig']['SecurityOpt']

            # Verify both options were applied
            assert security_opt is not None
            assert len(security_opt) >= 2

            # Check for both options (Docker may modify format)
            sec_str = ' '.join(security_opt)
            assert 'apparmor' in sec_str
            assert 'seccomp' in sec_str or 'unconfined' in sec_str

        finally:
            container.remove(force=True)


class TestNetdataConfiguration:
    """Test complete netdata configuration (Issue #69 scenario)"""

    def test_netdata_monitoring_container_config(self, orchestrator, docker_client):
        """Test netdata-like container with all required settings"""
        service_config = {
            'image': 'nginx:latest',  # Using alpine for test speed
            'pid': 'host',
            'network_mode': 'host',
            'cap_add': ['SYS_PTRACE', 'SYS_ADMIN'],
            'security_opt': ['apparmor:unconfined'],
            'user': '0:0',
            'command': 'sleep 10'
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-netdata-config',
            service_config=service_config
        )

        container = docker_client.containers.create(
            name='test-netdata-integration',
            **container_config
        )

        try:
            container.reload()
            host_config = container.attrs['HostConfig']
            config = container.attrs['Config']

            # Verify all netdata-critical settings applied
            assert host_config['PidMode'] == 'host'
            assert host_config['NetworkMode'] == 'host'
            assert 'SYS_PTRACE' in host_config['CapAdd']
            assert 'SYS_ADMIN' in host_config['CapAdd']
            assert host_config['SecurityOpt'] is not None
            assert any('apparmor' in opt for opt in host_config['SecurityOpt'])
            assert config['User'] == '0:0'

        finally:
            container.remove(force=True)


class TestPidAndSecurityCombined:
    """Test pid and security_opt work together"""

    def test_pid_host_with_security_combined(self, orchestrator, docker_client):
        """Test pid: host and security_opt can be used together"""
        service_config = {
            'image': 'nginx:latest',
            'pid': 'host',
            'security_opt': ['apparmor:unconfined'],
            'command': 'sleep 10'
        }

        container_config = orchestrator.map_service_to_container_config(
            service_name='test-combined',
            service_config=service_config
        )

        container = docker_client.containers.create(
            name='test-pid-security-combined',
            **container_config
        )

        try:
            container.reload()
            host_config = container.attrs['HostConfig']

            # Both should be applied
            assert host_config['PidMode'] == 'host'
            assert host_config['SecurityOpt'] is not None

        finally:
            container.remove(force=True)
