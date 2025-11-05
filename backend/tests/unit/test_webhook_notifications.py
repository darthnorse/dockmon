"""
Unit tests for webhook notification channel.

TDD RED Phase: These tests are written BEFORE the implementation.
They will fail until _send_webhook() is added to notifications.py.

Tests verify:
- Successful webhook delivery (JSON and form-encoded payloads)
- Custom HTTP headers (Authorization, etc.)
- Different HTTP methods (POST, PUT)
- Error handling (missing URL, HTTP errors, timeouts, connection errors)
- Test channel functionality
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import httpx
from datetime import datetime, timezone

# This import will work - NotificationService exists, but _send_webhook() doesn't yet
from notifications import NotificationService


@pytest.fixture
def notification_service():
    """Create NotificationService instance for testing"""
    mock_db = Mock()
    mock_event_logger = Mock()
    service = NotificationService(db=mock_db, event_logger=mock_event_logger)
    return service


@pytest.fixture
def mock_alert_event():
    """Create mock alert event for testing"""
    class MockEvent:
        container_name = "test-container"
        host_name = "test-host"
        timestamp = datetime.now(timezone.utc)
        new_state = "exited"
        event_type = "die"

    return MockEvent()


class TestWebhookSuccess:
    """Test successful webhook delivery scenarios"""

    @pytest.mark.asyncio
    async def test_send_webhook_json_success(self, notification_service):
        """
        Webhook with JSON payload should send POST request and return True on success.

        Scenario:
        - Config: URL, method=POST, payload_format=json
        - HTTP response: 200 OK
        - Should return True
        """
        config = {
            'url': 'https://example.com/webhook',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {}
        }
        message = "Test alert message"

        # Mock httpx response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()  # No exception = success

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await notification_service._send_webhook(config, message, title="Test Alert")

            assert result is True
            mock_post.assert_called_once()

            # Verify JSON payload structure
            call_args = mock_post.call_args
            assert call_args.kwargs['json']['title'] == "Test Alert"
            assert call_args.kwargs['json']['message'] == message
            assert 'timestamp' in call_args.kwargs['json']

    @pytest.mark.asyncio
    async def test_send_webhook_form_success(self, notification_service):
        """
        Webhook with form-encoded payload should send POST with form data.

        Scenario:
        - Config: payload_format=form
        - Should use 'data' parameter instead of 'json'
        - Should return True on 200 OK
        """
        config = {
            'url': 'https://example.com/webhook',
            'method': 'POST',
            'payload_format': 'form',
            'headers': {}
        }
        message = "Test alert"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await notification_service._send_webhook(config, message, title="Alert")

            assert result is True

            # Verify form data used instead of JSON
            call_args = mock_post.call_args
            assert 'data' in call_args.kwargs
            assert 'json' not in call_args.kwargs

    @pytest.mark.asyncio
    async def test_send_webhook_custom_headers(self, notification_service):
        """
        Webhook with custom headers should include them in HTTP request.

        Scenario:
        - Config: headers={'Authorization': 'Bearer token', 'X-Custom': 'value'}
        - Should pass headers to httpx request
        - Should return True on success
        """
        config = {
            'url': 'https://example.com/webhook',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {
                'Authorization': 'Bearer secret-token',
                'X-Custom-Header': 'custom-value'
            }
        }
        message = "Test"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await notification_service._send_webhook(config, message)

            assert result is True

            # Verify custom headers passed
            call_args = mock_post.call_args
            assert call_args.kwargs['headers']['Authorization'] == 'Bearer secret-token'
            assert call_args.kwargs['headers']['X-Custom-Header'] == 'custom-value'

    @pytest.mark.asyncio
    async def test_send_webhook_put_method(self, notification_service):
        """
        Webhook with PUT method should use httpx.put() instead of post().

        Scenario:
        - Config: method=PUT
        - Should call http_client.put()
        - Should return True on success
        """
        config = {
            'url': 'https://example.com/webhook',
            'method': 'PUT',
            'payload_format': 'json',
            'headers': {}
        }
        message = "Test"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        with patch.object(notification_service.http_client, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await notification_service._send_webhook(config, message)

            assert result is True

            # Verify PUT method used
            call_args = mock_request.call_args
            assert call_args.args[0] == 'PUT'

    @pytest.mark.asyncio
    async def test_send_webhook_accepted_response(self, notification_service):
        """
        Webhook should accept 202 Accepted as success (async processing).

        Scenario:
        - HTTP response: 202 Accepted
        - Should return True (2xx = success)
        """
        config = {
            'url': 'https://example.com/webhook',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {}
        }

        mock_response = Mock()
        mock_response.status_code = 202
        mock_response.raise_for_status = Mock()

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await notification_service._send_webhook(config, "Test")

            assert result is True


class TestWebhookErrors:
    """Test webhook error handling"""

    @pytest.mark.asyncio
    async def test_send_webhook_missing_url(self, notification_service):
        """
        Webhook with missing URL should log error and return False.

        Scenario:
        - Config: url is missing or empty
        - Should validate config
        - Should return False without making HTTP request
        """
        config = {
            'method': 'POST',
            'payload_format': 'json'
            # Missing 'url' key
        }

        result = await notification_service._send_webhook(config, "Test")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_http_500_error(self, notification_service):
        """
        Webhook should return False when endpoint returns 500 Internal Server Error.

        Scenario:
        - HTTP response: 500 Internal Server Error
        - Should catch HTTPStatusError
        - Should return False (triggers retry queue)
        """
        config = {
            'url': 'https://example.com/webhook',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {}
        }

        mock_response = Mock()
        mock_response.status_code = 500

        def raise_http_error():
            raise httpx.HTTPStatusError(
                "Internal Server Error",
                request=Mock(),
                response=mock_response
            )

        mock_response.raise_for_status = raise_http_error

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await notification_service._send_webhook(config, "Test")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_http_404_error(self, notification_service):
        """
        Webhook should return False when endpoint returns 404 Not Found.

        Scenario:
        - HTTP response: 404 Not Found
        - User configured wrong URL
        - Should return False
        """
        config = {
            'url': 'https://example.com/wrong-endpoint',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {}
        }

        mock_response = Mock()
        mock_response.status_code = 404

        def raise_http_error():
            raise httpx.HTTPStatusError(
                "Not Found",
                request=Mock(),
                response=mock_response
            )

        mock_response.raise_for_status = raise_http_error

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await notification_service._send_webhook(config, "Test")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_timeout(self, notification_service):
        """
        Webhook should return False when HTTP request times out.

        Scenario:
        - Webhook endpoint doesn't respond within timeout
        - httpx raises TimeoutException
        - Should catch exception and return False
        """
        config = {
            'url': 'https://slow-server.com/webhook',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {}
        }

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Request timed out")

            result = await notification_service._send_webhook(config, "Test")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_connection_error(self, notification_service):
        """
        Webhook should return False when connection fails (server unavailable).

        Scenario:
        - Webhook server is down
        - httpx raises ConnectError
        - Should catch exception and return False
        - This triggers retry queue with backoff
        """
        config = {
            'url': 'https://unavailable-server.com/webhook',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {}
        }

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")

            result = await notification_service._send_webhook(config, "Test")

            assert result is False

    @pytest.mark.asyncio
    async def test_send_webhook_dns_error(self, notification_service):
        """
        Webhook should return False when DNS resolution fails.

        Scenario:
        - Invalid hostname (DNS lookup fails)
        - httpx raises ConnectError
        - Should return False
        """
        config = {
            'url': 'https://nonexistent-domain-12345.com/webhook',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {}
        }

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("DNS resolution failed")

            result = await notification_service._send_webhook(config, "Test")

            assert result is False


class TestWebhookTestChannel:
    """Test test_channel() functionality for webhooks"""

    @pytest.mark.asyncio
    async def test_test_channel_webhook_success(self, notification_service):
        """
        test_channel() should send test webhook and return success dict.

        Scenario:
        - User clicks "Test" button on webhook channel
        - Should send test message to webhook
        - Should return {"success": True}
        """
        # Mock database to return webhook channel
        mock_channel = Mock()
        mock_channel.type = 'webhook'
        mock_channel.config = {
            'url': 'https://example.com/webhook',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {}
        }

        mock_session = Mock()
        mock_query = Mock()
        mock_query.filter_by.return_value.first.return_value = mock_channel
        mock_session.query.return_value = mock_query

        notification_service.db.get_session = Mock()
        notification_service.db.get_session.return_value.__enter__ = Mock(return_value=mock_session)
        notification_service.db.get_session.return_value.__exit__ = Mock(return_value=False)

        # Mock successful webhook send
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await notification_service.test_channel(channel_id=1)

            assert result["success"] is True
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_test_channel_webhook_failure(self, notification_service):
        """
        test_channel() should return error dict when webhook test fails.

        Scenario:
        - User clicks "Test" on webhook with bad URL
        - Webhook fails (connection error)
        - Should return {"success": False, "error": "..."}
        """
        mock_channel = Mock()
        mock_channel.type = 'webhook'
        mock_channel.config = {
            'url': 'https://bad-url.com/webhook',
            'method': 'POST',
            'payload_format': 'json',
            'headers': {}
        }

        mock_session = Mock()
        mock_query = Mock()
        mock_query.filter_by.return_value.first.return_value = mock_channel
        mock_session.query.return_value = mock_query

        notification_service.db.get_session = Mock()
        notification_service.db.get_session.return_value.__enter__ = Mock(return_value=mock_session)
        notification_service.db.get_session.return_value.__exit__ = Mock(return_value=False)

        with patch.object(notification_service.http_client, 'post', new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")

            result = await notification_service.test_channel(channel_id=1)

            assert result["success"] is False
            assert "error" in result
