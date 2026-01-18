"""
Settings and Configuration Models for DockMon
Pydantic models for global settings, alerts, and notifications
"""

import re
import uuid
from datetime import datetime
from typing import Optional, List

from cronsim import CronSim
from cronsim.cronsim import CronSimError
from pydantic import BaseModel, Field, field_validator, ConfigDict

class GlobalSettings(BaseModel):
    """Global monitoring settings"""
    max_retries: int = Field(3, ge=0, le=10)  # 0-10 retries
    retry_delay: int = Field(30, ge=5, le=300)  # 5 seconds to 5 minutes
    default_auto_restart: bool = False
    polling_interval: int = Field(2, ge=1, le=300)  # 1 second to 5 minutes
    connection_timeout: int = Field(10, ge=1, le=60)  # 1-60 seconds
    alert_template: Optional[str] = Field(None, max_length=2000)  # Global notification template (default)
    alert_template_metric: Optional[str] = Field(None, max_length=2000)  # Metric-based alert template
    alert_template_state_change: Optional[str] = Field(None, max_length=2000)  # State change alert template
    alert_template_health: Optional[str] = Field(None, max_length=2000)  # Health check alert template
    blackout_windows: Optional[List[dict]] = None  # Blackout windows configuration
    timezone_offset: int = Field(0, ge=-720, le=720)  # Timezone offset in minutes from UTC (-12h to +12h)
    show_host_stats: bool = Field(True)  # Show host statistics graphs on dashboard
    show_container_stats: bool = Field(True)  # Show container statistics on dashboard
    alert_retention_days: int = Field(90, ge=0, le=365)  # Keep resolved alerts for N days (0 = keep forever)

    @field_validator('max_retries')
    @classmethod
    def validate_max_retries(cls, v: int) -> int:
        """Validate retry count to prevent resource exhaustion"""
        if v < 0:
            raise ValueError('Max retries cannot be negative')
        if v > 10:
            raise ValueError('Max retries cannot exceed 10 to prevent resource exhaustion')
        return v

    @field_validator('retry_delay')
    @classmethod
    def validate_retry_delay(cls, v: int) -> int:
        """Validate retry delay to prevent system overload"""
        if v < 5:
            raise ValueError('Retry delay must be at least 5 seconds')
        if v > 300:
            raise ValueError('Retry delay cannot exceed 300 seconds')
        return v

    @field_validator('polling_interval')
    @classmethod
    def validate_polling_interval(cls, v: int) -> int:
        """Validate polling interval to prevent system overload"""
        if v < 1:
            raise ValueError('Polling interval must be at least 1 second')
        if v > 300:
            raise ValueError('Polling interval cannot exceed 300 seconds')
        return v

    @field_validator('connection_timeout')
    @classmethod
    def validate_connection_timeout(cls, v: int) -> int:
        """Validate connection timeout"""
        if v < 1:
            raise ValueError('Connection timeout must be at least 1 second')
        if v > 60:
            raise ValueError('Connection timeout cannot exceed 60 seconds')
        return v


class AlertRule(BaseModel):
    """Alert rule configuration"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    trigger_events: Optional[List[str]] = None
    trigger_states: Optional[List[str]] = None
    notification_channels: List[int]
    cooldown_minutes: int = 15
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_triggered: Optional[datetime] = None


class NotificationSettings(BaseModel):
    """Notification channel settings"""
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    discord_webhook: Optional[str] = None
    pushover_app_token: Optional[str] = None
    pushover_user_key: Optional[str] = None


# Alert System v2 Models
class AlertRuleV2Create(BaseModel):
    """Create alert rule v2"""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    scope: str = Field(..., pattern="^(host|container|group)$")
    kind: str = Field(..., min_length=1)
    enabled: bool = True
    severity: str = Field(..., pattern="^(info|warning|error|critical)$")

    # Metric-based rule fields
    metric: Optional[str] = None
    threshold: Optional[float] = None
    operator: Optional[str] = Field(None, pattern="^(>=|<=|>|<|==|!=)$")
    occurrences: Optional[int] = Field(None, ge=1)
    clear_threshold: Optional[float] = None

    # Alert timing
    alert_active_delay_seconds: int = Field(0, ge=0, description="Condition must be TRUE for X seconds before raising alert")
    alert_clear_delay_seconds: int = Field(0, ge=0, description="Condition must be FALSE for X seconds before clearing alert")

    # Notification timing
    notification_active_delay_seconds: int = Field(0, ge=0, description="Alert must be active for X seconds before sending notification")
    notification_cooldown_seconds: int = Field(300, ge=0, description="Wait X seconds before sending another notification")

    # Behavior flags
    auto_resolve: Optional[bool] = False  # Resolve immediately after notification (notification-only mode)
    auto_resolve_on_clear: Optional[bool] = False  # Clear when condition resolves (e.g., container restarts)
    suppress_during_updates: Optional[bool] = False  # Suppress alert during container updates

    # Selectors (JSON strings)
    host_selector_json: Optional[str] = None
    container_selector_json: Optional[str] = None
    labels_json: Optional[str] = None
    notify_channels_json: Optional[str] = None
    custom_template: Optional[str] = Field(None, max_length=2000)  # Custom template for this rule


class AlertRuleV2Update(BaseModel):
    """Update alert rule v2 (all fields optional)"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    scope: Optional[str] = Field(None, pattern="^(host|container|group)$")
    kind: Optional[str] = None
    enabled: Optional[bool] = None
    severity: Optional[str] = Field(None, pattern="^(info|warning|error|critical)$")

    # Metric-based rule fields
    metric: Optional[str] = None
    threshold: Optional[float] = None
    operator: Optional[str] = Field(None, pattern="^(>=|<=|>|<|==|!=)$")
    occurrences: Optional[int] = Field(None, ge=1)
    clear_threshold: Optional[float] = None

    # Alert timing
    alert_active_delay_seconds: Optional[int] = Field(None, ge=0, description="Condition must be TRUE for X seconds before raising alert")
    alert_clear_delay_seconds: Optional[int] = Field(None, ge=0, description="Condition must be FALSE for X seconds before clearing alert")

    # Notification timing
    notification_active_delay_seconds: Optional[int] = Field(None, ge=0, description="Alert must be active for X seconds before sending notification")
    notification_cooldown_seconds: Optional[int] = Field(None, ge=0, description="Wait X seconds before sending another notification")

    depends_on_json: Optional[str] = None  # JSON array of condition dependencies

    # Behavior flags
    auto_resolve: Optional[bool] = None  # Resolve immediately after notification (notification-only mode)
    auto_resolve_on_clear: Optional[bool] = None  # Clear when condition resolves (e.g., container restarts)
    suppress_during_updates: Optional[bool] = None  # Suppress alert during container updates

    host_selector_json: Optional[str] = None
    container_selector_json: Optional[str] = None
    labels_json: Optional[str] = None
    notify_channels_json: Optional[str] = None
    custom_template: Optional[str] = Field(None, max_length=2000)  # Custom template for this rule


class GlobalSettingsUpdate(BaseModel):
    """
    Pydantic model for validating global settings updates.

    Enforces:
    - Type safety (int, bool, str)
    - Range constraints (min/max values)
    - Rejects unknown fields

    All fields are optional to support partial updates.
    """

    # Auto-restart settings
    max_retries: Optional[int] = Field(None, ge=0, le=10, description="Maximum restart attempts (0-10)")
    retry_delay: Optional[int] = Field(None, ge=5, le=300, description="Delay between retries in seconds (5-300)")
    default_auto_restart: Optional[bool] = Field(None, description="Enable auto-restart by default")

    # Monitoring settings
    polling_interval: Optional[int] = Field(None, ge=1, le=600, description="Polling interval in seconds (1-600)")
    connection_timeout: Optional[int] = Field(None, ge=5, le=120, description="Docker connection timeout (5-120)")

    # Retention settings
    event_retention_days: Optional[int] = Field(None, ge=0, le=365, description="Event retention days (0-365, 0=forever)")
    alert_retention_days: Optional[int] = Field(None, ge=0, le=730, description="Alert retention days (0=forever, max 730)")
    unused_tag_retention_days: Optional[int] = Field(None, ge=0, le=365, description="Unused tag retention (0=never, max 365)")

    # Event suppression (v2.2.0+)
    event_suppression_patterns: Optional[List[str]] = Field(None, description="Glob patterns for container names to suppress from event log")

    # Notification settings
    enable_notifications: Optional[bool] = None
    alert_template: Optional[str] = Field(None, max_length=5000)
    alert_template_metric: Optional[str] = Field(None, max_length=5000)
    alert_template_state_change: Optional[str] = Field(None, max_length=5000)
    alert_template_health: Optional[str] = Field(None, max_length=5000)
    alert_template_update: Optional[str] = Field(None, max_length=5000)

    # Blackout windows (JSON array)
    blackout_windows: Optional[List[dict]] = None

    # UI settings
    timezone_offset: Optional[int] = Field(None, ge=-720, le=720, description="Timezone offset in minutes (-720 to +720)")
    show_host_stats: Optional[bool] = None
    show_container_stats: Optional[bool] = None
    show_container_alerts_on_hosts: Optional[bool] = None
    editor_theme: Optional[str] = Field(None, pattern="^(github-dark|vscode-dark|dracula|material-dark|nord)$", description="Editor theme for YAML/JSON editing")

    # Update settings
    auto_update_enabled_default: Optional[bool] = None
    update_check_interval_hours: Optional[int] = Field(None, ge=1, le=168, description="Update check interval (1-168 hours)")
    update_check_time: Optional[str] = Field(None, max_length=100, description="Schedule in HH:MM format or cron expression")
    skip_compose_containers: Optional[bool] = None
    health_check_timeout_seconds: Optional[int] = Field(None, ge=5, le=600, description="Health check timeout (5-600)")

    # Image pruning settings (v2.1+)
    prune_images_enabled: Optional[bool] = Field(None, description="Enable automatic image pruning")
    image_retention_count: Optional[int] = Field(None, ge=0, le=10, description="Keep last N versions per image (0=only in-use images, 1-10=keep N versions)")
    image_prune_grace_hours: Optional[int] = Field(None, ge=1, le=168, description="Don't remove images newer than N hours (1-168)")

    # External URL for notification action links (v2.2.0+)
    external_url: Optional[str] = Field(None, max_length=500, description="External URL for notification action links (e.g., https://dockmon.example.com)")

    model_config = ConfigDict(extra="forbid")  # Reject unknown keys (typos, attacks)

    @field_validator('update_check_time')
    @classmethod
    def validate_update_check_time(cls, v: Optional[str]) -> Optional[str]:
        """Validate schedule format (HH:MM or cron expression)"""
        if v is None:
            return v

        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Schedule cannot be empty")

        # Check HH:MM format
        time_pattern = re.compile(r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$')
        if time_pattern.match(trimmed):
            return trimmed

        # Check cron expression
        try:
            CronSim(trimmed, datetime.now().astimezone())
            return trimmed
        except CronSimError:
            raise ValueError(
                "Invalid schedule format. Use HH:MM (e.g., 02:00) or "
                "cron expression (e.g., 0 4 * * 6 for 4am every Saturday)"
            )

    @field_validator('blackout_windows')
    @classmethod
    def validate_blackout_windows(cls, v: Optional[List[dict]]) -> Optional[List[dict]]:
        """Validate blackout window structure"""
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("blackout_windows must be an array")
        for window in v:
            if not isinstance(window, dict):
                raise ValueError("Each blackout window must be an object")
            # Validate required fields
            required = ['name', 'start_time', 'end_time', 'days']
            for field in required:
                if field not in window:
                    raise ValueError(f"Blackout window missing required field: {field}")
        return v