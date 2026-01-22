"""
Unit tests for ntfy notification channel.

Tests the _send_ntfy() method in NotificationService for sending
notifications to ntfy servers (self-hosted or ntfy.sh).

Uses JSON API for proper Unicode/emoji support (Issue #163).

Issue: #80, #163
"""

import pytest
from unittest.mock import AsyncMock, Mock
import httpx
from notifications import NotificationService


class TestNtfyNotifications:
    """Test ntfy notification sending logic"""

    @pytest.fixture
    def notification_service(self):
        """Create NotificationService instance with mocked dependencies"""
        mock_db = Mock()
        service = NotificationService(db=mock_db, event_logger=None)
        service.http_client = AsyncMock()
        yield service

    @pytest.mark.asyncio
    async def test_ntfy_basic_notification(self, notification_service):
        """Test basic notification to ntfy server"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'dockmon-alerts'
        }
        message = 'Container nginx stopped'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message)

        assert result is True
        notification_service.http_client.post.assert_called_once()
        call_args = notification_service.http_client.post.call_args

        # Verify URL is server root (topic goes in JSON payload)
        assert call_args[0][0] == 'https://ntfy.sh'

        # Verify JSON payload
        payload = call_args[1]['json']
        assert payload['topic'] == 'dockmon-alerts'
        assert payload['message'] == 'Container nginx stopped'

    @pytest.mark.asyncio
    async def test_ntfy_self_hosted_server(self, notification_service):
        """Test notification to self-hosted ntfy instance"""
        config = {
            'server_url': 'https://ntfy.example.com',
            'topic': 'alerts'
        }
        message = 'Test message'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message)

        assert result is True
        call_args = notification_service.http_client.post.call_args
        assert call_args[0][0] == 'https://ntfy.example.com'
        assert call_args[1]['json']['topic'] == 'alerts'

    @pytest.mark.asyncio
    async def test_ntfy_with_trailing_slash(self, notification_service):
        """Test server URL with trailing slash is handled correctly"""
        config = {
            'server_url': 'https://ntfy.sh/',
            'topic': 'test-topic'
        }
        message = 'Test message'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message)

        assert result is True
        call_args = notification_service.http_client.post.call_args
        # Should not have trailing slash
        assert call_args[0][0] == 'https://ntfy.sh'

    @pytest.mark.asyncio
    async def test_ntfy_with_title(self, notification_service):
        """Test notification with custom title"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = 'Container crashed'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        # Create mock event with container name
        mock_event = Mock()
        mock_event.container_name = 'nginx'

        result = await notification_service._send_ntfy(config, message, event=mock_event)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        assert 'title' in payload
        assert 'nginx' in payload['title'] or 'DockMon' in payload['title']

    @pytest.mark.asyncio
    async def test_ntfy_with_priority(self, notification_service):
        """Test notification with priority based on event severity"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = 'Container died'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        # Create mock event with critical state
        mock_event = Mock()
        mock_event.new_state = 'dead'
        mock_event.container_name = 'critical-service'

        result = await notification_service._send_ntfy(config, message, event=mock_event)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        assert 'priority' in payload
        # Critical events should have high priority (4 or 5)
        assert payload['priority'] >= 4

    @pytest.mark.asyncio
    async def test_ntfy_with_access_token(self, notification_service):
        """Test notification with access token authentication"""
        config = {
            'server_url': 'https://ntfy.example.com',
            'topic': 'private-alerts',
            'access_token': 'tk_secrettoken123'
        }
        message = 'Test message'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message)

        assert result is True
        call_args = notification_service.http_client.post.call_args

        # Verify Authorization header is set
        headers = call_args[1].get('headers', {})
        assert 'Authorization' in headers
        assert headers['Authorization'] == 'Bearer tk_secrettoken123'

    @pytest.mark.asyncio
    async def test_ntfy_with_basic_auth(self, notification_service):
        """Test notification with username/password authentication"""
        config = {
            'server_url': 'https://ntfy.example.com',
            'topic': 'private-alerts',
            'username': 'admin',
            'password': 'secret123'
        }
        message = 'Test message'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message)

        assert result is True
        call_args = notification_service.http_client.post.call_args

        # Verify auth is passed in headers
        headers = call_args[1].get('headers', {})
        assert 'Authorization' in headers
        assert headers['Authorization'].startswith('Basic ')

    @pytest.mark.asyncio
    async def test_ntfy_missing_server_url(self, notification_service):
        """Test failure when server_url is missing"""
        config = {
            'topic': 'alerts'
            # Missing 'server_url'
        }
        message = 'Test message'

        result = await notification_service._send_ntfy(config, message)

        assert result is False
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_ntfy_missing_topic(self, notification_service):
        """Test failure when topic is missing"""
        config = {
            'server_url': 'https://ntfy.sh'
            # Missing 'topic'
        }
        message = 'Test message'

        result = await notification_service._send_ntfy(config, message)

        assert result is False
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_ntfy_empty_server_url(self, notification_service):
        """Test failure when server_url is empty"""
        config = {
            'server_url': '',
            'topic': 'alerts'
        }
        message = 'Test message'

        result = await notification_service._send_ntfy(config, message)

        assert result is False
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_ntfy_empty_topic(self, notification_service):
        """Test failure when topic is empty"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': ''
        }
        message = 'Test message'

        result = await notification_service._send_ntfy(config, message)

        assert result is False
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_ntfy_invalid_url_scheme(self, notification_service):
        """Test failure when server_url doesn't start with http/https"""
        config = {
            'server_url': 'ftp://ntfy.sh',
            'topic': 'alerts'
        }
        message = 'Test message'

        result = await notification_service._send_ntfy(config, message)

        assert result is False
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_ntfy_http_error(self, notification_service):
        """Test handling of HTTP errors"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = 'Test message'

        # Mock HTTP error response
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "Unauthorized",
                request=Mock(),
                response=mock_response
            )
        )
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message)

        assert result is False

    @pytest.mark.asyncio
    async def test_ntfy_connection_error(self, notification_service):
        """Test handling of connection errors"""
        config = {
            'server_url': 'https://ntfy.invalid',
            'topic': 'alerts'
        }
        message = 'Test message'

        # Mock connection error
        notification_service.http_client.post = AsyncMock(
            side_effect=httpx.RequestError("Connection failed", request=Mock())
        )

        result = await notification_service._send_ntfy(config, message)

        assert result is False

    @pytest.mark.asyncio
    async def test_ntfy_preserves_markdown_formatting(self, notification_service):
        """Test that markdown formatting is preserved with markdown enabled"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = '**Alert**: Container `nginx` is down'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        # Markdown should be preserved in message
        assert '**Alert**' in payload['message']
        assert '`nginx`' in payload['message']
        # Markdown should be enabled
        assert payload['markdown'] is True

    @pytest.mark.asyncio
    async def test_ntfy_preserves_emojis_in_message(self, notification_service):
        """Test that emojis are preserved in message"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = '\U0001f6a8 Container stopped \U0001f534'  # siren and red circle emojis

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        # Emojis should be preserved
        assert '\U0001f6a8' in payload['message']  # siren emoji
        assert '\U0001f534' in payload['message']  # red circle
        assert 'Container stopped' in payload['message']

    @pytest.mark.asyncio
    async def test_ntfy_preserves_emojis_in_title(self, notification_service):
        """Test that emojis are preserved in title (Issue #163)"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = 'Container stopped'
        title = '✅ DockMon Alert'  # Checkmark emoji in title

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message, title=title)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        # Emoji should be preserved in title (JSON handles Unicode natively)
        assert '✅' in payload['title']
        assert 'DockMon Alert' in payload['title']

    @pytest.mark.asyncio
    async def test_ntfy_default_title(self, notification_service):
        """Test default title when no event is provided"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = 'Test message'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message, event=None, title="Custom Title")

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        assert payload['title'] == 'Custom Title'

    @pytest.mark.asyncio
    async def test_ntfy_with_tags(self, notification_service):
        """Test notification includes appropriate tags based on event type"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = 'Container died'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        mock_event = Mock()
        mock_event.event_type = 'die'
        mock_event.container_name = 'web'

        result = await notification_service._send_ntfy(config, message, event=mock_event)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        # Tags should be present for critical events
        assert 'tags' in payload
        assert 'warning' in payload['tags']

    @pytest.mark.asyncio
    async def test_ntfy_with_action_url(self, notification_service):
        """Test notification includes action button when URL provided"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = 'Update available'
        action_url = 'https://dockmon.example.com/containers/abc123'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_ntfy(config, message, action_url=action_url)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        # Actions should be present
        assert 'actions' in payload
        assert len(payload['actions']) == 1
        assert payload['actions'][0]['action'] == 'view'
        assert payload['actions'][0]['url'] == action_url

    @pytest.mark.asyncio
    async def test_ntfy_priority_from_event_type(self, notification_service):
        """Test priority 5 triggered by critical event_type (oom, kill, die)"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': 'alerts'
        }
        message = 'Container killed'

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        # Test each critical event type
        for event_type in ['die', 'oom', 'kill']:
            mock_event = Mock()
            mock_event.event_type = event_type
            mock_event.container_name = 'critical-service'
            # Ensure new_state doesn't trigger priority (to isolate event_type test)
            mock_event.new_state = 'running'

            result = await notification_service._send_ntfy(config, message, event=mock_event)

            assert result is True
            payload = notification_service.http_client.post.call_args[1]['json']
            assert payload['priority'] == 5, f"event_type '{event_type}' should trigger priority 5"

    @pytest.mark.asyncio
    async def test_ntfy_whitespace_only_server_url(self, notification_service):
        """Test failure when server_url contains only whitespace"""
        config = {
            'server_url': '   ',
            'topic': 'alerts'
        }
        message = 'Test message'

        result = await notification_service._send_ntfy(config, message)

        assert result is False
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_ntfy_whitespace_only_topic(self, notification_service):
        """Test failure when topic contains only whitespace"""
        config = {
            'server_url': 'https://ntfy.sh',
            'topic': '   '
        }
        message = 'Test message'

        result = await notification_service._send_ntfy(config, message)

        assert result is False
        notification_service.http_client.post.assert_not_called()
