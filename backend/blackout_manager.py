"""
Blackout Window Management for DockMon
Handles alert suppression during maintenance windows
"""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from database import DatabaseManager

logger = logging.getLogger(__name__)


class BlackoutManager:
    """Manages blackout windows and deferred alerts"""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._check_task: Optional[asyncio.Task] = None
        self._last_check: Optional[datetime] = None
        self._connection_manager = None  # Will be set when monitoring starts

    def is_in_blackout_window(self) -> Tuple[bool, Optional[str]]:
        """
        Check if current time is within any blackout window
        Returns: (is_blackout, window_name)
        """
        try:
            settings = self.db.get_settings()
            if not settings or not settings.blackout_windows:
                return False, None

            # Get timezone offset from settings (in minutes), default to 0 (UTC)
            timezone_offset = getattr(settings, 'timezone_offset', 0)

            # Get current time in UTC and convert to user's timezone
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc + timedelta(minutes=timezone_offset)
            current_time = now_local.time()
            current_weekday = now_local.weekday()  # 0=Monday, 6=Sunday

            for window in settings.blackout_windows:
                if not window.get('enabled', True):
                    continue

                days = window.get('days', [])
                start_str = window.get('start', '00:00')
                end_str = window.get('end', '00:00')

                start_time = datetime.strptime(start_str, '%H:%M').time()
                end_time = datetime.strptime(end_str, '%H:%M').time()

                # Handle overnight windows (e.g., 23:00 to 02:00)
                if start_time > end_time:
                    # For overnight windows, check if we're in the late night part (before midnight)
                    # or the early morning part (after midnight)
                    if current_time >= start_time:
                        # Late night part - check if today is in the window
                        if current_weekday in days:
                            window_name = window.get('name', f"{start_str}-{end_str}")
                            return True, window_name
                    elif current_time < end_time:
                        # Early morning part - check if YESTERDAY was in the window
                        prev_day = (current_weekday - 1) % 7
                        if prev_day in days:
                            window_name = window.get('name', f"{start_str}-{end_str}")
                            return True, window_name
                else:
                    # Regular same-day window
                    if current_weekday in days and start_time <= current_time < end_time:
                        window_name = window.get('name', f"{start_str}-{end_str}")
                        return True, window_name

            return False, None

        except Exception as e:
            logger.error(f"Error checking blackout window: {e}")
            return False, None

    def get_last_window_end_time(self) -> Optional[datetime]:
        """Get when the last blackout window ended (for tracking)"""
        return getattr(self, '_last_window_end', None)

    def set_last_window_end_time(self, end_time: datetime):
        """Set when the last blackout window ended"""
        self._last_window_end = end_time

    async def check_container_states_after_blackout(self, notification_service, monitor) -> Dict:
        """
        Check all container states after blackout window ends.
        Alert if any containers are in problematic states.
        Returns summary of what was found.

        Args:
            notification_service: The notification service instance
            monitor: The DockerMonitor instance (reused, not created)
        """
        summary = {
            'containers_down': [],
            'total_checked': 0,
            'window_name': None
        }

        try:

            problematic_states = ['exited', 'dead', 'paused', 'removing']

            # Check all containers across all hosts
            for host_id, host in monitor.hosts.items():
                if not host.client:
                    continue

                try:
                    containers = host.client.containers.list(all=True)
                    summary['total_checked'] += len(containers)

                    for container in containers:
                        if container.status in problematic_states:
                            # Get exit code if container exited
                            exit_code = None
                            if container.status == 'exited':
                                try:
                                    exit_code = container.attrs.get('State', {}).get('ExitCode')
                                except (AttributeError, KeyError, TypeError) as e:
                                    logger.debug(f"Could not get exit code for container {container.id[:12]}: {e}")

                            summary['containers_down'].append({
                                'id': container.id[:12],
                                'name': container.name,
                                'host_id': host_id,
                                'host_name': host.name,
                                'state': container.status,
                                'exit_code': exit_code,
                                'image': container.image.tags[0] if container.image.tags else 'unknown'
                            })

                except Exception as e:
                    logger.error(f"Error checking containers on host {host.name}: {e}")

            # Send alert if any containers are down
            if summary['containers_down'] and notification_service:
                await self._send_post_blackout_alert(notification_service, summary)

        except Exception as e:
            logger.error(f"Error checking container states after blackout: {e}")

        return summary

    async def _send_post_blackout_alert(self, notification_service, summary: Dict):
        """Send alert for containers found in problematic state after blackout"""
        try:
            containers_down = summary['containers_down']

            # Get all alert rules that monitor state changes
            alert_rules = self.db.get_alert_rules()

            # For each container that's down, check if it matches any alert rules
            for container_info in containers_down:
                # Find matching alert rules for this container
                matching_rules = []
                for rule in alert_rules:
                    if not rule.enabled:
                        continue

                    # Check if this rule monitors the problematic state
                    if rule.trigger_states and container_info['state'] in rule.trigger_states:
                        # Check if container matches rule's container pattern
                        if self._container_matches_rule(container_info, rule):
                            matching_rules.append(rule)

                # Send alert through matching rules
                if matching_rules:
                    from notifications import AlertEvent
                    event = AlertEvent(
                        container_id=container_info['id'],
                        container_name=container_info['name'],
                        host_id=container_info['host_id'],
                        host_name=container_info['host_name'],
                        old_state='unknown_during_blackout',
                        new_state=container_info['state'],
                        exit_code=container_info.get('exit_code'),
                        timestamp=datetime.now(),
                        image=container_info['image'],
                        triggered_by='post_blackout_check'
                    )

                    # Send through each matching rule's channels
                    for rule in matching_rules:
                        try:
                            # Add note about blackout in the event
                            event.notes = f"Container found in {container_info['state']} state after maintenance window ended"
                            await notification_service.send_alert(event, rule)
                        except Exception as e:
                            logger.error(f"Failed to send post-blackout alert for {container_info['name']}: {e}")

        except Exception as e:
            logger.error(f"Error sending post-blackout alerts: {e}")

    def _container_matches_rule(self, container_info: Dict, rule) -> bool:
        """Check if container matches an alert rule's container criteria"""
        try:
            # If rule has specific container+host pairs
            if hasattr(rule, 'containers') and rule.containers:
                for container_spec in rule.containers:
                    if (container_spec.container_name == container_info['name'] and
                        container_spec.host_id == container_info['host_id']):
                        return True
                return False

            # Otherwise, rule applies to all containers
            return True

        except Exception as e:
            logger.error(f"Error matching container to rule: {e}")
            return False

    async def start_monitoring(self, notification_service, monitor, connection_manager=None):
        """Start monitoring for blackout window transitions

        Args:
            notification_service: The notification service instance
            monitor: The DockerMonitor instance (reused, not created)
            connection_manager: Optional WebSocket connection manager
        """
        self._connection_manager = connection_manager
        self._monitor = monitor  # Store monitor reference

        async def monitor_loop():
            was_in_blackout = False

            while True:
                try:
                    is_blackout, window_name = self.is_in_blackout_window()

                    # Check if blackout status changed
                    if was_in_blackout != is_blackout:
                        # Broadcast status change to all WebSocket clients
                        if self._connection_manager:
                            await self._connection_manager.broadcast({
                                'type': 'blackout_status_changed',
                                'data': {
                                    'is_blackout': is_blackout,
                                    'window_name': window_name
                                }
                            })

                        # If we just exited blackout, process suppressed alerts
                        if was_in_blackout and not is_blackout:
                            logger.info(f"Blackout window ended. Processing suppressed alerts...")
                            await notification_service.process_suppressed_alerts(self._monitor)

                    was_in_blackout = is_blackout

                    # Check every 15 seconds for more responsive updates
                    await asyncio.sleep(15)

                except Exception as e:
                    logger.error(f"Error in blackout monitoring: {e}")
                    await asyncio.sleep(15)

        self._check_task = asyncio.create_task(monitor_loop())

    def stop_monitoring(self):
        """Stop the monitoring task"""
        if self._check_task:
            self._check_task.cancel()
            self._check_task = None