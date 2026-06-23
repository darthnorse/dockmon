"""Integration tests for /api/settings live_chart_window_seconds.

The setting controls how far back the detail-view live chart reaches. It bounds
the in-memory live buffer per entity (age-trim), so it is purely backend +
frontend and is NOT pushed to the Go stats-service (unlike stats_retention_days
/ stats_points_per_view).

Mirrors test_webui_url_mapping_settings.py: GET /api/settings needs session
auth, so the read path is exercised through the POST response (built from the
same updated row) and via direct DB inspection.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from database import GlobalSettings


@pytest.fixture
def seed_global_settings(db_session):
    """Seed an empty GlobalSettings row so update_settings has something to mutate."""
    settings = GlobalSettings(id=1, updated_at=datetime.now(timezone.utc))
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.fixture
def mock_stats_client():
    """Fake stats-service client so the push path is observable (and inert)."""
    with patch("main.get_stats_client") as mock_get:
        client_mock = AsyncMock()
        mock_get.return_value = client_mock
        yield client_mock


@pytest.mark.integration
class TestLiveChartWindowSettings:
    def test_post_response_returns_default_when_unset(
        self, client, test_api_key_write, seed_global_settings
    ):
        """A no-op POST surfaces the new field with its 600s (10 min) default."""
        resp = client.post(
            "/api/settings", json={},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "live_chart_window_seconds" in body
        assert body["live_chart_window_seconds"] == 600

    def test_post_window_persists_and_round_trips(
        self, client, test_api_key_write, seed_global_settings, db_session
    ):
        resp = client.post(
            "/api/settings", json={"live_chart_window_seconds": 900},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["live_chart_window_seconds"] == 900

        # Proves the write path persists through DatabaseManager.update_settings,
        # not just a round-trip through the response model.
        db_session.expire_all()
        row = db_session.query(GlobalSettings).one()
        assert row.live_chart_window_seconds == 900

        # A follow-up no-op POST still sees the persisted value (survives reload).
        resp = client.post(
            "/api/settings", json={},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200
        assert resp.json()["live_chart_window_seconds"] == 900

    @pytest.mark.parametrize("value", [60, 1800])
    def test_post_accepts_boundary_values(
        self, client, test_api_key_write, seed_global_settings, value
    ):
        resp = client.post(
            "/api/settings", json={"live_chart_window_seconds": value},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["live_chart_window_seconds"] == value

    @pytest.mark.parametrize("value", [59, 1801, 0, -1])
    def test_post_rejects_out_of_range(
        self, client, test_api_key_write, seed_global_settings, value
    ):
        resp = client.post(
            "/api/settings", json={"live_chart_window_seconds": value},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 422

    def test_post_window_does_not_push_to_stats_service(
        self, client, test_api_key_write, seed_global_settings, mock_stats_client
    ):
        """Backend-only setting: must NOT be pushed to the Go stats-service."""
        mock_stats_client.push_settings_update = AsyncMock()
        resp = client.post(
            "/api/settings", json={"live_chart_window_seconds": 1200},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        mock_stats_client.push_settings_update.assert_not_called()
