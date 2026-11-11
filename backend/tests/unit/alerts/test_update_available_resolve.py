"""An update_available alert closes when the update is applied or no longer exists.

Regression for issue #255: the alert was keyed by the pre-update container id and stayed open.
Also covers the daily stale-alert sweep, which used to resolve every container alert on agent
hosts (no Docker client) and on hosts whose listing failed.
"""
import types
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Query

from agent.command_executor import CommandResult, CommandStatus
from alerts.engine import AlertEngine, resolve_update_available_alerts
from database import Agent, AlertRuleV2, AlertV2, ContainerUpdate, DockerHostDB, Tag, TagAssignment
from docker_monitor.container_discovery import ContainerDiscovery
from docker_monitor.periodic_jobs import PeriodicJobsManager
from updates.agent_executor import AgentUpdateExecutor
from updates.database_updater import update_container_records_after_update
from updates.types import UpdateContext
from updates.update_checker import UpdateChecker

HOST = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
AGENT_HOST = "f5cc8d91-318e-4a42-9ebc-bfe584f3a3b0"
OLD = "aaaaaaaaaaaa"
NEW = "bbbbbbbbbbbb"
OTHER = "cccccccccccc"


def key(container_id, host=HOST):
    return f"{host}:{container_id}"


@pytest.fixture
def seeded(db):
    with db.get_session() as session:
        session.add(DockerHostDB(id=HOST, name="docker-1", url="unix:///var/run/docker.sock", is_active=True))
        session.add(DockerHostDB(id=AGENT_HOST, name="agent-1", url="agent://", connection_type="agent", is_active=True))
        session.commit()
    return db


def add_rule(db, kind="update_available", auto_resolve_on_clear=False):
    rule_id = str(uuid.uuid4())
    with db.get_session() as session:
        session.add(AlertRuleV2(id=rule_id, name=f"{kind}-{rule_id[:4]}", scope="container", kind=kind,
                                severity="info", auto_resolve_on_clear=auto_resolve_on_clear))
        session.commit()
    return rule_id


def add_alert(db, scope_id, kind="update_available", state="open", rule_id=None, scope_type="container",
              last_seen=None):
    alert_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    with db.get_session() as session:
        session.add(AlertV2(id=alert_id, dedup_key=f"{alert_id}|{kind}|{scope_type}:{scope_id}",
                            scope_type=scope_type, scope_id=scope_id, kind=kind, severity="info", state=state,
                            title="t", message="m", first_seen=now, last_seen=last_seen or now,
                            rule_id=rule_id))
        session.commit()
    return alert_id


def alert(db, alert_id):
    with db.get_session() as session:
        row = session.query(AlertV2).filter_by(id=alert_id).one()
        session.expunge(row)
        return row


def add_update_record(db, container_key, update_available=True, host=HOST):
    with db.get_session() as session:
        session.add(ContainerUpdate(container_id=container_key, host_id=host, current_image="app:1.0",
                                    current_digest="sha256:old", update_available=update_available))
        session.commit()


class TestHelper:
    def test_resolves_open_and_snoozed_alerts_for_the_key_only(self, seeded):
        db = seeded
        opened = add_alert(db, key(OLD))
        snoozed = add_alert(db, key(OLD), state="snoozed")
        other_kind = add_alert(db, key(OLD), kind="container_stopped")
        other_key = add_alert(db, key(OTHER))

        with db.get_session() as session:
            count = resolve_update_available_alerts(session, key(OLD), "Container updated")
            session.commit()

        assert count == 2
        for alert_id in (opened, snoozed):
            row = alert(db, alert_id)
            assert (row.state, row.resolved_reason) == ("resolved", "Container updated")
            assert row.resolved_at is not None
            assert row.resolve_notified_at is None
        assert alert(db, other_kind).state == "open"
        assert alert(db, other_key).state == "open"

    def test_condition_clear_respects_the_rules_auto_resolve_on_clear(self, seeded):
        db = seeded
        clears = add_alert(db, key(OLD), rule_id=add_rule(db, auto_resolve_on_clear=True))
        keeps = add_alert(db, key(OLD), rule_id=add_rule(db, auto_resolve_on_clear=False))
        no_rule = add_alert(db, key(OLD))

        with db.get_session() as session:
            resolve_update_available_alerts(session, key(OLD), "No update available", require_auto_resolve=True)
            session.commit()

        assert alert(db, clears).state == "resolved"
        assert alert(db, keeps).state == "open"
        assert alert(db, no_rule).state == "open"


class TestReopen:
    def test_reopened_alert_can_send_another_recovery_notice(self, seeded):
        db = seeded
        alert_id = add_alert(db, key(OLD))
        with db.get_session() as session:
            row = session.query(AlertV2).filter_by(id=alert_id).one()
            row.state, row.resolve_notified_at = "resolved", datetime.now(timezone.utc)
            session.commit()
            session.expunge(row)

        AlertEngine(db)._update_alert(row)

        reopened = alert(db, alert_id)
        assert (reopened.state, reopened.resolve_notified_at) == ("open", None)


class TestUpdaterResolves:
    def test_update_resolves_the_old_containers_alert(self, seeded):
        db = seeded
        add_update_record(db, key(OLD))
        old_alert = add_alert(db, key(OLD), rule_id=add_rule(db))
        stopped = add_alert(db, key(OLD), kind="container_stopped")

        assert update_container_records_after_update(db, HOST, OLD, NEW, "app:1.1", "sha256:new",
                                                     invalidate_cache=False)

        assert alert(db, old_alert).state == "resolved"
        assert alert(db, stopped).state == "open"

    def test_second_call_is_a_no_op(self, seeded):
        db = seeded
        add_update_record(db, key(OLD))
        old_alert = add_alert(db, key(OLD))
        for _ in range(2):
            assert update_container_records_after_update(db, HOST, OLD, NEW, "app:1.1", "sha256:new",
                                                         invalidate_cache=False)
        resolved_at = alert(db, old_alert).resolved_at
        assert update_container_records_after_update(db, HOST, OLD, NEW, "app:1.1", "sha256:new",
                                                     invalidate_cache=False)
        assert alert(db, old_alert).resolved_at == resolved_at

    def test_tag_race_keeps_the_record_move_and_the_resolve(self, seeded):
        db = seeded
        add_update_record(db, key(OLD))
        old_alert = add_alert(db, key(OLD))
        with db.get_session() as session:
            session.add(Tag(id="t1", name="web"))
            session.flush()
            session.add(TagAssignment(tag_id="t1", subject_type="container", subject_id=key(OLD)))
            session.add(TagAssignment(tag_id="t1", subject_type="container", subject_id=key(NEW)))
            session.commit()

        # A reattachment that lands between the first count and the move.
        real_count = Query.count
        calls = []

        def first_count_misses_the_reattachment(query):
            calls.append(query)
            return 0 if len(calls) == 1 else real_count(query)

        with patch.object(Query, "count", first_count_misses_the_reattachment):
            assert update_container_records_after_update(db, HOST, OLD, NEW, "app:1.1", "sha256:new",
                                                         invalidate_cache=False)

        with db.get_session() as session:
            assert session.query(ContainerUpdate).one().container_id == key(NEW)
            assert [t.subject_id for t in session.query(TagAssignment).all()] == [key(NEW)]
        assert alert(db, old_alert).state == "resolved"


class TestAgentSelfUpdateResolves:
    async def test_self_update_resolves_the_alert(self, seeded):
        db = seeded
        container_key = key(OLD, AGENT_HOST)
        add_update_record(db, container_key, host=AGENT_HOST)
        alert_id = add_alert(db, container_key)

        command_executor = MagicMock()
        command_executor.execute_command = AsyncMock(return_value=CommandResult(
            status=CommandStatus.SUCCESS, success=True, response={}, error=None))
        executor = AgentUpdateExecutor(db=db, agent_manager=MagicMock(), agent_command_executor=command_executor,
                                       monitor=MagicMock(manager=None))
        executor._wait_for_agent_reconnection = AsyncMock(return_value=True)
        executor._get_agent_version = AsyncMock(return_value="1.2.1")
        record = ContainerUpdate(container_id=container_key, current_image="ghcr.io/darthnorse/dockmon-agent:1.2.0",
                                 latest_image="ghcr.io/darthnorse/dockmon-agent:1.2.1", update_available=True)
        context = UpdateContext(host_id=AGENT_HOST, container_id=OLD, container_name="dockmon-agent",
                                current_image=record.current_image, new_image=record.latest_image,
                                update_record_id=1)

        with patch("updates.dockmon_update_checker.get_dockmon_update_checker",
                   return_value=MagicMock(fetch_agent_checksum=AsyncMock(return_value=None))):
            result = await executor.execute_self_update(context=context, progress_callback=AsyncMock(),
                                                        update_record=record, agent_id="agent-1")

        assert result.success
        assert alert(db, alert_id).state == "resolved"


def update_info(update_available):
    return {
        "current_image": "app:1.0", "current_digest": "sha256:a", "latest_image": "app:1.0",
        "latest_digest": "sha256:b" if update_available else "sha256:a", "update_available": update_available,
        "registry_url": "docker.io", "platform": "linux/amd64", "floating_tag_mode": "exact",
        "current_version": None, "latest_version": None, "changelog_url": None, "changelog_source": None,
        "changelog_checked_at": None,
    }


CONTAINER = {"host_id": HOST, "id": OLD, "name": "app", "image": "app:1.0"}


class TestCheckerResolves:
    def test_negative_check_resolves_when_the_rule_clears_on_resolve(self, seeded):
        db = seeded
        clears = add_alert(db, key(OLD), rule_id=add_rule(db, auto_resolve_on_clear=True))
        UpdateChecker(db=db, monitor=MagicMock())._store_update_info(CONTAINER, update_info(False))
        assert alert(db, clears).state == "resolved"

    def test_negative_check_leaves_it_when_the_rule_does_not(self, seeded):
        db = seeded
        keeps = add_alert(db, key(OLD), rule_id=add_rule(db, auto_resolve_on_clear=False))
        UpdateChecker(db=db, monitor=MagicMock())._store_update_info(CONTAINER, update_info(False))
        assert alert(db, keeps).state == "open"

    def test_positive_check_leaves_it(self, seeded):
        db = seeded
        keeps = add_alert(db, key(OLD), rule_id=add_rule(db, auto_resolve_on_clear=True))
        UpdateChecker(db=db, monitor=MagicMock())._store_update_info(CONTAINER, update_info(True))
        assert alert(db, keeps).state == "open"

    def test_local_image_marker_resolves(self, seeded):
        db = seeded
        clears = add_alert(db, key(OLD), rule_id=add_rule(db, auto_resolve_on_clear=True))
        UpdateChecker(db=db, monitor=MagicMock())._store_local_image_info(CONTAINER)
        assert alert(db, clears).state == "resolved"

    async def test_failed_single_check_leaves_it(self, seeded):
        db = seeded
        keeps = add_alert(db, key(OLD), rule_id=add_rule(db, auto_resolve_on_clear=True))
        checker = UpdateChecker(db=db, monitor=MagicMock())
        checker._get_container_async = AsyncMock(return_value=dict(CONTAINER))
        checker._check_container_update = AsyncMock(return_value=None)
        assert await checker.check_single_container(HOST, OLD) is None
        assert alert(db, keeps).state == "open"

    async def test_negative_single_check_resolves(self, seeded):
        db = seeded
        clears = add_alert(db, key(OLD), rule_id=add_rule(db, auto_resolve_on_clear=True))
        checker = UpdateChecker(db=db, monitor=MagicMock())
        checker._get_container_async = AsyncMock(return_value=dict(CONTAINER))
        checker._check_container_update = AsyncMock(return_value=update_info(False))
        await checker.check_single_container(HOST, OLD)
        assert alert(db, clears).state == "resolved"


def jobs_with(db, hosts, listings):
    """listings: host_id -> set of short ids, or None for a failed listing."""
    async def list_container_ids(host_id):
        return listings[host_id]

    jobs = PeriodicJobsManager(db, event_logger=types.SimpleNamespace())
    jobs.monitor = types.SimpleNamespace(
        hosts={h: object() for h in hosts},
        discovery=types.SimpleNamespace(list_container_ids=AsyncMock(side_effect=list_container_ids)),
    )
    return jobs


class TestStaleSweep:
    async def test_running_container_on_an_agent_host_stays_open(self, seeded):
        db = seeded
        alert_id = add_alert(db, key(OLD, AGENT_HOST), kind="container_stopped")
        await jobs_with(db, [AGENT_HOST], {AGENT_HOST: {OLD}}).auto_resolve_stale_alerts()
        assert alert(db, alert_id).state == "open"

    async def test_failed_listing_stays_open(self, seeded):
        db = seeded
        alert_id = add_alert(db, key(OLD), kind="container_stopped")
        await jobs_with(db, [HOST], {HOST: None}).auto_resolve_stale_alerts()
        assert alert(db, alert_id).state == "open"

    async def test_gone_container_resolves(self, seeded):
        db = seeded
        alert_id = add_alert(db, key(OLD, AGENT_HOST), kind="container_stopped")
        await jobs_with(db, [AGENT_HOST], {AGENT_HOST: {OTHER}}).auto_resolve_stale_alerts()
        row = alert(db, alert_id)
        assert (row.state, row.resolved_reason) == ("resolved", "entity_gone")

    async def test_container_on_a_deleted_host_resolves(self, seeded):
        db = seeded
        alert_id = add_alert(db, key(OLD), kind="container_stopped")
        jobs = jobs_with(db, [], {})
        await jobs.auto_resolve_stale_alerts()
        assert alert(db, alert_id).resolved_reason == "entity_gone"
        jobs.monitor.discovery.list_container_ids.assert_not_awaited()

    async def test_host_alert_for_a_known_host_stays_open(self, seeded):
        db = seeded
        alert_id = add_alert(db, HOST, kind="host_down", scope_type="host")
        await jobs_with(db, [HOST], {HOST: set()}).auto_resolve_stale_alerts()
        assert alert(db, alert_id).state == "open"

    async def test_old_update_alert_stays_open_while_the_update_is_pending(self, seeded):
        db = seeded
        add_update_record(db, key(OLD), update_available=True)
        alert_id = add_alert(db, key(OLD), last_seen=datetime.now(timezone.utc) - timedelta(days=3))
        await jobs_with(db, [HOST], {HOST: {OLD}}).auto_resolve_stale_alerts()
        assert alert(db, alert_id).state == "open"

    async def test_old_update_alert_expires_once_the_update_is_gone(self, seeded):
        db = seeded
        add_update_record(db, key(OLD), update_available=False)
        alert_id = add_alert(db, key(OLD), last_seen=datetime.now(timezone.utc) - timedelta(days=3))
        await jobs_with(db, [HOST], {HOST: {OLD}}).auto_resolve_stale_alerts()
        assert alert(db, alert_id).resolved_reason == "expired"

    async def test_alert_changed_during_the_listing_is_left_alone(self, seeded):
        db = seeded
        manual = add_alert(db, key(OLD), kind="container_stopped")
        refreshed = add_alert(db, key(OTHER), kind="cpu_high",
                              last_seen=datetime.now(timezone.utc) - timedelta(days=3))

        async def list_container_ids(host_id):
            with db.get_session() as session:
                row = session.query(AlertV2).filter_by(id=manual).one()
                row.state, row.resolved_reason = "resolved", "manual"
                session.query(AlertV2).filter_by(id=refreshed).one().last_seen = datetime.now(timezone.utc)
                session.commit()
            return {OTHER}

        jobs = jobs_with(db, [HOST], {})
        jobs.monitor.discovery.list_container_ids = AsyncMock(side_effect=list_container_ids)
        await jobs.auto_resolve_stale_alerts()

        assert alert(db, manual).resolved_reason == "manual"
        assert alert(db, refreshed).state == "open"


class TestListContainerIds:
    def discovery(self, db, connection_type, client=None):
        host = types.SimpleNamespace(name="h", connection_type=connection_type)
        clients = {HOST: client} if client else {}
        return ContainerDiscovery(db=db, settings=None, hosts={HOST: host}, clients=clients)

    def agent_db(self, db):
        with db.get_session() as session:
            session.add(Agent(id="agent-1", host_id=HOST, engine_id="e", version="1.2.1", proto_version="1",
                              capabilities={}, status="online"))
            session.commit()
        return db

    def executor_returning(self, result):
        executor = MagicMock(execute_command=AsyncMock(return_value=result))
        return patch("docker_monitor.container_discovery.get_agent_command_executor", return_value=executor)

    async def test_agent_host_lists_short_ids(self, seeded):
        discovery = self.discovery(self.agent_db(seeded), "agent")
        result = CommandResult(status=CommandStatus.SUCCESS, success=True, error=None,
                               response=[{"Id": OLD + "f" * 52}, {"Id": OTHER}])
        with self.executor_returning(result):
            assert await discovery.list_container_ids(HOST) == {OLD, OTHER}

    async def test_agent_host_with_no_containers_is_an_empty_set(self, seeded):
        discovery = self.discovery(self.agent_db(seeded), "agent")
        result = CommandResult(status=CommandStatus.SUCCESS, success=True, error=None, response=[])
        with self.executor_returning(result):
            assert await discovery.list_container_ids(HOST) == set()

    @pytest.mark.parametrize("result", [
        CommandResult(status=CommandStatus.ERROR, success=False, error="offline", response=None),
        CommandResult(status=CommandStatus.SUCCESS, success=True, error=None, response={"unexpected": 1}),
        CommandResult(status=CommandStatus.SUCCESS, success=True, error=None, response=[{"Names": ["/x"]}]),
        CommandResult(status=CommandStatus.SUCCESS, success=True, error=None, response=[{"Id": OLD}, {"Id": "abc"}]),
    ])
    async def test_agent_failure_is_none(self, seeded, result):
        discovery = self.discovery(self.agent_db(seeded), "agent")
        with self.executor_returning(result):
            assert await discovery.list_container_ids(HOST) is None

    async def test_agent_host_without_an_agent_record_is_none(self, seeded):
        assert await self.discovery(seeded, "agent").list_container_ids(HOST) is None

    async def test_local_host_lists_short_ids(self, seeded):
        client = MagicMock()
        client.containers.list.return_value = [types.SimpleNamespace(id=OLD + "0" * 52)]
        assert await self.discovery(seeded, "local", client).list_container_ids(HOST) == {OLD}

    async def test_local_listing_failure_is_none(self, seeded):
        client = MagicMock()
        client.containers.list.side_effect = RuntimeError("socket closed")
        assert await self.discovery(seeded, "local", client).list_container_ids(HOST) is None

    async def test_local_host_without_a_client_is_none(self, seeded):
        assert await self.discovery(seeded, "local").list_container_ids(HOST) is None
