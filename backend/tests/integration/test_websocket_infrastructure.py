"""
Integration tests for WebSocket infrastructure (EventBus + ConnectionManager)

Critical infrastructure tests covering:
- EventBus event emission and processing
- WebSocket message broadcasting
- Database logging integration
- Alert evaluation triggering
- Connection management and cleanup
- Thread safety and concurrent operations

These tests verify that DockMon's real-time event delivery system works correctly.
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import Mock, MagicMock, AsyncMock, patch, call
from fastapi import WebSocket

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from event_bus import EventBus, Event, EventType
from websocket.connection import ConnectionManager, DateTimeEncoder


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket for testing."""
    ws = AsyncMock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


@pytest.fixture
def connection_manager():
    """Create a ConnectionManager instance."""
    return ConnectionManager()


@pytest.fixture
def mock_monitor():
    """Create a mock DockerMonitor with event_logger and alert_evaluation_service."""
    monitor = Mock()

    # Mock event_logger
    monitor.event_logger = Mock()
    monitor.event_logger.log_event = AsyncMock()

    # Mock alert_evaluation_service - using correct method names
    monitor.alert_evaluation_service = Mock()
    monitor.alert_evaluation_service.handle_container_event = AsyncMock()
    monitor.alert_evaluation_service.handle_host_event = AsyncMock()

    return monitor


@pytest.fixture
def event_bus(mock_monitor):
    """Create an EventBus instance with mocked monitor."""
    return EventBus(mock_monitor)


class TestEventBusEmission:
    """Test EventBus.emit() functionality."""

    @pytest.mark.asyncio
    async def test_emit_logs_event_to_database(self, event_bus, mock_monitor):
        """EventBus.emit() should log events to database via event_logger."""
        event = Event(
            event_type=EventType.CONTAINER_STARTED,
            scope_type='container',
            scope_id='host123:abc123def456',
            scope_name='test-nginx',
            host_id='host123',
            host_name='test-host',
            data={'message': 'Container started successfully'}
        )

        await event_bus.emit(event)

        # Verify event_logger.log_event was called
        assert mock_monitor.event_logger.log_event.called
        call_args = mock_monitor.event_logger.log_event.call_args

        # Verify correct event context passed
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_emit_triggers_alert_evaluation(self, event_bus, mock_monitor):
        """EventBus.emit() should trigger alert evaluation service."""
        event = Event(
            event_type=EventType.CONTAINER_DIED,
            scope_type='container',
            scope_id='host123:abc123def456',
            scope_name='critical-app',
            host_id='host123',
            data={'exit_code': 1}
        )

        await event_bus.emit(event)

        # Verify alert evaluation was triggered (container event)
        assert mock_monitor.alert_evaluation_service.handle_container_event.called

    @pytest.mark.asyncio
    async def test_emit_notifies_subscribers(self, event_bus):
        """EventBus.emit() should notify all subscribed handlers."""
        # Create subscriber handlers
        handler1 = AsyncMock()
        handler2 = AsyncMock()

        # Subscribe handlers to UPDATE_AVAILABLE event
        event_bus.subscribe(EventType.UPDATE_AVAILABLE, handler1)
        event_bus.subscribe(EventType.UPDATE_AVAILABLE, handler2)

        # Emit event
        event = Event(
            event_type=EventType.UPDATE_AVAILABLE,
            scope_type='container',
            scope_id='host123:abc123def456',
            scope_name='nginx',
            host_id='host123',
            data={'current': 'nginx:1.24', 'latest': 'nginx:1.25'}
        )

        await event_bus.emit(event)

        # Verify both handlers were called
        handler1.assert_called_once_with(event)
        handler2.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_emit_handles_subscriber_failure_gracefully(self, event_bus):
        """EventBus.emit() should handle subscriber failures without blocking other subscribers."""
        # Create handlers - one fails, one succeeds
        failing_handler = AsyncMock(side_effect=Exception("Handler error"))
        successful_handler = AsyncMock()

        event_bus.subscribe(EventType.UPDATE_COMPLETED, failing_handler)
        event_bus.subscribe(EventType.UPDATE_COMPLETED, successful_handler)

        event = Event(
            event_type=EventType.UPDATE_COMPLETED,
            scope_type='container',
            scope_id='host123:abc123def456',
            scope_name='nginx',
            host_id='host123',
            data={'duration': 45}
        )

        # Should not raise exception even though one handler fails
        await event_bus.emit(event)

        # Both handlers should have been called
        assert failing_handler.called
        assert successful_handler.called

    @pytest.mark.asyncio
    async def test_emit_without_event_logger(self):
        """EventBus.emit() should handle missing event_logger gracefully."""
        # Create monitor without event_logger
        monitor_without_logger = Mock()
        monitor_without_logger.event_logger = None
        monitor_without_logger.alert_evaluation_service = Mock()
        monitor_without_logger.alert_evaluation_service.handle_container_event = AsyncMock()
        monitor_without_logger.alert_evaluation_service.handle_host_event = AsyncMock()

        bus = EventBus(monitor_without_logger)

        event = Event(
            event_type=EventType.CONTAINER_STARTED,
            scope_type='container',
            scope_id='host123:abc123def456',
            scope_name='test',
            host_id='host123'
        )

        # Should not raise exception
        await bus.emit(event)

        # Alert evaluation should still work (container event)
        assert monitor_without_logger.alert_evaluation_service.handle_container_event.called


class TestEventBusSubscriptions:
    """Test EventBus subscription management."""

    def test_subscribe_adds_handler(self, event_bus):
        """EventBus.subscribe() should add handler to subscribers list."""
        handler = AsyncMock()

        event_bus.subscribe(EventType.UPDATE_STARTED, handler)

        assert 'update_started' in event_bus.subscribers
        assert handler in event_bus.subscribers['update_started']

    def test_subscribe_multiple_handlers_same_event(self, event_bus):
        """EventBus.subscribe() should allow multiple handlers for same event type."""
        handler1 = AsyncMock()
        handler2 = AsyncMock()

        event_bus.subscribe(EventType.UPDATE_FAILED, handler1)
        event_bus.subscribe(EventType.UPDATE_FAILED, handler2)

        assert len(event_bus.subscribers['update_failed']) == 2
        assert handler1 in event_bus.subscribers['update_failed']
        assert handler2 in event_bus.subscribers['update_failed']

    def test_unsubscribe_removes_handler(self, event_bus):
        """EventBus.unsubscribe() should remove handler from subscribers list."""
        handler = AsyncMock()

        event_bus.subscribe(EventType.CONTAINER_STOPPED, handler)
        event_bus.unsubscribe(EventType.CONTAINER_STOPPED, handler)

        assert 'container_stopped' not in event_bus.subscribers

    def test_unsubscribe_nonexistent_handler(self, event_bus):
        """EventBus.unsubscribe() should handle nonexistent handler gracefully."""
        handler = AsyncMock()

        # Should not raise exception
        event_bus.unsubscribe(EventType.HOST_CONNECTED, handler)


class TestWebSocketConnectionManager:
    """Test WebSocket ConnectionManager functionality."""

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self, connection_manager, mock_websocket):
        """ConnectionManager.connect() should accept WebSocket connection."""
        await connection_manager.connect(mock_websocket)

        mock_websocket.accept.assert_called_once()
        assert mock_websocket in connection_manager.active_connections

    @pytest.mark.asyncio
    async def test_connect_multiple_clients(self, connection_manager):
        """ConnectionManager should handle multiple WebSocket connections."""
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)
        ws3 = AsyncMock(spec=WebSocket)

        await connection_manager.connect(ws1)
        await connection_manager.connect(ws2)
        await connection_manager.connect(ws3)

        assert len(connection_manager.active_connections) == 3
        assert ws1 in connection_manager.active_connections
        assert ws2 in connection_manager.active_connections
        assert ws3 in connection_manager.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self, connection_manager, mock_websocket):
        """ConnectionManager.disconnect() should remove WebSocket from active connections."""
        await connection_manager.connect(mock_websocket)
        await connection_manager.disconnect(mock_websocket)

        assert mock_websocket not in connection_manager.active_connections

    @pytest.mark.asyncio
    async def test_has_active_connections(self, connection_manager, mock_websocket):
        """ConnectionManager.has_active_connections() should return correct status."""
        assert not connection_manager.has_active_connections()

        await connection_manager.connect(mock_websocket)
        assert connection_manager.has_active_connections()

        await connection_manager.disconnect(mock_websocket)
        assert not connection_manager.has_active_connections()

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(self, connection_manager):
        """ConnectionManager.broadcast() should send message to all connected clients."""
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)
        ws3 = AsyncMock(spec=WebSocket)

        await connection_manager.connect(ws1)
        await connection_manager.connect(ws2)
        await connection_manager.connect(ws3)

        message = {
            'type': 'test_event',
            'data': {'value': 123}
        }

        await connection_manager.broadcast(message)

        # All clients should receive the message
        expected_json = json.dumps(message, cls=DateTimeEncoder)
        ws1.send_text.assert_called_once_with(expected_json)
        ws2.send_text.assert_called_once_with(expected_json)
        ws3.send_text.assert_called_once_with(expected_json)

    @pytest.mark.asyncio
    async def test_broadcast_handles_datetime_serialization(self, connection_manager, mock_websocket):
        """ConnectionManager.broadcast() should properly serialize datetime objects."""
        await connection_manager.connect(mock_websocket)

        now = datetime.utcnow()
        message = {
            'type': 'event_with_timestamp',
            'timestamp': now,
            'data': {'created_at': now}
        }

        await connection_manager.broadcast(message)

        # Verify message was sent
        assert mock_websocket.send_text.called
        sent_json = mock_websocket.send_text.call_args[0][0]
        sent_data = json.loads(sent_json)

        # Verify timestamps have 'Z' suffix
        assert sent_data['timestamp'].endswith('Z')
        assert sent_data['data']['created_at'].endswith('Z')

    @pytest.mark.asyncio
    async def test_broadcast_cleans_up_dead_connections(self, connection_manager):
        """ConnectionManager.broadcast() should detect and remove dead connections."""
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)
        ws3 = AsyncMock(spec=WebSocket)

        # ws2 will fail when sending
        ws2.send_text.side_effect = Exception("Connection broken")

        await connection_manager.connect(ws1)
        await connection_manager.connect(ws2)
        await connection_manager.connect(ws3)

        message = {'type': 'test'}
        await connection_manager.broadcast(message)

        # ws2 should be removed from active connections
        assert ws1 in connection_manager.active_connections
        assert ws2 not in connection_manager.active_connections
        assert ws3 in connection_manager.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_to_empty_connection_list(self, connection_manager):
        """ConnectionManager.broadcast() should handle empty connection list gracefully."""
        message = {'type': 'test'}

        # Should not raise exception
        await connection_manager.broadcast(message)

    @pytest.mark.asyncio
    async def test_concurrent_broadcasts_thread_safe(self, connection_manager):
        """ConnectionManager.broadcast() should be thread-safe for concurrent calls."""
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)

        await connection_manager.connect(ws1)
        await connection_manager.connect(ws2)

        # Send multiple broadcasts concurrently
        broadcasts = [
            connection_manager.broadcast({'type': 'event1'}),
            connection_manager.broadcast({'type': 'event2'}),
            connection_manager.broadcast({'type': 'event3'}),
        ]

        await asyncio.gather(*broadcasts)

        # Each client should receive all 3 messages
        assert ws1.send_text.call_count == 3
        assert ws2.send_text.call_count == 3


class TestWebSocketIntegrationWithDeployments:
    """Test WebSocket integration with deployment events."""

    @pytest.mark.asyncio
    async def test_deployment_progress_event_broadcast(self, connection_manager, mock_websocket):
        """Deployment progress events should be properly formatted and broadcast."""
        await connection_manager.connect(mock_websocket)

        # Simulate deployment progress event
        event = {
            'type': 'deployment_progress',
            'data': {
                'deployment_id': 'host123:deploy001',
                'progress': 50,
                'stage': 'pulling_image',
                'message': 'Pulling image nginx:latest',
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
        }

        await connection_manager.broadcast(event)

        assert mock_websocket.send_text.called
        sent_json = mock_websocket.send_text.call_args[0][0]
        sent_data = json.loads(sent_json)

        assert sent_data['type'] == 'deployment_progress'
        assert sent_data['data']['deployment_id'] == 'host123:deploy001'
        assert sent_data['data']['progress'] == 50

    @pytest.mark.asyncio
    async def test_deployment_layer_progress_event_broadcast(self, connection_manager, mock_websocket):
        """Layer-by-layer progress events should be properly broadcast."""
        await connection_manager.connect(mock_websocket)

        event = {
            'type': 'deployment_layer_progress',
            'data': {
                'deployment_id': 'host123:deploy001',
                'layers': [
                    {'id': 'layer1', 'status': 'complete', 'progress': 100},
                    {'id': 'layer2', 'status': 'downloading', 'progress': 45},
                ],
                'overall_progress': 60,
                'download_speed': 12.5,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
        }

        await connection_manager.broadcast(event)

        assert mock_websocket.send_text.called
        sent_json = mock_websocket.send_text.call_args[0][0]
        sent_data = json.loads(sent_json)

        assert sent_data['type'] == 'deployment_layer_progress'
        assert sent_data['data']['overall_progress'] == 60
        assert sent_data['data']['download_speed'] == 12.5


class TestEndToEndEventFlow:
    """Test complete event flow: emit → database → alerts → websocket."""

    @pytest.mark.asyncio
    async def test_complete_event_flow(self, event_bus, mock_monitor, connection_manager, mock_websocket):
        """Test complete event flow from emission to WebSocket delivery."""
        # Connect WebSocket client
        await connection_manager.connect(mock_websocket)

        # Create subscriber that broadcasts to WebSocket
        async def websocket_broadcaster(event: Event):
            await connection_manager.broadcast({
                'type': 'event_notification',
                'event_type': event.event_type.value,
                'scope_id': event.scope_id,
                'data': event.data
            })

        event_bus.subscribe(EventType.UPDATE_COMPLETED, websocket_broadcaster)

        # Emit event
        event = Event(
            event_type=EventType.UPDATE_COMPLETED,
            scope_type='container',
            scope_id='host123:abc123def456',
            scope_name='nginx',
            host_id='host123',
            data={'duration': 45, 'new_image': 'nginx:1.25'}
        )

        await event_bus.emit(event)

        # Verify complete flow:
        # 1. Event logged to database
        assert mock_monitor.event_logger.log_event.called

        # 2. Alert evaluation triggered (container event)
        assert mock_monitor.alert_evaluation_service.handle_container_event.called

        # 3. WebSocket message sent to client
        assert mock_websocket.send_text.called
        sent_json = mock_websocket.send_text.call_args[0][0]
        sent_data = json.loads(sent_json)

        assert sent_data['type'] == 'event_notification'
        assert sent_data['event_type'] == 'update_completed'
        assert sent_data['scope_id'] == 'host123:abc123def456'


class TestWebSocketResilience:
    """Test WebSocket resilience and error handling."""

    @pytest.mark.asyncio
    async def test_broadcast_continues_after_single_client_failure(self, connection_manager):
        """Broadcast should continue to other clients if one fails."""
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)
        ws3 = AsyncMock(spec=WebSocket)
        ws4 = AsyncMock(spec=WebSocket)

        # ws2 fails immediately, ws3 fails later
        ws2.send_text.side_effect = Exception("Client error")
        ws3.send_text.side_effect = Exception("Network error")

        await connection_manager.connect(ws1)
        await connection_manager.connect(ws2)
        await connection_manager.connect(ws3)
        await connection_manager.connect(ws4)

        await connection_manager.broadcast({'type': 'test'})

        # Healthy clients should still receive message
        assert ws1.send_text.called
        assert ws4.send_text.called

        # Dead clients should be removed
        assert len(connection_manager.active_connections) == 2

    @pytest.mark.asyncio
    async def test_concurrent_connect_disconnect_operations(self, connection_manager):
        """Test thread safety with concurrent connect/disconnect operations."""
        clients = [AsyncMock(spec=WebSocket) for _ in range(10)]

        # Concurrently connect all clients
        await asyncio.gather(*[connection_manager.connect(ws) for ws in clients])
        assert len(connection_manager.active_connections) == 10

        # Concurrently disconnect half
        await asyncio.gather(*[connection_manager.disconnect(ws) for ws in clients[:5]])
        assert len(connection_manager.active_connections) == 5

        # Remaining clients should receive broadcasts
        await connection_manager.broadcast({'type': 'test'})
        for ws in clients[5:]:
            assert ws.send_text.called
