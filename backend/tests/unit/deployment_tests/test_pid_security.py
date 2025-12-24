"""
Unit tests for PID mode and security options in stack orchestrator.

Tests that Docker Compose pid and security_opt directives are correctly
mapped to Docker SDK parameters.
"""

import pytest
from deployment.stack_orchestrator import StackOrchestrator


class TestPidMode:
    """Test pid directive mapping"""

    def test_pid_host(self):
        """Test pid: host"""
        service_config = {
            'image': 'netdata/netdata:latest',
            'pid': 'host'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='netdata',
            service_config=service_config
        )

        assert config.get('pid_mode') == 'host'

    def test_pid_container_reference(self):
        """Test pid: container:name"""
        service_config = {
            'image': 'app:latest',
            'pid': 'container:other-container'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('pid_mode') == 'container:other-container'

    def test_pid_service_reference(self):
        """Test pid: service:name"""
        service_config = {
            'image': 'app:latest',
            'pid': 'service:other-service'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('pid_mode') == 'service:other-service'

    def test_no_pid_directive(self):
        """Test service without pid directive"""
        service_config = {
            'image': 'nginx:latest'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'pid_mode' not in config


class TestSecurityOpt:
    """Test security_opt directive mapping"""

    def test_security_opt_apparmor_unconfined(self):
        """Test security_opt with apparmor:unconfined"""
        service_config = {
            'image': 'netdata/netdata:latest',
            'security_opt': ['apparmor:unconfined']
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='netdata',
            service_config=service_config
        )

        assert config.get('security_opt') == ['apparmor:unconfined']

    def test_security_opt_multiple_options(self):
        """Test security_opt with multiple security options"""
        service_config = {
            'image': 'app:latest',
            'security_opt': [
                'apparmor:unconfined',
                'seccomp:unconfined',
                'label:disable'
            ]
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        sec_opt = config.get('security_opt')
        assert len(sec_opt) == 3
        assert 'apparmor:unconfined' in sec_opt
        assert 'seccomp:unconfined' in sec_opt
        assert 'label:disable' in sec_opt

    def test_security_opt_selinux_label(self):
        """Test security_opt with SELinux label"""
        service_config = {
            'image': 'app:latest',
            'security_opt': ['label:type:svirt_apache_t']
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config.get('security_opt') == ['label:type:svirt_apache_t']

    def test_security_opt_empty_list(self):
        """Test security_opt with empty list"""
        service_config = {
            'image': 'nginx:latest',
            'security_opt': []
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Empty list should not add security_opt
        assert 'security_opt' not in config

    def test_security_opt_null(self):
        """Test security_opt with null value"""
        service_config = {
            'image': 'nginx:latest',
            'security_opt': None
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # Null should not add security_opt
        assert 'security_opt' not in config

    def test_no_security_opt_directive(self):
        """Test service without security_opt"""
        service_config = {
            'image': 'nginx:latest'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'security_opt' not in config


class TestNetdataRealWorld:
    """Test real-world netdata configuration (Issue #69)"""

    def test_netdata_complete_config(self):
        """Test complete netdata configuration from Issue #69"""
        service_config = {
            'image': 'netdata/netdata:stable',
            'pid': 'host',
            'network_mode': 'host',
            'restart': 'always',
            'cap_add': ['SYS_PTRACE', 'SYS_ADMIN'],
            'security_opt': ['apparmor:unconfined'],
            'user': '0:0',
            'volumes': [
                '/etc/netdata:/etc/netdata',
                '/var/lib/netdata:/var/lib/netdata'
            ]
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='netdata',
            service_config=service_config
        )

        # Verify all critical netdata settings mapped
        assert config.get('pid_mode') == 'host'
        assert config.get('network_mode') == 'host'
        assert config.get('restart_policy') == {'Name': 'always'}
        assert config.get('cap_add') == ['SYS_PTRACE', 'SYS_ADMIN']
        assert config.get('security_opt') == ['apparmor:unconfined']
        assert config.get('user') == '0:0'
        assert len(config.get('volumes', [])) == 2


class TestPidAndSecurityCombined:
    """Test pid and security_opt together"""

    def test_pid_host_with_security_opt(self):
        """Test pid: host combined with security_opt"""
        service_config = {
            'image': 'monitoring:latest',
            'pid': 'host',
            'security_opt': ['apparmor:unconfined', 'seccomp:unconfined']
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='monitor',
            service_config=service_config
        )

        assert config.get('pid_mode') == 'host'
        assert config.get('security_opt') == ['apparmor:unconfined', 'seccomp:unconfined']
