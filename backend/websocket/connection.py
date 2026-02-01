"""
WebSocket Connection Management for DockMon
Handles WebSocket connections and message broadcasting
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional

from fastapi import WebSocket

from auth.api_key_auth import has_capability_for_user, get_capabilities_for_user, Capabilities
from utils.response_filtering import filter_ws_container_message


logger = logging.getLogger(__name__)

# Maps WS message types to required capabilities. Messages not in this map
# are sent to all connections (backward-compatible default). Note: initial_state
# is sent directly in main.py with its own per-field capability filtering.
MESSAGE_CAPABILITY_MAP: dict[str, str] = {
    "containers_update": "containers.view",
    "container_discovery": "containers.view",
    "container_recreated": "containers.view",
    "container_update_progress": "containers.view",
    "container_update_layer_progress": "containers.view",
    "container_update_warning": "containers.view",
    "container_update_complete": "containers.view",
    "container_stats": "containers.view",
    "auto_restart_success": "containers.view",
    "auto_restart_failed": "containers.view",
    "image_pull_progress": "containers.view",
    "batch_operation_progress": "batch.view",
    "batch_operation_complete": "batch.view",
    "batch_job_update": "batch.view",
    "batch_item_update": "batch.view",
    "host_added": "hosts.view",
    "host_removed": "hosts.view",
    "host_migrated": "hosts.view",
    "host_status_changed": "hosts.view",
    "migration_choice_needed": "hosts.view",
    "event": "events.view",
    "new_event": "events.view",
    "agent_update_progress": "containers.view",
    "deployment_progress": "stacks.view",
    "deployment_service_progress": "stacks.view",
    "deployment_layer_progress": "stacks.view",
}


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat() + 'Z'
        return super().default(obj)


class ConnectionManager:
    """Manages WebSocket connections with thread-safe operations.

    Supports per-connection user_id for group-based capability filtering.
    """

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._connection_user_ids: dict[WebSocket, int] = {}  # Store user_id per connection
        self._connection_capabilities: dict[WebSocket, set] = {}
        self._lock = asyncio.Lock()
        self.update_executor = None  # Set by monitor after initialization

    async def connect(self, websocket: WebSocket, user_id: Optional[int] = None, capabilities: Optional[set] = None):
        """Accept WebSocket connection and store user_id for capability checks.

        Args:
            websocket: The WebSocket connection
            user_id: User ID for group-based capability filtering
            capabilities: Pre-computed capability set; if None, fetched from user_id
        """
        await websocket.accept()
        caps = capabilities if capabilities is not None else (set(get_capabilities_for_user(user_id)) if user_id else set())
        async with self._lock:
            self.active_connections.append(websocket)
            if user_id is not None:
                self._connection_user_ids[websocket] = user_id
            self._connection_capabilities[websocket] = caps
        logger.debug(f"New WebSocket connection. Total connections: {len(self.active_connections)}")

        # Send active pull progress to newly connected client
        await self.send_active_pull_progress(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            # Clean up user_id mapping and capabilities
            self._connection_user_ids.pop(websocket, None)
            self._connection_capabilities.pop(websocket, None)
        logger.debug(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    def get_connection_user_id(self, websocket: WebSocket) -> Optional[int]:
        """Get user_id for a connection."""
        return self._connection_user_ids.get(websocket)

    def has_active_connections(self) -> bool:
        """Check if there are any active WebSocket connections"""
        return bool(self.active_connections)

    async def broadcast(self, message: dict, filter_containers: bool = False):
        """Send message to all connected clients.

        Args:
            message: Message to broadcast
            filter_containers: If True, filter container env vars based on user capabilities
        """
        msg_type = message.get("type")
        required_cap = MESSAGE_CAPABILITY_MAP.get(msg_type)

        # Get snapshot of connections with lock
        async with self._lock:
            connections = self.active_connections.copy()
            caps_snapshot = dict(self._connection_capabilities)
            # Also snapshot user_ids if filtering needed
            if filter_containers:
                user_ids_snapshot = dict(self._connection_user_ids)
            else:
                user_ids_snapshot = {}

        # Send messages without lock (IO can block)
        dead_connections = []
        for connection in connections:
            try:
                # Skip connections that lack the required capability for this message type
                if required_cap is not None:
                    conn_caps = caps_snapshot.get(connection, set())
                    if required_cap not in conn_caps:
                        continue

                # Filter data if needed based on user capabilities
                if filter_containers and msg_type == "containers_update":
                    user_id = user_ids_snapshot.get(connection)
                    filtered_message = self._filter_container_message(message, user_id)
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
                    self._connection_user_ids.pop(conn, None)
                    self._connection_capabilities.pop(conn, None)

    def _filter_container_message(self, message: dict, user_id: Optional[int]) -> dict:
        """Filter container data based on user capabilities.

        Removes env vars from containers for users without containers.view_env capability.
        Uses centralized filter_ws_container_message utility for consistency.
        """
        can_view_env = user_id is not None and has_capability_for_user(user_id, Capabilities.CONTAINERS_VIEW_ENV)
        return filter_ws_container_message(message, can_view_env)

    async def send_active_pull_progress(self, websocket: WebSocket):
        """
        Send current pull progress for all active pulls to newly connected client.

        Called when WebSocket connects/reconnects to restore progress state.
        Thread-safe: uses lock to prevent race with thread pool workers.
        """
        async with self._lock:
            conn_caps = self._connection_capabilities.get(websocket, set())
        if "containers.view" not in conn_caps:
            return

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

    async def refresh_capabilities_for_user(self, user_id: int):
        """Re-fetch cached capabilities for all connections belonging to a user."""
        caps = set(get_capabilities_for_user(user_id))
        async with self._lock:
            for ws, uid in self._connection_user_ids.items():
                if uid == user_id:
                    self._connection_capabilities[ws] = caps

    async def refresh_all_capabilities(self):
        """Re-fetch cached capabilities for all connected users."""
        # Snapshot user IDs under lock, fetch capabilities outside to minimize critical section
        async with self._lock:
            ws_user_ids = list(self._connection_user_ids.items())

        new_caps = {ws: set(get_capabilities_for_user(uid)) for ws, uid in ws_user_ids}

        async with self._lock:
            for ws, caps in new_caps.items():
                if ws in self._connection_capabilities:
                    self._connection_capabilities[ws] = caps
