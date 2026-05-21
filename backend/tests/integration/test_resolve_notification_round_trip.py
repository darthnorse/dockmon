"""Integration tests for the alert resolve path (#189).

Routes under test:
  POST   /api/alerts/rules          create_alert_rule_v2
  GET    /api/alerts/rules          get_alert_rules_v2  (returns all rules)
  PUT    /api/alerts/rules/{id}     update_alert_rule_v2
  POST   /api/alerts/{id}/resolve   resolve_alert

Fixtures used:
  client       - shared FastAPI TestClient (conftest.py, auth bypass via get_current_user)
  monkeypatch  - provided by pytest

Auth handling:
  The alert endpoints use require_capability("alerts.manage" / "alerts.view"),
  which is resolved via get_current_user_or_api_key (from auth.api_key_auth).
  We override both that dependency and the capability check (same pattern used by
  tests/integration/deployment_tests/test_validate_ports_route.py::authed_client).

Database:
  We replace monitor.db with a real DatabaseManager backed by a temp SQLite file
  so the test exercises the full SQL path without touching production state.
"""

from datetime import datetime, timezone

import pytest
import database as database_module
from database import AlertV2, DatabaseManager
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def _real_db(tmp_path):
    """Fresh DatabaseManager backed by a temp SQLite file."""
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
    """
    TestClient with:
    - get_current_user_or_api_key overridden (satisfies require_capability dependency)
    - check_auth_capability monkeypatched to always return True
    - monitor.db replaced with a real temp-SQLite DatabaseManager
    - monitor.event_logger replaced with a no-op mock
    """
    import main
    from auth.api_key_auth import get_current_user_or_api_key

    async def _mock_user():
        return {
            "username": "test_user",
            "user_id": 1,
            "auth_type": "session",
        }

    main.app.dependency_overrides[get_current_user_or_api_key] = _mock_user
    monkeypatch.setattr("auth.api_key_auth.check_auth_capability", lambda user, cap: True)

    # Replace monitor.db with real DB so SQL round-trips work end-to-end
    monkeypatch.setattr(main.monitor, "db", _real_db)

    # Replace event_logger with a no-op mock to avoid side-effects
    mock_event_logger = MagicMock()
    monkeypatch.setattr(main.monitor, "event_logger", mock_event_logger)

    yield client

    main.app.dependency_overrides.pop(get_current_user_or_api_key, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_rule(rules_list, rule_id):
    """Return the rule dict matching rule_id from a GET /api/alerts/rules response."""
    for rule in rules_list:
        if rule["id"] == rule_id:
            return rule
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_rule_with_notify_on_resolve_true_persists(alert_client):
    """POST a rule with notify_on_resolve=True then GET it back via bulk list."""
    payload = {
        "name": "Test Resolve Notification",
        "scope": "container",
        "kind": "container_stopped",
        "severity": "warning",
        "notify_on_resolve": True,
    }

    create_resp = alert_client.post("/api/alerts/rules", json=payload)
    assert create_resp.status_code == 200, create_resp.text
    rule_id = create_resp.json()["id"]

    get_resp = alert_client.get("/api/alerts/rules")
    assert get_resp.status_code == 200, get_resp.text
    rule = _find_rule(get_resp.json()["rules"], rule_id)
    assert rule is not None, f"Rule {rule_id} not found in GET response"
    assert rule["notify_on_resolve"] is True


def test_create_rule_with_notify_on_resolve_false_persists(alert_client):
    """POST a rule with notify_on_resolve=False (explicit) then verify GET."""
    payload = {
        "name": "No Resolve Notification",
        "scope": "container",
        "kind": "container_stopped",
        "severity": "warning",
        "notify_on_resolve": False,
    }

    create_resp = alert_client.post("/api/alerts/rules", json=payload)
    assert create_resp.status_code == 200, create_resp.text
    rule_id = create_resp.json()["id"]

    get_resp = alert_client.get("/api/alerts/rules")
    assert get_resp.status_code == 200
    rule = _find_rule(get_resp.json()["rules"], rule_id)
    assert rule is not None
    assert rule["notify_on_resolve"] is False


def test_create_rule_default_notify_on_resolve_is_false(alert_client):
    """POST a rule without notify_on_resolve; GET should return False (default)."""
    payload = {
        "name": "Default Resolve Flag",
        "scope": "container",
        "kind": "container_stopped",
        "severity": "warning",
    }

    create_resp = alert_client.post("/api/alerts/rules", json=payload)
    assert create_resp.status_code == 200, create_resp.text
    rule_id = create_resp.json()["id"]

    get_resp = alert_client.get("/api/alerts/rules")
    assert get_resp.status_code == 200
    rule = _find_rule(get_resp.json()["rules"], rule_id)
    assert rule is not None
    assert rule["notify_on_resolve"] is False


def test_update_rule_toggles_notify_on_resolve(alert_client):
    """PUT notify_on_resolve=True on an existing rule; GET confirms the change."""
    create_resp = alert_client.post("/api/alerts/rules", json={
        "name": "Toggle Test",
        "scope": "container",
        "kind": "container_stopped",
        "severity": "warning",
        "notify_on_resolve": False,
    })
    assert create_resp.status_code == 200, create_resp.text
    rule_id = create_resp.json()["id"]

    update_resp = alert_client.put(
        f"/api/alerts/rules/{rule_id}",
        json={"notify_on_resolve": True},
    )
    assert update_resp.status_code == 200, update_resp.text

    get_resp = alert_client.get("/api/alerts/rules")
    assert get_resp.status_code == 200
    rule = _find_rule(get_resp.json()["rules"], rule_id)
    assert rule is not None
    assert rule["notify_on_resolve"] is True


def test_update_rule_toggles_notify_on_resolve_back_to_false(alert_client):
    """PUT notify_on_resolve=False after it was True; GET confirms the change."""
    create_resp = alert_client.post("/api/alerts/rules", json={
        "name": "Toggle Back Test",
        "scope": "container",
        "kind": "container_stopped",
        "severity": "warning",
        "notify_on_resolve": True,
    })
    assert create_resp.status_code == 200, create_resp.text
    rule_id = create_resp.json()["id"]

    update_resp = alert_client.put(
        f"/api/alerts/rules/{rule_id}",
        json={"notify_on_resolve": False},
    )
    assert update_resp.status_code == 200, update_resp.text

    get_resp = alert_client.get("/api/alerts/rules")
    assert get_resp.status_code == 200
    rule = _find_rule(get_resp.json()["rules"], rule_id)
    assert rule is not None
    assert rule["notify_on_resolve"] is False


def test_manual_resolve_endpoint_returns_200_not_500(alert_client, _real_db):
    """POST /api/alerts/{id}/resolve must succeed end-to-end including audit logging.

    Regression for: TypeError: 'SecurityAuditLogger' object is not callable
    (alerts/api.py:221 was invoking the SecurityAuditLogger instance as if it
    were a function; the instance has no __call__).
    """
    now = datetime.now(timezone.utc)
    with _real_db.get_session() as session:
        session.add(AlertV2(
            id="alert-resolve-endpoint-1",
            dedup_key="container_stopped|container:h:c1",
            scope_type="container",
            scope_id="h:c1",
            kind="container_stopped",
            severity="warning",
            state="open",
            title="Container stopped",
            message="c1 stopped",
            first_seen=now,
            last_seen=now,
            occurrences=1,
        ))
        session.commit()

    resp = alert_client.post(
        "/api/alerts/alert-resolve-endpoint-1/resolve",
        json={"reason": "Manually resolved"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "resolved"
    assert body["resolved_reason"] == "Manually resolved"
