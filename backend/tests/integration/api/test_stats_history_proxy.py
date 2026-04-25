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

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from fastapi.testclient import TestClient

from database import GlobalSettings
from main import app
from stats_client import StatsServiceClient


@pytest.fixture
def client():
    """FastAPI TestClient for the stats history endpoints."""
    return TestClient(app)


@pytest.fixture
def mock_stats_client():
    """
    Patch get_stats_client where it is bound in main so the endpoints talk
    to a fake client that doesn't need a running stats-service.

    Tests set .get_host_stats_history / .get_container_stats_history on
    the returned mock to configure the fake response.
    """
    with patch("main.get_stats_client") as mock_get:
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

    @pytest.mark.parametrize("rng", ["1h", "8h", "24h", "7d", "30d"])
    def test_all_documented_ranges_are_accepted(
        self, client, test_api_key_write, mock_stats_client, rng
    ):
        """
        Guardrail against tier/regex drift: every TimeRange value in
        ui/src/lib/stats/historyTypes.ts (minus 'live') must be accepted by
        the proxy and forwarded verbatim to stats-service. Adding a new
        tier in cascade.go without updating main.STATS_RANGE_PATTERN now
        fails here instead of at runtime in the UI.
        """
        mock_stats_client.get_host_stats_history = AsyncMock(
            return_value=_host_history_payload()
        )
        resp = client.get(
            f"/api/hosts/host-1/stats/history?range={rng}",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        call_kwargs = mock_stats_client.get_host_stats_history.call_args.kwargs
        assert call_kwargs["range_"] == rng


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

    @pytest.mark.parametrize("rng", ["1h", "8h", "24h", "7d", "30d"])
    def test_all_documented_ranges_are_accepted(
        self, client, test_api_key_write, mock_stats_client, rng
    ):
        """
        Same guardrail as the host variant: any tier added to cascade.go
        must also be present in main.STATS_RANGE_PATTERN or this test
        catches the drift before it reaches the UI.
        """
        mock_stats_client.get_container_stats_history = AsyncMock(
            return_value=_container_history_payload()
        )
        resp = client.get(
            f"/api/hosts/host-1/containers/abc123abc123/stats/history?range={rng}",
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        call_kwargs = mock_stats_client.get_container_stats_history.call_args.kwargs
        assert call_kwargs["range_"] == rng


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
def seed_global_settings(db_session):
    """
    Seed a real GlobalSettings row in the test database so the POST
    /api/settings endpoint can actually read → mutate → commit → re-read it
    via the real monitor.db.update_settings path. No stubs — the whole code
    path (FastAPI → Pydantic → DatabaseManager.update_settings → SQLite →
    response) is exercised end-to-end.

    use_test_database_for_auth (autouse in this package's conftest.py)
    already redirects monitor.db.get_session → this same db_session, so
    update_settings() will see the row we commit here.
    """
    now = datetime.now(timezone.utc)
    # Only explicit values — the rest come from ORM/server defaults, which
    # is what a real fresh install looks like after migration 037 runs.
    settings = GlobalSettings(
        id=1,
        updated_at=now,
    )
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.mark.integration
class TestPushSettingsUpdate:
    """Task 17: POST /api/settings with stats_* keys should push to stats-service."""

    def test_update_settings_pushes_stats_settings(
        self, client, test_api_key_write, mock_stats_client, seed_global_settings
    ):
        mock_stats_client.push_settings_update = AsyncMock()

        resp = client.post(
            "/api/settings",
            json={"stats_retention_days": 25, "stats_points_per_view": 750},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        mock_stats_client.push_settings_update.assert_called_once_with(
            stats_retention_days=25,
            stats_points_per_view=750,
        )

        # Regression for the database.py ALLOWED_SETTINGS whitelist bug:
        # the values must actually be persisted, not silently dropped.
        # Response body round-trips the stored values.
        body = resp.json()
        assert body["stats_retention_days"] == 25
        assert body["stats_points_per_view"] == 750
        assert body["stats_persistence_enabled"] is False  # unchanged (server default)

    def test_update_settings_persists_stats_values_in_db(
        self, client, test_api_key_write, mock_stats_client,
        seed_global_settings, db_session,
    ):
        """
        Regression test for the ALLOWED_SETTINGS whitelist bug: POST with
        stats_* keys must actually UPDATE the row in the database, so on
        backend restart the values survive. Reads back via a fresh query
        on the same test session.
        """
        mock_stats_client.push_settings_update = AsyncMock()

        resp = client.post(
            "/api/settings",
            json={
                "stats_persistence_enabled": False,
                "stats_retention_days": 14,
                "stats_points_per_view": 1000,
            },
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text

        # Expire the seeded row so we re-read fresh from the DB, not the
        # SQLAlchemy identity map. This is the moment of truth: if the
        # whitelist silently dropped the keys, these asserts will fail.
        db_session.expire_all()
        row = db_session.query(GlobalSettings).one()
        assert row.stats_persistence_enabled is False
        assert row.stats_retention_days == 14
        assert row.stats_points_per_view == 1000

    def test_update_settings_without_stats_keys_does_not_push(
        self, client, test_api_key_write, mock_stats_client, seed_global_settings
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
        self, client, test_api_key_write, mock_stats_client, seed_global_settings
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
