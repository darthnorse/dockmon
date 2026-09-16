"""The nightly agent system-info refresh.

It was written against a request/response call that did not exist on either
side: the backend's send_command is fire-and-forget and the agent had no
get_system_info handler, so every night each agent logged a TypeError and
the host card only refreshed when the agent happened to reconnect.
"""
import asyncio
import logging
import time
import types
from unittest.mock import AsyncMock

import pytest

import agent.command_executor as executor_module
import agent.connection_manager as cm_module
from agent.command_executor import CommandErrorCode, CommandResult, CommandStatus
from database import Agent, DockerHostDB
from docker_monitor.monitor import DockerMonitor
from models.docker_models import DockerHost

HOST_ID = "7be442c9-24bc-4047-b33a-41bbf51ea2f9"
AGENT_ID = "c37b66aa-0000-4000-8000-000000000001"

STORED = {
    "os_version": "Debian GNU/Linux 12 (bookworm)",
    "docker_version": "27.0.0",
    "kernel_version": "6.1.0",
    "daemon_started_at": "2026-08-01T00:00:00Z",
    "total_memory": 8_000_000_000,
    "num_cpus": 4,
}

NEW_INFO = {
    "os_type": "linux",
    "os_version": "Debian GNU/Linux 13 (trixie)",
    "kernel_version": "6.12.48+deb13-amd64",
    "docker_version": "29.0.0",
    "daemon_started_at": "2026-09-16T02:00:00Z",
    "total_memory": 16_000_000_000,
    "num_cpus": 8,
}


@pytest.fixture
def seeded_db(db):
    with db.get_session() as session:
        session.add(DockerHostDB(id=HOST_ID, name="mediadmz", url="agent://", connection_type="agent", **STORED))
        session.add(Agent(
            id=AGENT_ID, host_id=HOST_ID, engine_id="engine-1", version="1.1.2",
            proto_version="1", capabilities={}, status="online",
        ))
        session.commit()
    return db


@pytest.fixture
def executor(monkeypatch):
    executor = types.SimpleNamespace(execute_command=AsyncMock())
    monkeypatch.setattr(executor_module, "get_agent_command_executor", lambda: executor)
    return executor


@pytest.fixture
def monitor(seeded_db, executor, monkeypatch):
    mon = DockerMonitor.__new__(DockerMonitor)
    mon.db = seeded_db
    monkeypatch.setattr(cm_module.agent_connection_manager, "is_connected", lambda agent_id: True)
    return mon


def _result(success=True, response=None, error=None):
    return CommandResult(
        status=CommandStatus.SUCCESS if success else CommandStatus.ERROR,
        success=success, response=response, error=error,
        error_code=None if success else CommandErrorCode.AGENT_ERROR,
    )


def _host(db):
    with db.get_session() as session:
        return session.query(DockerHostDB).filter_by(id=HOST_ID).one()


async def test_refresh_asks_the_agent_and_updates_the_host_row(monitor, executor):
    executor.execute_command.return_value = _result(response=NEW_INFO)

    updated = await monitor._refresh_agent_hosts_system_info()

    assert updated == 1
    call = executor.execute_command.await_args
    assert call.args[0] == AGENT_ID
    assert call.args[1] == {"type": "command", "command": "get_system_info"}
    assert call.kwargs.get("timeout", 0) > 0
    host = _host(monitor.db)
    assert host.docker_version == "29.0.0"
    assert host.os_version == "Debian GNU/Linux 13 (trixie)"
    assert host.kernel_version == "6.12.48+deb13-amd64"
    assert host.daemon_started_at == "2026-09-16T02:00:00Z"
    assert host.total_memory == 16_000_000_000
    assert host.num_cpus == 8


async def test_unchanged_info_is_not_counted_as_an_update(monitor, executor):
    executor.execute_command.return_value = _result(response={"os_type": None, **STORED})

    assert await monitor._refresh_agent_hosts_system_info() == 0


# An agent predating the command answers "unknown command". That is the
# normal state of a fleet mid-upgrade, not an error to page about.
async def test_old_agent_without_the_command_is_quiet(monitor, executor, caplog):
    executor.execute_command.return_value = _result(success=False, error="unknown command: get_system_info")

    with caplog.at_level(logging.INFO):
        updated = await monitor._refresh_agent_hosts_system_info()

    assert updated == 0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert _host(monitor.db).docker_version == "27.0.0"


async def test_failed_command_leaves_the_row_untouched_and_warns(monitor, executor, caplog):
    executor.execute_command.return_value = _result(success=False, error="Command timed out after 10s")

    with caplog.at_level(logging.WARNING):
        updated = await monitor._refresh_agent_hosts_system_info()

    assert updated == 0
    assert [r for r in caplog.records if AGENT_ID[:8] in r.message]
    assert _host(monitor.db).docker_version == "27.0.0"


async def test_disconnected_agent_is_skipped_without_a_command(monitor, executor, monkeypatch):
    monkeypatch.setattr(cm_module.agent_connection_manager, "is_connected", lambda agent_id: False)

    assert await monitor._refresh_agent_hosts_system_info() == 0
    executor.execute_command.assert_not_awaited()


async def test_non_dict_response_is_rejected(monitor, executor, caplog):
    executor.execute_command.return_value = _result(response=["not", "a", "dict"])

    with caplog.at_level(logging.WARNING):
        assert await monitor._refresh_agent_hosts_system_info() == 0

    assert _host(monitor.db).docker_version == "27.0.0"


# The agent's Go payload carries every key, zero-valued when unknown: daemon
# start time is "" whenever the daemon has no "bridge" network. Registration
# never overwrites a stored value with an empty one; the refresh must not either.
async def test_empty_values_do_not_clobber_stored_ones(monitor, executor):
    executor.execute_command.return_value = _result(response={
        **NEW_INFO, "daemon_started_at": "", "total_memory": 0, "os_type": None,
    })

    assert await monitor._refresh_agent_hosts_system_info() == 1
    host = _host(monitor.db)
    assert host.docker_version == "29.0.0"
    assert host.daemon_started_at == "2026-08-01T00:00:00Z"
    assert host.total_memory == 8_000_000_000


async def test_all_empty_response_is_not_an_update(monitor, executor):
    executor.execute_command.return_value = _result(response={
        k: ("" if isinstance(v, str) else 0) for k, v in NEW_INFO.items()
    })

    assert await monitor._refresh_agent_hosts_system_info() == 0
    assert _host(monitor.db).daemon_started_at == "2026-08-01T00:00:00Z"


# Registration validates these fields (length caps, numeric bounds, markup
# stripped) because an agent token is a low-privilege identity. The refresh
# writes the same columns and must hold the same line.
@pytest.mark.parametrize("bad", [
    {"os_version": "A" * 10_000},
    {"total_memory": "not-a-number"},
    {"num_cpus": {"nested": True}},
    {"num_cpus": -4},
    {"docker_version": "x" * 51},
])
async def test_out_of_bounds_values_are_rejected_whole(monitor, executor, caplog, bad):
    executor.execute_command.return_value = _result(response={**NEW_INFO, **bad})

    with caplog.at_level(logging.WARNING):
        assert await monitor._refresh_agent_hosts_system_info() == 0

    host = _host(monitor.db)
    assert host.docker_version == "27.0.0", "a partially valid payload must not be half-applied"
    warning = [r for r in caplog.records if AGENT_ID[:8] in r.message]
    assert warning
    assert "A" * 100 not in warning[0].message, "the raw agent payload must not be dumped into the log"


# A value that sanitizes down to nothing ("<>", whitespace) is empty too.
@pytest.mark.parametrize("empty_after_sanitizing", ["<>", "   ", "\x00\x01"])
async def test_values_that_sanitize_to_empty_do_not_clobber(monitor, executor, empty_after_sanitizing):
    executor.execute_command.return_value = _result(response={
        **NEW_INFO, "daemon_started_at": empty_after_sanitizing,
    })

    await monitor._refresh_agent_hosts_system_info()

    assert _host(monitor.db).daemon_started_at == "2026-08-01T00:00:00Z"


async def test_markup_is_stripped_like_registration(monitor, executor):
    executor.execute_command.return_value = _result(response={
        **NEW_INFO, "os_version": "Debian <script>alert(1)</script> 13",
    })

    await monitor._refresh_agent_hosts_system_info()

    assert _host(monitor.db).os_version == "Debian scriptalert(1)/script 13"


# One unresponsive agent must not hold the others (and the maintenance job
# behind them) for its whole timeout.
async def test_agents_are_refreshed_concurrently(monitor, executor):
    hosts = []
    with monitor.db.get_session() as session:
        for i in range(2, 7):
            hid, aid = f"host-{i}", f"agent-{i}"
            session.add(DockerHostDB(id=hid, name=f"h{i}", url="agent://", connection_type="agent"))
            session.add(Agent(id=aid, host_id=hid, engine_id=f"e{i}", version="1", proto_version="1",
                              capabilities={}, status="online"))
            hosts.append(aid)
        session.commit()

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.3)
        return _result(response=NEW_INFO)
    executor.execute_command.side_effect = slow

    start = time.monotonic()
    updated = await monitor._refresh_agent_hosts_system_info()
    elapsed = time.monotonic() - start

    assert updated == 6
    assert elapsed < 0.3 * 3, f"six agents took {elapsed:.2f}s; they were polled serially"


# The Docker-host branch has no client for an agent host; it used to warn and
# count every agent as a failure on every nightly run.
async def test_docker_host_branch_skips_agent_hosts_silently(monitor, executor, caplog):
    monitor.hosts = {HOST_ID: DockerHost(id=HOST_ID, name="mediadmz", url="agent://", connection_type="agent")}
    monitor.clients = {}
    executor.execute_command.return_value = _result(response=NEW_INFO)

    with caplog.at_level(logging.INFO):
        await monitor.refresh_all_hosts_system_info()

    assert not [r for r in caplog.records if "No client found" in r.message]
    assert [r for r in caplog.records if "refresh complete: 1 updated, 0 failed" in r.message]
