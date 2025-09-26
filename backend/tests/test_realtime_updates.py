"""
Tests for real-time WebSocket updates and event broadcasting
Ensures all clients receive updates properly
"""

import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime


class TestRealtimeUpdates:
    """Test real-time update functionality"""

    @pytest.mark.asyncio
    async def test_websocket_connection_tracking(self):
        """Test WebSocket connections are tracked properly"""
        from realtime import RealtimeManager

        manager = RealtimeManager()

        # Mock WebSocket connections
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        # Add connections
        await manager.connect(ws1)
        await manager.connect(ws2)

        assert len(manager.active_connections) == 2

        # Remove connection
        await manager.disconnect(ws1)
        assert len(manager.active_connections) == 1

    @pytest.mark.asyncio
    async def test_broadcast_container_update(self):
        """Test broadcasting container state changes"""
        from realtime import RealtimeManager

        manager = RealtimeManager()

        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws1.send_text = AsyncMock()
        ws2.send_text = AsyncMock()

        await manager.connect(ws1)
        await manager.connect(ws2)

        # Broadcast container update
        update = {
            "type": "container_update",
            "container_id": "abc123",
            "state": "exited",
            "exit_code": 1
        }

        await manager.broadcast(update)

        # Both connections should receive update
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

        # Verify message content
        sent_message = ws1.send_text.call_args[0][0]
        data = json.loads(sent_message)
        assert data["type"] == "container_update"
        assert data["container_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_websocket_error_handling(self):
        """Test handling of WebSocket errors during broadcast"""
        from realtime import RealtimeManager

        manager = RealtimeManager()

        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_text = AsyncMock(side_effect=Exception("Connection lost"))

        await manager.connect(good_ws)
        await manager.connect(bad_ws)

        # Broadcast should continue despite one connection failing
        await manager.broadcast({"type": "test"})

        # Bad connection should be removed
        assert bad_ws not in manager.active_connections
        assert good_ws in manager.active_connections

    @pytest.mark.asyncio
    async def test_docker_event_to_websocket(self):
        """Test Docker events are properly forwarded to WebSocket clients"""
        from realtime import RealtimeManager

        manager = RealtimeManager()
        ws = AsyncMock()
        await manager.connect(ws)

        # Simulate Docker event
        docker_event = {
            "Type": "container",
            "Action": "die",
            "Actor": {
                "ID": "container123",
                "Attributes": {"exitCode": "1", "name": "web-app"}
            }
        }

        await manager.handle_docker_event("host123", docker_event)

        # WebSocket should receive formatted event
        ws.send_text.assert_called()
        sent_data = json.loads(ws.send_text.call_args[0][0])
        assert sent_data["type"] == "docker_event"
        assert sent_data["event_type"] == "die"

    @pytest.mark.asyncio
    async def test_alert_triggered_broadcast(self):
        """Test alert notifications are broadcast to all clients"""
        from realtime import RealtimeManager

        manager = RealtimeManager()

        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await manager.connect(ws1)
        await manager.connect(ws2)

        # Trigger alert
        alert_data = {
            "type": "alert_triggered",
            "alert_name": "Container Down",
            "container": "database",
            "severity": "high"
        }

        await manager.broadcast_alert(alert_data)

        # All clients should receive alert
        ws1.send_text.assert_called()
        ws2.send_text.assert_called()

    @pytest.mark.asyncio
    async def test_host_connection_status_update(self):
        """Test host connection status updates"""
        from realtime import RealtimeManager

        manager = RealtimeManager()
        ws = AsyncMock()
        await manager.connect(ws)

        # Host goes offline
        await manager.broadcast_host_status("host123", "offline")

        sent_data = json.loads(ws.send_text.call_args[0][0])
        assert sent_data["type"] == "host_status"
        assert sent_data["host_id"] == "host123"
        assert sent_data["status"] == "offline"

    @pytest.mark.asyncio
    async def test_websocket_reconnection_handling(self):
        """Test client reconnection after disconnect"""
        from realtime import RealtimeManager

        manager = RealtimeManager()

        ws = AsyncMock()
        client_id = "client123"

        # Initial connection
        await manager.connect(ws, client_id=client_id)
        assert len(manager.active_connections) == 1

        # Disconnect
        await manager.disconnect(ws)
        assert len(manager.active_connections) == 0

        # Reconnect with same client ID
        new_ws = AsyncMock()
        await manager.connect(new_ws, client_id=client_id)

        # Should restore client state
        assert len(manager.active_connections) == 1

    @pytest.mark.asyncio
    async def test_rate_limited_updates(self):
        """Test rate limiting of frequent updates"""
        from realtime import RealtimeManager

        manager = RealtimeManager()
        ws = AsyncMock()
        await manager.connect(ws)

        # Send many rapid updates for same container
        for i in range(100):
            await manager.broadcast({
                "type": "container_update",
                "container_id": "abc123",
                "cpu_percent": i
            })

        # Should throttle updates (not send all 100)
        call_count = ws.send_text.call_count
        assert call_count < 100  # Throttled
        assert call_count > 0    # But some got through

    @pytest.mark.asyncio
    async def test_websocket_ping_pong(self):
        """Test WebSocket ping/pong keepalive"""
        from realtime import RealtimeManager

        manager = RealtimeManager()
        ws = AsyncMock()
        ws.send_text = AsyncMock()

        await manager.connect(ws)

        # Start keepalive
        await manager.start_keepalive(ws)

        # Should send ping
        await asyncio.sleep(0.1)

        # Verify ping was sent
        calls = [call[0][0] for call in ws.send_text.call_args_list]
        assert any('ping' in call.lower() for call in calls)

    @pytest.mark.asyncio
    async def test_selective_subscription(self):
        """Test clients can subscribe to specific event types"""
        from realtime import RealtimeManager

        manager = RealtimeManager()

        # Client 1 wants only alerts
        ws1 = AsyncMock()
        await manager.connect(ws1, subscriptions=["alerts"])

        # Client 2 wants everything
        ws2 = AsyncMock()
        await manager.connect(ws2, subscriptions=["all"])

        # Send container update
        await manager.broadcast({"type": "container_update"})

        # Only ws2 should receive it
        ws1.send_text.assert_not_called()
        ws2.send_text.assert_called()

        # Send alert
        await manager.broadcast({"type": "alert"})

        # Both should receive it
        assert ws1.send_text.call_count == 1
        assert ws2.send_text.call_count == 2