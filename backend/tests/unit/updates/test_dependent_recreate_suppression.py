"""A provider's update recreates its dependents; their stops are part of the update, not real stops."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alerts.engine import AlertEngine, EvaluationContext
from database import AlertRuleV2
from docker_monitor.monitor import DockerMonitor
from models.docker_models import Container
from updates.dependency_analyzer import recreated_dependents
from updates.types import UpdateResult
from updates.update_executor import UpdateExecutor
from utils.keys import make_composite_key

HOST = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
OTHER_HOST = "f5cc8d91-318e-4a42-9ebc-bfe584f3a3b0"
PROVIDER_ID = "16678699c163"
PROVIDER_FULL_ID = PROVIDER_ID + "4a7e0fb11255730d62d4f39be4ef58f6f8eaa996a2bf59390412"
DEPENDENT_ID = "6d471d175f43"
NEW_DEPENDENT_ID = "86b009b867ce"
UNRELATED_ID = "aaaaaaaaaaaa"


def make_container(name, short_id, network_mode="bridge", state="running", host_id=HOST):
    return Container(
        id=short_id, short_id=short_id, name=name, state=state, status=state,
        host_id=host_id, host_name="sonarr", image=f"{name}:latest", created="2026-11-09T00:00:00Z",
        network_mode=network_mode,
    )


def provider():
    return make_container("gluetun", PROVIDER_ID)


def dependent(short_id=DEPENDENT_ID, state="running", ref=PROVIDER_FULL_ID):
    return make_container("qbittorrent", short_id, f"container:{ref}", state=state)


def unrelated():
    return make_container("plex", UNRELATED_ID)


class TestRecreatedDependents:
    @pytest.mark.parametrize("ref", ["gluetun", PROVIDER_ID, PROVIDER_FULL_ID])
    def test_matches_the_refs_the_updater_matches(self, ref):
        found = recreated_dependents(provider(), [provider(), dependent(ref=ref), unrelated()])
        assert [c.name for c in found] == ["qbittorrent"]

    @pytest.mark.parametrize("ref", [PROVIDER_ID + "-sidecar", PROVIDER_ID[:8], "gluetun2"])
    def test_a_ref_that_only_starts_like_the_provider_is_not_a_dependent(self, ref):
        assert recreated_dependents(provider(), [provider(), dependent(ref=ref)]) == []

    def test_other_hosts_and_the_provider_itself_are_not_dependents(self):
        same_name_elsewhere = make_container(
            "qbittorrent", DEPENDENT_ID, "container:gluetun", host_id=OTHER_HOST
        )
        self_ref = make_container("gluetun", PROVIDER_ID, "container:gluetun")
        assert recreated_dependents(self_ref, [self_ref, same_name_elsewhere]) == []


def make_record():
    return SimpleNamespace(
        id=1,
        current_image="qmcgaw/gluetun:old",
        latest_image="qmcgaw/gluetun:latest",
        current_digest="sha256:old",
        latest_digest="sha256:new",
        changelog_url=None,
        current_version=None,
        latest_version=None,
    )


def make_executor(discoveries, last=None):
    """Executor whose host discovery returns each list in `discoveries` in turn."""
    with patch("updates.update_executor.UpdateClient"):
        executor = UpdateExecutor(db=MagicMock(), monitor=MagicMock())
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(
        connection_type="agent"
    )
    executor.db.get_session.return_value.__enter__.return_value = session
    executor.event_emitter = AsyncMock()
    executor._get_container_info = AsyncMock(return_value={"name": "gluetun"})
    executor._re_evaluate_alerts_after_update = AsyncMock()
    executor.monitor.get_containers = AsyncMock(side_effect=list(discoveries))
    executor.monitor.get_last_containers.return_value = (
        [provider(), dependent()] if last is None else last
    )
    executor.monitor.alert_evaluation_service.handle_container_event = AsyncMock()
    return executor


async def run_update(executor, during=None, result=None):
    async def execute(*args, **kwargs):
        if during:
            during()
        if isinstance(result, Exception):
            raise result
        return result or UpdateResult.success_result("2d98600a8ce6")

    executor._execute_agent_update = AsyncMock(side_effect=execute)
    with patch("updates.update_executor.update_container_records_after_update"):
        return await executor.update_container(HOST, PROVIDER_ID, make_record())


class TestDependentsMarkedDuringProviderUpdate:
    @pytest.mark.asyncio
    async def test_every_event_of_the_recreate_is_covered(self):
        before = [provider(), dependent(), unrelated()]
        executor = make_executor([before, before])
        seen = {}

        def during():
            seen["old"] = executor.is_container_updating(HOST, DEPENDENT_ID, "qbittorrent")
            seen["new"] = executor.is_container_updating(HOST, NEW_DEPENDENT_ID, "qbittorrent")
            seen["temp"] = executor.is_container_updating(
                HOST, DEPENDENT_ID, "qbittorrent-dockmon-temp-1794266276"
            )
            seen["unrelated"] = executor.is_container_updating(HOST, UNRELATED_ID, "plex")
            seen["other_host"] = executor.is_container_updating(OTHER_HOST, DEPENDENT_ID, "qbittorrent")
            seen["guard"] = make_composite_key(HOST, DEPENDENT_ID) in executor.updating_containers

        assert await run_update(executor, during) is True
        assert seen == {
            "old": True, "new": True, "temp": True,
            "unrelated": False, "other_host": False, "guard": False,
        }
        assert not executor.is_container_updating(HOST, NEW_DEPENDENT_ID, "qbittorrent")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome", [
        UpdateResult.failure_result("health check failed"),
        RuntimeError("agent went away"),
    ])
    async def test_marking_ends_when_the_update_fails(self, outcome):
        before = [provider(), dependent()]
        executor = make_executor([before, before])

        await run_update(executor, result=outcome)

        assert not executor.is_container_updating(HOST, DEPENDENT_ID, "qbittorrent")

    @pytest.mark.asyncio
    async def test_dependents_come_from_a_fresh_discovery_of_the_host(self):
        before = [provider(), dependent()]
        executor = make_executor([before, before])

        def fresh_only(host_id=None):
            assert host_id == HOST
            executor.monitor.invalidate_discovery.assert_called_with(HOST)
            return before

        executor.monitor.get_containers = AsyncMock(side_effect=fresh_only)
        await run_update(executor)

        assert executor.monitor.get_containers.await_count == 2

    @pytest.mark.asyncio
    async def test_invalidation_drops_the_key_get_containers_caches_under(self):
        monitor = DockerMonitor.__new__(DockerMonitor)
        monitor.hosts = {HOST: SimpleNamespace(status="online")}
        monitor.clients = {HOST: object()}
        monitor.restart_attempts = {}
        monitor.discovery = MagicMock()
        monitor.discovery.discover_containers_for_host = AsyncMock(return_value=[])
        monitor.discovery.populate_container_stats = AsyncMock()
        cache = MagicMock()

        await monitor.get_containers(HOST)
        with patch.dict("docker_monitor.monitor.CACHE_REGISTRY", {"discover_containers_for_host": cache}):
            monitor.invalidate_discovery(HOST)

        cached_under = (monitor.discovery,) + monitor.discovery.discover_containers_for_host.await_args.args
        assert cache.invalidate_key.call_args.args == cached_under

    @pytest.mark.asyncio
    async def test_a_host_without_shared_network_containers_is_not_listed(self):
        executor = make_executor([], last=[provider(), unrelated()])

        assert await run_update(executor) is True
        executor.monitor.get_containers.assert_not_awaited()
        executor.monitor.invalidate_discovery.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_failing_snapshot_does_not_stop_the_update(self):
        executor = make_executor([])
        executor.monitor.get_last_containers.side_effect = RuntimeError("monitor not ready")

        assert await run_update(executor) is True
        executor._execute_agent_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_discovery_marks_nothing_and_the_update_still_runs(self):
        executor = make_executor([RuntimeError("host offline"), []])
        assert await run_update(executor) is True
        executor._execute_agent_update.assert_awaited_once()


class TestDependentLeftDownAfterTheUpdate:
    @pytest.mark.asyncio
    async def test_a_dependent_that_did_not_come_back_alerts_as_stopped(self):
        after = [provider(), dependent(NEW_DEPENDENT_ID, state="exited")]
        executor = make_executor([[provider(), dependent()], after])
        evaluate = executor.monitor.alert_evaluation_service.handle_container_event

        async def check_unmarked(**kwargs):
            assert not executor.is_container_updating(HOST, NEW_DEPENDENT_ID, "qbittorrent")

        evaluate.side_effect = check_unmarked
        await run_update(executor)

        evaluate.assert_awaited_once()
        call = evaluate.await_args.kwargs
        assert call["event_type"] == "state_change"
        assert call["container_id"] == NEW_DEPENDENT_ID
        assert call["container_name"] == "qbittorrent"
        assert call["host_id"] == HOST
        assert call["event_data"]["new_state"] == "exited"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["exited", "dead"])
    async def test_a_dependent_left_under_its_temp_name_alerts(self, state):
        stranded = make_container(
            "qbittorrent-dockmon-temp-1794266276", DEPENDENT_ID, f"container:{PROVIDER_FULL_ID}", state=state
        )
        executor = make_executor([[provider(), dependent()], [provider(), stranded]])
        evaluate = executor.monitor.alert_evaluation_service.handle_container_event

        await run_update(executor)

        evaluate.assert_awaited_once()
        assert evaluate.await_args.kwargs["container_id"] == DEPENDENT_ID
        assert evaluate.await_args.kwargs["event_data"]["new_state"] == state

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["restarting", "paused", "created"])
    async def test_states_the_stop_rule_does_not_match_send_nothing(self, state):
        after = [provider(), dependent(NEW_DEPENDENT_ID, state=state)]
        executor = make_executor([[provider(), dependent()], after])

        await run_update(executor)

        executor.monitor.alert_evaluation_service.handle_container_event.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("before_state, after", [
        ("running", [provider(), dependent(NEW_DEPENDENT_ID)]),
        ("running", []),
        ("running", RuntimeError("host offline")),
        ("running", [provider()]),
        ("exited", [provider(), dependent(NEW_DEPENDENT_ID, state="exited")]),
    ], ids=["came-back", "empty-discovery", "discovery-failed", "removed", "was-not-running"])
    async def test_no_alert_without_evidence_it_was_left_down(self, before_state, after):
        executor = make_executor([[provider(), dependent(state=before_state)], after])

        await run_update(executor)

        executor.monitor.alert_evaluation_service.handle_container_event.assert_not_awaited()


@pytest.fixture
def stopped_rule(db):
    with db.get_session() as session:
        session.add(AlertRuleV2(
            id="rule-stopped", name="Container Stopped", kind="container_stopped",
            scope="container", severity="warning", enabled=True,
            suppress_during_updates=True, alert_active_delay_seconds=0,
            notification_cooldown_seconds=0,
        ))
        session.commit()


class TestAlertEngineUsesTheName:
    def evaluate(self, db, executor, container_id):
        context = EvaluationContext(
            scope_type="container", scope_id=make_composite_key(HOST, container_id),
            host_id=HOST, host_name="sonarr", container_id=container_id, container_name="qbittorrent",
        )
        with patch("updates.update_executor.get_update_executor", return_value=executor):
            return AlertEngine(db).evaluate_event("state_change", context, {"new_state": "exited"})

    def test_stop_of_a_recreated_dependent_is_suppressed(self, db, stopped_rule):
        with patch("updates.update_executor.UpdateClient"):
            executor = UpdateExecutor(db=MagicMock(), monitor=MagicMock())
        executor._recreating_dependents.add((HOST, "qbittorrent"))

        assert self.evaluate(db, executor, NEW_DEPENDENT_ID) == []

    def test_same_stop_alerts_when_nothing_recreates_it(self, db, stopped_rule):
        with patch("updates.update_executor.UpdateClient"):
            executor = UpdateExecutor(db=MagicMock(), monitor=MagicMock())

        assert len(self.evaluate(db, executor, NEW_DEPENDENT_ID)) == 1


class TestEventAutoRestartUsesTheName:
    @pytest.mark.asyncio
    async def test_die_of_a_recreated_dependent_is_not_auto_restarted(self, caplog):
        with patch("updates.update_executor.UpdateClient"):
            executor = UpdateExecutor(db=MagicMock(), monitor=MagicMock())
        executor._recreating_dependents.add((HOST, "qbittorrent"))

        monitor = DockerMonitor.__new__(DockerMonitor)
        monitor.hosts = {}
        monitor.alert_evaluation_service = None
        monitor._container_states = {}
        monitor._container_state_timestamps = {}
        monitor._container_state_sources = {}
        monitor._get_auto_restart_status = MagicMock(return_value=True)

        event = {
            "action": "die", "container_id": NEW_DEPENDENT_ID, "container_name": "qbittorrent",
            "host_id": HOST, "attributes": {"exitCode": "0"}, "timestamp": "2026-11-09T23:17:56Z",
        }
        with caplog.at_level(logging.INFO), \
                patch("updates.update_executor.get_update_executor", return_value=executor), \
                patch("docker_monitor.monitor.get_event_bus"):
            await monitor._handle_docker_event(event)

        assert "Skipping auto-restart for qbittorrent - container is being updated" in caplog.text
        monitor._get_auto_restart_status.assert_not_called()
