"""Integration tests for the on-demand live stats endpoints.

GET /api/hosts/{host_id}/stats/live
GET /api/hosts/{host_id}/containers/{container_id}/stats/live

These read the in-memory live buffers directly (NOT a stats-service proxy) and
return the EXTENDED sparkline shape (timestamps + memory bytes) for the
detail-view live chart. The broadcast path stays lean and is unaffected.
"""
import pytest

import main
from utils.keys import make_composite_key

EXTENDED_KEYS = {
    "timestamps", "cpu", "mem", "net",
    "memory_used_bytes", "memory_limit_bytes",
}


@pytest.fixture
def seeded_host_buffer():
    """Seed the host live buffer with a few points; clean up after."""
    host_id = "live-host"
    main.monitor.stats_history.remove_host(host_id)
    for i in range(5):
        main.monitor.stats_history.add_stats(
            host_id, cpu=float(i), mem=10.0, net=1.0,
            memory_used_bytes=1000 + i, memory_limit_bytes=8000,
        )
    yield host_id
    main.monitor.stats_history.remove_host(host_id)


@pytest.fixture
def seeded_container_buffer():
    """Seed the container live buffer (keyed by 12-char composite key)."""
    host_id, cid = "host-1", "abc123abc123"
    key = make_composite_key(host_id, cid)
    main.monitor.container_stats_history.remove_container(key)
    for i in range(3):
        main.monitor.container_stats_history.add_stats(
            key, cpu=float(i), mem=20.0, net=2.0,
            memory_used_bytes=2000 + i, memory_limit_bytes=16000,
        )
    yield host_id, cid, key
    main.monitor.container_stats_history.remove_container(key)


@pytest.mark.integration
class TestHostStatsLive:
    def test_requires_authentication(self, client):
        resp = client.get("/api/hosts/live-host/stats/live")
        assert resp.status_code == 401

    def test_returns_extended_series(
        self, client, test_api_key_write, seeded_host_buffer
    ):
        resp = client.get(
            f"/api/hosts/{seeded_host_buffer}/stats/live",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == EXTENDED_KEYS
        # Memory bytes are stored raw (not EMA-smoothed).
        assert body["memory_used_bytes"] == [1000, 1001, 1002, 1003, 1004]
        assert body["memory_limit_bytes"] == [8000] * 5
        assert len(body["timestamps"]) == 5
        assert all(isinstance(t, float) for t in body["timestamps"])

    def test_unknown_host_returns_empty_arrays(self, client, test_api_key_write):
        resp = client.get(
            "/api/hosts/does-not-exist/stats/live",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == EXTENDED_KEYS
        assert all(body[k] == [] for k in EXTENDED_KEYS)


@pytest.mark.integration
class TestContainerStatsLive:
    def test_requires_authentication(self, client):
        resp = client.get(
            "/api/hosts/host-1/containers/abc123abc123/stats/live"
        )
        assert resp.status_code == 401

    def test_returns_extended_series(
        self, client, test_api_key_write, seeded_container_buffer
    ):
        host_id, cid, _ = seeded_container_buffer
        resp = client.get(
            f"/api/hosts/{host_id}/containers/{cid}/stats/live",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == EXTENDED_KEYS
        assert body["memory_used_bytes"] == [2000, 2001, 2002]
        assert body["memory_limit_bytes"] == [16000] * 3

    def test_normalizes_64char_container_id(
        self, client, test_api_key_write, seeded_container_buffer
    ):
        host_id, cid, _ = seeded_container_buffer
        # Buffer is keyed by the 12-char id; a 64-char id must normalize to it.
        full_id = cid + "0" * 52  # 12 + 52 = 64 chars
        resp = client.get(
            f"/api/hosts/{host_id}/containers/{full_id}/stats/live",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["memory_used_bytes"] == [2000, 2001, 2002]
