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


class TestPartialFailureHandling:
    """Test handling of partial deployment failures"""

    @pytest.fixture
    def mock_db(self):
        """Mock database manager with deployment record"""
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
    async def test_handle_partial_success(self, executor):
        """Should handle partial success - some services running, others failed"""
        payload = {
            "deployment_id": "deploy-123",
            "success": False,
            "partial_success": True,
            "services": {
                "web": {
                    "container_id": "abc123def456",
                    "container_name": "test_web_1",
                    "image": "nginx:alpine",
                    "status": "running",
                },
                "db": {
                    "container_id": "xyz789ghi012",
                    "container_name": "test_db_1",
                    "image": "postgres:15",
                    "status": "exited (1)",
                    "error": "Database init failed",
                },
            },
            "failed_services": ["db"],
            "error": "Partial deployment: 1/2 services running",
        }

        with patch.object(executor, '_link_containers_to_deployment', new_callable=AsyncMock) as mock_link:
            with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
                await executor.handle_deploy_complete(payload)

                # Should link only successful containers (web, not db)
                mock_link.assert_called_once()
                linked_services = mock_link.call_args[0][1]
                assert "web" in linked_services
                assert "db" not in linked_services

                # Should update status to partial
                mock_update.assert_called_once()
                call_args = mock_update.call_args
                status = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("status")
                assert status == "partial"

    @pytest.mark.asyncio
    async def test_handle_partial_success_no_running_services(self, executor):
        """Should handle case where partial_success=True but no services actually running"""
        payload = {
            "deployment_id": "deploy-123",
            "success": False,
            "partial_success": True,
            "services": {
                "web": {
                    "container_id": "abc123def456",
                    "container_name": "test_web_1",
                    "status": "exited (1)",
                },
            },
            "failed_services": ["web"],
            "error": "All services failed",
        }

        with patch.object(executor, '_link_containers_to_deployment', new_callable=AsyncMock) as mock_link:
            with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
                await executor.handle_deploy_complete(payload)

                # Should not link any containers (all failed)
                mock_link.assert_not_called()

                # Should still update status to partial (as indicated by agent)
                mock_update.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_full_failure_no_partial(self, executor):
        """Should handle full failure when partial_success=False"""
        payload = {
            "deployment_id": "deploy-123",
            "success": False,
            "partial_success": False,
            "services": {},
            "error": "Image pull failed",
        }

        with patch.object(executor, '_link_containers_to_deployment', new_callable=AsyncMock) as mock_link:
            with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
                await executor.handle_deploy_complete(payload)

                # Should not link any containers
                mock_link.assert_not_called()

                # Should update status to failed
                mock_update.assert_called_once()
                call_args = mock_update.call_args
                status = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("status")
                assert status == "failed"

    def test_build_partial_failure_message(self, executor):
        """Should build detailed error message for partial failures"""
        services = {
            "web": {"status": "running"},
            "db": {"status": "exited (1)", "error": "Init failed"},
            "redis": {"status": "exited (137)"},
        }
        failed_services = ["db", "redis"]
        original_error = "Some services failed"

        message = executor._build_partial_failure_message(services, failed_services, original_error)

        # Verify message contains key info
        assert "1/3 services running" in message
        assert "Failed services:" in message
        assert "db:" in message
        assert "exited (1)" in message
        assert "Init failed" in message
        assert "redis:" in message

    def test_build_partial_failure_message_no_error_details(self, executor):
        """Should handle services without error details"""
        services = {
            "web": {"status": "running"},
            "db": {"status": "exited (1)"},  # No error field
        }
        failed_services = ["db"]

        message = executor._build_partial_failure_message(services, failed_services, None)

        assert "1/2 services running" in message
        assert "db:" in message
        assert "exited (1)" in message


class TestStateMachinePartialStatus:
    """Test state machine supports partial status"""

    def test_partial_status_is_valid(self):
        """Should recognize 'partial' as valid status"""
        from deployment.state_machine import DeploymentStateMachine

        sm = DeploymentStateMachine()
        assert sm.validate_state('partial')

    def test_can_transition_to_partial(self):
        """Should allow transition to partial from execution states"""
        from deployment.state_machine import DeploymentStateMachine

        sm = DeploymentStateMachine()

        # Can transition to partial from various states
        assert sm.can_transition('validating', 'partial')
        assert sm.can_transition('pulling_image', 'partial')
        assert sm.can_transition('creating', 'partial')
        assert sm.can_transition('starting', 'partial')

    def test_partial_allows_retry(self):
        """Should allow retry from partial state (transition to validating)"""
        from deployment.state_machine import DeploymentStateMachine

        sm = DeploymentStateMachine()

        # partial allows retry via validating
        next_states = sm.get_valid_next_states('partial')
        assert next_states == ['validating']

    def test_partial_sets_completed_at(self):
        """Should set completed_at when transitioning to partial"""
        from deployment.state_machine import DeploymentStateMachine

        sm = DeploymentStateMachine()

        # Mock deployment
        deployment = MagicMock()
        deployment.status = 'starting'
        deployment.completed_at = None

        sm.transition(deployment, 'partial')

        assert deployment.status == 'partial'
        assert deployment.completed_at is not None


# Phase 3 Tests

class TestComposeProfiles:
    """Test compose profiles support (Phase 3)"""

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
    async def test_deploy_includes_profiles(self, executor):
        """Should include profiles in deploy command"""
        valid_compose = """
services:
  web:
    image: nginx:alpine
  db:
    image: postgres:15
    profiles: [dev]
"""
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
                        profiles=["dev", "debug"],
                    )

                    assert result is True

                    # Verify profiles were included
                    call_args = mock_cmd_executor.execute_command.call_args
                    command = call_args[0][1]
                    assert command["payload"]["profiles"] == ["dev", "debug"]

    @pytest.mark.asyncio
    async def test_teardown_includes_profiles(self, executor):
        """Should include profiles in teardown command"""
        valid_compose = """
services:
  web:
    image: nginx:alpine
"""
        mock_cmd_executor = MagicMock()
        mock_cmd_executor.execute_command = AsyncMock(
            return_value=MagicMock(success=True)
        )

        with patch.object(executor, '_get_agent_id_for_host', return_value="agent-123"):
            with patch.object(executor, '_get_command_executor', return_value=mock_cmd_executor):
                result = await executor.teardown(
                    host_id="host-123",
                    deployment_id="deploy-123",
                    project_name="test-project",
                    compose_content=valid_compose,
                    profiles=["dev"],
                )

                assert result is True

                # Verify profiles were included
                call_args = mock_cmd_executor.execute_command.call_args
                command = call_args[0][1]
                assert command["payload"]["profiles"] == ["dev"]


class TestHealthAwareDeployments:
    """Test health-aware deployments (Phase 3)"""

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
    async def test_deploy_with_health_check(self, executor):
        """Should include health check options in deploy command"""
        valid_compose = """
services:
  web:
    image: nginx:alpine
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/"]
      interval: 5s
      timeout: 3s
"""
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
                        wait_for_healthy=True,
                        health_timeout=120,
                    )

                    assert result is True

                    # Verify health check options were included
                    call_args = mock_cmd_executor.execute_command.call_args
                    command = call_args[0][1]
                    assert command["payload"]["wait_for_healthy"] is True
                    assert command["payload"]["health_timeout"] == 120


class TestFineGrainedProgress:
    """Test fine-grained progress reporting (Phase 3)"""

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
    async def test_handle_service_progress(self, executor):
        """Should handle service-level progress events"""
        payload = {
            "deployment_id": "deploy-123",
            "stage": "executing",
            "message": "Deploying services (1/3 running)",
            "services": [
                {"name": "web", "status": "running", "image": "nginx:alpine"},
                {"name": "db", "status": "creating", "image": "postgres:15"},
                {"name": "redis", "status": "pulling", "image": "redis:7"},
            ],
        }

        with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
            with patch.object(executor, '_emit_service_progress', new_callable=AsyncMock) as mock_emit:
                await executor.handle_deploy_progress(payload)

                # Should update status
                mock_update.assert_called_once()

                # Should emit service progress
                mock_emit.assert_called_once_with("deploy-123", payload["services"])

    @pytest.mark.asyncio
    async def test_progress_calculation_with_services(self, executor):
        """Should calculate progress based on running services"""
        payload = {
            "deployment_id": "deploy-123",
            "stage": "executing",
            "message": "Deploying",
            "services": [
                {"name": "web", "status": "running"},
                {"name": "db", "status": "running"},
                {"name": "redis", "status": "creating"},
                {"name": "cache", "status": "pulling"},
            ],
        }

        with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
            with patch.object(executor, '_emit_service_progress', new_callable=AsyncMock):
                await executor.handle_deploy_progress(payload)

                # 2/4 services running = 50% of 40 (after 50 base) = 70
                call_args = mock_update.call_args
                progress = call_args.kwargs.get("progress") or call_args[1].get("progress")
                assert progress == 70  # 50 + (2/4 * 40)

    @pytest.mark.asyncio
    async def test_handle_waiting_for_health_stage(self, executor):
        """Should handle waiting_for_health stage"""
        payload = {
            "deployment_id": "deploy-123",
            "stage": "waiting_for_health",
            "message": "Waiting for services to be healthy...",
        }

        with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
            await executor.handle_deploy_progress(payload)

            mock_update.assert_called_once()
            call_args = mock_update.call_args

            # Progress should be 80 for waiting_for_health
            progress = call_args.kwargs.get("progress") or call_args[1].get("progress")
            assert progress == 80
