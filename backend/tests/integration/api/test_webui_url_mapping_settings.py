"""Integration tests for /api/settings webui_url_mapping_chain (Issue #207).

Note: GET /api/settings currently requires session-style auth (it reads
`current_user.get('username')` and 401s when None). API-key auth does not
populate `username`, so we exercise the read path through the POST response
(which is built from the same updated row) and via direct DB inspection.

The GET-vs-API-key asymmetry is a real product gap, tracked as a follow-up
to Issue #207 (see TODO at backend/main.py get_settings handler). Fixing it
is out of scope for this task.
"""
from datetime import datetime, timezone

import pytest

from database import GlobalSettings


@pytest.fixture
def seed_global_settings(db_session):
    """Seed an empty GlobalSettings row so update_settings has something to mutate."""
    settings = GlobalSettings(id=1, updated_at=datetime.now(timezone.utc))
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.mark.integration
class TestWebUIUrlMappingSettings:
    def test_post_response_returns_empty_chain_when_unset(
        self, client, test_api_key_write, seed_global_settings
    ):
        """A no-op POST should still surface the new field with its default ([])."""
        resp = client.post(
            "/api/settings",
            json={},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "webui_url_mapping_chain" in body
        assert body["webui_url_mapping_chain"] == []

    def test_post_chain_persists_and_round_trips(
        self, client, test_api_key_write, seed_global_settings, db_session
    ):
        chain = [
            "https://${env:WEBUI_URL}",
            "https://${env:VIRTUAL_HOST}",
            "${label:com.acme.url}",
        ]
        resp = client.post(
            "/api/settings",
            json={"webui_url_mapping_chain": chain},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["webui_url_mapping_chain"] == chain

        # Verify directly in the DB row that the value was actually persisted
        # (proves the write path goes through DatabaseManager.update_settings,
        # not just round-trips through the response model).
        db_session.expire_all()
        row = db_session.query(GlobalSettings).one()
        assert row.webui_url_mapping_chain == chain

        # And a follow-up POST should still see the persisted value
        resp = client.post(
            "/api/settings",
            json={},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200
        assert resp.json()["webui_url_mapping_chain"] == chain

    def test_post_empty_chain_clears_existing(
        self, client, test_api_key_write, seed_global_settings, db_session
    ):
        # Set, then clear
        client.post(
            "/api/settings",
            json={"webui_url_mapping_chain": ["https://${env:X}"]},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        resp = client.post(
            "/api/settings",
            json={"webui_url_mapping_chain": []},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 200
        assert resp.json()["webui_url_mapping_chain"] == []

        db_session.expire_all()
        row = db_session.query(GlobalSettings).one()
        assert (row.webui_url_mapping_chain or []) == []

    def test_post_rejects_unknown_extra_field(
        self, client, test_api_key_write, seed_global_settings
    ):
        # Unrelated regression check — Pydantic's extra=forbid still works.
        resp = client.post(
            "/api/settings",
            json={"totally_made_up_setting": "x"},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 422

    def test_post_rejects_empty_template(
        self, client, test_api_key_write, seed_global_settings
    ):
        resp = client.post(
            "/api/settings",
            json={"webui_url_mapping_chain": ["https://${env:X}", ""]},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 422

    def test_post_rejects_overlong_template(
        self, client, test_api_key_write, seed_global_settings
    ):
        resp = client.post(
            "/api/settings",
            json={"webui_url_mapping_chain": ["https://" + "a" * 2100]},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 422

    def test_post_rejects_overlong_chain(
        self, client, test_api_key_write, seed_global_settings
    ):
        resp = client.post(
            "/api/settings",
            json={"webui_url_mapping_chain": [f"https://${{env:VAR{i}}}" for i in range(25)]},
            headers={"Authorization": f"Bearer {test_api_key_write}"},
        )
        assert resp.status_code == 422
