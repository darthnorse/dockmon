"""
WebSocket Rate Limiting for DockMon
Provides generous rate limiting to prevent DoS while supporting large deployments
"""

import time
from collections import defaultdict, deque
from typing import Dict, Deque, Tuple
import logging

logger = logging.getLogger(__name__)


class WebSocketRateLimiter:
    """
    Rate limiter for WebSocket connections.
    Designed to be generous for legitimate use while preventing abuse.

    Supports monitoring hundreds of containers without issues.
    """

    def __init__(self):
        # Track message timestamps per connection
        # Format: {connection_id: deque of timestamps}
        self.message_history: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=1000))

        # Rate limits (generous for large deployments)
        self.limits = {
            # Allow 100 messages per second (very generous for real-time monitoring)
            "messages_per_second": 100,
            # Allow 1000 messages per minute (for burst activity)
            "messages_per_minute": 1000,
            # Allow 10000 messages per hour (for sustained monitoring)
            "messages_per_hour": 10000
        }

        # Track violations for logging
        self.violations: Dict[str, int] = defaultdict(int)

    def check_rate_limit(self, connection_id: str) -> Tuple[bool, str]:
        """
        Check if a connection has exceeded rate limits.

        Returns:
            (allowed, reason) - allowed is True if within limits,
                                reason explains why if rejected
        """
        current_time = time.time()
        history = self.message_history[connection_id]

        # Add current request
        history.append(current_time)

        # Count messages in different time windows
        messages_last_second = sum(1 for t in history if current_time - t <= 1)
        messages_last_minute = sum(1 for t in history if current_time - t <= 60)
        messages_last_hour = sum(1 for t in history if current_time - t <= 3600)

        # Check per-second limit (prevent bursts)
        if messages_last_second > self.limits["messages_per_second"]:
            self.violations[connection_id] += 1
            logger.warning(f"WebSocket rate limit exceeded for {connection_id}: "
                         f"{messages_last_second} msgs/sec (limit: {self.limits['messages_per_second']})")
            return False, f"Rate limit exceeded: {messages_last_second} messages per second"

        # Check per-minute limit
        if messages_last_minute > self.limits["messages_per_minute"]:
            self.violations[connection_id] += 1
            logger.warning(f"WebSocket rate limit exceeded for {connection_id}: "
                         f"{messages_last_minute} msgs/min (limit: {self.limits['messages_per_minute']})")
            return False, f"Rate limit exceeded: {messages_last_minute} messages per minute"

        # Check per-hour limit
        if messages_last_hour > self.limits["messages_per_hour"]:
            self.violations[connection_id] += 1
            logger.warning(f"WebSocket rate limit exceeded for {connection_id}: "
                         f"{messages_last_hour} msgs/hour (limit: {self.limits['messages_per_hour']})")
            return False, f"Rate limit exceeded: {messages_last_hour} messages per hour"

        # Reset violations on successful request
        if connection_id in self.violations:
            del self.violations[connection_id]

        return True, "OK"

    def cleanup_connection(self, connection_id: str):
        """Clean up tracking data when a connection closes"""
        if connection_id in self.message_history:
            del self.message_history[connection_id]
        if connection_id in self.violations:
            del self.violations[connection_id]

    def get_connection_stats(self, connection_id: str) -> dict:
        """Get current rate limiting stats for a connection"""
        current_time = time.time()
        history = self.message_history.get(connection_id, deque())

        return {
            "messages_last_second": sum(1 for t in history if current_time - t <= 1),
            "messages_last_minute": sum(1 for t in history if current_time - t <= 60),
            "messages_last_hour": sum(1 for t in history if current_time - t <= 3600),
            "violations": self.violations.get(connection_id, 0),
            "limits": self.limits
        }


# Global rate limiter instance
ws_rate_limiter = WebSocketRateLimiter()