"""disk_percent gains a producer (issue #243, Fix D).

The rule form has offered "Low Disk Space" (metric disk_percent, >=) for a
long time with nothing serving it. Once hosts report disk, stored rules must
work unchanged, and a host whose sample omits disk must be skipped rather than
evaluated as an empty disk - a plain zero would look exactly like a healthy
host, which is the failure this whole issue is about.
"""
import json
import logging
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

import database as database_module
from alerts.capabilities import HOST_METRIC_FIELDS, host_metric_capabilities
from alerts.evaluation_service import AlertEvaluationService
from alerts.metrics import (
    PENDING_METRICS_BY_SCOPE,
    PRODUCED_METRICS_BY_SCOPE,
    is_produced,
    validate_metric_fields,
)
from database import AlertRuleV2, DatabaseManager

REPORTING_HOST = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
SILENT_HOST = "11111111-2222-3333-4444-555555555555"


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


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _host(host_id, name, connection_type="agent", url="agent://"):
    return types.SimpleNamespace(
        id=host_id, name=name, connection_type=connection_type, status="online", url=url
    )


def _service(db, hosts, host_stats):
    monitor = types.SimpleNamespace(
        hosts={h.id: h for h in hosts},
        get_last_containers=lambda: [],
        get_containers=AsyncMock(return_value=[]),
    )
    stats_client = types.SimpleNamespace(
        get_host_stats=AsyncMock(return_value=host_stats),
        get_container_stats=AsyncMock(return_value={}),
    )
    service = AlertEvaluationService(db=db, monitor=monitor, stats_client=stats_client)
    service._handle_alert_notification = AsyncMock()
    return service


def _add_production_disk_rule(db, threshold=80.0, occurrences=1):
    """The shape of the user's own long-inert rule, stored as the API stored it."""
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="host-low-disk",
            name="Host Low Disk Space",
            kind="disk_low",
            enabled=True,
            scope="host",
            metric="disk_percent",
            operator=">=",
            threshold=threshold,
            occurrences=occurrences,
            severity="warning",
            host_selector_json=json.dumps({"include_all": True}),
        ))
        session.commit()


def _sample(disk_percent=None, **extra):
    stats = {"cpu_percent": 5.0, "memory_percent": 40.0, "last_update": _now_iso()}
    if disk_percent is not None:
        stats.update({
            "disk_percent": disk_percent,
            "disk_used_bytes": 53_000_000_000,
            "disk_available_bytes": 44_000_000_000,
            "disk_total_bytes": 103_000_000_000,
            "disk_source": "/var/lib/docker",
        })
    stats.update(extra)
    return stats


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


# --- registry ---

def test_disk_percent_is_a_produced_host_metric():
    assert "disk_percent" in PRODUCED_METRICS_BY_SCOPE["host"]
    assert "disk_percent" not in PENDING_METRICS_BY_SCOPE["host"]
    assert is_produced("host", "disk_percent")
    assert not is_produced("container", "disk_percent")


def test_capability_endpoint_advertises_disk_percent():
    assert "disk_percent" in HOST_METRIC_FIELDS


# No migration: the stored rule validates exactly as written.
def test_stored_disk_rule_validates_unchanged():
    validate_metric_fields("host", "disk_percent", 80.0, None, ">=")
    validate_metric_fields("host", "disk_percent", 85.0, 75.0, ">=")
    with pytest.raises(ValueError):
        validate_metric_fields("host", "disk_percent", 101.0, None, ">=")


# --- evaluation ---

async def test_production_rule_fires_at_85(db):
    _add_production_disk_rule(db, threshold=80.0)
    service = _service(db, [_host(REPORTING_HOST, "agent-box")],
                       {REPORTING_HOST: _sample(disk_percent=85.0)})

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 1


async def test_production_rule_does_not_fire_at_70(db):
    _add_production_disk_rule(db, threshold=80.0)
    service = _service(db, [_host(REPORTING_HOST, "agent-box")],
                       {REPORTING_HOST: _sample(disk_percent=70.0)})

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 0


# The fail-open this design exists to prevent: a host whose sample carries
# no disk_percent must be skipped, never evaluated as 0%.
@pytest.mark.parametrize("operator,threshold", [("<=", 10.0), ("<", 50.0)])
async def test_host_without_disk_is_skipped_not_evaluated_as_zero(db, operator, threshold):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="disk-low-side", name="disk under", kind="disk_low", enabled=True,
            scope="host", metric="disk_percent", operator=operator, threshold=threshold,
            occurrences=1, severity="warning", host_selector_json=json.dumps({"include_all": True}),
        ))
        session.commit()
    service = _service(db, [_host(REPORTING_HOST, "old-agent")],
                       {REPORTING_HOST: _sample()})

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 0


async def test_cpu_and_memory_still_evaluate_when_disk_is_absent(db):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="cpu-rule", name="cpu", kind="cpu_high", enabled=True, scope="host",
            metric="cpu_percent", operator=">=", threshold=80.0, occurrences=1,
            severity="warning", host_selector_json=json.dumps({"include_all": True}),
        ))
        session.commit()
    service = _service(db, [_host(REPORTING_HOST, "old-agent")],
                       {REPORTING_HOST: _sample(cpu_percent=95.0)})

    await _evaluate(service)

    assert service._handle_alert_notification.await_count == 1


# --- capability: two hosts in one payload ---

def test_capabilities_distinguish_disk_reporting_hosts():
    stats = {
        REPORTING_HOST: _sample(disk_percent=54.7),
        SILENT_HOST: _sample(),
    }
    caps = host_metric_capabilities(stats, [REPORTING_HOST, SILENT_HOST])

    assert "disk_percent" in caps[REPORTING_HOST]
    assert "disk_percent" not in caps[SILENT_HOST]
    assert "cpu_percent" in caps[SILENT_HOST]


# --- Fix C's warning stops naming disk_percent: the signal this phase worked ---

async def test_no_dead_metric_warning_for_disk_percent(db, caplog):
    _add_production_disk_rule(db)
    service = _service(db, [_host(REPORTING_HOST, "agent-box")],
                       {REPORTING_HOST: _sample(disk_percent=10.0)})

    with caplog.at_level(logging.WARNING):
        await service._evaluate_all_rules()

    dead = [r for r in caplog.records if "can never fire" in r.message]
    assert dead == []


# The remedy for a silent host must name the mount disk actually needs.
async def test_missing_metrics_remedy_names_hostfs_for_disk_rules(db, caplog):
    _add_production_disk_rule(db)
    service = _service(db, [_host(SILENT_HOST, "no-mounts")], {})

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    records = [r for r in caplog.records if "no-mounts" in r.message]
    assert len(records) == 1
    assert "/hostfs" in records[0].message
    assert "/host/proc" in records[0].message


# --- a host that reports CPU/memory but not disk must say so, once ---

async def test_host_with_cpu_but_no_disk_warns_once_naming_hostfs(db, caplog):
    _add_production_disk_rule(db)
    service = _service(db, [_host(REPORTING_HOST, "no-hostfs")],
                       {REPORTING_HOST: _sample()})

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)
        first = [r for r in caplog.records if "no-hostfs" in r.message]
        await _evaluate(service)
        second = [r for r in caplog.records if "no-hostfs" in r.message]

    assert len(first) == 1
    assert "disk_percent" in first[0].message
    assert "-v /:/hostfs:ro" in first[0].message
    assert "/host/proc" not in first[0].message, "the host already has /host/proc; only the missing mount belongs in the remedy"
    assert len(second) == 1, "warning must be throttled to once per host per metric"


async def test_missing_metric_warning_clears_when_the_metric_arrives(db, caplog):
    _add_production_disk_rule(db)
    service = _service(db, [_host(REPORTING_HOST, "late-hostfs")],
                       {REPORTING_HOST: _sample()})

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)
        service.stats_client.get_host_stats = AsyncMock(
            return_value={REPORTING_HOST: _sample(disk_percent=10.0)})
        await _evaluate(service)
        service.stats_client.get_host_stats = AsyncMock(
            return_value={REPORTING_HOST: _sample()})
        await _evaluate(service)

    assert len([r for r in caplog.records if "late-hostfs" in r.message]) == 2


# An mTLS host can never report disk; the warning must say that rather than
# offer a mount that does not apply.
async def test_missing_metric_warning_for_docker_host_offers_no_mount(db, caplog):
    _add_production_disk_rule(db)
    service = _service(db, [_host(SILENT_HOST, "docker-box", connection_type="remote", url="tcp://10.0.0.5:2376")],
                       {SILENT_HOST: _sample()})

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    records = [r for r in caplog.records if "docker-box" in r.message]
    assert len(records) == 1
    assert "hostfs" not in records[0].message
    assert "cannot" in records[0].message


async def test_no_missing_metric_warning_without_a_matching_rule(db, caplog):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="cpu-rule", name="cpu", kind="cpu_high", enabled=True, scope="host",
            metric="cpu_percent", operator=">=", threshold=80.0, occurrences=1,
            severity="warning", host_selector_json=json.dumps({"include_all": True}),
        ))
        session.commit()
    service = _service(db, [_host(REPORTING_HOST, "no-hostfs")],
                       {REPORTING_HOST: _sample()})

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    assert not [r for r in caplog.records if "no-hostfs" in r.message]


async def test_missing_metric_warning_respects_the_rule_selector(db, caplog):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="disk-other", name="disk elsewhere", kind="disk_low", enabled=True,
            scope="host", metric="disk_percent", operator=">=", threshold=80.0,
            occurrences=1, severity="warning",
            host_selector_json=json.dumps({"include": [SILENT_HOST]}),
        ))
        session.commit()
    service = _service(db, [_host(REPORTING_HOST, "untargeted")],
                       {REPORTING_HOST: _sample()})

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    assert not [r for r in caplog.records if "untargeted" in r.message]


# The local socket host is "remote" in memory like an mTLS host; only its URL
# tells them apart, and only the local one has a mount to offer.
async def test_missing_metric_warning_for_local_host_names_the_compose_mount(db, caplog):
    _add_production_disk_rule(db)
    service = _service(
        db,
        [_host(SILENT_HOST, "Local Docker", connection_type="remote", url="unix:///var/run/docker.sock")],
        {SILENT_HOST: _sample()},
    )

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    records = [r for r in caplog.records if "Local Docker" in r.message]
    assert len(records) == 1
    assert "docker-compose.yml" in records[0].message
    assert "/hostfs" in records[0].message


# The remedy is keyed by the missing metric, so the local host is never told
# to mount the host root for a metric /host/proc serves.
async def test_missing_metric_remedy_for_local_host_follows_the_metric(db, caplog):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="cpu-rule", name="cpu", kind="cpu_high", enabled=True, scope="host",
            metric="cpu_percent", operator=">=", threshold=80.0, occurrences=1,
            severity="warning", host_selector_json=json.dumps({"include_all": True}),
        ))
        session.commit()
    sample = _sample()
    del sample["cpu_percent"]
    service = _service(
        db,
        [_host(SILENT_HOST, "Local Docker", connection_type="remote", url="unix:///var/run/docker.sock")],
        {SILENT_HOST: sample},
    )

    with caplog.at_level(logging.WARNING):
        await _evaluate(service)

    records = [r for r in caplog.records if "Local Docker" in r.message]
    assert len(records) == 1
    assert "/host/proc" in records[0].message
    assert "hostfs" not in records[0].message
