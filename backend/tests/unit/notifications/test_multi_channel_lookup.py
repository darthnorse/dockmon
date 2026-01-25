"""
Unit tests for multiple notification channel support.

Tests the channel lookup logic when multiple channels of the same type exist.
Verifies that ID-based lookup correctly selects specific channels.

Issue: #167
"""

import json
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from contextlib import contextmanager

from notifications import NotificationService
from database import NotificationChannel, AlertRuleV2, AlertV2


# ==================== Shared Test Helpers ====================

def create_mock_channel(id: int, name: str, type: str, config: dict, enabled: bool = True):
    """Helper to create mock NotificationChannel"""
    channel = Mock(spec=NotificationChannel)
    channel.id = id
    channel.name = name
    channel.type = type
    channel.config = config
    channel.enabled = enabled
    return channel


def create_mock_alert(id: str = "alert-1", rule_id: str = "rule-1"):
    """Helper to create mock AlertV2"""
    alert = Mock(spec=AlertV2)
    alert.id = id
    alert.rule_id = rule_id
    alert.title = "Test Alert"
    alert.message = "Test message"
    alert.severity = "warning"
    alert.kind = "container_stopped"
    alert.scope_type = "container"
    alert.scope_id = "host1:abc123"
    alert.container_name = "nginx"
    alert.host_name = "server1"
    alert.notified_at = None  # Not yet notified
    return alert


def create_mock_rule(id: str = "rule-1", notify_channels_json: str = "[1, 2]"):
    """Helper to create mock AlertRuleV2"""
    rule = Mock(spec=AlertRuleV2)
    rule.id = id
    rule.name = "Test Rule"
    rule.notify_channels_json = notify_channels_json
    rule.custom_template = None
    rule.category = "container"
    return rule


# ==================== Shared Fixtures ====================

@pytest.fixture
def mock_db():
    """Create mock database manager"""
    db = Mock()
    db.get_session = MagicMock()
    db.get_settings = Mock(return_value=Mock(external_url=None))
    return db


@pytest.fixture
def mock_db_with_session():
    """Create mock database manager with context manager session"""
    db = Mock()

    @contextmanager
    def mock_session():
        session = Mock()
        session.query.return_value.filter.return_value.first.return_value = None
        yield session

    db.get_session = mock_session
    db.get_settings = Mock(return_value=Mock(external_url=None))
    return db


@pytest.fixture
def notification_service(mock_db):
    """Create NotificationService with mocked dependencies"""
    service = NotificationService(db=mock_db, event_logger=None)
    service.http_client = AsyncMock()
    return service


@pytest.fixture
def notification_service_full(mock_db_with_session):
    """Create NotificationService with full mocking for end-to-end tests"""
    service = NotificationService(db=mock_db_with_session, event_logger=None)
    service.http_client = AsyncMock()
    service.blackout_manager = Mock()
    service.blackout_manager.is_in_blackout_window.return_value = (False, None)
    service._is_rate_limited = Mock(return_value=False)
    service._get_template_for_alert_v2 = Mock(return_value="Test: {title}")
    service._format_message_v2 = Mock(return_value="Formatted test message")
    return service


# ==================== Test Classes ====================

class TestMultiChannelLookup:
    """Test notification channel lookup with multiple channels of same type"""

    def test_channel_map_by_type_overwrites_duplicates(self, notification_service, mock_db):
        """
        Verify that channel_map_by_type only keeps one channel per type.
        This demonstrates the bug when using type-based lookup.
        """
        # Create two Discord channels
        discord_alerts = create_mock_channel(
            id=1, name="Discord - Alerts", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        discord_critical = create_mock_channel(
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
        discord_alerts = create_mock_channel(
            id=1, name="Discord - Alerts", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        discord_critical = create_mock_channel(
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
        discord_alerts = create_mock_channel(
            id=1, name="Discord - Alerts", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        discord_critical = create_mock_channel(
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
        discord = create_mock_channel(
            id=1, name="Discord", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        telegram = create_mock_channel(
            id=2, name="Telegram", type="telegram",
            config={"bot_token": "token", "chat_id": "123"}
        )
        discord2 = create_mock_channel(
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
        discord1 = create_mock_channel(
            id=1, name="Discord 1", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        discord2 = create_mock_channel(
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
        discord1 = create_mock_channel(
            id=1, name="Discord 1", type="discord",
            config={"webhook_url": "https://discord.com/webhook1"}
        )
        telegram = create_mock_channel(
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

    @pytest.mark.asyncio
    async def test_sends_to_multiple_discord_channels(self, notification_service, mock_db):
        """Test that notifications are sent to all specified Discord channels"""
        # Create two Discord channels with different webhooks
        discord_alerts = create_mock_channel(
            id=1, name="Discord - Alerts", type="discord",
            config={"webhook_url": "https://discord.com/api/webhooks/alerts"}
        )
        discord_critical = create_mock_channel(
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


class TestSendAlertV2EndToEnd:
    """End-to-end tests that call actual send_alert_v2 method"""

    @pytest.mark.asyncio
    async def test_send_alert_v2_with_integer_channel_ids(self, notification_service_full, mock_db_with_session):
        """
        End-to-end test: send_alert_v2 correctly sends to multiple Discord channels
        when notify_channels_json contains integer IDs.
        """
        # Create two Discord channels
        discord1 = create_mock_channel(
            id=1, name="Discord - Alerts", type="discord",
            config={"webhook_url": "https://discord.com/api/webhooks/111/alerts"}
        )
        discord2 = create_mock_channel(
            id=2, name="Discord - Critical", type="discord",
            config={"webhook_url": "https://discord.com/api/webhooks/222/critical"}
        )

        # Mock database returns both channels
        mock_db_with_session.get_notification_channels.return_value = [discord1, discord2]

        # Create alert and rule with integer channel IDs
        alert = create_mock_alert()
        rule = create_mock_rule(notify_channels_json='[1, 2]')  # Integer IDs

        # Mock successful Discord webhook responses
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service_full.http_client.post = AsyncMock(return_value=mock_response)

        # Call the actual method
        result = await notification_service_full.send_alert_v2(alert, rule)

        # Verify success
        assert result is True

        # Verify both Discord webhooks were called
        assert notification_service_full.http_client.post.call_count == 2

        # Extract webhook URLs that were called
        called_urls = [
            call.args[0] for call in notification_service_full.http_client.post.call_args_list
        ]
        assert "https://discord.com/api/webhooks/111/alerts" in called_urls
        assert "https://discord.com/api/webhooks/222/critical" in called_urls

    @pytest.mark.asyncio
    async def test_send_alert_v2_with_legacy_type_strings(self, notification_service_full, mock_db_with_session):
        """
        End-to-end test: send_alert_v2 still works with legacy type strings
        (but only sends to one channel per type due to map overwrite).
        """
        # Create two Discord channels
        discord1 = create_mock_channel(
            id=1, name="Discord 1", type="discord",
            config={"webhook_url": "https://discord.com/api/webhooks/111"}
        )
        discord2 = create_mock_channel(
            id=2, name="Discord 2", type="discord",
            config={"webhook_url": "https://discord.com/api/webhooks/222"}
        )

        mock_db_with_session.get_notification_channels.return_value = [discord1, discord2]

        alert = create_mock_alert()
        rule = create_mock_rule(notify_channels_json='["discord"]')  # Legacy type string

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service_full.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service_full.send_alert_v2(alert, rule)

        assert result is True
        # With legacy format, only ONE Discord channel is called (the last one in map)
        assert notification_service_full.http_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_send_alert_v2_with_mixed_format(self, notification_service_full, mock_db_with_session):
        """
        End-to-end test: send_alert_v2 handles mixed array of IDs and type strings.
        """
        discord = create_mock_channel(
            id=1, name="Discord", type="discord",
            config={"webhook_url": "https://discord.com/api/webhooks/111"}
        )
        telegram = create_mock_channel(
            id=2, name="Telegram", type="telegram",
            config={"bot_token": "token123", "chat_id": "456"}
        )

        mock_db_with_session.get_notification_channels.return_value = [discord, telegram]

        alert = create_mock_alert()
        # Mixed format: ID 1 (Discord) + type string "telegram"
        rule = create_mock_rule(notify_channels_json='[1, "telegram"]')

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service_full.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service_full.send_alert_v2(alert, rule)

        assert result is True
        # Both channels should be called
        assert notification_service_full.http_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_alert_v2_skips_nonexistent_channel_ids(self, notification_service_full, mock_db_with_session):
        """
        End-to-end test: send_alert_v2 gracefully skips channel IDs that don't exist.
        """
        discord = create_mock_channel(
            id=1, name="Discord", type="discord",
            config={"webhook_url": "https://discord.com/api/webhooks/111"}
        )

        mock_db_with_session.get_notification_channels.return_value = [discord]

        alert = create_mock_alert()
        # Channel ID 999 doesn't exist
        rule = create_mock_rule(notify_channels_json='[1, 999]')

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        notification_service_full.http_client.post = AsyncMock(return_value=mock_response)

        result = await notification_service_full.send_alert_v2(alert, rule)

        assert result is True
        # Only the existing channel (ID 1) should be called
        assert notification_service_full.http_client.post.call_count == 1
