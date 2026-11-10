"""Rate limiter: limits looked up by endpoint type, per-type buckets, windowed violations."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from security.rate_limiting import RateLimiter, get_rate_limit_dependency

IP = "203.0.113.5"


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    c = Clock()
    with patch("security.rate_limiting.time.time", c):
        yield c


@pytest.fixture
def limiter(clock):
    return RateLimiter()


def _drain(limiter, endpoint_type, path, n):
    return [limiter.is_allowed(IP, endpoint_type, f"{endpoint_type}_{path}").allowed for _ in range(n)]


def test_alerts_write_uses_its_own_burst(limiter):
    results = _drain(limiter, "alerts_write", "/api/alerts/x/resolve", 101)
    assert all(results[:100])
    assert results[100] is False


def test_container_routes_under_hosts_use_container_limits(limiter):
    results = _drain(limiter, "containers", "/api/hosts/h/containers/c/restart", 180)
    assert all(results)


def test_read_traffic_does_not_drain_write_bucket(limiter):
    _drain(limiter, "alerts", "/api/alerts/", 25)
    assert limiter.is_allowed(IP, "alerts_write", "alerts_write_/api/alerts/x/resolve").allowed


def test_violations_outside_window_do_not_ban(limiter, clock):
    limiter.limits["alerts"] = (1, 1, 3)
    assert limiter.is_allowed(IP, "alerts").allowed
    assert not limiter.is_allowed(IP, "alerts").allowed
    assert not limiter.is_allowed(IP, "alerts").allowed

    clock.now += 61
    assert limiter.is_allowed(IP, "alerts").allowed
    assert not limiter.is_allowed(IP, "alerts").allowed
    decision = limiter.is_allowed(IP, "alerts")

    assert not decision.allowed
    assert IP not in limiter.banned_clients


def test_violations_inside_window_still_ban(limiter):
    limiter.limits["alerts"] = (1, 1, 3)
    _drain(limiter, "alerts", "/api/alerts/", 4)
    assert IP in limiter.banned_clients


def test_retry_after_is_time_to_next_token(limiter):
    limiter.limits["alerts"] = (6, 1, 100)
    limiter.is_allowed(IP, "alerts")
    decision = limiter.is_allowed(IP, "alerts")
    assert not decision.allowed
    assert decision.retry_after == 10


def test_zero_rate_does_not_divide_by_zero(limiter):
    limiter.limits["alerts"] = (0, 1, 100)
    limiter.is_allowed(IP, "alerts")
    decision = limiter.is_allowed(IP, "alerts")
    assert not decision.allowed
    assert decision.retry_after == 60


def test_banned_client_gets_remaining_ban_time(limiter, clock):
    limiter.banned_clients[IP] = clock.now + 42
    decision = limiter.is_allowed(IP, "alerts")
    assert not decision.allowed
    assert decision.retry_after == 42


def test_unknown_type_falls_back_to_default(limiter):
    assert limiter._get_limit("no_such_type") == limiter.limits["default"]


def test_dependency_sets_computed_retry_after_header(limiter):
    limiter.limits["alerts"] = (6, 1, 100)
    request = Request({
        "type": "http", "method": "GET", "path": "/api/alerts/", "headers": [],
        "client": (IP, 1234), "query_string": b"",
    })
    check = get_rate_limit_dependency("alerts")
    with patch("security.rate_limiting.rate_limiter", limiter):
        check(request)
        with pytest.raises(HTTPException) as exc:
            check(request)
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"] == "10"


def test_stats_count_clients_not_buckets(limiter):
    limiter.is_allowed(IP, "alerts")
    limiter.is_allowed(IP, "alerts_write")
    limiter.is_allowed("198.51.100.7", "alerts")
    assert limiter.get_stats()["active_clients"] == 2
