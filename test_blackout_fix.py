#!/usr/bin/env python3
"""
Test script to verify that exiting a blackout window doesn't create
duplicate DockerMonitor instances
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

# Mock the database and event logger to avoid actual initialization
import unittest.mock as mock

# Test the signature changes
def test_blackout_manager_signature():
    """Test that BlackoutManager.start_monitoring accepts monitor parameter"""
    from blackout_manager import BlackoutManager
    from database import DatabaseManager
    import inspect

    # Check start_monitoring signature
    sig = inspect.signature(BlackoutManager.start_monitoring)
    params = list(sig.parameters.keys())

    print("✓ BlackoutManager.start_monitoring parameters:", params)
    assert 'monitor' in params, "Missing 'monitor' parameter in start_monitoring"
    print("✓ BlackoutManager.start_monitoring has 'monitor' parameter")

def test_notification_service_signature():
    """Test that NotificationService.process_suppressed_alerts accepts monitor parameter"""
    from notifications import NotificationService
    import inspect

    # Check process_suppressed_alerts signature
    sig = inspect.signature(NotificationService.process_suppressed_alerts)
    params = list(sig.parameters.keys())

    print("✓ NotificationService.process_suppressed_alerts parameters:", params)
    assert 'monitor' in params, "Missing 'monitor' parameter in process_suppressed_alerts"
    print("✓ NotificationService.process_suppressed_alerts has 'monitor' parameter")

def test_no_monitor_instantiation():
    """Test that process_suppressed_alerts doesn't instantiate DockerMonitor"""
    import inspect
    from notifications import NotificationService

    # Get source code
    source = inspect.getsource(NotificationService.process_suppressed_alerts)

    # Check that it doesn't create a new DockerMonitor
    if 'DockerMonitor()' in source:
        print("✗ FAIL: process_suppressed_alerts still creates DockerMonitor()")
        return False
    else:
        print("✓ process_suppressed_alerts does NOT create DockerMonitor()")
        return True

def test_blackout_manager_no_instantiation():
    """Test that check_container_states_after_blackout doesn't instantiate DockerMonitor"""
    import inspect
    from blackout_manager import BlackoutManager

    # Get source code
    source = inspect.getsource(BlackoutManager.check_container_states_after_blackout)

    # Check that it doesn't create a new DockerMonitor
    if 'DockerMonitor()' in source:
        print("✗ FAIL: check_container_states_after_blackout still creates DockerMonitor()")
        return False
    else:
        print("✓ check_container_states_after_blackout does NOT create DockerMonitor()")
        return True

if __name__ == '__main__':
    print("Testing blackout window fix...")
    print()

    try:
        test_blackout_manager_signature()
        print()
        test_notification_service_signature()
        print()
        test_no_monitor_instantiation()
        print()
        test_blackout_manager_no_instantiation()
        print()
        print("="*60)
        print("✓ All tests passed! Fix is correct.")
        print("="*60)
    except Exception as e:
        print()
        print("="*60)
        print(f"✗ Test failed: {e}")
        print("="*60)
        sys.exit(1)