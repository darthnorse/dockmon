#!/usr/bin/env python3
import requests
import json
import time
from typing import Dict, List

API_BASE = "http://localhost:8080"
SESSION = requests.Session()
SESSION.verify = False

def login():
    """Login to get session cookie"""
    print("🔐 Logging in...")
    response = SESSION.post(
        f"{API_BASE}/api/auth/login",
        json={"username": "admin", "password": "test1234"}
    )
    if response.status_code == 200:
        print("✅ Login successful\n")
        return True
    else:
        print(f"❌ Login failed: {response.status_code}")
        return False

def get_hosts() -> List[Dict]:
    """Get all hosts"""
    response = SESSION.get(f"{API_BASE}/api/hosts")
    if response.status_code == 200:
        return response.json()
    return []

def create_notification_channel(name: str, channel_type: str, config: Dict) -> Dict:
    """Create a notification channel"""
    data = {
        "name": name,
        "type": channel_type,
        "config": config,
        "enabled": True
    }
    response = SESSION.post(
        f"{API_BASE}/api/notifications/channels",
        json=data
    )
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Created channel: {name} (ID: {result['id']})")
        return result
    else:
        print(f"❌ Failed to create channel {name}: {response.status_code} - {response.text}")
        return {}

def get_notification_channels() -> List[Dict]:
    """Get all notification channels"""
    response = SESSION.get(f"{API_BASE}/api/notifications/channels")
    if response.status_code == 200:
        return response.json()
    return []

def create_alert_rule(name: str, channel_ids: List[int], containers: List[Dict]) -> Dict:
    """Create an alert rule"""
    data = {
        "name": name,
        "trigger_events": ["start", "stop", "kill"],
        "trigger_states": ["running", "exited"],
        "notification_channels": channel_ids,
        "cooldown_minutes": 15,
        "enabled": True,
        "containers": containers
    }
    response = SESSION.post(
        f"{API_BASE}/api/alerts",
        json=data
    )
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Created alert: {name} with channels {channel_ids}")
        return result
    else:
        print(f"❌ Failed to create alert {name}: {response.status_code} - {response.text}")
        return {}

def get_alert_rules() -> List[Dict]:
    """Get all alert rules"""
    response = SESSION.get(f"{API_BASE}/api/alerts")
    if response.status_code == 200:
        return response.json()
    return []

def delete_notification_channel(channel_id: int) -> Dict:
    """Delete a notification channel"""
    response = SESSION.delete(f"{API_BASE}/api/notifications/channels/{channel_id}")
    if response.status_code == 200:
        return response.json()
    else:
        print(f"❌ Failed to delete channel {channel_id}: {response.status_code}")
        return {}

def cleanup():
    """Clean up all test data"""
    print("\n🧹 Cleaning up test data...")

    # Delete all alert rules
    alerts = get_alert_rules()
    for alert in alerts:
        response = SESSION.delete(f"{API_BASE}/api/alerts/{alert['id']}")
        if response.status_code == 200:
            print(f"  Deleted alert: {alert['name']}")

    # Delete all notification channels
    channels = get_notification_channels()
    for channel in channels:
        response = SESSION.delete(f"{API_BASE}/api/notifications/channels/{channel['id']}")
        if response.status_code == 200:
            print(f"  Deleted channel: {channel['name']}")

    print("✅ Cleanup complete\n")

def run_tests():
    """Run comprehensive tests for channel deletion safeguards"""

    print("\n" + "="*60)
    print("🧪 TESTING CHANNEL DELETION SAFEGUARDS")
    print("="*60 + "\n")

    if not login():
        return

    # Cleanup any existing test data
    cleanup()

    # Get hosts and containers
    print("📋 Getting hosts and containers...")
    hosts = get_hosts()
    if len(hosts) < 1:
        print("❌ Need at least 1 host")
        return

    # Get all containers
    response = SESSION.get(f"{API_BASE}/api/containers")
    if response.status_code != 200:
        print("❌ Failed to get containers")
        return

    containers = response.json()
    if len(containers) < 2:
        print(f"❌ Need at least 2 containers, found {len(containers)}")
        return

    print(f"✅ Found {len(hosts)} host(s) with {len(containers)} total containers\n")

    # Use first two containers for testing
    container1 = {
        "host_id": containers[0]['host_id'],
        "container_name": containers[0]['name']
    }
    container2 = {
        "host_id": containers[1]['host_id'],
        "container_name": containers[1]['name']
    }

    print(f"   Using containers: {container1['container_name']} and {container2['container_name']}")

    # Step 1: Create notification channels
    print("📢 Step 1: Creating notification channels...")
    print("-" * 60)

    discord_channel = create_notification_channel(
        "Test Discord",
        "discord",
        {"webhook_url": "https://discord.com/api/webhooks/test123"}
    )

    pushover_channel = create_notification_channel(
        "Test Pushover",
        "pushover",
        {"app_token": "azgxk8wa4zp6y5qkqwc8z9fs89d1h3", "user_key": "u2jmqp8xk2w3z8r7y5b3m6k9v4c7x1"}
    )

    time.sleep(2)

    # Step 2: Create alert rules
    print("\n🚨 Step 2: Creating alert rules...")
    print("-" * 60)

    # Alert with only Discord (should be deleted when Discord is removed)
    alert1 = create_alert_rule(
        "Alert - Discord Only",
        [discord_channel['id']],
        [container1]
    )

    # Alert with only Pushover (should be deleted when Pushover is removed)
    alert2 = create_alert_rule(
        "Alert - Pushover Only",
        [pushover_channel['id']],
        [container2]
    )

    # Alert with Discord + Pushover (should survive Discord deletion, have Discord removed)
    alert3 = create_alert_rule(
        "Alert - Discord + Pushover",
        [discord_channel['id'], pushover_channel['id']],
        [container1, container2]
    )

    time.sleep(1)

    # Step 3: Verify initial state
    print("\n📊 Step 3: Verifying initial state...")
    print("-" * 60)

    channels = get_notification_channels()
    alerts = get_alert_rules()

    print(f"Channels created: {len(channels)}")
    for ch in channels:
        print(f"  - {ch['name']} (ID: {ch['id']}, Type: {ch['type']})")

    print(f"\nAlerts created: {len(alerts)}")
    for alert in alerts:
        print(f"  - {alert['name']}: channels {alert['notification_channels']}")

    # Step 4: Test deleting Discord channel
    print("\n🗑️  Step 4: Deleting Discord channel...")
    print("-" * 60)
    print("Expected behavior:")
    print("  ✓ 'Alert - Discord Only' should be DELETED (orphaned)")
    print("  ✓ 'Alert - Discord + Pushover' should SURVIVE (has Pushover)")
    print("  ✓ 'Alert - Pushover + Slack' should SURVIVE (no Discord)")
    print("  ✓ 'Alert - All Three Channels' should SURVIVE (has other channels)")
    print()

    result = delete_notification_channel(discord_channel['id'])
    print(f"Delete response: {json.dumps(result, indent=2)}")

    deleted_alert_names = result.get('deleted_alerts', [])
    print(f"\n🗑️  Alerts deleted: {deleted_alert_names}")

    time.sleep(1)

    # Step 5: Verify state after Discord deletion
    print("\n📊 Step 5: Verifying state after Discord deletion...")
    print("-" * 60)

    channels_after = get_notification_channels()
    alerts_after = get_alert_rules()

    print(f"Channels remaining: {len(channels_after)}")
    for ch in channels_after:
        print(f"  - {ch['name']} (ID: {ch['id']}, Type: {ch['type']})")

    print(f"\nAlerts remaining: {len(alerts_after)}")
    for alert in alerts_after:
        print(f"  - {alert['name']}: channels {alert['notification_channels']}")

    # Validate results
    print("\n✅ Validation Results:")
    print("-" * 60)

    success = True

    # Check that Discord channel is gone
    discord_exists = any(ch['id'] == discord_channel['id'] for ch in channels_after)
    if discord_exists:
        print("❌ FAIL: Discord channel still exists")
        success = False
    else:
        print("✅ PASS: Discord channel deleted")

    # Check that "Alert - Discord Only" was deleted
    alert1_exists = any(a['name'] == "Alert - Discord Only" for a in alerts_after)
    if alert1_exists:
        print("❌ FAIL: 'Alert - Discord Only' still exists (should be deleted)")
        success = False
    else:
        print("✅ PASS: 'Alert - Discord Only' was deleted (orphaned)")

    # Check that multi-channel alert survived
    alert3_exists = any(a['name'] == "Alert - Discord + Pushover" for a in alerts_after)

    if not alert3_exists:
        print("❌ FAIL: 'Alert - Discord + Pushover' was deleted (should survive)")
        success = False
    else:
        # Check that Discord was removed from channels
        alert3_data = next(a for a in alerts_after if a['name'] == "Alert - Discord + Pushover")
        if discord_channel['id'] in alert3_data['notification_channels']:
            print("❌ FAIL: Discord still in 'Alert - Discord + Pushover' channels")
            success = False
        elif pushover_channel['id'] not in alert3_data['notification_channels']:
            print("❌ FAIL: Pushover missing from 'Alert - Discord + Pushover' channels")
            success = False
        else:
            print("✅ PASS: 'Alert - Discord + Pushover' survived with Pushover only")

    # Step 6: Test deleting Pushover channel (should delete remaining alerts)
    print("\n🗑️  Step 6: Deleting Pushover channel...")
    print("-" * 60)
    print("Expected behavior:")
    print("  ✓ 'Alert - Pushover Only' should be DELETED (orphaned)")
    print("  ✓ 'Alert - Discord + Pushover' should be DELETED (orphaned, only had Pushover left)")
    print()

    result2 = delete_notification_channel(pushover_channel['id'])
    print(f"Delete response: {json.dumps(result2, indent=2)}")

    deleted_alert_names2 = result2.get('deleted_alerts', [])
    print(f"\n🗑️  Alerts deleted: {deleted_alert_names2}")

    time.sleep(1)

    # Step 7: Final verification
    print("\n📊 Step 7: Final verification...")
    print("-" * 60)

    channels_final = get_notification_channels()
    alerts_final = get_alert_rules()

    print(f"Channels remaining: {len(channels_final)}")
    for ch in channels_final:
        print(f"  - {ch['name']} (ID: {ch['id']}, Type: {ch['type']})")

    print(f"\nAlerts remaining: {len(alerts_final)}")
    for alert in alerts_final:
        print(f"  - {alert['name']}: channels {alert['notification_channels']}")

    # Expected: No channels and no alerts remain
    if len(channels_final) != 0:
        print(f"\n❌ FAIL: Expected no channels to remain, got {len(channels_final)}")
        success = False
    else:
        print("\n✅ PASS: No channels remain")

    if len(alerts_final) != 0:
        print(f"❌ FAIL: Expected no alerts to remain, got {len(alerts_final)}")
        success = False
    else:
        print("✅ PASS: No alerts remain as expected")

    # Cleanup
    cleanup()

    # Final summary
    print("\n" + "="*60)
    if success:
        print("✅ ALL TESTS PASSED!")
    else:
        print("❌ SOME TESTS FAILED")
    print("="*60 + "\n")

if __name__ == "__main__":
    # Disable SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    run_tests()