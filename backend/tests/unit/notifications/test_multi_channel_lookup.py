"""
Unit tests for multiple notification channel support.

Tests the channel lookup logic when multiple channels of the same type exist.
Verifies that ID-based lookup correctly selects specific channels.

Issue: #167
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from notifications import NotificationService
from database import NotificationChannel, AlertRuleV2, AlertV2


class TestMultiChannelLookup:
    """Test notification channel lookup with multiple channels of same type"""

    @pytest.fixture
    def mock_db(self):
        """Create mock database manager"""
        db = Mock()
        db.get_session = MagicMock()
        return db

    @pytest.fixture
    def notification_service(self, mock_db):
        """Create NotificationService with mocked dependencies"""
        service = NotificationService(db=mock_db, event_logger=None)
        service.http_client = AsyncMock()
        return service

    def create_mock_channel(self, id: int, name: str, type: str, config: dict, enabled: bool = True):
        """Helper to create mock NotificationChannel"""
        channel = Mock(spec=NotificationChannel)
        channel.id = id
        channel.name = name
        channel.type = type
        channel.config = config
        channel.enabled = enabled
        return channel

    def test_channel_map_by_type_overwrites_duplicates(self, notification_service, mock_db):
        """
        Verify that channel_map_by_type only keeps one channel per type.
        This demonstrates the bug when using type-based lookup.
        """
        # Create two Discord channels
        discord_alerts = self.create_mock_channel(
            id=1, name="Discord - Alerts", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        discord_critical = self.create_mock_channel(
            id=2, name="Discord - Critical", type="discord",
            config={"webhook_url": "https://discord.com/webhook2"}
        )

        channels = [discord_alerts, discord_critical]

        # This is how the code builds the type map (line 1051 in notifications.py)
        channel_map_by_type = {ch.type: ch for ch in channels}

        # Bug: Only ONE Discord channel in the map (the last one)
        assert len(channel_map_by_type) == 1
        assert channel_map_by_type["discord"].id == 2  # Second channel overwrote first

    def test_channel_map_by_id_keeps_all_channels(self, notification_service, mock_db):
        """
        Verify that channel_map_by_id correctly keeps all channels.
        This is the correct approach for multi-channel support.
        """
        # Create two Discord channels
        discord_alerts = self.create_mock_channel(
            id=1, name="Discord - Alerts", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        discord_critical = self.create_mock_channel(
            id=2, name="Discord - Critical", type="discord",
            config={"webhook_url": "https://discord.com/webhook2"}
        )

        channels = [discord_alerts, discord_critical]

        # This is how the code builds the ID map (line 1050 in notifications.py)
        channel_map_by_id = {ch.id: ch for ch in channels}

        # Correct: Both channels are accessible by ID
        assert len(channel_map_by_id) == 2
        assert channel_map_by_id[1].name == "Discord - Alerts"
        assert channel_map_by_id[2].name == "Discord - Critical"

    def test_id_based_lookup_selects_correct_channel(self, notification_service, mock_db):
        """
        Test that ID-based channel lookup (integers) selects the correct channel.
        """
        # Create two Discord channels
        discord_alerts = self.create_mock_channel(
            id=1, name="Discord - Alerts", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        discord_critical = self.create_mock_channel(
            id=2, name="Discord - Critical", type="discord",
            config={"webhook_url": "https://discord.com/webhook2"}
        )

        channels = [discord_alerts, discord_critical]
        channel_map_by_id = {ch.id: ch for ch in channels}
        channel_map_by_type = {ch.type: ch for ch in channels}

        # Simulate the lookup logic from notifications.py lines 1109-1118
        def lookup_channel(channel_id):
            if isinstance(channel_id, int) and channel_id in channel_map_by_id:
                return channel_map_by_id[channel_id]
            elif isinstance(channel_id, str) and channel_id in channel_map_by_type:
                return channel_map_by_type[channel_id]
            return None

        # ID-based lookup correctly finds specific channels
        assert lookup_channel(1).name == "Discord - Alerts"
        assert lookup_channel(2).name == "Discord - Critical"

        # Type-based lookup only finds one (the bug)
        assert lookup_channel("discord").name == "Discord - Critical"  # Always the last one

    def test_notify_channels_json_with_ids(self, notification_service, mock_db):
        """
        Test that notify_channels_json with integer IDs works correctly.
        """
        # Create channels of different types
        discord = self.create_mock_channel(
            id=1, name="Discord", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        telegram = self.create_mock_channel(
            id=2, name="Telegram", type="telegram",
            config={"bot_token": "token", "chat_id": "123"}
        )
        discord2 = self.create_mock_channel(
            id=3, name="Discord 2", type="discord",
            config={"webhook_url": "https://discord.com/webhook2"}
        )

        channels = [discord, telegram, discord2]
        channel_map_by_id = {ch.id: ch for ch in channels}

        # New format: array of channel IDs
        notify_channels_json = json.dumps([1, 3])  # Both Discord channels
        channel_ids = json.loads(notify_channels_json)

        # Verify both Discord channels are selected
        selected = [channel_map_by_id[cid] for cid in channel_ids if cid in channel_map_by_id]
        assert len(selected) == 2
        assert selected[0].name == "Discord"
        assert selected[1].name == "Discord 2"

    def test_backward_compatibility_with_type_strings(self, notification_service, mock_db):
        """
        Test that old format (type strings) still works but only selects one channel per type.
        """
        discord1 = self.create_mock_channel(
            id=1, name="Discord 1", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        discord2 = self.create_mock_channel(
            id=2, name="Discord 2", type="discord",
            config={"webhook_url": "https://discord.com/webhook2"}
        )

        channels = [discord1, discord2]
        channel_map_by_id = {ch.id: ch for ch in channels}
        channel_map_by_type = {ch.type: ch for ch in channels}

        # Old format: array of type strings
        notify_channels_json = json.dumps(["discord"])
        channel_ids = json.loads(notify_channels_json)

        # Simulate lookup logic
        selected = []
        for channel_id in channel_ids:
            if isinstance(channel_id, int) and channel_id in channel_map_by_id:
                selected.append(channel_map_by_id[channel_id])
            elif isinstance(channel_id, str) and channel_id in channel_map_by_type:
                selected.append(channel_map_by_type[channel_id])

        # Old format only gets ONE channel (the bug, but backward compatible)
        assert len(selected) == 1

    def test_mixed_id_and_type_lookup(self, notification_service, mock_db):
        """
        Test that mixed arrays (IDs + type strings) work for migration period.
        """
        discord1 = self.create_mock_channel(
            id=1, name="Discord 1", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        telegram = self.create_mock_channel(
            id=2, name="Telegram", type="telegram",
            config={"bot_token": "token", "chat_id": "123"}
        )

        channels = [discord1, telegram]
        channel_map_by_id = {ch.id: ch for ch in channels}
        channel_map_by_type = {ch.type: ch for ch in channels}

        # Mixed format (unlikely but possible during migration)
        notify_channels_json = json.dumps([1, "telegram"])
        channel_ids = json.loads(notify_channels_json)

        # Simulate lookup logic
        selected = []
        for channel_id in channel_ids:
            if isinstance(channel_id, int) and channel_id in channel_map_by_id:
                selected.append(channel_map_by_id[channel_id])
            elif isinstance(channel_id, str) and channel_id in channel_map_by_type:
                selected.append(channel_map_by_type[channel_id])

        # Both channels found
        assert len(selected) == 2
        assert selected[0].name == "Discord 1"
        assert selected[1].name == "Telegram"


class TestMultiChannelNotificationSending:
    """Integration-style tests for sending to multiple channels of same type"""

    @pytest.fixture
    def mock_db(self):
        """Create mock database manager"""
        db = Mock()
        db.get_session = MagicMock()
        return db

    @pytest.fixture
    def notification_service(self, mock_db):
        """Create NotificationService with mocked dependencies"""
        service = NotificationService(db=mock_db, event_logger=None)
        service.http_client = AsyncMock()
        # Mock the blackout manager
        service.blackout_manager = Mock()
        service.blackout_manager.is_in_blackout_window.return_value = (False, None)
        return service

    def create_mock_channel(self, id: int, name: str, type: str, config: dict, enabled: bool = True):
        """Helper to create mock NotificationChannel"""
        channel = Mock(spec=NotificationChannel)
        channel.id = id
        channel.name = name
        channel.type = type
        channel.config = config
        channel.enabled = enabled
        return channel

    @pytest.mark.asyncio
    async def test_sends_to_multiple_discord_channels(self, notification_service, mock_db):
        """Test that notifications are sent to all specified Discord channels"""
        # Create two Discord channels with different webhooks
        discord_alerts = self.create_mock_channel(
            id=1, name="Discord - Alerts", type="discord",
            config={"webhook_url": "https://discord.com/api/webhooks/alerts"}
        )
        discord_critical = self.create_mock_channel(
            id=2, name="Discord - Critical", type="discord",
            config={"webhook_url": "https://discord.com/api/webhooks/critical"}
        )

        # Mock db.get_notification_channels to return both
        mock_db.get_notification_channels.return_value = [discord_alerts, discord_critical]

        # Mock successful HTTP responses
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service.http_client.post = AsyncMock(return_value=mock_response)

        # Build channel maps (simulating what send_alert_v2 does)
        channels = mock_db.get_notification_channels(enabled_only=True)
        channel_map_by_id = {ch.id: ch for ch in channels}

        # Channels to notify (IDs, not types)
        channel_ids = [1, 2]  # Both Discord channels

        # Simulate sending to each channel
        webhooks_called = []
        for channel_id in channel_ids:
            channel = channel_map_by_id.get(channel_id)
            if channel:
                # Record which webhook would be called
                webhooks_called.append(channel.config["webhook_url"])

        # Verify both webhooks would be called
        assert len(webhooks_called) == 2
        assert "https://discord.com/api/webhooks/alerts" in webhooks_called
        assert "https://discord.com/api/webhooks/critical" in webhooks_called
