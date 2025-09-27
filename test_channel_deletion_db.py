#!/usr/bin/env python3
"""
Test channel deletion safeguards by directly using the database and API modules
"""
import sys
sys.path.insert(0, '/app/backend')

from database import DatabaseManager
import json

def run_tests():
    """Run comprehensive tests for channel deletion safeguards"""

    print("\n" + "="*60)
    print("🧪 TESTING CHANNEL DELETION SAFEGUARDS")
    print("="*60 + "\n")

    db = DatabaseManager()

    # Cleanup any existing test data
    print("🧹 Cleaning up existing test data...")
    all_alerts = db.get_alert_rules()
    for alert in all_alerts:
        db.delete_alert_rule(alert.id)

    all_channels = db.get_notification_channels()
    for channel in all_channels:
        db.delete_notification_channel(channel.id)
    print("✅ Cleanup complete\n")

    # Get hosts for testing
    print("📋 Getting hosts and containers...")
    hosts = db.get_hosts()
    if len(hosts) < 1:
        print("❌ Need at least 1 host with containers")
        return

    host = hosts[0]
    # Get containers from host
    containers_data = db.get_containers_by_host(host.id)
    if len(containers_data) < 2:
        print("❌ Need at least 2 containers for testing")
        return

    print(f"✅ Found host: {host.name} with {len(containers_data)} containers\n")

    container1_name = containers_data[0]['name']
    container2_name = containers_data[1]['name']

    # Step 1: Create notification channels
    print("📢 Step 1: Creating notification channels...")
    print("-" * 60)

    discord_channel = db.add_notification_channel({
        "name": "Test Discord",
        "type": "discord",
        "config": {"webhook_url": "https://discord.com/api/webhooks/test123"},
        "enabled": True
    })
    print(f"✅ Created channel: {discord_channel.name} (ID: {discord_channel.id})")

    pushover_channel = db.add_notification_channel({
        "name": "Test Pushover",
        "type": "pushover",
        "config": {"app_token": "test_app_token", "user_key": "test_user_key"},
        "enabled": True
    })
    print(f"✅ Created channel: {pushover_channel.name} (ID: {pushover_channel.id})")

    slack_channel = db.add_notification_channel({
        "name": "Test Slack",
        "type": "slack",
        "config": {"webhook_url": "https://hooks.slack.com/services/test123"},
        "enabled": True
    })
    print(f"✅ Created channel: {slack_channel.name} (ID: {slack_channel.id})")

    # Step 2: Create alert rules
    print("\n🚨 Step 2: Creating alert rules...")
    print("-" * 60)

    # Alert with only Discord (should be deleted when Discord is removed)
    alert1 = db.add_alert_rule({
        "name": "Alert - Discord Only",
        "trigger_events": ["start", "stop", "die"],
        "trigger_states": ["running", "exited"],
        "notification_channels": [discord_channel.id],
        "cooldown_minutes": 15,
        "enabled": True,
        "containers": [
            {"host_id": host.id, "container_name": container1_name}
        ]
    })
    print(f"✅ Created alert: {alert1.name} with channels {alert1.notification_channels}")

    # Alert with only Pushover (should be deleted when Pushover is removed)
    alert2 = db.add_alert_rule({
        "name": "Alert - Pushover Only",
        "trigger_events": ["start", "stop", "die"],
        "trigger_states": ["running", "exited"],
        "notification_channels": [pushover_channel.id],
        "cooldown_minutes": 15,
        "enabled": True,
        "containers": [
            {"host_id": host.id, "container_name": container2_name}
        ]
    })
    print(f"✅ Created alert: {alert2.name} with channels {alert2.notification_channels}")

    # Alert with Discord + Pushover (should survive Discord deletion)
    alert3 = db.add_alert_rule({
        "name": "Alert - Discord + Pushover",
        "trigger_events": ["start", "stop", "die"],
        "trigger_states": ["running", "exited"],
        "notification_channels": [discord_channel.id, pushover_channel.id],
        "cooldown_minutes": 15,
        "enabled": True,
        "containers": [
            {"host_id": host.id, "container_name": container1_name},
            {"host_id": host.id, "container_name": container2_name}
        ]
    })
    print(f"✅ Created alert: {alert3.name} with channels {alert3.notification_channels}")

    # Alert with Pushover + Slack (should survive Pushover deletion)
    alert4 = db.add_alert_rule({
        "name": "Alert - Pushover + Slack",
        "trigger_events": ["start", "stop", "die"],
        "trigger_states": ["running", "exited"],
        "notification_channels": [pushover_channel.id, slack_channel.id],
        "cooldown_minutes": 15,
        "enabled": True,
        "containers": [
            {"host_id": host.id, "container_name": container1_name}
        ]
    })
    print(f"✅ Created alert: {alert4.name} with channels {alert4.notification_channels}")

    # Alert with all three channels
    alert5 = db.add_alert_rule({
        "name": "Alert - All Three Channels",
        "trigger_events": ["start", "stop", "die"],
        "trigger_states": ["running", "exited"],
        "notification_channels": [discord_channel.id, pushover_channel.id, slack_channel.id],
        "cooldown_minutes": 15,
        "enabled": True,
        "containers": [
            {"host_id": host.id, "container_name": container2_name}
        ]
    })
    print(f"✅ Created alert: {alert5.name} with channels {alert5.notification_channels}")

    # Step 3: Verify initial state
    print("\n📊 Step 3: Verifying initial state...")
    print("-" * 60)

    channels = db.get_notification_channels()
    alerts = db.get_alert_rules()

    print(f"Channels created: {len(channels)}")
    for ch in channels:
        print(f"  - {ch.name} (ID: {ch.id}, Type: {ch.type})")

    print(f"\nAlerts created: {len(alerts)}")
    for alert in alerts:
        print(f"  - {alert.name}: channels {alert.notification_channels}")

    # Step 4: Find dependent alerts before deletion
    print("\n🔍 Step 4: Checking for dependent alerts on Discord channel...")
    print("-" * 60)

    dependent_alerts = db.get_alerts_dependent_on_channel(discord_channel.id)
    print(f"Alerts that would be orphaned by deleting Discord: {[a['name'] for a in dependent_alerts]}")

    # Step 5: Delete Discord channel
    print("\n🗑️  Step 5: Deleting Discord channel...")
    print("-" * 60)
    print("Expected behavior:")
    print("  ✓ 'Alert - Discord Only' should be DELETED (orphaned)")
    print("  ✓ 'Alert - Discord + Pushover' should SURVIVE (has Pushover)")
    print("  ✓ 'Alert - Pushover + Slack' should SURVIVE (no Discord)")
    print("  ✓ 'Alert - All Three Channels' should SURVIVE (has other channels)")
    print()

    # Manually delete dependent alerts and then the channel (simulating backend logic)
    deleted_alerts = []
    for alert_info in dependent_alerts:
        if db.delete_alert_rule(alert_info['id']):
            deleted_alerts.append(alert_info['name'])
            print(f"  🗑️  Deleted orphaned alert: {alert_info['name']}")

    success = db.delete_notification_channel(discord_channel.id)
    if success:
        print(f"✅ Discord channel deleted")
        if deleted_alerts:
            print(f"   Along with {len(deleted_alerts)} orphaned alert(s): {deleted_alerts}")
    else:
        print(f"❌ Failed to delete Discord channel")

    # Step 6: Verify state after Discord deletion
    print("\n📊 Step 6: Verifying state after Discord deletion...")
    print("-" * 60)

    channels_after = db.get_notification_channels()
    alerts_after = db.get_alert_rules()

    print(f"Channels remaining: {len(channels_after)}")
    for ch in channels_after:
        print(f"  - {ch.name} (ID: {ch.id}, Type: {ch.type})")

    print(f"\nAlerts remaining: {len(alerts_after)}")
    for alert in alerts_after:
        print(f"  - {alert.name}: channels {alert.notification_channels}")

    # Validate results
    print("\n✅ Validation Results:")
    print("-" * 60)

    success_flag = True

    # Check that Discord channel is gone
    discord_exists = any(ch.id == discord_channel.id for ch in channels_after)
    if discord_exists:
        print("❌ FAIL: Discord channel still exists")
        success_flag = False
    else:
        print("✅ PASS: Discord channel deleted")

    # Check that "Alert - Discord Only" was deleted
    alert1_exists = any(a.name == "Alert - Discord Only" for a in alerts_after)
    if alert1_exists:
        print("❌ FAIL: 'Alert - Discord Only' still exists (should be deleted)")
        success_flag = False
    else:
        print("✅ PASS: 'Alert - Discord Only' was deleted (orphaned)")

    # Check that multi-channel alerts survived
    alert3_exists = any(a.name == "Alert - Discord + Pushover" for a in alerts_after)
    alert4_exists = any(a.name == "Alert - Pushover + Slack" for a in alerts_after)
    alert5_exists = any(a.name == "Alert - All Three Channels" for a in alerts_after)

    if not alert3_exists:
        print("❌ FAIL: 'Alert - Discord + Pushover' was deleted (should survive)")
        success_flag = False
    else:
        # Check that Discord was removed but alert still has Pushover
        alert3_data = next(a for a in alerts_after if a.name == "Alert - Discord + Pushover")
        if discord_channel.id in alert3_data.notification_channels:
            print("❌ FAIL: Discord still in 'Alert - Discord + Pushover' channels")
            success_flag = False
        elif pushover_channel.id not in alert3_data.notification_channels:
            print("❌ FAIL: Pushover missing from 'Alert - Discord + Pushover' channels")
            success_flag = False
        else:
            print("✅ PASS: 'Alert - Discord + Pushover' survived with Pushover only")

    if not alert4_exists:
        print("❌ FAIL: 'Alert - Pushover + Slack' was deleted (should survive)")
        success_flag = False
    else:
        print("✅ PASS: 'Alert - Pushover + Slack' survived")

    if not alert5_exists:
        print("❌ FAIL: 'Alert - All Three Channels' was deleted (should survive)")
        success_flag = False
    else:
        alert5_data = next(a for a in alerts_after if a.name == "Alert - All Three Channels")
        if discord_channel.id in alert5_data.notification_channels:
            print("❌ FAIL: Discord still in 'Alert - All Three Channels'")
            success_flag = False
        else:
            print("✅ PASS: 'Alert - All Three Channels' survived without Discord")

    # Step 7: Delete Pushover channel
    print("\n🔍 Step 7: Checking for dependent alerts on Pushover channel...")
    print("-" * 60)

    dependent_alerts2 = db.get_alerts_dependent_on_channel(pushover_channel.id)
    print(f"Alerts that would be orphaned by deleting Pushover: {[a['name'] for a in dependent_alerts2]}")

    print("\n🗑️  Step 8: Deleting Pushover channel...")
    print("-" * 60)
    print("Expected behavior:")
    print("  ✓ 'Alert - Pushover Only' should be DELETED (orphaned)")
    print("  ✓ 'Alert - Discord + Pushover' should be DELETED (orphaned, only had Pushover left)")
    print("  ✓ 'Alert - Pushover + Slack' should SURVIVE (has Slack)")
    print("  ✓ 'Alert - All Three Channels' should SURVIVE (has Slack)")
    print()

    deleted_alerts2 = []
    for alert_info in dependent_alerts2:
        if db.delete_alert_rule(alert_info['id']):
            deleted_alerts2.append(alert_info['name'])
            print(f"  🗑️  Deleted orphaned alert: {alert_info['name']}")

    success = db.delete_notification_channel(pushover_channel.id)
    if success:
        print(f"✅ Pushover channel deleted")
        if deleted_alerts2:
            print(f"   Along with {len(deleted_alerts2)} orphaned alert(s): {deleted_alerts2}")

    # Step 9: Final verification
    print("\n📊 Step 9: Final verification...")
    print("-" * 60)

    channels_final = db.get_notification_channels()
    alerts_final = db.get_alert_rules()

    print(f"Channels remaining: {len(channels_final)}")
    for ch in channels_final:
        print(f"  - {ch.name} (ID: {ch.id}, Type: {ch.type})")

    print(f"\nAlerts remaining: {len(alerts_final)}")
    for alert in alerts_final:
        print(f"  - {alert.name}: channels {alert.notification_channels}")

    # Expected: Only Slack channel and 2 alerts remain
    if len(channels_final) != 1 or channels_final[0].type != 'slack':
        print("\n❌ FAIL: Expected only Slack channel to remain")
        success_flag = False
    else:
        print("\n✅ PASS: Only Slack channel remains")

    if len(alerts_final) != 2:
        print(f"❌ FAIL: Expected 2 alerts to remain, got {len(alerts_final)}")
        success_flag = False
    else:
        print("✅ PASS: 2 alerts remain as expected")

    # Cleanup
    print("\n🧹 Final cleanup...")
    for alert in alerts_final:
        db.delete_alert_rule(alert.id)
    for channel in channels_final:
        db.delete_notification_channel(channel.id)
    print("✅ Cleanup complete")

    # Final summary
    print("\n" + "="*60)
    if success_flag:
        print("✅ ALL TESTS PASSED!")
    else:
        print("❌ SOME TESTS FAILED")
    print("="*60 + "\n")

if __name__ == "__main__":
    run_tests()