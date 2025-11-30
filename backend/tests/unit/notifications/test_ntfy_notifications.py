"""
Unit tests for ntfy notification channel.

Tests the _send_ntfy() method in NotificationService for sending
notifications to ntfy servers (self-hosted or ntfy.sh).

Issue: #80
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
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

        # Verify URL format: server_url/topic
        assert call_args[0][0] == 'https://ntfy.sh/dockmon-alerts'

        # Verify message sent as plain text content
        content = call_args[1]['content']
        assert content == 'Container nginx stopped'

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
        assert call_args[0][0] == 'https://ntfy.example.com/alerts'

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
        # Should not have double slash
        assert call_args[0][0] == 'https://ntfy.sh/test-topic'

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
        headers = notification_service.http_client.post.call_args[1]['headers']
        assert 'Title' in headers
        assert 'nginx' in headers['Title'] or 'DockMon' in headers['Title']

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
        headers = notification_service.http_client.post.call_args[1]['headers']
        assert 'Priority' in headers
        # Critical events should have high priority (4 or 5)
        assert int(headers['Priority']) >= 4

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

        # Verify auth is passed
        assert 'auth' in call_args[1] or 'Authorization' in call_args[1].get('headers', {})

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
    async def test_ntfy_strips_markdown_formatting(self, notification_service):
        """Test that markdown formatting is stripped for plain text"""
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
        call_args = notification_service.http_client.post.call_args
        # Message sent as plain text body via content= parameter
        content = call_args[1]['content']
        # Markdown should be stripped
        assert '**' not in content
        assert '`' not in content
        assert 'Alert' in content
        assert 'nginx' in content

    @pytest.mark.asyncio
    async def test_ntfy_strips_emojis(self, notification_service):
        """Test that emojis are stripped from message"""
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
        content = notification_service.http_client.post.call_args[1]['content']
        # Common alert emojis should be stripped
        assert '\U0001f6a8' not in content  # siren emoji
        assert '\U0001f534' not in content  # red circle
        assert 'Container stopped' in content

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
        headers = notification_service.http_client.post.call_args[1]['headers']
        assert headers['Title'] == 'Custom Title'

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
        headers = notification_service.http_client.post.call_args[1]['headers']
        # Tags should be present for critical events
        assert 'Tags' in headers
        assert 'warning' in headers['Tags']
