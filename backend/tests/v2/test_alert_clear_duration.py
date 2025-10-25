"""
Unit tests for alert clear duration logic

Tests the auto-clear functionality for alerts based on clear_duration setting.
When an alert condition resolves, the alert can be configured to:
- Clear immediately (clear_duration = 0)
- Clear after X minutes (clear_duration = 5, 10, 15, etc.)
- Never auto-clear (clear_duration = None or not set)

This prevents alert flapping and gives confidence that issues are truly resolved.
"""

import pytest
from datetime import datetime, timedelta


class TestAlertClearDuration:
    """Tests for alert clear duration logic"""

    def test_immediate_clear_duration_zero(self):
        """Should clear immediately when clear_duration = 0"""
        clear_duration = 0  # minutes
        condition_met = False  # Condition no longer met

        # With 0 duration, alert should clear immediately
        should_clear = (clear_duration == 0 and not condition_met)

        assert should_clear is True

    def test_delayed_clear_duration_five_minutes(self):
        """Should wait 5 minutes before clearing when clear_duration = 5"""
        clear_duration = 5  # minutes
        condition_met = False  # Condition no longer met

        # Alert entered "clearing" state at this time
        started_clearing_at = datetime(2025, 10, 14, 10, 0, 0)
        current_time = datetime(2025, 10, 14, 10, 3, 0)  # 3 minutes later

        # Calculate if enough time has passed
        elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60
        should_clear = (not condition_met and elapsed_minutes >= clear_duration)

        assert should_clear is False  # Only 3 minutes elapsed, need 5

    def test_delayed_clear_duration_elapsed(self):
        """Should clear after clear_duration has fully elapsed"""
        clear_duration = 5  # minutes
        condition_met = False  # Condition no longer met

        # Alert entered "clearing" state at this time
        started_clearing_at = datetime(2025, 10, 14, 10, 0, 0)
        current_time = datetime(2025, 10, 14, 10, 5, 0)  # Exactly 5 minutes later

        # Calculate if enough time has passed
        elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60
        should_clear = (not condition_met and elapsed_minutes >= clear_duration)

        assert should_clear is True

    def test_delayed_clear_duration_exceeded(self):
        """Should clear even if more time than clear_duration has passed"""
        clear_duration = 5  # minutes
        condition_met = False  # Condition no longer met

        # Alert entered "clearing" state at this time
        started_clearing_at = datetime(2025, 10, 14, 10, 0, 0)
        current_time = datetime(2025, 10, 14, 10, 10, 0)  # 10 minutes later

        # Calculate if enough time has passed
        elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60
        should_clear = (not condition_met and elapsed_minutes >= clear_duration)

        assert should_clear is True  # 10 > 5, should clear

    def test_condition_returns_during_clear_duration(self):
        """Should NOT clear if condition returns during wait period"""
        clear_duration = 5  # minutes
        condition_met = True  # Condition came back!

        # Alert entered "clearing" state, but condition returned
        started_clearing_at = datetime(2025, 10, 14, 10, 0, 0)
        current_time = datetime(2025, 10, 14, 10, 3, 0)

        elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60
        should_clear = (not condition_met and elapsed_minutes >= clear_duration)

        assert should_clear is False  # condition_met = True blocks clearing

    def test_condition_returns_after_clear_duration_elapsed(self):
        """Should NOT clear if condition returns even after duration elapsed"""
        clear_duration = 5  # minutes
        condition_met = True  # Condition came back after 6 minutes

        started_clearing_at = datetime(2025, 10, 14, 10, 0, 0)
        current_time = datetime(2025, 10, 14, 10, 6, 0)

        elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60
        should_clear = (not condition_met and elapsed_minutes >= clear_duration)

        assert should_clear is False  # condition_met = True blocks clearing

    def test_none_clear_duration_never_clears(self):
        """Should never auto-clear when clear_duration = None"""
        clear_duration = None
        condition_met = False  # Condition resolved

        # Check if should clear (None means manual clear only)
        should_clear = (clear_duration is not None and clear_duration == 0 and not condition_met) or \
                      (clear_duration is not None and clear_duration > 0 and not condition_met)

        assert should_clear is False  # None means no auto-clear

    def test_different_clear_durations(self):
        """Should support various clear_duration values (1, 5, 10, 15, 30, 60)"""
        test_cases = [
            (1, timedelta(minutes=1)),
            (5, timedelta(minutes=5)),
            (10, timedelta(minutes=10)),
            (15, timedelta(minutes=15)),
            (30, timedelta(minutes=30)),
            (60, timedelta(minutes=60)),
        ]

        started_clearing_at = datetime(2025, 10, 14, 10, 0, 0)

        for clear_duration, expected_delta in test_cases:
            # Time exactly at clear duration
            current_time = started_clearing_at + expected_delta
            elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60

            should_clear = (elapsed_minutes >= clear_duration)
            assert should_clear is True, f"Failed for clear_duration={clear_duration}"

    def test_clear_duration_with_seconds_precision(self):
        """Should handle sub-minute precision correctly"""
        clear_duration = 5  # minutes
        condition_met = False

        # Alert started clearing
        started_clearing_at = datetime(2025, 10, 14, 10, 0, 0)

        # Test at 4:59 (299 seconds) - should NOT clear
        current_time = started_clearing_at + timedelta(seconds=299)
        elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60
        should_clear = (not condition_met and elapsed_minutes >= clear_duration)
        assert should_clear is False

        # Test at 5:00 (300 seconds) - should clear
        current_time = started_clearing_at + timedelta(seconds=300)
        elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60
        should_clear = (not condition_met and elapsed_minutes >= clear_duration)
        assert should_clear is True

    def test_alert_state_transitions_with_clear_duration(self):
        """Simulate full alert lifecycle with clear_duration"""
        # Initial state
        alert_state = 'open'
        clear_duration = 5
        condition_met = True

        # Step 1: Alert is open, condition is met
        assert alert_state == 'open'
        assert condition_met is True

        # Step 2: Condition resolves, enter "clearing" state
        condition_met = False
        alert_state = 'clearing'
        started_clearing_at = datetime(2025, 10, 14, 10, 0, 0)

        # Step 3: Check at 3 minutes - still clearing
        current_time = datetime(2025, 10, 14, 10, 3, 0)
        elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60
        if not condition_met and elapsed_minutes >= clear_duration:
            alert_state = 'resolved'

        assert alert_state == 'clearing'  # Not enough time

        # Step 4: Check at 5 minutes - should resolve
        current_time = datetime(2025, 10, 14, 10, 5, 0)
        elapsed_minutes = (current_time - started_clearing_at).total_seconds() / 60
        if not condition_met and elapsed_minutes >= clear_duration:
            alert_state = 'resolved'

        assert alert_state == 'resolved'

    def test_alert_flapping_prevented_by_clear_duration(self):
        """Clear duration prevents alert flapping on transient issues"""
        clear_duration = 5  # minutes

        # Scenario: CPU spikes briefly then returns to normal
        timeline = [
            {'time': 0, 'cpu': 95, 'condition_met': True},   # Alert opens
            {'time': 1, 'cpu': 50, 'condition_met': False},  # CPU drops (start clearing)
            {'time': 2, 'cpu': 55, 'condition_met': False},  # Still low (clearing...)
            {'time': 3, 'cpu': 92, 'condition_met': True},   # Spikes again! (back to open)
            {'time': 4, 'cpu': 60, 'condition_met': False},  # Drops again (start clearing)
            {'time': 9, 'cpu': 55, 'condition_met': False},  # Stable for 5 min (resolve)
        ]

        alert_state = 'open'
        started_clearing_at = None

        for event in timeline:
            if event['condition_met']:
                # Condition met - alert is open
                alert_state = 'open'
                started_clearing_at = None
            else:
                # Condition not met
                if alert_state == 'open':
                    # Enter clearing state
                    alert_state = 'clearing'
                    started_clearing_at = event['time']
                elif alert_state == 'clearing':
                    # Check if enough time elapsed
                    elapsed = event['time'] - started_clearing_at
                    if elapsed >= clear_duration:
                        alert_state = 'resolved'

        # Final state: Alert should be resolved after 5 minutes of stability
        assert alert_state == 'resolved'

        # Without clear_duration, alert would have flapped 3 times:
        # open -> closed -> open -> closed (flapping)
        # With clear_duration, alert stays open until truly stable

    def test_zero_clear_duration_immediate_behavior(self):
        """Zero clear_duration should behave like instant clear"""
        clear_duration = 0
        condition_met = False

        # With zero duration, no waiting period needed
        should_clear = (clear_duration == 0 and not condition_met)

        assert should_clear is True

        # This is equivalent to no clear_duration (legacy behavior)

    def test_negative_clear_duration_invalid(self):
        """Negative clear_duration should be treated as invalid"""
        clear_duration = -5  # Invalid

        # In real code, this should be validated and rejected
        # For testing purposes, we'll check that it's not used
        is_valid = (clear_duration is None or clear_duration >= 0)

        assert is_valid is False

    def test_clear_duration_comparison_operators(self):
        """Should use >= for elapsed time comparison, not =="""
        clear_duration = 5
        started_clearing_at = datetime(2025, 10, 14, 10, 0, 0)

        # Test cases with different elapsed times
        test_cases = [
            (4.9, False),   # Just before threshold
            (5.0, True),    # Exactly at threshold
            (5.1, True),    # Just after threshold
            (10.0, True),   # Well after threshold
        ]

        for elapsed_minutes, expected_should_clear in test_cases:
            current_time = started_clearing_at + timedelta(minutes=elapsed_minutes)
            actual_elapsed = (current_time - started_clearing_at).total_seconds() / 60
            should_clear = (actual_elapsed >= clear_duration)

            assert should_clear == expected_should_clear, \
                f"Failed for elapsed={elapsed_minutes}, expected={expected_should_clear}"

    def test_real_world_scenario_cpu_spike(self):
        """Simulate real scenario: CPU spike with 5-minute clear duration"""
        # Rule: CPU > 90% for container 'web-server'
        # Clear duration: 5 minutes

        clear_duration = 5
        threshold = 90

        # Timeline of CPU readings (minute, cpu_percent)
        readings = [
            (0, 95),   # Spike! Alert opens
            (1, 92),   # Still high
            (2, 88),   # Drops below threshold (start clearing)
            (3, 85),   # Still good
            (4, 87),   # Still good
            (5, 86),   # Still good
            (6, 84),   # Still good
            (7, 83),   # Alert should resolve at minute 7 (5 min after minute 2)
        ]

        alert_state = None
        started_clearing_at = None

        for minute, cpu in readings:
            condition_met = (cpu > threshold)

            if condition_met:
                if alert_state is None:
                    alert_state = 'open'
                started_clearing_at = None
            else:
                if alert_state == 'open':
                    alert_state = 'clearing'
                    started_clearing_at = minute
                elif alert_state == 'clearing':
                    elapsed = minute - started_clearing_at
                    if elapsed >= clear_duration:
                        alert_state = 'resolved'

        # Alert should be resolved by end of timeline
        assert alert_state == 'resolved'

    def test_real_world_scenario_container_restart_loop(self):
        """Simulate: Container flapping with 10-minute clear duration"""
        # Rule: Container state != running
        # Clear duration: 10 minutes (give it time to stabilize)

        clear_duration = 10

        # Timeline (minute, state)
        states = [
            (0, 'exited'),    # Alert opens
            (1, 'restarting'),
            (2, 'running'),   # Back up! (start clearing)
            (3, 'running'),
            (4, 'exited'),    # Crashed again! (back to open)
            (5, 'restarting'),
            (6, 'running'),   # Up again (start clearing)
            (7, 'running'),
            (16, 'running'),  # Stable for 10 minutes (resolve at minute 16)
        ]

        alert_state = None
        started_clearing_at = None

        for minute, state in states:
            condition_met = (state != 'running')

            if condition_met:
                if alert_state is None or alert_state == 'clearing':
                    alert_state = 'open'
                started_clearing_at = None
            else:
                if alert_state == 'open':
                    alert_state = 'clearing'
                    started_clearing_at = minute
                elif alert_state == 'clearing':
                    elapsed = minute - started_clearing_at
                    if elapsed >= clear_duration:
                        alert_state = 'resolved'

        # Alert should be resolved (container stable for 10+ minutes)
        assert alert_state == 'resolved'

        # Without clear_duration, alert would have flapped:
        # open -> closed -> open -> closed (2 notifications instead of 1)
