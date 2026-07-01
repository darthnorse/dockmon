"""
Regression test: deploying with env_files but no explicit env_file_content must
populate env_file_content in the agent command payload from the map's .env entry,
so old agents (which ignore env_files entirely) still receive the .env contents.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deployment.agent_executor import AgentDeploymentExecutor
from agent.command_executor import CommandResult, CommandStatus

# Minimal valid compose YAML (no build: directive so validation passes).
_COMPOSE = """\
services:
  web:
    image: nginx:latest
"""


def _make_executor() -> AgentDeploymentExecutor:
    """Build an AgentDeploymentExecutor with stub monitor and db."""
    monitor = MagicMock()
    monitor.manager = MagicMock()
    monitor.manager.broadcast = AsyncMock()

    db = MagicMock()
    # _is_persistent_deployment queries the db; stub it so we don't need a real DB.
    executor = AgentDeploymentExecutor(monitor=monitor, database_manager=db)
    return executor


@pytest.mark.asyncio
async def test_env_file_content_derived_from_env_files_map():
    """
    When deploy() is called with env_files={".env": "TOP=1\\n"} and no
    env_file_content, the command payload sent to the agent must carry
    env_file_content == "TOP=1\\n" so old agents receive the .env.
    """
    executor = _make_executor()

    captured_commands: list[dict] = []

    # Successful CommandResult stub
    ok_result = CommandResult(
        status=CommandStatus.SUCCESS,
        success=True,
        response={"status": "ok"},
        error=None,
    )

    mock_cmd_executor = MagicMock()
    mock_cmd_executor.execute_command = AsyncMock(
        side_effect=lambda agent_id, command, **kw: (
            captured_commands.append(command) or asyncio.coroutine(lambda: ok_result)()
        )
    )

    async def _capture_and_return(agent_id, command, **kw):
        captured_commands.append(command)
        return ok_result

    mock_cmd_executor.execute_command = AsyncMock(side_effect=_capture_and_return)

    with (
        patch.object(executor, "_get_command_executor", return_value=mock_cmd_executor),
        patch.object(executor, "_get_agent_id_for_host", return_value="agent-123"),
        patch.object(executor, "_report_deployment_status", new_callable=AsyncMock),
    ):
        result = await executor.deploy(
            host_id="host-abc",
            deployment_id="host-abc:mystack:0001",
            compose_content=_COMPOSE,
            project_name="mystack",
            env_files={".env": "TOP=1\n"},
            # env_file_content intentionally omitted (defaults to None)
        )

    assert result is True, "deploy() should return True on success"
    assert len(captured_commands) == 1, "exactly one command should have been sent"

    payload = captured_commands[0]["payload"]
    assert payload["env_file_content"] == "TOP=1\n", (
        "env_file_content must be derived from env_files['.env'] "
        "so old agents still receive the .env contents"
    )
    assert payload["env_files"] == {".env": "TOP=1\n"}, (
        "env_files map must also be present in the payload for new agents"
    )


@pytest.mark.asyncio
async def test_explicit_env_file_content_not_overwritten():
    """
    When deploy() is called with BOTH env_file_content and env_files, the
    explicit env_file_content must NOT be replaced by env_files[".env"].
    """
    executor = _make_executor()
    captured_commands: list[dict] = []

    ok_result = CommandResult(
        status=CommandStatus.SUCCESS,
        success=True,
        response={"status": "ok"},
        error=None,
    )

    async def _capture_and_return(agent_id, command, **kw):
        captured_commands.append(command)
        return ok_result

    mock_cmd_executor = MagicMock()
    mock_cmd_executor.execute_command = AsyncMock(side_effect=_capture_and_return)

    with (
        patch.object(executor, "_get_command_executor", return_value=mock_cmd_executor),
        patch.object(executor, "_get_agent_id_for_host", return_value="agent-123"),
        patch.object(executor, "_report_deployment_status", new_callable=AsyncMock),
    ):
        result = await executor.deploy(
            host_id="host-abc",
            deployment_id="host-abc:mystack:0002",
            compose_content=_COMPOSE,
            project_name="mystack",
            env_file_content="EXPLICIT=yes\n",
            env_files={".env": "FROM_MAP=yes\n"},
        )

    assert result is True
    payload = captured_commands[0]["payload"]
    assert payload["env_file_content"] == "EXPLICIT=yes\n", (
        "Explicit env_file_content must not be overwritten by env_files derivation"
    )


@pytest.mark.asyncio
async def test_no_env_content_when_no_dot_env_in_map():
    """
    When deploy() is called with env_files that has no '.env' key and no
    env_file_content, the payload carries an empty string (same as before).
    """
    executor = _make_executor()
    captured_commands: list[dict] = []

    ok_result = CommandResult(
        status=CommandStatus.SUCCESS,
        success=True,
        response={"status": "ok"},
        error=None,
    )

    async def _capture_and_return(agent_id, command, **kw):
        captured_commands.append(command)
        return ok_result

    mock_cmd_executor = MagicMock()
    mock_cmd_executor.execute_command = AsyncMock(side_effect=_capture_and_return)

    with (
        patch.object(executor, "_get_command_executor", return_value=mock_cmd_executor),
        patch.object(executor, "_get_agent_id_for_host", return_value="agent-123"),
        patch.object(executor, "_report_deployment_status", new_callable=AsyncMock),
        patch.object(executor, "_get_agent_record", return_value=MagicMock(capabilities='{"multi_env_files": true}')),
    ):
        result = await executor.deploy(
            host_id="host-abc",
            deployment_id="host-abc:mystack:0003",
            compose_content=_COMPOSE,
            project_name="mystack",
            env_files={"other.env": "X=1\n"},
        )

    assert result is True
    payload = captured_commands[0]["payload"]
    assert payload["env_file_content"] == "", (
        "env_file_content should be empty when no .env key exists in the map"
    )


# ==================== Fix A: old-agent gate tests ====================

def _fake_agent(has_capability: bool) -> MagicMock:
    """Return a mock Agent-like object with or without multi_env_files capability."""
    import json
    agent = MagicMock()
    if has_capability:
        agent.capabilities = json.dumps({"multi_env_files": True})
    else:
        agent.capabilities = json.dumps({"other_cap": True})
    return agent


@pytest.mark.asyncio
async def test_single_non_dot_env_file_old_agent_is_blocked():
    """
    A stack with exactly one non-.env file and an OLD agent must be blocked.
    The bug: len == 1 so the old len > 1 gate missed it.
    """
    executor = _make_executor()
    captured_commands: list[dict] = []

    ok_result = CommandResult(
        status=CommandStatus.SUCCESS, success=True,
        response={"status": "ok"}, error=None,
    )

    async def _capture_and_return(agent_id, command, **kw):
        captured_commands.append(command)
        return ok_result

    mock_cmd_executor = MagicMock()
    mock_cmd_executor.execute_command = AsyncMock(side_effect=_capture_and_return)

    with (
        patch.object(executor, "_get_command_executor", return_value=mock_cmd_executor),
        patch.object(executor, "_get_agent_id_for_host", return_value="agent-old"),
        patch.object(executor, "_report_deployment_status", new_callable=AsyncMock),
        patch.object(executor, "_get_agent_record", return_value=_fake_agent(has_capability=False)),
    ):
        result = await executor.deploy(
            host_id="host-abc",
            deployment_id="host-abc:mystack:0010",
            compose_content=_COMPOSE,
            project_name="mystack",
            env_files={".db.env": "X=1\n"},
        )

    assert result is False, "Old agent with single non-.env file must be blocked"
    assert len(captured_commands) == 0, "No command must be sent to old agent"


@pytest.mark.asyncio
async def test_single_non_dot_env_file_new_agent_proceeds():
    """
    A stack with exactly one non-.env file and a NEW agent must proceed.
    """
    executor = _make_executor()
    captured_commands: list[dict] = []

    ok_result = CommandResult(
        status=CommandStatus.SUCCESS, success=True,
        response={"status": "ok"}, error=None,
    )

    async def _capture_and_return(agent_id, command, **kw):
        captured_commands.append(command)
        return ok_result

    mock_cmd_executor = MagicMock()
    mock_cmd_executor.execute_command = AsyncMock(side_effect=_capture_and_return)

    with (
        patch.object(executor, "_get_command_executor", return_value=mock_cmd_executor),
        patch.object(executor, "_get_agent_id_for_host", return_value="agent-new"),
        patch.object(executor, "_report_deployment_status", new_callable=AsyncMock),
        patch.object(executor, "_get_agent_record", return_value=_fake_agent(has_capability=True)),
    ):
        result = await executor.deploy(
            host_id="host-abc",
            deployment_id="host-abc:mystack:0011",
            compose_content=_COMPOSE,
            project_name="mystack",
            env_files={".db.env": "X=1\n"},
        )

    assert result is True, "New agent with single non-.env file must proceed"
    assert len(captured_commands) == 1, "Exactly one command must be sent to new agent"


@pytest.mark.asyncio
async def test_single_dot_env_only_old_agent_not_blocked():
    """
    A stack with only .env and an OLD agent must NOT be blocked.
    Old agents already handle .env via the legacy env_file_content channel.
    """
    executor = _make_executor()
    captured_commands: list[dict] = []

    ok_result = CommandResult(
        status=CommandStatus.SUCCESS, success=True,
        response={"status": "ok"}, error=None,
    )

    async def _capture_and_return(agent_id, command, **kw):
        captured_commands.append(command)
        return ok_result

    mock_cmd_executor = MagicMock()
    mock_cmd_executor.execute_command = AsyncMock(side_effect=_capture_and_return)

    with (
        patch.object(executor, "_get_command_executor", return_value=mock_cmd_executor),
        patch.object(executor, "_get_agent_id_for_host", return_value="agent-old"),
        patch.object(executor, "_report_deployment_status", new_callable=AsyncMock),
        # _get_agent_record must NOT be called (gate not triggered)
    ):
        result = await executor.deploy(
            host_id="host-abc",
            deployment_id="host-abc:mystack:0012",
            compose_content=_COMPOSE,
            project_name="mystack",
            env_files={".env": "X=1\n"},
        )

    assert result is True, ".env-only stack must not be blocked on old agent"
    assert len(captured_commands) == 1, "Command must be sent"
    assert captured_commands[0]["payload"]["env_file_content"] == "X=1\n"


@pytest.mark.asyncio
async def test_two_env_files_old_agent_blocked_regression():
    """
    Regression: original case - two files (.env + .db.env) + OLD agent -> blocked.
    """
    executor = _make_executor()
    captured_commands: list[dict] = []

    ok_result = CommandResult(
        status=CommandStatus.SUCCESS, success=True,
        response={"status": "ok"}, error=None,
    )

    async def _capture_and_return(agent_id, command, **kw):
        captured_commands.append(command)
        return ok_result

    mock_cmd_executor = MagicMock()
    mock_cmd_executor.execute_command = AsyncMock(side_effect=_capture_and_return)

    with (
        patch.object(executor, "_get_command_executor", return_value=mock_cmd_executor),
        patch.object(executor, "_get_agent_id_for_host", return_value="agent-old"),
        patch.object(executor, "_report_deployment_status", new_callable=AsyncMock),
        patch.object(executor, "_get_agent_record", return_value=_fake_agent(has_capability=False)),
    ):
        result = await executor.deploy(
            host_id="host-abc",
            deployment_id="host-abc:mystack:0013",
            compose_content=_COMPOSE,
            project_name="mystack",
            env_files={".env": "TOP=1\n", ".db.env": "P=secret\n"},
        )

    assert result is False, "Two-file stack must be blocked on old agent"
    assert len(captured_commands) == 0, "No command must be sent to old agent"
