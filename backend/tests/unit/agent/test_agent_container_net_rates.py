"""Agent container stats: the handler derives per-direction network rates from the
cumulative counters, alongside the combined rate the sparklines already use."""

import json
import math
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.websocket_handler import AgentWebSocketHandler


def _handler():
    monitor = SimpleNamespace(
        container_stats_history=MagicMock(),
        agent_container_stats_cache={},
        manager=SimpleNamespace(broadcast=AsyncMock()),
    )
    with patch("agent.websocket_handler.AgentManager"), patch("agent.websocket_handler.DatabaseManager"):
        handler = AgentWebSocketHandler(websocket=MagicMock(), monitor=monitor)
    handler.agent_id = "agent-1"
    handler.host_id = "11111111-1111-1111-1111-111111111111"
    return handler


async def test_per_direction_rates_from_cumulative_counters():
    handler = _handler()
    key = f"{handler.host_id}:aaa111111111"
    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": 1000, "network_tx": 500})
    handler.prev_network_stats[key]["timestamp"] = time.time() - 1.0

    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": 3000, "network_tx": 1500})

    cached = handler.monitor.agent_container_stats_cache[key]
    assert cached["net_bytes_per_sec"] == pytest.approx(3000, rel=0.1)
    assert cached["net_rx_bytes_per_sec"] == pytest.approx(2000, rel=0.1)
    assert cached["net_tx_bytes_per_sec"] == pytest.approx(1000, rel=0.1)


async def test_counter_reset_zeroes_every_rate():
    handler = _handler()
    key = f"{handler.host_id}:aaa111111111"
    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": 5000, "network_tx": 5000})
    handler.prev_network_stats[key]["timestamp"] = time.time() - 1.0

    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": 10, "network_tx": 10})

    cached = handler.monitor.agent_container_stats_cache[key]
    assert (cached["net_bytes_per_sec"], cached["net_rx_bytes_per_sec"], cached["net_tx_bytes_per_sec"]) == (0, 0, 0)


async def test_one_direction_reset_zeroes_every_rate():
    handler = _handler()
    key = f"{handler.host_id}:aaa111111111"
    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": 100, "network_tx": 100})
    handler.prev_network_stats[key]["timestamp"] = time.time() - 1.0

    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": 50, "network_tx": 300})

    cached = handler.monitor.agent_container_stats_cache[key]
    assert (cached["net_bytes_per_sec"], cached["net_rx_bytes_per_sec"], cached["net_tx_bytes_per_sec"]) == (0, 0, 0)


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), -5, 10**400, True, "12"])
async def test_unusable_counters_yield_finite_zero_rates(bad):
    handler = _handler()
    key = f"{handler.host_id}:aaa111111111"
    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": 1, "network_tx": 1})
    handler.prev_network_stats[key]["timestamp"] = time.time() - 1.0

    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": bad, "network_tx": 1})

    cached = handler.monitor.agent_container_stats_cache[key]
    rates = (cached["net_bytes_per_sec"], cached["net_rx_bytes_per_sec"], cached["net_tx_bytes_per_sec"])
    assert rates == (0, 0, 0)
    assert all(math.isfinite(r) for r in rates)
    assert cached["network_rx"] == 0 and cached["network_tx"] == 0


async def test_unusable_sample_does_not_become_the_baseline():
    handler = _handler()
    key = f"{handler.host_id}:aaa111111111"
    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": float("inf"), "network_tx": 1})
    assert key not in handler.prev_network_stats

    # The next valid sample is a warm-up, not a jump from zero
    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": 10**9, "network_tx": 10**9})
    cached = handler.monitor.agent_container_stats_cache[key]
    assert (cached["net_bytes_per_sec"], cached["net_rx_bytes_per_sec"], cached["net_tx_bytes_per_sec"]) == (0, 0, 0)


async def test_broadcast_carries_sanitized_counters_and_rates():
    handler = _handler()
    await handler._handle_container_stats({"container_id": "aaa111111111", "network_rx": float("nan"), "network_tx": 1})

    payload = handler.monitor.manager.broadcast.await_args.args[0]
    assert payload["type"] == "container_stats"
    stats = payload["stats"]
    assert stats["network_rx"] == 0 and stats["network_tx"] == 0
    assert all(math.isfinite(stats[k]) for k in ("net_bytes_per_sec", "net_rx_bytes_per_sec", "net_tx_bytes_per_sec"))
    json.dumps(payload, allow_nan=False)
