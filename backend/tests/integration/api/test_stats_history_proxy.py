"""
Integration tests for the stats history proxy endpoints.

These cover:
- /api/hosts/{host_id}/stats/history
- /api/hosts/{host_id}/containers/{container_id}/stats/history

The endpoints forward to the Go stats-service. Tests patch
stats_client.get_stats_client so they run without the Go service
actually running — the focus is on request wiring, validation, and
defense-in-depth container_id normalization.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """FastAPI TestClient for the stats history endpoints."""
    return TestClient(app)


@pytest.fixture
def mock_stats_client():
    """
    Patch stats_client.get_stats_client so the endpoints talk to a fake
    client that doesn't need a running stats-service.

    Tests set .get_host_stats_history / .get_container_stats_history on
    the returned mock to configure the fake response.
    """
    with patch("stats_client.get_stats_client") as mock_get:
        client_mock = AsyncMock()
        mock_get.return_value = client_mock
        yield client_mock


def _host_history_payload():
    return {
        "tier": "1h",
        "tier_seconds": 3600,
        "interval_seconds": 7,
        "from": 0,
        "to": 3600,
        "server_time": 5000,
        "timestamps": [0, 7, 14],
        "cpu": [1.0, None, 3.0],
        "mem": [10.0, 11.0, 12.0],
        "net_bps": [100.0, 200.0, 300.0],
    }


def _container_history_payload():
    return {
        "tier": "1h",
        "tier_seconds": 3600,
        "interval_seconds": 7,
        "from": 0,
        "to": 3600,
        "server_time": 5000,
        "timestamps": [],
        "cpu": [],
        "mem": [],
        "net_bps": [],
        "memory_used_bytes": [],
        "memory_limit_bytes": [],
    }


@pytest.mark.integration
class TestHostStatsHistoryProxy:
    """Tests for GET /api/hosts/{host_id}/stats/history."""

    def test_requires_authentication(self, client):
        resp = client.get("/api/hosts/host-1/stats/history?range=1h")
        assert resp.status_code == 401

    def test_missing_range_and_from_returns_400(
        self, client, test_api_key_write
    ):
        resp = client.get(
            "/api/hosts/host-1/stats/history",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 400

    def test_range_forwards_to_stats_service(
        self, client, test_api_key_write, mock_stats_client
    ):
        mock_stats_client.get_host_stats_history = AsyncMock(
            return_value=_host_history_payload()
        )

        resp = client.get(
            "/api/hosts/host-1/stats/history?range=1h",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tier"] == "1h"
        assert body["timestamps"] == [0, 7, 14]
        mock_stats_client.get_host_stats_history.assert_called_once_with(
            host_id="host-1",
            range_="1h",
            from_=None,
            to=None,
            since=None,
        )

    def test_from_to_forwards_to_stats_service(
        self, client, test_api_key_write, mock_stats_client
    ):
        mock_stats_client.get_host_stats_history = AsyncMock(
            return_value=_host_history_payload()
        )

        resp = client.get(
            "/api/hosts/host-1/stats/history?from=100&to=200",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )

        assert resp.status_code == 200, resp.text
        mock_stats_client.get_host_stats_history.assert_called_once_with(
            host_id="host-1",
            range_=None,
            from_=100,
            to=200,
            since=None,
        )

    def test_invalid_range_value_returns_422(
        self, client, test_api_key_write
    ):
        """Regex pattern on range query param rejects unknown tiers."""
        resp = client.get(
            "/api/hosts/host-1/stats/history?range=99y",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        # FastAPI returns 422 for query-param validation failures.
        assert resp.status_code == 422


@pytest.mark.integration
class TestContainerStatsHistoryProxy:
    """Tests for GET /api/hosts/{host_id}/containers/{container_id}/stats/history."""

    def test_requires_authentication(self, client):
        resp = client.get(
            "/api/hosts/host-1/containers/abc123abc123/stats/history?range=1h"
        )
        assert resp.status_code == 401

    def test_missing_range_and_from_returns_400(
        self, client, test_api_key_write
    ):
        resp = client.get(
            "/api/hosts/host-1/containers/abc123abc123/stats/history",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 400

    def test_range_forwards_to_stats_service(
        self, client, test_api_key_write, mock_stats_client
    ):
        mock_stats_client.get_container_stats_history = AsyncMock(
            return_value=_container_history_payload()
        )

        resp = client.get(
            "/api/hosts/host-1/containers/abc123abc123/stats/history?range=1h",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tier"] == "1h"
        mock_stats_client.get_container_stats_history.assert_called_once_with(
            host_id="host-1",
            container_id="abc123abc123",
            range_="1h",
            from_=None,
            to=None,
            since=None,
        )

    def test_long_container_id_is_normalized_to_12_chars(
        self, client, test_api_key_write, mock_stats_client
    ):
        """
        CLAUDE.md defense-in-depth: container endpoints MUST normalize the
        path param at entry, so a 64-char ID from the frontend is collapsed
        to the canonical 12-char form before hitting the stats-service.
        """
        mock_stats_client.get_container_stats_history = AsyncMock(
            return_value=_container_history_payload()
        )
        long_id = "a" * 64

        resp = client.get(
            f"/api/hosts/host-1/containers/{long_id}/stats/history?range=1h",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )

        assert resp.status_code == 200, resp.text
        call_kwargs = mock_stats_client.get_container_stats_history.call_args.kwargs
        assert len(call_kwargs["container_id"]) == 12
        assert call_kwargs["container_id"] == "a" * 12

    def test_since_param_is_forwarded(
        self, client, test_api_key_write, mock_stats_client
    ):
        mock_stats_client.get_container_stats_history = AsyncMock(
            return_value=_container_history_payload()
        )

        resp = client.get(
            "/api/hosts/host-1/containers/abc123abc123/stats/history?range=1h&since=42",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )

        assert resp.status_code == 200, resp.text
        mock_stats_client.get_container_stats_history.assert_called_once_with(
            host_id="host-1",
            container_id="abc123abc123",
            range_="1h",
            from_=None,
            to=None,
            since=42,
        )
