"""
Alert Rule Evaluation Engine for DockMon

Handles both event-driven and metric-driven alert rule evaluation with:
- Deduplication using dedup_key pattern
- Sliding window breach detection for metric rules
- Alert lifecycle management (open → snoozed → resolved)
- Cooldown enforcement
- Grace period support
"""

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from database import DatabaseManager, AlertRuleV2, AlertV2, RuleRuntime, RuleEvaluation
from utils.keys import parse_composite_key

logger = logging.getLogger(__name__)


@dataclass
class EvaluationContext:
    """Context for rule evaluation"""
    scope_type: str  # 'host' | 'container'
    scope_id: str
    host_id: Optional[str] = None
    host_name: Optional[str] = None
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    desired_state: Optional[str] = None  # Container desired state: 'should_run', 'on_demand', 'unspecified'
    labels: Optional[Dict[str, str]] = None
    tags: Optional[List[str]] = None  # Container or host tags for tag-based filtering


@dataclass
class MetricSample:
    """Single metric observation"""
    timestamp: datetime
    value: float
    breached: bool


@dataclass
class PendingEventAlert:
    """Pending event-driven alert waiting for delay to pass"""
    rule_id: str
    rule_name: str
    kind: str
    delay_seconds: int
    triggered_at: datetime
    context: 'EvaluationContext'
    event_type: str
    event_data: Optional[Dict[str, Any]]
    dedup_key: str


@dataclass
class PendingAlertClear:
    """Pending alert clear waiting for clear delay to pass"""
    alert_id: str
    alert_title: str
    rule_id: str
    delay_seconds: int
    clear_started_at: datetime
    reason: str


class AlertEngine:
    """
    Core alert evaluation engine

    Responsibilities:
    - Evaluate rules against events/metrics
    - Manage alert lifecycle (create, update, resolve)
    - Enforce deduplication using dedup_key
    - Track rule runtime state for sliding windows
    - Handle cooldowns and grace periods
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        # Track pending event-driven alerts waiting for delay to pass
        # Key: dedup_key, Value: PendingEventAlert
        self._pending_event_alerts: Dict[str, PendingEventAlert] = {}
        # Track pending alert clears waiting for clear delay to pass
        # Key: alert_id, Value: PendingAlertClear
        self._pending_alert_clears: Dict[str, PendingAlertClear] = {}

    # ==================== Deduplication ====================

    def _make_dedup_key(self, rule_id: str, kind: str, scope_type: str, scope_id: str) -> str:
        """
        Generate deduplication key: {rule_id}|{kind}|{scope_type}:{scope_id}

        Includes rule_id to allow multiple rules to create separate alerts for the same condition.
        For example: A "Warning" rule and a "Critical" rule for container stops can coexist.

        Examples:
        - rule-123|cpu_high|container:abc123
        - rule-456|unhealthy|container:xyz789
        - rule-789|disk_full|host:host-001
        """
        return f"{rule_id}|{kind}|{scope_type}:{scope_id}"

    def _make_runtime_key(self, rule_id: str, scope_type: str, scope_id: str) -> str:
        """
        Generate runtime state key: {rule_id}|{scope_type}:{scope_id}

        One runtime state per (rule, scope) combination
        """
        return f"{rule_id}|{scope_type}:{scope_id}"

    # ==================== Alert Lifecycle ====================

    def _get_or_create_alert(
        self,
        dedup_key: str,
        rule: AlertRuleV2,
        context: EvaluationContext,
        current_value: Optional[float] = None,
        event_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[AlertV2, bool]:
        """
        Get existing alert by dedup_key or create new one

        Returns: (alert, is_new)
        """
        with self.db.get_session() as session:
            # Try to find existing alert
            existing = session.query(AlertV2).filter(AlertV2.dedup_key == dedup_key).first()

            if existing:
                return existing, False

            # Create new alert
            now = datetime.now(timezone.utc)
            alert = AlertV2(
                id=str(uuid.uuid4()),
                dedup_key=dedup_key,
                scope_type=context.scope_type,
                scope_id=context.scope_id,
                kind=rule.kind,
                severity=rule.severity,
                state="open",
                title=self._generate_alert_title(rule, context),
                message=self._generate_alert_message(rule, context, current_value),
                first_seen=now,
                last_seen=now,
                occurrences=1,
                rule_id=rule.id,
                rule_version=rule.version,
                current_value=current_value,
                threshold=rule.threshold,
                rule_snapshot=self._snapshot_rule(rule),
                labels_json=json.dumps(context.labels) if context.labels else None,
                host_name=context.host_name,
                host_id=context.host_id,
                container_name=context.container_name,
                event_context_json=json.dumps(event_data) if event_data else None,
            )

            session.add(alert)
            session.commit()
            session.refresh(alert)

            logger.info(f"Created new alert: {alert.id} ({dedup_key})")
            return alert, True

    def _update_alert(
        self,
        alert: AlertV2,
        current_value: Optional[float] = None,
        increment_occurrences: bool = True,
        event_data: Optional[Dict[str, Any]] = None
    ) -> AlertV2:
        """Update existing alert with new occurrence"""
        with self.db.get_session() as session:
            alert = session.merge(alert)

            # If alert was previously resolved, reopen it
            if alert.state == "resolved":
                alert.state = "open"
                alert.resolved_at = None
                alert.resolved_reason = None
                alert.notified_at = None  # Clear notification timestamp so alert gets re-sent
                logger.info(f"Reopened previously resolved alert {alert.id}")

            # For update_available alerts, clear notified_at if digest changed (new version available)
            # This ensures users get notified when a newer version is released, not just the first time
            if alert.kind == "update_available" and event_data:
                # Get old digest from existing alert context
                old_digest = None
                if alert.event_context_json:
                    try:
                        existing_context = json.loads(alert.event_context_json)
                        old_digest = existing_context.get('latest_digest')
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Get new digest from incoming event
                new_digest = event_data.get('latest_digest')

                # If digest changed (new version available), clear notified_at to re-notify
                if old_digest is not None and new_digest is not None and old_digest != new_digest:
                    alert.notified_at = None
                    logger.info(
                        f"New version available for alert {alert.id} "
                        f"(digest: {old_digest[:12]}... -> {new_digest[:12]}...), will re-notify"
                    )

            alert.last_seen = datetime.now(timezone.utc)
            if increment_occurrences:
                alert.occurrences += 1
            if current_value is not None:
                alert.current_value = current_value
            if event_data is not None:
                # Merge new event_data with existing, preserving important fields like exit_code
                existing_context = {}
                if alert.event_context_json:
                    try:
                        existing_context = json.loads(alert.event_context_json)
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Merge: new data takes precedence, but preserve exit_code if new one is null
                merged_context = {**existing_context, **event_data}
                if event_data.get('exit_code') is None and existing_context.get('exit_code') is not None:
                    merged_context['exit_code'] = existing_context['exit_code']

                alert.event_context_json = json.dumps(merged_context)

            session.commit()
            session.refresh(alert)

            logger.debug(f"Updated alert {alert.id}: occurrences={alert.occurrences}, value={current_value}")
            return alert

    def _resolve_alert(
        self,
        alert: AlertV2,
        reason: str = "Clear condition met"
    ) -> AlertV2:
        """Mark alert as resolved"""
        with self.db.get_session() as session:
            alert = session.merge(alert)
            alert.state = "resolved"
            alert.resolved_at = datetime.now(timezone.utc)
            alert.resolved_reason = reason

            session.commit()
            session.refresh(alert)

            logger.info(f"Resolved alert {alert.id}: {reason}")
            return alert

    def _check_cooldown(self, alert: AlertV2, cooldown_seconds: int) -> bool:
        """
        Check if alert is in cooldown period

        Cooldown prevents notification spam by requiring a minimum time between
        notifications. Uses notified_at (when notification was sent), not last_seen
        (which updates every evaluation cycle).

        Returns: True if in cooldown (should skip notification), False otherwise
        """
        if not alert.notified_at:
            # Never notified, not in cooldown
            return False

        # Handle both naive and aware datetimes
        notified_at = alert.notified_at if alert.notified_at.tzinfo else alert.notified_at.replace(tzinfo=timezone.utc)
        time_since_notification = (datetime.now(timezone.utc) - notified_at).total_seconds()
        return time_since_notification < cooldown_seconds


    # ==================== Event-Driven Evaluation ====================

    def evaluate_event(
        self,
        event_type: str,
        context: EvaluationContext,
        event_data: Optional[Dict[str, Any]] = None
    ) -> List[AlertV2]:
        """
        Evaluate event-driven rules for a specific event

        Event-driven rules fire immediately when conditions match:
        - Container became unhealthy
        - Container churn (3+ restarts in 5m)
        - Host disconnected

        Returns: List of alerts created/updated
        """
        alerts_changed = []

        with self.db.get_session() as session:
            # Find all enabled event-driven rules that match this event
            # Event-driven rules have metric=None
            rules = session.query(AlertRuleV2).filter(
                AlertRuleV2.enabled.is_(True),
                AlertRuleV2.metric == None,
                AlertRuleV2.scope == context.scope_type
            ).all()

            logger.debug(f"Engine: Found {len(rules)} event-driven rules for scope={context.scope_type}")

            for rule in rules:
                logger.debug(f"Engine: Checking rule '{rule.name}' (kind={rule.kind}) against event_type={event_type}")

                # Check if rule matches this event type
                matches_event = self._rule_matches_event(rule, event_type, context, event_data)
                logger.debug(f"Engine: Rule '{rule.name}' matches event: {matches_event}")
                if not matches_event:
                    continue

                # Check selectors
                matches_selectors = self._check_selectors(rule, context)
                logger.debug(f"Engine: Rule '{rule.name}' matches selectors: {matches_selectors}")
                if not matches_selectors:
                    continue

                # Check if we should suppress this alert during container update
                # IMPORTANT: Never suppress update-related alerts (update_completed, update_available, update_failed)
                # These are specifically about the update process and MUST fire during updates
                update_related_kinds = {"update_completed", "update_available", "update_failed"}
                if rule.suppress_during_updates and context.scope_type == "container" and rule.kind not in update_related_kinds:
                    # scope_id is composite key (host_id:container_id), extract SHORT ID
                    _, container_id = parse_composite_key(context.scope_id)
                    is_updating = self._is_container_updating(context.host_id, container_id)
                    if is_updating:
                        logger.info(f"Engine: Rule '{rule.name}' suppressed - container is being updated")
                        continue

                logger.info(f"Engine: Rule '{rule.name}' MATCHED!")

                # Generate dedup key (includes rule_id to allow multiple rules for same condition)
                dedup_key = self._make_dedup_key(rule.id, rule.kind, context.scope_type, context.scope_id)
                logger.debug(f"Engine: Dedup key: {dedup_key}")

                # Check if rule has an alert active delay (Issue #96)
                delay_seconds = rule.alert_active_delay_seconds or 0
                if delay_seconds > 0:
                    # Check if already pending
                    if dedup_key in self._pending_event_alerts:
                        logger.debug(f"Engine: Rule '{rule.name}' already pending, ignoring duplicate event")
                        continue

                    # Add to pending alerts - will be checked by background task
                    pending = PendingEventAlert(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        kind=rule.kind,
                        delay_seconds=delay_seconds,
                        triggered_at=datetime.now(timezone.utc),
                        context=context,
                        event_type=event_type,
                        event_data=event_data,
                        dedup_key=dedup_key
                    )
                    self._pending_event_alerts[dedup_key] = pending
                    logger.info(f"Engine: Rule '{rule.name}' added to pending (delay={delay_seconds}s)")
                    continue

                # No delay - fire immediately
                logger.info(f"Engine: Rule '{rule.name}' firing immediately (no delay)")

                # Get or create alert (pass event_data for template variables)
                alert, is_new = self._get_or_create_alert(dedup_key, rule, context, event_data=event_data)
                logger.debug(f"Engine: Alert {alert.id} - is_new={is_new}")

                # Check notification cooldown
                cooldown = rule.notification_cooldown_seconds or 300
                if not is_new and self._check_cooldown(alert, cooldown):
                    logger.info(f"Engine: Alert {alert.id} in cooldown (notification_cooldown_seconds={cooldown}), skipping notification but updating context")
                    # Still update event_context to preserve important data like exit_code
                    alert = self._update_alert(alert, event_data=event_data, increment_occurrences=False)
                    continue

                # Update alert
                if not is_new:
                    alert = self._update_alert(alert, event_data=event_data)
                    logger.debug(f"Engine: Updated existing alert {alert.id}")

                alerts_changed.append(alert)
                logger.debug(f"Engine: Added alert {alert.id} to alerts_changed list (count={len(alerts_changed)})")
                logger.info(f"Engine: Alert {alert.id} ready for notification")

        if alerts_changed:
            logger.debug(f"Engine: evaluate_event returning {len(alerts_changed)} alerts")
        return alerts_changed

    def check_pending_event_alerts(self) -> List[AlertV2]:
        """
        Check pending event-driven alerts and fire those whose delay has passed.

        Called by background task in evaluation service.

        Returns: List of alerts that were fired
        """
        alerts_fired = []
        now = datetime.now(timezone.utc)
        keys_to_remove = []

        for dedup_key, pending in self._pending_event_alerts.items():
            elapsed = (now - pending.triggered_at).total_seconds()

            if elapsed >= pending.delay_seconds:
                logger.info(
                    f"Engine: Pending alert '{pending.rule_name}' delay passed "
                    f"({elapsed:.1f}s >= {pending.delay_seconds}s), firing now"
                )

                # Get the rule from database to fire the alert
                with self.db.get_session() as session:
                    rule = session.query(AlertRuleV2).filter(
                        AlertRuleV2.id == pending.rule_id
                    ).first()

                    if not rule:
                        logger.warning(f"Engine: Rule {pending.rule_id} not found, removing pending alert")
                        keys_to_remove.append(dedup_key)
                        continue

                    if not rule.enabled:
                        logger.info(f"Engine: Rule '{rule.name}' disabled, removing pending alert")
                        keys_to_remove.append(dedup_key)
                        continue

                    # Fire the alert
                    alert, is_new = self._get_or_create_alert(
                        dedup_key, rule, pending.context, event_data=pending.event_data
                    )

                    if not is_new:
                        alert = self._update_alert(alert, event_data=pending.event_data)

                    alerts_fired.append(alert)
                    keys_to_remove.append(dedup_key)
                    logger.info(f"Engine: Fired delayed alert {alert.id} for rule '{rule.name}'")

        # Remove fired/expired pending alerts
        for key in keys_to_remove:
            del self._pending_event_alerts[key]

        return alerts_fired

    def clear_pending_for_scope(self, scope_type: str, scope_id: str, kinds: Optional[List[str]] = None) -> int:
        """
        Clear pending event alerts for a scope when the condition clears.

        For example, when a container starts, clear any pending container_stopped alerts.

        Args:
            scope_type: 'host' or 'container'
            scope_id: The scope identifier (composite key for containers)
            kinds: Optional list of rule kinds to clear. If None, clears all kinds.

        Returns: Number of pending alerts cleared
        """
        keys_to_remove = []

        for dedup_key, pending in self._pending_event_alerts.items():
            if pending.context.scope_type != scope_type:
                continue
            if pending.context.scope_id != scope_id:
                continue
            if kinds and pending.kind not in kinds:
                continue

            logger.info(
                f"Engine: Clearing pending alert '{pending.rule_name}' for {scope_type}:{scope_id} "
                f"(condition cleared before delay passed)"
            )
            keys_to_remove.append(dedup_key)

        for key in keys_to_remove:
            del self._pending_event_alerts[key]

        return len(keys_to_remove)

    def get_pending_count(self) -> int:
        """Return the number of pending event alerts"""
        return len(self._pending_event_alerts)

    # ==================== Pending Alert Clears (Issue #96) ====================

    def add_pending_alert_clear(
        self,
        alert: AlertV2,
        rule: AlertRuleV2,
        reason: str
    ) -> bool:
        """
        Add an alert to pending clears instead of resolving immediately.

        Called when condition clears but rule has alert_clear_delay_seconds > 0.

        Returns: True if added to pending, False if already pending
        """
        if alert.id in self._pending_alert_clears:
            logger.debug(f"Engine: Alert {alert.id} already pending clear, ignoring")
            return False

        delay_seconds = rule.alert_clear_delay_seconds or 0
        pending = PendingAlertClear(
            alert_id=alert.id,
            alert_title=alert.title,
            rule_id=rule.id,
            delay_seconds=delay_seconds,
            clear_started_at=datetime.now(timezone.utc),
            reason=reason
        )
        self._pending_alert_clears[alert.id] = pending
        logger.info(f"Engine: Alert '{alert.title}' added to pending clear (delay={delay_seconds}s)")
        return True

    def check_pending_alert_clears(self) -> List[str]:
        """
        Check pending alert clears and resolve those whose delay has passed.

        Called by background task in evaluation service.

        Returns: List of alert IDs that were resolved
        """
        alerts_resolved = []
        now = datetime.now(timezone.utc)
        keys_to_remove = []

        for alert_id, pending in self._pending_alert_clears.items():
            elapsed = (now - pending.clear_started_at).total_seconds()

            if elapsed >= pending.delay_seconds:
                logger.info(
                    f"Engine: Pending clear for '{pending.alert_title}' delay passed "
                    f"({elapsed:.1f}s >= {pending.delay_seconds}s), resolving now"
                )

                # Resolve the alert
                with self.db.get_session() as session:
                    alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()

                    if not alert:
                        logger.warning(f"Engine: Alert {alert_id} not found, removing pending clear")
                        keys_to_remove.append(alert_id)
                        continue

                    if alert.state != "open":
                        logger.info(f"Engine: Alert {alert_id} no longer open (state={alert.state}), removing pending clear")
                        keys_to_remove.append(alert_id)
                        continue

                    # Resolve the alert
                    self._resolve_alert(alert, pending.reason)
                    alerts_resolved.append(alert_id)
                    keys_to_remove.append(alert_id)
                    logger.info(f"Engine: Resolved delayed-clear alert {alert_id}: {pending.alert_title}")

        # Remove processed pending clears
        for key in keys_to_remove:
            del self._pending_alert_clears[key]

        return alerts_resolved

    def cancel_pending_clear_for_alert(self, alert_id: str) -> bool:
        """
        Cancel a pending clear when the condition becomes active again.

        For example, if container stops → starts (pending clear) → stops again,
        we should cancel the pending clear since the alert condition is active again.

        Returns: True if a pending clear was cancelled, False otherwise
        """
        if alert_id in self._pending_alert_clears:
            pending = self._pending_alert_clears[alert_id]
            logger.info(
                f"Engine: Cancelling pending clear for '{pending.alert_title}' "
                f"(condition became active again)"
            )
            del self._pending_alert_clears[alert_id]
            return True
        return False

    def cancel_pending_clears_for_scope(self, scope_type: str, scope_id: str, kinds: Optional[List[str]] = None) -> int:
        """
        Cancel pending clears for a scope when condition becomes active again.

        Args:
            scope_type: 'host' or 'container'
            scope_id: The scope identifier
            kinds: Optional list of rule kinds to cancel. If None, cancels all kinds.

        Returns: Number of pending clears cancelled
        """
        keys_to_remove = []

        with self.db.get_session() as session:
            for alert_id, pending in self._pending_alert_clears.items():
                # Get alert to check scope
                alert = session.query(AlertV2).filter(AlertV2.id == alert_id).first()
                if not alert:
                    keys_to_remove.append(alert_id)
                    continue

                if alert.scope_type != scope_type:
                    continue
                if alert.scope_id != scope_id:
                    continue
                if kinds and alert.kind not in kinds:
                    continue

                logger.info(
                    f"Engine: Cancelling pending clear for '{pending.alert_title}' "
                    f"(condition became active again for {scope_type}:{scope_id})"
                )
                keys_to_remove.append(alert_id)

        for key in keys_to_remove:
            if key in self._pending_alert_clears:
                del self._pending_alert_clears[key]

        return len(keys_to_remove)

    def get_pending_clears_count(self) -> int:
        """Return the number of pending alert clears"""
        return len(self._pending_alert_clears)

    def _rule_matches_event(
        self,
        rule: AlertRuleV2,
        event_type: str,
        context: EvaluationContext,
        event_data: Optional[Dict[str, Any]]
    ) -> bool:
        """Check if rule matches the event"""
        # Map rule kinds to event types
        # This will be expanded as we add more rule types

        if rule.kind in ["unhealthy", "container_unhealthy"]:
            # Container health status changed to unhealthy (Docker native health checks)
            return event_type == "state_change" and event_data and event_data.get("new_state") == "unhealthy"

        if rule.kind == "health_check_failed":
            # HTTP/HTTPS health check failed
            return (event_type == "state_change" and
                    event_data and
                    event_data.get("new_state") == "unhealthy" and
                    event_data.get("health_check_type") == "http")

        if rule.kind == "container_stopped":
            # Container stopped/exited (includes clean stops with exit 0 and crashes)
            return event_type == "state_change" and event_data and event_data.get("new_state") in ["stopped", "exited", "dead"]

        if rule.kind in ["container_restart", "container_restarted"]:
            # Container restarted (went through restart cycle)
            return event_type == "state_change" and event_data and event_data.get("new_state") == "restarting"

        if rule.kind in ["host_disconnected", "host_down"]:
            # Host disconnected/offline
            return event_type == "disconnection" and context.scope_type == "host"

        if rule.kind == "update_completed":
            # Container update completed successfully
            # Update events are logged as ACTION_TAKEN with update_completed flag
            return (event_type == "action_taken" and
                    context.scope_type == "container" and
                    event_data and
                    event_data.get("update_completed") == True)

        if rule.kind == "update_available":
            # New update detected for container
            # Update availability is signaled via INFO events with specific metadata
            return event_type == "info" and context.scope_type == "container" and event_data and event_data.get("update_detected") == True

        if rule.kind == "update_failed":
            # Container update failed
            # Update failures are logged as ERROR events with specific metadata
            return event_type == "error" and context.scope_type == "container" and event_data and event_data.get("update_failure") == True

        # Add more mappings as needed
        return False

    def _check_selectors(self, rule: AlertRuleV2, context: EvaluationContext) -> bool:
        """
        Check if rule selectors match the context

        Selectors are optional filters on host/container attributes
        """
        # Host selector - filter by host properties
        if rule.host_selector_json:
            try:
                host_selector = json.loads(rule.host_selector_json)

                # Check include/include_all (host ID filtering)
                # If include or include_all is specified, filter by host IDs
                # If neither is specified but other selectors exist (tags, host_name, etc.), skip ID filtering
                has_id_selector = 'include_all' in host_selector or 'include' in host_selector
                has_other_selectors = any(key in host_selector for key in ['tags', 'host_name', 'host_id'])

                if 'include_all' in host_selector and host_selector['include_all']:
                    # include_all: true means match all hosts (no ID filtering)
                    pass
                elif 'include' in host_selector:
                    # include: ["id1", "id2"] means only match these specific hosts
                    allowed_ids = host_selector['include']
                    if context.host_id not in allowed_ids:
                        return False
                elif has_id_selector and not has_other_selectors:
                    # Has ID selector but it's not set properly and no other selectors - don't match
                    return False
                # If no ID selector but has other selectors (like tags), continue to check those

                # Supported keys: host_name (exact or regex), host_id (exact)
                if 'host_name' in host_selector:
                    pattern = host_selector['host_name']
                    if pattern.startswith('regex:'):
                        # Regex matching
                        regex_pattern = pattern[6:]  # Remove 'regex:' prefix
                        if not re.match(regex_pattern, context.host_name or ''):
                            return False
                    else:
                        # Exact matching
                        if context.host_name != pattern:
                            return False

                if 'host_id' in host_selector:
                    if context.host_id != host_selector['host_id']:
                        return False
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Invalid host_selector_json in rule {rule.id}: {e}")
                return False

        # Container selector - filter by container properties
        if rule.container_selector_json:
            try:
                container_selector = json.loads(rule.container_selector_json)

                # Check include/include_all (container name filtering)
                # If include or include_all is specified, filter by container names
                # If neither is specified but other selectors exist (tags, should_run, etc.), skip name filtering
                has_name_selector = 'include_all' in container_selector or 'include' in container_selector
                has_other_selectors = any(key in container_selector for key in ['tags', 'should_run', 'container_name', 'container_id'])

                if 'include_all' in container_selector and container_selector['include_all']:
                    # include_all: true means match all containers (no name filtering)
                    pass
                elif 'include' in container_selector:
                    # include: ["name1", "name2"] or ["host_id:name1", "host_id:name2"]
                    # Issue #99: Support composite keys to differentiate same-named containers on different hosts
                    allowed_entries = container_selector['include']
                    matched = False
                    for entry in allowed_entries:
                        if ':' in entry and len(entry.split(':')[0]) == 36:
                            # Composite key format: "host_id:container_name" (UUID is 36 chars with dashes)
                            entry_host_id, entry_name = entry.split(':', 1)
                            if context.host_id == entry_host_id and context.container_name == entry_name:
                                matched = True
                                break
                        else:
                            # Legacy format: just container name (backward compatible)
                            if context.container_name == entry:
                                matched = True
                                break
                    if not matched:
                        return False
                elif has_name_selector and not has_other_selectors:
                    # Has name selector but it's not set properly and no other selectors - don't match
                    return False
                # If no name selector but has other selectors (like tags), continue to check those

                # Check should_run filter (for container run mode filtering)
                # should_run: true means desired_state == 'should_run'
                # should_run: false means desired_state == 'on_demand'
                if 'should_run' in container_selector:
                    required_should_run = container_selector['should_run']
                    if required_should_run is True:
                        if context.desired_state != 'should_run':
                            return False
                    elif required_should_run is False:
                        if context.desired_state != 'on_demand':
                            return False

                # Supported keys: container_name (exact or regex), container_id (exact), image (exact or regex)
                if 'container_name' in container_selector:
                    pattern = container_selector['container_name']
                    if pattern.startswith('regex:'):
                        # Regex matching
                        regex_pattern = pattern[6:]  # Remove 'regex:' prefix
                        if not re.match(regex_pattern, context.container_name or ''):
                            return False
                    else:
                        # Exact matching
                        if context.container_name != pattern:
                            return False

                if 'container_id' in container_selector:
                    if context.container_id != container_selector['container_id']:
                        return False

                # Check tags in container selector (match if container has ANY of the required tags)
                if 'tags' in container_selector and container_selector['tags']:
                    required_tags = container_selector['tags']
                    if not context.tags:
                        # Rule requires tags but context has none
                        return False
                    # Match if container has ANY of the required tags
                    if not any(tag in context.tags for tag in required_tags):
                        return False

                # Note: Image matching would require passing image info in context
                # Currently not available in EvaluationContext
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Invalid container_selector_json in rule {rule.id}: {e}")
                return False

        # Check tags in host selector (match if host has ANY of the required tags)
        if rule.host_selector_json:
            try:
                host_selector = json.loads(rule.host_selector_json)
                if 'tags' in host_selector and host_selector['tags']:
                    required_tags = host_selector['tags']
                    if not context.tags:
                        # Rule requires tags but context has none
                        return False
                    # Match if host has ANY of the required tags
                    if not any(tag in context.tags for tag in required_tags):
                        return False
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Invalid host_selector_json for tags in rule {rule.id}: {e}")
                return False

        # Labels selector
        if rule.labels_json:
            try:
                required_labels = json.loads(rule.labels_json)
                if context.labels:
                    # Check if all required labels match
                    for key, value in required_labels.items():
                        if context.labels.get(key) != value:
                            return False
                else:
                    # Rule requires labels but context has none
                    return False
            except json.JSONDecodeError:
                logger.warning(f"Invalid labels_json in rule {rule.id}")
                return False

        return True

    def _is_container_updating(self, host_id: str, container_id: str) -> bool:
        """Check if a container is currently being updated"""
        try:
            from updates.update_executor import get_update_executor
            update_executor = get_update_executor()
            if update_executor:
                return update_executor.is_container_updating(host_id, container_id)
        except Exception as e:
            logger.warning(f"Could not check if container is updating: {e}")
        return False

    # ==================== Metric-Driven Evaluation ====================

    def evaluate_metric(
        self,
        metric_name: str,
        metric_value: float,
        context: EvaluationContext
    ) -> List[AlertV2]:
        """
        Evaluate metric-driven rules for a specific metric

        Metric-driven rules use sliding windows:
        - CPU > 90% for 5 minutes
        - Memory > 80% for 3 minutes
        - Disk usage > 95%

        Returns: List of alerts created/updated
        """
        alerts_changed = []
        now = datetime.now(timezone.utc)

        with self.db.get_session() as session:
            # Find all enabled metric-driven rules for this metric
            rules = session.query(AlertRuleV2).filter(
                AlertRuleV2.enabled.is_(True),
                AlertRuleV2.metric == metric_name,
                AlertRuleV2.scope == context.scope_type
            ).all()

            for rule in rules:
                # Check selectors
                if not self._check_selectors(rule, context):
                    continue

                # Get or create runtime state
                runtime_key = self._make_runtime_key(rule.id, context.scope_type, context.scope_id)
                runtime = session.query(RuleRuntime).filter(RuleRuntime.dedup_key == runtime_key).first()

                if not runtime:
                    # Initialize new runtime state
                    initial_state = {
                        "window_start": now.isoformat(),
                        "samples": [],
                        "breach_count": 0,
                        "breach_started_at": None,
                        "clear_started_at": None,
                        "last_notified_at": None,
                        "last_occurrence_milestone": 0
                    }

                    runtime = RuleRuntime(
                        dedup_key=runtime_key,
                        rule_id=rule.id,
                        state_json=json.dumps(initial_state),
                        updated_at=now
                    )

                    session.add(runtime)
                    session.flush()  # Get the ID without committing

                # Parse state
                state = self._parse_metric_state(runtime.state_json)

                # Check if metric breaches threshold
                breached = self._check_breach(metric_value, rule.threshold, rule.operator)

                # Add sample to sliding window
                sample = MetricSample(timestamp=now, value=metric_value, breached=breached)
                state["samples"].append({
                    "ts": sample.timestamp.isoformat(),
                    "val": sample.value,
                    "breached": sample.breached
                })

                # Trim old samples outside duration window
                active_delay = rule.alert_active_delay_seconds or 0
                if active_delay > 0:
                    cutoff = now - timedelta(seconds=active_delay)
                    state["samples"] = [
                        s for s in state["samples"]
                        if datetime.fromisoformat(s["ts"]) > cutoff
                    ]

                # Count breaches in window
                breach_count = sum(1 for s in state["samples"] if s["breached"])
                state["breach_count"] = breach_count

                # Check if we should fire alert
                should_fire = False
                if rule.occurrences:
                    # Need N breaches in window
                    should_fire = breach_count >= rule.occurrences
                else:
                    # Just need to be breaching
                    should_fire = breached

                # Record evaluation for debugging
                self._record_evaluation(rule.id, context.scope_id, metric_value, breached, now)

                if should_fire:
                    # Track breach start
                    if state["breach_started_at"] is None:
                        state["breach_started_at"] = now.isoformat()

                    # Generate dedup key (includes rule_id to allow multiple rules for same condition)
                    dedup_key = self._make_dedup_key(rule.id, rule.kind, context.scope_type, context.scope_id)

                    # Get or create alert
                    alert, is_new = self._get_or_create_alert(dedup_key, rule, context, metric_value)

                    # Check notification cooldown
                    cooldown = rule.notification_cooldown_seconds or 300
                    if not is_new and self._check_cooldown(alert, cooldown):
                        logger.debug(f"Alert {alert.id} in cooldown, skipping")
                    else:
                        # Update alert
                        if not is_new:
                            alert = self._update_alert(alert, metric_value)

                        alerts_changed.append(alert)

                        # Check grace period before notifying
                        # Alert ready for notification (handled by evaluation_service)
                        logger.info(f"Alert {alert.id} ready for notification")

                else:
                    # Not breaching - check if we should clear
                    # Use clear_threshold if set, otherwise fall back to threshold (Issue #73)
                    effective_clear_threshold = rule.clear_threshold if rule.clear_threshold is not None else rule.threshold
                    clear_breached = self._check_breach(metric_value, effective_clear_threshold, rule.operator)

                    if not clear_breached:
                        # Determine clear delay (alert_clear_delay_seconds, fallback to alert_active_delay, then 60s default)
                        clear_delay = rule.alert_clear_delay_seconds if rule.alert_clear_delay_seconds is not None else (rule.alert_active_delay_seconds if rule.alert_active_delay_seconds else 60)

                        # Handle immediate clearing (alert_clear_delay_seconds = 0)
                        if clear_delay == 0:
                            # Clear immediately without waiting
                            dedup_key = self._make_dedup_key(rule.id, rule.kind, context.scope_type, context.scope_id)
                            existing = session.query(AlertV2).filter(
                                AlertV2.dedup_key == dedup_key,
                                AlertV2.state == "open"
                            ).first()

                            if existing:
                                self._resolve_alert(existing, "Clear condition met (immediate)")
                                alerts_changed.append(existing)

                            # Reset state
                            state["breach_started_at"] = None
                            state["clear_started_at"] = None
                        else:
                            # Track clear start for sustained clearing
                            if state["clear_started_at"] is None:
                                state["clear_started_at"] = now.isoformat()

                            # Check if we've been below clear threshold long enough
                            clear_start = datetime.fromisoformat(state["clear_started_at"])
                            time_clearing = (now - clear_start).total_seconds()

                            if time_clearing >= clear_delay:
                                # Clear the alert
                                dedup_key = self._make_dedup_key(rule.id, rule.kind, context.scope_type, context.scope_id)
                                existing = session.query(AlertV2).filter(
                                    AlertV2.dedup_key == dedup_key,
                                    AlertV2.state == "open"
                                ).first()

                                if existing:
                                    self._resolve_alert(existing, "Clear condition met")
                                    alerts_changed.append(existing)

                                # Reset state
                                state["breach_started_at"] = None
                                state["clear_started_at"] = None
                    else:
                        # Still breaching clear threshold, reset
                        state["clear_started_at"] = None

                # Save updated state
                runtime.state_json = json.dumps(state)
                runtime.updated_at = now
                session.commit()

        return alerts_changed

    def _check_breach(self, value: float, threshold: float, operator: str) -> bool:
        """Check if value breaches threshold"""
        if operator == ">=":
            return value >= threshold
        elif operator == "<=":
            return value <= threshold
        elif operator == "==":
            # Use epsilon comparison for floating point equality (tolerance: 0.001%)
            epsilon = abs(threshold) * 0.00001 if threshold != 0 else 0.00001
            return abs(value - threshold) < epsilon
        elif operator == ">":
            return value > threshold
        elif operator == "<":
            return value < threshold
        else:
            logger.warning(f"Unknown operator: {operator}")
            return False

    def _get_or_create_runtime(self, runtime_key: str, rule_id: str) -> RuleRuntime:
        """Get or create runtime state for rule evaluation"""
        with self.db.get_session() as session:
            runtime = session.query(RuleRuntime).filter(RuleRuntime.dedup_key == runtime_key).first()

            if not runtime:
                # Initialize new runtime state
                initial_state = {
                    "window_start": datetime.now(timezone.utc).isoformat(),
                    "samples": [],
                    "breach_count": 0,
                    "breach_started_at": None,
                    "clear_started_at": None,
                    "last_notified_at": None,
                    "last_occurrence_milestone": 0
                }

                runtime = RuleRuntime(
                    dedup_key=runtime_key,
                    rule_id=rule_id,
                    state_json=json.dumps(initial_state),
                    updated_at=datetime.now(timezone.utc)
                )

                session.add(runtime)
                session.commit()
                session.refresh(runtime)

            return runtime

    def _parse_metric_state(self, state_json: str) -> Dict[str, Any]:
        """Parse metric rule state JSON"""
        try:
            return json.loads(state_json)
        except json.JSONDecodeError:
            # Return default state if invalid
            return {
                "window_start": datetime.now(timezone.utc).isoformat(),
                "samples": [],
                "breach_count": 0,
                "breach_started_at": None,
                "clear_started_at": None,
                "last_notified_at": None,
                "last_occurrence_milestone": 0
            }

    def _record_evaluation(
        self,
        rule_id: str,
        scope_id: str,
        value: float,
        breached: bool,
        timestamp: datetime
    ) -> None:
        """Record rule evaluation for debugging (24h retention)"""
        with self.db.get_session() as session:
            evaluation = RuleEvaluation(
                rule_id=rule_id,
                timestamp=timestamp,
                scope_id=scope_id,
                value=value,
                breached=breached,
                action=None  # Will be set if alert fired
            )

            session.add(evaluation)
            session.commit()

    # ==================== Alert Message Generation ====================

    def _generate_alert_title(self, rule: AlertRuleV2, context: EvaluationContext) -> str:
        """Generate alert title"""
        if context.scope_type == "container":
            container_name = context.container_name or context.scope_id
            host_name = context.host_name or "unknown host"
            return f"{rule.name} - {container_name} on {host_name}"
        elif context.scope_type == "host":
            return f"{rule.name} - {context.host_name or context.scope_id}"
        else:
            return rule.name

    def _generate_alert_message(
        self,
        rule: AlertRuleV2,
        context: EvaluationContext,
        current_value: Optional[float] = None
    ) -> str:
        """Generate alert message"""
        parts = []

        if rule.description:
            parts.append(rule.description)

        if rule.metric and rule.threshold and rule.operator:
            if current_value is not None:
                parts.append(f"{rule.metric} is {current_value:.1f} (threshold: {rule.operator} {rule.threshold})")
            else:
                parts.append(f"{rule.metric} {rule.operator} {rule.threshold}")

        return " • ".join(parts) if parts else "Alert condition met"

    def _snapshot_rule(self, rule: AlertRuleV2) -> str:
        """Create JSON snapshot of rule for audit trail"""
        snapshot = {
            "id": rule.id,
            "name": rule.name,
            "kind": rule.kind,
            "severity": rule.severity,
            "metric": rule.metric,
            "threshold": rule.threshold,
            "operator": rule.operator,
            # Timing fields
            "alert_active_delay_seconds": rule.alert_active_delay_seconds,
            "alert_clear_delay_seconds": rule.alert_clear_delay_seconds,
            "notification_active_delay_seconds": rule.notification_active_delay_seconds,
            "notification_cooldown_seconds": rule.notification_cooldown_seconds,
            "occurrences": rule.occurrences,
            "version": rule.version
        }
        return json.dumps(snapshot)
