"""Agent update failures reach the waiting executor as soon as they are reported."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.command_executor import CommandStatus
from agent.websocket_handler import AgentWebSocketHandler
from updates.agent_executor import AgentUpdateExecutor
from updates.event_emitter import UpdateEventEmitter
from updates.pending_updates import PendingUpdatesRegistry
from updates.types import UpdateContext, UpdateResult
from updates.update_executor import UpdateExecutor

HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
CONTAINER_ID = "16678699c163"


@pytest.fixture
def registry():
    PendingUpdatesRegistry._instance = None
    instance = PendingUpdatesRegistry()
    yield instance
    PendingUpdatesRegistry._instance = None


@pytest.fixture
def handler(registry):
    instance = AgentWebSocketHandler.__new__(AgentWebSocketHandler)
    instance.agent_id = "agent-1"
    instance.agent_hostname = "radarr"
    instance.host_id = HOST_ID
    instance.monitor = MagicMock()
    instance.monitor.manager.broadcast = AsyncMock()
    return instance


async def register(registry, request_id="req-1"):
    return await registry.register(HOST_ID, CONTAINER_ID, "gluetun", request_id=request_id)


def progress(stage, message="boom", request_id=None):
    payload = {"container_id": CONTAINER_ID, "stage": stage, "message": message}
    if request_id:
        payload["request_id"] = request_id
    return payload


def failed_event(request_id="req-1"):
    return {
        "request_id": request_id,
        "container_id": CONTAINER_ID,
        "error": "health check failed",
        "rolled_back": True,
        "failed_dependents": ["qbittorrent"],
    }


def is_awake(pending):
    return pending.completion_event.is_set()


class TestUpdateFailedEvent:
    @pytest.mark.asyncio
    async def test_wakes_with_the_reported_outcome(self, handler, registry):
        pending = await register(registry)

        await handler._handle_update_failed(failed_event())

        assert is_awake(pending)
        assert pending.success is False
        assert pending.error == "health check failed"
        assert pending.rollback_performed is True
        assert pending.failed_dependents == ["qbittorrent"]

    @pytest.mark.asyncio
    async def test_mismatched_request_id_is_ignored(self, handler, registry):
        pending = await register(registry, request_id="retry")

        await handler._handle_update_failed(failed_event(request_id="first-attempt"))

        assert not is_awake(pending)
        assert pending.error is None

    @pytest.mark.asyncio
    async def test_nothing_registered_raises_nothing(self, handler, registry):
        await handler._handle_update_failed(failed_event())


class TestUpdateCompleteRequestId:
    @pytest.mark.asyncio
    async def test_mismatched_request_id_is_ignored(self, registry):
        pending = await register(registry, request_id="retry")

        signalled = await registry.signal_complete(
            HOST_ID, CONTAINER_ID, "newcontainer", request_id="first-attempt"
        )

        assert signalled is False
        assert not is_awake(pending)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("request_id", [None, "req-1"])
    async def test_older_agent_and_matching_id_resolve(self, registry, request_id):
        pending = await register(registry)

        await registry.signal_complete(HOST_ID, CONTAINER_ID, "newcontainer", request_id=request_id)

        assert is_awake(pending)
        assert pending.success is True
        assert pending.new_container_id == "newcontainer"


class TestNewAgentFailureProgress:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("stage", ["failed", "rollback"])
    async def test_stores_the_error_without_waking(self, handler, registry, stage):
        pending = await register(registry)

        await handler._handle_update_progress(progress(stage, request_id="req-1"))

        assert not is_awake(pending)
        assert pending.error == "boom"

    @pytest.mark.asyncio
    async def test_mismatched_id_stores_nothing(self, handler, registry):
        pending = await register(registry, request_id="retry")

        await handler._handle_update_progress(progress("failed", request_id="first-attempt"))

        assert pending.error is None

    @pytest.mark.asyncio
    async def test_lost_update_failed_times_out_with_the_stored_error(self, handler, registry):
        pending = await register(registry)
        await handler._handle_update_progress(progress("rollback", request_id="req-1"))

        assert await registry.wait_for_completion(pending, timeout=0.01) is False
        assert pending.error == "boom"


class TestOlderAgentInference:
    @pytest.mark.asyncio
    async def test_failed_wakes_on_the_first_event(self, handler, registry):
        pending = await register(registry)

        await handler._handle_update_progress(progress("failed", "first"))
        assert is_awake(pending)
        assert pending.error == "first"
        assert pending.rollback_performed is False

        await handler._handle_update_progress(progress("failed", "first"))

    @pytest.mark.asyncio
    async def test_rollback_twice_wakes_on_the_second(self, handler, registry):
        pending = await register(registry)

        await handler._handle_update_progress(progress("rollback"))
        assert not is_awake(pending)

        await handler._handle_update_progress(progress("rollback"))
        assert is_awake(pending)
        assert pending.rollback_performed is True

    @pytest.mark.asyncio
    async def test_rollback_then_failed_keeps_the_final_error(self, handler, registry):
        pending = await register(registry)

        await handler._handle_update_progress(progress("rollback", "health check failed"))
        await handler._handle_update_progress(
            progress("failed", "health check failed (rollback also failed: gone)")
        )

        assert is_awake(pending)
        assert "rollback also failed" in pending.error
        assert pending.rollback_performed is False

    @pytest.mark.asyncio
    async def test_second_event_lost_times_out_with_the_stored_error(self, handler, registry):
        pending = await register(registry)

        await handler._handle_update_progress(progress("rollback", "health check failed"))

        assert await registry.wait_for_completion(pending, timeout=0.01) is False
        assert pending.error == "health check failed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stage", ["pulling", "backup", "health_check", "dependents", "completed"])
    async def test_other_stages_signal_nothing(self, handler, registry, stage):
        pending = await register(registry)

        await handler._handle_update_progress(progress(stage))

        assert not is_awake(pending)
        assert pending.error is None


class TestProgressHandlerRobustness:
    @pytest.mark.asyncio
    async def test_nothing_registered_still_broadcasts(self, handler, registry):
        await handler._handle_update_progress(progress("failed"))

        handler.monitor.manager.broadcast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_websocket_manager_still_signals(self, handler, registry):
        handler.monitor = None
        pending = await register(registry)

        await handler._handle_update_progress(progress("failed"))

        assert is_awake(pending)


def make_agent_executor(execute_command):
    agent_manager = MagicMock()
    agent_manager.get_agent_for_host.return_value = "agent-1"
    command_executor = MagicMock()
    command_executor.execute_command = execute_command
    return AgentUpdateExecutor(
        db=MagicMock(),
        agent_manager=agent_manager,
        agent_command_executor=command_executor,
        monitor=MagicMock(),
    )


def make_context():
    return UpdateContext(
        host_id=HOST_ID,
        container_id=CONTAINER_ID,
        container_name="gluetun",
        current_image="qmcgaw/gluetun:old",
        new_image="qmcgaw/gluetun:latest",
        update_record_id=1,
    )


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


def acknowledged():
    return SimpleNamespace(status=CommandStatus.SUCCESS, error=None)


def not_acknowledged():
    return SimpleNamespace(status=CommandStatus.TIMEOUT, error="timed out")


async def run_agent_update(execute_command):
    return await asyncio.wait_for(
        make_agent_executor(execute_command).execute(make_context(), AsyncMock(), make_record()),
        timeout=2,
    )


class TestAgentExecutor:
    @pytest.mark.asyncio
    async def test_payload_carries_a_request_id_that_events_must_match(self, handler, registry):
        sent = {}

        async def execute_command(agent_id, command, timeout):
            sent.update(command)
            await handler._handle_update_failed(
                failed_event(request_id=command["payload"]["request_id"])
            )
            return acknowledged()

        result = await run_agent_update(execute_command)

        assert sent["payload"]["request_id"]
        assert result.success is False
        assert result.error_message == "health check failed"
        assert result.rollback_performed is True
        assert result.failed_dependents == ["qbittorrent"]
        assert not registry._pending

    @pytest.mark.asyncio
    async def test_older_agent_failure_returns_without_waiting_for_the_timeout(self, handler, registry):
        async def execute_command(agent_id, command, timeout):
            await handler._handle_update_progress(progress("failed", "pull failed"))
            return acknowledged()

        result = await run_agent_update(execute_command)

        assert result.success is False
        assert result.error_message == "pull failed"
        assert not registry._pending

    @pytest.mark.asyncio
    async def test_unacknowledged_command_reports_a_recorded_failure(self, handler, registry):
        async def execute_command(agent_id, command, timeout):
            await handler._handle_update_failed(
                failed_event(request_id=command["payload"]["request_id"])
            )
            return not_acknowledged()

        result = await run_agent_update(execute_command)

        assert result.error_message == "health check failed"
        assert result.rollback_performed is True
        assert result.failed_dependents == ["qbittorrent"]
        assert not registry._pending

    @pytest.mark.asyncio
    async def test_unacknowledged_command_with_nothing_recorded_is_rejected(self, registry):
        async def execute_command(agent_id, command, timeout):
            return not_acknowledged()

        result = await run_agent_update(execute_command)

        assert result.error_message == "Agent rejected update command: timed out"
        assert not registry._pending


class TestUpdateContainerFailureEvents:
    async def run_update(self, result):
        with patch("updates.update_executor.UpdateClient"):
            executor = UpdateExecutor(db=MagicMock(), monitor=MagicMock())
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(
            connection_type="agent"
        )
        executor.db.get_session.return_value.__enter__.return_value = session
        executor.event_emitter = AsyncMock()
        executor._get_container_info = AsyncMock(return_value={"name": "gluetun"})
        executor._execute_agent_update = AsyncMock(return_value=result)
        executor._re_evaluate_alerts_after_update = AsyncMock()

        success = await executor.update_container(HOST_ID, CONTAINER_ID, make_record())
        assert success is False
        return executor.event_emitter

    @pytest.mark.asyncio
    async def test_rollback_with_unrecovered_dependents(self):
        emitter = await self.run_update(
            UpdateResult.failure_result("boom", rollback_performed=True, failed_dependents=["qbittorrent"])
        )

        emitter.emit_rollback_completed.assert_awaited_once()
        emitter.emit_dependents_failed.assert_awaited_once_with(
            HOST_ID, CONTAINER_ID, "gluetun", ["qbittorrent"]
        )

    @pytest.mark.asyncio
    async def test_failure_without_rollback_or_dependents(self):
        emitter = await self.run_update(UpdateResult.failure_result("boom"))

        emitter.emit_failed.assert_awaited_once()
        emitter.emit_rollback_completed.assert_not_awaited()
        emitter.emit_dependents_failed.assert_not_awaited()


class TestDependentsWarningWording:
    @pytest.mark.asyncio
    async def test_does_not_claim_the_provider_updated(self):
        monitor = MagicMock()
        monitor.manager.broadcast = AsyncMock()
        monitor.hosts = {}
        with patch("updates.event_emitter.get_event_bus") as get_bus:
            get_bus.return_value = AsyncMock()
            await UpdateEventEmitter(monitor).emit_dependents_failed(
                HOST_ID, CONTAINER_ID, "gluetun", ["qbittorrent"]
            )

        warning = monitor.manager.broadcast.await_args.args[0]["data"]["warning"]
        assert "updated successfully" not in warning
        assert "qbittorrent" in warning
