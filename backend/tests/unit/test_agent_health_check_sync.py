"""
Unit tests for Agent Health Check Sync functionality.

Tests the health check config sync to agents (health_check_sync.py).
Ensures health check configurations are properly pushed to connected agents.

Architecture (v2.2.0+):
- HTTP health checks can run from backend OR agent (check_from field)
- When check_from='agent', configs are pushed to agents via WebSocket
- Agents execute health checks locally and report results back
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from agent.connection_manager import agent_connection_manager
from agent.health_check_sync import (
    _build_config_payload,
    push_health_check_config_to_agent,
    remove_health_check_config_from_agent,
)
from database import ContainerHttpHealthCheck


class TestBuildConfigPayload:
    """Test _build_config_payload helper function"""

    def test_builds_complete_payload(self):
        """Should build payload with all config fields"""
        config = MagicMock(spec=ContainerHttpHealthCheck)
        config.enabled = True
        config.url = "http://localhost:8080/health"
        config.method = "GET"
        config.expected_status_codes = "200,201"
        config.timeout_seconds = 10
        config.check_interval_seconds = 30
        config.follow_redirects = True
        config.verify_ssl = False
        config.headers_json = '{"X-Custom": "value"}'
        config.auth_config_json = '{"type": "basic", "username": "user"}'

        payload = _build_config_payload(config, "abc123def456", "host-123")

        assert payload["container_id"] == "abc123def456"
        assert payload["host_id"] == "host-123"
        assert payload["enabled"] is True
        assert payload["url"] == "http://localhost:8080/health"
        assert payload["method"] == "GET"
        assert payload["expected_status_codes"] == "200,201"
        assert payload["timeout_seconds"] == 10
        assert payload["check_interval_seconds"] == 30
        assert payload["follow_redirects"] is True
        assert payload["verify_ssl"] is False
        assert payload["headers_json"] == '{"X-Custom": "value"}'
        assert payload["auth_config_json"] == '{"type": "basic", "username": "user"}'

    def test_builds_minimal_payload(self):
        """Should build payload with minimal config"""
        config = MagicMock(spec=ContainerHttpHealthCheck)
        config.enabled = False
        config.url = "http://example.com"
        config.method = "HEAD"
        config.expected_status_codes = "200"
        config.timeout_seconds = 5
        config.check_interval_seconds = 60
        config.follow_redirects = False
        config.verify_ssl = True
        config.headers_json = None
        config.auth_config_json = None

        payload = _build_config_payload(config, "def456abc123", "host-456")

        assert payload["container_id"] == "def456abc123"
        assert payload["host_id"] == "host-456"
        assert payload["enabled"] is False
        assert payload["headers_json"] is None
        assert payload["auth_config_json"] is None


AGENT_ID = "agent-1"


def _agent_config(**overrides):
    config = MagicMock(spec=ContainerHttpHealthCheck)
    config.check_from = 'agent'
    config.enabled = True
    config.url = "http://localhost:8080/health"
    config.method = "GET"
    config.expected_status_codes = "200"
    config.timeout_seconds = 10
    config.check_interval_seconds = 30
    config.follow_redirects = True
    config.verify_ssl = True
    config.headers_json = None
    config.auth_config_json = None
    for name, value in overrides.items():
        setattr(config, name, value)
    return config


@pytest.fixture
def agent_ws():
    """A websocket registered on the real connection manager, as a connected agent would be."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    agent_connection_manager.connections[AGENT_ID] = ws
    yield ws
    agent_connection_manager.connections.pop(AGENT_ID, None)


def _db_manager_returning(config):
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = config
    db_manager = MagicMock()
    db_manager.get_session.return_value.__enter__ = MagicMock(return_value=session)
    db_manager.get_session.return_value.__exit__ = MagicMock(return_value=False)
    return db_manager, session


class TestPushHealthCheckConfigToAgent:
    """Test push_health_check_config_to_agent function"""

    @pytest.mark.asyncio
    async def test_pushes_config_to_connected_agent(self, agent_ws):
        result = await push_health_check_config_to_agent(
            AGENT_ID, "host-123", "abc123def456", config=_agent_config()
        )

        assert result is True
        agent_ws.send_json.assert_called_once()
        message = agent_ws.send_json.call_args[0][0]
        assert message["type"] == "health_check_config"
        assert message["payload"]["container_id"] == "abc123def456"
        assert message["payload"]["host_id"] == "host-123"

    @pytest.mark.asyncio
    async def test_returns_false_when_host_has_no_agent(self):
        result = await push_health_check_config_to_agent(
            None, "host-123", "abc123def456", config=_agent_config()
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_agent_not_connected(self):
        result = await push_health_check_config_to_agent(
            "agent-offline", "host-123", "abc123def456", config=_agent_config()
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_backend_health_check(self, agent_ws):
        result = await push_health_check_config_to_agent(
            AGENT_ID, "host-123", "abc123def456", config=_agent_config(check_from='backend')
        )

        assert result is False
        agent_ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_queries_config_from_database_if_not_provided(self, agent_ws):
        db_manager, session = _db_manager_returning(_agent_config(url="http://test/health"))

        result = await push_health_check_config_to_agent(
            AGENT_ID, "host-123", "abc123def456", db_manager=db_manager
        )

        assert result is True
        session.query.assert_called()
        assert agent_ws.send_json.call_args[0][0]["payload"]["url"] == "http://test/health"

    @pytest.mark.asyncio
    async def test_returns_false_when_config_not_found_in_database(self, agent_ws):
        db_manager, _ = _db_manager_returning(None)

        result = await push_health_check_config_to_agent(
            AGENT_ID, "host-123", "abc123def456", db_manager=db_manager
        )

        assert result is False
        agent_ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_websocket_error_gracefully(self, agent_ws):
        agent_ws.send_json.side_effect = Exception("WebSocket error")

        result = await push_health_check_config_to_agent(
            AGENT_ID, "host-123", "abc123def456", config=_agent_config()
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_full_payload_reaches_agent(self, agent_ws):
        config = _agent_config(
            url="https://my-service.local:8443/api/health",
            expected_status_codes="200-299",
            check_interval_seconds=60,
            verify_ssl=False,
            headers_json='{"Authorization": "Bearer token123"}',
        )

        result = await push_health_check_config_to_agent(
            AGENT_ID, "7be442c9-24bc-4047-b33a-41bbf51ea2f9", "abc123def456", config=config
        )

        assert result is True
        payload = agent_ws.send_json.call_args[0][0]["payload"]
        assert payload["url"] == "https://my-service.local:8443/api/health"
        assert payload["verify_ssl"] is False
        assert payload["headers_json"] == '{"Authorization": "Bearer token123"}'
        assert payload["check_interval_seconds"] == 60


class TestRemoveHealthCheckConfigFromAgent:
    """Test remove_health_check_config_from_agent function"""

    @pytest.mark.asyncio
    async def test_sends_remove_message_to_agent(self, agent_ws):
        result = await remove_health_check_config_from_agent(AGENT_ID, "abc123def456")

        assert result is True
        message = agent_ws.send_json.call_args[0][0]
        assert message["type"] == "health_check_config_remove"
        assert message["payload"]["container_id"] == "abc123def456"

    @pytest.mark.asyncio
    async def test_returns_false_when_host_has_no_agent(self):
        assert await remove_health_check_config_from_agent(None, "abc123def456") is False

    @pytest.mark.asyncio
    async def test_returns_false_when_agent_not_connected(self):
        assert await remove_health_check_config_from_agent("agent-offline", "abc123def456") is False

    @pytest.mark.asyncio
    async def test_handles_websocket_error_gracefully(self, agent_ws):
        agent_ws.send_json.side_effect = Exception("Connection lost")

        assert await remove_health_check_config_from_agent(AGENT_ID, "abc123def456") is False
