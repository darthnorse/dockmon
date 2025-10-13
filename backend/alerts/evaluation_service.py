"""
Alert Evaluation Service

Integrates alert engine with:
- Stats service (metric-driven rules)
- Event logger (event-driven rules)

Runs periodic evaluation of metric-driven rules and processes events for event-driven rules.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

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
        stats_client=None,
        event_logger: Optional[EventLogger] = None,
        evaluation_interval: int = 10  # seconds
    ):
        self.db = db
        self.stats_client = stats_client
        self.event_logger = event_logger
        self.evaluation_interval = evaluation_interval
        self.engine = AlertEngine(db)

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._container_cache: Dict[str, Dict] = {}  # Cache container metadata

    async def start(self):
        """Start the alert evaluation service"""
        if self._running:
            logger.warning("Alert evaluation service already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._evaluation_loop())
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

            # Evaluate each container's metrics
            for container_id, container_stats in stats.items():
                # Get container metadata
                container_info = await self._get_container_info(container_id)

                if not container_info:
                    logger.debug(f"No metadata for container {container_id}")
                    continue

                # Create evaluation context
                context = EvaluationContext(
                    scope_type="container",
                    scope_id=container_id,
                    host_id=container_info.get("host_id"),
                    host_name=container_info.get("host_name"),
                    container_id=container_id,
                    container_name=container_info.get("name"),
                    labels=container_info.get("labels", {})
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

    async def _get_container_info(self, container_id: str) -> Optional[Dict[str, Any]]:
        """
        Get container metadata (name, host, labels)

        This should fetch from the monitor's container cache or database.
        For now, return minimal info.
        """
        # TODO: Integrate with docker_monitor to get actual container info
        # For now, return cached or None
        return self._container_cache.get(container_id)

    def update_container_cache(self, container_id: str, info: Dict[str, Any]):
        """Update container metadata cache"""
        self._container_cache[container_id] = info

    async def _handle_alert_notification(self, alert: AlertV2):
        """
        Handle alert notification

        This is called when an alert is created or updated.
        Should check notification settings and send notifications.
        Also logs alert events to the event log.
        """
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
                await self.event_logger.log(
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

        # TODO: Integrate with notification system to send actual notifications

    # ==================== Event-Driven Rule Evaluation ====================

    async def handle_container_event(
        self,
        event_type: str,
        container_id: str,
        host_id: str,
        event_data: Dict[str, Any]
    ):
        """
        Handle container event for event-driven rules

        Called by event logger when container events occur.
        """
        try:
            # Get container info
            container_info = await self._get_container_info(container_id)

            if not container_info:
                logger.debug(f"No metadata for container {container_id} in event handler")
                return

            # Create evaluation context
            context = EvaluationContext(
                scope_type="container",
                scope_id=container_id,
                host_id=host_id,
                host_name=container_info.get("host_name"),
                container_id=container_id,
                container_name=container_info.get("name"),
                labels=container_info.get("labels", {})
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

            # Create evaluation context
            context = EvaluationContext(
                scope_type="host",
                scope_id=host_id,
                host_id=host_id,
                host_name=host_name
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
