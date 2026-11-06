"""
Pending Updates Registry

Coordinates between AgentUpdateExecutor and WebSocket handler to wait for
update_complete and failure events from agents.

Architecture:
1. AgentUpdateExecutor registers a pending update before sending command
2. WebSocket handler signals when an agent reports completion or failure
3. AgentUpdateExecutor awaits the completion signal with timeout
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
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
    # Result data populated by websocket handler from the agent's update events
    new_container_id: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
    request_id: Optional[str] = None
    rollback_seen: bool = False
    rollback_performed: bool = False
    failed_dependents: List[str] = field(default_factory=list)


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

    async def register(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        request_id: Optional[str] = None,
    ) -> PendingUpdate:
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
                request_id=request_id,
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
        request_id: Optional[str] = None,
    ) -> bool:
        """
        Signal that an update has completed.

        Called by WebSocketHandler when update_complete event received.
        Returns True if a pending update was found and signaled.
        """
        key = self._make_key(host_id, old_container_id)

        async with self._lock:
            pending = self._matching_pending(key, request_id)
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

    def _matching_pending(self, key: str, request_id: Optional[str]) -> Optional[PendingUpdate]:
        """Return the pending update unless the event belongs to a different attempt.

        Older agents send no request_id, so their events match on the key alone.
        """
        pending = self._pending.get(key)
        if pending and request_id and pending.request_id != request_id:
            logger.info(f"Ignoring event for {key} from an earlier update attempt")
            return None
        return pending

    async def signal_failed(
        self,
        host_id: str,
        container_id: str,
        request_id: Optional[str],
        error: str,
        rolled_back: bool,
        failed_dependents: Optional[List[str]] = None,
    ) -> bool:
        """Record the outcome stated by an agent's update_failed event and wake the waiter."""
        async with self._lock:
            pending = self._matching_pending(self._make_key(host_id, container_id), request_id)
            if not pending:
                return False
            pending.success = False
            pending.error = error
            pending.rollback_performed = rolled_back
            pending.failed_dependents = failed_dependents or []
            pending.completion_event.set()
            return True

    async def record_failure_progress(
        self,
        host_id: str,
        container_id: str,
        request_id: str,
        stage: str,
        message: str,
    ) -> None:
        """Keep what a new agent's progress events established, in case update_failed is lost."""
        async with self._lock:
            pending = self._matching_pending(self._make_key(host_id, container_id), request_id)
            if pending and not pending.completion_event.is_set():
                self._apply_failure_stage(pending, stage, message)

    async def signal_legacy_failure_stage(
        self,
        host_id: str,
        container_id: str,
        stage: str,
        message: str,
    ) -> None:
        """Infer the outcome of an update from an older agent's progress events."""
        async with self._lock:
            pending = self._pending.get(self._make_key(host_id, container_id))
            if not pending or pending.completion_event.is_set():
                return
            if self._apply_failure_stage(pending, stage, message):
                pending.success = False
                pending.completion_event.set()

    @staticmethod
    def _apply_failure_stage(pending: PendingUpdate, stage: str, message: str) -> bool:
        """Record a failure progress event, returning whether it settles the outcome.

        Agents send two per failure: failed+failed, rollback+rollback when the provider was
        restored, or rollback+failed when restoring it also failed. The second carries the
        final error, so a first rollback settles nothing.
        """
        pending.error = message
        if stage == "rollback" and not pending.rollback_seen:
            pending.rollback_seen = True
            return False
        pending.rollback_performed = stage == "rollback"
        return True

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
