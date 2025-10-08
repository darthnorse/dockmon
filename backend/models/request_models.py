"""
Request Models for DockMon API Endpoints
Pydantic models for API request validation
"""

import re
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, validator


class ContainerHostPair(BaseModel):
    """Container and host pair for alert rules"""
    host_id: str = Field(..., max_length=50)
    container_name: str = Field(..., min_length=1, max_length=200)


class AutoRestartRequest(BaseModel):
    """Request model for toggling auto-restart"""
    container_name: str
    enabled: bool


class AlertRuleCreate(BaseModel):
    """Request model for creating alert rules"""
    name: str = Field(..., min_length=1, max_length=100)
    containers: Optional[List[ContainerHostPair]] = Field(None, max_items=100)
    trigger_events: Optional[List[str]] = Field(None, max_items=20)  # Docker events
    trigger_states: Optional[List[str]] = Field(None, max_items=10)  # Docker states
    notification_channels: List[int] = Field(..., min_items=1, max_items=20)
    cooldown_minutes: int = Field(15, ge=1, le=1440)  # 1 min to 24 hours
    enabled: bool = True

    @validator('name')
    def validate_name(cls, v):
        """Validate rule name for security"""
        if not v or not v.strip():
            raise ValueError('Rule name cannot be empty')
        # Sanitize and prevent XSS
        sanitized = re.sub(r'[<>"\']', '', v.strip())
        if len(sanitized) != len(v.strip()):
            raise ValueError('Rule name contains invalid characters')
        return sanitized

    @validator('trigger_events')
    def validate_trigger_events(cls, v):
        """Validate Docker events"""
        if not v:
            return v  # Events are optional

        valid_events = {
            # Critical events
            'oom', 'die-nonzero', 'health_status:unhealthy',
            # Warning events
            'kill', 'die-zero', 'restart-loop', 'stuck-removing',
            # Info events
            'start', 'stop', 'create', 'destroy', 'pause', 'unpause',
            'health_status:healthy'
        }

        invalid_events = [event for event in v if event not in valid_events]
        if invalid_events:
            raise ValueError(f'Invalid trigger events: {invalid_events}')

        return v

    @validator('trigger_states')
    def validate_trigger_states(cls, v):
        """Validate container states"""
        if not v:
            return v  # States are optional now

        valid_states = {'created', 'restarting', 'running', 'removing', 'paused', 'exited', 'dead'}
        invalid_states = [state for state in v if state not in valid_states]
        if invalid_states:
            raise ValueError(f'Invalid trigger states: {invalid_states}')

        return v

    def __init__(self, **data):
        """Custom validation to ensure at least one trigger is specified"""
        super().__init__(**data)
        events = self.trigger_events or []
        states = self.trigger_states or []
        if not events and not states:
            raise ValueError('At least one trigger event or state is required')

    @validator('notification_channels')
    def validate_notification_channels(cls, v):
        """Validate notification channel IDs"""
        if not v:
            raise ValueError('At least one notification channel is required')

        # Validate all are positive integers
        invalid_ids = [id for id in v if id <= 0]
        if invalid_ids:
            raise ValueError(f'Invalid notification channel IDs: {invalid_ids}')

        return v


class AlertRuleUpdate(BaseModel):
    """Request model for updating alert rules"""
    name: Optional[str] = None
    containers: Optional[List[ContainerHostPair]] = None
    trigger_events: Optional[List[str]] = None  # Docker events
    trigger_states: Optional[List[str]] = None  # Docker states
    notification_channels: Optional[List[int]] = None
    cooldown_minutes: Optional[int] = None
    enabled: Optional[bool] = None


class NotificationChannelCreate(BaseModel):
    """Request model for creating notification channels"""
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., min_length=1, max_length=20)
    config: Dict[str, Any] = Field(..., min_items=1, max_items=10)
    enabled: bool = True

    @validator('name')
    def validate_name(cls, v):
        """Validate channel name for security"""
        if not v or not v.strip():
            raise ValueError('Channel name cannot be empty')
        # Sanitize and prevent XSS
        sanitized = re.sub(r'[<>"\']', '', v.strip())
        if len(sanitized) != len(v.strip()):
            raise ValueError('Channel name contains invalid characters')
        return sanitized

    @validator('type')
    def validate_type(cls, v):
        """Validate notification type"""
        if not v or not v.strip():
            raise ValueError('Channel type cannot be empty')

        valid_types = {'telegram', 'discord', 'pushover', 'slack', 'gotify', 'smtp'}
        v = v.strip().lower()

        if v not in valid_types:
            raise ValueError(f'Invalid channel type. Must be one of: {valid_types}')

        return v

    @validator('config')
    def validate_config(cls, v, values):
        """Validate channel configuration based on type"""
        if not v:
            raise ValueError('Configuration cannot be empty')

        channel_type = values.get('type', '').lower()

        # Validate configuration based on channel type
        if channel_type == 'telegram':
            required_keys = {'bot_token', 'chat_id'}
            if not all(key in v for key in required_keys):
                raise ValueError(f'Telegram config must contain: {required_keys}')

            # Validate bot token format
            bot_token = v.get('bot_token', '')
            if not re.match(r'^\d+:[A-Za-z0-9_-]+$', bot_token):
                raise ValueError('Invalid Telegram bot token format')

        elif channel_type == 'discord':
            required_keys = {'webhook_url'}
            if not all(key in v for key in required_keys):
                raise ValueError(f'Discord config must contain: {required_keys}')

            # Validate Discord webhook URL
            webhook_url = v.get('webhook_url', '')
            if not webhook_url.startswith('https://discord.com/api/webhooks/'):
                raise ValueError('Invalid Discord webhook URL')

        elif channel_type == 'slack':
            required_keys = {'webhook_url'}
            if not all(key in v for key in required_keys):
                raise ValueError(f'Slack config must contain: {required_keys}')

            # Validate Slack webhook URL
            webhook_url = v.get('webhook_url', '')
            if not (webhook_url.startswith('https://hooks.slack.com/services/') or
                    webhook_url.startswith('https://hooks.slack.com/workflows/')):
                raise ValueError('Invalid Slack webhook URL')

        elif channel_type == 'pushover':
            required_keys = {'app_token', 'user_key'}
            if not all(key in v for key in required_keys):
                raise ValueError(f'Pushover config must contain: {required_keys}')

            # Validate token formats
            app_token = v.get('app_token', '')
            user_key = v.get('user_key', '')
            if not re.match(r'^[a-z0-9]{30}$', app_token, re.IGNORECASE):
                raise ValueError('Invalid Pushover app token format')
            if not re.match(r'^[a-z0-9]{30}$', user_key, re.IGNORECASE):
                raise ValueError('Invalid Pushover user key format')

        elif channel_type == 'gotify':
            required_keys = {'server_url', 'app_token'}
            if not all(key in v for key in required_keys):
                raise ValueError(f'Gotify config must contain: {required_keys}')

            # Validate server URL
            server_url = v.get('server_url', '')
            if not (server_url.startswith('http://') or server_url.startswith('https://')):
                raise ValueError('Gotify server URL must start with http:// or https://')

        elif channel_type == 'smtp':
            required_keys = {'smtp_host', 'from_email', 'to_email'}
            if not all(key in v for key in required_keys):
                raise ValueError(f'SMTP config must contain: {required_keys}')

            # Default port to 587 if not provided or empty
            if 'smtp_port' not in v or v['smtp_port'] == '' or v['smtp_port'] is None:
                v['smtp_port'] = 587

            # Validate email format
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            from_email = v.get('from_email', '')
            to_email = v.get('to_email', '')
            if not re.match(email_pattern, from_email):
                raise ValueError('Invalid from_email format')
            if not re.match(email_pattern, to_email):
                raise ValueError('Invalid to_email format')

            # Validate port
            try:
                port = int(v.get('smtp_port', 587))
                if port < 1 or port > 65535:
                    raise ValueError('SMTP port must be between 1 and 65535')
                v['smtp_port'] = port  # Ensure it's stored as int
            except (ValueError, TypeError):
                raise ValueError('SMTP port must be a valid number')

        # Validate all string values in config for security
        for key, value in v.items():
            if isinstance(value, str):
                # Prevent code injection in configuration values
                dangerous_patterns = ['<script', 'javascript:', 'data:', 'vbscript:', '<?php', '<%']
                value_lower = value.lower()
                if any(pattern in value_lower for pattern in dangerous_patterns):
                    raise ValueError(f'Configuration value for {key} contains potentially dangerous content')

                # Limit string length to prevent DoS
                if len(value) > 1000:
                    raise ValueError(f'Configuration value for {key} is too long (max 1000 characters)')

        return v


class NotificationChannelUpdate(BaseModel):
    """Request model for updating notification channels"""
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class EventLogFilter(BaseModel):
    """Request model for filtering events"""
    category: Optional[str] = None
    event_type: Optional[str] = None
    severity: Optional[str] = None
    host_id: Optional[str] = None
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    correlation_id: Optional[str] = None
    search: Optional[str] = None
    limit: int = 100
    offset: int = 0