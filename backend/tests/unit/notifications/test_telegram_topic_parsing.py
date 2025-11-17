"""
Unit tests for Telegram topic ID parsing in notifications.

Tests the parsing of chat_id format "-1001234567890/42" into
separate chat_id and message_thread_id parameters for Telegram Bot API.

Issue: #53
PR: #55 (merged with improvements)
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from backend.notifications import NotificationService


class TestTelegramTopicParsing:
    """Test Telegram topic ID parsing logic"""

    @pytest.fixture
    def notification_service(self):
        """Create NotificationService instance with mocked dependencies"""
        # Mock database manager
        mock_db = Mock()

        # Create service with mocked dependencies
        service = NotificationService(db=mock_db, event_logger=None)

        # Replace HTTP client with mock
        service.http_client = AsyncMock()

        yield service

    @pytest.mark.asyncio
    async def test_telegram_regular_chat_no_topic(self, notification_service):
        """Test regular chat without topic ID (backward compatibility)"""
        config = {
            'token': 'test_bot_token_123',
            'chat_id': '-1001234567890'
        }
        message = 'Test message'

        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_telegram(config, message)

        assert result is True
        # Verify the API was called
        notification_service.http_client.post.assert_called_once()
        call_args = notification_service.http_client.post.call_args

        # Verify URL
        assert call_args[0][0] == 'https://api.telegram.org/bottest_bot_token_123/sendMessage'

        # Verify payload structure
        payload = call_args[1]['json']
        assert payload['chat_id'] == '-1001234567890'
        assert 'message_thread_id' not in payload  # Should NOT be present for regular chat
        assert payload['text'] == 'Test message'
        assert payload['parse_mode'] == 'HTML'

    @pytest.mark.asyncio
    async def test_telegram_topic_chat_with_integer_topic_id(self, notification_service):
        """Test topic chat with format: -1001234567890/42"""
        config = {
            'token': 'test_bot_token_456',
            'chat_id': '-1001234567890/42'
        }
        message = 'Test topic message'

        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_telegram(config, message)

        assert result is True
        notification_service.http_client.post.assert_called_once()
        call_args = notification_service.http_client.post.call_args

        # Verify payload structure
        payload = call_args[1]['json']
        assert payload['chat_id'] == -1001234567890  # Should be integer
        assert payload['message_thread_id'] == 42  # Should be integer
        assert payload['text'] == 'Test topic message'
        assert payload['parse_mode'] == 'HTML'

    @pytest.mark.asyncio
    async def test_telegram_topic_chat_large_topic_id(self, notification_service):
        """Test topic with large topic ID"""
        config = {
            'token': 'test_bot_token_789',
            'chat_id': '-1001234567890/999999'
        }
        message = 'Test message'

        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_telegram(config, message)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        assert payload['chat_id'] == -1001234567890
        assert payload['message_thread_id'] == 999999

    @pytest.mark.asyncio
    async def test_telegram_topic_invalid_format_non_numeric_channel(self, notification_service):
        """Test invalid format: non-numeric channel ID"""
        config = {
            'token': 'test_bot_token',
            'chat_id': 'invalid-channel/42'
        }
        message = 'Test message'

        result = await notification_service._send_telegram(config, message)

        # Should return False due to ValueError
        assert result is False
        # Should NOT call the API
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_topic_invalid_format_non_numeric_topic(self, notification_service):
        """Test invalid format: non-numeric topic ID"""
        config = {
            'token': 'test_bot_token',
            'chat_id': '-1001234567890/invalid'
        }
        message = 'Test message'

        result = await notification_service._send_telegram(config, message)

        # Should return False due to ValueError
        assert result is False
        # Should NOT call the API
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_topic_missing_token(self, notification_service):
        """Test missing bot token (should fail early)"""
        config = {
            'chat_id': '-1001234567890/42'
            # Missing 'token' field
        }
        message = 'Test message'

        result = await notification_service._send_telegram(config, message)

        # Should return False due to missing token
        assert result is False
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_topic_missing_chat_id(self, notification_service):
        """Test missing chat_id (should fail early)"""
        config = {
            'token': 'test_bot_token'
            # Missing 'chat_id' field
        }
        message = 'Test message'

        result = await notification_service._send_telegram(config, message)

        # Should return False due to missing chat_id
        assert result is False
        notification_service.http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_telegram_topic_positive_chat_id(self, notification_service):
        """Test topic with positive chat ID (user chat, not channel)"""
        config = {
            'token': 'test_bot_token',
            'chat_id': '123456789/42'
        }
        message = 'Test message'

        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_telegram(config, message)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        assert payload['chat_id'] == 123456789  # Positive integer
        assert payload['message_thread_id'] == 42

    @pytest.mark.asyncio
    async def test_telegram_html_escaping_preserved(self, notification_service):
        """Test that HTML escaping still works with topic parsing"""
        config = {
            'token': 'test_bot_token',
            'chat_id': '-1001234567890/42'
        }
        # Message with special characters that need HTML escaping
        message = 'Container <nginx> failed'

        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_telegram(config, message)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        # HTML entities should be escaped
        assert '&lt;nginx&gt;' in payload['text']
        # Topic parsing should still work
        assert payload['message_thread_id'] == 42

    @pytest.mark.asyncio
    async def test_telegram_markdown_formatting_preserved(self, notification_service):
        """Test that markdown to HTML conversion works with topic parsing"""
        config = {
            'token': 'test_bot_token',
            'chat_id': '-1001234567890/42'
        }
        # Message with markdown formatting
        message = '**Alert**: Container `nginx` is down'

        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_telegram(config, message)

        assert result is True
        payload = notification_service.http_client.post.call_args[1]['json']
        # Markdown should be converted to HTML
        assert '<b>Alert</b>' in payload['text']
        assert '<code>nginx</code>' in payload['text']
        # Topic parsing should still work
        assert payload['message_thread_id'] == 42

    @pytest.mark.asyncio
    async def test_telegram_backward_compatibility_bot_token_field(self, notification_service):
        """Test backward compatibility with 'bot_token' field name"""
        config = {
            'bot_token': 'test_bot_token_legacy',  # Old field name
            'chat_id': '-1001234567890/42'
        }
        message = 'Test message'

        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_telegram(config, message)

        assert result is True
        # Should use bot_token field
        call_args = notification_service.http_client.post.call_args
        assert 'test_bot_token_legacy' in call_args[0][0]
        # Topic parsing should still work
        payload = call_args[1]['json']
        assert payload['message_thread_id'] == 42

    @pytest.mark.asyncio
    async def test_telegram_multiple_slashes_only_first_split(self, notification_service):
        """Test that only first slash is used for splitting (edge case)"""
        config = {
            'token': 'test_bot_token',
            'chat_id': '-1001234567890/42/extra'
        }
        message = 'Test message'

        # Mock successful response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service._send_telegram(config, message)

        # Should fail because "42/extra" is not a valid integer for topic_id
        assert result is False
        notification_service.http_client.post.assert_not_called()
