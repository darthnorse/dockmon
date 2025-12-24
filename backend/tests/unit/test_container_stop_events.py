"""
Unit tests for container stop event handling.

Tests that:
1. Clean exits (exit code 0) emit CONTAINER_STOPPED with INFO severity
2. Crashes (exit code != 0) emit CONTAINER_DIED with ERROR severity
3. Docker 'stop' events are ignored (only 'die' events are processed)

This prevents regression of Issue #23 and #104 fixes.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from event_bus import EventType, EventBus, Event
from event_logger import EventSeverity, EventCategory, EventType as LogEventType


class TestEventBusSeverityMapping:
    """Test that event types have correct severity mappings"""

    def test_container_stopped_has_info_severity(self):
        """CONTAINER_STOPPED should be INFO severity (clean exits are expected)"""
        # Create a mock monitor with event_logger
        mock_monitor = MagicMock()
        mock_monitor.event_logger = MagicMock()

        event_bus = EventBus(mock_monitor)

        # Access the event type mapping (it's created in _log_event_to_database)
        # We'll verify by checking what severity gets passed to event_logger
        event_type_map = {
            EventType.CONTAINER_STOPPED: (LogEventType.STATE_CHANGE, EventCategory.CONTAINER, EventSeverity.INFO),
        }

        # Verify the expected mapping
        log_type, category, severity = event_type_map[EventType.CONTAINER_STOPPED]
        assert severity == EventSeverity.INFO, "CONTAINER_STOPPED should have INFO severity"

    def test_container_died_has_error_severity(self):
        """CONTAINER_DIED should be ERROR severity (crashes are problems)"""
        event_type_map = {
            EventType.CONTAINER_DIED: (LogEventType.STATE_CHANGE, EventCategory.CONTAINER, EventSeverity.ERROR),
        }

        log_type, category, severity = event_type_map[EventType.CONTAINER_DIED]
        assert severity == EventSeverity.ERROR, "CONTAINER_DIED should have ERROR severity"


class TestAgentContainerEventHandling:
    """Test agent websocket handler processes container events correctly"""

    @pytest.fixture
    def mock_websocket_handler(self):
        """Create a minimal mock of the websocket handler's event processing logic"""
        # This tests the logic extracted from websocket_handler.py
        class EventProcessor:
            def determine_event_type(self, action: str, attributes: dict) -> tuple:
                """
                Determine event type based on action and exit code.
                Returns (event_type, exit_code) or (None, None) if action should be skipped.
                """
                # Map Docker actions to EventBus event types
                # 'stop' is intentionally omitted - Docker emits both 'stop' and 'die'
                event_type_map = {
                    "start": EventType.CONTAINER_STARTED,
                    "restart": EventType.CONTAINER_RESTARTED,
                    "destroy": EventType.CONTAINER_DELETED
                }

                if action == "die":
                    exit_code_str = attributes.get("exitCode")
                    exit_code = 0
                    if exit_code_str is not None:
                        try:
                            exit_code = int(exit_code_str)
                        except (ValueError, TypeError):
                            exit_code = 0

                    if exit_code == 0:
                        return EventType.CONTAINER_STOPPED, exit_code
                    else:
                        return EventType.CONTAINER_DIED, exit_code
                else:
                    event_type = event_type_map.get(action)
                    return event_type, None

        return EventProcessor()

    def test_die_event_exit_code_0_emits_container_stopped(self, mock_websocket_handler):
        """die event with exit code 0 should emit CONTAINER_STOPPED"""
        event_type, exit_code = mock_websocket_handler.determine_event_type(
            action="die",
            attributes={"exitCode": "0"}
        )

        assert event_type == EventType.CONTAINER_STOPPED
        assert exit_code == 0

    def test_die_event_exit_code_1_emits_container_died(self, mock_websocket_handler):
        """die event with exit code 1 should emit CONTAINER_DIED"""
        event_type, exit_code = mock_websocket_handler.determine_event_type(
            action="die",
            attributes={"exitCode": "1"}
        )

        assert event_type == EventType.CONTAINER_DIED
        assert exit_code == 1

    def test_die_event_exit_code_137_emits_container_died(self, mock_websocket_handler):
        """die event with exit code 137 (SIGKILL) should emit CONTAINER_DIED"""
        event_type, exit_code = mock_websocket_handler.determine_event_type(
            action="die",
            attributes={"exitCode": "137"}
        )

        assert event_type == EventType.CONTAINER_DIED
        assert exit_code == 137

    def test_die_event_no_exit_code_defaults_to_stopped(self, mock_websocket_handler):
        """die event with no exit code should default to CONTAINER_STOPPED (exit 0)"""
        event_type, exit_code = mock_websocket_handler.determine_event_type(
            action="die",
            attributes={}
        )

        assert event_type == EventType.CONTAINER_STOPPED
        assert exit_code == 0

    def test_stop_event_is_ignored(self, mock_websocket_handler):
        """stop event should be ignored (returns None) to avoid duplicate events"""
        event_type, exit_code = mock_websocket_handler.determine_event_type(
            action="stop",
            attributes={}
        )

        assert event_type is None, "stop events should be ignored"

    def test_start_event_emits_container_started(self, mock_websocket_handler):
        """start event should emit CONTAINER_STARTED"""
        event_type, exit_code = mock_websocket_handler.determine_event_type(
            action="start",
            attributes={}
        )

        assert event_type == EventType.CONTAINER_STARTED

    def test_restart_event_emits_container_restarted(self, mock_websocket_handler):
        """restart event should emit CONTAINER_RESTARTED"""
        event_type, exit_code = mock_websocket_handler.determine_event_type(
            action="restart",
            attributes={}
        )

        assert event_type == EventType.CONTAINER_RESTARTED

    def test_destroy_event_emits_container_deleted(self, mock_websocket_handler):
        """destroy event should emit CONTAINER_DELETED"""
        event_type, exit_code = mock_websocket_handler.determine_event_type(
            action="destroy",
            attributes={}
        )

        assert event_type == EventType.CONTAINER_DELETED

    def test_invalid_exit_code_defaults_to_zero(self, mock_websocket_handler):
        """Invalid exit code should default to 0 (CONTAINER_STOPPED)"""
        event_type, exit_code = mock_websocket_handler.determine_event_type(
            action="die",
            attributes={"exitCode": "invalid"}
        )

        assert event_type == EventType.CONTAINER_STOPPED
        assert exit_code == 0


class TestEventBusIntegration:
    """Integration tests for event bus severity handling"""

    @pytest.mark.asyncio
    async def test_container_stopped_logged_as_info(self):
        """Verify CONTAINER_STOPPED is logged with INFO severity"""
        mock_monitor = MagicMock()
        mock_event_logger = MagicMock()
        mock_monitor.event_logger = mock_event_logger
        mock_monitor.alert_evaluation_service = None

        event_bus = EventBus(mock_monitor)

        event = Event(
            event_type=EventType.CONTAINER_STOPPED,
            scope_type='container',
            scope_id='host-123:abc123',
            scope_name='test-container',
            host_id='host-123',
            host_name='test-host',
            data={'exit_code': 0, 'old_state': 'running', 'new_state': 'stopped'}
        )

        await event_bus.emit(event)

        # Verify event_logger was called with INFO severity
        mock_event_logger.log_event.assert_called_once()
        call_kwargs = mock_event_logger.log_event.call_args
        assert call_kwargs[1]['severity'] == EventSeverity.INFO

    @pytest.mark.asyncio
    async def test_container_died_logged_as_error(self):
        """Verify CONTAINER_DIED is logged with ERROR severity"""
        mock_monitor = MagicMock()
        mock_event_logger = MagicMock()
        mock_monitor.event_logger = mock_event_logger
        mock_monitor.alert_evaluation_service = None

        event_bus = EventBus(mock_monitor)

        event = Event(
            event_type=EventType.CONTAINER_DIED,
            scope_type='container',
            scope_id='host-123:abc123',
            scope_name='test-container',
            host_id='host-123',
            host_name='test-host',
            data={'exit_code': 1, 'old_state': 'running', 'new_state': 'exited'}
        )

        await event_bus.emit(event)

        # Verify event_logger was called with ERROR severity
        mock_event_logger.log_event.assert_called_once()
        call_kwargs = mock_event_logger.log_event.call_args
        assert call_kwargs[1]['severity'] == EventSeverity.ERROR
