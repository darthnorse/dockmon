"""
Integration tests for the stats history proxy endpoints.

These cover:
- /api/hosts/{host_id}/stats/history
- /api/hosts/{host_id}/containers/{container_id}/stats/history

The endpoints forward to the Go stats-service. Tests patch
stats_client.get_stats_client so they run without the Go service
actually running — the focus is on request wiring, validation,
upstream error mapping, and defense-in-depth container_id
normalization.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from fastapi.testclient import TestClient

import main as main_module
from main import app
from stats_client import StatsServiceClient


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


@pytest.mark.integration
class TestUpstreamErrorMapping:
    """
    The proxy must translate stats-service errors into appropriate
    HTTP responses so a bad query doesn't look like a backend crash.
    """

    def test_upstream_400_is_mirrored_as_400(
        self, client, test_api_key_write, mock_stats_client
    ):
        """4xx upstream errors surface to the caller as the same 4xx."""
        mock_stats_client.get_host_stats_history = AsyncMock(
            side_effect=StatsServiceClient.HistoryUpstreamError(
                400, "requested window > tier window (1h)\n"
            )
        )

        resp = client.get(
            "/api/hosts/host-1/stats/history?range=1h&from=0&to=9999999",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )

        assert resp.status_code == 400, resp.text
        assert "tier window" in resp.json()["detail"]

    def test_upstream_500_is_mapped_to_502(
        self, client, test_api_key_write, mock_stats_client
    ):
        """Upstream 5xx becomes 502 Bad Gateway at the proxy."""
        mock_stats_client.get_host_stats_history = AsyncMock(
            side_effect=StatsServiceClient.HistoryUpstreamError(
                500, "database is locked"
            )
        )

        resp = client.get(
            "/api/hosts/host-1/stats/history?range=1h",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )

        assert resp.status_code == 502, resp.text
        assert "stats-service error" in resp.json()["detail"]

    def test_upstream_connection_error_is_mapped_to_502(
        self, client, test_api_key_write, mock_stats_client
    ):
        """aiohttp connection errors become 502 at the proxy."""
        mock_stats_client.get_container_stats_history = AsyncMock(
            side_effect=aiohttp.ClientConnectionError("connection refused")
        )

        resp = client.get(
            "/api/hosts/host-1/containers/abc123abc123/stats/history?range=1h",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )

        assert resp.status_code == 502, resp.text
        assert "unavailable" in resp.json()["detail"]


@pytest.mark.integration
class TestStatsClientHistoryMethod:
    """
    Unit-level tests for the stats_client helper methods themselves,
    exercising the 401-retry loop and error-raising behaviour without
    going through the FastAPI app.
    """

    async def test_401_triggers_token_refresh_and_retry(self):
        """First 401 should invalidate cached token and retry once."""
        from unittest.mock import MagicMock
        svc = StatsServiceClient()

        # Build a response mock that returns 401 the first time and 200
        # the second time. aiohttp's session.get returns an async context
        # manager, so we need to fake that protocol.
        class _FakeResp:
            def __init__(self, status, payload):
                self.status = status
                self._payload = payload
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def json(self):
                return self._payload
            async def text(self):
                return ""

        responses = [
            _FakeResp(401, None),
            _FakeResp(200, {"tier": "1h", "timestamps": []}),
        ]

        fake_session = MagicMock()
        fake_session.get = MagicMock(side_effect=lambda *a, **kw: responses.pop(0))

        svc._get_session = AsyncMock(return_value=fake_session)
        svc._invalidate_auth = AsyncMock()

        result = await svc.get_host_stats_history(host_id="h1", range_="1h")
        assert result == {"tier": "1h", "timestamps": []}
        svc._invalidate_auth.assert_awaited_once()
        assert fake_session.get.call_count == 2

    async def test_upstream_non_200_raises_history_upstream_error(self):
        """Non-200 on the second attempt propagates as HistoryUpstreamError."""
        from unittest.mock import MagicMock
        svc = StatsServiceClient()

        class _FakeResp:
            def __init__(self, status, text_body):
                self.status = status
                self._text = text_body
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def text(self):
                return self._text
            async def json(self):
                raise AssertionError("should not decode JSON on error path")

        fake_session = MagicMock()
        fake_session.get = MagicMock(
            return_value=_FakeResp(400, "invalid range \"99y\"\n")
        )
        svc._get_session = AsyncMock(return_value=fake_session)
        svc._invalidate_auth = AsyncMock()

        with pytest.raises(StatsServiceClient.HistoryUpstreamError) as excinfo:
            await svc.get_container_stats_history(
                host_id="h1", container_id="abc123abc123", range_="99y"
            )

        assert excinfo.value.status == 400
        assert "invalid range" in excinfo.value.body
        svc._invalidate_auth.assert_not_awaited()


@pytest.fixture
def stub_settings_db(monkeypatch):
    """
    Stub monitor.db.update_settings so the POST /api/settings test doesn't
    need a real GlobalSettings row (the test database is empty). Returns a
    fake settings object with the attributes the endpoint reads after the
    update, matching the GlobalSettings schema. The tests for Task 17 only
    care about the hot-push code path, not the database layer itself.
    """
    # Fake "updated" settings object returned by db.update_settings.
    fake_settings = MagicMock()
    fake_settings.show_host_stats = True
    fake_settings.show_container_stats = True
    fake_settings.session_timeout_hours = 24
    fake_settings.update_check_time = "03:00"
    fake_settings.event_suppression_patterns = None
    # All the fields the endpoint returns in its response dict — set to
    # sensible defaults so getattr() returns real values.
    for attr in (
        "max_retries", "retry_delay", "default_auto_restart",
        "polling_interval", "connection_timeout", "enable_notifications",
        "alert_template", "alert_template_metric", "alert_template_state_change",
        "alert_template_health", "alert_template_update", "blackout_windows",
        "timezone_offset", "show_container_alerts_on_hosts",
        "unused_tag_retention_days", "event_retention_days",
    ):
        setattr(fake_settings, attr, None)

    monkeypatch.setattr(
        main_module.monitor.db, "update_settings", lambda updates: fake_settings
    )
    # monitor.settings is read for old_show_*_stats comparisons before the DB call.
    monkeypatch.setattr(main_module.monitor, "settings", fake_settings)
    return fake_settings


@pytest.mark.integration
class TestPushSettingsUpdate:
    """Task 17: POST /api/settings with stats_* keys should push to stats-service."""

    def test_update_settings_pushes_stats_settings(
        self, client, test_api_key_write, mock_stats_client, stub_settings_db
    ):
        mock_stats_client.push_settings_update = AsyncMock()

        resp = client.post(
            "/api/settings",
            json={"stats_retention_days": 45, "stats_points_per_view": 750},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        mock_stats_client.push_settings_update.assert_called_once_with(
            stats_retention_days=45,
            stats_points_per_view=750,
        )

    def test_update_settings_without_stats_keys_does_not_push(
        self, client, test_api_key_write, mock_stats_client, stub_settings_db
    ):
        mock_stats_client.push_settings_update = AsyncMock()

        resp = client.post(
            "/api/settings",
            json={"max_retries": 5},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        mock_stats_client.push_settings_update.assert_not_called()

    def test_update_settings_push_failure_is_non_fatal(
        self, client, test_api_key_write, mock_stats_client, stub_settings_db
    ):
        mock_stats_client.push_settings_update = AsyncMock(
            side_effect=aiohttp.ClientError("connection refused")
        )

        resp = client.post(
            "/api/settings",
            json={"stats_retention_days": 30},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        # Should still succeed even though push failed
        assert resp.status_code == 200, resp.text
