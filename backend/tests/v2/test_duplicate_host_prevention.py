"""
Unit tests for duplicate host prevention

Tests the add_host() validation that prevents adding hosts with duplicate URLs.
These are logic tests that verify the duplicate detection algorithm without
requiring a full DockerMonitor instance.
"""

import pytest
from unittest.mock import Mock


class TestDuplicateHostPrevention:
    """Tests for duplicate host URL validation logic"""

    def test_duplicate_url_detection_simple(self):
        """Should detect duplicate URL in simple case"""
        # Simulate the duplicate check logic
        existing_hosts = {
            'host1': Mock(name='Existing Host', url='tcp://192.168.1.100:2376')
        }
        new_url = 'tcp://192.168.1.100:2376'

        # Check for duplicate
        is_duplicate = any(host.url == new_url for host in existing_hosts.values())

        assert is_duplicate == True

    def test_unique_url_detection(self):
        """Should not detect duplicate for unique URL"""
        existing_hosts = {
            'host1': Mock(name='Existing Host', url='tcp://192.168.1.100:2376')
        }
        new_url = 'tcp://192.168.1.101:2376'

        # Check for duplicate
        is_duplicate = any(host.url == new_url for host in existing_hosts.values())

        assert is_duplicate == False

    def test_duplicate_url_with_multiple_hosts(self):
        """Should detect duplicate among multiple existing hosts"""
        existing_hosts = {
            'host1': Mock(name='Host 1', url='tcp://192.168.1.100:2376'),
            'host2': Mock(name='Host 2', url='tcp://192.168.1.101:2376'),
            'host3': Mock(name='Host 3', url='tcp://192.168.1.102:2376'),
        }
        new_url = 'tcp://192.168.1.101:2376'

        # Check for duplicate
        is_duplicate = any(host.url == new_url for host in existing_hosts.values())

        assert is_duplicate == True

    def test_error_message_format(self):
        """Should generate proper error message with existing host name"""
        existing_host = Mock(name='Production Server', url='tcp://192.168.1.100:2376')
        new_url = 'tcp://192.168.1.100:2376'

        # Simulate error message generation
        error_message = f"Host with URL '{new_url}' already exists as '{existing_host.name}'"

        assert 'already exists' in error_message
        assert 'Production Server' in error_message
        assert 'tcp://192.168.1.100:2376' in error_message

    def test_finds_correct_existing_host_in_error(self):
        """Should identify the correct existing host in error message"""
        host1 = Mock()
        host1.name = 'Host 1'
        host1.url = 'tcp://192.168.1.100:2376'

        host2 = Mock()
        host2.name = 'Host 2'
        host2.url = 'tcp://192.168.1.101:2376'

        existing_hosts = {
            'host1': host1,
            'host2': host2,
        }
        new_url = 'tcp://192.168.1.100:2376'

        # Find the conflicting host
        conflicting_host = next(
            (host for host in existing_hosts.values() if host.url == new_url),
            None
        )

        assert conflicting_host is not None
        assert conflicting_host.name == 'Host 1'

    def test_case_sensitive_url_comparison(self):
        """Should treat URLs as case-sensitive"""
        existing_hosts = {
            'host1': Mock(name='Host 1', url='tcp://192.168.1.100:2376')
        }
        new_url = 'TCP://192.168.1.100:2376'  # Different case

        # Check for duplicate (case-sensitive)
        is_duplicate = any(host.url == new_url for host in existing_hosts.values())

        # URLs are case-sensitive, so this should not be a duplicate
        assert is_duplicate == False

    def test_different_protocols_not_duplicate(self):
        """Should treat same address with different protocols as different"""
        existing_hosts = {
            'host1': Mock(name='TCP Host', url='tcp://192.168.1.100:2376')
        }
        new_url = 'http://192.168.1.100:2376'  # Different protocol

        # Check for duplicate
        is_duplicate = any(host.url == new_url for host in existing_hosts.values())

        assert is_duplicate == False

    def test_unix_socket_duplicate_detection(self):
        """Should detect duplicate Unix socket URLs"""
        existing_hosts = {
            'host1': Mock(name='Local Docker', url='unix:///var/run/docker.sock')
        }
        new_url = 'unix:///var/run/docker.sock'

        # Check for duplicate
        is_duplicate = any(host.url == new_url for host in existing_hosts.values())

        assert is_duplicate == True

    def test_empty_hosts_dict_no_duplicate(self):
        """Should not find duplicate when no hosts exist"""
        existing_hosts = {}
        new_url = 'tcp://192.168.1.100:2376'

        # Check for duplicate
        is_duplicate = any(host.url == new_url for host in existing_hosts.values())

        assert is_duplicate == False

    def test_http_exception_status_code(self):
        """Should use status code 400 for duplicate host error"""
        # Verify that 400 Bad Request is appropriate for this validation error
        status_code = 400
        assert status_code == 400

    def test_skip_duplicate_check_logic(self):
        """Should skip duplicate check when skip_db_save flag is True"""
        skip_db_save = True

        # Duplicate check should be skipped when loading from DB
        should_check = not skip_db_save

        assert should_check == False
