"""Rule metric validation on the live write path (issue #243, Fix C).

Routes under test:
  POST /api/alerts/rules       create_alert_rule_v2
  PUT  /api/alerts/rules/{id}  update_alert_rule_v2

Neither route validated `metric` at all, so a rule naming a metric no producer
serves saved with a 200 and then never fired. A dead AlertRuleValidator module
looked like it covered this but was imported only by its own tests; it has since been removed.

Partial updates are the subtle half: with exclude_unset=True a PUT carries
neither scope nor metric, so validation has to run against the stored rule
merged with the update, not against the payload alone.
"""
from unittest.mock import MagicMock

import pytest

import database as database_module
from database import AlertRuleV2, DatabaseManager

DROPPED_METRICS = (
    "network_rx_bytes",
    "network_tx_bytes",
    "block_read_bytes",
    "block_write_bytes",
)


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
    """TestClient with alert capabilities satisfied and a real temp SQLite DB."""
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
        "name": "Test Rule",
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
    """Model-level rejections are 422, route-level ones 400. Both are refusals."""
    return resp.status_code in (400, 422)


def _stored(db, rule_id):
    with db.get_session() as session:
        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).first()
        if rule:
            session.expunge(rule)
        return rule


def _insert(db, rule_id, **fields):
    row = {
        "id": rule_id,
        "name": rule_id,
        "kind": "cpu_high",
        "enabled": True,
        "scope": "host",
        "metric": "cpu_percent",
        "operator": ">=",
        "threshold": 90.0,
        "occurrences": 1,
        "severity": "warning",
    }
    row.update(fields)
    with db.get_session() as session:
        session.add(AlertRuleV2(**row))
        session.commit()
    return rule_id


@pytest.mark.integration
class TestCreateValidation:
    def test_valid_rule_still_saves(self, alert_client):
        # The route declares no status_code, so FastAPI answers 200.
        resp = alert_client.post("/api/alerts/rules", json=_payload())
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("metric", DROPPED_METRICS)
    def test_dropped_metrics_are_refused(self, alert_client, metric):
        resp = alert_client.post(
            "/api/alerts/rules",
            json=_payload(scope="container", kind="cpu_high", metric=metric, threshold=1000.0),
        )
        assert _rejected(resp), resp.text

    def test_unknown_metric_is_refused(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(metric="banana"))
        assert _rejected(resp), resp.text

    def test_event_rule_without_metric_still_saves(self, alert_client):
        resp = alert_client.post(
            "/api/alerts/rules",
            json={
                "name": "Container stopped",
                "scope": "container",
                "kind": "container_stopped",
                "severity": "warning",
            },
        )
        assert resp.status_code == 200, resp.text

    def test_memory_percent_threshold_is_capped(self, alert_client):
        # The gap the parent plan aimed at, on the path that actually runs.
        resp = alert_client.post(
            "/api/alerts/rules",
            json=_payload(kind="memory_high", metric="memory_percent", threshold=5000.0),
        )
        assert _rejected(resp), resp.text

    def test_container_cpu_may_exceed_100(self, alert_client):
        resp = alert_client.post(
            "/api/alerts/rules", json=_payload(scope="container", threshold=200.0)
        )
        assert resp.status_code == 200, resp.text

    def test_host_cpu_may_not_exceed_100(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(threshold=200.0))
        assert _rejected(resp), resp.text

    def test_disk_percent_is_host_only(self, alert_client):
        ok = alert_client.post(
            "/api/alerts/rules",
            json=_payload(kind="disk_low", metric="disk_percent", threshold=85.0),
        )
        assert ok.status_code == 200, ok.text

        bad = alert_client.post(
            "/api/alerts/rules",
            json=_payload(scope="container", kind="disk_low", metric="disk_percent", threshold=85.0),
        )
        assert _rejected(bad), bad.text

    def test_memory_usage_is_container_only(self, alert_client):
        ok = alert_client.post(
            "/api/alerts/rules",
            json=_payload(scope="container", metric="memory_usage", threshold=1024.0),
        )
        assert ok.status_code == 200, ok.text

        bad = alert_client.post(
            "/api/alerts/rules", json=_payload(metric="memory_usage", threshold=1024.0)
        )
        assert _rejected(bad), bad.text

    def test_metric_without_threshold_is_refused(self, alert_client):
        payload = _payload()
        del payload["threshold"]
        assert _rejected(alert_client.post("/api/alerts/rules", json=payload))

    def test_metric_without_operator_is_refused(self, alert_client):
        payload = _payload()
        del payload["operator"]
        assert _rejected(alert_client.post("/api/alerts/rules", json=payload))

    def test_not_equal_operator_is_refused(self, alert_client):
        resp = alert_client.post("/api/alerts/rules", json=_payload(operator="!="))
        assert _rejected(resp), resp.text

    @pytest.mark.parametrize("operator", [">=", "<=", ">", "<", "=="])
    def test_supported_operators_save(self, alert_client, operator):
        resp = alert_client.post(
            "/api/alerts/rules", json=_payload(name=f"rule {operator}", operator=operator)
        )
        assert resp.status_code == 200, resp.text

    def test_negative_threshold_is_refused(self, alert_client):
        assert _rejected(alert_client.post("/api/alerts/rules", json=_payload(threshold=-1.0)))

    def test_inverted_clear_threshold_is_refused(self, alert_client):
        bad = alert_client.post(
            "/api/alerts/rules", json=_payload(threshold=90.0, clear_threshold=95.0)
        )
        assert _rejected(bad), bad.text

    def test_correctly_directed_clear_threshold_saves(self, alert_client):
        resp = alert_client.post(
            "/api/alerts/rules", json=_payload(threshold=90.0, clear_threshold=80.0)
        )
        assert resp.status_code == 200, resp.text

    def test_rejection_explains_itself(self, alert_client):
        # A model-level rejection is flattened to "Invalid request data" by the
        # RequestValidationError handler, which is the only text the UI shows.
        resp = alert_client.post(
            "/api/alerts/rules",
            json=_payload(kind="memory_high", metric="memory_percent", threshold=5000.0),
        )

        assert resp.status_code == 400, resp.text
        assert "memory_percent" in resp.json()["detail"]

    def test_system_scope_cannot_be_created(self, alert_client):
        # "system" is storable so the self-diagnostic rule stays editable, but
        # only the scope pattern keeps clients from minting new system rules.
        resp = alert_client.post(
            "/api/alerts/rules",
            json=_payload(scope="system", kind="system_error", metric=None,
                          threshold=None, operator=None),
        )
        assert _rejected(resp), resp.text

    @pytest.mark.parametrize("field", ["threshold", "clear_threshold"])
    def test_boolean_threshold_is_refused(self, alert_client, field):
        # Pydantic coerces JSON true to 1.0 for a float field, so a bool has to
        # be caught before coercion or it silently becomes a real threshold.
        resp = alert_client.post("/api/alerts/rules", json=_payload(**{field: True}))
        assert _rejected(resp), resp.text


@pytest.mark.integration
class TestUpdateValidation:
    """Each case starts from a rule already stored, as a real edit would."""

    def test_partial_threshold_update_is_validated_against_the_stored_metric(
        self, alert_client, _real_db
    ):
        _insert(_real_db, "mem-rule", metric="memory_percent", kind="memory_high", threshold=90.0)

        resp = alert_client.put("/api/alerts/rules/mem-rule", json={"threshold": 200.0})

        assert resp.status_code == 400, resp.text
        assert _stored(_real_db, "mem-rule").threshold == 90.0

    def test_valid_partial_threshold_update_still_succeeds(self, alert_client, _real_db):
        # Without this, an implementation that rejects every partial update
        # would pass every negative case above while being wrong.
        _insert(_real_db, "mem-ok", metric="memory_percent", kind="memory_high", threshold=90.0)

        resp = alert_client.put("/api/alerts/rules/mem-ok", json={"threshold": 75.0})

        assert resp.status_code == 200, resp.text
        assert _stored(_real_db, "mem-ok").threshold == 75.0

    def test_changing_metric_revalidates_the_existing_threshold(self, alert_client, _real_db):
        _insert(_real_db, "cpu-rule", scope="container", metric="cpu_percent", threshold=200.0)

        resp = alert_client.put(
            "/api/alerts/rules/cpu-rule", json={"metric": "memory_percent"}
        )

        assert resp.status_code == 400, resp.text
        assert _stored(_real_db, "cpu-rule").metric == "cpu_percent"

    def test_changing_scope_revalidates_the_existing_metric(self, alert_client, _real_db):
        _insert(
            _real_db, "usage-rule", scope="container", metric="memory_usage", threshold=1024.0
        )

        resp = alert_client.put("/api/alerts/rules/usage-rule", json={"scope": "host"})

        assert resp.status_code == 400, resp.text
        assert _stored(_real_db, "usage-rule").scope == "container"

    def test_correcting_several_fields_in_one_request_succeeds(self, alert_client, _real_db):
        # Proves the merged record is what gets validated: metric, threshold and
        # scope are only jointly valid.
        _insert(_real_db, "fixme", scope="host", metric="cpu_percent", threshold=90.0)

        resp = alert_client.put(
            "/api/alerts/rules/fixme",
            json={"scope": "container", "metric": "cpu_percent", "threshold": 200.0},
        )

        assert resp.status_code == 200, resp.text
        stored = _stored(_real_db, "fixme")
        assert (stored.scope, stored.threshold) == ("container", 200.0)

    def test_explicit_null_scope_is_refused_not_a_500(self, alert_client, _real_db):
        # scope is NOT NULL; setattr(None) reached the DB and surfaced as a 500.
        _insert(_real_db, "event-rule", metric=None, kind="container_stopped", threshold=None,
                operator=None, scope="container")

        resp = alert_client.put("/api/alerts/rules/event-rule", json={"scope": None})

        assert _rejected(resp), resp.text
        assert _stored(_real_db, "event-rule").scope == "container"

    def test_clearing_metric_makes_the_rule_event_driven(self, alert_client, _real_db):
        _insert(_real_db, "to-event", metric="cpu_percent", threshold=90.0)

        resp = alert_client.put("/api/alerts/rules/to-event", json={"metric": None})

        assert resp.status_code == 200, resp.text
        assert _stored(_real_db, "to-event").metric is None

    def test_unrelated_partial_update_of_an_invalid_rule_still_works(
        self, alert_client, _real_db
    ):
        _insert(_real_db, "legacy", scope="container", metric="network_rx_bytes", threshold=1e9)

        resp = alert_client.put("/api/alerts/rules/legacy", json={"name": "renamed"})

        assert resp.status_code == 200, resp.text
        assert _stored(_real_db, "legacy").name == "renamed"

    def test_touching_metric_fields_of_an_invalid_rule_is_refused(self, alert_client, _real_db):
        _insert(_real_db, "legacy2", scope="container", metric="network_rx_bytes", threshold=1e9)

        resp = alert_client.put("/api/alerts/rules/legacy2", json={"threshold": 2e9})

        assert resp.status_code == 400, resp.text

    def test_missing_rule_is_404_not_500(self, alert_client):
        resp = alert_client.put("/api/alerts/rules/nope", json={"threshold": 50.0})
        assert resp.status_code == 404, resp.text

    def test_system_scoped_rule_still_accepts_metric_field_updates(
        self, alert_client, _real_db
    ):
        # The self-diagnostic rule stores scope="system"; validating the merged
        # record must not reject it as an invalid scope.
        _insert(_real_db, "system-rule", scope="system", kind="system_error",
                metric=None, threshold=None, operator=None)

        resp = alert_client.put("/api/alerts/rules/system-rule", json={"threshold": 5.0})

        assert resp.status_code == 200, resp.text

    def test_rejection_explains_itself(self, alert_client, _real_db):
        _insert(_real_db, "detail-rule", metric="memory_percent", kind="memory_high")

        resp = alert_client.put("/api/alerts/rules/detail-rule", json={"threshold": 500.0})

        assert resp.status_code == 400
        assert "memory_percent" in resp.json()["detail"]
