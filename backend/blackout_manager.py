"""
Blackout Window Management for DockMon
Handles alert suppression during maintenance windows
"""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from database import DatabaseManager
from utils.async_docker import async_docker_call

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

    async def start_monitoring(self, notification_service, monitor, connection_manager=None):
        """Start monitoring for blackout window transitions

        Args:
            notification_service: The notification service instance
            monitor: The DockerMonitor instance (reused, not created)
            connection_manager: Optional WebSocket connection manager
        """
        self._connection_manager = connection_manager

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

                        # Alert processing is now handled by evaluation_service._check_blackout_transitions()
                        if was_in_blackout and not is_blackout:
                            logger.info(f"Blackout window ended - alert processing handled by evaluation service")

                    was_in_blackout = is_blackout

                    # Check every 15 seconds for more responsive updates
                    await asyncio.sleep(15)

                except Exception as e:
                    logger.error(f"Error in blackout monitoring: {e}")
                    await asyncio.sleep(15)

        self._check_task = asyncio.create_task(monitor_loop())

    async def stop_monitoring(self):
        """Stop the monitoring task"""
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None