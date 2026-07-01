"""
Unit tests for AgentContainerOperations.create_network.

These tests pin the command contract sent to the Go agent (command name and
payload shape) - if the Python side and the Go agent's create_network case
drift, network creation on remote hosts breaks silently. They also verify
error mapping to HTTP status codes.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from agent.container_operations import AgentContainerOperations
from agent.command_executor import CommandStatus, CommandResult


def make_ops(agent_id="agent-1"):
    """Build AgentContainerOperations with a mocked executor and agent_manager."""
    agent_manager = MagicMock()
    agent_manager.get_agent_for_host.return_value = agent_id

    command_executor = MagicMock()
    command_executor.execute_command = AsyncMock()

    ops = AgentContainerOperations(
        command_executor=command_executor,
        db=MagicMock(),
        agent_manager=agent_manager,
    )
    return ops, command_executor


def result(status, response=None, error=None):
    return CommandResult(
        status=status,
        success=(status == CommandStatus.SUCCESS),
        response=response,
        error=error,
    )


@pytest.mark.unit
class TestAgentCreateNetwork:
    async def test_sends_create_network_command_with_full_payload(self):
        ops, executor = make_ops()
        executor.execute_command.return_value = result(
            CommandStatus.SUCCESS,
            response={"id": "abc123def456", "name": "my-net", "driver": "bridge"},
        )

        out = await ops.create_network(
            "host-1",
            name="my-net",
            driver="bridge",
            subnet="172.30.0.0/16",
            gateway="172.30.0.1",
            internal=True,
        )

        assert out["name"] == "my-net"

        # Pin the exact contract the Go agent parses (create_network case).
        sent = executor.execute_command.call_args[0][1]
        assert sent["command"] == "create_network"
        assert sent["payload"] == {
            "name": "my-net",
            "driver": "bridge",
            "subnet": "172.30.0.0/16",
            "gateway": "172.30.0.1",
            "internal": True,
        }

    async def test_defaults_optional_fields(self):
        ops, executor = make_ops()
        executor.execute_command.return_value = result(
            CommandStatus.SUCCESS, response={"id": "x", "name": "minimal"}
        )

        await ops.create_network("host-1", name="minimal")

        sent = executor.execute_command.call_args[0][1]
        assert sent["payload"] == {
            "name": "minimal",
            "driver": "bridge",
            "subnet": "",
            "gateway": "",
            "internal": False,
        }

    async def test_no_agent_raises_404(self):
        ops, _ = make_ops(agent_id=None)

        with pytest.raises(HTTPException) as exc:
            await ops.create_network("host-1", name="x")
        assert exc.value.status_code == 404

    async def test_duplicate_network_maps_to_409(self):
        ops, executor = make_ops()
        executor.execute_command.return_value = result(
            CommandStatus.ERROR,
            error="failed to create network: network with name my-net already exists",
        )

        with pytest.raises(HTTPException) as exc:
            await ops.create_network("host-1", name="my-net")
        assert exc.value.status_code == 409

    async def test_timeout_maps_to_504(self):
        ops, executor = make_ops()
        executor.execute_command.return_value = result(
            CommandStatus.TIMEOUT, error="timeout"
        )

        with pytest.raises(HTTPException) as exc:
            await ops.create_network("host-1", name="my-net")
        assert exc.value.status_code == 504

    async def test_generic_error_maps_to_500(self):
        ops, executor = make_ops()
        executor.execute_command.return_value = result(
            CommandStatus.ERROR, error="some docker daemon error"
        )

        with pytest.raises(HTTPException) as exc:
            await ops.create_network("host-1", name="my-net")
        assert exc.value.status_code == 500

    async def test_old_agent_unknown_command_maps_to_update_message(self):
        # An out-of-date agent that predates create_network replies with the
        # default "unknown command" error. Surface a clear "update the agent"
        # message instead of a raw 500.
        ops, executor = make_ops()
        executor.execute_command.return_value = result(
            CommandStatus.ERROR, error="unknown command: create_network"
        )

        with pytest.raises(HTTPException) as exc:
            await ops.create_network("host-1", name="my-net")
        assert exc.value.status_code == 501
        assert "agent" in exc.value.detail.lower()
        assert "update" in exc.value.detail.lower()
