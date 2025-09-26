"""
Rate Limiting System for DockMon
Provides protection against abuse and DoS attacks using token bucket algorithm
"""

import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, Tuple

from fastapi import Request, HTTPException, status, Depends

from .audit import security_audit

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    In-memory rate limiter using token bucket algorithm
    Provides protection against abuse and DoS attacks
    """
    def __init__(self):
        # Start with some initial tokens to avoid immediate rate limiting
        self.clients = defaultdict(lambda: {"tokens": 10, "last_update": time.time(), "violations": 0})

        # Get rate limits from environment or use production-friendly defaults
        self.limits = {
            # endpoint_pattern: (requests_per_minute, burst_limit, violation_threshold)
            "default": (
                int(os.getenv('DOCKMON_RATE_LIMIT_DEFAULT', 120)),
                int(os.getenv('DOCKMON_RATE_BURST_DEFAULT', 20)),
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_DEFAULT', 8))
            ),
            "auth": (
                int(os.getenv('DOCKMON_RATE_LIMIT_AUTH', 10)),  # 10 per minute for auth
                int(os.getenv('DOCKMON_RATE_BURST_AUTH', 5)),   # Lower burst
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_AUTH', 10))  # More lenient violations
            ),
            "hosts": (
                int(os.getenv('DOCKMON_RATE_LIMIT_HOSTS', 60)),
                int(os.getenv('DOCKMON_RATE_BURST_HOSTS', 15)),
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_HOSTS', 8))
            ),
            "containers": (
                int(os.getenv('DOCKMON_RATE_LIMIT_CONTAINERS', 200)),
                int(os.getenv('DOCKMON_RATE_BURST_CONTAINERS', 40)),
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_CONTAINERS', 15))
            ),
            "notifications": (
                int(os.getenv('DOCKMON_RATE_LIMIT_NOTIFICATIONS', 30)),
                int(os.getenv('DOCKMON_RATE_BURST_NOTIFICATIONS', 10)),
                int(os.getenv('DOCKMON_RATE_VIOLATIONS_NOTIFICATIONS', 5))
            ),
        }

        logger.info(f"Rate limiting configured: Default={self.limits['default'][0]}/min, "
                   f"Auth={self.limits['auth'][0]}/min, Containers={self.limits['containers'][0]}/min")
        self.banned_clients = {}  # IP -> ban_until_timestamp

    def _get_limit(self, endpoint: str) -> tuple:
        """Get rate limit for specific endpoint"""
        for pattern, limits in self.limits.items():
            if pattern in endpoint.lower():
                return limits
        return self.limits["default"]

    def _cleanup_old_entries(self):
        """Clean up old entries to prevent memory leaks"""
        current_time = time.time()
        # Remove clients not seen for 1 hour
        cutoff_time = current_time - 3600

        old_clients = [ip for ip, data in self.clients.items()
                      if data["last_update"] < cutoff_time]
        for ip in old_clients:
            del self.clients[ip]

        # Remove expired bans
        expired_bans = [ip for ip, ban_time in self.banned_clients.items()
                       if current_time > ban_time]
        for ip in expired_bans:
            del self.banned_clients[ip]

    def is_allowed(self, client_ip: str, endpoint: str) -> Tuple[bool, str]:
        """Check if request is allowed and return (allowed, reason)"""
        current_time = time.time()

        # Cleanup old entries periodically
        if current_time % 300 < 1:  # Every 5 minutes
            self._cleanup_old_entries()

        # Check if client is banned
        if client_ip in self.banned_clients:
            if current_time < self.banned_clients[client_ip]:
                return False, f"IP banned until {datetime.fromtimestamp(self.banned_clients[client_ip]).isoformat()}"
            else:
                # Ban expired, remove from banned list
                del self.banned_clients[client_ip]

        requests_per_minute, burst_limit, violation_threshold = self._get_limit(endpoint)
        client_data = self.clients[client_ip]

        # Token bucket algorithm with burst support
        time_passed = current_time - client_data["last_update"]
        tokens_to_add = (time_passed / 60.0) * requests_per_minute
        # Allow bursting up to burst_limit tokens
        client_data["tokens"] = min(burst_limit, client_data["tokens"] + tokens_to_add)
        client_data["last_update"] = current_time

        # Check if request is allowed
        if client_data["tokens"] >= 1.0:
            client_data["tokens"] -= 1.0
            return True, "OK"
        else:
            # Rate limit exceeded
            client_data["violations"] += 1

            # Check if violations exceed threshold - ban the client
            if client_data["violations"] >= violation_threshold:
                ban_duration = 900  # 15 minutes ban
                self.banned_clients[client_ip] = current_time + ban_duration
                logger.warning(f"IP {client_ip} banned for 15 minutes due to {violation_threshold} rate limit violations")

                # Security audit log
                security_audit.log_rate_limit_violation(
                    client_ip=client_ip,
                    endpoint=endpoint,
                    violations=client_data["violations"],
                    banned=True
                )

                return False, f"IP banned for repeated violations"

            # Log rate limit violation
            security_audit.log_rate_limit_violation(
                client_ip=client_ip,
                endpoint=endpoint,
                violations=client_data["violations"],
                banned=False
            )

            return False, f"Rate limit exceeded. Try again in {int(60 - time_passed)} seconds"

    def get_stats(self) -> dict:
        """Get rate limiter statistics"""
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
        client_ip = request.client.host
        endpoint_name = f"{endpoint_type}_{request.url.path}"

        allowed, reason = rate_limiter.is_allowed(client_ip, endpoint_name)

        if not allowed:
            logger.warning(f"Rate limit exceeded for {client_ip} on {endpoint_name}: {reason}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {reason}",
                headers={"Retry-After": "60"}
            )
        return True
    return rate_limit_check


# Rate limiting dependencies for different endpoint types
rate_limit_auth = Depends(get_rate_limit_dependency("auth"))
rate_limit_hosts = Depends(get_rate_limit_dependency("hosts"))
rate_limit_containers = Depends(get_rate_limit_dependency("containers"))
rate_limit_notifications = Depends(get_rate_limit_dependency("notifications"))
rate_limit_default = Depends(get_rate_limit_dependency("default"))