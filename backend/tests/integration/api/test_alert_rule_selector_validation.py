"""Selector validation on the live write path.

The engine runs `regex:`-prefixed selector values as patterns on every
evaluation cycle. Rejecting a bad one at the door beats discovering it when the
loop stalls - but this is a usability boundary, not a security one: restores,
migrations and direct DatabaseManager calls all bypass it, which is why the
runtime bound in alerts/safe_regex.py is what actually keeps the loop safe.
"""
import json
from unittest.mock import MagicMock

import pytest

import database as database_module
from database import AlertRuleV2, DatabaseManager

CATASTROPHIC = r"(a|aa)+$"


@pytest.fixture
def _real_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database_module._database_manager_instance = None
    db_manager = DatabaseManager(db_path=db_path)
    try:
        yield db_manager
    finally:
        if hasattr(db_manager, "engine"):
            db_manager.engine.dispose()
        database_module._database_manager_instance = None


@pytest.fixture
def alert_client(client, monkeypatch, _real_db):
    import main
    from auth.api_key_auth import get_current_user_or_api_key

    async def _mock_user():
        return {"username": "test_user", "user_id": 1, "auth_type": "session"}

    main.app.dependency_overrides[get_current_user_or_api_key] = _mock_user
    monkeypatch.setattr("auth.api_key_auth.check_auth_capability", lambda user, cap: True)
    monkeypatch.setattr(main.monitor, "db", _real_db)
    monkeypatch.setattr(main.monitor, "event_logger", MagicMock())

    yield client

    main.app.dependency_overrides.pop(get_current_user_or_api_key, None)


def _payload(**overrides):
    payload = {
        "name": "Selector Rule",
        "scope": "host",
        "kind": "cpu_high",
        "severity": "warning",
        "metric": "cpu_percent",
        "operator": ">=",
        "threshold": 90.0,
    }
    payload.update(overrides)
    return payload


def _rejected(resp):
    return resp.status_code in (400, 422)


def _insert(db, rule_id, **fields):
    row = {
        "id": rule_id, "name": rule_id, "kind": "cpu_high", "enabled": True,
        "scope": "host", "metric": "cpu_percent", "operator": ">=",
        "threshold": 90.0, "occurrences": 1, "severity": "warning",
    }
    row.update(fields)
    with db.get_session() as session:
        session.add(AlertRuleV2(**row))
        session.commit()
    return rule_id


def _stored(db, rule_id):
    with db.get_session() as session:
        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).first()
        if rule:
            session.expunge(rule)
        return rule


@pytest.mark.integration
class TestCreateSelectorValidation:
    def test_valid_selector_saves(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(
            host_selector_json=json.dumps({"host_name": "regex:^web-[0-9]+$"})
        ))
        assert resp.status_code == 200, resp.text

    def test_exact_match_selector_saves(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(
            host_selector_json=json.dumps({"host_name": "web-01"})
        ))
        assert resp.status_code == 200, resp.text

    def test_no_selector_saves(self, alert_client):
        assert alert_client.post("/api/alerts/rules", json=_payload()).status_code == 200

    def test_unparseable_selector_json_is_refused(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(
            host_selector_json="{not json"
        ))
        assert _rejected(resp), resp.text

    def test_non_object_selector_json_is_refused(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(
            host_selector_json=json.dumps(["web-01"])
        ))
        assert _rejected(resp), resp.text

    def test_oversized_selector_is_refused(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(
            host_selector_json=json.dumps({"host_name": "x" * 20000})
        ))
        assert _rejected(resp), resp.text

    def test_uncompilable_pattern_is_refused(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(
            host_selector_json=json.dumps({"host_name": "regex:(unclosed"})
        ))
        assert _rejected(resp), resp.text

    def test_over_long_pattern_is_refused(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(
            host_selector_json=json.dumps({"host_name": "regex:" + "a" * 600})
        ))
        assert _rejected(resp), resp.text

    def test_container_selector_is_validated_too(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(
            scope="container",
            container_selector_json=json.dumps({"container_name": "regex:(unclosed"}),
        ))
        assert _rejected(resp), resp.text

    def test_rejection_explains_itself(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(
            host_selector_json=json.dumps({"host_name": "regex:(unclosed"})
        ))
        assert resp.status_code == 400, resp.text
        assert "host_selector_json" in resp.json()["detail"]


@pytest.mark.integration
class TestUpdateSelectorValidation:
    def test_changing_a_selector_is_validated(self, alert_client, _real_db):
        _insert(_real_db, "sel-rule", host_selector_json=json.dumps({"host_name": "web-01"}))

        resp = alert_client.put("/api/alerts/rules/sel-rule", json={
            "host_selector_json": json.dumps({"host_name": "regex:(unclosed"})
        })

        assert resp.status_code == 400, resp.text
        assert "web-01" in _stored(_real_db, "sel-rule").host_selector_json

    def test_valid_selector_change_succeeds(self, alert_client, _real_db):
        _insert(_real_db, "sel-ok", host_selector_json=json.dumps({"host_name": "web-01"}))

        resp = alert_client.put("/api/alerts/rules/sel-ok", json={
            "host_selector_json": json.dumps({"host_name": "regex:^web-[0-9]+$"})
        })

        assert resp.status_code == 200, resp.text
        assert "regex:" in _stored(_real_db, "sel-ok").host_selector_json

    def test_a_legacy_bad_container_selector_does_not_block_fixing_the_host_one(
        self, alert_client, _real_db
    ):
        """Only the selector being changed is validated.

        Merging both would make an untouched legacy field veto a legitimate fix.
        """
        _insert(
            _real_db, "half-bad",
            host_selector_json=json.dumps({"host_name": f"regex:{CATASTROPHIC}"}),
            container_selector_json="{not json at all",
        )

        resp = alert_client.put("/api/alerts/rules/half-bad", json={
            "host_selector_json": json.dumps({"host_name": "web-01"})
        })

        assert resp.status_code == 200, resp.text

    def test_unrelated_update_of_a_legacy_bad_rule_still_works(self, alert_client, _real_db):
        _insert(_real_db, "legacy-sel", host_selector_json="{not json")

        resp = alert_client.put("/api/alerts/rules/legacy-sel", json={"name": "renamed"})

        assert resp.status_code == 200, resp.text
        assert _stored(_real_db, "legacy-sel").name == "renamed"
