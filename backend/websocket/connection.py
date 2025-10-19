"""
WebSocket Connection Management for DockMon
Handles WebSocket connections and message broadcasting
"""

import asyncio
import json
import logging
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

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.debug(f"New WebSocket connection. Total connections: {len(self.active_connections)}")

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