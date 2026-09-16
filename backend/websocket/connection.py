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

from auth.api_key_auth import (
    Capabilities,
    get_capabilities_for_user,
    get_user_group_ids,
    get_visible_host_ids_for_groups,
    has_capability_for_user,
)
from utils.response_filtering import DROP, PRUNE, WS_HOST_VISIBILITY, filter_ws_container_message, filter_ws_host_visibility


logger = logging.getLogger(__name__)

# Maps every emitted WS message type to the capability it requires (None = no
# capability). Kept in lockstep with WS_HOST_VISIBILITY and the emitter inventory
# by tests/unit/websocket/test_ws_host_visibility.py. Note: initial_state is sent
# directly in main.py with its own per-field capability filtering.
MESSAGE_CAPABILITY_MAP: dict[str, Optional[str]] = {
    "containers_update": "containers.view",
    "container_recreated": "containers.view",
    "container_update_progress": "containers.view",
    "container_update_layer_progress": "containers.view",
    "container_update_warning": "containers.view",
    "container_update_complete": "containers.view",
    "container_stats": "containers.view",
    "auto_restart_success": "containers.view",
    "auto_restart_failed": "containers.view",
    "batch_job_update": "batch.view",
    "batch_item_update": "batch.view",
    "host_added": "hosts.view",
    "host_removed": "hosts.view",
    "host_migrated": "hosts.view",
    "host_status_changed": "hosts.view",
    "migration_choice_needed": "hosts.view",
    "new_event": "events.view",
    "agent_update_progress": "containers.view",
    "blackout_status_changed": None,
    "deployment_created": "stacks.view",
    "deployment_progress": "stacks.view",
    "deployment_completed": "stacks.view",
    "deployment_failed": "stacks.view",
    "deployment_rolled_back": "stacks.view",
    "deployment_service_progress": "stacks.view",
    "deployment_layer_progress": "stacks.view",
}

_warned_unmapped_types: set[str] = set()


def _warn_unmapped(msg_type: str) -> None:
    if msg_type not in _warned_unmapped_types:
        _warned_unmapped_types.add(msg_type)
        logger.warning(f"WS message type '{msg_type}' has no host-visibility rule; dropped for scoped connections")


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
        # None = unrestricted; a set = only these host ids (fail-closed per message type)
        self._connection_visible_hosts: dict[WebSocket, Optional[set]] = {}
        # Bumped on every refresh so a connection resolving its visible set
        # concurrently with a scope change can detect the lost update.
        self._visibility_generation = 0
        self._lock = asyncio.Lock()
        self.update_executor = None  # Set by monitor after initialization
        self.realtime = None  # Set by monitor after initialization

    @property
    def visibility_generation(self) -> int:
        return self._visibility_generation

    async def connect(self, websocket: WebSocket, user_id: Optional[int] = None, capabilities: Optional[set] = None,
                      visible_host_ids: Optional[set] = None):
        """Accept WebSocket connection and store user_id for capability checks.

        Args:
            websocket: The WebSocket connection
            user_id: User ID for group-based capability filtering
            capabilities: Pre-computed capability set; if None, fetched from user_id
            visible_host_ids: Pre-computed host scope; None = unrestricted
        """
        await websocket.accept()
        caps = capabilities if capabilities is not None else (set(get_capabilities_for_user(user_id)) if user_id else set())
        async with self._lock:
            self.active_connections.append(websocket)
            if user_id is not None:
                self._connection_user_ids[websocket] = user_id
            self._connection_capabilities[websocket] = caps
            self._connection_visible_hosts[websocket] = visible_host_ids
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
            self._connection_visible_hosts.pop(websocket, None)
        logger.debug(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    def get_connection_user_id(self, websocket: WebSocket) -> Optional[int]:
        """Get user_id for a connection."""
        return self._connection_user_ids.get(websocket)

    def get_visible_hosts(self, websocket: WebSocket) -> Optional[set]:
        """Current host scope of a connection; None = unrestricted."""
        return self._connection_visible_hosts.get(websocket)

    async def set_visible_hosts(self, websocket: WebSocket, visible_host_ids: Optional[set]) -> None:
        async with self._lock:
            if websocket in self._connection_capabilities:
                self._connection_visible_hosts[websocket] = visible_host_ids

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
            visible_snapshot = dict(self._connection_visible_hosts)
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

                visible = visible_snapshot.get(connection)
                if visible is None:
                    # Unrestricted: env filter only, payload otherwise untouched
                    if filter_containers and msg_type == "containers_update":
                        user_id = user_ids_snapshot.get(connection)
                        filtered_message = self._filter_container_message(message, user_id)
                        await connection.send_text(json.dumps(filtered_message, cls=DateTimeEncoder))
                    else:
                        await connection.send_text(json.dumps(message, cls=DateTimeEncoder))
                    continue

                rule = WS_HOST_VISIBILITY.get(msg_type)
                if rule is None:
                    _warn_unmapped(msg_type)
                    continue
                scoped_message = message
                if filter_containers and msg_type == "containers_update":
                    scoped_message = self._filter_container_message(message, user_ids_snapshot.get(connection))
                if rule is PRUNE:
                    scoped_message = filter_ws_host_visibility(scoped_message, visible)
                else:
                    hosts = rule(message)
                    if hosts is DROP or not hosts <= visible:
                        continue
                await connection.send_text(json.dumps(scoped_message, cls=DateTimeEncoder))
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
                    self._connection_visible_hosts.pop(conn, None)

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

    async def refresh_visible_hosts_for_user(self, user_id: int):
        """Recompute the host scope of every connection belonging to a user and
        revoke stats subscriptions that fell outside it."""
        await self._refresh_visible_hosts(lambda uid: uid == user_id)

    async def refresh_all_visible_hosts(self):
        """Recompute every connection's host scope (scope, membership or host-tag change)."""
        await self._refresh_visible_hosts(lambda uid: True)

    async def _refresh_visible_hosts(self, applies_to) -> None:
        async with self._lock:
            self._visibility_generation += 1
            ws_user_ids = [(ws, uid) for ws, uid in self._connection_user_ids.items() if applies_to(uid)]

        per_user: dict[int, Optional[set]] = {}
        for _, uid in ws_user_ids:
            if uid not in per_user:
                per_user[uid] = get_visible_host_ids_for_groups(get_user_group_ids(uid))

        async with self._lock:
            refreshed = [(ws, per_user[uid]) for ws, uid in ws_user_ids if ws in self._connection_capabilities]
            for ws, visible in refreshed:
                self._connection_visible_hosts[ws] = visible

        if self.realtime is not None:
            for ws, visible in refreshed:
                await self.realtime.revoke_hidden_subscriptions(ws, visible)
