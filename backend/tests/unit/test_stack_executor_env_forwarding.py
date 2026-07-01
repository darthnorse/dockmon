"""
Regression tests for env-file forwarding on the DeploymentExecutor stack path.

Covers both the single-env-file (.env only) and multi-env-file paths through
stack_executor._execute_via_go_service -> ComposeClient.deploy_with_progress.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from deployment import stack_executor
from deployment.compose_client import DeployResult


async def test_execute_stack_deployment_forwards_env_files_single():
    """The stack's single .env file is forwarded as env_files map to the Go service."""
    deployment = MagicMock()
    deployment.id = "dep-1"
    deployment.host_id = "host-1"
    deployment.stack_name = "myapp"

    definition = {
        "compose_yaml": "services:\n  web:\n    image: nginx:alpine\n",
        "env_files": {".env": "IMAGE=nginx:alpine\n"},
    }

    session = MagicMock()
    state_machine = MagicMock()
    update_progress = AsyncMock()
    create_deployment_metadata = MagicMock()

    with patch.object(stack_executor, "_get_host_connection_info", return_value={}), \
         patch.object(stack_executor, "ComposeValidator") as mock_validator_cls, \
         patch.object(stack_executor, "ComposeClient") as mock_client_cls:
        mock_validator_cls.return_value.validate_yaml_safety = MagicMock()
        mock_client = mock_client_cls.return_value
        mock_client.deploy_with_progress = AsyncMock(
            return_value=DeployResult(deployment_id="dep-1", success=True, services={})
        )

        await stack_executor.execute_stack_deployment(
            session=session,
            deployment=deployment,
            definition=definition,
            docker_monitor=MagicMock(),
            state_machine=state_machine,
            update_progress=update_progress,
            create_deployment_metadata=create_deployment_metadata,
        )

    assert mock_client.deploy_with_progress.await_count == 1
    kwargs = mock_client.deploy_with_progress.call_args.kwargs
    assert kwargs.get("env_files") == {".env": "IMAGE=nginx:alpine\n"}
    assert "environment" not in kwargs
    assert "env_file_content" not in kwargs


async def test_execute_stack_deployment_forwards_env_files_map():
    """The Go-socket path forwards definition['env_files'] as env_files."""
    deployment = MagicMock()
    deployment.id, deployment.host_id, deployment.stack_name = "d", "h", "app"
    definition = {
        "compose_yaml": "services:\n  db:\n    image: x\n",
        "env_files": {".env": "A=1\n", ".db.env": "B=2\n"},
    }
    session, sm = MagicMock(), MagicMock()
    up, cdm = AsyncMock(), MagicMock()
    with patch.object(stack_executor, "_get_host_connection_info", return_value={}), \
         patch.object(stack_executor, "ComposeValidator") as v, \
         patch.object(stack_executor, "ComposeClient") as c:
        v.return_value.validate_yaml_safety = MagicMock()
        client = c.return_value
        client.deploy_with_progress = AsyncMock(
            return_value=DeployResult(deployment_id="d", success=True, services={}))
        await stack_executor.execute_stack_deployment(
            session=session, deployment=deployment, definition=definition,
            docker_monitor=MagicMock(), state_machine=sm,
            update_progress=up, create_deployment_metadata=cdm)
    kwargs = client.deploy_with_progress.call_args.kwargs
    assert kwargs.get("env_files") == {".env": "A=1\n", ".db.env": "B=2\n"}
