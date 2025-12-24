"""
Unit tests for healthcheck mapping in stack orchestrator.

Tests the conversion of Docker Compose healthcheck directives to
Docker SDK healthcheck configuration.
"""

import pytest
from deployment.stack_orchestrator import StackOrchestrator


class TestBasicHealthcheckMapping:
    """Test basic healthcheck directive mapping"""

    def test_healthcheck_with_all_fields(self):
        """Test healthcheck with all fields specified"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': ['CMD', 'curl', '-f', 'http://localhost:80'],
                'interval': '30s',
                'timeout': '10s',
                'retries': 3,
                'start_period': '40s'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        hc = config.get('healthcheck')
        assert hc is not None
        assert hc['test'] == ['CMD', 'curl', '-f', 'http://localhost:80']
        assert hc['interval'] == 30_000_000_000  # 30s in nanoseconds
        assert hc['timeout'] == 10_000_000_000   # 10s in nanoseconds
        assert hc['retries'] == 3
        assert hc['start_period'] == 40_000_000_000  # 40s in nanoseconds

    def test_healthcheck_minimal(self):
        """Test healthcheck with only test command"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': ['CMD', 'true']
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        hc = config.get('healthcheck')
        assert hc is not None
        assert hc['test'] == ['CMD', 'true']
        assert 'interval' not in hc
        assert 'timeout' not in hc
        assert 'retries' not in hc

    def test_healthcheck_string_test_command(self):
        """Test healthcheck with string test command (not array)"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': 'curl -f http://localhost',
                'interval': '10s'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        hc = config.get('healthcheck')
        assert hc is not None
        assert hc['test'] == 'curl -f http://localhost'
        assert hc['interval'] == 10_000_000_000

    def test_healthcheck_disable(self):
        """Test healthcheck with disable: true"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'disable': True
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        # disable: true should set healthcheck to None
        assert config.get('healthcheck') is None


class TestHealthcheckTimeParsing:
    """Test time duration parsing in healthcheck context"""

    def test_healthcheck_with_minute_interval(self):
        """Test healthcheck with minute-based interval"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': ['CMD', 'true'],
                'interval': '2m'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config['healthcheck']['interval'] == 120_000_000_000

    def test_healthcheck_with_compound_start_period(self):
        """Test healthcheck with compound duration (1m30s)"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': ['CMD', 'true'],
                'start_period': '1m30s'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config['healthcheck']['start_period'] == 90_000_000_000

    def test_healthcheck_with_millisecond_timeout(self):
        """Test healthcheck with millisecond timeout"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': ['CMD', 'true'],
                'timeout': '500ms'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert config['healthcheck']['timeout'] == 500_000_000


class TestHealthcheckEdgeCases:
    """Test edge cases in healthcheck configuration"""

    def test_no_healthcheck_directive(self):
        """Test service without healthcheck"""
        service_config = {
            'image': 'nginx:latest'
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        assert 'healthcheck' not in config

    def test_empty_healthcheck_object(self):
        """Test empty healthcheck object"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {}
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        hc = config.get('healthcheck')
        # Empty healthcheck object is falsy, so elif hc_source fails, no healthcheck set
        assert hc is None or hc == {}

    def test_healthcheck_only_retries(self):
        """Test healthcheck with only retries (no test command)"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'retries': 5
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='app',
            service_config=service_config
        )

        hc = config.get('healthcheck')
        assert hc is not None
        assert hc['retries'] == 5
        assert 'test' not in hc


class TestRealWorldHealthchecks:
    """Test real-world healthcheck configurations"""

    def test_nginx_healthcheck(self):
        """Test typical nginx healthcheck"""
        service_config = {
            'image': 'nginx:latest',
            'healthcheck': {
                'test': ['CMD', 'curl', '-f', 'http://localhost:80'],
                'interval': '30s',
                'timeout': '3s',
                'retries': 3,
                'start_period': '10s'
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='nginx',
            service_config=service_config
        )

        hc = config['healthcheck']
        assert hc['test'] == ['CMD', 'curl', '-f', 'http://localhost:80']
        assert hc['interval'] == 30_000_000_000
        assert hc['timeout'] == 3_000_000_000
        assert hc['retries'] == 3
        assert hc['start_period'] == 10_000_000_000

    def test_database_healthcheck_long_start_period(self):
        """Test database healthcheck with long start period"""
        service_config = {
            'image': 'postgres:latest',
            'healthcheck': {
                'test': ['CMD-SHELL', 'pg_isready -U postgres'],
                'interval': '10s',
                'timeout': '5s',
                'retries': 5,
                'start_period': '60s'  # Database needs time to initialize
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='db',
            service_config=service_config
        )

        hc = config['healthcheck']
        assert hc['test'] == ['CMD-SHELL', 'pg_isready -U postgres']
        assert hc['start_period'] == 60_000_000_000  # 1 minute

    def test_api_healthcheck_with_shell_command(self):
        """Test API healthcheck with shell command string"""
        service_config = {
            'image': 'myapi:latest',
            'healthcheck': {
                'test': 'wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1',
                'interval': '15s',
                'timeout': '10s',
                'retries': 3
            }
        }

        orchestrator = StackOrchestrator()
        config = orchestrator.map_service_to_container_config(
            service_name='api',
            service_config=service_config
        )

        hc = config['healthcheck']
        assert isinstance(hc['test'], str)
        assert 'wget' in hc['test']
        assert hc['interval'] == 15_000_000_000
        assert hc['timeout'] == 10_000_000_000
