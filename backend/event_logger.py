"""
Comprehensive event logging service for DockMon
Provides structured logging for all system activities
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from dataclasses import dataclass
from database import DatabaseManager, EventLog

logger = logging.getLogger(__name__)

class EventCategory(str, Enum):
    """Event categories"""
    CONTAINER = "container"
    HOST = "host"
    SYSTEM = "system"
    ALERT = "alert"
    NOTIFICATION = "notification"
    USER = "user"

class EventType(str, Enum):
    """Event types"""
    # Container events
    STATE_CHANGE = "state_change"
    ACTION_TAKEN = "action_taken"
    AUTO_RESTART = "auto_restart"

    # Host events
    CONNECTION = "connection"
    DISCONNECTION = "disconnection"
    HOST_ADDED = "host_added"
    HOST_REMOVED = "host_removed"

    # System events
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    ERROR = "error"
    PERFORMANCE = "performance"

    # Alert events
    RULE_TRIGGERED = "rule_triggered"
    RULE_CREATED = "rule_created"
    RULE_DELETED = "rule_deleted"

    # Notification events
    SENT = "sent"
    FAILED = "failed"
    CHANNEL_CREATED = "channel_created"
    CHANNEL_TESTED = "channel_tested"

    # User events
    LOGIN = "login"
    LOGOUT = "logout"
    CONFIG_CHANGED = "config_changed"

class EventSeverity(str, Enum):
    """Event severity levels"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class EventContext:
    """Context information for events"""
    correlation_id: Optional[str] = None
    host_id: Optional[str] = None
    host_name: Optional[str] = None
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None

class EventLogger:
    """Comprehensive event logging service"""

    def __init__(self, db: DatabaseManager, websocket_manager=None):
        self.db = db
        self.websocket_manager = websocket_manager
        self._event_queue = asyncio.Queue(maxsize=10000)  # Prevent unbounded memory growth
        self._processing_task: Optional[asyncio.Task] = None
        self._active_correlations: Dict[str, List[str]] = {}
        self._dropped_events_count = 0  # Track dropped events for monitoring

    async def start(self):
        """Start the event processing task"""
        if not self._processing_task:
            self._processing_task = asyncio.create_task(self._process_events())
            logger.info("Event logger started")

    async def stop(self):
        """Stop the event processing task"""
        if self._processing_task:
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

            # Drain the queue to prevent memory leak
            while not self._event_queue.empty():
                try:
                    self._event_queue.get_nowait()
                    self._event_queue.task_done()
                except Exception:
                    break

            logger.info("Event logger stopped")

    def log_event(self,
                  category: EventCategory,
                  event_type: EventType,
                  title: str,
                  severity: EventSeverity = EventSeverity.INFO,
                  message: Optional[str] = None,
                  context: Optional[EventContext] = None,
                  old_state: Optional[str] = None,
                  new_state: Optional[str] = None,
                  triggered_by: Optional[str] = None,
                  details: Optional[Dict[str, Any]] = None,
                  duration_ms: Optional[int] = None):
        """Log an event asynchronously"""

        if context is None:
            context = EventContext()

        event_data = {
            'correlation_id': context.correlation_id,
            'category': category.value,
            'event_type': event_type.value,
            'severity': severity.value,
            'host_id': context.host_id,
            'host_name': context.host_name,
            'container_id': context.container_id,
            'container_name': context.container_name,
            'title': title,
            'message': message,
            'old_state': old_state,
            'new_state': new_state,
            'triggered_by': triggered_by,
            'details': details or {},
            'duration_ms': duration_ms,
            'timestamp': datetime.now(timezone.utc)
        }

        # Add to queue for async processing
        try:
            self._event_queue.put_nowait(event_data)
        except asyncio.QueueFull:
            self._dropped_events_count += 1
            # Log more prominently for critical events
            if severity in [EventSeverity.CRITICAL, EventSeverity.ERROR]:
                logger.error(f"Event queue FULL! Dropped {severity.value} event: {title} (total dropped: {self._dropped_events_count})")
            else:
                # Periodic warning to avoid log spam
                if self._dropped_events_count % 100 == 1:
                    logger.warning(f"Event queue full, dropped {self._dropped_events_count} events total")

        # Also log to Python logger for immediate visibility
        python_logger_level = {
            EventSeverity.DEBUG: logging.DEBUG,
            EventSeverity.INFO: logging.INFO,
            EventSeverity.WARNING: logging.WARNING,
            EventSeverity.ERROR: logging.ERROR,
            EventSeverity.CRITICAL: logging.CRITICAL
        }[severity]

        logger.log(python_logger_level, f"[{category.value.upper()}] {title}: {message or ''}")

    def create_correlation_id(self) -> str:
        """Create a new correlation ID for linking related events"""
        correlation_id = str(uuid.uuid4())
        self._active_correlations[correlation_id] = []
        return correlation_id

    def end_correlation(self, correlation_id: str):
        """End a correlation session"""
        if correlation_id in self._active_correlations:
            del self._active_correlations[correlation_id]

    async def _process_events(self):
        """Process events from the queue"""
        while True:
            try:
                event_data = await self._event_queue.get()
                # Save to database
                event_obj = self.db.add_event(event_data)

                # Broadcast to WebSocket clients
                if self.websocket_manager and event_obj:
                    try:
                        await self.websocket_manager.broadcast({
                            'type': 'new_event',
                            'event': {
                                'id': event_obj.id,
                                'correlation_id': event_obj.correlation_id,
                                'category': event_obj.category,
                                'event_type': event_obj.event_type,
                                'severity': event_obj.severity,
                                'host_id': event_obj.host_id,
                                'host_name': event_obj.host_name,
                                'container_id': event_obj.container_id,
                                'container_name': event_obj.container_name,
                                'title': event_obj.title,
                                'message': event_obj.message,
                                'old_state': event_obj.old_state,
                                'new_state': event_obj.new_state,
                                'triggered_by': event_obj.triggered_by,
                                'details': event_obj.details,
                                'duration_ms': event_obj.duration_ms,
                                'timestamp': event_obj.timestamp.isoformat()
                            }
                        })
                    except Exception as ws_error:
                        logger.debug(f"WebSocket broadcast failed (non-critical): {ws_error}")

                self._event_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing event: {e}")

    # Convenience methods for common event types

    def log_container_state_change(self,
                                 container_name: str,
                                 container_id: str,
                                 host_name: str,
                                 host_id: str,
                                 old_state: str,
                                 new_state: str,
                                 triggered_by: str = "system",
                                 correlation_id: Optional[str] = None):
        """Log container state change"""
        # Match severity with alert rule definitions
        if triggered_by == "user":
            # User-initiated changes are WARNING (intentional but noteworthy)
            # except for starting containers which is INFO
            if new_state in ['running', 'restarting']:
                severity = EventSeverity.INFO
            else:
                severity = EventSeverity.WARNING
        elif new_state in ['exited', 'dead']:
            severity = EventSeverity.CRITICAL  # Unexpected crash
        elif new_state in ['stopped', 'paused']:
            severity = EventSeverity.WARNING  # Stopped but not crashed
        else:
            severity = EventSeverity.INFO

        context = EventContext(
            correlation_id=correlation_id,
            host_id=host_id,
            host_name=host_name,
            container_id=container_id,
            container_name=container_name
        )

        # Add context to message if user-initiated
        if triggered_by == "user":
            title = f"Container {container_name} state changed (user action)"
            message = f"Container '{container_name}' on host '{host_name}' state changed from {old_state} to {new_state} (user action)"
        else:
            title = f"Container {container_name} state changed"
            message = f"Container '{container_name}' on host '{host_name}' state changed from {old_state} to {new_state}"

        self.log_event(
            category=EventCategory.CONTAINER,
            event_type=EventType.STATE_CHANGE,
            title=title,
            severity=severity,
            message=message,
            context=context,
            old_state=old_state,
            new_state=new_state,
            triggered_by=triggered_by
        )

    def log_container_action(self,
                           action: str,
                           container_name: str,
                           container_id: str,
                           host_name: str,
                           host_id: str,
                           success: bool,
                           triggered_by: str = "user",
                           error_message: Optional[str] = None,
                           duration_ms: Optional[int] = None,
                           correlation_id: Optional[str] = None):
        """Log container action (start, stop, restart, etc.)"""
        severity = EventSeverity.ERROR if not success else EventSeverity.INFO
        title = f"Container {action} {'succeeded' if success else 'failed'}"
        message = f"Container '{container_name}' on host '{host_name}' {action} {'completed successfully' if success else 'failed'}"

        if error_message:
            message += f": {error_message}"

        context = EventContext(
            correlation_id=correlation_id,
            host_id=host_id,
            host_name=host_name,
            container_id=container_id,
            container_name=container_name
        )

        self.log_event(
            category=EventCategory.CONTAINER,
            event_type=EventType.ACTION_TAKEN,
            title=title,
            severity=severity,
            message=message,
            context=context,
            triggered_by=triggered_by,
            duration_ms=duration_ms,
            details={'action': action, 'success': success, 'error': error_message}
        )

    def log_auto_restart_attempt(self,
                                container_name: str,
                                container_id: str,
                                host_name: str,
                                host_id: str,
                                attempt: int,
                                max_attempts: int,
                                success: bool,
                                error_message: Optional[str] = None,
                                correlation_id: Optional[str] = None):
        """Log auto-restart attempt"""
        severity = EventSeverity.ERROR if not success else EventSeverity.INFO
        title = f"Auto-restart attempt {attempt}/{max_attempts}"
        message = f"Auto-restart attempt {attempt} of {max_attempts} for container '{container_name}' on host '{host_name}' {'succeeded' if success else 'failed'}"

        if error_message:
            message += f": {error_message}"

        context = EventContext(
            correlation_id=correlation_id,
            host_id=host_id,
            host_name=host_name,
            container_id=container_id,
            container_name=container_name
        )

        self.log_event(
            category=EventCategory.CONTAINER,
            event_type=EventType.AUTO_RESTART,
            title=title,
            severity=severity,
            message=message,
            context=context,
            triggered_by="auto_restart",
            details={'attempt': attempt, 'max_attempts': max_attempts, 'success': success, 'error': error_message}
        )

    def log_host_connection(self,
                          host_name: str,
                          host_id: str,
                          host_url: str,
                          connected: bool,
                          error_message: Optional[str] = None):
        """Log host connection/disconnection"""
        severity = EventSeverity.WARNING if not connected else EventSeverity.INFO
        event_type = EventType.CONNECTION if connected else EventType.DISCONNECTION
        title = f"Host {host_name} {'connected' if connected else 'disconnected'}"
        message = f"Docker host {host_name} ({host_url}) {'connected successfully' if connected else 'disconnected'}"

        if error_message:
            message += f": {error_message}"

        context = EventContext(
            host_id=host_id,
            host_name=host_name
        )

        self.log_event(
            category=EventCategory.HOST,
            event_type=event_type,
            title=title,
            severity=severity,
            message=message,
            context=context,
            details={'url': host_url, 'connected': connected, 'error': error_message}
        )

    def log_alert_triggered(self,
                          rule_name: str,
                          rule_id: str,
                          container_name: str,
                          container_id: str,
                          host_name: str,
                          host_id: str,
                          old_state: str,
                          new_state: str,
                          channels_notified: int,
                          total_channels: int,
                          correlation_id: Optional[str] = None):
        """Log alert rule trigger"""
        severity = EventSeverity.WARNING if new_state in ['exited', 'dead'] else EventSeverity.INFO
        title = f"Alert rule '{rule_name}' triggered"
        message = f"Alert rule triggered for {container_name} state change ({old_state} → {new_state}). Notified {channels_notified}/{total_channels} channels."

        context = EventContext(
            correlation_id=correlation_id,
            host_id=host_id,
            host_name=host_name,
            container_id=container_id,
            container_name=container_name
        )

        self.log_event(
            category=EventCategory.ALERT,
            event_type=EventType.RULE_TRIGGERED,
            title=title,
            severity=severity,
            message=message,
            context=context,
            old_state=old_state,
            new_state=new_state,
            details={'rule_id': rule_id, 'channels_notified': channels_notified, 'total_channels': total_channels}
        )

    def log_notification_sent(self,
                            channel_name: str,
                            channel_type: str,
                            success: bool,
                            container_name: str,
                            error_message: Optional[str] = None,
                            correlation_id: Optional[str] = None):
        """Log notification attempt"""
        severity = EventSeverity.ERROR if not success else EventSeverity.INFO
        title = f"Notification {'sent' if success else 'failed'} via {channel_name}"
        message = f"Notification via {channel_name} ({channel_type}) {'sent successfully' if success else 'failed'}"

        if error_message:
            message += f": {error_message}"

        context = EventContext(
            correlation_id=correlation_id,
            container_name=container_name
        )

        self.log_event(
            category=EventCategory.NOTIFICATION,
            event_type=EventType.SENT if success else EventType.FAILED,
            title=title,
            severity=severity,
            message=message,
            context=context,
            details={'channel_name': channel_name, 'channel_type': channel_type, 'success': success, 'error': error_message}
        )

    def log_host_added(self,
                      host_name: str,
                      host_id: str,
                      host_url: str,
                      triggered_by: str = "user"):
        """Log host addition"""
        context = EventContext(
            host_id=host_id,
            host_name=host_name
        )

        self.log_event(
            category=EventCategory.HOST,
            event_type=EventType.HOST_ADDED,
            title=f"Host {host_name} added",
            severity=EventSeverity.INFO,
            message=f"Docker host '{host_name}' ({host_url}) was added to monitoring",
            context=context,
            triggered_by=triggered_by,
            details={'url': host_url}
        )

    def log_host_removed(self,
                        host_name: str,
                        host_id: str,
                        triggered_by: str = "user"):
        """Log host removal"""
        context = EventContext(
            host_id=host_id,
            host_name=host_name
        )

        self.log_event(
            category=EventCategory.HOST,
            event_type=EventType.HOST_REMOVED,
            title=f"Host {host_name} removed",
            severity=EventSeverity.INFO,
            message=f"Docker host '{host_name}' was removed from monitoring",
            context=context,
            triggered_by=triggered_by
        )

    def log_alert_rule_created(self,
                              rule_name: str,
                              rule_id: str,
                              container_count: int,
                              channels: List[str],
                              triggered_by: str = "user"):
        """Log alert rule creation"""
        self.log_event(
            category=EventCategory.ALERT,
            event_type=EventType.RULE_CREATED,
            title=f"Alert rule '{rule_name}' created",
            severity=EventSeverity.INFO,
            message=f"New alert rule '{rule_name}' created with {container_count} container(s) and {len(channels)} notification channel(s)",
            triggered_by=triggered_by,
            details={'rule_id': rule_id, 'container_count': container_count, 'channels': channels}
        )

    def log_alert_rule_deleted(self,
                              rule_name: str,
                              rule_id: str,
                              triggered_by: str = "user"):
        """Log alert rule deletion"""
        self.log_event(
            category=EventCategory.ALERT,
            event_type=EventType.RULE_DELETED,
            title=f"Alert rule '{rule_name}' deleted",
            severity=EventSeverity.INFO,
            message=f"Alert rule '{rule_name}' was deleted",
            triggered_by=triggered_by,
            details={'rule_id': rule_id}
        )

    def log_notification_channel_created(self,
                                        channel_name: str,
                                        channel_type: str,
                                        triggered_by: str = "user"):
        """Log notification channel creation"""
        self.log_event(
            category=EventCategory.NOTIFICATION,
            event_type=EventType.CHANNEL_CREATED,
            title=f"Notification channel '{channel_name}' created",
            severity=EventSeverity.INFO,
            message=f"New notification channel '{channel_name}' ({channel_type}) was created",
            triggered_by=triggered_by,
            details={'channel_name': channel_name, 'channel_type': channel_type}
        )

    def log_system_event(self,
                       title: str,
                       message: str,
                       severity: EventSeverity = EventSeverity.INFO,
                       event_type: EventType = EventType.STARTUP,
                       details: Optional[Dict[str, Any]] = None):
        """Log system-level events"""
        self.log_event(
            category=EventCategory.SYSTEM,
            event_type=event_type,
            title=title,
            severity=severity,
            message=message,
            details=details
        )

class PerformanceTimer:
    """Context manager for timing operations"""

    def __init__(self, event_logger: EventLogger, operation_name: str, context: Optional[EventContext] = None):
        self.event_logger = event_logger
        self.operation_name = operation_name
        self.context = context or EventContext()
        self.start_time = None
        self.correlation_id = None

    def __enter__(self):
        self.start_time = time.time()
        self.correlation_id = self.event_logger.create_correlation_id()
        self.context.correlation_id = self.correlation_id
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.time() - self.start_time) * 1000)

        if exc_type is None:
            # Success
            self.event_logger.log_event(
                category=EventCategory.SYSTEM,
                event_type=EventType.PERFORMANCE,
                title=f"{self.operation_name} completed",
                severity=EventSeverity.DEBUG,
                message=f"Operation '{self.operation_name}' completed in {duration_ms}ms",
                context=self.context,
                duration_ms=duration_ms
            )
        else:
            # Error occurred
            self.event_logger.log_event(
                category=EventCategory.SYSTEM,
                event_type=EventType.ERROR,
                title=f"{self.operation_name} failed",
                severity=EventSeverity.ERROR,
                message=f"Operation '{self.operation_name}' failed after {duration_ms}ms: {exc_val}",
                context=self.context,
                duration_ms=duration_ms,
                details={'error_type': exc_type.__name__ if exc_type else None, 'error_message': str(exc_val)}
            )

        self.event_logger.end_correlation(self.correlation_id)