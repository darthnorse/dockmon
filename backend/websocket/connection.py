"""
WebSocket Connection Management for DockMon
Handles WebSocket connections and message broadcasting
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import WebSocket

from auth.api_key_auth import (
    Capabilities,
    get_capabilities_for_user,
    get_visible_host_ids_for_user,
    has_capability_for_user,
    host_is_visible,
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
        # Interactive shells are not broadcast targets, but a user delete or a scope
        # change must still be able to close them: (user_id, host_id) per socket
        self._shell_sockets: dict[WebSocket, tuple[int, str]] = {}
        # Bumped on every refresh so a connection resolving its visible set
        # concurrently with a scope change can detect the lost update.
        self._visibility_generation = 0
        self._lock = asyncio.Lock()
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

    def get_capabilities(self, websocket: WebSocket) -> set:
        """Current capability set of a connection; unknown sockets have none."""
        return self._connection_capabilities.get(websocket, set())

    def get_visible_hosts(self, websocket: WebSocket) -> Optional[set]:
        """Current host scope of a connection; None = unrestricted. A socket this
        manager does not know (already evicted) sees nothing, never everything."""
        return self._connection_visible_hosts.get(websocket, set())

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
            if required_cap is not None:
                conn_caps = caps_snapshot.get(connection, set())
                if required_cap not in conn_caps:
                    continue

            try:
                outgoing = self._scope_message(message, msg_type, visible_snapshot.get(connection))
                if outgoing is None:
                    continue
                if filter_containers and msg_type == "containers_update":
                    outgoing = self._filter_container_message(outgoing, user_ids_snapshot.get(connection))
                payload = json.dumps(outgoing, cls=DateTimeEncoder)
            except Exception:
                # Withhold this message from this connection; only a failed send marks it dead
                logger.exception(f"Failed to prepare WS message '{msg_type}' for a connection; skipped")
                continue
            try:
                await connection.send_text(payload)
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

    @staticmethod
    def _scope_message(message: dict, msg_type: str, visible: Optional[set]) -> Optional[dict]:
        """Apply the connection's host scope; None = drop. Unrestricted connections
        get the message back untouched. Pruning runs before the env filter so the
        env filter's deep copy only covers the visible subset."""
        if visible is None:
            return message
        rule = WS_HOST_VISIBILITY.get(msg_type)
        if rule is None:
            _warn_unmapped(msg_type)
            return None
        if rule is PRUNE:
            return filter_ws_host_visibility(message, visible)
        hosts = rule(message)
        if hosts is DROP or not hosts <= visible:
            return None
        return message

    def _filter_container_message(self, message: dict, user_id: Optional[int]) -> dict:
        """Filter container data based on user capabilities.

        Removes env vars from containers for users without containers.view_env capability.
        Uses centralized filter_ws_container_message utility for consistency.
        """
        can_view_env = user_id is not None and has_capability_for_user(user_id, Capabilities.CONTAINERS_VIEW_ENV)
        return filter_ws_container_message(message, can_view_env)

    async def refresh_capabilities_for_user(self, user_id: int):
        """Re-fetch cached capabilities for all connections belonging to a user."""
        caps = set(get_capabilities_for_user(user_id))
        async with self._lock:
            self._visibility_generation += 1
            for ws, uid in self._connection_user_ids.items():
                if uid == user_id:
                    self._connection_capabilities[ws] = caps
        await self._close_shells_without_capability({user_id: caps})

    async def refresh_all_capabilities(self):
        """Re-fetch cached capabilities for all connected users."""
        # Snapshot user IDs under lock, fetch capabilities outside to minimize critical section
        async with self._lock:
            ws_user_ids = list(self._connection_user_ids.items())

        new_caps = {ws: set(get_capabilities_for_user(uid)) for ws, uid in ws_user_ids}

        async with self._lock:
            self._visibility_generation += 1
            for ws, caps in new_caps.items():
                if ws in self._connection_capabilities:
                    self._connection_capabilities[ws] = caps
            shell_users = {uid for uid, _ in self._shell_sockets.values()}
        await self._close_shells_without_capability({uid: set(get_capabilities_for_user(uid)) for uid in shell_users})

    async def _close_shells_without_capability(self, caps_by_user: dict[int, set]) -> None:
        """An open shell is root-equivalent on its container; losing containers.shell ends it."""
        async with self._lock:
            revoked = [ws for ws, (uid, _) in self._shell_sockets.items()
                       if uid in caps_by_user and Capabilities.CONTAINERS_SHELL not in caps_by_user[uid]]
        for ws in revoked:
            await self._close(ws, 4403, "Shell access revoked")
            await self.unregister_shell(ws)

    async def register_shell(self, websocket: WebSocket, user_id: int, host_id: str):
        async with self._lock:
            self._shell_sockets[websocket] = (user_id, host_id)

    async def unregister_shell(self, websocket: WebSocket):
        async with self._lock:
            self._shell_sockets.pop(websocket, None)

    async def _close(self, websocket: WebSocket, code: int, reason: str):
        try:
            await websocket.close(code=code, reason=reason)
        except Exception as e:
            logger.debug(f"Closing socket ({reason}): {e}")

    async def disconnect_user(self, user_id: int):
        """Close every connection belonging to a user (account deleted), shells included."""
        async with self._lock:
            self._visibility_generation += 1
            sockets = [ws for ws, uid in self._connection_user_ids.items() if uid == user_id]
            shells = [ws for ws, (uid, _) in self._shell_sockets.items() if uid == user_id]
        for ws in sockets:
            await self._close(ws, 4401, "User account deleted")
            await self.disconnect(ws)
        for ws in shells:
            await self._close(ws, 4401, "User account deleted")
            await self.unregister_shell(ws)

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
            shells = [(ws, uid, host_id) for ws, (uid, host_id) in self._shell_sockets.items() if applies_to(uid)]

        per_user: dict[int, Optional[set]] = {}
        for uid in {uid for _, uid in ws_user_ids} | {uid for _, uid, _ in shells}:
            per_user[uid] = get_visible_host_ids_for_user(uid)

        async with self._lock:
            refreshed = [(ws, per_user[uid]) for ws, uid in ws_user_ids if ws in self._connection_capabilities]
            for ws, visible in refreshed:
                self._connection_visible_hosts[ws] = visible

        if self.realtime is not None:
            for ws, visible in refreshed:
                await self.realtime.revoke_hidden_subscriptions(ws, visible)

        for ws, uid, host_id in shells:
            if not host_is_visible(host_id, per_user[uid]):
                await self._close(ws, 4404, "Not found")
                await self.unregister_shell(ws)
