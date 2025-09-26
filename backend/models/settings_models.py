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
    polling_interval: int = Field(10, ge=5, le=300)  # 5 seconds to 5 minutes
    connection_timeout: int = Field(10, ge=1, le=60)  # 1-60 seconds
    alert_template: Optional[str] = Field(None, max_length=2000)  # Global notification template
    blackout_windows: Optional[List[dict]] = None  # Blackout windows configuration

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
        if v < 5:
            raise ValueError('Polling interval must be at least 5 seconds to prevent system overload')
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