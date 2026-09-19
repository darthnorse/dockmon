"""Integration tests for GET /api/alerts/metrics/capabilities (issue #243).

A host-scope metric rule targeting a host that reports no host metrics can
never fire. The endpoint exposes which hosts can report what, so the rule form
can say so instead of accepting the rule silently.
"""
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

import alerts.api as alerts_api
import main

AGENT_WITH_PROC = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
AGENT_WITHOUT_PROC = "11111111-2222-3333-4444-555555555555"


def _host(host_id, name):
    return types.SimpleNamespace(id=host_id, name=name, connection_type="agent")


@pytest.fixture
def two_agent_hosts(monkeypatch):
    """Two agent hosts, only one of which reports host metrics."""
    hosts = {
        AGENT_WITH_PROC: _host(AGENT_WITH_PROC, "with-proc"),
        AGENT_WITHOUT_PROC: _host(AGENT_WITHOUT_PROC, "without-proc"),
    }
    monkeypatch.setattr(main.monitor, "hosts", hosts)
    return hosts


def _stub_stats_client(monkeypatch, host_stats):
    stub = types.SimpleNamespace(get_host_stats=AsyncMock(return_value=host_stats))
    monkeypatch.setattr(alerts_api, "get_stats_client", lambda: stub)
    return stub


@pytest.mark.integration
class TestMetricCapabilities:
    def test_requires_authentication(self, client):
        assert client.get("/api/alerts/metrics/capabilities").status_code == 401

    def test_capability_follows_observed_samples_not_connection_type(
        self, client, test_api_key_read, two_agent_hosts, monkeypatch
    ):
        _stub_stats_client(monkeypatch, {
            AGENT_WITH_PROC: {
                "cpu_percent": 12.0,
                "memory_percent": 44.0,
                "last_update": datetime.now(timezone.utc).isoformat(),
            }
        })

        resp = client.get(
            "/api/alerts/metrics/capabilities",
            headers={"Authorization": f"Bearer {test_api_key_read}"},
        )
        assert resp.status_code == 200

        by_id = {h["host_id"]: h for h in resp.json()["hosts"]}
        assert set(by_id) == {AGENT_WITH_PROC, AGENT_WITHOUT_PROC}
        assert set(by_id[AGENT_WITH_PROC]["metrics"]) == {"cpu_percent", "memory_percent"}
        assert by_id[AGENT_WITHOUT_PROC]["metrics"] == []
        assert by_id[AGENT_WITHOUT_PROC]["host_name"] == "without-proc"

    def test_reports_known_host_metrics(
        self, client, test_api_key_read, two_agent_hosts, monkeypatch
    ):
        _stub_stats_client(monkeypatch, {})

        resp = client.get(
            "/api/alerts/metrics/capabilities",
            headers={"Authorization": f"Bearer {test_api_key_read}"},
        )
        assert resp.status_code == 200
        assert set(resp.json()["host_metrics"]) == {"cpu_percent", "memory_percent", "disk_percent"}

    def test_stats_service_failure_degrades_to_no_capability(
        self, client, test_api_key_read, two_agent_hosts, monkeypatch
    ):
        stub = types.SimpleNamespace(
            get_host_stats=AsyncMock(side_effect=RuntimeError("stats-service down"))
        )
        monkeypatch.setattr(alerts_api, "get_stats_client", lambda: stub)

        resp = client.get(
            "/api/alerts/metrics/capabilities",
            headers={"Authorization": f"Bearer {test_api_key_read}"},
        )
        assert resp.status_code == 200
        assert all(h["metrics"] == [] for h in resp.json()["hosts"])
