"""
Settings and Configuration Models for DockMon
Pydantic models for global settings, alerts, and notifications
"""

import uuid
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, validator


from typing import Optional, List

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

    @validator('max_retries')
    def validate_max_retries(cls, v):
        """Validate retry count to prevent resource exhaustion"""
        if v < 0:
            raise ValueError('Max retries cannot be negative')
        if v > 10:
            raise ValueError('Max retries cannot exceed 10 to prevent resource exhaustion')
        return v

    @validator('retry_delay')
    def validate_retry_delay(cls, v):
        """Validate retry delay to prevent system overload"""
        if v < 5:
            raise ValueError('Retry delay must be at least 5 seconds')
        if v > 300:
            raise ValueError('Retry delay cannot exceed 300 seconds')
        return v

    @validator('polling_interval')
    def validate_polling_interval(cls, v):
        """Validate polling interval to prevent system overload"""
        if v < 1:
            raise ValueError('Polling interval must be at least 1 second')
        if v > 300:
            raise ValueError('Polling interval cannot exceed 300 seconds')
        return v

    @validator('connection_timeout')
    def validate_connection_timeout(cls, v):
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
    duration_seconds: Optional[int] = Field(None, ge=0)
    occurrences: Optional[int] = Field(None, ge=1)
    clear_threshold: Optional[float] = None
    clear_duration_seconds: Optional[int] = Field(None, ge=0)

    # Timing configuration
    cooldown_seconds: int = Field(300, ge=0)

    # Behavior flags
    auto_resolve: Optional[bool] = False  # Auto-resolve alert after notification (for update alerts)
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

    metric: Optional[str] = None
    threshold: Optional[float] = None
    operator: Optional[str] = Field(None, pattern="^(>=|<=|>|<|==|!=)$")
    duration_seconds: Optional[int] = Field(None, ge=0)
    occurrences: Optional[int] = Field(None, ge=1)
    clear_threshold: Optional[float] = None
    clear_duration_seconds: Optional[int] = Field(None, ge=0)

    cooldown_seconds: Optional[int] = Field(None, ge=0)
    depends_on_json: Optional[str] = None  # JSON array of condition dependencies

    # Behavior flags
    auto_resolve: Optional[bool] = None  # Auto-resolve alert after notification (for update alerts)
    suppress_during_updates: Optional[bool] = None  # Suppress alert during container updates

    host_selector_json: Optional[str] = None
    container_selector_json: Optional[str] = None
    labels_json: Optional[str] = None
    notify_channels_json: Optional[str] = None
    custom_template: Optional[str] = Field(None, max_length=2000)  # Custom template for this rule