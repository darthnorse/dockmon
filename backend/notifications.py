"""
Notification service for DockMon
Handles sending alerts via Discord, Telegram, and Pushover
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import requests
import httpx
from database import DatabaseManager, NotificationChannel, AlertRuleDB, ContainerHistory

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

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._last_alerts: Dict[str, datetime] = {}  # For cooldown tracking
        self._last_container_state: Dict[str, str] = {}  # Track last known state per container

    async def process_docker_event(self, event: DockerEventAlert) -> bool:
        """Process a Docker event and send alerts if rules match"""
        try:
            # Get matching alert rules for this event
            rules = self.db.get_alert_rules(enabled_only=True)
            matching_rules = []

            logger.info(f"Processing Docker event: {event.event_type} for container {event.container_name} on host {event.host_id}")

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
                logger.debug(f"No rules match Docker event {event.event_type} for {event.container_name}")
                return False

            # Send notifications for matching rules
            success_count = 0
            for rule in matching_rules:
                # Check cooldown
                container_key = f"{event.host_id}:{event.container_id}"
                cooldown_key = f"event:{rule.id}:{container_key}:{event.event_type}"

                # Check cooldown
                if cooldown_key in self._last_alerts:
                    time_since = datetime.now() - self._last_alerts[cooldown_key]
                    if time_since.total_seconds() < rule.cooldown_minutes * 60:
                        logger.debug(f"Skipping alert for {event.container_name} due to cooldown")
                        continue

                # Send notification
                if await self._send_event_notification(rule, event):
                    success_count += 1
                    self._last_alerts[cooldown_key] = datetime.now()

                    # Update rule's last triggered time
                    self.db.update_alert_rule(rule.id, {
                        'last_triggered': datetime.now()
                    })

            return success_count > 0

        except Exception as e:
            logger.error(f"Error processing Docker event for {event.container_name}: {e}")
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
                        logger.info(f"Event notification sent via {channel.type} for {event.container_name}")
                    except Exception as e:
                        logger.error(f"Failed to send {channel.type} notification: {e}")

            logger.info(f"Event alert sent to {success_count}/{total_channels} channels for {event.container_name}")
            return success_count > 0

        except Exception as e:
            logger.error(f"Error sending event notification: {e}")
            return False

    async def send_alert(self, event: AlertEvent) -> bool:
        """Process an alert event and send notifications"""
        try:
            # Get matching alert rules
            alert_rules = await self._get_matching_rules(event)

            logger.info(f"Found {len(alert_rules) if alert_rules else 0} matching alert rules for {event.container_name}")

            if not alert_rules:
                logger.warning(f"No alert rules match container {event.container_name} (state: {event.old_state} → {event.new_state})")
                return False

            success_count = 0
            total_rules = len(alert_rules)

            # Process each matching rule
            for rule in alert_rules:
                if await self._should_send_alert(rule, event):
                    if await self._send_rule_notifications(rule, event):
                        success_count += 1
                        # Update last triggered time for this container + rule combination
                        container_key = f"{event.host_id}:{event.container_id}"
                        cooldown_key = f"{rule.id}:{container_key}"
                        self._last_alerts[cooldown_key] = datetime.now()

                        # Also update the rule's global last_triggered for backward compatibility
                        self.db.update_alert_rule(rule.id, {
                            'last_triggered': datetime.now()
                        })

            # Log the event
            self.db.add_container_event({
                'host_id': event.host_id,
                'container_id': event.container_id,
                'container_name': event.container_name,
                'event_type': 'alert_triggered',
                'old_state': event.old_state,
                'new_state': event.new_state,
                'triggered_by': event.triggered_by,
                'details': {'rules_triggered': success_count, 'total_rules': total_rules}
            })

            return success_count > 0

        except Exception as e:
            logger.error(f"Error processing alert for {event.container_name}: {e}")
            return False

    async def _get_matching_rules(self, event: AlertEvent) -> List[AlertRuleDB]:
        """Get alert rules that match the container and state change"""
        rules = self.db.get_alert_rules(enabled_only=True)
        matching_rules = []

        logger.info(f"Checking {len(rules)} alert rules for container {event.container_name} on host {event.host_id} (state: {event.old_state} → {event.new_state})")

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
                logger.debug(f"Rule {rule.id} skipped: no containers defined")
                continue

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
        logger.debug(f"Alert check for {event.container_name}: {event.old_state} → {event.new_state}")

        # If container was in a "good" state (running) and now in "bad" state (exited),
        # this is a new incident - reset cooldown
        good_states = ['running', 'created']
        if rule.trigger_states and event.old_state in good_states and event.new_state in rule.trigger_states:
            logger.info(f"Alert allowed for {event.container_name}: Container recovered ({event.old_state}) then failed ({event.new_state}) - new incident detected")
            # Remove the cooldown for this container
            if cooldown_key in self._last_alerts:
                del self._last_alerts[cooldown_key]
            return True

        if cooldown_key not in self._last_alerts:
            logger.debug(f"Alert allowed: No previous alert for this container")
            return True

        # Check cooldown period
        time_since_last = datetime.now() - self._last_alerts[cooldown_key]
        cooldown_minutes = rule.cooldown_minutes or 15
        cooldown_seconds = cooldown_minutes * 60

        if time_since_last.total_seconds() >= cooldown_seconds:
            logger.debug(f"Alert allowed: Cooldown period exceeded ({time_since_last.total_seconds():.1f}s > {cooldown_seconds}s)")
            return True
        else:
            logger.info(f"Alert blocked for {event.container_name}: Still in cooldown ({cooldown_seconds - time_since_last.total_seconds():.1f}s remaining)")
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

        logger.info(f"Alert sent to {success_count}/{total_channels} channels for {event.container_name}")
        return success_count > 0

    async def _send_to_channel(self, channel: NotificationChannel,
                             event: AlertEvent, rule: AlertRuleDB) -> bool:
        """Send notification to a specific channel"""
        message = self._format_message(event, rule)

        if channel.type == "telegram":
            return await self._send_telegram(channel.config, message)
        elif channel.type == "discord":
            return await self._send_discord(channel.config, message)
        elif channel.type == "pushover":
            return await self._send_pushover(channel.config, message, event)
        else:
            logger.warning(f"Unknown notification channel type: {channel.type}")
            return False

    def _format_message(self, event: AlertEvent, rule: AlertRuleDB) -> str:
        """Format alert message"""
        message = f"""🚨 **DockMon Alert**

**Container:** `{event.container_name}`
**Host:** {event.host_name}
**State Change:** `{event.old_state}` → `{event.new_state}`
**Image:** {event.image}
**Time:** {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
**Rule:** {rule.name}"""

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
                timestamp=datetime.now(),
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

    async def close(self):
        """Clean up resources"""
        await self.http_client.aclose()

class AlertProcessor:
    """Processes container state changes and triggers alerts"""

    def __init__(self, notification_service: NotificationService):
        self.notification_service = notification_service
        self._container_states: Dict[str, str] = {}  # Track previous states

    async def process_container_update(self, containers: List[Any], hosts: Dict[str, Any]):
        """Process container updates and trigger alerts for state changes"""
        for container in containers:
            container_key = f"{container.host_id}:{container.id}"
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
                container_id=container.id,
                container_name=container.name,
                host_id=container.host_id,
                host_name=host_name,
                old_state=previous_state,
                new_state=current_state,
                timestamp=datetime.now(),
                image=container.image,
                triggered_by='monitor'
            )

            # Send alert
            logger.debug(f"Processing state change for {container.name}: {previous_state} → {current_state}")
            await self.notification_service.send_alert(alert_event)

    def get_container_states(self) -> Dict[str, str]:
        """Get current container states for debugging"""
        return self._container_states.copy()