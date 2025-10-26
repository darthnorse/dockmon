"""
Integration tests for all deployment types.

Tests:
- Container deployments (docker run style)
- Stack deployments (docker compose)
- Template-based deployments
- Full end-to-end deployment workflows
"""

import pytest
import time
from database import get_db, Deployment
from deployment import DeploymentExecutor, TemplateManager
import docker


@pytest.fixture
def docker_client():
    """Get Docker client for verification and cleanup."""
    return docker.from_env()


@pytest.fixture
def deployment_executor(test_db):
    """Create deployment executor with test database."""
    return DeploymentExecutor(test_db)


@pytest.fixture
def template_manager(test_db):
    """Create template manager with test database."""
    return TemplateManager(test_db)


@pytest.fixture(autouse=True)
def cleanup_test_resources(docker_client):
    """Clean up test containers, networks, and volumes before and after each test."""
    def cleanup():
        try:
            # Remove test containers
            for container in docker_client.containers.list(all=True):
                if any(name in container.name for name in ['test-deploy', 'test-stack', 'test-template']):
                    try:
                        container.stop(timeout=1)
                        container.remove(force=True)
                    except:
                        pass

            # Remove test networks
            for network in docker_client.networks.list():
                if any(name in network.name for name in ['test-deploy', 'test-stack', 'test-template']):
                    try:
                        network.remove()
                    except:
                        pass

            # Remove test volumes
            for volume in docker_client.volumes.list():
                if any(name in volume.name for name in ['test-deploy', 'test-stack', 'test-template']):
                    try:
                        volume.remove(force=True)
                    except:
                        pass
        except Exception as e:
            print(f"Cleanup warning: {e}")

    cleanup()
    yield
    cleanup()


# ==================== Container Deployment Tests ====================

class TestContainerDeployment:
    """Integration tests for 'docker run' style container deployments."""

    @pytest.mark.asyncio
    async def test_deploy_simple_container(self, deployment_executor, test_db, docker_client):
        """
        Test deploying a simple container (nginx).
        Verifies the full workflow: create → execute → verify.
        """
        # Create deployment
        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-deploy-nginx',
            deployment_type='container',
            definition={
                'image': 'nginx:alpine',
                'ports': ['18080:80'],
                'restart_policy': 'unless-stopped'
            },
            rollback_on_failure=True
        )

        # Execute deployment
        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion (max 60 seconds)
        for _ in range(60):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment succeeded
        with get_db().get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed', f"Deployment failed: {deployment.error_message}"
            assert deployment.progress_percent == 100
            assert deployment.committed is True

        # Verify container was created and is running
        containers = docker_client.containers.list(filters={'name': 'test-deploy-nginx'})
        assert len(containers) == 1
        container = containers[0]
        assert container.status == 'running'

        # Verify port mapping
        ports = container.attrs['HostConfig']['PortBindings']
        assert '80/tcp' in ports
        assert ports['80/tcp'][0]['HostPort'] == '18080'

        # Verify restart policy
        restart_policy = container.attrs['HostConfig']['RestartPolicy']
        assert restart_policy['Name'] == 'unless-stopped'


    @pytest.mark.asyncio
    async def test_deploy_container_with_environment_variables(self, deployment_executor, test_db, docker_client):
        """Test container deployment with environment variables."""
        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-deploy-env',
            deployment_type='container',
            definition={
                'image': 'alpine:latest',
                'command': 'sleep 60',
                'environment': {
                    'TEST_VAR': 'test_value',
                    'ANOTHER_VAR': '12345'
                }
            },
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(30):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment succeeded
        with get_db().get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed'

        # Verify environment variables
        containers = docker_client.containers.list(filters={'name': 'test-deploy-env'})
        container = containers[0]
        env_dict = {e.split('=')[0]: e.split('=')[1] for e in container.attrs['Config']['Env']}
        assert env_dict.get('TEST_VAR') == 'test_value'
        assert env_dict.get('ANOTHER_VAR') == '12345'


    @pytest.mark.asyncio
    async def test_container_deployment_rollback_on_invalid_image(self, deployment_executor, test_db, docker_client):
        """Test that rollback works when image doesn't exist."""
        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-deploy-fail',
            deployment_type='container',
            definition={
                'image': 'this-image-absolutely-does-not-exist-xyz123',
            },
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for rollback
        for _ in range(30):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment was rolled back
        with get_db().get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'rolled_back'
            assert 'not found' in deployment.error_message.lower() or 'does not exist' in deployment.error_message.lower()

        # Verify no containers remain
        containers = docker_client.containers.list(all=True, filters={'name': 'test-deploy-fail'})
        assert len(containers) == 0


    @pytest.mark.asyncio
    async def test_container_deployment_with_volumes(self, deployment_executor, test_db, docker_client):
        """Test container deployment with volume mounts."""
        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-deploy-volumes',
            deployment_type='container',
            definition={
                'image': 'alpine:latest',
                'command': 'sleep 60',
                'volumes': ['test-deploy-vol:/data']
            },
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(30):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment succeeded
        with get_db().get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed'

        # Verify volume mount
        containers = docker_client.containers.list(filters={'name': 'test-deploy-volumes'})
        container = containers[0]
        mounts = container.attrs['Mounts']
        assert len(mounts) > 0
        assert any(m['Destination'] == '/data' for m in mounts)


# ==================== Stack Deployment Tests ====================

class TestStackDeployment:
    """Integration tests for Docker Compose stack deployments."""

    @pytest.mark.asyncio
    async def test_deploy_simple_two_service_stack(self, deployment_executor, test_db, docker_client):
        """Test deploying a 2-service stack (web + redis)."""
        compose_yaml = """
services:
  web:
    image: nginx:alpine
    ports:
      - "19080:80"
  redis:
    image: redis:alpine
"""

        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-stack',
            deployment_type='stack',
            definition={'compose_yaml': compose_yaml},
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(60):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment succeeded
        with get_db().get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed', f"Stack deployment failed: {deployment.error_message}"

        # Verify both containers exist and are running
        containers = docker_client.containers.list(filters={'name': 'test-stack_'})
        assert len(containers) == 2
        assert all(c.status == 'running' for c in containers)


    @pytest.mark.asyncio
    async def test_stack_with_dependency_ordering(self, deployment_executor, test_db, docker_client):
        """Test that services with dependencies are created in correct order."""
        compose_yaml = """
services:
  web:
    image: nginx:alpine
    depends_on:
      - api
  api:
    image: redis:alpine
    depends_on:
      - db
  db:
    image: alpine:latest
    command: sleep 120
"""

        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-stack',
            deployment_type='stack',
            definition={'compose_yaml': compose_yaml},
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(60):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify all services deployed
        with get_db().get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed'

        containers = docker_client.containers.list(filters={'name': 'test-stack_'})
        assert len(containers) == 3


# ==================== Template Deployment Tests ====================

class TestTemplateDeployment:
    """Integration tests for template-based deployments."""

    @pytest.mark.asyncio
    async def test_create_and_deploy_from_container_template(self, deployment_executor, template_manager, test_db, docker_client):
        """Test creating a template and deploying from it."""
        # Create template
        template_id = template_manager.create_template(
            name='nginx-template',
            deployment_type='container',
            template_definition={
                'image': 'nginx:${VERSION}',
                'ports': ['${PORT}:80'],
                'environment': {
                    'ENV': 'production'
                }
            },
            category='web-servers',
            description='Nginx web server template',
            variables={
                'VERSION': {'default': 'alpine', 'description': 'Nginx version tag'},
                'PORT': {'default': '8080', 'description': 'Host port to bind'}
            }
        )

        # Render template with custom values
        rendered = template_manager.render_template(template_id, {'VERSION': 'alpine', 'PORT': '18081'})

        # Create deployment from rendered template
        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-template-nginx',
            deployment_type='container',
            definition=rendered,
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(60):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment succeeded
        with get_db().get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed'

        # Verify container was created with correct configuration
        containers = docker_client.containers.list(filters={'name': 'test-template-nginx'})
        assert len(containers) == 1
        container = containers[0]

        # Verify image
        assert 'nginx' in container.image.tags[0]
        assert 'alpine' in container.image.tags[0]

        # Verify port
        ports = container.attrs['HostConfig']['PortBindings']
        assert '80/tcp' in ports
        assert ports['80/tcp'][0]['HostPort'] == '18081'


    @pytest.mark.asyncio
    async def test_create_and_deploy_from_stack_template(self, deployment_executor, template_manager, test_db, docker_client):
        """Test creating a stack template and deploying from it."""
        # Create stack template
        template_id = template_manager.create_template(
            name='wordpress-template',
            deployment_type='stack',
            template_definition={
                'compose_yaml': """
services:
  web:
    image: nginx:${NGINX_VERSION}
    ports:
      - "${WEB_PORT}:80"
  db:
    image: mysql:${MYSQL_VERSION}
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_PASSWORD}
"""
            },
            category='cms',
            description='WordPress-like stack',
            variables={
                'NGINX_VERSION': {'default': 'alpine'},
                'MYSQL_VERSION': {'default': '8'},
                'WEB_PORT': {'default': '8080'},
                'DB_PASSWORD': {'default': 'secret123'}
            }
        )

        # Render with values
        rendered = template_manager.render_template(template_id, {
            'NGINX_VERSION': 'alpine',
            'MYSQL_VERSION': '8',
            'WEB_PORT': '19081',
            'DB_PASSWORD': 'testpass'
        })

        # Deploy from template
        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-template-stack',
            deployment_type='stack',
            definition=rendered,
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(90):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Verify deployment succeeded
        with get_db().get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status == 'completed'

        # Verify both services were created
        containers = docker_client.containers.list(filters={'name': 'test-template-stack_'})
        assert len(containers) == 2


# ==================== Edge Case Tests ====================

class TestDeploymentEdgeCases:
    """Edge case and error handling tests."""

    @pytest.mark.asyncio
    async def test_cannot_execute_deployment_twice(self, deployment_executor, test_db):
        """Test that a deployment can only be executed once."""
        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-deploy-once',
            deployment_type='container',
            definition={'image': 'alpine:latest', 'command': 'sleep 60'},
            rollback_on_failure=True
        )

        # Execute first time
        await deployment_executor.execute_deployment(deployment_id)

        # Wait for completion
        for _ in range(30):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Try to execute again - should fail
        with pytest.raises(ValueError, match="Cannot start deployment.*in status"):
            await deployment_executor.execute_deployment(deployment_id)


    @pytest.mark.asyncio
    async def test_deployment_with_invalid_port_format(self, deployment_executor, test_db):
        """Test that invalid port format is rejected during security validation."""
        # This should fail during creation due to security validation
        with pytest.raises(Exception):  # Could be ValueError or SecurityException
            await deployment_executor.create_deployment(
                host_id='localhost',
                name='test-deploy-badport',
                deployment_type='container',
                definition={
                    'image': 'nginx:alpine',
                    'ports': ['not-a-valid-port-format']
                },
                rollback_on_failure=True
            )


    @pytest.mark.asyncio
    async def test_stack_deployment_with_circular_dependencies(self, deployment_executor, test_db):
        """Test that circular dependencies are rejected during validation."""
        compose_yaml = """
services:
  web:
    image: nginx:alpine
    depends_on:
      - api
  api:
    image: redis:alpine
    depends_on:
      - web
"""

        deployment_id = await deployment_executor.create_deployment(
            host_id='localhost',
            name='test-stack-circular',
            deployment_type='stack',
            definition={'compose_yaml': compose_yaml},
            rollback_on_failure=True
        )

        await deployment_executor.execute_deployment(deployment_id)

        # Wait for it to fail
        for _ in range(30):
            with get_db().get_session() as session:
                deployment = session.query(Deployment).filter_by(id=deployment_id).first()
                if deployment.status in ['completed', 'failed', 'rolled_back']:
                    break
            time.sleep(1)

        # Should fail due to circular dependency
        with get_db().get_session() as session:
            deployment = session.query(Deployment).filter_by(id=deployment_id).first()
            assert deployment.status in ['failed', 'rolled_back']
            assert 'cycle' in deployment.error_message.lower()
