"""
WebSocket Connection Management for DockMon
Handles WebSocket connections and message broadcasting
"""

import asyncio
import json
import logging
import time
from typing import List

from fastapi import WebSocket


logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects"""
    def default(self, obj):
        from datetime import datetime
        if isinstance(obj, datetime):
            return obj.isoformat() + 'Z'
        return super().default(obj)


class ConnectionManager:
    """Manages WebSocket connections with thread-safe operations"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()
        self.update_executor = None  # Set by monitor after initialization

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.debug(f"New WebSocket connection. Total connections: {len(self.active_connections)}")

        # Send active pull progress to newly connected client
        await self.send_active_pull_progress(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.debug(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    def has_active_connections(self) -> bool:
        """Check if there are any active WebSocket connections"""
        return bool(self.active_connections)

    async def broadcast(self, message: dict):
        """Send message to all connected clients"""
        # Get snapshot of connections with lock
        async with self._lock:
            connections = self.active_connections.copy()

        # Send messages without lock (IO can block)
        dead_connections = []
        for connection in connections:
            try:
                await connection.send_text(json.dumps(message, cls=DateTimeEncoder))
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                dead_connections.append(connection)

        # Clean up dead connections with lock
        if dead_connections:
            async with self._lock:
                for conn in dead_connections:
                    if conn in self.active_connections:
                        self.active_connections.remove(conn)

    async def send_active_pull_progress(self, websocket: WebSocket):
        """
        Send current pull progress for all active pulls to newly connected client.

        Called when WebSocket connects/reconnects to restore progress state.
        Thread-safe: uses lock to prevent race with thread pool workers.
        """
        if not self.update_executor or not hasattr(self.update_executor, '_active_pulls'):
            return

        try:
            # Thread-safe: create snapshot while holding lock
            with self.update_executor._active_pulls_lock:
                active_pulls_snapshot = dict(self.update_executor._active_pulls)

            # Send messages without holding lock (IO can block)
            for composite_key, progress in active_pulls_snapshot.items():
                # Only send if updated within last 10 minutes (still active)
                if time.time() - progress['updated'] < 600:
                    await websocket.send_text(json.dumps({
                        "type": "container_update_layer_progress",
                        "data": progress
                    }, cls=DateTimeEncoder))
        except Exception as e:
            logger.error(f"Error sending active pull progress: {e}", exc_info=True)
