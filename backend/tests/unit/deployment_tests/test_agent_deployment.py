"""
Unit tests for Agent Deployment Executor.

Tests the native compose deployment pathway for agent-based hosts:
- Compose content validation (reject build: directives)
- Container params to compose conversion
- AgentDeploymentExecutor integration
"""

import pytest
import yaml
from unittest.mock import MagicMock, AsyncMock, patch

from deployment.agent_executor import (
    validate_compose_for_agent,
    container_params_to_compose,
    AgentDeploymentExecutor,
    get_agent_deployment_executor,
)


class TestValidateComposeForAgent:
    """Test compose validation for agent deployments"""

    def test_valid_compose_with_image(self):
        """Should accept compose with image: directive"""
        compose = """
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is True
        assert error is None

    def test_valid_compose_multiple_services(self):
        """Should accept compose with multiple services using images"""
        compose = """
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
  redis:
    image: redis:7
    volumes:
      - redis_data:/data

volumes:
  redis_data:
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is True
        assert error is None

    def test_reject_compose_with_build_directive(self):
        """Should reject compose with build: directive"""
        compose = """
services:
  app:
    build: .
    ports:
      - "3000:3000"
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is False
        assert "build:" in error.lower()
        assert "app" in error

    def test_reject_compose_with_build_context(self):
        """Should reject compose with build context"""
        compose = """
services:
  app:
    build:
      context: ./myapp
      dockerfile: Dockerfile.prod
    ports:
      - "3000:3000"
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is False
        assert "build:" in error.lower()

    def test_reject_partial_build_services(self):
        """Should reject if any service uses build:"""
        compose = """
services:
  web:
    image: nginx:alpine
  app:
    build: ./app
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is False
        assert "app" in error

    def test_invalid_yaml(self):
        """Should reject invalid YAML"""
        compose = """
services:
  - this is invalid yaml
  web:
    image: nginx
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is False
        assert "yaml" in error.lower()

    def test_missing_services_section(self):
        """Should reject compose without services section"""
        compose = """
version: "3"
volumes:
  data:
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is False
        assert "services" in error.lower()


class TestContainerParamsToCompose:
    """Test conversion of container params to compose YAML"""

    def test_basic_container(self):
        """Should convert basic container params to compose"""
        params = {
            "image": "nginx:alpine",
            "name": "my-nginx",
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert "services" in compose
        assert "my-nginx" in compose["services"]
        assert compose["services"]["my-nginx"]["image"] == "nginx:alpine"
        assert compose["services"]["my-nginx"]["container_name"] == "my-nginx"

    def test_container_with_ports(self):
        """Should include ports in compose output"""
        params = {
            "image": "nginx:alpine",
            "name": "web",
            "ports": ["8080:80", "443:443"],
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert compose["services"]["web"]["ports"] == ["8080:80", "443:443"]

    def test_container_with_volumes(self):
        """Should include volumes in compose output"""
        params = {
            "image": "nginx:alpine",
            "name": "web",
            "volumes": ["/host/path:/container/path", "named_vol:/data"],
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert "/host/path:/container/path" in compose["services"]["web"]["volumes"]
        assert "named_vol:/data" in compose["services"]["web"]["volumes"]

    def test_container_with_environment(self):
        """Should include environment variables in compose output"""
        params = {
            "image": "postgres:15",
            "name": "db",
            "environment": {
                "POSTGRES_DB": "mydb",
                "POSTGRES_USER": "admin",
            },
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        env = compose["services"]["db"]["environment"]
        assert env["POSTGRES_DB"] == "mydb"
        assert env["POSTGRES_USER"] == "admin"

    def test_container_with_restart_policy(self):
        """Should include restart policy in compose output"""
        params = {
            "image": "nginx:alpine",
            "name": "web",
            "restart_policy": "unless-stopped",
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert compose["services"]["web"]["restart"] == "unless-stopped"

    def test_container_with_restart_policy_dict(self):
        """Should handle restart policy as dict (Docker SDK format)"""
        params = {
            "image": "nginx:alpine",
            "name": "web",
            "restart_policy": {"Name": "on-failure"},
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert compose["services"]["web"]["restart"] == "on-failure"

    def test_container_with_resource_limits(self):
        """Should include resource limits in compose output"""
        params = {
            "image": "nginx:alpine",
            "name": "web",
            "memory_limit": "512m",
            "cpu_limit": 0.5,
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        deploy = compose["services"]["web"]["deploy"]
        assert deploy["resources"]["limits"]["memory"] == "512m"
        assert deploy["resources"]["limits"]["cpus"] == "0.5"

    def test_container_with_labels(self):
        """Should include labels in compose output"""
        params = {
            "image": "nginx:alpine",
            "name": "web",
            "labels": {
                "traefik.enable": "true",
                "app.version": "1.0",
            },
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert compose["services"]["web"]["labels"]["traefik.enable"] == "true"

    def test_container_with_command(self):
        """Should include command in compose output"""
        params = {
            "image": "alpine",
            "name": "runner",
            "command": ["sh", "-c", "echo hello"],
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert compose["services"]["runner"]["command"] == ["sh", "-c", "echo hello"]

    def test_container_with_network_mode(self):
        """Should include network_mode in compose output"""
        params = {
            "image": "nginx:alpine",
            "name": "web",
            "network_mode": "host",
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert compose["services"]["web"]["network_mode"] == "host"

    def test_container_with_privileged(self):
        """Should include privileged flag in compose output"""
        params = {
            "image": "docker:dind",
            "name": "dind",
            "privileged": True,
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert compose["services"]["dind"]["privileged"] is True


class TestAgentDeploymentExecutor:
    """Test AgentDeploymentExecutor class"""

    @pytest.fixture
    def mock_db(self):
        """Mock database manager"""
        db = MagicMock()
        session = MagicMock()
        db.get_session.return_value.__enter__ = MagicMock(return_value=session)
        db.get_session.return_value.__exit__ = MagicMock(return_value=False)
        return db

    @pytest.fixture
    def executor(self, mock_db):
        """Create executor with mocked dependencies"""
        return AgentDeploymentExecutor(database_manager=mock_db)

    def test_singleton_pattern(self):
        """Should always return same instance when called multiple times"""
        # Reset singleton for test
        import deployment.agent_executor as module
        original_instance = module._agent_deployment_executor_instance

        # Create a mock instance
        mock_instance = MagicMock(spec=AgentDeploymentExecutor)
        module._agent_deployment_executor_instance = mock_instance

        try:
            executor1 = get_agent_deployment_executor()
            executor2 = get_agent_deployment_executor()

            # Should be the same instance
            assert executor1 is executor2
            assert executor1 is mock_instance
        finally:
            # Restore original
            module._agent_deployment_executor_instance = original_instance

    @pytest.mark.asyncio
    async def test_deploy_validates_compose_content(self, executor):
        """Should validate compose content before sending to agent"""
        invalid_compose = """
services:
  app:
    build: .
"""
        # Mock the agent manager to return an agent ID
        with patch.object(executor, '_get_agent_id_for_host', return_value="agent-123"):
            # Mock the status update
            with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock):
                result = await executor.deploy(
                    host_id="host-123",
                    deployment_id="deploy-123",
                    compose_content=invalid_compose,
                    project_name="test",
                )

                # Should fail validation
                assert result is False

    @pytest.mark.asyncio
    async def test_deploy_sends_command_to_agent(self, executor):
        """Should send deploy_compose command to agent"""
        valid_compose = """
services:
  web:
    image: nginx:alpine
"""
        # Mock dependencies
        mock_cmd_executor = MagicMock()
        mock_cmd_executor.execute_command = AsyncMock(
            return_value=MagicMock(success=True)
        )

        with patch.object(executor, '_get_agent_id_for_host', return_value="agent-123"):
            with patch.object(executor, '_get_command_executor', return_value=mock_cmd_executor):
                with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock):
                    result = await executor.deploy(
                        host_id="host-123",
                        deployment_id="deploy-123",
                        compose_content=valid_compose,
                        project_name="test-project",
                    )

                    assert result is True

                    # Verify command was sent
                    mock_cmd_executor.execute_command.assert_called_once()
                    call_args = mock_cmd_executor.execute_command.call_args

                    # Check agent_id
                    assert call_args[0][0] == "agent-123"

                    # Check command structure
                    command = call_args[0][1]
                    assert command["command"] == "deploy_compose"
                    assert command["payload"]["project_name"] == "test-project"
                    assert command["payload"]["action"] == "up"


class TestDeployProgressHandling:
    """Test handling of deploy_progress events from agent"""

    @pytest.fixture
    def mock_db(self):
        """Mock database manager"""
        db = MagicMock()
        session = MagicMock()
        db.get_session.return_value.__enter__ = MagicMock(return_value=session)
        db.get_session.return_value.__exit__ = MagicMock(return_value=False)
        return db

    @pytest.fixture
    def executor(self, mock_db):
        """Create executor with mocked dependencies"""
        return AgentDeploymentExecutor(database_manager=mock_db)

    @pytest.mark.asyncio
    async def test_handle_deploy_progress_updates_status(self, executor):
        """Should update deployment status on progress event"""
        payload = {
            "deployment_id": "deploy-123",
            "stage": "executing",
            "message": "Pulling images...",
        }

        with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
            await executor.handle_deploy_progress(payload)

            # Should update status
            mock_update.assert_called_once()
            # Check first positional arg is deployment_id
            call_args = mock_update.call_args
            assert call_args[0][0] == "deploy-123" or call_args.kwargs.get("deployment_id") == "deploy-123"

    @pytest.mark.asyncio
    async def test_handle_deploy_progress_ignores_terminal_stages(self, executor):
        """Should not update status for completed/failed stages (handled by deploy_complete)"""
        # completed stage is handled by deploy_complete, not deploy_progress
        payload = {
            "deployment_id": "deploy-123",
            "stage": "completed",
            "message": "Done",
        }

        with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
            await executor.handle_deploy_progress(payload)

            # Should NOT update status (completed is terminal)
            mock_update.assert_not_called()


class TestDeployCompleteHandling:
    """Test handling of deploy_complete events from agent"""

    @pytest.fixture
    def mock_db(self):
        """Mock database manager with deployment record"""
        db = MagicMock()
        session = MagicMock()

        # Mock deployment record
        deployment = MagicMock()
        deployment.host_id = "host-123"

        session.query.return_value.filter_by.return_value.first.return_value = deployment

        db.get_session.return_value.__enter__ = MagicMock(return_value=session)
        db.get_session.return_value.__exit__ = MagicMock(return_value=False)
        return db

    @pytest.fixture
    def executor(self, mock_db):
        """Create executor with mocked dependencies"""
        return AgentDeploymentExecutor(database_manager=mock_db)

    @pytest.mark.asyncio
    async def test_handle_deploy_complete_success(self, executor):
        """Should update database with container IDs on success"""
        payload = {
            "deployment_id": "deploy-123",
            "success": True,
            "services": {
                "web": {
                    "container_id": "abc123def456",
                    "container_name": "test_web_1",
                    "image": "nginx:alpine",
                    "status": "running",
                },
                "redis": {
                    "container_id": "xyz789ghi012",
                    "container_name": "test_redis_1",
                    "image": "redis:7",
                    "status": "running",
                },
            },
        }

        with patch.object(executor, '_link_containers_to_deployment', new_callable=AsyncMock) as mock_link:
            with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock):
                await executor.handle_deploy_complete(payload)

                # Should link containers
                mock_link.assert_called_once_with("deploy-123", payload["services"])

    @pytest.mark.asyncio
    async def test_handle_deploy_complete_failure(self, executor):
        """Should update status to failed on deployment failure"""
        payload = {
            "deployment_id": "deploy-123",
            "success": False,
            "error": "Image pull failed: nginx:invalid-tag",
        }

        with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
            await executor.handle_deploy_complete(payload)

            # Should update status to failed
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            # Check status arg (second positional) or keyword
            status = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("status")
            assert status == "failed"
            # Check error message
            error_msg = call_args.kwargs.get("error_message", "")
            assert "pull failed" in error_msg.lower() or "deployment failed" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_handle_deploy_complete_missing_deployment_id(self, executor):
        """Should handle missing deployment_id gracefully"""
        payload = {
            "success": True,
            "services": {},
        }

        # Should not raise exception
        await executor.handle_deploy_complete(payload)


class TestContainerIdNormalization:
    """Test that container IDs are normalized to 12-char short format"""

    @pytest.fixture
    def mock_db(self):
        """Mock database manager"""
        db = MagicMock()
        session = MagicMock()

        deployment = MagicMock()
        deployment.host_id = "host-123"

        session.query.return_value.filter_by.return_value.first.return_value = deployment
        session.query.return_value.filter.return_value.delete.return_value = None

        db.get_session.return_value.__enter__ = MagicMock(return_value=session)
        db.get_session.return_value.__exit__ = MagicMock(return_value=False)
        return db

    @pytest.fixture
    def executor(self, mock_db):
        """Create executor with mocked dependencies"""
        return AgentDeploymentExecutor(database_manager=mock_db)

    @pytest.mark.asyncio
    async def test_link_containers_truncates_long_ids(self, executor):
        """Should truncate 64-char container IDs to 12 chars"""
        deployment_id = "host-123:deploy-456"

        # Agent might send full 64-char IDs
        services = {
            "web": {
                "container_id": "abc123def456abc123def456abc123def456abc123def456abc123def456abc123",  # 64 chars
                "container_name": "test_web_1",
                "image": "nginx:alpine",
                "status": "running",
            },
        }

        # Call the method and verify IDs are truncated
        with patch('deployment.agent_executor.DeploymentContainer') as mock_dc:
            with patch('deployment.agent_executor.DeploymentMetadata') as mock_dm:
                await executor._link_containers_to_deployment(deployment_id, services)

                # DeploymentContainer should receive short ID
                dc_call = mock_dc.call_args
                assert len(dc_call[1]["container_id"]) == 12
                assert dc_call[1]["container_id"] == "abc123def456"
