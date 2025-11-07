"""
Unit tests for exit code-based event handling (Issue #23)

Tests that Docker 'die' events with exit code 0 are treated as clean stops
while non-zero exit codes are treated as container crashes/errors.
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from event_bus import EventType, Event


class TestExitCodeEventHandling:
    """Test that exit codes determine event type and severity"""

    def test_exit_code_zero_generates_stopped_event(self):
        """Exit code 0 should generate CONTAINER_STOPPED event"""
        # Simulate Docker 'die' event with exit code 0
        docker_event = {
            'Action': 'die',
            'Actor': {
                'Attributes': {
                    'exitCode': '0',  # Clean exit
                    'name': 'test-container'
                },
                'ID': '1234567890ab'
            },
            'Type': 'container',
            'status': 'die'
        }

        # Mock monitor's event emission
        mock_event_bus = Mock()

        # This will fail until we implement the fix
        # Expected: Event type should be CONTAINER_STOPPED
        # Actual: Currently emits CONTAINER_DIED for all 'die' events

        # TODO: Add actual implementation test once monitor code is modified
        # For now, this documents expected behavior
        pytest.fail("Implementation pending - exit code 0 should emit CONTAINER_STOPPED")

    def test_exit_code_nonzero_generates_died_event(self):
        """Exit code != 0 should generate CONTAINER_DIED event"""
        # Simulate Docker 'die' event with exit code 1 (error)
        docker_event = {
            'Action': 'die',
            'Actor': {
                'Attributes': {
                    'exitCode': '1',  # Error exit
                    'name': 'test-container'
                },
                'ID': '1234567890ab'
            },
            'Type': 'container',
            'status': 'die'
        }

        # This will fail until we implement the fix
        # Expected: Event type should be CONTAINER_DIED
        # Actual: Currently emits CONTAINER_DIED (correct behavior, should continue)

        pytest.fail("Implementation pending - exit code != 0 should emit CONTAINER_DIED")

    def test_missing_exit_code_generates_died_event(self):
        """Missing exit code should generate CONTAINER_DIED (safe fallback)"""
        # Simulate Docker 'die' event without exit code
        docker_event = {
            'Action': 'die',
            'Actor': {
                'Attributes': {
                    'name': 'test-container'
                    # No exitCode field
                },
                'ID': '1234567890ab'
            },
            'Type': 'container',
            'status': 'die'
        }

        # This will fail until we implement the fix
        # Expected: Event type should be CONTAINER_DIED (safe default)
        # Actual: Currently emits CONTAINER_DIED (correct behavior, should continue)

        pytest.fail("Implementation pending - missing exit code should default to CONTAINER_DIED")

    def test_stopped_event_message_includes_exit_code(self):
        """CONTAINER_STOPPED message should include exit code when present"""
        from event_bus import EventBus

        # Create test event with exit code
        event = Event(
            event_type=EventType.CONTAINER_STOPPED,
            scope_type='container',
            scope_name='test-container',
            scope_id='host123:1234567890ab',
            host_id='host123',
            host_name='test-host',
            data={'exit_code': '0'}
        )

        # Mock monitor
        mock_monitor = Mock()
        event_bus = EventBus(mock_monitor)

        # Generate message
        title, message = event_bus._generate_event_message(event)

        # This will fail until we implement the fix
        # Expected: Message includes "exit code 0"
        # Actual: Currently shows "changed state: unknown → stopped"

        assert 'exit code' in message.lower(), f"Expected exit code in message, got: {message}"
        assert '0' in message, f"Expected exit code value in message, got: {message}"
        pytest.fail("Implementation pending - CONTAINER_STOPPED should include exit code in message")

    def test_stopped_event_without_exit_code_uses_default_message(self):
        """CONTAINER_STOPPED without exit code should use default state change message"""
        from event_bus import EventBus

        # Create test event without exit code (from 'stop' action, not 'die')
        event = Event(
            event_type=EventType.CONTAINER_STOPPED,
            scope_type='container',
            scope_name='test-container',
            scope_id='host123:1234567890ab',
            host_id='host123',
            host_name='test-host',
            data={'old_state': 'running', 'new_state': 'stopped'}
        )

        # Mock monitor
        mock_monitor = Mock()
        event_bus = EventBus(mock_monitor)

        # Generate message
        title, message = event_bus._generate_event_message(event)

        # This should continue to work as before (state change message)
        assert 'changed state' in message.lower() or 'running' in message.lower()
        pytest.fail("Implementation pending - verify existing CONTAINER_STOPPED behavior preserved")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
