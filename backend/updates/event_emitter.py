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
        current_digest: Optional[str] = None,
        latest_digest: Optional[str] = None,
        changelog_url: Optional[str] = None,
        current_version: Optional[str] = None,
        latest_version: Optional[str] = None,
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
                    'current_digest': current_digest,
                    'latest_digest': latest_digest,
                    'changelog_url': changelog_url,
                    'current_version': current_version,
                    'latest_version': latest_version,
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

    async def emit_dependents_failed(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        failed_dependents: list
    ):
        """
        Emit warning about failed dependent container recreation.

        Called when container update succeeded but dependent containers
        (using network_mode: container:X) failed to be recreated.
        """
        try:
            # Broadcast warning to UI
            if self.monitor and hasattr(self.monitor, 'manager'):
                warning_msg = (
                    f"Container '{container_name}' updated successfully but "
                    f"{len(failed_dependents)} dependent container(s) failed to recreate: "
                    f"{', '.join(failed_dependents)}"
                )
                await self.monitor.manager.broadcast({
                    "type": "container_update_warning",
                    "data": {
                        "host_id": host_id,
                        "container_id": container_id,
                        "container_name": container_name,
                        "failed_dependents": failed_dependents,
                        "warning": warning_msg,
                    }
                })
                logger.warning(warning_msg)
        except Exception as e:
            logger.error(f"Error emitting dependents failed warning: {e}")
