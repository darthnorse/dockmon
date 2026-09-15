"""Rules on metrics nothing produces must not evaluate in silence (issue #243, Fix C).

Validation stops new dead rules, but rows already stored keep sitting there
enabled and never firing - the same silence the whole issue is about. The
evaluator names them once per distinct set of affected rules.

Rows here are inserted directly rather than through the API, because that is
what an upgraded install looks like: rules the old API accepted.
"""
import logging
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import database as database_module
from alerts.evaluation_service import AlertEvaluationService
from database import AlertRuleV2, DatabaseManager

HOST_A = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
CONTAINER_ID = "67c5d2141338"

DROPPED_METRICS = (
    "network_rx_bytes",
    "network_tx_bytes",
    "block_read_bytes",
    "block_write_bytes",
)


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


def _host(host_id, name):
    return types.SimpleNamespace(
        id=host_id, name=name, connection_type="agent", status="online"
    )


def _container(cid, name, host_id):
    return types.SimpleNamespace(
        id=cid, short_id=cid, name=name, host_id=host_id, host_name="agent-host",
        tags=[], labels={}, desired_state="running", state="running",
    )


def _service(db, host_stats=None, container_stats=None, containers=None):
    monitor = types.SimpleNamespace(
        hosts={HOST_A: _host(HOST_A, "agent-host")},
        get_last_containers=lambda: containers or [],
        get_containers=AsyncMock(return_value=containers or []),
    )
    stats_client = types.SimpleNamespace(
        get_host_stats=AsyncMock(return_value=host_stats or {}),
        get_container_stats=AsyncMock(return_value=container_stats or {}),
    )
    service = AlertEvaluationService(db=db, monitor=monitor, stats_client=stats_client)
    service._handle_alert_notification = AsyncMock()
    return service


def _add_rule(db, rule_id, metric, scope="container", enabled=True, name=None):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id=rule_id, name=name or rule_id, kind="cpu_high", enabled=enabled,
            scope=scope, metric=metric, operator=">=", threshold=1.0,
            occurrences=1, severity="warning",
        ))
        session.commit()


def _set_enabled(db, rule_id, enabled):
    with db.get_session() as session:
        rule = session.query(AlertRuleV2).filter(AlertRuleV2.id == rule_id).first()
        rule.enabled = enabled
        session.commit()


def _dead_warnings(caplog):
    return [
        r.message for r in caplog.records
        if r.levelno == logging.WARNING and "never fire" in r.message
    ]


@pytest.mark.asyncio
class TestDroppedMetricsNoLongerResolve:
    @pytest.mark.parametrize("metric", DROPPED_METRICS)
    async def test_dropped_metric_does_not_evaluate_even_when_present(self, db, metric, caplog):
        """The payload field exists under a different name; the rule stays dead."""
        _add_rule(db, f"rule-{metric}", metric)
        container = _container(CONTAINER_ID, "web", HOST_A)
        service = _service(
            db,
            container_stats={f"{HOST_A}:{CONTAINER_ID}": {
                metric: 10 ** 12,
                "network_rx": 10 ** 12, "network_tx": 10 ** 12,
                "disk_read": 10 ** 12, "disk_write": 10 ** 12,
                "last_update": _now_iso(),
            }},
            containers=[container],
        )
        service.engine.evaluate_metric = MagicMock(return_value=[])

        await service._evaluate_all_rules()

        assert service.engine.evaluate_metric.call_count == 0

    async def test_live_container_metrics_still_evaluate(self, db):
        _add_rule(db, "cpu-rule", "cpu_percent")
        container = _container(CONTAINER_ID, "web", HOST_A)
        service = _service(
            db,
            container_stats={f"{HOST_A}:{CONTAINER_ID}": {
                "cpu_percent": 95.0, "memory_percent": 80.0,
                "memory_usage": 512, "memory_limit": 1024,
                "last_update": _now_iso(),
            }},
            containers=[container],
        )
        service.engine.evaluate_metric = MagicMock(return_value=[])

        await service._evaluate_all_rules()

        evaluated = {c.args[0] for c in service.engine.evaluate_metric.call_args_list}
        assert "cpu_percent" in evaluated

    async def test_host_metrics_still_evaluate(self, db):
        _add_rule(db, "host-cpu", "cpu_percent", scope="host")
        service = _service(
            db,
            host_stats={HOST_A: {
                "cpu_percent": 95.0, "memory_percent": 80.0, "last_update": _now_iso(),
            }},
        )
        service.engine.evaluate_metric = MagicMock(return_value=[])

        await service._evaluate_all_rules()

        evaluated = {c.args[0] for c in service.engine.evaluate_metric.call_args_list}
        assert "cpu_percent" in evaluated


@pytest.mark.asyncio
class TestDeadRuleWarning:
    async def test_warns_naming_the_rule(self, db, caplog):
        _add_rule(db, "legacy-1", "network_rx_bytes", name="Ingress watch")
        service = _service(db)

        with caplog.at_level(logging.WARNING):
            await service._evaluate_all_rules()

        warnings = _dead_warnings(caplog)
        assert len(warnings) == 1
        assert "Ingress watch" in warnings[0]
        assert "network_rx_bytes" in warnings[0]

    async def test_warning_is_throttled_across_cycles(self, db, caplog):
        _add_rule(db, "legacy-1", "network_rx_bytes")
        service = _service(db)

        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                await service._evaluate_all_rules()

        assert len(_dead_warnings(caplog)) == 1

    async def test_a_second_rule_on_the_same_dead_metric_re_warns(self, db, caplog):
        """Throttling on the metric alone would swallow this."""
        _add_rule(db, "legacy-1", "network_rx_bytes")
        service = _service(db)

        with caplog.at_level(logging.WARNING):
            await service._evaluate_all_rules()
            _add_rule(db, "legacy-2", "network_rx_bytes")
            await service._evaluate_all_rules()

        assert len(_dead_warnings(caplog)) == 2

    async def test_disk_percent_is_served_and_not_warned(self, db, caplog):
        """Fix D gave disk_percent a producer; the warning naming it must be gone."""
        _add_rule(db, "disk-rule", "disk_percent", scope="host")
        service = _service(db)

        with caplog.at_level(logging.WARNING):
            await service._evaluate_all_rules()

        assert _dead_warnings(caplog) == []

    async def test_silent_when_every_rule_is_servable(self, db, caplog):
        _add_rule(db, "cpu-rule", "cpu_percent")
        _add_rule(db, "host-mem", "memory_percent", scope="host")
        service = _service(db)

        with caplog.at_level(logging.WARNING):
            await service._evaluate_all_rules()

        assert _dead_warnings(caplog) == []

    async def test_re_enabling_the_last_dead_rule_warns_again(self, db, caplog):
        """Reconciliation must run even on cycles that find no enabled rules.

        _evaluate_all_rules returns early when the query is empty; pruning
        placed after that return would latch the signature forever.
        """
        _add_rule(db, "legacy-1", "network_rx_bytes")
        service = _service(db)

        with caplog.at_level(logging.WARNING):
            await service._evaluate_all_rules()
            _set_enabled(db, "legacy-1", False)
            await service._evaluate_all_rules()
            _set_enabled(db, "legacy-1", True)
            await service._evaluate_all_rules()

        assert len(_dead_warnings(caplog)) == 2

    async def test_throttle_state_does_not_grow_without_bound(self, db):
        _add_rule(db, "legacy-1", "network_rx_bytes")
        service = _service(db)

        await service._evaluate_all_rules()
        with db.get_session() as session:
            session.query(AlertRuleV2).delete()
            session.commit()
        await service._evaluate_all_rules()

        assert service._dead_metric_reported == {}
