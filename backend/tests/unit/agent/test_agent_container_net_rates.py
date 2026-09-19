"""Agent container stats: the handler derives per-direction network rates from the
cumulative counters, alongside the combined rate the sparklines already use."""

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
