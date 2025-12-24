"""
Alert Rule Input Validation
Validates rule definitions before creation/update to prevent invalid configurations
"""

import re
import json
from typing import Dict, Any, Optional
from datetime import datetime


class AlertRuleValidationError(Exception):
    """Raised when rule validation fails"""
    pass


class AlertRuleValidator:
    """Validates alert rule configurations"""

    # Validation limits
    MAX_THRESHOLD_PERCENTAGE = 100
    MIN_THRESHOLD_PERCENTAGE = 0
    MIN_DURATION_SECONDS = 1
    MAX_DURATION_SECONDS = 86400  # 24 hours
    MIN_OCCURRENCES = 1
    MAX_OCCURRENCES = 100
    MAX_SELECTOR_SIZE_BYTES = 10000  # 10KB
    MAX_LABELS_SIZE_BYTES = 5000  # 5KB
    MAX_DEPENDENCIES = 5
    MAX_NOTIFICATION_CHANNELS = 10
    MAX_UNHEALTHY_COUNT = 1000

    VALID_SCOPES = {'host', 'container', 'group'}
    VALID_SEVERITIES = {'info', 'warning', 'error', 'critical'}
    VALID_OPERATORS = {'>=', '<=', '==', '>', '<', '!='}
    VALID_NOTIFICATION_CHANNELS = {'slack', 'discord', 'telegram', 'pushover', 'gotify', 'ntfy', 'smtp', 'webhook'}

    # Percentage-based metrics
    PERCENTAGE_METRICS = {
        'docker_cpu_workload_pct',
        'docker_mem_workload_pct',
        'disk_free_pct',
        'disk_used_pct'
    }

    # Count-based metrics
    COUNT_METRICS = {
        'unhealthy_count',
        'restart_count',
        'container_count'
    }

    def validate_rule(self, rule_data: Dict[str, Any]) -> None:
        """
        Validate complete rule configuration
        Raises AlertRuleValidationError if invalid
        """
        # Required fields
        self._validate_required_fields(rule_data)

        # Scope and kind
        self._validate_scope(rule_data.get('scope'))
        self._validate_kind(rule_data.get('kind'))

        # Severity
        self._validate_severity(rule_data.get('severity'))

        # Thresholds (for metric-driven rules)
        if rule_data.get('metric'):
            self._validate_threshold(rule_data)

        # Durations
        self._validate_durations(rule_data)

        # Occurrences
        if rule_data.get('occurrences') is not None:
            self._validate_occurrences(rule_data.get('occurrences'))

        # Selectors
        self._validate_selectors(rule_data)

        # Notifications
        self._validate_notifications(rule_data)

        # Dependencies
        self._validate_dependencies(rule_data)

    def _validate_required_fields(self, rule_data: Dict[str, Any]) -> None:
        """Validate presence of required fields"""
        required = ['name', 'scope', 'kind', 'severity']
        missing = [field for field in required if not rule_data.get(field)]

        if missing:
            raise AlertRuleValidationError(
                f"Missing required fields: {', '.join(missing)}"
            )

    def _validate_scope(self, scope: Optional[str]) -> None:
        """Validate rule scope"""
        if not scope:
            raise AlertRuleValidationError("Scope is required")

        if scope not in self.VALID_SCOPES:
            raise AlertRuleValidationError(
                f"Invalid scope '{scope}'. Must be one of: {', '.join(self.VALID_SCOPES)}"
            )

    def _validate_kind(self, kind: Optional[str]) -> None:
        """Validate rule kind"""
        if not kind:
            raise AlertRuleValidationError("Kind is required")

        # Kind should be alphanumeric with underscores
        if not re.match(r'^[a-z0-9_]+$', kind):
            raise AlertRuleValidationError(
                "Kind must contain only lowercase letters, numbers, and underscores"
            )

    def _validate_severity(self, severity: Optional[str]) -> None:
        """Validate alert severity"""
        if not severity:
            raise AlertRuleValidationError("Severity is required")

        if severity not in self.VALID_SEVERITIES:
            raise AlertRuleValidationError(
                f"Invalid severity '{severity}'. Must be one of: {', '.join(self.VALID_SEVERITIES)}"
            )

    def _validate_threshold(self, rule_data: Dict[str, Any]) -> None:
        """Validate threshold configuration"""
        metric = rule_data.get('metric')
        threshold = rule_data.get('threshold')
        operator = rule_data.get('operator')
        clear_threshold = rule_data.get('clear_threshold')

        if not metric:
            raise AlertRuleValidationError("Metric is required for metric-driven rules")

        if threshold is None:
            raise AlertRuleValidationError("Threshold is required for metric-driven rules")

        if not operator:
            raise AlertRuleValidationError("Operator is required for metric-driven rules")

        # Type check
        if not isinstance(threshold, (int, float)):
            raise AlertRuleValidationError("Threshold must be a number")

        if clear_threshold is not None and not isinstance(clear_threshold, (int, float)):
            raise AlertRuleValidationError("Clear threshold must be a number")

        # Validate operator
        if operator not in self.VALID_OPERATORS:
            raise AlertRuleValidationError(
                f"Invalid operator '{operator}'. Must be one of: {', '.join(self.VALID_OPERATORS)}"
            )

        # Range validation based on metric type
        if metric in self.PERCENTAGE_METRICS:
            if not self.MIN_THRESHOLD_PERCENTAGE <= threshold <= self.MAX_THRESHOLD_PERCENTAGE:
                raise AlertRuleValidationError(
                    f"Percentage metric threshold must be between "
                    f"{self.MIN_THRESHOLD_PERCENTAGE} and {self.MAX_THRESHOLD_PERCENTAGE}"
                )

            if clear_threshold is not None:
                if not self.MIN_THRESHOLD_PERCENTAGE <= clear_threshold <= self.MAX_THRESHOLD_PERCENTAGE:
                    raise AlertRuleValidationError(
                        f"Percentage metric clear threshold must be between "
                        f"{self.MIN_THRESHOLD_PERCENTAGE} and {self.MAX_THRESHOLD_PERCENTAGE}"
                    )

        elif metric in self.COUNT_METRICS:
            if threshold < 0:
                raise AlertRuleValidationError("Count metric threshold must be non-negative")

            if metric == 'unhealthy_count' and threshold > self.MAX_UNHEALTHY_COUNT:
                raise AlertRuleValidationError(
                    f"Unhealthy count threshold must be <= {self.MAX_UNHEALTHY_COUNT}"
                )

        # Clear threshold sanity check
        if clear_threshold is not None:
            if operator == '>=' and clear_threshold >= threshold:
                raise AlertRuleValidationError(
                    "Clear threshold must be below threshold for >= operator"
                )
            elif operator == '<=' and clear_threshold <= threshold:
                raise AlertRuleValidationError(
                    "Clear threshold must be above threshold for <= operator"
                )
            elif operator == '>' and clear_threshold >= threshold:
                raise AlertRuleValidationError(
                    "Clear threshold must be below threshold for > operator"
                )
            elif operator == '<' and clear_threshold <= threshold:
                raise AlertRuleValidationError(
                    "Clear threshold must be above threshold for < operator"
                )

    def _validate_durations(self, rule_data: Dict[str, Any]) -> None:
        """Validate timing fields"""
        # Alert timing
        alert_active_delay = rule_data.get('alert_active_delay_seconds')
        alert_clear_delay = rule_data.get('alert_clear_delay_seconds')
        # Notification timing
        notification_active_delay = rule_data.get('notification_active_delay_seconds')
        notification_cooldown = rule_data.get('notification_cooldown_seconds')
        # Legacy field
        grace = rule_data.get('grace_seconds')

        # Alert active delay validation
        if alert_active_delay is not None:
            if not isinstance(alert_active_delay, int):
                raise AlertRuleValidationError("Alert active delay must be an integer")

            if alert_active_delay < 0 or alert_active_delay > self.MAX_DURATION_SECONDS:
                raise AlertRuleValidationError(
                    f"Alert active delay must be between 0 and {self.MAX_DURATION_SECONDS}s (24 hours)"
                )

        # Alert clear delay validation
        if alert_clear_delay is not None:
            if not isinstance(alert_clear_delay, int):
                raise AlertRuleValidationError("Alert clear delay must be an integer")

            if alert_clear_delay < 0 or alert_clear_delay > self.MAX_DURATION_SECONDS:
                raise AlertRuleValidationError(
                    f"Alert clear delay must be between 0 and {self.MAX_DURATION_SECONDS}s (24 hours)"
                )

        # Notification active delay validation
        if notification_active_delay is not None:
            if not isinstance(notification_active_delay, int):
                raise AlertRuleValidationError("Notification active delay must be an integer")

            if notification_active_delay < 0 or notification_active_delay > self.MAX_DURATION_SECONDS:
                raise AlertRuleValidationError(
                    f"Notification active delay must be between 0 and {self.MAX_DURATION_SECONDS}s (24 hours)"
                )

        # Notification cooldown validation
        if notification_cooldown is not None:
            if not isinstance(notification_cooldown, int):
                raise AlertRuleValidationError("Notification cooldown must be an integer")

            if notification_cooldown < 0 or notification_cooldown > self.MAX_DURATION_SECONDS:
                raise AlertRuleValidationError(
                    f"Notification cooldown must be between 0 and {self.MAX_DURATION_SECONDS}s (24 hours)"
                )

        # Grace validation (legacy)
        if grace is not None:
            if not isinstance(grace, int):
                raise AlertRuleValidationError("Grace period must be an integer")

            if grace < 0 or grace > self.MAX_DURATION_SECONDS:
                raise AlertRuleValidationError(
                    f"Grace period must be between 0 and {self.MAX_DURATION_SECONDS}s (24 hours)"
                )

    def _validate_occurrences(self, occurrences: int) -> None:
        """Validate occurrences field"""
        if not isinstance(occurrences, int):
            raise AlertRuleValidationError("Occurrences must be an integer")

        if not self.MIN_OCCURRENCES <= occurrences <= self.MAX_OCCURRENCES:
            raise AlertRuleValidationError(
                f"Occurrences must be between {self.MIN_OCCURRENCES} and {self.MAX_OCCURRENCES}"
            )

    def _validate_selectors(self, rule_data: Dict[str, Any]) -> None:
        """Validate selector JSON fields"""
        host_selector = rule_data.get('host_selector_json')
        container_selector = rule_data.get('container_selector_json')
        labels = rule_data.get('labels_json')

        # Size limits to prevent DoS
        if host_selector:
            self._validate_selector_size('host_selector_json', host_selector)
            self._validate_json_parseable('host_selector_json', host_selector)

            # Validate regex if present
            if isinstance(host_selector, dict) and 'regex' in host_selector:
                self._validate_regex(host_selector['regex'])

        if container_selector:
            self._validate_selector_size('container_selector_json', container_selector)
            self._validate_json_parseable('container_selector_json', container_selector)

            # Validate regex if present
            if isinstance(container_selector, dict) and 'regex' in container_selector:
                self._validate_regex(container_selector['regex'])

        if labels:
            if isinstance(labels, str):
                # JSON string
                if len(labels) > self.MAX_LABELS_SIZE_BYTES:
                    raise AlertRuleValidationError(
                        f"Labels JSON too large (max {self.MAX_LABELS_SIZE_BYTES} bytes)"
                    )
                try:
                    json.loads(labels)
                except json.JSONDecodeError as e:
                    raise AlertRuleValidationError(f"Invalid labels JSON: {e}")
            elif isinstance(labels, dict):
                # Dict object
                if len(json.dumps(labels)) > self.MAX_LABELS_SIZE_BYTES:
                    raise AlertRuleValidationError(
                        f"Labels JSON too large (max {self.MAX_LABELS_SIZE_BYTES} bytes)"
                    )

    def _validate_selector_size(self, field_name: str, selector: Any) -> None:
        """Validate selector size"""
        if isinstance(selector, str):
            size = len(selector)
        else:
            size = len(json.dumps(selector))

        if size > self.MAX_SELECTOR_SIZE_BYTES:
            raise AlertRuleValidationError(
                f"{field_name} too large (max {self.MAX_SELECTOR_SIZE_BYTES} bytes)"
            )

    def _validate_json_parseable(self, field_name: str, value: Any) -> None:
        """Validate that value is valid JSON"""
        if isinstance(value, str):
            try:
                json.loads(value)
            except json.JSONDecodeError as e:
                raise AlertRuleValidationError(f"Invalid {field_name}: {e}")

    def _validate_regex(self, pattern: str) -> None:
        """Validate regex pattern"""
        try:
            re.compile(pattern)
        except re.error as e:
            raise AlertRuleValidationError(f"Invalid regex pattern: {e}")

        # Check for dangerous patterns that could cause ReDoS
        dangerous_patterns = [
            r'.*.*.*',  # Nested quantifiers
            r'.+.+.+',
            r'(.*)*',   # Nested groups with quantifiers
            r'(.+)+',
            r'(.*)+',
            r'(.+)*'
        ]

        for dangerous in dangerous_patterns:
            if dangerous in pattern:
                raise AlertRuleValidationError(
                    f"Regex pattern may cause ReDoS (Regular Expression Denial of Service): "
                    f"contains dangerous pattern '{dangerous}'"
                )

    def _validate_notifications(self, rule_data: Dict[str, Any]) -> None:
        """Validate notification configuration"""
        channels = rule_data.get('notify_channels_json')

        if not channels:
            return  # Notifications are optional

        # Handle both string and list
        if isinstance(channels, str):
            try:
                channels = json.loads(channels)
            except json.JSONDecodeError as e:
                raise AlertRuleValidationError(f"Invalid notify_channels_json: {e}")

        if not isinstance(channels, list):
            raise AlertRuleValidationError("notify_channels must be an array")

        if len(channels) > self.MAX_NOTIFICATION_CHANNELS:
            raise AlertRuleValidationError(
                f"Maximum {self.MAX_NOTIFICATION_CHANNELS} notification channels allowed"
            )

        for channel in channels:
            if not isinstance(channel, str):
                raise AlertRuleValidationError("Notification channel must be a string")

            if channel not in self.VALID_NOTIFICATION_CHANNELS:
                raise AlertRuleValidationError(
                    f"Invalid notification channel '{channel}'. "
                    f"Must be one of: {', '.join(self.VALID_NOTIFICATION_CHANNELS)}"
                )

    def _validate_dependencies(self, rule_data: Dict[str, Any]) -> None:
        """Validate rule dependencies"""
        depends_on = rule_data.get('depends_on_json')

        if not depends_on:
            return  # Dependencies are optional

        # Handle both string and list
        if isinstance(depends_on, str):
            try:
                depends_on = json.loads(depends_on)
            except json.JSONDecodeError as e:
                raise AlertRuleValidationError(f"Invalid depends_on_json: {e}")

        if not isinstance(depends_on, list):
            raise AlertRuleValidationError("depends_on must be an array")

        if len(depends_on) > self.MAX_DEPENDENCIES:
            raise AlertRuleValidationError(
                f"Maximum {self.MAX_DEPENDENCIES} dependencies allowed"
            )

        # Check for self-dependency
        rule_id = rule_data.get('id')
        if rule_id and rule_id in depends_on:
            raise AlertRuleValidationError("Rule cannot depend on itself")

        # Validate dependency IDs are strings
        for dep_id in depends_on:
            if not isinstance(dep_id, str):
                raise AlertRuleValidationError("Dependency rule ID must be a string")

            if not re.match(r'^[a-z0-9_]+$', dep_id):
                raise AlertRuleValidationError(
                    f"Invalid dependency rule ID '{dep_id}'. "
                    "Must contain only lowercase letters, numbers, and underscores"
                )


# Singleton validator instance
validator = AlertRuleValidator()
