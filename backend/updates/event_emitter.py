"""
Event emitter for container updates.

Handles emission of update-related events via the EventBus system.
Centralizes event creation to reduce boilerplate in UpdateExecutor.
"""

import logging
from typing import Optional

from event_bus import Event, EventType as BusEventType, get_event_bus
from utils.keys import make_composite_key

logger = logging.getLogger(__name__)


class UpdateEventEmitter:
    """
    Emits update-related events via the EventBus.

    Centralizes event emission logic to reduce boilerplate. All events
    include host_id, host_name, scope_type='container', and scope_id.
    """

    def __init__(self, monitor):
        """
        Initialize the event emitter.

        Args:
            monitor: DockerMonitor instance (for host name lookup and event bus)
        """
        self.monitor = monitor

    def _get_host_name(self, host_id: str) -> str:
        """Get host name from monitor, falling back to host_id."""
        if self.monitor and hasattr(self.monitor, 'hosts') and host_id in self.monitor.hosts:
            return self.monitor.hosts[host_id].name
        return host_id

    async def emit_started(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        target_image: str
    ):
        """Emit UPDATE_STARTED event."""
        try:
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.UPDATE_STARTED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=self._get_host_name(host_id),
                data={
                    'target_image': target_image,
                }
            ))
        except Exception as e:
            logger.error(f"Error emitting update started event: {e}")

    async def emit_completed(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        previous_image: str,
        new_image: str,
        previous_digest: str = None,
        new_digest: str = None
    ):
        """Emit UPDATE_COMPLETED event."""
        try:
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.UPDATE_COMPLETED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=self._get_host_name(host_id),
                data={
                    'previous_image': previous_image,
                    'new_image': new_image,
                    'current_digest': previous_digest,
                    'latest_digest': new_digest,
                }
            ))
        except Exception as e:
            logger.error(f"Error emitting update completed event: {e}")

    async def emit_failed(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        error_message: str
    ):
        """Emit UPDATE_FAILED event."""
        try:
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.UPDATE_FAILED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=self._get_host_name(host_id),
                data={
                    'error_message': error_message,
                }
            ))
        except Exception as e:
            logger.error(f"Error emitting update failed event: {e}")

    async def emit_warning(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        warning_message: str
    ):
        """Emit UPDATE_SKIPPED_VALIDATION event (warning level)."""
        try:
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.UPDATE_SKIPPED_VALIDATION,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=self._get_host_name(host_id),
                data={
                    'message': f"Auto-update skipped: {warning_message}",
                    'category': 'update_validation',
                    'reason': warning_message
                }
            ))
        except Exception as e:
            logger.error(f"Error emitting update warning event: {e}")

    async def emit_rollback_completed(
        self,
        host_id: str,
        container_id: str,
        container_name: str
    ):
        """Emit ROLLBACK_COMPLETED event."""
        try:
            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(Event(
                event_type=BusEventType.ROLLBACK_COMPLETED,
                scope_type='container',
                scope_id=make_composite_key(host_id, container_id),
                scope_name=container_name,
                host_id=host_id,
                host_name=self._get_host_name(host_id),
                data={}
            ))
        except Exception as e:
            logger.error(f"Error emitting rollback completed event: {e}")
