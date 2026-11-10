"""
Rate Limiting System for DockMon
Provides protection against abuse and DoS attacks using token bucket algorithm
"""

import logging
import math
import os
import time
from threading import Lock
from typing import NamedTuple, Optional

from fastapi import Request, HTTPException, status, Depends

from .audit import security_audit
from utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)


def _get_int_env(key: str, default: int) -> int:
    """
    Safely parse integer from environment variable with validation.

    Args:
        key: Environment variable name
        default: Default value if not set or invalid

    Returns:
        Parsed integer value or default
    """
    try:
        value = os.getenv(key)
        if value is not None:
            parsed = int(value)
            if parsed < 0:
                logger.warning(f"Invalid negative value for {key}={value}, using default {default}")
                return default
            return parsed
    except ValueError:
        logger.warning(f"Invalid integer for {key}={os.getenv(key)}, using default {default}")
    return default


VIOLATION_WINDOW_SECONDS = 60
BAN_SECONDS = 60


class RateDecision(NamedTuple):
    allowed: bool
    reason: str
    retry_after: int = 0


class RateLimiter:
    """
    In-memory rate limiter using token bucket algorithm
    Provides protection against abuse and DoS attacks
    """
    def __init__(self):
        self._lock = Lock()
        # One bucket per (client_ip, endpoint_type): each type's burst only caps its own traffic.
        self.clients: dict[tuple[str, str], dict] = {}
        self._last_cleanup = time.time()  # Track last cleanup time

        # Get rate limits from environment or use production-friendly defaults
        self.limits = {
            # endpoint_pattern: (requests_per_minute, burst_limit, violation_threshold)
            "default": (
                _get_int_env('DOCKMON_RATE_LIMIT_DEFAULT', 120),
                _get_int_env('DOCKMON_RATE_BURST_DEFAULT', 20),
                _get_int_env('DOCKMON_RATE_VIOLATIONS_DEFAULT', 8)
            ),
            "auth": (
                _get_int_env('DOCKMON_RATE_LIMIT_AUTH', 10),  # 10 per minute for auth
                _get_int_env('DOCKMON_RATE_BURST_AUTH', 5),   # Lower burst
                _get_int_env('DOCKMON_RATE_VIOLATIONS_AUTH', 10)  # More lenient violations
            ),
            "hosts": (
                _get_int_env('DOCKMON_RATE_LIMIT_HOSTS', 60),
                _get_int_env('DOCKMON_RATE_BURST_HOSTS', 15),
                _get_int_env('DOCKMON_RATE_VIOLATIONS_HOSTS', 8)
            ),
            "containers": (
                _get_int_env('DOCKMON_RATE_LIMIT_CONTAINERS', 900),  # Increased for logs polling with multiple containers
                _get_int_env('DOCKMON_RATE_BURST_CONTAINERS', 180),
                _get_int_env('DOCKMON_RATE_VIOLATIONS_CONTAINERS', 25)
            ),
            "notifications": (
                _get_int_env('DOCKMON_RATE_LIMIT_NOTIFICATIONS', 30),
                _get_int_env('DOCKMON_RATE_BURST_NOTIFICATIONS', 10),
                _get_int_env('DOCKMON_RATE_VIOLATIONS_NOTIFICATIONS', 5)
            ),
            "alerts": (
                _get_int_env('DOCKMON_RATE_LIMIT_ALERTS', 100),  # Read operations
                _get_int_env('DOCKMON_RATE_BURST_ALERTS', 20),
                _get_int_env('DOCKMON_RATE_VIOLATIONS_ALERTS', 8)
            ),
            "alerts_write": (
                _get_int_env('DOCKMON_RATE_LIMIT_ALERTS_WRITE', 200),  # Write operations (resolve/snooze) - increased for bulk operations
                _get_int_env('DOCKMON_RATE_BURST_ALERTS_WRITE', 100),
                _get_int_env('DOCKMON_RATE_VIOLATIONS_ALERTS_WRITE', 5)
            ),
            "backup": (
                _get_int_env('DOCKMON_RATE_LIMIT_BACKUP', 10),
                _get_int_env('DOCKMON_RATE_BURST_BACKUP', 5),
                _get_int_env('DOCKMON_RATE_VIOLATIONS_BACKUP', 5)
            ),
            "stacks": (
                _get_int_env('DOCKMON_RATE_LIMIT_STACKS', 60),  # Stack CRUD operations
                _get_int_env('DOCKMON_RATE_BURST_STACKS', 15),
                _get_int_env('DOCKMON_RATE_VIOLATIONS_STACKS', 8)
            ),
        }

        logger.info(f"Rate limiting configured: Default={self.limits['default'][0]}/min, "
                   f"Auth={self.limits['auth'][0]}/min, Containers={self.limits['containers'][0]}/min")
        self.banned_clients = {}  # IP -> ban_until_timestamp

    def _get_limit(self, endpoint_type: str) -> tuple:
        return self.limits.get(endpoint_type, self.limits["default"])

    def _cleanup_old_entries(self):
        """Clean up old entries to prevent memory leaks. Must be called with self._lock held."""
        current_time = time.time()
        # Remove clients not seen for 1 hour
        cutoff_time = current_time - 3600

        old_buckets = [key for key, data in self.clients.items()
                       if data["last_update"] < cutoff_time]
        for key in old_buckets:
            del self.clients[key]

        # Remove expired bans
        expired_bans = [ip for ip, ban_time in self.banned_clients.items()
                       if current_time > ban_time]
        for ip in expired_bans:
            del self.banned_clients[ip]

    def is_allowed(self, client_ip: str, endpoint_type: str, endpoint_name: Optional[str] = None) -> RateDecision:
        """Spend one token from the (client_ip, endpoint_type) bucket; endpoint_name is for logs only."""
        endpoint_name = endpoint_name or endpoint_type
        with self._lock:
            current_time = time.time()

            if current_time - self._last_cleanup >= 300:
                self._cleanup_old_entries()
                self._last_cleanup = current_time

            ban_until = self.banned_clients.get(client_ip)
            if ban_until is not None:
                if current_time < ban_until:
                    return RateDecision(False, "IP banned for repeated violations",
                                        max(1, math.ceil(ban_until - current_time)))
                del self.banned_clients[client_ip]

            requests_per_minute, burst_limit, violation_threshold = self._get_limit(endpoint_type)
            bucket = self.clients.get((client_ip, endpoint_type))
            if bucket is None:
                bucket = {"tokens": float(burst_limit), "last_update": current_time,
                          "violations": 0, "violation_window_start": current_time}
                self.clients[(client_ip, endpoint_type)] = bucket

            time_passed = current_time - bucket["last_update"]
            tokens_to_add = (time_passed / 60.0) * requests_per_minute
            bucket["tokens"] = min(burst_limit, bucket["tokens"] + tokens_to_add)
            bucket["last_update"] = current_time

            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
                return RateDecision(True, "OK")

            if current_time - bucket["violation_window_start"] > VIOLATION_WINDOW_SECONDS:
                bucket["violations"] = 0
                bucket["violation_window_start"] = current_time
            bucket["violations"] += 1

            if bucket["violations"] >= violation_threshold:
                self.banned_clients[client_ip] = current_time + BAN_SECONDS
                logger.warning(f"IP {client_ip} banned for {BAN_SECONDS} seconds due to "
                               f"{violation_threshold} rate limit violations")
                security_audit.log_rate_limit_violation(
                    client_ip=client_ip,
                    endpoint=endpoint_name,
                    violations=bucket["violations"],
                    banned=True
                )
                return RateDecision(False, "IP banned for repeated violations", BAN_SECONDS)

            security_audit.log_rate_limit_violation(
                client_ip=client_ip,
                endpoint=endpoint_name,
                violations=bucket["violations"],
                banned=False
            )

            if requests_per_minute <= 0:
                retry_after = 60
            else:
                retry_after = max(1, math.ceil((1.0 - bucket["tokens"]) * 60.0 / requests_per_minute))
            return RateDecision(False, f"Rate limit exceeded. Try again in {retry_after} seconds", retry_after)

    def get_stats(self) -> dict:
        """Get rate limiter statistics"""
        with self._lock:
            return {
                "active_clients": len(self.clients),
                "banned_clients": len(self.banned_clients),
                "total_violations": sum(data["violations"] for data in self.clients.values())
            }


# Global rate limiter instance
rate_limiter = RateLimiter()


def get_rate_limit_dependency(endpoint_type: str = "default"):
    """Create a dependency for rate limiting specific endpoint types"""
    def rate_limit_check(request: Request):
        client_ip = get_client_ip(request)
        endpoint_name = f"{endpoint_type}_{request.url.path}"

        decision = rate_limiter.is_allowed(client_ip, endpoint_type, endpoint_name)

        if not decision.allowed:
            logger.warning(f"Rate limit exceeded for {client_ip} on {endpoint_name}: {decision.reason}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {decision.reason}",
                headers={"Retry-After": str(decision.retry_after)}
            )
        return True
    return rate_limit_check


# Rate limiting dependencies for different endpoint types
rate_limit_auth = Depends(get_rate_limit_dependency("auth"))
rate_limit_hosts = Depends(get_rate_limit_dependency("hosts"))
rate_limit_containers = Depends(get_rate_limit_dependency("containers"))
rate_limit_notifications = Depends(get_rate_limit_dependency("notifications"))
rate_limit_stacks = Depends(get_rate_limit_dependency("stacks"))
rate_limit_default = Depends(get_rate_limit_dependency("default"))