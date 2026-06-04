"""
Unit tests for the container_restarted discriminator flag in the EventBus.

A Docker 'restart' surfaces as CONTAINER_RESTARTED with new_state == "running"
- indistinguishable from a plain start by new_state alone. The EventBus tags
restart events with container_restarted=True so the alert engine can match the
container_restarted rule. This is the single chokepoint both the local/Go event
path and the agent path funnel through.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from event_bus import EventType, EventBus, Event


def _make_bus_with_capture():
    """EventBus whose alert evaluation captures the event_data it receives."""
    mock_monitor = MagicMock()
    mock_monitor.event_logger = MagicMock()
    mock_monitor.alert_evaluation_service = MagicMock()
    mock_monitor.alert_evaluation_service.handle_container_event = AsyncMock()
    return EventBus(mock_monitor), mock_monitor


def _event(event_type):
    return Event(
        event_type=event_type,
        scope_type='container',
        scope_id='host-123:abc123def456',
        scope_name='test-container',
        host_id='host-123',
        host_name='test-host',
        data={'old_state': 'running', 'new_state': 'running'},
    )


class TestContainerRestartedFlag:

    @pytest.mark.asyncio
    async def test_restarted_event_sets_flag(self):
        """CONTAINER_RESTARTED must pass container_restarted=True to alert eval."""
        bus, monitor = _make_bus_with_capture()

        await bus.emit(_event(EventType.CONTAINER_RESTARTED))

        monitor.alert_evaluation_service.handle_container_event.assert_called_once()
        event_data = monitor.alert_evaluation_service.handle_container_event.call_args.kwargs['event_data']
        assert event_data.get('container_restarted') is True

    @pytest.mark.asyncio
    async def test_started_event_does_not_set_flag(self):
        """A plain CONTAINER_STARTED must NOT carry the restart flag."""
        bus, monitor = _make_bus_with_capture()

        await bus.emit(_event(EventType.CONTAINER_STARTED))

        monitor.alert_evaluation_service.handle_container_event.assert_called_once()
        event_data = monitor.alert_evaluation_service.handle_container_event.call_args.kwargs['event_data']
        assert event_data.get('container_restarted') is not True
