"""
Notification service for DockMon
Handles sending alerts via Discord, Telegram, and Pushover
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import requests
import httpx
from database import DatabaseManager, NotificationChannel, AlertRuleDB, AlertV2
from event_logger import EventSeverity, EventCategory, EventType

logger = logging.getLogger(__name__)

@dataclass
class AlertEvent:
    """Container alert event"""
    container_id: str
    container_name: str
    host_id: str
    host_name: str
    old_state: str
    new_state: str
    timestamp: datetime
    image: str
    triggered_by: str = "monitor"

@dataclass
class DockerEventAlert:
    """Docker event that might trigger an alert"""
    container_id: str
    container_name: str
    host_id: str
    event_type: str  # e.g., "die", "oom", "kill", "health_status:unhealthy"
    timestamp: datetime
    attributes: Dict[str, Any] = None  # Additional event attributes
    exit_code: Optional[int] = None

class NotificationService:
    """Handles all notification channels and alert processing"""

    def __init__(self, db: DatabaseManager, event_logger=None):
        self.db = db
        self.event_logger = event_logger
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._last_alerts: Dict[str, datetime] = {}  # For cooldown tracking
        self._last_container_state: Dict[str, str] = {}  # Track last known state per container
        self._suppressed_alerts: List[AlertEvent] = []  # Track alerts suppressed during blackout windows
        self.MAX_SUPPRESSED_ALERTS = 1000  # Prevent unbounded memory growth
        self.MAX_COOLDOWN_ENTRIES = 10000  # Prevent unbounded cooldown dictionary
        self.COOLDOWN_MAX_AGE_DAYS = 7  # Remove cooldown entries older than 7 days

        # Initialize blackout manager
        from blackout_manager import BlackoutManager
        self.blackout_manager = BlackoutManager(db)

    def _cleanup_old_cooldowns(self) -> None:
        """Clean up old cooldown entries to prevent memory leak"""
        now = datetime.now(timezone.utc)
        max_age = timedelta(days=self.COOLDOWN_MAX_AGE_DAYS)

        # Remove entries older than max age
        keys_to_remove = [
            key for key, timestamp in self._last_alerts.items()
            if now - timestamp > max_age
        ]

        for key in keys_to_remove:
            del self._last_alerts[key]

        if keys_to_remove:
            logger.info(f"Cleaned up {len(keys_to_remove)} old cooldown entries")

        # If still over limit, remove oldest entries
        if len(self._last_alerts) > self.MAX_COOLDOWN_ENTRIES:
            # Sort by timestamp and keep only the newest MAX_COOLDOWN_ENTRIES
            sorted_alerts = sorted(self._last_alerts.items(), key=lambda x: x[1], reverse=True)
            self._last_alerts = dict(sorted_alerts[:self.MAX_COOLDOWN_ENTRIES])
            logger.warning(f"Cooldown dictionary exceeded limit, truncated to {self.MAX_COOLDOWN_ENTRIES} entries")

    def _get_host_name(self, event) -> str:
        """Get host name from event, handling both AlertEvent and DockerEventAlert types"""
        if hasattr(event, 'host_name'):
            return event.host_name
        elif hasattr(event, 'host_id'):
            # Look up host name from host_id in database
            try:
                host = self.db.get_host(event.host_id)
                return host.name if host else 'Unknown Host'
            except Exception:
                return 'Unknown Host'
        else:
            return 'Unknown Host'

    async def process_docker_event(self, event: DockerEventAlert) -> bool:
        """Process a Docker event and send alerts if rules match"""
        try:
            # Get matching alert rules for this event
            rules = self.db.get_alert_rules(enabled_only=True)
            matching_rules = []

            host_name = self._get_host_name(event)
            logger.info(f"Processing Docker event: {event.event_type} for container '{event.container_name}' on host '{host_name}'")

            for rule in rules:
                # Check if rule has event triggers
                if not rule.trigger_events:
                    continue

                # Check if this event type matches any triggers
                event_matches = False
                for trigger in rule.trigger_events:
                    # Handle special event mappings
                    if trigger == "die-nonzero" and event.event_type == "die" and event.exit_code and event.exit_code != 0:
                        event_matches = True
                        break
                    elif trigger == "die-zero" and event.event_type == "die" and event.exit_code == 0:
                        event_matches = True
                        break
                    elif trigger == event.event_type:
                        event_matches = True
                        break
                    # Handle health status events
                    elif trigger.startswith("health_status:") and event.event_type == "health_status":
                        health_status = event.attributes.get("health_status") if event.attributes else None
                        if health_status and trigger == f"health_status:{health_status}":
                            event_matches = True
                            break

                if not event_matches:
                    continue

                # Check if this container+host matches the rule
                # First check if rule has specific container+host pairs
                if hasattr(rule, 'containers') and rule.containers:
                    # Use specific container+host pairs
                    matches = False
                    for container in rule.containers:
                        if (container.host_id == event.host_id and
                            container.container_name == event.container_name):
                            matches = True
                            break

                    if not matches:
                        continue
                else:
                    continue

                logger.info(f"Docker event matches rule {rule.id}: {rule.name}")
                matching_rules.append(rule)

            if not matching_rules:
                logger.debug(f"No rules match Docker event {event.event_type} for container '{event.container_name}' on host '{host_name}'")
                return False

            # Send notifications for matching rules
            success_count = 0
            for rule in matching_rules:
                logger.info(f"Processing Docker event rule '{rule.name}' for container '{event.container_name}' on host '{host_name}'")

                # Check cooldown
                container_key = f"{event.host_id}:{event.container_id}"
                cooldown_key = f"event:{rule.id}:{container_key}:{event.event_type}"

                # Periodic cleanup of old cooldown entries (every ~100 alerts)
                if len(self._last_alerts) % 100 == 0:
                    self._cleanup_old_cooldowns()

                # Check cooldown
                if cooldown_key in self._last_alerts:
                    time_since = datetime.now(timezone.utc) - self._last_alerts[cooldown_key]
                    if time_since.total_seconds() < rule.cooldown_minutes * 60:
                        logger.info(f"Skipping Docker event alert for container '{event.container_name}' on host '{host_name}' (rule: {rule.name}) due to cooldown")
                        continue

                # Check if we're in a blackout window
                is_blackout, window_name = self.blackout_manager.is_in_blackout_window()
                logger.info(f"Blackout check for Docker event (rule: {rule.name}): is_blackout={is_blackout}, window_name={window_name}")
                if is_blackout:
                    logger.info(f"Docker event alert suppressed during blackout window '{window_name}' for container '{event.container_name}' on host '{host_name}' (rule: {rule.name})")
                    continue

                # Send notification
                logger.info(f"Sending Docker event notification for rule '{rule.name}'")
                if await self._send_event_notification(rule, event):
                    success_count += 1
                    self._last_alerts[cooldown_key] = datetime.now(timezone.utc)

                    # Update rule's last triggered time
                    self.db.update_alert_rule(rule.id, {
                        'last_triggered': datetime.now(timezone.utc)
                    })

            return success_count > 0

        except Exception as e:
            host_name = self._get_host_name(event)
            logger.error(f"Error processing Docker event for container '{event.container_name}' on host '{host_name}': {e}")
            return False

    async def _send_event_notification(self, rule: AlertRuleDB, event: DockerEventAlert) -> bool:
        """Send notifications for a Docker event"""
        try:
            # Get host name
            host_name = event.host_id
            try:
                with self.db.get_session() as session:
                    from database import DockerHostDB
                    host = session.query(DockerHostDB).filter_by(id=event.host_id).first()
                    if host:
                        host_name = host.name
            except Exception as e:
                logger.warning(f"Could not get host name: {e}")

            # Get container image
            image = event.attributes.get('image', 'Unknown') if event.attributes else 'Unknown'

            # Format event type description
            if event.event_type == "die":
                if event.exit_code == 0:
                    event_desc = "Container stopped normally (exit code 0)"
                    emoji = "🟢"
                else:
                    event_desc = f"Container died with exit code {event.exit_code}"
                    emoji = "🔴"
            elif event.event_type == "oom":
                event_desc = "Container killed due to Out Of Memory (OOM)"
                emoji = "💀"
            elif event.event_type == "kill":
                event_desc = "Container was killed"
                emoji = "⚠️"
            elif event.event_type.startswith("health_status"):
                status = event.attributes.get("health_status", "unknown") if event.attributes else "unknown"
                if status == "unhealthy":
                    event_desc = "Container is UNHEALTHY"
                    emoji = "🏥"
                elif status == "healthy":
                    event_desc = "Container is healthy again"
                    emoji = "✅"
                else:
                    event_desc = f"Health status: {status}"
                    emoji = "🏥"
            elif event.event_type == "restart-loop":
                event_desc = "Container is in a restart loop"
                emoji = "🔄"
            else:
                event_desc = f"Docker event: {event.event_type}"
                emoji = "📢"

            # Format structured message like state alerts
            message = f"""{emoji} **DockMon Alert**

**Container:** `{event.container_name}`
**Host:** {host_name}
**Event:** {event_desc}
**Image:** {image}
**Time:** {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
**Rule:** {rule.name}"""

            # Get notification channels
            channels = self.db.get_notification_channels_by_ids(rule.notification_channels)

            success_count = 0
            total_channels = len(channels)

            for channel in channels:
                if channel.enabled:
                    try:
                        if channel.type == 'telegram':
                            await self._send_telegram(channel.config, message)
                            success_count += 1
                        elif channel.type == 'discord':
                            await self._send_discord(channel.config, message)
                            success_count += 1
                        elif channel.type == 'pushover':
                            await self._send_pushover(channel.config, message, event)
                            success_count += 1
                        elif channel.type == 'slack':
                            await self._send_slack(channel.config, message, event)
                            success_count += 1
                        elif channel.type == 'gotify':
                            await self._send_gotify(channel.config, message, event)
                            success_count += 1
                        elif channel.type == 'smtp':
                            await self._send_smtp(channel.config, message, event)
                            success_count += 1
                        host_name = self._get_host_name(event)
                        logger.info(f"Event notification sent via {channel.type} for container '{event.container_name}' on host '{host_name}'")
                    except Exception as e:
                        logger.error(f"Failed to send {channel.type} notification: {e}")

            host_name = self._get_host_name(event)
            logger.info(f"Event alert sent to {success_count}/{total_channels} channels for container '{event.container_name}' on host '{host_name}'")
            return success_count > 0

        except Exception as e:
            logger.error(f"Error sending event notification: {e}")
            return False

    async def send_alert(self, event: AlertEvent) -> bool:
        """Process an alert event and send notifications"""
        try:
            # Get matching alert rules
            alert_rules = await self._get_matching_rules(event)

            host_name = self._get_host_name(event)
            logger.info(f"Found {len(alert_rules) if alert_rules else 0} matching alert rules for container '{event.container_name}' on host '{host_name}'")

            if not alert_rules:
                logger.warning(f"No alert rules match container '{event.container_name}' on host '{host_name}' (state: {event.old_state} → {event.new_state})")
                return False

            success_count = 0
            total_rules = len(alert_rules)

            # Check if we're in a blackout window
            is_blackout, window_name = self.blackout_manager.is_in_blackout_window()
            if is_blackout:
                logger.info(f"Suppressed {len(alert_rules)} alerts during blackout window '{window_name}' for container '{event.container_name}' on host '{host_name}'")
                # Track this alert for later (with cap to prevent memory leak)
                if len(self._suppressed_alerts) < self.MAX_SUPPRESSED_ALERTS:
                    self._suppressed_alerts.append(event)
                else:
                    logger.warning(f"Suppressed alerts queue full ({self.MAX_SUPPRESSED_ALERTS}), dropping oldest")
                    self._suppressed_alerts.pop(0)
                    self._suppressed_alerts.append(event)

                # Log suppression event
                if self.event_logger:
                    rule_names = ", ".join([rule.name for rule in alert_rules[:3]])  # First 3 rules
                    if len(alert_rules) > 3:
                        rule_names += f" (+{len(alert_rules) - 3} more)"

                    from event_logger import EventContext
                    context = EventContext(
                        host_id=event.host_id,
                        host_name=host_name,
                        container_id=event.container_id,
                        container_name=event.container_name
                    )

                    self.event_logger.log_event(
                        title=f"Alert Suppressed: {event.container_name}",
                        message=f"Alert suppressed during blackout window '{window_name}'. State change: {event.old_state} → {event.new_state}. Matching rules: {rule_names}",
                        category=EventCategory.ALERT,
                        event_type=EventType.RULE_TRIGGERED,
                        severity=EventSeverity.WARNING,
                        context=context,
                        old_state=event.old_state,
                        new_state=event.new_state,
                        details={"blackout_window": window_name, "rules_count": len(alert_rules), "suppressed": True}
                    )

                return False

            # Process each matching rule
            triggered_rules = []
            for rule in alert_rules:
                if await self._should_send_alert(rule, event):
                    if await self._send_rule_notifications(rule, event):
                        success_count += 1
                        triggered_rules.append(rule.name)
                        # Update last triggered time for this container + rule combination
                        container_key = f"{event.host_id}:{event.container_id}"
                        cooldown_key = f"{rule.id}:{container_key}"
                        self._last_alerts[cooldown_key] = datetime.now(timezone.utc)

                        # Also update the rule's global last_triggered for backward compatibility
                        self.db.update_alert_rule(rule.id, {
                            'last_triggered': datetime.now(timezone.utc)
                        })

            # Log the event to new event system
            if success_count > 0 and self.event_logger:
                rule_names = ", ".join(triggered_rules[:3])  # First 3 rules
                if len(triggered_rules) > 3:
                    rule_names += f" (+{len(triggered_rules) - 3} more)"

                # Determine severity based on state
                severity = EventSeverity.CRITICAL if event.new_state in ['exited', 'dead'] else EventSeverity.ERROR

                from event_logger import EventContext
                context = EventContext(
                    host_id=event.host_id,
                    host_name=host_name,
                    container_id=event.container_id,
                    container_name=event.container_name
                )

                self.event_logger.log_event(
                    category=EventCategory.ALERT,
                    event_type=EventType.RULE_TRIGGERED,
                    title=f"Alert Triggered: {event.container_name}",
                    message=f"{success_count} alert rule(s) triggered for container state change: {event.old_state} → {event.new_state}. Rules: {rule_names}",
                    severity=severity,
                    context=context,
                    old_state=event.old_state,
                    new_state=event.new_state,
                    details={"rules_triggered": triggered_rules, "rules_count": success_count, "total_rules": total_rules}
                )

            return success_count > 0

        except Exception as e:
            host_name = self._get_host_name(event)
            logger.error(f"Error processing alert for container '{event.container_name}' on host '{host_name}': {e}")
            return False

    async def _get_matching_rules(self, event: AlertEvent) -> List[AlertRuleDB]:
        """Get alert rules that match the container and state change"""
        rules = self.db.get_alert_rules(enabled_only=True)
        matching_rules = []

        host_name = self._get_host_name(event)
        logger.info(f"Checking {len(rules)} alert rules for container '{event.container_name}' on host '{host_name}' (state: {event.old_state} → {event.new_state})")

        for rule in rules:
            container_info = f"{len(rule.containers)} container+host pairs" if hasattr(rule, 'containers') and rule.containers else "no containers"
            logger.debug(f"Rule {rule.id}: name='{rule.name}', containers={container_info}, states={rule.trigger_states}, events={rule.trigger_events}")

            # Check if this container+host matches the rule
            # First check if rule has specific container+host pairs
            if hasattr(rule, 'containers') and rule.containers:
                # Use specific container+host pairs
                matches = False
                for container in rule.containers:
                    if (container.host_id == event.host_id and
                        container.container_name == event.container_name):
                        matches = True
                        break

                if not matches:
                    logger.debug(f"Rule {rule.id} skipped: no matching container+host pair")
                    continue
            else:
                # No containers specified = monitor all containers
                logger.debug(f"Rule {rule.id} matches: monitoring all containers")

            # Check if new state triggers alert (only if trigger_states is defined)
            if rule.trigger_states and event.new_state not in rule.trigger_states:
                logger.debug(f"Rule {rule.id} skipped: state '{event.new_state}' not in triggers {rule.trigger_states}")
                continue
            elif not rule.trigger_states:
                # This rule only has event triggers, not state triggers, skip for state changes
                logger.debug(f"Rule {rule.id} skipped: no state triggers defined (events only)")
                continue

            logger.debug(f"Rule {rule.id} MATCHES!")
            matching_rules.append(rule)

        return matching_rules

    async def _should_send_alert(self, rule: AlertRuleDB, event: AlertEvent) -> bool:
        """Check if alert should be sent based on cooldown per container"""
        container_key = f"{event.host_id}:{event.container_id}"
        cooldown_key = f"{rule.id}:{container_key}"

        # Check if container recovered (went to a non-alert state) since last alert
        # Use old_state from the event, not our tracked state!
        host_name = self._get_host_name(event)
        logger.debug(f"Alert check for container '{event.container_name}' on host '{host_name}': {event.old_state} → {event.new_state}")

        # If container was in a "good" state (running) and now in "bad" state (exited),
        # this is a new incident - reset cooldown
        good_states = ['running', 'created']
        if rule.trigger_states and event.old_state in good_states and event.new_state in rule.trigger_states:
            logger.info(f"Alert allowed for container '{event.container_name}' on host '{host_name}': Container recovered ({event.old_state}) then failed ({event.new_state}) - new incident detected")
            # Remove the cooldown for this container
            if cooldown_key in self._last_alerts:
                del self._last_alerts[cooldown_key]
            return True

        if cooldown_key not in self._last_alerts:
            logger.debug(f"Alert allowed: No previous alert for this container")
            return True

        # Check cooldown period
        time_since_last = datetime.now(timezone.utc) - self._last_alerts[cooldown_key]
        cooldown_minutes = rule.cooldown_minutes or 15
        cooldown_seconds = cooldown_minutes * 60

        if time_since_last.total_seconds() >= cooldown_seconds:
            logger.debug(f"Alert allowed: Cooldown period exceeded ({time_since_last.total_seconds():.1f}s > {cooldown_seconds}s)")
            return True
        else:
            host_name = self._get_host_name(event)
            logger.info(f"Alert blocked for container '{event.container_name}' on host '{host_name}': Still in cooldown ({cooldown_seconds - time_since_last.total_seconds():.1f}s remaining)")
            return False

    async def _send_rule_notifications(self, rule: AlertRuleDB, event: AlertEvent) -> bool:
        """Send notifications for a specific rule"""
        if not rule.notification_channels:
            return False

        channels = self.db.get_notification_channels(enabled_only=True)
        channel_map = {str(ch.id): ch for ch in channels}

        success_count = 0
        total_channels = len(rule.notification_channels)

        # Send to each configured channel
        for channel_id in rule.notification_channels:
            if str(channel_id) in channel_map:
                channel = channel_map[str(channel_id)]
                try:
                    if await self._send_to_channel(channel, event, rule):
                        success_count += 1
                except Exception as e:
                    logger.error(f"Failed to send to channel {channel.name}: {e}")

        host_name = self._get_host_name(event)
        logger.info(f"Alert sent to {success_count}/{total_channels} channels for container '{event.container_name}' on host '{host_name}'")
        return success_count > 0

    async def _send_to_channel(self, channel: NotificationChannel,
                             event: AlertEvent, rule: AlertRuleDB) -> bool:
        """Send notification to a specific channel"""
        # Get global template from settings
        settings = self.db.get_settings()
        template = getattr(settings, 'alert_template', None) if settings else None

        # Use global template or default
        if not template:
            template = self._get_default_template(channel.type)

        message = self._format_message(event, rule, template)

        if channel.type == "telegram":
            return await self._send_telegram(channel.config, message)
        elif channel.type == "discord":
            return await self._send_discord(channel.config, message)
        elif channel.type == "pushover":
            return await self._send_pushover(channel.config, message, event)
        elif channel.type == "slack":
            return await self._send_slack(channel.config, message, event)
        elif channel.type == "gotify":
            return await self._send_gotify(channel.config, message, event)
        elif channel.type == "smtp":
            return await self._send_smtp(channel.config, message, event)
        else:
            logger.warning(f"Unknown notification channel type: {channel.type}")
            return False

    def _get_default_template(self, channel_type: str = None) -> str:
        """Get default template for channel type"""
        # Default template with variables - ends with separator for visual distinction
        default = """🚨 **DockMon Alert**

**Container:** `{CONTAINER_NAME}`
**Host:** {HOST_NAME}
**State Change:** `{OLD_STATE}` → `{NEW_STATE}`
**Image:** {IMAGE}
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}
───────────────────────"""

        # Channel-specific defaults (can be customized per platform)
        templates = {
            'slack': default,
            'discord': default,
            'telegram': default,
            'pushover': """DockMon Alert
Container: {CONTAINER_NAME}
Host: {HOST_NAME}
State: {OLD_STATE} → {NEW_STATE}
Image: {IMAGE}
Time: {TIMESTAMP}
Rule: {RULE_NAME}
---"""
        }

        return templates.get(channel_type, default)

    def _format_message(self, event: AlertEvent, rule: AlertRuleDB, template: str = None) -> str:
        """Format alert message using template with variable substitution"""
        # Use provided template or default
        if not template:
            template = self._get_default_template()

        # Get timezone offset from settings
        settings = self.db.get_settings()
        timezone_offset = getattr(settings, 'timezone_offset', 0) if settings else 0

        # Convert timestamp to local timezone
        local_timestamp = event.timestamp + timedelta(minutes=timezone_offset)

        # Prepare variables for substitution
        host_name = self._get_host_name(event)
        variables = {
            '{CONTAINER_NAME}': event.container_name,
            '{CONTAINER_ID}': event.container_id[:12],  # Short ID
            '{HOST_NAME}': host_name,
            '{HOST_ID}': event.host_id,
            '{OLD_STATE}': event.old_state,
            '{NEW_STATE}': event.new_state,
            '{IMAGE}': event.image,
            '{TIMESTAMP}': local_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            '{TIME}': local_timestamp.strftime('%H:%M:%S'),
            '{DATE}': local_timestamp.strftime('%Y-%m-%d'),
            '{RULE_NAME}': rule.name,
            '{RULE_ID}': str(rule.id),
            '{TRIGGERED_BY}': event.triggered_by,
        }

        # Handle optional Docker event attributes
        if hasattr(event, 'event_type'):
            variables['{EVENT_TYPE}'] = event.event_type
            if hasattr(event, 'exit_code') and event.exit_code is not None:
                variables['{EXIT_CODE}'] = str(event.exit_code)

        # Replace all variables in template
        message = template
        for var, value in variables.items():
            message = message.replace(var, value)

        # Clean up any unused variables (remove them)
        import re
        message = re.sub(r'\{[A-Z_]+\}', '', message)

        return message

    async def _send_telegram(self, config: Dict[str, Any], message: str) -> bool:
        """Send notification via Telegram"""
        try:
            # Support both 'token' and 'bot_token' for backward compatibility
            token = config.get('token') or config.get('bot_token')
            chat_id = config.get('chat_id')

            if not token or not chat_id:
                logger.error(f"Telegram config missing token or chat_id")
                return False

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }

            response = await self.http_client.post(url, json=payload)
            response.raise_for_status()

            logger.info("Telegram notification sent successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False

    async def _send_discord(self, config: Dict[str, Any], message: str) -> bool:
        """Send notification via Discord webhook"""
        try:
            webhook_url = config.get('webhook_url')

            if not webhook_url:
                logger.error("Discord config missing webhook_url")
                return False

            # Convert markdown to Discord format
            discord_message = message.replace('`', '`').replace('**', '**')

            payload = {
                'content': discord_message,
                'username': 'DockMon',
                'avatar_url': 'https://cdn-icons-png.flaticon.com/512/919/919853.png'
            }

            response = await self.http_client.post(webhook_url, json=payload)
            response.raise_for_status()

            logger.info("Discord notification sent successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
            return False

    async def _send_pushover(self, config: Dict[str, Any], message: str,
                           event) -> bool:
        """Send notification via Pushover"""
        try:
            app_token = config.get('app_token')
            user_key = config.get('user_key')

            if not app_token or not user_key:
                logger.error("Pushover config missing app_token or user_key")
                return False

            # Strip markdown for Pushover
            plain_message = re.sub(r'\*\*(.*?)\*\*', r'\1', message)  # Bold
            plain_message = re.sub(r'`(.*?)`', r'\1', plain_message)   # Code
            plain_message = re.sub(r'🚨', '', plain_message)  # Remove alert emoji

            # Determine priority based on event type
            priority = 0  # Normal
            # Handle both AlertEvent and DockerEventAlert
            if hasattr(event, 'new_state') and event.new_state in ['exited', 'dead']:
                priority = 1  # High priority for state failures
            elif hasattr(event, 'event_type') and event.event_type in ['die', 'oom', 'kill']:
                priority = 1  # High priority for critical Docker events

            payload = {
                'token': app_token,
                'user': user_key,
                'message': plain_message,
                'title': f"DockMon: {event.container_name}",
                'priority': priority,
                'url': config.get('url', ''),
                'url_title': 'Open DockMon'
            }

            response = await self.http_client.post(
                'https://api.pushover.net/1/messages.json',
                data=payload
            )
            response.raise_for_status()

            logger.info("Pushover notification sent successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to send Pushover notification: {e}")
            return False

    async def _send_slack(self, config: Dict[str, Any], message: str, event: AlertEvent) -> bool:
        """Send notification via Slack webhook"""
        try:
            webhook_url = config.get('webhook_url')

            if not webhook_url:
                logger.error("Slack config missing webhook_url")
                return False

            # Convert markdown to Slack format
            # Slack uses mrkdwn format which is similar to markdown but with some differences
            slack_message = message.replace('**', '*')  # Bold in Slack is single asterisk
            slack_message = slack_message.replace('`', '`')  # Code blocks remain the same

            # Determine color based on event type
            color = "#ff0000"  # Default red for critical
            if hasattr(event, 'new_state'):
                if event.new_state == 'running':
                    color = "#00ff00"  # Green for running
                elif event.new_state in ['stopped', 'paused']:
                    color = "#ffaa00"  # Orange for stopped/paused
            elif hasattr(event, 'event_type'):
                if event.event_type in ['start', 'unpause']:
                    color = "#00ff00"  # Green for recovery events
                elif event.event_type in ['stop', 'pause']:
                    color = "#ffaa00"  # Orange for controlled stops

            # Create rich Slack message with attachments
            payload = {
                'attachments': [{
                    'color': color,
                    'fallback': slack_message,
                    'title': '🚨 DockMon Alert',
                    'text': slack_message,
                    'mrkdwn_in': ['text'],
                    'footer': 'DockMon',
                    'footer_icon': 'https://raw.githubusercontent.com/docker/compose/v2/logo.png',
                    'ts': int(event.timestamp.timestamp())
                }]
            }

            response = await self.http_client.post(webhook_url, json=payload)
            response.raise_for_status()

            logger.info("Slack notification sent successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False

    async def _send_gotify(self, config: Dict[str, Any], message: str, event) -> bool:
        """Send notification via Gotify"""
        try:
            # Validate required config fields
            server_url = config.get('server_url', '').strip()
            app_token = config.get('app_token', '').strip()

            if not server_url:
                logger.error("Gotify config missing server_url")
                return False

            if not app_token:
                logger.error("Gotify config missing app_token")
                return False

            # Validate server URL format
            if not server_url.startswith(('http://', 'https://')):
                logger.error(f"Gotify server_url must start with http:// or https://: {server_url}")
                return False

            # Strip markdown formatting for plain text
            plain_message = re.sub(r'\*\*(.*?)\*\*', r'\1', message)
            plain_message = re.sub(r'`(.*?)`', r'\1', plain_message)
            plain_message = re.sub(r'[🚨🔴🟢💀⚠️🏥✅🔄📢]', '', plain_message)  # Remove emojis

            # Determine priority (0-10, default 5)
            priority = 5
            if hasattr(event, 'new_state') and event.new_state in ['exited', 'dead']:
                priority = 8  # High priority for critical states
            elif hasattr(event, 'event_type') and event.event_type in ['die', 'oom', 'kill']:
                priority = 8  # High priority for critical events

            # Build URL with proper path handling
            base_url = server_url.rstrip('/')
            url = f"{base_url}/message?token={app_token}"

            # Create payload
            payload = {
                'title': f"DockMon: {event.container_name}",
                'message': plain_message,
                'priority': priority
            }

            # Send request with timeout
            response = await self.http_client.post(url, json=payload)
            response.raise_for_status()

            logger.info("Gotify notification sent successfully")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Gotify HTTP error {e.response.status_code}: {e}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Gotify connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Gotify notification: {e}")
            return False

    async def _send_smtp(self, config: Dict[str, Any], message: str, event) -> bool:
        """Send notification via SMTP (Email)"""
        try:
            # Import SMTP libraries (only when needed to avoid dependency issues)
            try:
                import aiosmtplib
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart
            except ImportError:
                logger.error("SMTP support requires 'aiosmtplib' package. Install with: pip install aiosmtplib")
                return False

            # Validate required config fields
            smtp_host = config.get('smtp_host', '').strip()
            smtp_port = config.get('smtp_port', 587)
            smtp_user = config.get('smtp_user', '').strip()
            smtp_password = config.get('smtp_password', '').strip()
            from_email = config.get('from_email', '').strip()
            to_email = config.get('to_email', '').strip()
            use_tls = config.get('use_tls', True)

            # Validate all required fields
            if not smtp_host:
                logger.error("SMTP config missing smtp_host")
                return False
            if not smtp_user:
                logger.error("SMTP config missing smtp_user")
                return False
            if not smtp_password:
                logger.error("SMTP config missing smtp_password")
                return False
            if not from_email:
                logger.error("SMTP config missing from_email")
                return False
            if not to_email:
                logger.error("SMTP config missing to_email")
                return False

            # Validate port range
            try:
                smtp_port = int(smtp_port)
                if smtp_port < 1 or smtp_port > 65535:
                    logger.error(f"SMTP port must be between 1-65535: {smtp_port}")
                    return False
            except (ValueError, TypeError):
                logger.error(f"Invalid SMTP port: {smtp_port}")
                return False

            # Validate email format (basic check)
            email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
            if not email_pattern.match(from_email):
                logger.error(f"Invalid from_email format: {from_email}")
                return False
            if not email_pattern.match(to_email):
                logger.error(f"Invalid to_email format: {to_email}")
                return False

            # Create multipart email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"DockMon Alert: {event.container_name}"
            msg['From'] = from_email
            msg['To'] = to_email

            # Plain text version (strip markdown and emojis)
            plain_text = re.sub(r'\*\*(.*?)\*\*', r'\1', message)
            plain_text = re.sub(r'`(.*?)`', r'\1', plain_text)
            plain_text = re.sub(r'[🚨🔴🟢💀⚠️🏥✅🔄📢]', '', plain_text)

            # HTML version with basic styling (light theme for better email compatibility)
            html_text = message.replace('\n', '<br>')
            html_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html_text)
            html_text = re.sub(r'`(.*?)`', r'<code style="background:#f5f5f5;color:#333;padding:2px 6px;border-radius:3px;font-family:monospace;">\1</code>', html_text)

            html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;background:#f9f9f9;color:#333;">
    <div style="max-width:600px;margin:20px auto;background:#ffffff;padding:24px;border-radius:8px;border:1px solid #e0e0e0;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
        <div style="line-height:1.6;font-size:14px;">
            {html_text}
        </div>
        <div style="margin-top:20px;padding-top:20px;border-top:1px solid #e0e0e0;font-size:12px;color:#666;">
            Sent by DockMon Container Monitoring
        </div>
    </div>
</body>
</html>"""

            # Attach both versions
            part1 = MIMEText(plain_text, 'plain', 'utf-8')
            part2 = MIMEText(html_body, 'html', 'utf-8')
            msg.attach(part1)
            msg.attach(part2)

            # Send email with proper connection handling
            # Port 587 uses STARTTLS, port 465 uses direct TLS/SSL
            if smtp_port == 587:
                smtp_kwargs = {
                    'hostname': smtp_host,
                    'port': smtp_port,
                    'start_tls': use_tls,  # Use STARTTLS for port 587
                    'timeout': 30
                }
            elif smtp_port == 465:
                smtp_kwargs = {
                    'hostname': smtp_host,
                    'port': smtp_port,
                    'use_tls': use_tls,  # Use direct TLS for port 465
                    'timeout': 30
                }
            else:
                # Other ports (like 25) - no encryption by default unless use_tls is True
                smtp_kwargs = {
                    'hostname': smtp_host,
                    'port': smtp_port,
                    'start_tls': use_tls if use_tls else False,
                    'timeout': 30
                }

            async with aiosmtplib.SMTP(**smtp_kwargs) as smtp:
                await smtp.login(smtp_user, smtp_password)
                await smtp.send_message(msg)

            logger.info(f"SMTP notification sent successfully to {to_email}")
            return True

        except aiosmtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            return False
        except aiosmtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send SMTP notification: {e}")
            return False

    async def test_channel(self, channel_id: int) -> Dict[str, Any]:
        """Test a notification channel"""
        try:
            channel = self.db.get_notification_channels(enabled_only=False)
            channel = next((ch for ch in channel if ch.id == channel_id), None)

            if not channel:
                return {'success': False, 'error': 'Channel not found'}

            # Create test event
            test_event = AlertEvent(
                container_id='test_container',
                container_name='test-container',
                host_id='test_host',
                host_name='Test Host',
                old_state='running',
                new_state='stopped',
                timestamp=datetime.now(timezone.utc),
                image='nginx:latest',
                triggered_by='test'
            )

            # Create test rule
            test_rule = type('TestRule', (), {
                'id': 'test_rule',
                'name': 'Test Notification',
                'notification_channels': [channel_id]
            })()

            success = await self._send_to_channel(channel, test_event, test_rule)

            return {
                'success': success,
                'channel_name': channel.name,
                'channel_type': channel.type
            }

        except Exception as e:
            logger.error(f"Error testing channel {channel_id}: {e}")
            return {'success': False, 'error': str(e)}

    async def process_suppressed_alerts(self, monitor):
        """Process alerts that were suppressed during blackout windows

        Args:
            monitor: The DockerMonitor instance (reused, not created)
        """
        if not self._suppressed_alerts:
            logger.info("No suppressed alerts to process")
            return

        logger.info(f"Processing {len(self._suppressed_alerts)} suppressed alerts from blackout windows")

        alerts_to_send = []

        # For each suppressed alert, check if the container is still in that problematic state
        for alert in self._suppressed_alerts:
            container_key = f"{alert.host_id}:{alert.container_id}"

            # Get current state of this container
            try:
                client = monitor.clients.get(alert.host_id)
                if not client:
                    logger.debug(f"No client found for host {alert.host_id}")
                    continue

                try:
                    container = client.containers.get(alert.container_id)
                    current_state = container.status

                    # If container is still in the problematic state from the alert, send it
                    if current_state == alert.new_state:
                        logger.info(f"Container {alert.container_name} still in '{current_state}' state - sending suppressed alert")
                        alerts_to_send.append(alert)
                    else:
                        logger.info(f"Container {alert.container_name} recovered from '{alert.new_state}' to '{current_state}' during blackout window - skipping alert")

                except Exception as e:
                    # Container might have been removed
                    logger.debug(f"Could not check container {alert.container_id}: {e}")

            except Exception as e:
                logger.error(f"Error checking suppressed alert for {alert.container_name}: {e}")

        # Clear the suppressed alerts list
        self._suppressed_alerts.clear()

        # Send alerts for containers still in problematic states
        for alert in alerts_to_send:
            try:
                await self.send_alert(alert)
            except Exception as e:
                logger.error(f"Failed to send suppressed alert for {alert.container_name}: {e}")

        logger.info(f"Sent {len(alerts_to_send)} of {len(self._suppressed_alerts) + len(alerts_to_send)} suppressed alerts")

    async def send_alert_v2(self, alert, rule=None) -> bool:
        """
        Send notifications for Alert System v2

        Args:
            alert: AlertV2 database object
            rule: Optional AlertRuleV2 object (if not provided, will be fetched)

        Returns:
            True if notification sent successfully to at least one channel
        """
        try:
            # Prevent duplicate notifications within 5 seconds (Docker sends kill/stop/die almost simultaneously)
            # This protects against rapid-fire notifications from the same event
            if hasattr(alert, 'notified_at') and alert.notified_at:
                time_since_notified = datetime.now(timezone.utc) - alert.notified_at.replace(tzinfo=timezone.utc if not alert.notified_at.tzinfo else None)
                if time_since_notified.total_seconds() < 5:
                    logger.debug(f"Skipping duplicate notification for alert {alert.id} (last notified {time_since_notified.total_seconds():.1f}s ago)")
                    return False

            # Get the rule if not provided
            if rule is None and alert.rule_id:
                rule = self.db.get_alert_rule_v2(alert.rule_id)

            if not rule:
                logger.warning(f"No rule found for alert {alert.id}, cannot send notification")
                return False

            # Parse notification channels from rule
            try:
                channel_ids = json.loads(rule.notify_channels_json) if rule.notify_channels_json else []
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid notify_channels_json for rule {rule.id}")
                return False

            if not channel_ids:
                logger.debug(f"No notification channels configured for rule {rule.name}")
                return False

            # Check blackout window
            is_blackout, window_name = self.blackout_manager.is_in_blackout_window()
            if is_blackout:
                logger.info(f"Suppressed alert '{alert.title}' during blackout window '{window_name}'")
                return False

            # Get enabled channels
            channels = self.db.get_notification_channels(enabled_only=True)
            # Support both ID-based (integers) and type-based (strings like "discord") lookup
            channel_map_by_id = {ch.id: ch for ch in channels}
            channel_map_by_type = {ch.type: ch for ch in channels}

            success_count = 0
            total_channels = len(channel_ids)

            # Determine which template to use (priority: custom > category > global)
            template = self._get_template_for_alert_v2(alert, rule)

            # Format the message with alert variables
            message = self._format_message_v2(alert, rule, template)

            # Send to each configured channel
            for channel_id in channel_ids:
                # Try to find channel by ID first (integer), then by type (string)
                channel = None
                if isinstance(channel_id, int) and channel_id in channel_map_by_id:
                    channel = channel_map_by_id[channel_id]
                elif isinstance(channel_id, str) and channel_id in channel_map_by_type:
                    channel = channel_map_by_type[channel_id]

                if channel:
                    try:
                        if channel.type == "telegram":
                            if await self._send_telegram(channel.config, message):
                                success_count += 1
                        elif channel.type == "discord":
                            if await self._send_discord(channel.config, message):
                                success_count += 1
                        elif channel.type == "slack":
                            if await self._send_slack(channel.config, message):
                                success_count += 1
                        elif channel.type == "pushover":
                            if await self._send_pushover(channel.config, message, alert.title):
                                success_count += 1
                    except Exception as e:
                        logger.error(f"Failed to send alert to channel {channel.name}: {e}")

            # Update notified_at timestamp to prevent immediate duplicates
            if success_count > 0:
                with self.db.get_session() as session:
                    alert_to_update = session.query(AlertV2).filter(AlertV2.id == alert.id).first()
                    if alert_to_update:
                        alert_to_update.notified_at = datetime.now(timezone.utc)
                        alert_to_update.notification_count = (alert_to_update.notification_count or 0) + 1
                        session.commit()

            logger.info(f"Alert '{alert.title}' sent to {success_count}/{total_channels} channels")
            return success_count > 0

        except Exception as e:
            logger.error(f"Error sending alert v2 notification: {e}", exc_info=True)
            return False

    def _get_template_for_alert_v2(self, alert, rule):
        """Get the appropriate template for v2 alert based on priority"""
        # Priority 1: Custom template on the rule
        if rule.custom_template:
            return rule.custom_template

        # Priority 2: Category-specific template based on alert kind
        settings = self.db.get_settings()
        if settings:
            # Check if it's a metric alert
            if rule.metric and settings.alert_template_metric:
                return settings.alert_template_metric
            # Check if it's a state change alert
            elif rule.kind in ['container_stopped', 'container_restarted'] and settings.alert_template_state_change:
                return settings.alert_template_state_change
            # Check if it's a health alert
            elif rule.kind in ['container_unhealthy', 'host_unhealthy'] and settings.alert_template_health:
                return settings.alert_template_health
            # Check if it's an update alert
            elif rule.kind in ['update_completed', 'update_available', 'update_failed'] and settings.alert_template_update:
                return settings.alert_template_update
            # Priority 3: Global default template
            elif settings.alert_template:
                return settings.alert_template

        # Fallback: Built-in default template (kind-specific)
        return self._get_default_template_v2(rule.kind)

    def _get_default_template_v2(self, kind=None):
        """Get built-in default template for v2 alerts - generic fallback only"""
        return """🚨 **{SEVERITY} Alert: {KIND}**

**{TITLE}**
{MESSAGE}

**Details:**
- Container: {CONTAINER_NAME}
- Host: {HOST_NAME}
- Severity: {SEVERITY}
- Scope: {SCOPE_TYPE}
- First Seen: {FIRST_SEEN}
- Occurrences: {OCCURRENCES}

🤖 DockMon Alert System"""

    def _format_exit_code(self, exit_code: int) -> str:
        """Format exit code to human-readable string"""
        try:
            code = int(exit_code)
            if code == 0:
                return "0 (Clean exit)"
            elif code == 137:
                return "137 (SIGKILL - Force killed / OOM)"
            elif code == 143:
                return "143 (SIGTERM - Graceful stop)"
            elif code == 130:
                return "130 (SIGINT - Interrupted)"
            elif code == 126:
                return "126 (Command cannot execute)"
            elif code == 127:
                return "127 (Command not found)"
            elif code == 128:
                return "128 (Invalid exit code)"
            elif 129 <= code <= 255:
                # Signal = code - 128
                signal = code - 128
                return f"{code} (Signal {signal})"
            elif 1 <= code <= 127:
                return f"{code} (Application error)"
            else:
                return str(code)
        except (ValueError, TypeError):
            return str(exit_code) if exit_code is not None else ''

    def _format_message_v2(self, alert, rule, template):
        """Format message for v2 alert with variable substitution"""
        # Get timezone offset from settings
        settings = self.db.get_settings()
        tz_offset_minutes = settings.timezone_offset if settings else 0

        # Create timezone object from offset
        local_tz = timezone(timedelta(minutes=tz_offset_minutes))

        # Convert UTC timestamps to local time
        first_seen_local = alert.first_seen.replace(tzinfo=timezone.utc).astimezone(local_tz) if alert.first_seen else datetime.now(timezone.utc)
        last_seen_local = alert.last_seen.replace(tzinfo=timezone.utc).astimezone(local_tz) if alert.last_seen else datetime.now(timezone.utc)

        # Build variable substitution map
        # Shorten container ID to 12 characters (Docker standard)
        container_id_short = alert.scope_id[:12] if alert.scope_type == 'container' and alert.scope_id else 'N/A'

        variables = {
            # Basic entity info
            '{CONTAINER_NAME}': alert.container_name or 'N/A',
            '{CONTAINER_ID}': container_id_short,
            '{HOST_NAME}': alert.host_name or 'N/A',
            '{HOST_ID}': alert.scope_id if alert.scope_type == 'host' else 'N/A',

            # Alert info
            '{SEVERITY}': alert.severity.upper(),
            '{KIND}': alert.kind,
            '{TITLE}': alert.title,
            '{MESSAGE}': alert.message,
            '{SCOPE_TYPE}': alert.scope_type.capitalize(),
            '{SCOPE_ID}': alert.scope_id,
            '{STATE}': alert.state,

            # Temporal info
            '{FIRST_SEEN}': first_seen_local.strftime('%Y-%m-%d %H:%M:%S'),
            '{LAST_SEEN}': last_seen_local.strftime('%Y-%m-%d %H:%M:%S'),
            '{TIMESTAMP}': last_seen_local.strftime('%Y-%m-%d %H:%M:%S'),
            '{TIME}': last_seen_local.strftime('%H:%M:%S'),
            '{DATE}': last_seen_local.strftime('%Y-%m-%d'),
            '{OCCURRENCES}': str(alert.occurrences),

            # Rule context
            '{RULE_NAME}': rule.name if rule else 'N/A',
            '{RULE_ID}': alert.rule_id or 'N/A',

            # Metrics (for metric-driven alerts)
            '{CURRENT_VALUE}': str(alert.current_value) if alert.current_value is not None else 'N/A',
            '{THRESHOLD}': str(alert.threshold) if alert.threshold is not None else 'N/A',

            # Initialize state change variables (will be overridden if event_context_json exists)
            '{OLD_STATE}': '',
            '{NEW_STATE}': '',
            '{EXIT_CODE}': '',
            '{IMAGE}': '',
            '{EVENT_TYPE}': '',
            '{TRIGGERED_BY}': 'system',
        }

        # Optional labels
        if alert.labels_json:
            try:
                labels = json.loads(alert.labels_json)
                labels_str = ', '.join([f'{k}={v}' for k, v in labels.items()])
                variables['{LABELS}'] = labels_str
            except:
                variables['{LABELS}'] = ''
        else:
            variables['{LABELS}'] = ''

        # Event-specific context (for state change and health check alerts)
        if hasattr(alert, 'event_context_json') and alert.event_context_json:
            try:
                event_context = json.loads(alert.event_context_json)

                # State transition info
                variables['{OLD_STATE}'] = event_context.get('old_state', '') or ''
                variables['{NEW_STATE}'] = event_context.get('new_state', '') or ''

                # Translate exit code to human-readable format
                exit_code = event_context.get('exit_code')
                if exit_code is not None:
                    exit_code_display = self._format_exit_code(exit_code)
                    variables['{EXIT_CODE}'] = exit_code_display
                else:
                    variables['{EXIT_CODE}'] = ''

                variables['{IMAGE}'] = event_context.get('image', '') or ''
                variables['{EVENT_TYPE}'] = event_context.get('event_type', '') or ''
                variables['{TRIGGERED_BY}'] = event_context.get('triggered_by', 'system') or 'system'

                # Also check attributes for additional info if not directly available
                if not variables['{IMAGE}'] and 'attributes' in event_context:
                    attributes = event_context.get('attributes', {})
                    variables['{IMAGE}'] = attributes.get('image', '') or ''
            except Exception as e:
                logger.debug(f"Error parsing event context: {e}")

        # Replace all variables in template
        message = template
        for var, value in variables.items():
            message = message.replace(var, value)

        # Clean up any unused variables
        import re
        message = re.sub(r'\{[A-Z_]+\}', '', message)

        return message

    async def close(self):
        """Clean up resources"""
        await self.http_client.aclose()

    async def __aenter__(self):
        """Context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure cleanup"""
        await self.close()
        return False

class AlertProcessor:
    """Processes container state changes and triggers alerts"""

    def __init__(self, notification_service: NotificationService):
        self.notification_service = notification_service
        self._container_states: Dict[str, str] = {}  # Track previous states

    async def process_container_update(self, containers: List[Any], hosts: Dict[str, Any]):
        """Process container updates and trigger alerts for state changes"""
        for container in containers:
            # Use short_id for consistency
            container_key = f"{container.host_id}:{container.short_id}"
            current_state = container.status
            previous_state = self._container_states.get(container_key)

            # Skip if no state change
            if previous_state == current_state:
                continue

            # Update tracked state
            self._container_states[container_key] = current_state

            # IMPORTANT: Update the notification service's state tracking too
            # This ensures recovery states are tracked even when they don't trigger alerts
            self.notification_service._last_container_state[container_key] = current_state
            logger.debug(f"State transition for {container.name}: {previous_state} → {current_state}")

            # Skip if this is the first time we see this container
            if previous_state is None:
                continue

            # Create alert event
            host = hosts.get(container.host_id)
            host_name = host.name if host else 'Unknown Host'

            alert_event = AlertEvent(
                container_id=container.short_id,  # Use short_id for consistency
                container_name=container.name,
                host_id=container.host_id,
                host_name=host_name,
                old_state=previous_state,
                new_state=current_state,
                timestamp=datetime.now(timezone.utc),
                image=container.image,
                triggered_by='monitor'
            )

            # Send alert
            logger.debug(f"Processing state change for {container.name}: {previous_state} → {current_state}")
            await self.notification_service.send_alert(alert_event)

    def get_container_states(self) -> Dict[str, str]:
        """Get current container states for debugging"""
        return self._container_states.copy()