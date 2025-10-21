"""
Event Bus - Centralized event coordination system

This module provides a central event bus that:
1. Receives events from various services (update checker, monitor, etc.)
2. Logs events to database via event_logger
3. Automatically triggers alert evaluation
4. Manages event subscribers for extensibility

Events flow: Service → EventBus → [Database, AlertEvaluator, Subscribers]
"""

import logging
from typing import Dict, Any, Optional, List, Callable, Awaitable
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Standard event types in the system"""
    # Container update events
    UPDATE_AVAILABLE = "update_available"
    UPDATE_COMPLETED = "update_completed"
    UPDATE_FAILED = "update_failed"
    UPDATE_SKIPPED_VALIDATION = "update_skipped_validation"  # Auto-update skipped due to validation

    # Container state events
    CONTAINER_STARTED = "container_started"
    CONTAINER_STOPPED = "container_stopped"
    CONTAINER_RESTARTED = "container_restarted"
    CONTAINER_DIED = "container_died"
    CONTAINER_HEALTH_CHANGED = "container_health_changed"

    # Host events
    HOST_CONNECTED = "host_connected"
    HOST_DISCONNECTED = "host_disconnected"

    # System events
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"


class Event:
    """
    Standard event object passed through the event bus
    """
    def __init__(
        self,
        event_type: EventType,
        scope_type: str,  # 'container', 'host', 'system'
        scope_id: str,
        scope_name: str,
        host_id: Optional[str] = None,
        host_name: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ):
        self.event_type = event_type
        self.scope_type = scope_type
        self.scope_id = scope_id
        self.scope_name = scope_name
        self.host_id = host_id
        self.host_name = host_name
        self.data = data or {}
        self.timestamp = timestamp or datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for logging/processing"""
        return {
            'event_type': self.event_type.value if isinstance(self.event_type, EventType) else str(self.event_type),
            'scope_type': self.scope_type,
            'scope_id': self.scope_id,
            'scope_name': self.scope_name,
            'host_id': self.host_id,
            'host_name': self.host_name,
            'data': self.data,
            'timestamp': self.timestamp.isoformat() + 'Z'
        }


class EventBus:
    """
    Centralized event bus for coordinating events and alerts

    Usage:
        bus = EventBus(monitor)
        await bus.emit(Event(
            event_type=EventType.UPDATE_AVAILABLE,
            scope_type='container',
            scope_id=container_id,
            scope_name=container_name,
            host_id=host_id,
            host_name=host_name,
            data={'current_image': '...', 'latest_image': '...'}
        ))
    """

    def __init__(self, monitor):
        """
        Initialize event bus

        Args:
            monitor: DockerMonitor instance (provides event_logger, alert_evaluation_service, etc.)
        """
        self.monitor = monitor
        self.subscribers: Dict[str, List[Callable[[Event], Awaitable[None]]]] = {}
        logger.info("EventBus initialized")

    def subscribe(self, event_type: EventType, handler: Callable[[Event], Awaitable[None]]):
        """
        Subscribe to specific event type

        Args:
            event_type: Type of event to subscribe to
            handler: Async function that handles the event
        """
        event_type_str = event_type.value if isinstance(event_type, EventType) else str(event_type)
        if event_type_str not in self.subscribers:
            self.subscribers[event_type_str] = []
        self.subscribers[event_type_str].append(handler)
        logger.info(f"Subscribed handler to event type: {event_type_str}")

    def unsubscribe(self, event_type: EventType, handler: Callable[[Event], Awaitable[None]]):
        """
        Unsubscribe from specific event type

        Args:
            event_type: Type of event to unsubscribe from
            handler: Handler function to remove
        """
        event_type_str = event_type.value if isinstance(event_type, EventType) else str(event_type)
        if event_type_str in self.subscribers:
            try:
                self.subscribers[event_type_str].remove(handler)
                if not self.subscribers[event_type_str]:
                    del self.subscribers[event_type_str]
                logger.info(f"Unsubscribed handler from event type: {event_type_str}")
            except ValueError:
                logger.warning(f"Handler not found in subscribers for event type: {event_type_str}")

    async def emit(self, event: Event):
        """
        Emit an event - logs to database and triggers alert evaluation

        Args:
            event: Event object to emit
        """
        try:
            logger.debug(f"EventBus: Emitting {event.event_type} for {event.scope_type}:{event.scope_name}")

            # Step 1: Log event to database
            await self._log_event_to_database(event)

            # Step 2: Trigger alert evaluation
            await self._trigger_alert_evaluation(event)

            # Step 3: Notify subscribers
            await self._notify_subscribers(event)

            logger.debug(f"EventBus: Successfully processed {event.event_type} for {event.scope_name}")

        except Exception as e:
            logger.error(f"EventBus: Error processing event {event.event_type}: {e}", exc_info=True)

    async def _log_event_to_database(self, event: Event):
        """Log event to database using event_logger"""
        try:
            if not self.monitor or not hasattr(self.monitor, 'event_logger'):
                logger.warning("EventBus: event_logger not available, skipping database log")
                return

            from event_logger import EventCategory, EventType as LogEventType, EventSeverity, EventContext

            # Map event types to log event types and categories
            event_type_map = {
                EventType.UPDATE_AVAILABLE: (LogEventType.ACTION_TAKEN, EventCategory.CONTAINER, EventSeverity.INFO),
                EventType.UPDATE_COMPLETED: (LogEventType.ACTION_TAKEN, EventCategory.CONTAINER, EventSeverity.INFO),
                EventType.UPDATE_FAILED: (LogEventType.ERROR, EventCategory.CONTAINER, EventSeverity.ERROR),
                EventType.CONTAINER_STARTED: (LogEventType.STATE_CHANGE, EventCategory.CONTAINER, EventSeverity.INFO),
                EventType.CONTAINER_RESTARTED: (LogEventType.STATE_CHANGE, EventCategory.CONTAINER, EventSeverity.INFO),
                EventType.CONTAINER_STOPPED: (LogEventType.STATE_CHANGE, EventCategory.CONTAINER, EventSeverity.WARNING),
                EventType.CONTAINER_DIED: (LogEventType.STATE_CHANGE, EventCategory.CONTAINER, EventSeverity.ERROR),
                EventType.CONTAINER_HEALTH_CHANGED: (LogEventType.STATE_CHANGE, EventCategory.HEALTH_CHECK, EventSeverity.WARNING),
                EventType.HOST_CONNECTED: (LogEventType.CONNECTION, EventCategory.HOST, EventSeverity.INFO),
                EventType.HOST_DISCONNECTED: (LogEventType.DISCONNECTION, EventCategory.HOST, EventSeverity.ERROR),
            }

            log_event_type, category, severity = event_type_map.get(
                event.event_type,
                (LogEventType.ACTION_TAKEN, EventCategory.SYSTEM, EventSeverity.INFO)
            )

            # Create context
            context = EventContext(
                host_id=event.host_id,
                host_name=event.host_name,
                container_id=event.scope_id if event.scope_type == 'container' else None,
                container_name=event.scope_name if event.scope_type == 'container' else None
            )

            # Generate title and message based on event type
            title, message = self._generate_event_message(event)

            # Extract old_state and new_state from event data for proper deduplication
            old_state = event.data.get('old_state') if event.data else None
            new_state = event.data.get('new_state') if event.data else None

            # Log event
            self.monitor.event_logger.log_event(
                category=category,
                event_type=log_event_type,
                severity=severity,
                title=title,
                message=message,
                context=context,
                old_state=old_state,
                new_state=new_state
            )

        except Exception as e:
            logger.error(f"EventBus: Error logging event to database: {e}", exc_info=True)

    async def _trigger_alert_evaluation(self, event: Event):
        """Trigger alert evaluation for this event"""
        try:
            if not self.monitor or not hasattr(self.monitor, 'alert_evaluation_service'):
                logger.debug("EventBus: alert_evaluation_service not available, skipping alert evaluation")
                return

            # Map our event types to alert evaluation event types
            alert_event_type_map = {
                EventType.UPDATE_AVAILABLE: 'info',
                EventType.UPDATE_COMPLETED: 'action_taken',
                EventType.UPDATE_FAILED: 'error',
                EventType.CONTAINER_STARTED: 'state_change',
                EventType.CONTAINER_RESTARTED: 'state_change',
                EventType.CONTAINER_STOPPED: 'state_change',
                EventType.CONTAINER_DIED: 'state_change',
                EventType.CONTAINER_HEALTH_CHANGED: 'state_change',
                EventType.HOST_CONNECTED: 'connection',
                EventType.HOST_DISCONNECTED: 'disconnection',
            }

            alert_event_type = alert_event_type_map.get(event.event_type)
            if not alert_event_type:
                logger.debug(f"EventBus: No alert mapping for {event.event_type}, skipping alert evaluation")
                return

            # Build event data with special flags for alert matching
            event_data = {
                'timestamp': event.timestamp.isoformat() + 'Z',
                'event_type': alert_event_type,
                'triggered_by': 'event_bus',
                **event.data  # Include all custom data
            }

            # Add special flags for alert rule matching
            if event.event_type == EventType.UPDATE_AVAILABLE:
                event_data['update_detected'] = True
            elif event.event_type == EventType.UPDATE_FAILED:
                event_data['update_failure'] = True

            # Call alert evaluation service based on scope
            if event.scope_type == 'container':
                # Extract container_id from composite key (scope_id = host_id:container_id)
                from utils.keys import parse_composite_key
                _, container_id = parse_composite_key(event.scope_id)

                await self.monitor.alert_evaluation_service.handle_container_event(
                    event_type=alert_event_type,
                    container_id=container_id,
                    container_name=event.scope_name,
                    host_id=event.host_id or '',
                    host_name=event.host_name or '',
                    event_data=event_data
                )
                logger.debug(f"EventBus: Triggered container alert evaluation for {event.event_type}")
            elif event.scope_type == 'host':
                await self.monitor.alert_evaluation_service.handle_host_event(
                    event_type=alert_event_type,
                    host_id=event.scope_id,
                    event_data=event_data
                )
                logger.debug(f"EventBus: Triggered host alert evaluation for {event.event_type}")

        except Exception as e:
            logger.error(f"EventBus: Error triggering alert evaluation: {e}", exc_info=True)

    async def _notify_subscribers(self, event: Event):
        """Notify all subscribers of this event type"""
        try:
            event_type_str = event.event_type.value if isinstance(event.event_type, EventType) else str(event.event_type)
            handlers = self.subscribers.get(event_type_str, [])

            for handler in handlers:
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(f"EventBus: Error in subscriber handler: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"EventBus: Error notifying subscribers: {e}", exc_info=True)

    def _generate_event_message(self, event: Event) -> tuple[str, str]:
        """Generate human-readable title and message for event"""
        if event.event_type == EventType.UPDATE_AVAILABLE:
            title = f"Update Available: {event.scope_name}"
            current = event.data.get('current_image', '?')
            latest = event.data.get('latest_image', '?')
            message = f"Update available: {current} → {latest}"

        elif event.event_type == EventType.UPDATE_COMPLETED:
            title = f"Container Update: {event.scope_name}"
            previous = event.data.get('previous_image', '?')
            new = event.data.get('new_image', '?')
            message = f"Container successfully updated from {previous} to {new}"

        elif event.event_type == EventType.UPDATE_FAILED:
            title = f"Container Update Failed: {event.scope_name}"
            error = event.data.get('error_message', 'Unknown error')
            message = f"Container update failed: {error}"

        elif event.event_type == EventType.CONTAINER_STARTED:
            title = f"Container Started: {event.scope_name}"
            message = f"Container {event.scope_name} started"

        elif event.event_type == EventType.CONTAINER_RESTARTED:
            title = f"Container Restarted: {event.scope_name}"
            message = f"Container {event.scope_name} restarted"

        elif event.event_type == EventType.CONTAINER_STOPPED:
            title = f"Container Stopped: {event.scope_name}"
            old_state = event.data.get('old_state', 'unknown')
            new_state = event.data.get('new_state', 'stopped')
            message = f"Container {event.scope_name} changed state: {old_state} → {new_state}"

        elif event.event_type == EventType.CONTAINER_DIED:
            title = f"Container Died: {event.scope_name}"
            exit_code = event.data.get('exit_code')
            if exit_code is not None:
                message = f"Container {event.scope_name} died with exit code {exit_code}"
            else:
                message = f"Container {event.scope_name} died"

        elif event.event_type == EventType.CONTAINER_HEALTH_CHANGED:
            title = f"Container Health Changed: {event.scope_name}"
            old_state = event.data.get('old_state', 'unknown')
            new_state = event.data.get('new_state', 'unknown')
            message = f"Container {event.scope_name} health status: {old_state} → {new_state}"

        elif event.event_type == EventType.HOST_DISCONNECTED:
            title = f"Host Disconnected: {event.host_name or event.scope_name}"
            error = event.data.get('error', 'Connection lost')
            message = f"Host disconnected: {error}"

        elif event.event_type == EventType.HOST_CONNECTED:
            title = f"Host Connected: {event.host_name or event.scope_name}"
            url = event.data.get('url', 'unknown')
            message = f"Host {event.host_name or event.scope_name} reconnected ({url})"

        else:
            title = f"{event.event_type.value}: {event.scope_name}"
            message = str(event.data)

        return title, message


# Global singleton instance
_event_bus: Optional[EventBus] = None


def get_event_bus(monitor=None) -> EventBus:
    """Get or create global event bus instance"""
    global _event_bus
    if _event_bus is None:
        if monitor is None:
            raise RuntimeError("EventBus not initialized - must provide monitor on first call")
        _event_bus = EventBus(monitor)
    return _event_bus
