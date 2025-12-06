"""
Request Models for DockMon API Endpoints
Pydantic models for API request validation
"""

import re
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ContainerHostPair(BaseModel):
    """Container and host pair for alert rules"""
    host_id: str = Field(..., max_length=50)
    container_name: str = Field(..., min_length=1, max_length=200)


class AutoRestartRequest(BaseModel):
    """Request model for toggling auto-restart"""
    container_name: str
    enabled: bool


class DesiredStateRequest(BaseModel):
    """Request model for setting container desired state"""
    container_name: str
    desired_state: str = Field(..., pattern='^(should_run|on_demand|unspecified)$')
    web_ui_url: Optional[str] = None

    @field_validator('desired_state')
    @classmethod
    def validate_desired_state(cls, v: str) -> str:
        """Validate desired state value"""
        valid_states = {'should_run', 'on_demand', 'unspecified'}
        if v not in valid_states:
            raise ValueError(f'Invalid desired state. Must be one of: {valid_states}')
        return v


class AlertRuleCreate(BaseModel):
    """Request model for creating alert rules"""
    name: str = Field(..., min_length=1, max_length=100)
    containers: Optional[List[ContainerHostPair]] = Field(None, max_length=100)
    trigger_events: Optional[List[str]] = Field(None, max_length=20)  # Docker events
    trigger_states: Optional[List[str]] = Field(None, max_length=10)  # Docker states
    notification_channels: List[int] = Field(..., min_length=1, max_length=20)
    cooldown_minutes: int = Field(15, ge=1, le=1440)  # 1 min to 24 hours
    enabled: bool = True

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate rule name for security"""
        if not v or not v.strip():
            raise ValueError('Rule name cannot be empty')
        # Sanitize and prevent XSS
        sanitized = re.sub(r'[<>"\']', '', v.strip())
        if len(sanitized) != len(v.strip()):
            raise ValueError('Rule name contains invalid characters')
        return sanitized

    @field_validator('trigger_events')
    @classmethod
    def validate_trigger_events(cls, v: Optional[List[str]]) -> Optional[List[str]]:
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

    @field_validator('trigger_states')
    @classmethod
    def validate_trigger_states(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate container states"""
        if not v:
            return v  # States are optional now

        valid_states = {'created', 'restarting', 'running', 'removing', 'paused', 'exited', 'dead'}
        invalid_states = [state for state in v if state not in valid_states]
        if invalid_states:
            raise ValueError(f'Invalid trigger states: {invalid_states}')

        return v

    @model_validator(mode='after')
    def validate_triggers(self):
        """Ensure at least one trigger is specified"""
        events = self.trigger_events or []
        states = self.trigger_states or []
        if not events and not states:
            raise ValueError('At least one trigger event or state is required')
        return self

    @field_validator('notification_channels')
    @classmethod
    def validate_notification_channels(cls, v: List[int]) -> List[int]:
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
    config: Dict[str, Any] = Field(..., min_length=1, max_length=10)
    enabled: bool = True

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate channel name for security"""
        if not v or not v.strip():
            raise ValueError('Channel name cannot be empty')
        # Sanitize and prevent XSS
        sanitized = re.sub(r'[<>"\']', '', v.strip())
        if len(sanitized) != len(v.strip()):
            raise ValueError('Channel name contains invalid characters')
        return sanitized

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate notification type"""
        if not v or not v.strip():
            raise ValueError('Channel type cannot be empty')

        valid_types = {'telegram', 'discord', 'pushover', 'slack', 'gotify', 'ntfy', 'smtp', 'webhook'}
        v = v.strip().lower()

        if v not in valid_types:
            raise ValueError(f'Invalid channel type. Must be one of: {valid_types}')

        return v

    @model_validator(mode='after')
    def validate_config(self):
        """Validate channel configuration based on type"""
        v = self.config
        if not v:
            raise ValueError('Configuration cannot be empty')

        channel_type = self.type.lower() if self.type else ''

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

        elif channel_type == 'ntfy':
            required_keys = {'server_url', 'topic'}
            if not all(key in v for key in required_keys):
                raise ValueError(f'ntfy config must contain: {required_keys}')

            # Validate server URL
            server_url = v.get('server_url', '')
            if not (server_url.startswith('http://') or server_url.startswith('https://')):
                raise ValueError('ntfy server URL must start with http:// or https://')

            # Validate topic is not empty
            topic = v.get('topic', '')
            if not topic.strip():
                raise ValueError('ntfy topic cannot be empty')

        elif channel_type == 'smtp':
            required_keys = {'smtp_host', 'from_email', 'to_email'}
            if not all(key in v for key in required_keys):
                raise ValueError(f'SMTP config must contain: {required_keys}')

            # Default port to 587 if not provided or empty
            if 'smtp_port' not in v or v['smtp_port'] == '' or v['smtp_port'] is None:
                v['smtp_port'] = 587

            # Validate email format
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

        elif channel_type == 'webhook':
            required_keys = {'url'}
            if not all(key in v for key in required_keys):
                raise ValueError(f'Webhook config must contain: {required_keys}')

            # Validate webhook URL
            url = v.get('url', '')
            if not (url.startswith('http://') or url.startswith('https://')):
                raise ValueError('Webhook URL must start with http:// or https://')

            # Validate headers is a dict if provided
            if 'headers' in v and v['headers'] is not None:
                if not isinstance(v['headers'], dict):
                    raise ValueError('Headers must be a valid JSON object (dict)')

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

        return self


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


class BatchJobCreate(BaseModel):
    """Request model for creating batch jobs"""
    scope: str = Field(..., pattern='^container$')  # Only 'container' for now
    action: str = Field(..., pattern='^(start|stop|restart|add-tags|remove-tags|set-auto-restart|set-auto-update|set-desired-state|check-updates|delete-containers|update-containers)$')  # Container actions
    ids: List[str] = Field(..., min_length=1, max_length=100)  # Container IDs
    params: Optional[Dict[str, Any]] = None  # Optional parameters (e.g., tags, enabled, desired_state)
    dry_run: bool = False  # Not implemented in Phase 1

    @field_validator('scope')
    @classmethod
    def validate_scope(cls, v: str) -> str:
        """Validate batch job scope"""
        if v != 'container':
            raise ValueError('Only "container" scope is supported')
        return v

    @field_validator('action')
    @classmethod
    def validate_action(cls, v: str) -> str:
        """Validate batch job action"""
        valid_actions = {'start', 'stop', 'restart', 'add-tags', 'remove-tags', 'set-auto-restart', 'set-auto-update', 'set-desired-state', 'check-updates', 'delete-containers', 'update-containers'}
        if v not in valid_actions:
            raise ValueError(f'Invalid action. Must be one of: {valid_actions}')
        return v

    @field_validator('ids')
    @classmethod
    def validate_ids(cls, v: List[str]) -> List[str]:
        """Validate container IDs"""
        if not v:
            raise ValueError('At least one container ID is required')
        if len(v) > 100:
            raise ValueError('Maximum 100 containers per batch job')
        return v


class TagUpdateBase(BaseModel):
    """
    Base model for updating tags (v2.1.8-hotfix.1+)

    Supports two modes:
    1. Delta mode: tags_to_add/tags_to_remove (backwards compatible)
    2. Ordered mode: ordered_tags (new - for reordering)
    """
    # Mode 1: Delta operations (backwards compatible)
    tags_to_add: Optional[List[str]] = Field(default=None, max_length=50)
    tags_to_remove: Optional[List[str]] = Field(default=None, max_length=50)

    # Mode 2: Ordered list (new - for reordering)
    ordered_tags: Optional[List[str]] = Field(default=None, max_length=50)

    @field_validator('tags_to_add', 'tags_to_remove', 'ordered_tags')
    @classmethod
    def validate_tags_list(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate tag list and individual tag format"""
        if v is None:
            return v

        validated_tags = []
        for tag in v:
            if not tag or not tag.strip():
                raise ValueError('Tag cannot be empty')
            if len(tag) > 50:
                raise ValueError('Tag cannot exceed 50 characters')
            # Allow alphanumeric, dash, underscore, colon, dot
            if not all(c.isalnum() or c in '-_:.' for c in tag):
                raise ValueError('Tag can only contain alphanumeric characters, dash, underscore, colon, and dot')
            validated_tags.append(tag.strip().lower())

        return validated_tags

    @model_validator(mode='after')
    def validate_tags(self):
        """Ensure only one mode is used and at least one operation specified"""
        tags_to_add = self.tags_to_add
        tags_to_remove = self.tags_to_remove
        ordered_tags = self.ordered_tags

        # Check mutual exclusivity
        if ordered_tags is not None and (tags_to_add or tags_to_remove):
            raise ValueError('Cannot use ordered_tags with tags_to_add/tags_to_remove')

        # Ensure at least one operation
        if ordered_tags is None and not tags_to_add and not tags_to_remove:
            raise ValueError('Must provide either ordered_tags or tags_to_add/tags_to_remove')

        # Only validate delta operations if not using ordered mode
        if ordered_tags is None:
            add_list = tags_to_add or []
            remove_list = tags_to_remove or []

            if not add_list and not remove_list:
                raise ValueError('At least one tag operation (add or remove) is required')

            # Check for conflicts (adding and removing the same tag)
            conflicts = set(add_list) & set(remove_list)
            if conflicts:
                raise ValueError(f'Cannot add and remove the same tag(s): {", ".join(conflicts)}')

        return self


class ContainerTagUpdate(TagUpdateBase):
    """Request model for adding/removing tags from a container"""
    pass


class HostTagUpdate(TagUpdateBase):
    """Request model for adding/removing tags from a host"""
    pass


class HttpHealthCheckConfig(BaseModel):
    """Request model for HTTP health check configuration"""
    enabled: bool = Field(default=False)
    url: str = Field(..., min_length=1, max_length=500)
    method: str = Field(default='GET', pattern='^(GET|POST|HEAD)$')
    expected_status_codes: str = Field(default='200', min_length=1, max_length=100)
    timeout_seconds: int = Field(default=10, ge=5, le=60)
    check_interval_seconds: int = Field(default=60, ge=10, le=3600)
    follow_redirects: bool = Field(default=True)
    verify_ssl: bool = Field(default=True)
    check_from: str = Field(default='backend', pattern='^(backend|agent)$')  # v2.2.0+
    auto_restart_on_failure: bool = Field(default=False)
    failure_threshold: int = Field(default=3, ge=1, le=10)
    success_threshold: int = Field(default=1, ge=1, le=10)
    max_restart_attempts: int = Field(default=3, ge=1, le=10)  # v2.0.2+
    restart_retry_delay_seconds: int = Field(default=120, ge=30, le=600)  # v2.0.2+

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format"""
        if not v or not v.strip():
            raise ValueError('URL cannot be empty')

        v = v.strip()

        # Must start with http:// or https://
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError('URL must start with http:// or https://')

        # Basic sanity checks
        if ' ' in v:
            raise ValueError('URL cannot contain spaces')

        return v

    @field_validator('expected_status_codes')
    @classmethod
    def validate_status_codes(cls, v: str) -> str:
        """Validate status codes format (e.g., "200", "200-299", "200,201,204")"""
        if not v or not v.strip():
            raise ValueError('Expected status codes cannot be empty')

        v = v.strip()

        # Split by comma and validate each part
        for part in v.split(','):
            part = part.strip()

            if '-' in part:
                # Range format: "200-299"
                try:
                    start, end = part.split('-', 1)
                    start_code = int(start.strip())
                    end_code = int(end.strip())

                    if not (100 <= start_code <= 599):
                        raise ValueError(f'Invalid HTTP status code: {start_code}')
                    if not (100 <= end_code <= 599):
                        raise ValueError(f'Invalid HTTP status code: {end_code}')
                    if start_code >= end_code:
                        raise ValueError(f'Invalid range: {start_code}-{end_code} (start must be less than end)')
                except ValueError as e:
                    if 'Invalid' in str(e):
                        raise
                    raise ValueError(f'Invalid status code range format: {part}')
            else:
                # Single code
                try:
                    code = int(part)
                    if not (100 <= code <= 599):
                        raise ValueError(f'Invalid HTTP status code: {code}')
                except ValueError:
                    raise ValueError(f'Invalid status code: {part}')

        return v