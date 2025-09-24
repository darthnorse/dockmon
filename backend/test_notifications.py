#!/usr/bin/env python3
"""
Test script for DockMon notification functionality
"""

import asyncio
import json
import sys
from datetime import datetime
from notifications import NotificationService, AlertEvent, AlertProcessor
from database import DatabaseManager

async def test_notification_channels():
    """Test creating and testing notification channels"""
    print("🔧 Testing notification channel functionality...")

    db = DatabaseManager(db_path="test_dockmon.db")
    notification_service = NotificationService(db)

    try:
        # Test Telegram channel creation
        print("\n📱 Testing Telegram channel...")
        telegram_channel = db.add_notification_channel({
            "name": "Test Telegram",
            "type": "telegram",
            "config": {
                "bot_token": "test_token",
                "chat_id": "test_chat_id"
            },
            "enabled": True
        })
        print(f"✅ Created Telegram channel: {telegram_channel.name} (ID: {telegram_channel.id})")

        # Test Discord channel creation
        print("\n💬 Testing Discord channel...")
        discord_channel = db.add_notification_channel({
            "name": "Test Discord",
            "type": "discord",
            "config": {
                "webhook_url": "https://discord.com/api/webhooks/test"
            },
            "enabled": True
        })
        print(f"✅ Created Discord channel: {discord_channel.name} (ID: {discord_channel.id})")

        # Test Pushover channel creation
        print("\n🔔 Testing Pushover channel...")
        pushover_channel = db.add_notification_channel({
            "name": "Test Pushover",
            "type": "pushover",
            "config": {
                "app_token": "test_app_token",
                "user_key": "test_user_key"
            },
            "enabled": True
        })
        print(f"✅ Created Pushover channel: {pushover_channel.name} (ID: {pushover_channel.id})")

        # List all channels
        print("\n📋 All notification channels:")
        channels = db.get_notification_channels(enabled_only=False)
        for channel in channels:
            status = "✅ Enabled" if channel.enabled else "❌ Disabled"
            print(f"  - {channel.name} ({channel.type}) - {status}")

        print(f"\n🎯 Total channels created: {len(channels)}")

    except Exception as e:
        print(f"❌ Error testing channels: {e}")
    finally:
        await notification_service.close()

async def test_alert_rules():
    """Test creating and managing alert rules"""
    print("\n🚨 Testing alert rule functionality...")

    db = DatabaseManager(db_path="test_dockmon.db")

    try:
        # Create test alert rule
        rule_data = {
            "id": "test_rule_1",
            "name": "Container Down Alert",
            "host_id": None,  # All hosts
            "container_pattern": ".*",  # All containers
            "trigger_states": ["exited", "dead"],
            "notification_channels": [1, 2],  # Use first two channels
            "cooldown_minutes": 5,
            "enabled": True
        }

        alert_rule = db.add_alert_rule(rule_data)
        print(f"✅ Created alert rule: {alert_rule.name}")
        print(f"   Pattern: {alert_rule.container_pattern}")
        print(f"   Triggers: {alert_rule.trigger_states}")
        print(f"   Channels: {alert_rule.notification_channels}")

        # List all rules
        rules = db.get_alert_rules(enabled_only=False)
        print(f"\n📋 Total alert rules: {len(rules)}")

    except Exception as e:
        print(f"❌ Error testing alert rules: {e}")

async def test_alert_processing():
    """Test alert processing logic"""
    print("\n⚡ Testing alert processing...")

    db = DatabaseManager(db_path="test_dockmon.db")
    notification_service = NotificationService(db)

    try:
        # Create test alert event
        alert_event = AlertEvent(
            container_id="test_container_123",
            container_name="nginx-web",
            host_id="test_host",
            host_name="Test Docker Host",
            old_state="running",
            new_state="exited",
            timestamp=datetime.now(),
            image="nginx:latest",
            triggered_by="test"
        )

        print(f"📦 Test alert event:")
        print(f"   Container: {alert_event.container_name}")
        print(f"   State change: {alert_event.old_state} → {alert_event.new_state}")
        print(f"   Host: {alert_event.host_name}")

        # Process alert (will attempt to send notifications)
        result = await notification_service.send_alert(alert_event)

        if result:
            print("✅ Alert processed successfully")
        else:
            print("⚠️  No matching alert rules or notifications sent")

        # Check container history
        history = db.get_container_history(limit=5)
        print(f"\n📊 Recent container events: {len(history)}")
        for event in history[:3]:  # Show last 3 events
            print(f"   - {event.container_name}: {event.event_type} at {event.timestamp}")

    except Exception as e:
        print(f"❌ Error testing alert processing: {e}")
    finally:
        await notification_service.close()

def test_database_operations():
    """Test database operations"""
    print("\n💾 Testing database operations...")

    try:
        db = DatabaseManager(db_path="test_dockmon.db")

        # Test settings
        settings = db.get_settings()
        print(f"✅ Global settings loaded:")
        print(f"   Max retries: {settings.max_retries}")
        print(f"   Polling interval: {settings.polling_interval}")
        print(f"   Notifications enabled: {settings.enable_notifications}")

        # Test updating settings
        updated = db.update_settings({"enable_notifications": True})
        print(f"✅ Settings updated - Notifications: {updated.enable_notifications}")

    except Exception as e:
        print(f"❌ Error testing database: {e}")

async def main():
    """Main test function"""
    print("🐳 DockMon Notification System Test")
    print("=" * 50)

    # Run tests
    test_database_operations()
    await test_notification_channels()
    await test_alert_rules()
    await test_alert_processing()

    print("\n🎉 Test completed!")
    print("\nℹ️  Note: Actual notifications will fail with test credentials.")
    print("   Configure real credentials to test actual sending.")

if __name__ == "__main__":
    asyncio.run(main())