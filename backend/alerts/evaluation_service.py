"""
Alert Evaluation Service

Integrates alert engine with:
- Stats service (metric-driven rules)
- Event logger (event-driven rules)

Runs periodic evaluation of metric-driven rules and processes events for event-driven rules.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from database import DatabaseManager, AlertRuleV2, AlertV2
from alerts.engine import AlertEngine, EvaluationContext
from event_logger import EventLogger, EventContext, EventCategory, EventType, EventSeverity
from utils.keys import make_composite_key, parse_composite_key

logger = logging.getLogger(__name__)


def calculate_next_retry(attempt_count: int) -> datetime:
    """
    Calculate next retry time with exponential backoff.

    Formula: delay = min(5 * 2^attempt, 3600)

    Backoff schedule:
    - Attempt 1: 5s
    - Attempt 2: 10s
    - Attempt 3: 20s
    - Attempt 4: 40s
    - Attempt 5: 80s
    - Attempt 6: 160s (2.6min)
    - Attempt 7: 320s (5.3min)
    - Attempt 8: 640s (10.6min)
    - Attempt 9: 1280s (21.3min)
    - Attempt 10: 2560s (42.6min)
    - Attempt 11+: 3600s (1 hour, capped)

    Over 24h: ~32 total attempts

    Args:
        attempt_count: Number of failed attempts so far

    Returns:
        Datetime when next retry should occur
    """
    from datetime import timedelta
    base_delay = 5  # seconds
    max_delay = 3600  # 1 hour cap
    delay = min(base_delay * (2 ** attempt_count), max_delay)
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


def should_give_up_retry(first_attempt_time: datetime) -> bool:
    """
    Determine if we should give up retrying after 24 hours.

    Args:
        first_attempt_time: When the first notification attempt occurred

    Returns:
        True if more than 24 hours have elapsed since first attempt
    """
    from datetime import timedelta
    if not first_attempt_time:
        return False
    max_window = timedelta(hours=24)
    # Ensure timezone-aware comparison
    if not first_attempt_time.tzinfo:
        first_attempt_time = first_attempt_time.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - first_attempt_time
    return elapsed > max_window


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
        self._snooze_task: Optional[asyncio.Task] = None
        self._blackout_task: Optional[asyncio.Task] = None

        # Track blackout state for transition detection
        self._last_blackout_state = False

    async def start(self):
        """Start the alert evaluation service"""
        if self._running:
            logger.warning("Alert evaluation service already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._evaluation_loop())
        self._notification_task = asyncio.create_task(self._pending_notifications_loop())
        self._snooze_task = asyncio.create_task(self._snooze_expiry_loop())
        self._blackout_task = asyncio.create_task(self._blackout_transition_loop())
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

        if self._snooze_task:
            self._snooze_task.cancel()
            try:
                await self._snooze_task
            except asyncio.CancelledError:
                pass

        if self._blackout_task:
            self._blackout_task.cancel()
            try:
                await self._blackout_task
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
                # Exclude alerts suppressed by blackout (will be processed when blackout ends)
                # Respect exponential backoff: only retry if next_retry_at is NULL or in the past
                # Use joinedload to eagerly load rules (avoids N+1 query)
                now = datetime.now(timezone.utc)
                pending_alerts = session.query(AlertV2).options(
                    joinedload(AlertV2.rule)
                ).filter(
                    AlertV2.state == "open",
                    AlertV2.notified_at == None,
                    AlertV2.suppressed_by_blackout == False,
                    or_(
                        AlertV2.next_retry_at == None,  # Never attempted or no retry scheduled
                        AlertV2.next_retry_at <= now  # Retry time has passed
                    )
                ).all()

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

    async def _snooze_expiry_loop(self):
        """
        Background task to check for expired snoozes every 60 seconds.

        When an alert is snoozed, it has a snoozed_until timestamp. Once that
        time passes, the alert should automatically return to 'open' state.
        """
        check_interval = 60  # Check every 60 seconds

        while self._running:
            try:
                await self._check_expired_snoozes()
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in snooze expiry loop: {e}", exc_info=True)
                await asyncio.sleep(check_interval)

    async def _check_expired_snoozes(self):
        """Un-snooze alerts where snoozed_until has expired"""
        try:
            with self.db.get_session() as session:
                now = datetime.now(timezone.utc)
                expired = session.query(AlertV2).filter(
                    AlertV2.state == "snoozed",
                    AlertV2.snoozed_until <= now
                ).all()

                for alert in expired:
                    alert.state = "open"
                    alert.snoozed_until = None
                    logger.info(f"Auto-unsnoozed alert {alert.id}: {alert.title}")

                if expired:
                    session.commit()
                    logger.info(f"Auto-unsnoozed {len(expired)} expired alerts")

        except Exception as e:
            logger.error(f"Error checking expired snoozes: {e}", exc_info=True)

    async def _blackout_transition_loop(self):
        """
        Background task to detect blackout window transitions.

        Checks every 30 seconds for blackout state changes. When a blackout window ends,
        all suppressed alerts are re-evaluated. If the condition is still true, the alert
        is sent. If the condition cleared during blackout, the alert is auto-resolved.
        """
        check_interval = 30  # Check every 30 seconds

        while self._running:
            try:
                await self._check_blackout_transitions()
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in blackout transition loop: {e}", exc_info=True)
                await asyncio.sleep(check_interval)

    async def _check_blackout_transitions(self):
        """
        Detect when blackout window ends and process suppressed alerts.

        When blackout ends:
        1. Find all alerts suppressed during blackout
        2. Re-verify each alert's condition
        3. If still true → send notification
        4. If no longer true → auto-resolve silently
        """
        try:
            # Check if notification service is available
            if not self.notification_service:
                return

            # Get current blackout state
            is_blackout, window_name = self.notification_service.blackout_manager.is_in_blackout_window()

            # Detect transition from blackout to non-blackout
            if self._last_blackout_state and not is_blackout:
                logger.info("Blackout window ended - processing suppressed alerts")

                # Find ALL suppressed alerts (both open and resolved)
                # We need to clear the flag on all of them to prevent issues when alerts reopen later
                with self.db.get_session() as session:
                    suppressed_alerts = session.query(AlertV2).options(
                        joinedload(AlertV2.rule)
                    ).filter(
                        AlertV2.suppressed_by_blackout == True
                    ).all()

                    if suppressed_alerts:
                        logger.info(f"Found {len(suppressed_alerts)} suppressed alerts to process")

                # Process each suppressed alert outside the session
                for alert in suppressed_alerts:
                    try:
                        # Only process and potentially send notifications for OPEN alerts
                        if alert.state == "open":
                            # Re-verify the alert condition
                            if await self._verify_alert_condition(alert):
                                # Condition still true - send notification
                                logger.info(f"Alert {alert.id} ({alert.title}) still active - sending notification")
                                await self._send_notification(alert)
                            else:
                                # Condition cleared during blackout - auto-resolve silently
                                logger.info(f"Alert {alert.id} ({alert.title}) cleared during blackout - auto-resolving")
                                with self.db.get_session() as session:
                                    alert_to_resolve = session.query(AlertV2).filter(AlertV2.id == alert.id).first()
                                    if alert_to_resolve and alert_to_resolve.state == "open":
                                        self.engine._resolve_alert(
                                            alert_to_resolve,
                                            "Auto-resolved: condition cleared during blackout window"
                                        )
                                        session.commit()

                        # Clear suppression flag on ALL suppressed alerts (open, resolved, etc.)
                        # This ensures the flag doesn't persist if the alert is reopened later
                        with self.db.get_session() as session:
                            alert_to_clear = session.query(AlertV2).filter(AlertV2.id == alert.id).first()
                            if alert_to_clear:
                                alert_to_clear.suppressed_by_blackout = False
                                session.commit()
                                logger.debug(f"Cleared suppression flag on alert {alert.id} (state={alert.state})")
                    except Exception as e:
                        logger.error(f"Error processing suppressed alert {alert.id}: {e}", exc_info=True)

            # Update state for next check
            self._last_blackout_state = is_blackout

        except Exception as e:
            logger.error(f"Error checking blackout transitions: {e}", exc_info=True)

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
                # CRITICAL: Match by both short_id AND host_id to prevent cross-host confusion in multi-host setups
                # Parse composite scope_id to extract short container ID
                _, container_short_id = parse_composite_key(alert.scope_id)
                containers = await self.monitor.get_containers()
                container = next((c for c in containers
                                if c.short_id == container_short_id and c.host_id == alert.host_id), None)

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

                # CRITICAL: Match by both short_id AND host_id to prevent cross-host confusion
                # Parse composite scope_id to extract short container ID
                _, container_short_id = parse_composite_key(alert.scope_id)
                containers = await self.monitor.get_containers()
                container = next((c for c in containers
                                if c.short_id == container_short_id and c.host_id == alert.host_id), None)

                if not container:
                    return True

                if container.state.lower() == "unhealthy":
                    return True
                else:
                    logger.info(f"Alert {alert.id}: Container now {container.state} - no longer unhealthy")
                    return False

            # For metric-based alerts (CPU, memory), re-check current metric value
            elif alert.kind in ["cpu_high", "memory_high"] and alert.scope_type == "container":
                if not self.stats_client:
                    logger.debug(f"Alert {alert.id}: Stats client not available, cannot verify metric")
                    return True  # Cannot verify without stats, send notification

                try:
                    # Get current stats for this container
                    # scope_id is already a composite key {host_id}:{container_id}
                    stats = await self.stats_client.get_container_stats()
                    container_key = alert.scope_id
                    current_stats = stats.get(container_key)

                    if not current_stats:
                        # Container gone or no stats - keep alert
                        logger.debug(f"Alert {alert.id}: No current stats found, keeping alert")
                        return True

                    # Get rule to check threshold
                    rule = self.engine.db.get_alert_rule_v2(alert.rule_id) if alert.rule_id else None
                    if not rule:
                        logger.debug(f"Alert {alert.id}: Rule not found, cannot verify threshold")
                        return True

                    # Check if metric still breaching
                    metric_name = "cpu_percent" if alert.kind == "cpu_high" else "memory_percent"
                    current_value = current_stats.get(metric_name)

                    if current_value is None:
                        logger.debug(f"Alert {alert.id}: Metric {metric_name} not in current stats")
                        return True

                    # Use engine's breach checking logic
                    breached = self.engine._check_breach(current_value, rule.threshold, rule.operator)
                    if not breached:
                        logger.info(
                            f"Alert {alert.id}: Metric {metric_name} no longer breaching "
                            f"(current: {current_value:.1f}%, threshold: {rule.threshold}, operator: {rule.operator}) - condition cleared"
                        )
                        return False

                    logger.debug(f"Alert {alert.id}: Metric {metric_name} still breaching (current: {current_value:.1f}%)")
                    return True

                except Exception as e:
                    logger.error(f"Error verifying metric alert {alert.id}: {e}", exc_info=True)
                    return True  # On error, send notification

            # For host disconnected alerts, check if host reconnected
            elif alert.kind in ["host_disconnected", "host_down"] and alert.scope_type == "host":
                if not self.monitor:
                    return True

                try:
                    # Check if host is online in monitor
                    host = self.db.get_host(alert.scope_id)
                    if host and host.is_active:
                        # Check if host is actually online (not just client exists)
                        # Bug fix: client object persists even when host is offline
                        monitor_host = self.monitor.hosts.get(alert.scope_id)
                        if monitor_host and monitor_host.status == "online":
                            logger.info(f"Alert {alert.id}: Host {host.name} reconnected - condition cleared")
                            return False

                    logger.debug(f"Alert {alert.id}: Host still disconnected")
                    return True

                except Exception as e:
                    logger.error(f"Error verifying host alert {alert.id}: {e}", exc_info=True)
                    return True

            # For other alert types, default to sending notification
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

            # Send notification via notification service with exponential backoff retry logic
            now = datetime.now(timezone.utc)

            # Determine if this is a permanent failure (no retry) or temporary (retry with backoff)
            permanent_failure = False
            notification_result = False

            if not rule:
                # Rule was deleted - permanent failure
                logger.warning(f"Rule not found for alert {alert.id} - permanent failure")
                permanent_failure = True
            elif not hasattr(self, 'notification_service') or not self.notification_service:
                # No notification service - permanent failure
                logger.warning(f"No notification service available for alert {alert.id}")
                permanent_failure = True
            else:
                # Try to send notification
                logger.info(f"Calling notification_service.send_alert_v2 for alert {alert.id}")
                try:
                    notification_result = await self.notification_service.send_alert_v2(alert, rule)
                    logger.info(f"send_alert_v2 returned: {notification_result} for alert {alert.id}")

                    # Check if failure was due to no channels (permanent)
                    if not notification_result:
                        try:
                            channel_ids = json.loads(rule.notify_channels_json) if rule.notify_channels_json else []
                            if not channel_ids:
                                logger.info(f"No channels configured for rule {rule.name} - permanent failure")
                                permanent_failure = True
                        except (json.JSONDecodeError, TypeError, AttributeError):
                            # Can't parse channels - treat as permanent to avoid infinite retry
                            logger.warning(f"Cannot parse channels for rule {rule.name} - treating as permanent failure")
                            permanent_failure = True

                except Exception as e:
                    logger.error(f"Exception sending notification for alert {alert.id}: {e}", exc_info=True)
                    # Exception is a temporary failure - will retry

            # Update database with retry state
            with self.engine.db.get_session() as session:
                alert_to_update = session.query(AlertV2).filter(AlertV2.id == alert.id).first()
                if not alert_to_update:
                    return

                # Track first attempt time (for 24h timeout)
                if not alert_to_update.last_notification_attempt_at:
                    alert_to_update.last_notification_attempt_at = now

                # Increment attempt counter
                alert_to_update.notification_count = (alert_to_update.notification_count or 0) + 1

                if notification_result:
                    # SUCCESS - mark as notified, clear retry state
                    alert_to_update.notified_at = now
                    alert_to_update.next_retry_at = None
                    logger.info(f"Alert {alert.id} notification sent successfully (attempt {alert_to_update.notification_count})")

                elif permanent_failure:
                    # PERMANENT FAILURE - mark as notified to stop retrying
                    alert_to_update.notified_at = now
                    alert_to_update.next_retry_at = None
                    logger.warning(f"Alert {alert.id} permanent failure - marking as notified to stop retries")

                else:
                    # TEMPORARY FAILURE - check if should give up or schedule retry
                    first_attempt = alert_to_update.last_notification_attempt_at

                    if should_give_up_retry(first_attempt):
                        # Give up after 24 hours
                        alert_to_update.notified_at = now
                        alert_to_update.next_retry_at = None
                        logger.error(
                            f"Alert {alert.id} failed for 24+ hours - giving up after "
                            f"{alert_to_update.notification_count} attempts"
                        )
                    else:
                        # Schedule retry with exponential backoff
                        alert_to_update.next_retry_at = calculate_next_retry(alert_to_update.notification_count)
                        time_until_retry = (alert_to_update.next_retry_at - now).total_seconds()
                        logger.info(
                            f"Alert {alert.id} will retry in {time_until_retry:.0f}s "
                            f"(attempt {alert_to_update.notification_count}, "
                            f"next: {alert_to_update.next_retry_at.strftime('%H:%M:%S')})"
                        )

                session.commit()

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
                await self._evaluate_host_metrics(rules_by_metric)

        except Exception as e:
            logger.error(f"Error evaluating rules: {e}", exc_info=True)
            # Create system alert to notify users of evaluation failure
            await self._create_system_alert(
                title="Alert Rule Evaluation Failed",
                message=f"Failed to evaluate alert rules: {str(e)[:500]}",  # Truncate long error messages
                severity="error"
            )

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
            container_map = {make_composite_key(c.host_id, c.short_id): c for c in containers}

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
                # Use composite key for scope_id to prevent cross-host collisions
                context = EvaluationContext(
                    scope_type="container",
                    scope_id=make_composite_key(container.host_id, container.short_id),
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

                    # Trigger notifications for all matched alerts
                    for alert in alerts:
                        await self._handle_alert_notification(alert)

            except Exception as e:
                logger.error(
                    f"Error evaluating {metric_name} for {context.container_name}: {e}",
                    exc_info=True
                )

    async def _evaluate_host_metrics(self, rules_by_metric: Dict[str, List[AlertRuleV2]]):
        """Evaluate host metric rules"""
        try:
            # Get all host stats from stats service
            stats = await self.stats_client.get_host_stats()

            if not stats:
                logger.debug("No host stats available")
                return

            # Get hosts from monitor
            hosts = list(self.monitor.hosts.values())

            if not hosts:
                logger.debug("No hosts available")
                return

            # Evaluate each host's metrics
            for host in hosts:
                host_stats = stats.get(host.id)

                if not host_stats:
                    logger.debug(f"Host {host.name} stats not found")
                    continue

                # Fetch host tags for tag-based selector matching
                host_tags = self.db.get_tags_for_subject('host', host.id)

                # Create evaluation context
                context = EvaluationContext(
                    scope_type="host",
                    scope_id=host.id,
                    host_id=host.id,
                    host_name=host.name,
                    tags=host_tags
                )

                # Evaluate metrics
                await self._evaluate_host_stats(host_stats, context, rules_by_metric)

        except Exception as e:
            logger.error(f"Error evaluating host metrics: {e}", exc_info=True)

    async def _evaluate_host_stats(
        self,
        stats: Dict[str, Any],
        context: EvaluationContext,
        rules_by_metric: Dict[str, List[AlertRuleV2]]
    ):
        """Evaluate stats for a single host"""
        # Map stats to metric names and evaluate
        metric_mappings = {
            "cpu_percent": stats.get("cpu_percent"),
            "memory_percent": stats.get("memory_percent"),
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
                        f"Alert triggered for host {context.host_name}: "
                        f"{metric_name}={metric_value}"
                    )

                    # Trigger notifications for all matched alerts
                    for alert in alerts:
                        await self._handle_alert_notification(alert)

            except Exception as e:
                logger.error(
                    f"Error evaluating {metric_name} for host {context.host_name}: {e}",
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
        - Container starts → clear container_stopped alerts (if rule.auto_resolve=True)
        - Container becomes healthy → clear unhealthy alerts (if rule.auto_resolve=True)

        Only alerts whose rules have auto_resolve=True will be cleared.

        Args:
            scope_type: "container" or "host"
            scope_id: Container ID or host ID
            kinds_to_clear: List of alert kinds to clear (e.g., ["container_stopped"])
            reason: Reason for clearing (e.g., "Container started")
        """
        try:
            with self.db.get_session() as session:
                # Find open alerts matching the scope and kinds
                # Join with rules to check auto_resolve setting
                alerts_to_check = session.query(AlertV2).join(
                    AlertRuleV2, AlertV2.rule_id == AlertRuleV2.id
                ).filter(
                    AlertV2.scope_type == scope_type,
                    AlertV2.scope_id == scope_id,
                    AlertV2.state == "open",
                    AlertV2.kind.in_(kinds_to_clear)
                ).all()

                # Filter to only alerts whose rules have auto_resolve=True
                alerts_to_clear = []
                for alert in alerts_to_check:
                    rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == alert.rule_id).first()
                    if rule and rule.auto_resolve:
                        alerts_to_clear.append(alert)
                    else:
                        logger.debug(
                            f"Skipping auto-clear for alert {alert.id} ({alert.title}) - "
                            f"rule auto_resolve={rule.auto_resolve if rule else None}"
                        )

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
        logger.debug(f"V2: Processing {event_type} for {container_name} ({container_id}) on {host_name} ({host_id[:8]})")
        try:
            # Get desired_state from database
            desired_state = self.db.get_desired_state(host_id, container_id) or 'unspecified'

            # Fetch container tags for tag-based selector matching
            # Tags are stored with composite key: host_id:container_id
            composite_key = make_composite_key(host_id, container_id)
            container_tags = self.db.get_tags_for_subject('container', composite_key)

            # Create evaluation context with the data passed in
            # Use composite key for scope_id to prevent cross-host collisions
            context = EvaluationContext(
                scope_type="container",
                scope_id=make_composite_key(host_id, container_id),
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
                # Use composite key for cross-host safety
                if new_state in ["running", "restarting"]:
                    await self._auto_clear_alerts_by_kind(
                        scope_type="container",
                        scope_id=make_composite_key(host_id, container_id),
                        kinds_to_clear=["container_stopped"],
                        reason="Container started"
                    )

                # Container became healthy → clear unhealthy alerts
                elif new_state == "healthy":
                    await self._auto_clear_alerts_by_kind(
                        scope_type="container",
                        scope_id=make_composite_key(host_id, container_id),
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

    # ==================== Cleanup & Maintenance ====================

    async def auto_resolve_orphaned_container_alerts(self) -> int:
        """
        Auto-resolve open alerts for containers that no longer exist.

        This prevents the alerts table from filling with orphaned alerts when
        containers are permanently deleted.

        Returns:
            Number of alerts auto-resolved
        """
        resolved_count = 0

        try:
            # Extract alert data and close session BEFORE async Docker calls
            container_alerts_to_check = []
            with self.db.get_session() as session:
                # Get all open/snoozed container-scoped alerts
                open_alerts = session.query(AlertV2).filter(
                    AlertV2.scope_type == 'container',
                    AlertV2.state.in_(['open', 'snoozed'])
                ).all()

                # Extract data we need while session is open
                for alert in open_alerts:
                    container_alerts_to_check.append({
                        'id': alert.id,
                        'scope_id': alert.scope_id,  # Composite key {host_id}:{container_id}
                        'container_name': alert.container_name,
                        'host_id': alert.host_id
                    })

            # Session is now closed - safe for async operations
            if not self.monitor:
                logger.warning("Cannot auto-resolve orphaned alerts - monitor not available")
                return 0

            # Get all existing containers from monitor
            containers = await self.monitor.get_containers()

            # Build set of existing container composite keys {host_id}:{container_id}
            existing_container_ids = {make_composite_key(c.host_id, c.short_id) for c in containers}

            # Check each alert to see if container still exists
            alerts_to_resolve = []
            for alert_data in container_alerts_to_check:
                if alert_data['scope_id'] not in existing_container_ids:
                    alerts_to_resolve.append(alert_data)
                    logger.info(
                        f"Container {alert_data['container_name']} ({alert_data['scope_id']}) "
                        f"no longer exists, will auto-resolve alert {alert_data['id']}"
                    )

            # Reopen session to update alerts
            if alerts_to_resolve:
                with self.db.get_session() as session:
                    for alert_info in alerts_to_resolve:
                        alert = session.query(AlertV2).filter(AlertV2.id == alert_info['id']).first()
                        if alert and alert.state in ['open', 'snoozed']:
                            alert.state = 'resolved'
                            alert.resolved_at = datetime.now(timezone.utc)
                            alert.resolved_reason = 'Container deleted'
                            resolved_count += 1

                    session.commit()
                    logger.info(f"Auto-resolved {resolved_count} alerts for deleted containers")

            return resolved_count

        except Exception as e:
            logger.error(f"Error auto-resolving orphaned container alerts: {e}", exc_info=True)
            return resolved_count

    async def _create_system_alert(self, title: str, message: str, severity: str = "error"):
        """
        Create a system alert for internal failures.

        System alerts notify users when the alert system itself encounters problems,
        such as rule evaluation failures, database errors, or service crashes.

        Args:
            title: Alert title
            message: Detailed error message
            severity: Alert severity ('warning' or 'error')
        """
        try:
            # Get or create the system alert rule
            system_rule = self.db.get_or_create_system_alert_rule()

            # Create evaluation context for system scope
            context = EvaluationContext(
                scope_type="system",
                scope_id="alert_service",
                host_id=None,
                host_name="Alert System"
            )

            # Create dedup key for this specific error type
            dedup_key = f"{system_rule.id}|system_error|system:alert_service"

            # Get or create the alert (deduplicates if already exists)
            alert, is_new = self.engine._get_or_create_alert(
                dedup_key=dedup_key,
                rule=system_rule,
                context=context
            )

            if not is_new:
                # Update existing alert with new occurrence
                alert = self.engine._update_alert(alert)

            # Send notification
            await self._send_notification(alert)

            logger.info(f"Created system alert: {title}")

        except Exception as e:
            # Fail silently - we don't want system alert creation to crash the service
            logger.error(f"Failed to create system alert: {e}", exc_info=True)

    # ==================== Manual Evaluation ====================

    async def evaluate_now(self):
        """Trigger immediate evaluation of all rules (for testing/debugging)"""
        logger.info("Manual evaluation triggered")
        await self._evaluate_all_rules()
