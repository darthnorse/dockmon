"""
Alert Evaluation Service

Integrates alert engine with:
- Stats service (metric-driven rules)
- Event logger (event-driven rules)

Runs periodic evaluation of metric-driven rules and processes events for event-driven rules.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import joinedload

from database import DatabaseManager, AlertRuleV2, AlertV2
from alerts.engine import AlertEngine, EvaluationContext
from event_logger import EventLogger, EventContext, EventCategory, EventType, EventSeverity

logger = logging.getLogger(__name__)


class AlertEvaluationService:
    """
    Manages periodic alert rule evaluation

    Responsibilities:
    - Fetch container/host metrics periodically
    - Evaluate metric-driven alert rules
    - Process event-driven rules via event logger integration
    - Coordinate with notification system
    """

    def __init__(
        self,
        db: DatabaseManager,
        monitor=None,
        stats_client=None,
        event_logger: Optional[EventLogger] = None,
        notification_service=None,
        evaluation_interval: int = 10  # seconds
    ):
        self.db = db
        self.monitor = monitor  # Reference to DockerMonitor for container lookups
        self.stats_client = stats_client
        self.event_logger = event_logger
        self.notification_service = notification_service
        self.evaluation_interval = evaluation_interval
        self.engine = AlertEngine(db)

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._notification_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the alert evaluation service"""
        if self._running:
            logger.warning("Alert evaluation service already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._evaluation_loop())
        self._notification_task = asyncio.create_task(self._pending_notifications_loop())
        logger.info(f"Alert evaluation service started (interval: {self.evaluation_interval}s)")

    async def stop(self):
        """Stop the alert evaluation service"""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._notification_task:
            self._notification_task.cancel()
            try:
                await self._notification_task
            except asyncio.CancelledError:
                pass

        logger.info("Alert evaluation service stopped")

    async def _evaluation_loop(self):
        """Main evaluation loop"""
        while self._running:
            try:
                await self._evaluate_all_rules()
                await asyncio.sleep(self.evaluation_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in alert evaluation loop: {e}", exc_info=True)
                await asyncio.sleep(self.evaluation_interval)

    async def _pending_notifications_loop(self):
        """
        Background task to check for alerts that need delayed notifications.

        Checks every 5 seconds for:
        1. Open alerts that haven't been notified yet (notified_at is NULL)
        2. Alert age >= rule.clear_duration_seconds
        3. Sends notification and marks notified_at
        """
        check_interval = 5  # Check every 5 seconds

        while self._running:
            try:
                await self._check_pending_notifications()
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in pending notifications loop: {e}", exc_info=True)
                await asyncio.sleep(check_interval)

    async def _check_pending_notifications(self):
        """Check for alerts that have exceeded their clear_duration and need notifications"""
        try:
            # Fetch alerts and close session BEFORE calling async methods
            # to avoid holding database connections across await boundaries
            pending_alerts_data = []

            with self.db.get_session() as session:
                # Get all open alerts that haven't been notified yet
                # Use joinedload to eagerly load rules (avoids N+1 query)
                pending_alerts = session.query(AlertV2).options(
                    joinedload(AlertV2.rule)
                ).filter(
                    AlertV2.state == "open",
                    AlertV2.notified_at == None
                ).all()

                now = datetime.now(timezone.utc)

                # Extract data we need while session is still open
                for alert in pending_alerts:
                    rule = alert.rule

                    if not rule:
                        continue

                    # Get clear_duration (default to 0 if not set)
                    clear_duration = rule.clear_duration_seconds or 0

                    # Calculate alert age from last_seen
                    last_seen = alert.last_seen if alert.last_seen.tzinfo else alert.last_seen.replace(tzinfo=timezone.utc)
                    alert_age = (now - last_seen).total_seconds()

                    # Check if alert has exceeded clear_duration
                    if alert_age >= clear_duration:
                        # Store alert data for processing after session closes
                        pending_alerts_data.append({
                            'alert': alert,
                            'alert_age': alert_age,
                            'clear_duration': clear_duration
                        })

            # Session is now closed - safe to call async methods
            for data in pending_alerts_data:
                alert = data['alert']
                logger.info(
                    f"Alert {alert.id} ({alert.title}) exceeded clear_duration "
                    f"({data['alert_age']:.1f}s >= {data['clear_duration']}s) - verifying condition still true"
                )

                # Verify alert condition is still true before notifying
                # This prevents false alerts when condition was transient (e.g., container stopped then quickly restarted)
                if await self._verify_alert_condition(alert):
                    logger.info(f"Alert {alert.id} condition verified - sending notification")
                    await self._send_notification(alert)
                else:
                    logger.info(f"Alert {alert.id} condition no longer true - auto-resolving without notification")
                    # Condition cleared during grace period - resolve silently
                    with self.db.get_session() as session:
                        alert_to_resolve = session.query(AlertV2).filter(AlertV2.id == alert.id).first()
                        if alert_to_resolve and alert_to_resolve.state == "open":
                            self.engine._resolve_alert(alert_to_resolve, "Condition cleared during grace period")

        except Exception as e:
            logger.error(f"Error checking pending notifications: {e}", exc_info=True)

    async def _verify_alert_condition(self, alert: AlertV2) -> bool:
        """
        Verify that an alert's condition is still true before sending delayed notification.

        This prevents false alerts when:
        - Container stopped briefly then restarted (within grace period)
        - Metric spiked momentarily then returned to normal
        - Host disconnected briefly then reconnected

        Returns: True if condition still true (send notification), False if condition cleared
        """
        try:
            # For container_stopped alerts, verify container is actually still stopped
            if alert.kind == "container_stopped" and alert.scope_type == "container":
                if not self.monitor:
                    logger.warning(f"Cannot verify container state - monitor not available")
                    return True  # Default to sending notification if we can't verify

                # Get current container state from monitor
                containers = await self.monitor.get_containers()
                container = next((c for c in containers if c.short_id == alert.scope_id), None)

                if not container:
                    # Container no longer exists - still consider this a valid alert
                    logger.info(f"Alert {alert.id}: Container no longer found - keeping alert")
                    return True

                # Check if container is running
                if container.state.lower() in ["running", "restarting"]:
                    logger.info(f"Alert {alert.id}: Container now {container.state} - condition cleared")
                    return False

                # Container still stopped/exited - condition still true
                logger.info(f"Alert {alert.id}: Container still {container.state} - condition valid")
                return True

            # For unhealthy alerts, verify container is still unhealthy
            elif alert.kind == "unhealthy" and alert.scope_type == "container":
                if not self.monitor:
                    return True

                containers = await self.monitor.get_containers()
                container = next((c for c in containers if c.short_id == alert.scope_id), None)

                if not container:
                    return True

                if container.state.lower() == "unhealthy":
                    return True
                else:
                    logger.info(f"Alert {alert.id}: Container now {container.state} - no longer unhealthy")
                    return False

            # For other alert types, default to sending notification
            # TODO: Add verification for metric-based alerts and other event types
            return True

        except Exception as e:
            logger.error(f"Error verifying alert condition for {alert.id}: {e}", exc_info=True)
            # On error, default to sending notification (fail-open)
            return True

    async def _send_notification(self, alert: AlertV2):
        """
        Send notification for an alert.

        This is a separate method to centralize notification sending logic.
        """
        logger.info(f"_send_notification called for alert {alert.id} ({alert.title})")
        try:
            # Get the rule for this alert
            rule = self.engine.db.get_alert_rule_v2(alert.rule_id) if alert.rule_id else None

            if not rule:
                logger.warning(f"Cannot send notification - rule not found for alert {alert.id}")
                return

            # Log event to event log system
            if self.event_logger:
                try:
                    from event_logger import EventContext, EventCategory, EventType, EventSeverity

                    event_type = EventType.RULE_TRIGGERED
                    event_message = f"Alert triggered: {alert.message}"

                    # Create event context
                    event_context = EventContext(
                        host_id=alert.scope_id if alert.scope_type == "host" else None,
                        host_name=alert.host_name,
                        container_id=alert.scope_id if alert.scope_type == "container" else None,
                        container_name=alert.container_name,
                    )

                    # Map alert severity to event severity
                    severity_map = {
                        "info": EventSeverity.INFO,
                        "warning": EventSeverity.WARNING,
                        "error": EventSeverity.ERROR,
                        "critical": EventSeverity.CRITICAL,
                    }
                    event_severity = severity_map.get(alert.severity, EventSeverity.INFO)

                    # Log the event
                    self.event_logger.log_event(
                        category=EventCategory.ALERT,
                        event_type=event_type,
                        severity=event_severity,
                        title=alert.title,
                        message=event_message,
                        context=event_context,
                        details={
                            "alert_id": alert.id,
                            "dedup_key": alert.dedup_key,
                            "rule_id": alert.rule_id,
                            "scope_type": alert.scope_type,
                            "scope_id": alert.scope_id,
                            "kind": alert.kind,
                            "state": alert.state,
                            "current_value": alert.current_value,
                            "threshold": alert.threshold,
                        }
                    )

                except Exception as e:
                    logger.error(f"Failed to log alert event: {e}", exc_info=True)

            # Send notification via notification service
            if hasattr(self, 'notification_service') and self.notification_service:
                logger.info(f"Calling notification_service.send_alert_v2 for alert {alert.id}")
                try:
                    result = await self.notification_service.send_alert_v2(alert, rule)
                    logger.info(f"send_alert_v2 returned: {result} for alert {alert.id}")
                except Exception as e:
                    logger.error(f"Failed to send notification for alert {alert.id}: {e}", exc_info=True)
            else:
                logger.warning(f"No notification service available for alert {alert.id}")

        except Exception as e:
            logger.error(f"Error in _send_notification: {e}", exc_info=True)

    async def _evaluate_all_rules(self):
        """Evaluate all enabled metric-driven rules"""
        try:
            # Get all enabled metric-driven rules
            with self.db.get_session() as session:
                rules = session.query(AlertRuleV2).filter(
                    AlertRuleV2.enabled == True,
                    AlertRuleV2.metric != None  # Metric-driven rules
                ).all()

                if not rules:
                    return

                # Group rules by metric type
                rules_by_metric: Dict[str, List[AlertRuleV2]] = {}
                for rule in rules:
                    if rule.metric not in rules_by_metric:
                        rules_by_metric[rule.metric] = []
                    rules_by_metric[rule.metric].append(rule)

            # Fetch container stats if we have stats client
            if self.stats_client:
                await self._evaluate_container_metrics(rules_by_metric)

        except Exception as e:
            logger.error(f"Error evaluating rules: {e}", exc_info=True)

    async def _evaluate_container_metrics(self, rules_by_metric: Dict[str, List[AlertRuleV2]]):
        """Evaluate container metric rules"""
        try:
            # Get all container stats from stats service
            stats = await self.stats_client.get_container_stats()

            if not stats:
                logger.debug("No container stats available")
                return

            # Get containers from monitor's cache (avoids redundant Docker API queries)
            containers = self.monitor.get_last_containers()

            if not containers:
                # Fallback: Cache might be empty during startup
                logger.debug("Container cache empty, querying Docker directly")
                containers = await self.monitor.get_containers()

            # Build lookup map for O(1) container lookups using composite key
            # Stats dict uses composite keys (host_id:container_id), so map must match
            container_map = {f"{c.host_id}:{c.short_id}": c for c in containers}

            # Evaluate each container's metrics
            # Note: container_id here is actually the composite key (host_id:container_id)
            for composite_key, container_stats in stats.items():
                container = container_map.get(composite_key)

                if not container:
                    logger.debug(f"Container {composite_key} not found in cache")
                    continue

                # Fetch container tags for tag-based selector matching
                # Tags are stored with composite key: host_id:container_id
                container_tags = self.db.get_tags_for_subject('container', composite_key)

                # Create evaluation context
                context = EvaluationContext(
                    scope_type="container",
                    scope_id=container.short_id,
                    host_id=container.host_id,
                    host_name=container.host_name,
                    container_id=container.short_id,
                    container_name=container.name,
                    desired_state=container.desired_state or 'unspecified',
                    labels=container.labels or {},
                    tags=container_tags  # Container tags for tag-based filtering
                )

                # Evaluate metrics
                await self._evaluate_container_stats(container_stats, context, rules_by_metric)

        except Exception as e:
            logger.error(f"Error evaluating container metrics: {e}", exc_info=True)

    async def _evaluate_container_stats(
        self,
        stats: Dict[str, Any],
        context: EvaluationContext,
        rules_by_metric: Dict[str, List[AlertRuleV2]]
    ):
        """Evaluate stats for a single container"""
        # Map stats to metric names and evaluate
        metric_mappings = {
            "cpu_percent": stats.get("cpu_percent"),
            "memory_percent": stats.get("memory_percent"),
            "memory_usage": stats.get("memory_usage"),
            "memory_limit": stats.get("memory_limit"),
            "network_rx_bytes": stats.get("network_rx_bytes"),
            "network_tx_bytes": stats.get("network_tx_bytes"),
            "block_read_bytes": stats.get("block_read_bytes"),
            "block_write_bytes": stats.get("block_write_bytes"),
        }

        for metric_name, metric_value in metric_mappings.items():
            if metric_value is None:
                continue

            # Check if we have rules for this metric
            if metric_name not in rules_by_metric:
                continue

            # Evaluate metric against all matching rules
            try:
                alerts = self.engine.evaluate_metric(
                    metric_name,
                    float(metric_value),
                    context
                )

                if alerts:
                    logger.info(
                        f"Alert triggered for {context.container_name}: "
                        f"{metric_name}={metric_value}"
                    )

                    # TODO: Trigger notifications here
                    for alert in alerts:
                        await self._handle_alert_notification(alert)

            except Exception as e:
                logger.error(
                    f"Error evaluating {metric_name} for {context.container_name}: {e}",
                    exc_info=True
                )

    async def _handle_alert_notification(self, alert: AlertV2):
        """
        Handle alert notification

        This is called when an alert is created or updated.

        For alerts with clear_duration:
        - Clear notified_at and defer notification to background task
        - Background task will send notification after clear_duration expires (if still open)
        - This applies to both new and re-triggered alerts

        For alerts without clear_duration:
        - Send notification immediately
        """
        # Check if alert should be deferred based on clear_duration
        if alert.state == "open":
            # Get the rule to check clear_duration
            rule = self.engine.db.get_alert_rule_v2(alert.rule_id) if alert.rule_id else None

            if rule and rule.clear_duration_seconds and rule.clear_duration_seconds > 0:
                # Clear notified_at so the background task will pick it up
                # This applies to both new alerts and re-triggered alerts
                with self.engine.db.get_session() as session:
                    alert_to_update = session.query(AlertV2).filter(AlertV2.id == alert.id).first()
                    if alert_to_update:
                        alert_to_update.notified_at = None
                        session.commit()
                        logger.info(
                            f"Deferring notification for alert {alert.id} - "
                            f"will notify after {rule.clear_duration_seconds}s if still open"
                        )
                        return

        # For alerts without clear_duration, send immediately
        logger.info(
            f"Alert notification: {alert.title} "
            f"(severity={alert.severity}, state={alert.state})"
        )

        # Log event to event log system
        if self.event_logger:
            try:
                # Determine event type based on alert state
                if alert.state == "open":
                    event_type = EventType.RULE_TRIGGERED
                    event_message = f"Alert triggered: {alert.message}"
                elif alert.state == "resolved":
                    event_type = EventType.RULE_TRIGGERED  # Using same type for now
                    event_message = f"Alert resolved: {alert.resolved_reason or 'Condition cleared'}"
                else:
                    event_type = EventType.RULE_TRIGGERED
                    event_message = alert.message

                # Create event context
                event_context = EventContext(
                    host_id=alert.scope_id if alert.scope_type == "host" else None,
                    host_name=alert.host_name,
                    container_id=alert.scope_id if alert.scope_type == "container" else None,
                    container_name=alert.container_name,
                )

                # Map alert severity to event severity
                severity_map = {
                    "info": EventSeverity.INFO,
                    "warning": EventSeverity.WARNING,
                    "error": EventSeverity.ERROR,
                    "critical": EventSeverity.CRITICAL,
                }
                event_severity = severity_map.get(alert.severity, EventSeverity.INFO)

                # Log the event
                self.event_logger.log_event(
                    category=EventCategory.ALERT,
                    event_type=event_type,
                    severity=event_severity,
                    title=alert.title,
                    message=event_message,
                    context=event_context,
                    details={
                        "alert_id": alert.id,
                        "dedup_key": alert.dedup_key,
                        "rule_id": alert.rule_id,
                        "scope_type": alert.scope_type,
                        "scope_id": alert.scope_id,
                        "kind": alert.kind,
                        "state": alert.state,
                        "current_value": alert.current_value,
                        "threshold": alert.threshold,
                    }
                )

                logger.debug(f"Logged alert event to event log: {alert.id}")

            except Exception as e:
                logger.error(f"Failed to log alert event: {e}", exc_info=True)

        # Send notification via notification service
        if alert.state == "open":
            # Only send notifications for new/open alerts, not resolved ones
            # (You might want to make this configurable)
            try:
                # Get the rule for this alert
                rule = self.engine.db.get_alert_rule_v2(alert.rule_id) if alert.rule_id else None

                # Import and get notification service from main
                # The notification service should be passed to evaluation service on init
                if hasattr(self, 'notification_service') and self.notification_service:
                    await self.notification_service.send_alert_v2(alert, rule)
                else:
                    logger.warning("Notification service not available, skipping notification")
            except Exception as e:
                logger.error(f"Failed to send alert notification: {e}", exc_info=True)

    async def _auto_clear_alerts_by_kind(
        self,
        scope_type: str,
        scope_id: str,
        kinds_to_clear: List[str],
        reason: str
    ):
        """
        Auto-clear open alerts of specific kinds for a scope.

        This is used for auto-resolving alerts when opposite conditions occur:
        - Container starts → clear container_stopped alerts
        - Container becomes healthy → clear unhealthy alerts

        Args:
            scope_type: "container" or "host"
            scope_id: Container ID or host ID
            kinds_to_clear: List of alert kinds to clear (e.g., ["container_stopped"])
            reason: Reason for clearing (e.g., "Container started")
        """
        try:
            with self.db.get_session() as session:
                # Find open alerts matching the scope and kinds
                alerts_to_clear = session.query(AlertV2).filter(
                    AlertV2.scope_type == scope_type,
                    AlertV2.scope_id == scope_id,
                    AlertV2.state == "open",
                    AlertV2.kind.in_(kinds_to_clear)
                ).all()

                if alerts_to_clear:
                    logger.info(
                        f"Auto-clearing {len(alerts_to_clear)} alert(s) for {scope_type}:{scope_id} - {reason}"
                    )

                    for alert in alerts_to_clear:
                        # Use engine's resolve method to properly mark as resolved
                        self.engine._resolve_alert(alert, reason)
                        logger.info(f"Auto-cleared alert {alert.id}: {alert.title}")

        except Exception as e:
            logger.error(f"Error auto-clearing alerts: {e}", exc_info=True)

    # ==================== Event-Driven Rule Evaluation ====================

    async def handle_container_event(
        self,
        event_type: str,
        container_id: str,
        container_name: str,
        host_id: str,
        host_name: str,
        event_data: Dict[str, Any]
    ):
        """
        Handle container event for event-driven rules

        Args:
            event_type: Type of event (container_stopped, container_started, etc.)
            container_id: Full container ID
            container_name: Container name
            host_id: Host ID
            host_name: Host name
            event_data: Additional event data (timestamp, exit_code, etc.)
        """
        logger.info(f"V2: Processing {event_type} for {container_name} on {host_name}")
        try:
            # Get desired_state from database
            desired_state = self.db.get_desired_state(host_id, container_id) or 'unspecified'

            # Fetch container tags for tag-based selector matching
            # Tags are stored with composite key: host_id:container_id
            composite_key = f"{host_id}:{container_id}"
            container_tags = self.db.get_tags_for_subject('container', composite_key)

            # Create evaluation context with the data passed in
            context = EvaluationContext(
                scope_type="container",
                scope_id=container_id,
                host_id=host_id,
                host_name=host_name,
                container_id=container_id,
                container_name=container_name,
                desired_state=desired_state,
                labels={},  # Labels not needed for basic event-driven rules
                tags=container_tags  # Container tags for tag-based filtering
            )

            # Auto-clear opposite-state alerts before evaluating new rules
            # If container started, clear any container_stopped alerts
            # If container stopped, clear any container_started alerts (if we add those)
            if event_type == "state_change" and event_data:
                new_state = event_data.get("new_state")

                # Container started → clear container_stopped alerts
                if new_state in ["running", "restarting"]:
                    await self._auto_clear_alerts_by_kind(
                        scope_type="container",
                        scope_id=container_id,
                        kinds_to_clear=["container_stopped"],
                        reason="Container started"
                    )

                # Container became healthy → clear unhealthy alerts
                elif new_state == "healthy":
                    await self._auto_clear_alerts_by_kind(
                        scope_type="container",
                        scope_id=container_id,
                        kinds_to_clear=["unhealthy"],
                        reason="Container became healthy"
                    )

            # Evaluate event-driven rules
            alerts = self.engine.evaluate_event(event_type, context, event_data)

            if alerts:
                logger.info(
                    f"Event-driven alert triggered for {context.container_name}: "
                    f"event={event_type}"
                )

                for alert in alerts:
                    await self._handle_alert_notification(alert)

        except Exception as e:
            logger.error(f"Error handling container event: {e}", exc_info=True)

    async def handle_host_event(
        self,
        event_type: str,
        host_id: str,
        event_data: Dict[str, Any]
    ):
        """
        Handle host event for event-driven rules

        Called by event logger when host events occur.
        """
        try:
            # Get host info from event data
            host_name = event_data.get("host_name", host_id)

            # Fetch host tags for tag-based selector matching
            host_tags = self.db.get_tags_for_subject('host', host_id)
            logger.debug(f"Host {host_name} has tags: {host_tags}")

            # Create evaluation context
            context = EvaluationContext(
                scope_type="host",
                scope_id=host_id,
                host_id=host_id,
                host_name=host_name,
                tags=host_tags  # Host tags for tag-based filtering
            )

            # Evaluate event-driven rules
            alerts = self.engine.evaluate_event(event_type, context, event_data)

            if alerts:
                logger.info(
                    f"Event-driven alert triggered for host {host_name}: "
                    f"event={event_type}"
                )

                for alert in alerts:
                    await self._handle_alert_notification(alert)

        except Exception as e:
            logger.error(f"Error handling host event: {e}", exc_info=True)

    # ==================== Manual Evaluation ====================

    async def evaluate_now(self):
        """Trigger immediate evaluation of all rules (for testing/debugging)"""
        logger.info("Manual evaluation triggered")
        await self._evaluate_all_rules()
