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
                # Support both 'start'/'end' (old format) and 'start_time'/'end_time' (new format)
                start_str = window.get('start_time') or window.get('start', '00:00')
                end_str = window.get('end_time') or window.get('end', '00:00')

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

            # Note: Post-blackout alerts are handled by V2 alert evaluation system
            # which continuously monitors container states

        except Exception as e:
            logger.error(f"Error checking container states after blackout: {e}")

        return summary


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