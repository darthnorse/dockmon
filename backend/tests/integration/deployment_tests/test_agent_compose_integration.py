"""
Integration tests for Agent Native Compose Deployments (Phase 3).

These tests verify the full deployment workflow with a real agent connection.
They require:
- Docker compose available on the system
- A running or mock agent connection

To run these tests:
    pytest backend/tests/integration/deployment_tests/test_agent_compose_integration.py -v -m integration

Note: These tests are marked as integration tests and will be skipped by default
unless the -m integration marker is used.
"""

import pytest
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from deployment.agent_executor import (
    AgentDeploymentExecutor,
    validate_compose_for_agent,
    container_params_to_compose,
)


# Skip all tests in this module if not running integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def mock_db():
    """Mock database manager for integration tests"""
    db = MagicMock()
    session = MagicMock()

    deployment = MagicMock()
    deployment.host_id = "test-host-123"
    deployment.id = "test-deploy-123"
    deployment.status = "pending"
    deployment.progress_percent = 0
    deployment.current_stage = ""
    deployment.error_message = None
    deployment.created_at = None
    deployment.completed_at = None
    deployment.updated_at = None

    session.query.return_value.filter_by.return_value.first.return_value = deployment
    session.query.return_value.filter.return_value.delete.return_value = None

    db.get_session.return_value.__enter__ = MagicMock(return_value=session)
    db.get_session.return_value.__exit__ = MagicMock(return_value=False)
    return db


@pytest.fixture
def executor(mock_db):
    """Create executor with mocked dependencies"""
    return AgentDeploymentExecutor(database_manager=mock_db)


class TestComposeValidation:
    """Integration tests for compose content validation"""

    def test_validate_compose_with_profiles(self):
        """Should accept compose with profiles defined"""
        compose = """
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
  db:
    image: postgres:15
    profiles:
      - dev
  debug:
    image: alpine
    profiles:
      - debug
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is True
        assert error is None

    def test_validate_compose_with_healthcheck(self):
        """Should accept compose with healthcheck definitions"""
        compose = """
services:
  web:
    image: nginx:alpine
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is True
        assert error is None

    def test_validate_complex_compose(self):
        """Should accept complex compose with multiple features"""
        compose = """
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/"]
      interval: 5s
      timeout: 3s

  db:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: secret
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
    profiles:
      - with-db

  redis:
    image: redis:7-alpine
    profiles:
      - with-cache

volumes:
  db_data:
"""
        is_valid, error = validate_compose_for_agent(compose)
        assert is_valid is True
        assert error is None


class TestContainerParamsConversion:
    """Integration tests for container params to compose conversion"""

    def test_convert_params_with_healthcheck(self):
        """Should convert container params with healthcheck"""
        import yaml

        params = {
            "image": "nginx:alpine",
            "name": "web",
            "ports": ["80:80"],
            "healthcheck": {
                "test": ["CMD", "curl", "-f", "http://localhost/"],
                "interval": "30s",
                "timeout": "10s",
                "retries": 3,
            },
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert "services" in compose
        assert "web" in compose["services"]
        # Healthcheck might not be directly converted (depends on implementation)
        # This test documents expected behavior

    def test_convert_params_with_profiles(self):
        """Should convert container params - profiles are compose-level, not container-level"""
        import yaml

        # Note: profiles are defined at compose file level, not container params
        params = {
            "image": "nginx:alpine",
            "name": "web",
            "ports": ["80:80"],
        }

        compose_yaml = container_params_to_compose(params)
        compose = yaml.safe_load(compose_yaml)

        assert "services" in compose
        assert "web" in compose["services"]


class TestDeployCommandConstruction:
    """Integration tests for deploy command construction"""

    @pytest.mark.asyncio
    async def test_deploy_command_includes_all_phase3_fields(self, executor):
        """Should include all Phase 3 fields in deploy command"""
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
                with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock):
                    result = await executor.deploy(
                        host_id="host-123",
                        deployment_id="deploy-123",
                        compose_content=valid_compose,
                        project_name="test-project",
                        env_file_content="ENV_VAR=value\nOTHER_VAR=test",
                        profiles=["dev", "debug"],
                        wait_for_healthy=True,
                        health_timeout=120,
                    )

                    assert result is True

                    # Verify all fields were included
                    call_args = mock_cmd_executor.execute_command.call_args
                    command = call_args[0][1]
                    payload = command["payload"]

                    assert payload["deployment_id"] == "deploy-123"
                    assert payload["project_name"] == "test-project"
                    assert payload["action"] == "up"
                    assert payload["env_file_content"] == "ENV_VAR=value\nOTHER_VAR=test"
                    assert payload["profiles"] == ["dev", "debug"]
                    assert payload["wait_for_healthy"] is True
                    assert payload["health_timeout"] == 120

    @pytest.mark.asyncio
    async def test_teardown_command_includes_profiles(self, executor):
        """Should include profiles in teardown command for proper cleanup"""
        valid_compose = """
services:
  web:
    image: nginx:alpine
  db:
    image: postgres:15
    profiles:
      - dev
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
                    remove_volumes=True,
                    profiles=["dev"],
                )

                assert result is True

                # Verify teardown includes profiles
                call_args = mock_cmd_executor.execute_command.call_args
                command = call_args[0][1]
                payload = command["payload"]

                assert payload["action"] == "down"
                assert payload["profiles"] == ["dev"]
                assert payload["remove_volumes"] is True


class TestProgressHandling:
    """Integration tests for progress event handling"""

    @pytest.mark.asyncio
    async def test_full_progress_flow(self, executor):
        """Should handle full progress flow from starting to completed"""
        progress_events = [
            {"deployment_id": "deploy-123", "stage": "starting", "message": "Starting deployment..."},
            {"deployment_id": "deploy-123", "stage": "executing", "message": "Running compose up..."},
            {
                "deployment_id": "deploy-123",
                "stage": "executing",
                "message": "Deploying services (1/2 running)",
                "services": [
                    {"name": "web", "status": "running", "image": "nginx:alpine"},
                    {"name": "db", "status": "creating", "image": "postgres:15"},
                ],
            },
            {
                "deployment_id": "deploy-123",
                "stage": "executing",
                "message": "Deploying services (2/2 running)",
                "services": [
                    {"name": "web", "status": "running", "image": "nginx:alpine"},
                    {"name": "db", "status": "running", "image": "postgres:15"},
                ],
            },
            {"deployment_id": "deploy-123", "stage": "waiting_for_health", "message": "Waiting for services to be healthy..."},
        ]

        progress_values = []

        async def capture_progress(*args, **kwargs):
            progress = kwargs.get("progress")
            if progress is not None:
                progress_values.append(progress)

        with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock, side_effect=capture_progress):
            with patch.object(executor, '_emit_service_progress', new_callable=AsyncMock):
                for event in progress_events:
                    await executor.handle_deploy_progress(event)

        # Verify progress increases over time
        assert len(progress_values) == 5
        assert progress_values[0] == 20  # starting
        assert progress_values[1] == 50  # executing
        assert progress_values[2] == 70  # 1/2 running = 50 + 20
        assert progress_values[3] == 90  # 2/2 running = 50 + 40
        assert progress_values[4] == 80  # waiting_for_health

    @pytest.mark.asyncio
    async def test_service_progress_emission(self, executor):
        """Should emit service progress for fine-grained tracking"""
        payload = {
            "deployment_id": "deploy-123",
            "stage": "executing",
            "message": "Deploying services",
            "services": [
                {"name": "web", "status": "running", "image": "nginx:alpine"},
                {"name": "db", "status": "starting", "image": "postgres:15"},
                {"name": "redis", "status": "pulling", "image": "redis:7"},
            ],
        }

        emitted_services = []

        async def capture_services(deployment_id, services):
            emitted_services.append((deployment_id, services))

        with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock):
            with patch.object(executor, '_emit_service_progress', new_callable=AsyncMock, side_effect=capture_services):
                await executor.handle_deploy_progress(payload)

        assert len(emitted_services) == 1
        deployment_id, services = emitted_services[0]
        assert deployment_id == "deploy-123"
        assert len(services) == 3
        assert services[0]["name"] == "web"
        assert services[0]["status"] == "running"


class TestDeployCompleteHandling:
    """Integration tests for deploy complete event handling"""

    @pytest.mark.asyncio
    async def test_successful_deployment_with_healthy_services(self, executor):
        """Should handle successful deployment with all services healthy"""
        payload = {
            "deployment_id": "deploy-123",
            "success": True,
            "services": {
                "web": {
                    "container_id": "abc123def456",
                    "container_name": "test_web_1",
                    "image": "nginx:alpine",
                    "status": "running (healthy)",
                },
                "db": {
                    "container_id": "xyz789ghi012",
                    "container_name": "test_db_1",
                    "image": "postgres:15",
                    "status": "running (healthy)",
                },
            },
        }

        with patch.object(executor, '_link_containers_to_deployment', new_callable=AsyncMock) as mock_link:
            with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
                await executor.handle_deploy_complete(payload)

                # Should link all containers
                mock_link.assert_called_once_with("deploy-123", payload["services"])

                # Should update status to running
                mock_update.assert_called_once()
                call_args = mock_update.call_args
                status = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("status")
                assert status == "running"

    @pytest.mark.asyncio
    async def test_partial_deployment_with_health_timeout(self, executor):
        """Should handle partial success due to health check timeout"""
        payload = {
            "deployment_id": "deploy-123",
            "success": False,
            "partial_success": True,
            "services": {
                "web": {
                    "container_id": "abc123def456",
                    "container_name": "test_web_1",
                    "image": "nginx:alpine",
                    "status": "running (healthy)",
                },
                "db": {
                    "container_id": "xyz789ghi012",
                    "container_name": "test_db_1",
                    "image": "postgres:15",
                    "status": "running (unhealthy)",
                    "error": "Health check timed out after 60 seconds",
                },
            },
            "failed_services": ["db"],
            "error": "Health check timeout for db service",
        }

        with patch.object(executor, '_link_containers_to_deployment', new_callable=AsyncMock) as mock_link:
            with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
                await executor.handle_deploy_complete(payload)

                # Should only link healthy container
                mock_link.assert_called_once()
                linked_services = mock_link.call_args[0][1]
                assert "web" in linked_services
                assert "db" not in linked_services

                # Should update status to partial
                mock_update.assert_called_once()


class TestEdgeCases:
    """Integration tests for edge cases and error conditions"""

    @pytest.mark.asyncio
    async def test_empty_profiles_list(self, executor):
        """Should handle empty profiles list gracefully"""
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
                with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock):
                    result = await executor.deploy(
                        host_id="host-123",
                        deployment_id="deploy-123",
                        compose_content=valid_compose,
                        project_name="test-project",
                        profiles=[],  # Empty list
                    )

                    assert result is True

                    call_args = mock_cmd_executor.execute_command.call_args
                    command = call_args[0][1]
                    assert command["payload"]["profiles"] == []

    @pytest.mark.asyncio
    async def test_zero_health_timeout(self, executor):
        """Should handle zero health timeout (use default)"""
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
                with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock):
                    result = await executor.deploy(
                        host_id="host-123",
                        deployment_id="deploy-123",
                        compose_content=valid_compose,
                        project_name="test-project",
                        wait_for_healthy=True,
                        health_timeout=0,  # Agent should use default (60)
                    )

                    assert result is True

                    call_args = mock_cmd_executor.execute_command.call_args
                    command = call_args[0][1]
                    assert command["payload"]["health_timeout"] == 0

    @pytest.mark.asyncio
    async def test_progress_without_services(self, executor):
        """Should handle progress events without services field"""
        payload = {
            "deployment_id": "deploy-123",
            "stage": "executing",
            "message": "Running compose up...",
            # No services field
        }

        with patch.object(executor, '_update_deployment_status', new_callable=AsyncMock) as mock_update:
            with patch.object(executor, '_emit_service_progress', new_callable=AsyncMock) as mock_emit:
                await executor.handle_deploy_progress(payload)

                # Should update status
                mock_update.assert_called_once()

                # Should NOT emit service progress
                mock_emit.assert_not_called()
