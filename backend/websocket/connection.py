"""
WebSocket Connection Management for DockMon
Handles WebSocket connections and message broadcasting

v2.3.0: Added per-connection user scopes for role-based data filtering
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional

from fastapi import WebSocket

from auth.api_key_auth import has_capability, Capabilities
from utils.response_filtering import filter_ws_container_message


logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat() + 'Z'
        return super().default(obj)


class ConnectionManager:
    """Manages WebSocket connections with thread-safe operations.

    v2.3.0: Supports per-connection user scopes for role-based filtering.
    """

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._connection_scopes: Dict[WebSocket, List[str]] = {}  # v2.3.0: Store user scopes per connection
        self._lock = asyncio.Lock()
        self.update_executor = None  # Set by monitor after initialization

    async def connect(self, websocket: WebSocket, user_scopes: Optional[List[str]] = None):
        """Accept WebSocket connection and optionally store user scopes.

        Args:
            websocket: The WebSocket connection
            user_scopes: Optional list of user scopes (e.g., ['admin'], ['read', 'write'])
        """
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
            if user_scopes is not None:
                self._connection_scopes[websocket] = user_scopes
        logger.debug(f"New WebSocket connection. Total connections: {len(self.active_connections)}")

        # Send active pull progress to newly connected client
        await self.send_active_pull_progress(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            # Clean up scopes (v2.3.0+)
            self._connection_scopes.pop(websocket, None)
        logger.debug(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    def get_connection_scopes(self, websocket: WebSocket) -> List[str]:
        """Get user scopes for a connection (v2.3.0+)."""
        return self._connection_scopes.get(websocket, [])

    def has_active_connections(self) -> bool:
        """Check if there are any active WebSocket connections"""
        return bool(self.active_connections)

    async def broadcast(self, message: dict, filter_containers: bool = False):
        """Send message to all connected clients.

        Args:
            message: Message to broadcast
            filter_containers: If True, filter container env vars based on user scopes (v2.3.0+)
        """
        # Get snapshot of connections with lock
        async with self._lock:
            connections = self.active_connections.copy()
            # Also snapshot scopes if filtering needed
            if filter_containers:
                scopes_snapshot = dict(self._connection_scopes)
            else:
                scopes_snapshot = {}

        # Send messages without lock (IO can block)
        dead_connections = []
        for connection in connections:
            try:
                # Filter data if needed (v2.3.0+)
                if filter_containers and message.get("type") == "containers_update":
                    user_scopes = scopes_snapshot.get(connection, [])
                    filtered_message = self._filter_container_message(message, user_scopes)
                    await connection.send_text(json.dumps(filtered_message, cls=DateTimeEncoder))
                else:
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

    def _filter_container_message(self, message: dict, user_scopes: List[str]) -> dict:
        """Filter container data based on user scopes (v2.3.0+).

        Removes env vars from containers for users without containers.view_env capability.
        Uses centralized filter_ws_container_message utility for consistency.
        """
        can_view_env = has_capability(user_scopes, Capabilities.CONTAINERS_VIEW_ENV)
        return filter_ws_container_message(message, can_view_env)

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
