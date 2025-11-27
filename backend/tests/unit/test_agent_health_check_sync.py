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
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

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


class TestPushHealthCheckConfigToAgent:
    """Test push_health_check_config_to_agent function"""

    @pytest.mark.asyncio
    async def test_pushes_config_to_connected_agent(self):
        """Should send health check config to connected agent"""
        # Setup mock agent
        mock_agent = MagicMock()
        mock_agent.websocket = MagicMock()
        mock_agent.websocket.send_json = AsyncMock()

        # Setup mock connection manager
        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=mock_agent)

            # Create config
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

            # Execute
            result = await push_health_check_config_to_agent(
                host_id="host-123",
                container_id="abc123def456",
                config=config
            )

            # Verify
            assert result is True
            mock_cm.get_agent_for_host.assert_called_once_with("host-123")
            mock_agent.websocket.send_json.assert_called_once()

            # Verify message format
            call_args = mock_agent.websocket.send_json.call_args[0][0]
            assert call_args["type"] == "health_check_config"
            assert "payload" in call_args
            assert call_args["payload"]["container_id"] == "abc123def456"
            assert call_args["payload"]["host_id"] == "host-123"

    @pytest.mark.asyncio
    async def test_returns_false_when_no_agent_connected(self):
        """Should return False if no agent for host"""
        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=None)

            result = await push_health_check_config_to_agent(
                host_id="host-123",
                container_id="abc123def456",
                config=MagicMock(check_from='agent')
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_backend_health_check(self):
        """Should return False if check_from is not 'agent'"""
        mock_agent = MagicMock()
        mock_agent.websocket = MagicMock()
        mock_agent.websocket.send_json = AsyncMock()

        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=mock_agent)

            config = MagicMock(spec=ContainerHttpHealthCheck)
            config.check_from = 'backend'  # Not agent-based

            result = await push_health_check_config_to_agent(
                host_id="host-123",
                container_id="abc123def456",
                config=config
            )

            assert result is False
            mock_agent.websocket.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_queries_config_from_database_if_not_provided(self):
        """Should query config from DB if not provided"""
        mock_agent = MagicMock()
        mock_agent.websocket = MagicMock()
        mock_agent.websocket.send_json = AsyncMock()

        # Setup mock config from DB
        mock_config = MagicMock(spec=ContainerHttpHealthCheck)
        mock_config.check_from = 'agent'
        mock_config.enabled = True
        mock_config.url = "http://test/health"
        mock_config.method = "GET"
        mock_config.expected_status_codes = "200"
        mock_config.timeout_seconds = 10
        mock_config.check_interval_seconds = 30
        mock_config.follow_redirects = True
        mock_config.verify_ssl = True
        mock_config.headers_json = None
        mock_config.auth_config_json = None

        # Setup mock session
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_config

        mock_db_manager = MagicMock()
        mock_db_manager.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db_manager.get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=mock_agent)

            result = await push_health_check_config_to_agent(
                host_id="host-123",
                container_id="abc123def456",
                config=None,
                db_manager=mock_db_manager
            )

            assert result is True
            # Verify DB was queried with composite key
            mock_session.query.assert_called()

    @pytest.mark.asyncio
    async def test_returns_false_when_config_not_found_in_database(self):
        """Should return False if config not in DB"""
        mock_agent = MagicMock()

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        mock_db_manager = MagicMock()
        mock_db_manager.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db_manager.get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=mock_agent)

            result = await push_health_check_config_to_agent(
                host_id="host-123",
                container_id="abc123def456",
                config=None,
                db_manager=mock_db_manager
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_handles_websocket_error_gracefully(self):
        """Should handle WebSocket errors and return False"""
        mock_agent = MagicMock()
        mock_agent.websocket = MagicMock()
        mock_agent.websocket.send_json = AsyncMock(side_effect=Exception("WebSocket error"))

        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=mock_agent)

            config = MagicMock(spec=ContainerHttpHealthCheck)
            config.check_from = 'agent'
            config.enabled = True
            config.url = "http://test"
            config.method = "GET"
            config.expected_status_codes = "200"
            config.timeout_seconds = 10
            config.check_interval_seconds = 30
            config.follow_redirects = True
            config.verify_ssl = True
            config.headers_json = None
            config.auth_config_json = None

            result = await push_health_check_config_to_agent(
                host_id="host-123",
                container_id="abc123def456",
                config=config
            )

            assert result is False


class TestRemoveHealthCheckConfigFromAgent:
    """Test remove_health_check_config_from_agent function"""

    @pytest.mark.asyncio
    async def test_sends_remove_message_to_agent(self):
        """Should send removal message to connected agent"""
        mock_agent = MagicMock()
        mock_agent.websocket = MagicMock()
        mock_agent.websocket.send_json = AsyncMock()

        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=mock_agent)

            result = await remove_health_check_config_from_agent(
                host_id="host-123",
                container_id="abc123def456"
            )

            assert result is True
            mock_agent.websocket.send_json.assert_called_once()

            # Verify message format
            call_args = mock_agent.websocket.send_json.call_args[0][0]
            assert call_args["type"] == "health_check_config_remove"
            assert call_args["payload"]["container_id"] == "abc123def456"

    @pytest.mark.asyncio
    async def test_returns_false_when_no_agent_connected(self):
        """Should return False if no agent for host"""
        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=None)

            result = await remove_health_check_config_from_agent(
                host_id="host-123",
                container_id="abc123def456"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_handles_websocket_error_gracefully(self):
        """Should handle errors and return False"""
        mock_agent = MagicMock()
        mock_agent.websocket = MagicMock()
        mock_agent.websocket.send_json = AsyncMock(side_effect=Exception("Connection lost"))

        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=mock_agent)

            result = await remove_health_check_config_from_agent(
                host_id="host-123",
                container_id="abc123def456"
            )

            assert result is False


class TestHealthCheckSyncIntegration:
    """Integration-style tests for health check sync flow"""

    @pytest.mark.asyncio
    async def test_full_config_push_flow(self):
        """Should handle complete config push flow"""
        mock_agent = MagicMock()
        mock_agent.websocket = MagicMock()
        mock_agent.websocket.send_json = AsyncMock()

        with patch('agent.health_check_sync.agent_connection_manager') as mock_cm:
            mock_cm.get_agent_for_host = AsyncMock(return_value=mock_agent)

            # Create realistic config
            config = MagicMock(spec=ContainerHttpHealthCheck)
            config.check_from = 'agent'
            config.enabled = True
            config.url = "https://my-service.local:8443/api/health"
            config.method = "GET"
            config.expected_status_codes = "200-299"
            config.timeout_seconds = 15
            config.check_interval_seconds = 60
            config.follow_redirects = False
            config.verify_ssl = False  # Self-signed cert
            config.headers_json = '{"Authorization": "Bearer token123"}'
            config.auth_config_json = None

            result = await push_health_check_config_to_agent(
                host_id="7be442c9-24bc-4047-b33a-41bbf51ea2f9",
                container_id="abc123def456",
                config=config
            )

            assert result is True

            # Verify complete payload
            call_args = mock_agent.websocket.send_json.call_args[0][0]
            payload = call_args["payload"]

            assert payload["url"] == "https://my-service.local:8443/api/health"
            assert payload["verify_ssl"] is False
            assert payload["headers_json"] == '{"Authorization": "Bearer token123"}'
            assert payload["check_interval_seconds"] == 60
