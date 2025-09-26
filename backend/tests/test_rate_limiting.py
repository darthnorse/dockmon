"""
Tests for rate limiting functionality
Ensures proper request throttling and ban logic
"""

import pytest
from unittest.mock import MagicMock, patch
import time
from datetime import datetime, timedelta


class TestRateLimiting:
    """Test rate limiting implementation"""

    def test_basic_rate_limiting(self):
        """Test basic rate limit enforcement"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()
        client_ip = "192.168.1.100"
        endpoint = "/api/test"

        # Configure limit: 5 requests per minute
        limiter.configure(endpoint, requests_per_minute=5)

        # First 5 requests should pass
        for i in range(5):
            allowed, violations = limiter.check_rate_limit(client_ip, endpoint)
            assert allowed is True
            assert violations == 0

        # 6th request should be blocked
        allowed, violations = limiter.check_rate_limit(client_ip, endpoint)
        assert allowed is False
        assert violations == 1

    def test_burst_allowance(self):
        """Test burst request allowance"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()
        client_ip = "192.168.1.100"
        endpoint = "/api/test"

        # Configure with burst allowance
        limiter.configure(endpoint, requests_per_minute=60, burst_size=10)

        # Should allow burst of 10 requests immediately
        for i in range(10):
            allowed, _ = limiter.check_rate_limit(client_ip, endpoint)
            assert allowed is True

        # 11th immediate request should be blocked
        allowed, _ = limiter.check_rate_limit(client_ip, endpoint)
        assert allowed is False

    def test_rate_limit_reset(self):
        """Test rate limit reset after time window"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()
        client_ip = "192.168.1.100"
        endpoint = "/api/test"

        limiter.configure(endpoint, requests_per_minute=5)

        # Exhaust limit
        for i in range(6):
            limiter.check_rate_limit(client_ip, endpoint)

        # Should be blocked
        allowed, _ = limiter.check_rate_limit(client_ip, endpoint)
        assert allowed is False

        # Simulate time passing (reset window)
        with patch('time.time', return_value=time.time() + 61):
            allowed, _ = limiter.check_rate_limit(client_ip, endpoint)
            assert allowed is True  # Should be allowed after reset

    def test_violation_threshold_ban(self):
        """Test automatic ban after violation threshold"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()
        client_ip = "192.168.1.100"
        endpoint = "/api/auth/login"

        limiter.configure(
            endpoint,
            requests_per_minute=5,
            violation_threshold=3,
            ban_duration_minutes=30
        )

        # Exhaust normal limit
        for i in range(5):
            limiter.check_rate_limit(client_ip, endpoint)

        # Accumulate violations
        for i in range(3):
            allowed, violations = limiter.check_rate_limit(client_ip, endpoint)
            assert allowed is False

        # Should be banned after 3 violations
        is_banned = limiter.is_banned(client_ip)
        assert is_banned is True

        # Should remain banned even for other endpoints
        allowed, _ = limiter.check_rate_limit(client_ip, "/api/other")
        assert allowed is False

    def test_ban_expiration(self):
        """Test ban expiration after duration"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()
        client_ip = "192.168.1.100"

        # Ban the IP
        limiter.ban_ip(client_ip, duration_minutes=1)
        assert limiter.is_banned(client_ip) is True

        # Simulate time passing
        with patch('datetime.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value = datetime.utcnow() + timedelta(minutes=2)
            assert limiter.is_banned(client_ip) is False

    def test_whitelist_bypass(self):
        """Test whitelisted IPs bypass rate limiting"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()
        limiter.add_to_whitelist("127.0.0.1")
        limiter.add_to_whitelist("10.0.0.0/8")  # Subnet

        # Whitelisted IPs should never be limited
        for i in range(100):
            allowed, _ = limiter.check_rate_limit("127.0.0.1", "/api/test")
            assert allowed is True

        # Subnet whitelist
        allowed, _ = limiter.check_rate_limit("10.0.0.50", "/api/test")
        assert allowed is True

    def test_endpoint_specific_limits(self):
        """Test different limits for different endpoints"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()
        client_ip = "192.168.1.100"

        # Configure different limits
        limiter.configure("/api/auth/login", requests_per_minute=5)
        limiter.configure("/api/containers", requests_per_minute=60)
        limiter.configure("/api/hosts", requests_per_minute=30)

        # Test auth endpoint (strict limit)
        for i in range(5):
            allowed, _ = limiter.check_rate_limit(client_ip, "/api/auth/login")
            assert allowed is True

        allowed, _ = limiter.check_rate_limit(client_ip, "/api/auth/login")
        assert allowed is False  # Should be blocked

        # Container endpoint should still work (higher limit)
        for i in range(30):
            allowed, _ = limiter.check_rate_limit(client_ip, "/api/containers")
            assert allowed is True

    def test_cleanup_old_entries(self):
        """Test cleanup of old rate limit entries"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()

        # Add many entries
        for i in range(1000):
            ip = f"192.168.1.{i % 256}"
            limiter.check_rate_limit(ip, "/api/test")

        initial_size = len(limiter.request_history)

        # Simulate time passing
        with patch('time.time', return_value=time.time() + 3600):
            limiter.cleanup_old_entries()

        # Old entries should be cleaned up
        assert len(limiter.request_history) < initial_size

    def test_rate_limit_statistics(self):
        """Test rate limit statistics collection"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()

        # Generate some activity
        limiter.check_rate_limit("192.168.1.100", "/api/test")
        limiter.check_rate_limit("192.168.1.101", "/api/test")
        limiter.ban_ip("192.168.1.102")

        stats = limiter.get_statistics()

        assert stats["total_requests"] > 0
        assert stats["unique_ips"] == 2
        assert stats["banned_ips"] == 1
        assert "requests_per_endpoint" in stats

    def test_distributed_rate_limiting(self):
        """Test rate limiting across distributed instances (Redis-based)"""
        from auth.rate_limiter import DistributedRateLimiter

        with patch('redis.Redis') as mock_redis:
            mock_redis_instance = MagicMock()
            mock_redis.return_value = mock_redis_instance

            limiter = DistributedRateLimiter(redis_client=mock_redis_instance)

            client_ip = "192.168.1.100"
            endpoint = "/api/test"

            # Should use Redis for state
            limiter.check_rate_limit(client_ip, endpoint)
            mock_redis_instance.incr.assert_called()
            mock_redis_instance.expire.assert_called()

    def test_rate_limit_headers(self):
        """Test rate limit headers in responses"""
        from auth.rate_limiter import add_rate_limit_headers

        response = MagicMock()
        response.headers = {}

        add_rate_limit_headers(
            response,
            limit=100,
            remaining=50,
            reset_time=int(time.time() + 60)
        )

        assert response.headers["X-RateLimit-Limit"] == "100"
        assert response.headers["X-RateLimit-Remaining"] == "50"
        assert "X-RateLimit-Reset" in response.headers

    def test_rate_limit_middleware(self):
        """Test rate limiting middleware integration"""
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from auth.rate_limiter import RateLimitMiddleware

        app = FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/api/test")
        def test_endpoint():
            return {"status": "ok"}

        client = TestClient(app)

        # Should allow normal requests
        response = client.get("/api/test")
        assert response.status_code == 200

        # Exhaust rate limit
        for i in range(100):
            client.get("/api/test")

        # Should eventually be rate limited
        response = client.get("/api/test")
        assert response.status_code == 429  # Too Many Requests

    def test_custom_rate_limit_key(self):
        """Test custom rate limit key generation (e.g., by API key instead of IP)"""
        from auth.rate_limiter import RateLimiter

        limiter = RateLimiter()

        # Rate limit by API key
        api_key = "api_key_12345"
        endpoint = "/api/data"

        limiter.configure(endpoint, requests_per_minute=100)

        # Use API key as identifier
        for i in range(100):
            allowed, _ = limiter.check_rate_limit(
                identifier=api_key,
                endpoint=endpoint,
                key_type="api_key"
            )
            assert allowed is True

        # 101st request should be blocked
        allowed, _ = limiter.check_rate_limit(
            identifier=api_key,
            endpoint=endpoint,
            key_type="api_key"
        )
        assert allowed is False