"""
Pytest configuration and fixtures for DockMon tests
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add backend to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import DatabaseManager, Base


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    db = DatabaseManager(db_path)
    yield db

    # Cleanup
    os.unlink(db_path)


@pytest.fixture
def mock_docker_client():
    """Create a mock Docker client"""
    client = MagicMock()
    client.ping.return_value = True
    client.info.return_value = {'ServerVersion': '20.10.0'}

    # Mock containers
    container = MagicMock()
    container.id = 'test_container_123'
    container.short_id = 'test_container'
    container.name = 'test_container'
    container.status = 'running'
    container.attrs = {
        'State': {'Status': 'running'},
        'Config': {'Image': 'test:latest'}
    }
    container.logs.return_value = b'test log line\n'

    client.containers.list.return_value = [container]
    client.containers.get.return_value = container

    return client


@pytest.fixture
def mock_docker_module(monkeypatch):
    """Mock the docker module"""
    mock = MagicMock()
    monkeypatch.setattr('docker.DockerClient', mock)
    return mock


@pytest.fixture
def test_host_config():
    """Create a test host configuration"""
    from models.docker_models import DockerHostConfig
    return DockerHostConfig(
        name="TestHost",
        url="tcp://localhost:2376",
        tls_cert=None,
        tls_key=None,
        tls_ca=None
    )


@pytest.fixture
def test_host_config_with_tls():
    """Create a test host configuration with TLS"""
    from models.docker_models import DockerHostConfig
    return DockerHostConfig(
        name="SecureHost",
        url="tcp://secure.example.com:2376",
        tls_cert="-----BEGIN CERTIFICATE-----\ntest_cert\n-----END CERTIFICATE-----",
        tls_key="-----BEGIN PRIVATE KEY-----\ntest_key\n-----END PRIVATE KEY-----",
        tls_ca="-----BEGIN CERTIFICATE-----\ntest_ca\n-----END CERTIFICATE-----"
    )


@pytest.fixture
def test_alert_rule():
    """Create a test alert rule"""
    from models.request_models import AlertRule
    return AlertRule(
        name="Test Alert",
        container_pattern="test_*",
        trigger_states=["exited", "dead"],
        trigger_events=["die", "oom"],
        cooldown_minutes=5,
        enabled=True
    )