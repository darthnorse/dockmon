"""Metric alerts on agent-connected hosts (issue #243).

Host-scope CPU/memory rules never fired for agent hosts because host metrics
only ever reached the UI pipeline, never the stats-service cache the evaluator
reads. These tests cover the evaluator half: agent host samples evaluate like
any other, stale samples are skipped instead of alerting on old data, and a
host with no metrics at all is reported instead of silently skipped.
"""
import logging
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

import database as database_module
from alerts.capabilities import (
    HOST_METRIC_FIELDS,
    host_metric_capabilities,
    parse_stats_timestamp,
)
from alerts.evaluation_service import STATS_MAX_AGE_SECONDS, AlertEvaluationService
from database import AlertRuleV2, DatabaseManager

AGENT_HOST = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
MTLS_HOST = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database_module._database_manager_instance = None
    db_manager = DatabaseManager(db_path=db_path)
    try:
        yield db_manager
    finally:
        if hasattr(db_manager, "engine"):
            db_manager.engine.dispose()
        database_module._database_manager_instance = None


def _now_iso(offset_seconds: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)).isoformat()


def _host(host_id, name, connection_type="agent", status="online"):
    return types.SimpleNamespace(
        id=host_id, name=name, connection_type=connection_type, status=status
    )


def _service(db, hosts, host_stats=None, container_stats=None):
    monitor = types.SimpleNamespace(
        hosts={h.id: h for h in hosts},
        get_last_containers=lambda: [],
        get_containers=AsyncMock(return_value=[]),
    )
    stats_client = types.SimpleNamespace(
        get_host_stats=AsyncMock(return_value=host_stats or {}),
        get_container_stats=AsyncMock(return_value=container_stats or {}),
    )
    service = AlertEvaluationService(db=db, monitor=monitor, stats_client=stats_client)
    service._handle_alert_notification = AsyncMock()
    return service


def _add_host_rule(db, metric="cpu_percent", threshold=80.0, rule_id="rule-1"):
    with db.get_session() as session:
        rule = AlertRuleV2(
            id=rule_id,
            name=f"{metric} high",
            kind=f"{metric}_high",
            enabled=True,
            scope="host",
            metric=metric,
            operator=">=",
            threshold=threshold,
            occurrences=1,
            severity="warning",
        )
        session.add(rule)
        session.commit()
    return rule_id


async def _evaluate(service):
    with service.db.get_session() as session:
        rules = session.query(AlertRuleV2).filter(
            AlertRuleV2.enabled == True,  # noqa: E712
            AlertRuleV2.metric != None,   # noqa: E711
        ).all()
        rules_by_metric = {}
        for rule in rules:
            rules_by_metric.setdefault(rule.metric, []).append(rule)
        session.expunge_all()
    await service._evaluate_host_metrics(rules_by_metric)
    return rules_by_metric


# --- the reported bug: an agent host's host metrics must evaluate ---

async def test_agent_host_cpu_rule_fires(db):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(
        db,
        [_host(AGENT_HOST, "agent-box")],
        host_stats={AGENT_HOST: {
            "cpu_percent": 95.0,
            "memory_percent": 40.0,
            "last_update": _now_iso(),
        }},
    )

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 1


async def test_agent_host_memory_rule_fires(db):
    _add_host_rule(db, metric="memory_percent", threshold=90.0)
    service = _service(
        db,
        [_host(AGENT_HOST, "agent-box")],
        host_stats={AGENT_HOST: {
            "cpu_percent": 5.0,
            "memory_percent": 97.5,
            "last_update": _now_iso(),
        }},
    )

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 1


# --- freshness ---

async def test_stale_host_sample_is_not_evaluated(db):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(
        db,
        [_host(AGENT_HOST, "agent-box")],
        host_stats={AGENT_HOST: {
            "cpu_percent": 99.0,
            "last_update": _now_iso(STATS_MAX_AGE_SECONDS + 30),
        }},
    )

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 0


async def test_sample_just_inside_the_window_is_evaluated(db):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(
        db,
        [_host(AGENT_HOST, "agent-box")],
        host_stats={AGENT_HOST: {
            "cpu_percent": 99.0,
            "last_update": _now_iso(STATS_MAX_AGE_SECONDS - 5),
        }},
    )

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 1


# Go marshals time.Time as RFC3339 with up to nanosecond precision. Assert the
# parse itself: freshness fails open, so an evaluator-level assertion alone
# would pass even with parsing broken.
@pytest.mark.parametrize("timestamp,expected", [
    ("2999-01-01T00:00:00.123456789Z", datetime(2999, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc)),
    ("2999-01-01T00:00:00.123456Z", datetime(2999, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc)),
    ("2999-01-01T00:00:00Z", datetime(2999, 1, 1, tzinfo=timezone.utc)),
    ("2999-01-01T00:00:00+00:00", datetime(2999, 1, 1, tzinfo=timezone.utc)),
    ("2999-01-01T01:00:00+01:00", datetime(2999, 1, 1, tzinfo=timezone.utc)),
    ("2999-01-01T00:00:00", datetime(2999, 1, 1, tzinfo=timezone.utc)),
])
def test_rfc3339_timestamp_variants_parse(timestamp, expected):
    assert parse_stats_timestamp(timestamp) == expected


@pytest.mark.parametrize("timestamp", ["not-a-time", "", None, 12345])
def test_unparseable_timestamps_return_none(timestamp):
    assert parse_stats_timestamp(timestamp) is None


# Go's zero time means "never reported". In a positive-offset zone it overflows
# on UTC conversion; returning None there would fail open and evaluate it, while
# the same instant written as Z ages out and is skipped - the freshness gate
# must not depend on how the timestamp was spelled.
@pytest.mark.parametrize("zero_time", [
    "0001-01-01T00:00:00Z",
    "0001-01-01T00:00:00+01:00",
    "0001-01-01T00:00:00-01:00",
])
async def test_go_zero_time_is_stale_in_every_offset(db, zero_time):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(
        db,
        [_host(AGENT_HOST, "agent-box")],
        host_stats={AGENT_HOST: {"cpu_percent": 99.0, "last_update": zero_time}},
    )

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 0


async def test_fresh_timestamp_evaluates_without_a_parse_warning(db, caplog):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(
        db,
        [_host(AGENT_HOST, "agent-box")],
        host_stats={AGENT_HOST: {
            "cpu_percent": 99.0,
            "last_update": "2999-01-01T00:00:00.123456789Z",
        }},
    )

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    assert service._handle_alert_notification.await_count == 1
    assert not [r for r in caplog.records if "last_update" in r.message]


# Fail open: a missing or unreadable timestamp must not silence alerting, which
# is the failure mode this whole issue is about.
async def test_missing_last_update_still_evaluates(db):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(
        db,
        [_host(AGENT_HOST, "agent-box")],
        host_stats={AGENT_HOST: {"cpu_percent": 99.0}},
    )

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 1


async def test_unparseable_last_update_evaluates_and_warns(db, caplog):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(
        db,
        [_host(AGENT_HOST, "agent-box")],
        host_stats={AGENT_HOST: {"cpu_percent": 99.0, "last_update": "not-a-time"}},
    )

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    assert service._handle_alert_notification.await_count == 1
    assert any("last_update" in r.message for r in caplog.records)


async def test_stale_container_sample_is_not_evaluated(db):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="rule-c", name="container cpu", kind="cpu_high", enabled=True,
            scope="container", metric="cpu_percent", operator=">=", threshold=50.0,
            occurrences=1, severity="warning",
        ))
        session.commit()

    container = types.SimpleNamespace(
        host_id=AGENT_HOST, short_id="abc123abc123", name="nginx",
        host_name="agent-box", desired_state="running", labels={}, tags=[],
    )
    service = _service(db, [_host(AGENT_HOST, "agent-box")])
    service.monitor.get_last_containers = lambda: [container]
    service.stats_client.get_container_stats = AsyncMock(return_value={
        f"{AGENT_HOST}:abc123abc123": {
            "cpu_percent": 99.0,
            "last_update": _now_iso(STATS_MAX_AGE_SECONDS + 30),
        }
    })

    with db.get_session() as session:
        rules = session.query(AlertRuleV2).all()
        rules_by_metric = {"cpu_percent": list(rules)}
        session.expunge_all()
    await service._evaluate_container_metrics(rules_by_metric)

    assert service._handle_alert_notification.await_count == 0


# --- visibility: a host with no metrics must not fail silently ---

async def test_host_without_stats_logs_warning_once_per_interval(db, caplog):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(
        db,
        [_host(AGENT_HOST, "no-proc-mount"), _host(MTLS_HOST, "docker-box", "tcp")],
        host_stats={MTLS_HOST: {"cpu_percent": 10.0, "last_update": _now_iso()}},
    )

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)
        first = [r for r in caplog.records if "no-proc-mount" in r.message]
        await _evaluate(service)
        second = [r for r in caplog.records if "no-proc-mount" in r.message]

    assert len(first) == 1, "expected a warning naming the host with no metrics"
    assert len(second) == 1, "warning must be throttled to once per host per interval"


# An offline host has an obvious reason to report nothing; warning about it
# would bury the case an operator can actually act on.
async def test_offline_host_is_not_reported(db, caplog):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(db, [_host(AGENT_HOST, "gone-away", status="offline")])

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    assert not [r for r in caplog.records if "gone-away" in r.message]


# The /host/proc remedy is agent-specific; an mTLS host reporting nothing has a
# different cause, and the advice would send the operator down a dead end.
async def test_remedy_only_offered_for_agent_hosts(db, caplog):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(db, [_host(MTLS_HOST, "docker-box", connection_type="tcp")])

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    records = [r for r in caplog.records if "docker-box" in r.message]
    assert len(records) == 1
    assert "/host/proc" not in records[0].message


async def test_no_warning_when_no_host_rules_match(db):
    service = _service(
        db,
        [_host(AGENT_HOST, "no-proc-mount")],
        host_stats={},
    )

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 0


# --- capability derivation ---

def test_capabilities_come_from_observed_fresh_fields():
    """Two agent hosts, same connection type: only the one whose samples
    actually arrive reports metrics."""
    stats = {
        AGENT_HOST: {
            "cpu_percent": 12.0,
            "memory_percent": 55.0,
            "disk_percent": 54.7,
            "last_update": _now_iso(),
        },
    }
    caps = host_metric_capabilities(stats, [AGENT_HOST, MTLS_HOST])

    assert set(caps[AGENT_HOST]) == set(HOST_METRIC_FIELDS)
    assert caps[MTLS_HOST] == []


def test_capabilities_ignore_stale_samples():
    stats = {AGENT_HOST: {
        "cpu_percent": 12.0,
        "memory_percent": 55.0,
        "last_update": _now_iso(STATS_MAX_AGE_SECONDS + 30),
    }}

    assert host_metric_capabilities(stats, [AGENT_HOST])[AGENT_HOST] == []


def test_capabilities_report_only_fields_present():
    stats = {AGENT_HOST: {"cpu_percent": 12.0, "last_update": _now_iso()}}

    assert host_metric_capabilities(stats, [AGENT_HOST])[AGENT_HOST] == ["cpu_percent"]


# The throttle key must survive a rename, or a renamed host both leaks its old
# entry and re-warns under its new name.
async def test_bad_timestamp_throttle_is_keyed_by_host_id(db, caplog):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    host = _host(AGENT_HOST, "before-rename")
    service = _service(
        db, [host],
        host_stats={AGENT_HOST: {"cpu_percent": 99.0, "last_update": "not-a-time"}},
    )

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)
        host.name = "after-rename"
        await _evaluate(service)

    warnings = [r for r in caplog.records if "Unreadable last_update" in r.message]
    assert len(warnings) == 1
    assert service._bad_timestamp_reported == {f"host:{AGENT_HOST}"}


async def test_throttle_entries_are_pruned_for_departed_hosts(db):
    _add_host_rule(db, metric="cpu_percent", threshold=80.0)
    service = _service(
        db, [_host(AGENT_HOST, "agent-box")],
        host_stats={AGENT_HOST: {"cpu_percent": 99.0, "last_update": "not-a-time"}},
    )

    await _evaluate(service)
    assert service._bad_timestamp_reported

    service.monitor.hosts = {}
    service._hosts_missing_metrics_reported.add(AGENT_HOST)
    await _evaluate(service)

    assert service._bad_timestamp_reported == set()
    assert service._hosts_missing_metrics_reported == set()
