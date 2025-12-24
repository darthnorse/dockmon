"""
Pending Updates Registry

Coordinates between AgentUpdateExecutor and WebSocket handler to wait for
update_complete events from agents.

Architecture:
1. AgentUpdateExecutor registers a pending update before sending command
2. WebSocket handler signals completion when update_complete event received
3. AgentUpdateExecutor awaits the completion signal with timeout
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class PendingUpdate:
    """Tracks a pending container update awaiting agent completion."""
    container_id: str
    host_id: str
    container_name: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completion_event: asyncio.Event = field(default_factory=asyncio.Event)
    # Result data populated by websocket handler when update_complete received
    new_container_id: Optional[str] = None
    success: bool = False
    error: Optional[str] = None


class PendingUpdatesRegistry:
    """
    Registry of pending container updates awaiting agent completion.

    Thread-safe singleton that coordinates between:
    - AgentUpdateExecutor: registers pending updates, waits for completion
    - WebSocketHandler: signals completion when update_complete received
    """

    _instance: Optional["PendingUpdatesRegistry"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._pending: Dict[str, PendingUpdate] = {}
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    def _make_key(self, host_id: str, container_id: str) -> str:
        """Create lookup key from host and container ID."""
        return f"{host_id}:{container_id[:12]}"

    async def register(self, host_id: str, container_id: str, container_name: str) -> PendingUpdate:
        """
        Register a pending update before sending command to agent.

        Returns PendingUpdate object with asyncio.Event to await.
        """
        key = self._make_key(host_id, container_id)

        async with self._lock:
            # Clean up any stale entry
            if key in self._pending:
                logger.warning(f"Overwriting stale pending update for {key}")

            pending = PendingUpdate(
                container_id=container_id[:12],
                host_id=host_id,
                container_name=container_name,
            )
            self._pending[key] = pending
            logger.debug(f"Registered pending update: {key} ({container_name})")
            return pending

    async def signal_complete(
        self,
        host_id: str,
        old_container_id: str,
        new_container_id: str,
        success: bool = True,
        error: Optional[str] = None,
    ) -> bool:
        """
        Signal that an update has completed.

        Called by WebSocketHandler when update_complete event received.
        Returns True if a pending update was found and signaled.
        """
        key = self._make_key(host_id, old_container_id)

        async with self._lock:
            pending = self._pending.get(key)
            if pending:
                pending.new_container_id = new_container_id[:12] if new_container_id else None
                pending.success = success
                pending.error = error
                pending.completion_event.set()
                logger.info(f"Signaled completion for {key}: success={success}, new_id={new_container_id[:12] if new_container_id else None}")
                return True
            else:
                logger.debug(f"No pending update found for {key}")
                return False

    async def unregister(self, host_id: str, container_id: str):
        """Remove a pending update from the registry."""
        key = self._make_key(host_id, container_id)

        async with self._lock:
            if key in self._pending:
                del self._pending[key]
                logger.debug(f"Unregistered pending update: {key}")

    async def wait_for_completion(
        self,
        pending: PendingUpdate,
        timeout: float = 300.0,
    ) -> bool:
        """
        Wait for an update to complete.

        Returns True if completed successfully within timeout.
        """
        try:
            await asyncio.wait_for(pending.completion_event.wait(), timeout=timeout)
            return pending.success
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for update completion: {pending.container_name}")
            return False


# Singleton instance
def get_pending_updates_registry() -> PendingUpdatesRegistry:
    """Get the singleton PendingUpdatesRegistry instance."""
    return PendingUpdatesRegistry()
