"""
Regression tests for env-file forwarding on the DeploymentExecutor stack path.

Bug: stack_executor._execute_via_go_service called
    client.deploy_with_progress(..., environment=variables, ...)
- `environment` is not a parameter of deploy_with_progress (it is `env_file_content`).
- `variables` was read from definition['variables'], a key the executor never sets
  (it sets 'env_content'), so it was always {}.

Result: the stack's .env never reached the Go compose service on the
DeploymentExecutor (deploy-by-ID / redeploy) path for local/mTLS hosts.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from deployment import stack_executor
from deployment.compose_client import DeployResult


async def test_execute_stack_deployment_forwards_env_content_as_env_file_content():
    """The stack's env_content must be sent to the Go service as env_file_content,
    and the nonexistent `environment` kwarg must not be passed."""
    deployment = MagicMock()
    deployment.id = "dep-1"
    deployment.host_id = "host-1"
    deployment.stack_name = "myapp"

    definition = {
        "compose_yaml": "services:\n  web:\n    image: nginx:alpine\n",
        "env_content": "IMAGE=nginx:alpine\n",
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
    assert kwargs.get("env_file_content") == "IMAGE=nginx:alpine\n"
    assert "environment" not in kwargs
