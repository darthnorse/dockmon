#!/usr/bin/env python3
"""
Comprehensive test script for DockMon event logging system
Tests all aspects of event logging, viewing, and management
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timedelta
from database import DatabaseManager, EventLog
from event_logger import EventLogger, EventContext, EventCategory, EventType, EventSeverity
from notifications import NotificationService, AlertEvent

async def test_event_logger_service():
    """Test the event logger service"""
    print("🔧 Testing Event Logger Service...")

    db = DatabaseManager(db_path="test_event_dockmon.db")
    event_logger = EventLogger(db)

    try:
        # Start the event logger
        await event_logger.start()

        print("\n1. Testing basic event logging...")

        # Test system event
        event_logger.log_system_event(
            "Test System Startup",
            "Testing system event logging functionality",
            EventSeverity.INFO,
            EventType.STARTUP
        )

        # Test container state change
        event_logger.log_container_state_change(
            container_name="test-nginx",
            container_id="abc123",
            host_name="Docker Host 1",
            host_id="host1",
            old_state="running",
            new_state="stopped",
            triggered_by="user"
        )

        # Test container action
        event_logger.log_container_action(
            action="restart",
            container_name="test-nginx",
            container_id="abc123",
            host_name="Docker Host 1",
            host_id="host1",
            success=True,
            triggered_by="user",
            duration_ms=2500
        )

        # Test auto-restart attempt
        correlation_id = event_logger.create_correlation_id()
        event_logger.log_auto_restart_attempt(
            container_name="test-nginx",
            container_id="abc123",
            host_name="Docker Host 1",
            host_id="host1",
            attempt=1,
            max_attempts=3,
            success=False,
            error_message="Container failed to start",
            correlation_id=correlation_id
        )

        # Test host connection
        event_logger.log_host_connection(
            host_name="Docker Host 1",
            host_id="host1",
            host_url="tcp://192.168.1.100:2376",
            connected=True
        )

        # Test alert triggered
        event_logger.log_alert_triggered(
            rule_name="Container Down Alert",
            rule_id="rule1",
            container_name="test-nginx",
            container_id="abc123",
            host_name="Docker Host 1",
            host_id="host1",
            old_state="running",
            new_state="stopped",
            channels_notified=2,
            total_channels=3,
            correlation_id=correlation_id
        )

        # Test notification sent
        event_logger.log_notification_sent(
            channel_name="Discord Alerts",
            channel_type="discord",
            success=True,
            container_name="test-nginx",
            correlation_id=correlation_id
        )

        # Wait for async processing
        await asyncio.sleep(1)

        print("✅ Basic event logging completed")

        print("\n2. Testing database queries...")

        # Test getting all events
        events, total = db.get_events(limit=50)
        print(f"✅ Retrieved {len(events)} events (total: {total})")

        # Test filtering by category
        container_events, _ = db.get_events(category="container", limit=10)
        print(f"✅ Container events: {len(container_events)}")

        # Test filtering by severity
        error_events, _ = db.get_events(severity="error", limit=10)
        print(f"✅ Error events: {len(error_events)}")

        # Test correlation tracking
        correlated_events = db.get_events_by_correlation(correlation_id)
        print(f"✅ Correlated events: {len(correlated_events)}")

        # Test container-specific events
        container_events, _ = db.get_events(container_id="abc123", limit=10)
        print(f"✅ Events for container abc123: {len(container_events)}")

        # Test host-specific events
        host_events, _ = db.get_events(host_id="host1", limit=10)
        print(f"✅ Events for host1: {len(host_events)}")

        # Test search functionality
        search_events, _ = db.get_events(search="nginx", limit=10)
        print(f"✅ Search results for 'nginx': {len(search_events)}")

        print("\n3. Testing event statistics...")
        stats = db.get_event_statistics()
        print(f"✅ Event statistics:")
        print(f"   Total events: {stats['total_events']}")
        print(f"   Categories: {stats['category_counts']}")
        print(f"   Severities: {stats['severity_counts']}")

        print("\n4. Testing event cleanup...")
        # Add some old events for testing
        old_event_data = {
            'category': 'system',
            'event_type': 'test',
            'severity': 'info',
            'title': 'Old Test Event',
            'message': 'This is an old event for testing cleanup',
            'timestamp': datetime.now() - timedelta(days=40)
        }
        db.add_event(old_event_data)

        # Run cleanup
        deleted_count = db.cleanup_old_events(days=30)
        print(f"✅ Cleaned up {deleted_count} old events")

    except Exception as e:
        print(f"❌ Error in event logger tests: {e}")
    finally:
        await event_logger.stop()

async def test_performance_timer():
    """Test the performance timer context manager"""
    print("\n🚀 Testing Performance Timer...")

    db = DatabaseManager(db_path="test_event_dockmon.db")
    event_logger = EventLogger(db)

    try:
        await event_logger.start()

        context = EventContext(
            host_id="host1",
            host_name="Test Host",
            container_id="perf123",
            container_name="performance-test"
        )

        # Test successful operation
        from event_logger import PerformanceTimer
        with PerformanceTimer(event_logger, "Test Operation Success", context):
            await asyncio.sleep(0.1)  # Simulate work

        # Test failed operation
        try:
            with PerformanceTimer(event_logger, "Test Operation Failure", context):
                await asyncio.sleep(0.05)  # Simulate some work
                raise ValueError("Simulated error")
        except ValueError:
            pass  # Expected

        await asyncio.sleep(0.5)  # Wait for logging

        # Check performance events were logged
        perf_events, _ = db.get_events(event_type="performance", limit=5)
        error_events, _ = db.get_events(event_type="error", limit=5)

        print(f"✅ Performance events logged: {len(perf_events)}")
        print(f"✅ Error events logged: {len(error_events)}")

        if perf_events:
            event = perf_events[0]
            print(f"   - Duration: {event.duration_ms}ms")
            print(f"   - Title: {event.title}")

    except Exception as e:
        print(f"❌ Error in performance timer tests: {e}")
    finally:
        await event_logger.stop()

def test_database_schema():
    """Test database schema and operations"""
    print("\n💾 Testing Database Schema...")

    try:
        db = DatabaseManager(db_path="test_event_dockmon.db")

        # Test event creation with all fields
        event_data = {
            'correlation_id': 'test-correlation-123',
            'category': 'container',
            'event_type': 'state_change',
            'severity': 'warning',
            'host_id': 'test-host',
            'host_name': 'Test Host',
            'container_id': 'test-container',
            'container_name': 'test-app',
            'title': 'Container State Changed',
            'message': 'Container test-app changed from running to stopped',
            'old_state': 'running',
            'new_state': 'stopped',
            'triggered_by': 'system',
            'details': {'reason': 'test', 'exit_code': 0},
            'duration_ms': 1500,
            'timestamp': datetime.now()
        }

        # Add event
        event = db.add_event(event_data)
        print(f"✅ Created event with ID: {event.id}")

        # Test retrieval
        retrieved = db.get_event_by_id(event.id)
        assert retrieved is not None
        assert retrieved.title == event_data['title']
        print(f"✅ Retrieved event: {retrieved.title}")

        # Test pagination
        events, total = db.get_events(limit=5, offset=0)
        print(f"✅ Pagination test: {len(events)} events, total: {total}")

        # Test date range filtering
        yesterday = datetime.now() - timedelta(days=1)
        tomorrow = datetime.now() + timedelta(days=1)

        events, total = db.get_events(
            start_date=yesterday,
            end_date=tomorrow,
            limit=10
        )
        print(f"✅ Date range filter: {len(events)} events")

        print("✅ Database schema tests completed")

    except Exception as e:
        print(f"❌ Error in database schema tests: {e}")

def print_sample_events():
    """Print sample events for manual verification"""
    print("\n📋 Sample Events Log:")

    db = DatabaseManager(db_path="test_event_dockmon.db")

    try:
        events, _ = db.get_events(limit=10)

        for event in events[:5]:  # Show last 5 events
            severity_emoji = {
                'debug': '🐛',
                'info': 'ℹ️',
                'warning': '⚠️',
                'error': '❌',
                'critical': '🚨'
            }.get(event.severity, '📝')

            category_emoji = {
                'container': '🐳',
                'host': '🖥️',
                'system': '⚙️',
                'alert': '🔔',
                'notification': '📧'
            }.get(event.category, '📄')

            print(f"{severity_emoji} {category_emoji} [{event.timestamp.strftime('%H:%M:%S')}] {event.title}")
            if event.message:
                print(f"    {event.message}")
            if event.old_state and event.new_state:
                print(f"    State: {event.old_state} → {event.new_state}")
            if event.duration_ms:
                print(f"    Duration: {event.duration_ms}ms")
            print()

    except Exception as e:
        print(f"❌ Error printing sample events: {e}")

async def main():
    """Main test function"""
    print("🐳 DockMon Event Logging System Test")
    print("=" * 50)

    # Run all tests
    test_database_schema()
    await test_event_logger_service()
    await test_performance_timer()
    print_sample_events()

    print("\n🎉 Event logging system test completed!")
    print("\nAPI Endpoints Available:")
    print("• GET /api/events - List all events with filtering")
    print("• GET /api/events/{id} - Get specific event")
    print("• GET /api/events/correlation/{id} - Get correlated events")
    print("• GET /api/events/statistics - Get event statistics")
    print("• GET /api/events/container/{id} - Container events")
    print("• GET /api/events/host/{id} - Host events")
    print("• DELETE /api/events/cleanup?days=30 - Cleanup old events")

if __name__ == "__main__":
    asyncio.run(main())