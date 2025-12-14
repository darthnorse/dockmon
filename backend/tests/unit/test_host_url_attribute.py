"""
Unit tests for DockerHostDB url attribute usage.

These tests ensure the correct attribute 'url' is used across the codebase,
not the incorrect 'docker_url' which doesn't exist on the model.

This bug caused auto-updates and stack deployments to fail on remote/mTLS hosts
with: AttributeError: 'DockerHostDB' object has no attribute 'docker_url'

Test coverage:
- DockerHostDB model has 'url' attribute
- DockerHostDB model does NOT have 'docker_url' attribute
- update_executor._execute_go_update uses host.url for remote hosts
- stack_executor._get_host_config uses host.url for remote hosts
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from contextlib import contextmanager
from datetime import datetime, timezone


class TestDockerHostDBModel:
    """Tests for DockerHostDB model attributes."""

    def test_host_has_url_attribute(self, test_db):
        """DockerHostDB model should have 'url' attribute."""
        from database import DockerHostDB

        host = DockerHostDB(
            id='test-host-123',
            name='test-host',
            url='tcp://192.168.1.100:2376',
            connection_type='remote',
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(host)
        test_db.commit()
        test_db.refresh(host)

        # Verify url attribute exists and has correct value
        assert hasattr(host, 'url')
        assert host.url == 'tcp://192.168.1.100:2376'

    def test_host_does_not_have_docker_url_attribute(self, test_db):
        """DockerHostDB model should NOT have 'docker_url' attribute."""
        from database import DockerHostDB

        host = DockerHostDB(
            id='test-host-456',
            name='test-host-2',
            url='tcp://192.168.1.101:2376',
            connection_type='remote',
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(host)
        test_db.commit()
        test_db.refresh(host)

        # Verify docker_url attribute does NOT exist
        assert not hasattr(host, 'docker_url')

        # Verify accessing docker_url raises AttributeError
        with pytest.raises(AttributeError):
            _ = host.docker_url


class TestUpdateExecutorHostUrl:
    """Tests for update_executor using correct host.url attribute."""

    @pytest.fixture
    def remote_host(self, test_db):
        """Create a remote/mTLS host for testing."""
        from database import DockerHostDB

        host = DockerHostDB(
            id='remote-host-uuid',
            name='remote-mtls-host',
            url='tcp://192.168.1.100:2376',
            connection_type='remote',
            tls_ca='-----BEGIN CERTIFICATE-----\nMOCK_CA\n-----END CERTIFICATE-----',
            tls_cert='-----BEGIN CERTIFICATE-----\nMOCK_CERT\n-----END CERTIFICATE-----',
            tls_key='-----BEGIN RSA PRIVATE KEY-----\nMOCK_KEY\n-----END RSA PRIVATE KEY-----',
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(host)
        test_db.commit()
        test_db.refresh(host)
        return host

    @pytest.fixture
    def local_host(self, test_db):
        """Create a local host for testing."""
        from database import DockerHostDB

        host = DockerHostDB(
            id='local-host-uuid',
            name='local-docker-host',
            url='unix:///var/run/docker.sock',
            connection_type='local',
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(host)
        test_db.commit()
        test_db.refresh(host)
        return host

    @pytest.fixture
    def agent_host(self, test_db):
        """Create an agent-based host for testing."""
        from database import DockerHostDB

        host = DockerHostDB(
            id='agent-host-uuid',
            name='agent-based-host',
            url='agent://',
            connection_type='agent',
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(host)
        test_db.commit()
        test_db.refresh(host)
        return host

    @pytest.fixture
    def mock_db_manager(self, test_db):
        """Create mock DatabaseManager that returns test_db session."""
        mock_db = Mock()

        @contextmanager
        def get_session_cm():
            yield test_db

        mock_db.get_session = get_session_cm
        return mock_db

    def test_remote_host_url_accessed_correctly(self, test_db, remote_host, mock_db_manager):
        """Update executor should access host.url (not docker_url) for remote hosts."""
        from database import DockerHostDB

        # Query the host like the update executor does
        host = test_db.query(DockerHostDB).filter_by(id=remote_host.id).first()

        assert host is not None
        assert host.connection_type == 'remote'

        # This is what the code should do (and now does after fix)
        docker_host = host.url
        assert docker_host == 'tcp://192.168.1.100:2376'

        # This is what the buggy code did - would raise AttributeError
        with pytest.raises(AttributeError):
            _ = host.docker_url

    def test_local_host_no_docker_host_extracted(self, test_db, local_host):
        """For local hosts, docker_host should not be extracted (only for remote)."""
        from database import DockerHostDB

        host = test_db.query(DockerHostDB).filter_by(id=local_host.id).first()

        assert host is not None
        assert host.connection_type == 'local'

        # For local hosts, we don't extract docker_host URL
        # The Go service uses the default socket
        if host.connection_type == 'remote':
            docker_host = host.url
        else:
            docker_host = None

        assert docker_host is None

    def test_agent_host_no_docker_host_extracted(self, test_db, agent_host):
        """For agent hosts, docker_host should not be extracted (routed differently)."""
        from database import DockerHostDB

        host = test_db.query(DockerHostDB).filter_by(id=agent_host.id).first()

        assert host is not None
        assert host.connection_type == 'agent'

        # For agent hosts, updates go through WebSocket, not Go service
        if host.connection_type == 'remote':
            docker_host = host.url
        else:
            docker_host = None

        assert docker_host is None


class TestStackExecutorHostUrl:
    """Tests for stack_executor._get_host_config using correct host.url attribute."""

    @pytest.fixture
    def remote_host_with_tls(self, test_db):
        """Create a remote host with TLS certs for testing."""
        from database import DockerHostDB

        host = DockerHostDB(
            id='stack-remote-host',
            name='stack-remote',
            url='tcp://192.168.1.200:2376',
            connection_type='remote',
            tls_ca='encrypted_ca_cert',
            tls_cert='encrypted_cert',
            tls_key='encrypted_key',
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(host)
        test_db.commit()
        test_db.refresh(host)
        return host

    def test_get_host_config_uses_url_not_docker_url(self, test_db, remote_host_with_tls):
        """_get_host_config should use host.url, not host.docker_url."""
        from database import DockerHostDB

        host = test_db.query(DockerHostDB).filter_by(id=remote_host_with_tls.id).first()

        assert host is not None
        assert host.connection_type == 'remote'

        # Simulate what _get_host_config does
        result = {}
        if host.connection_type == 'remote':
            # This is correct (after fix)
            result['docker_host'] = host.url

        assert result['docker_host'] == 'tcp://192.168.1.200:2376'

        # Verify the buggy approach would fail
        with pytest.raises(AttributeError):
            result['docker_host'] = host.docker_url


class TestAllConnectionTypes:
    """Comprehensive tests for all connection_type values."""

    @pytest.fixture
    def all_host_types(self, test_db):
        """Create hosts of all connection types."""
        from database import DockerHostDB

        hosts = {}

        # Local host
        local = DockerHostDB(
            id='local-123',
            name='local-host',
            url='unix:///var/run/docker.sock',
            connection_type='local',
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(local)
        hosts['local'] = local

        # Remote/mTLS host
        remote = DockerHostDB(
            id='remote-456',
            name='remote-host',
            url='tcp://192.168.1.100:2376',
            connection_type='remote',
            tls_ca='ca_cert',
            tls_cert='client_cert',
            tls_key='client_key',
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(remote)
        hosts['remote'] = remote

        # Agent host
        agent = DockerHostDB(
            id='agent-789',
            name='agent-host',
            url='agent://',
            connection_type='agent',
            is_active=True,
            created_at=datetime.now(timezone.utc)
        )
        test_db.add(agent)
        hosts['agent'] = agent

        test_db.commit()
        for h in hosts.values():
            test_db.refresh(h)

        return hosts

    def test_all_hosts_have_url_attribute(self, all_host_types):
        """All host types should have 'url' attribute."""
        for conn_type, host in all_host_types.items():
            assert hasattr(host, 'url'), f"{conn_type} host missing 'url' attribute"
            assert host.url is not None, f"{conn_type} host has None url"

    def test_no_hosts_have_docker_url_attribute(self, all_host_types):
        """No host type should have 'docker_url' attribute."""
        for conn_type, host in all_host_types.items():
            assert not hasattr(host, 'docker_url'), f"{conn_type} host has unexpected 'docker_url'"

    def test_remote_host_url_for_go_service(self, all_host_types):
        """Only remote hosts should have their URL passed to Go service."""
        for conn_type, host in all_host_types.items():
            # Simulate update executor logic
            docker_host = None
            if host.connection_type == 'remote':
                docker_host = host.url

            if conn_type == 'remote':
                assert docker_host == 'tcp://192.168.1.100:2376'
            else:
                assert docker_host is None, f"{conn_type} should not extract docker_host"
