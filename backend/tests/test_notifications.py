"""
Tests for notification system
Covers Discord, Telegram, Pushover, and notification channel management
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import json
import httpx


class TestNotificationChannels:
    """Test notification channel management"""

    def test_telegram_channel_creation(self):
        """Test Telegram channel configuration"""
        from notifications.channels import TelegramChannel

        channel = TelegramChannel(
            bot_token="123456:ABC-DEF",
            chat_id="-100123456789"
        )
        assert channel.bot_token == "123456:ABC-DEF"
        assert channel.chat_id == "-100123456789"

    def test_discord_channel_creation(self):
        """Test Discord channel configuration"""
        from notifications.channels import DiscordChannel

        channel = DiscordChannel(
            webhook_url="https://discord.com/api/webhooks/123/abc"
        )
        assert channel.webhook_url == "https://discord.com/api/webhooks/123/abc"

    def test_pushover_channel_creation(self):
        """Test Pushover channel configuration"""
        from notifications.channels import PushoverChannel

        channel = PushoverChannel(
            app_token="azGDORePK8gMaC0QOYAMyEEuzJnyUi",
            user_key="uQiRzpo4DXghDmr9QzzfQu27cmVRsG"
        )
        assert channel.app_token == "azGDORePK8gMaC0QOYAMyEEuzJnyUi"
        assert channel.user_key == "uQiRzpo4DXghDmr9QzzfQu27cmVRsG"

    @patch('httpx.AsyncClient.post')
    async def test_telegram_send_success(self, mock_post):
        """Test successful Telegram notification"""
        from notifications.channels import TelegramChannel

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_post.return_value = mock_response

        channel = TelegramChannel(
            bot_token="test_token",
            chat_id="test_chat"
        )

        result = await channel.send_notification(
            title="Test Alert",
            message="Container stopped",
            priority="high"
        )
        assert result is True
        mock_post.assert_called_once()

    @patch('httpx.AsyncClient.post')
    async def test_telegram_send_failure(self, mock_post):
        """Test failed Telegram notification"""
        from notifications.channels import TelegramChannel

        mock_post.side_effect = httpx.HTTPError("Connection failed")

        channel = TelegramChannel(
            bot_token="test_token",
            chat_id="test_chat"
        )

        result = await channel.send_notification(
            title="Test Alert",
            message="Container stopped",
            priority="high"
        )
        assert result is False

    @patch('httpx.AsyncClient.post')
    async def test_discord_send_with_embed(self, mock_post):
        """Test Discord notification with rich embed"""
        from notifications.channels import DiscordChannel

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response

        channel = DiscordChannel(
            webhook_url="https://discord.com/api/webhooks/test"
        )

        result = await channel.send_notification(
            title="Container Alert",
            message="Container 'web-app' has stopped",
            priority="high",
            container_info={
                "name": "web-app",
                "status": "exited",
                "exit_code": 1
            }
        )
        assert result is True

        # Verify embed was created
        call_args = mock_post.call_args
        payload = call_args.kwargs.get('json', {})
        assert 'embeds' in payload

    @patch('httpx.AsyncClient.post')
    async def test_pushover_priority_levels(self, mock_post):
        """Test Pushover with different priority levels"""
        from notifications.channels import PushoverChannel

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": 1}
        mock_post.return_value = mock_response

        channel = PushoverChannel(
            app_token="test_app",
            user_key="test_user"
        )

        # Test high priority (should set priority=1)
        await channel.send_notification(
            title="Critical Alert",
            message="Container OOM",
            priority="critical"
        )

        call_args = mock_post.call_args
        data = call_args.kwargs.get('data', {})
        assert data.get('priority') == 2  # Critical in Pushover

    def test_channel_validation(self):
        """Test channel configuration validation"""
        from notifications.channels import validate_channel_config

        # Valid Telegram config
        assert validate_channel_config("telegram", {
            "bot_token": "123:ABC",
            "chat_id": "-100123"
        }) is True

        # Invalid Telegram config (missing chat_id)
        assert validate_channel_config("telegram", {
            "bot_token": "123:ABC"
        }) is False

        # Valid Discord config
        assert validate_channel_config("discord", {
            "webhook_url": "https://discord.com/api/webhooks/123/abc"
        }) is True

        # Invalid Discord URL
        assert validate_channel_config("discord", {
            "webhook_url": "not_a_url"
        }) is False


class TestNotificationManager:
    """Test notification manager and alert sending"""

    @pytest.fixture
    def notification_manager(self, temp_db):
        """Create a notification manager instance"""
        from notifications.manager import NotificationManager
        return NotificationManager(temp_db)

    def test_load_channels(self, notification_manager, temp_db):
        """Test loading notification channels from database"""
        # Add test channel to database
        temp_db.add_notification_channel({
            "type": "telegram",
            "name": "Test Telegram",
            "config": json.dumps({
                "bot_token": "test_token",
                "chat_id": "test_chat"
            }),
            "enabled": True
        })

        channels = notification_manager.load_channels()
        assert len(channels) == 1
        assert channels[0]["type"] == "telegram"

    @patch('notifications.manager.TelegramChannel.send_notification')
    async def test_send_alert_to_all_channels(self, mock_send, notification_manager, temp_db):
        """Test sending alert to all configured channels"""
        mock_send.return_value = True

        # Add multiple channels
        temp_db.add_notification_channel({
            "type": "telegram",
            "name": "Channel 1",
            "config": json.dumps({"bot_token": "token1", "chat_id": "chat1"}),
            "enabled": True
        })
        temp_db.add_notification_channel({
            "type": "discord",
            "name": "Channel 2",
            "config": json.dumps({"webhook_url": "https://discord.com/webhook"}),
            "enabled": True
        })

        alert_data = {
            "title": "Container Alert",
            "message": "Container stopped unexpectedly",
            "container_name": "web-app",
            "host_name": "production-server"
        }

        results = await notification_manager.send_alert(alert_data)
        assert len(results) == 2

    def test_disabled_channel_not_used(self, notification_manager, temp_db):
        """Test that disabled channels don't receive notifications"""
        # Add disabled channel
        temp_db.add_notification_channel({
            "type": "telegram",
            "name": "Disabled Channel",
            "config": json.dumps({"bot_token": "token", "chat_id": "chat"}),
            "enabled": False
        })

        channels = notification_manager.get_active_channels()
        assert len(channels) == 0

    @patch('httpx.AsyncClient.post')
    async def test_notification_retry_logic(self, mock_post, notification_manager):
        """Test notification retry on failure"""
        # First call fails, second succeeds
        mock_post.side_effect = [
            httpx.HTTPError("Connection failed"),
            MagicMock(status_code=200, json=lambda: {"ok": True})
        ]

        from notifications.channels import TelegramChannel
        channel = TelegramChannel("token", "chat")

        # Should retry and succeed
        result = await channel.send_notification_with_retry(
            title="Test",
            message="Test message",
            max_retries=2
        )
        assert result is True
        assert mock_post.call_count == 2

    def test_notification_rate_limiting(self, notification_manager):
        """Test notification rate limiting to prevent spam"""
        # Send multiple notifications for same container
        for i in range(10):
            should_send = notification_manager.should_send_notification(
                container_id="container123",
                alert_type="status_change",
                cooldown_minutes=5
            )
            if i == 0:
                assert should_send is True  # First should send
            else:
                assert should_send is False  # Rest should be rate limited

    def test_notification_formatting(self, notification_manager):
        """Test notification message formatting"""
        message = notification_manager.format_notification(
            container_name="web-app",
            event_type="die",
            host_name="production",
            exit_code=1,
            timestamp="2024-01-01T12:00:00Z"
        )

        assert "web-app" in message
        assert "die" in message
        assert "production" in message
        assert "exit code 1" in message

    def test_priority_determination(self, notification_manager):
        """Test priority level determination based on event"""
        # Critical events
        assert notification_manager.get_priority("oom") == "critical"
        assert notification_manager.get_priority("die", exit_code=137) == "critical"

        # High priority
        assert notification_manager.get_priority("die", exit_code=1) == "high"
        assert notification_manager.get_priority("health_status", health="unhealthy") == "high"

        # Normal priority
        assert notification_manager.get_priority("stop") == "normal"
        assert notification_manager.get_priority("pause") == "normal"

    @patch('notifications.manager.NotificationManager.send_notification')
    async def test_batch_notifications(self, mock_send, notification_manager):
        """Test batching multiple notifications"""
        notifications = [
            {"container": "app1", "event": "stop"},
            {"container": "app2", "event": "stop"},
            {"container": "app3", "event": "stop"}
        ]

        # Should batch into single notification
        await notification_manager.send_batch_notification(notifications)

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert "3 containers" in call_args[0][0]  # Message should mention 3 containers

    def test_notification_deduplication(self, notification_manager):
        """Test deduplication of identical notifications"""
        notification1 = {
            "container_id": "abc123",
            "event": "die",
            "timestamp": "2024-01-01T12:00:00Z"
        }
        notification2 = {
            "container_id": "abc123",
            "event": "die",
            "timestamp": "2024-01-01T12:00:01Z"  # 1 second later
        }

        # Should detect as duplicate
        assert notification_manager.is_duplicate(notification1, notification2, window_seconds=10) is True

        # Different event should not be duplicate
        notification2["event"] = "start"
        assert notification_manager.is_duplicate(notification1, notification2, window_seconds=10) is False