# DockMon Container & Stack Deployment - Implementation Guide

**Version:** 2.1.0
**Status:** Design Document
**Created:** 2025-10-23
**Target Release:** v2.1

---

## Table of Contents

1. [Overview](#overview)
2. [Database Schema](#database-schema)
3. [Backend Implementation](#backend-implementation)
4. [Frontend Implementation](#frontend-implementation)
5. [Implementation Phases](#implementation-phases)
6. [Security Considerations](#security-considerations)
7. [Testing Strategy](#testing-strategy)
8. [Migration Path](#migration-path)

---

## Overview

### Goals

Add container and stack deployment capabilities to DockMon, making it a complete Docker management platform competitive with Portainer.

### Scope

**Phase 1: Single Container Deployment**
- Deploy containers from Docker images
- Basic configuration (ports, env vars, volumes, networks)
- Form-based UI with validation
- Works on local and remote hosts (via existing mTLS connections)

**Phase 2: Docker Compose Stack Deployment**
- Deploy multi-container applications via docker-compose
- YAML editor with syntax validation
- Stack lifecycle management (deploy, update, remove)
- Template library for common stacks

### Non-Goals (Future Versions)

- Docker Swarm stack deployment
- Kubernetes deployment
- Building images from Dockerfile
- Container registry management
- Git repository integration (initially)

---

## Database Schema

### New Tables

#### 1. `deployments`

Tracks all deployment operations (containers and stacks).

```sql
CREATE TABLE deployments (
    id VARCHAR(36) PRIMARY KEY,  -- UUID
    host_id VARCHAR(36) NOT NULL,
    deployment_type VARCHAR(20) NOT NULL,  -- 'container' or 'stack'
    name VARCHAR(255) NOT NULL,  -- Container/stack name
    status VARCHAR(20) NOT NULL,  -- 'pending', 'deploying', 'running', 'failed', 'removed'

    -- Configuration (JSON)
    config JSON NOT NULL,  -- Deployment configuration

    -- Metadata
    created_by VARCHAR(255),  -- User who created it
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deployed_at TIMESTAMP,  -- When deployment succeeded

    -- Results
    container_ids JSON,  -- Array of container IDs created
    error_message TEXT,  -- If deployment failed

    -- Tracking
    last_checked TIMESTAMP,

    FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE,
    INDEX idx_host_type (host_id, deployment_type),
    INDEX idx_status (status),
    INDEX idx_name (name)
);
```

**Example records:**

```json
// Single container deployment
{
  "id": "dep_abc123",
  "host_id": "host_123",
  "deployment_type": "container",
  "name": "my-nginx",
  "status": "running",
  "config": {
    "image": "nginx:latest",
    "ports": {"80/tcp": 8080},
    "environment": {"KEY": "value"},
    "volumes": {"/host/path": {"bind": "/container/path", "mode": "rw"}},
    "restart_policy": {"Name": "unless-stopped"},
    "labels": {"dockmon.managed": "true"}
  },
  "created_by": "admin@example.com",
  "created_at": "2025-10-23T10:00:00Z",
  "deployed_at": "2025-10-23T10:00:05Z",
  "container_ids": ["abc123def456"]
}

// Stack deployment
{
  "id": "dep_xyz789",
  "host_id": "host_123",
  "deployment_type": "stack",
  "name": "wordpress-stack",
  "status": "running",
  "config": {
    "compose_file": "version: '3.8'\nservices:\n  wordpress:\n    image: wordpress:latest\n    ...",
    "env_file": "DB_PASSWORD=secret\n...",
    "working_dir": "/opt/dockmon/stacks/wordpress-stack"
  },
  "created_by": "admin@example.com",
  "created_at": "2025-10-23T11:00:00Z",
  "deployed_at": "2025-10-23T11:00:15Z",
  "container_ids": ["wordpress_web_1", "wordpress_db_1"]
}
```

#### 2. `deployment_templates`

Pre-configured templates for common applications.

```sql
CREATE TABLE deployment_templates (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(50),  -- 'web', 'database', 'monitoring', 'media', etc.
    icon_url VARCHAR(500),

    template_type VARCHAR(20) NOT NULL,  -- 'container' or 'stack'
    template_config JSON NOT NULL,  -- Template configuration

    -- Metadata
    is_official BOOLEAN DEFAULT FALSE,  -- Official DockMon template
    is_enabled BOOLEAN DEFAULT TRUE,
    downloads INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_category (category),
    INDEX idx_type (template_type)
);
```

**Example templates:**

```json
// Nginx container template
{
  "id": "tmpl_nginx",
  "name": "Nginx Web Server",
  "description": "High-performance web server and reverse proxy",
  "category": "web",
  "icon_url": "https://cdn.dockmon.io/icons/nginx.png",
  "template_type": "container",
  "template_config": {
    "image": "nginx:latest",
    "ports": {"80/tcp": null},  // User must specify
    "volumes": {
      "/path/to/html": {"bind": "/usr/share/nginx/html", "mode": "ro"}
    },
    "restart_policy": {"Name": "unless-stopped"}
  },
  "is_official": true
}

// WordPress stack template
{
  "id": "tmpl_wordpress",
  "name": "WordPress with MySQL",
  "description": "Complete WordPress blog with MySQL database",
  "category": "web",
  "template_type": "stack",
  "template_config": {
    "compose_file": "version: '3.8'\nservices:\n  wordpress:\n    image: wordpress:latest\n    ports:\n      - '${WP_PORT:-8080}:80'\n    environment:\n      WORDPRESS_DB_HOST: db\n      WORDPRESS_DB_USER: wordpress\n      WORDPRESS_DB_PASSWORD: ${DB_PASSWORD}\n      WORDPRESS_DB_NAME: wordpress\n    volumes:\n      - wordpress_data:/var/www/html\n    depends_on:\n      - db\n    restart: unless-stopped\n\n  db:\n    image: mysql:8.0\n    environment:\n      MYSQL_DATABASE: wordpress\n      MYSQL_USER: wordpress\n      MYSQL_PASSWORD: ${DB_PASSWORD}\n      MYSQL_RANDOM_ROOT_PASSWORD: '1'\n    volumes:\n      - db_data:/var/lib/mysql\n    restart: unless-stopped\n\nvolumes:\n  wordpress_data:\n  db_data:\n",
    "required_env_vars": ["DB_PASSWORD", "WP_PORT"]
  },
  "is_official": true
}
```

#### 3. `deployment_history`

Audit log of all deployment operations.

```sql
CREATE TABLE deployment_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    deployment_id VARCHAR(36) NOT NULL,

    action VARCHAR(50) NOT NULL,  -- 'create', 'update', 'start', 'stop', 'remove'
    status VARCHAR(20) NOT NULL,  -- 'success', 'failed'

    -- Context
    triggered_by VARCHAR(255),  -- User or 'system'

    -- Details
    changes JSON,  -- What changed (for updates)
    error_message TEXT,

    -- Timing
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER,

    FOREIGN KEY (deployment_id) REFERENCES deployments(id) ON DELETE CASCADE,
    INDEX idx_deployment (deployment_id),
    INDEX idx_action (action),
    INDEX idx_timestamp (started_at)
);
```

### Schema Changes to Existing Tables

#### Update `containers` table

Add column to track if container is managed by DockMon deployment:

```sql
ALTER TABLE containers
ADD COLUMN deployment_id VARCHAR(36),
ADD COLUMN is_managed BOOLEAN DEFAULT FALSE,
ADD FOREIGN KEY (deployment_id) REFERENCES deployments(id) ON DELETE SET NULL,
ADD INDEX idx_deployment (deployment_id);
```

#### Update `events` table

Add deployment-related event types:

```sql
-- No schema change needed, just new event types:
-- 'deployment_created'
-- 'deployment_started'
-- 'deployment_failed'
-- 'deployment_updated'
-- 'deployment_removed'
```

---

## Backend Implementation

### New Modules

#### 1. `backend/deployment/`

Main deployment module structure:

```
backend/deployment/
├── __init__.py
├── api.py                 # FastAPI routes
├── container_deployer.py  # Single container deployment
├── stack_deployer.py      # Docker Compose stack deployment
├── validator.py           # Config validation
├── templates.py           # Template management
└── models.py              # Pydantic models
```

### API Endpoints

#### Container Deployment

```python
# POST /api/v2/deployments/container
@router.post("/deployments/container")
async def deploy_container(
    request: ContainerDeploymentRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Deploy a single container

    Request body:
    {
        "host_id": "host_123",
        "name": "my-nginx",
        "image": "nginx:latest",
        "ports": {"80/tcp": 8080},
        "environment": {"KEY": "value"},
        "volumes": {"/host/path": {"bind": "/container/path", "mode": "rw"}},
        "networks": ["bridge"],
        "restart_policy": "unless-stopped",
        "labels": {"app": "web"}
    }

    Response:
    {
        "deployment_id": "dep_abc123",
        "status": "deploying",
        "container_id": null  // Populated when deployment completes
    }
    """
    pass

# GET /api/v2/deployments
@router.get("/deployments")
async def list_deployments(
    host_id: Optional[str] = None,
    deployment_type: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """List all deployments with optional filters"""
    pass

# GET /api/v2/deployments/{deployment_id}
@router.get("/deployments/{deployment_id}")
async def get_deployment(deployment_id: str):
    """Get deployment details"""
    pass

# DELETE /api/v2/deployments/{deployment_id}
@router.delete("/deployments/{deployment_id}")
async def remove_deployment(deployment_id: str):
    """Remove deployment (stops and removes containers)"""
    pass

# POST /api/v2/deployments/{deployment_id}/update
@router.post("/deployments/{deployment_id}/update")
async def update_deployment(
    deployment_id: str,
    request: DeploymentUpdateRequest
):
    """Update deployment configuration (recreates containers)"""
    pass
```

#### Stack Deployment

```python
# POST /api/v2/deployments/stack
@router.post("/deployments/stack")
async def deploy_stack(
    request: StackDeploymentRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Deploy a Docker Compose stack

    Request body:
    {
        "host_id": "host_123",
        "name": "wordpress-stack",
        "compose_file": "version: '3.8'\nservices:\n  ...",
        "env_vars": {"DB_PASSWORD": "secret"},
        "working_dir": "/opt/dockmon/stacks/wordpress-stack"  // Optional
    }

    Response:
    {
        "deployment_id": "dep_xyz789",
        "status": "deploying",
        "container_ids": []  // Populated when deployment completes
    }
    """
    pass

# POST /api/v2/deployments/stack/validate
@router.post("/deployments/stack/validate")
async def validate_compose_file(request: ComposeValidationRequest):
    """
    Validate docker-compose.yml syntax

    Returns:
    {
        "valid": true,
        "errors": [],
        "warnings": ["Using deprecated 'version' field"],
        "services": ["web", "db"],
        "volumes": ["data"],
        "networks": ["default"]
    }
    """
    pass
```

#### Templates

```python
# GET /api/v2/templates
@router.get("/templates")
async def list_templates(
    category: Optional[str] = None,
    template_type: Optional[str] = None
):
    """List available templates"""
    pass

# GET /api/v2/templates/{template_id}
@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """Get template details"""
    pass

# POST /api/v2/deployments/from-template
@router.post("/deployments/from-template")
async def deploy_from_template(
    template_id: str,
    overrides: dict,
    current_user: User = Depends(get_current_user)
):
    """Deploy container/stack from template with user overrides"""
    pass
```

### Core Implementation Classes

#### `container_deployer.py`

```python
from docker import DockerClient
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ContainerDeployer:
    """Handles single container deployment"""

    def __init__(self, clients: Dict[str, DockerClient], event_logger):
        self.clients = clients
        self.event_logger = event_logger

    async def deploy(
        self,
        host_id: str,
        deployment_id: str,
        config: Dict[str, Any]
    ) -> str:
        """
        Deploy a single container

        Args:
            host_id: Target Docker host
            deployment_id: Deployment record ID
            config: Container configuration

        Returns:
            container_id: ID of created container

        Raises:
            DeploymentError: If deployment fails
        """
        from utils.async_docker import async_docker_call

        if host_id not in self.clients:
            raise DeploymentError(f"Host {host_id} not found")

        client = self.clients[host_id]

        try:
            # Validate configuration
            self._validate_config(config)

            # Pull image if needed
            image = config['image']
            logger.info(f"Pulling image {image}")
            await self._pull_image(client, image)

            # Prepare container config
            container_config = self._prepare_container_config(config, deployment_id)

            # Create and start container
            logger.info(f"Creating container {config['name']}")
            container = await async_docker_call(
                client.containers.create,
                **container_config
            )

            logger.info(f"Starting container {container.id}")
            await async_docker_call(container.start)

            # Log event
            self.event_logger.log_deployment_event(
                action="container_deployed",
                deployment_id=deployment_id,
                container_id=container.id,
                host_id=host_id,
                success=True
            )

            return container.id

        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            self.event_logger.log_deployment_event(
                action="container_deploy_failed",
                deployment_id=deployment_id,
                host_id=host_id,
                success=False,
                error_message=str(e)
            )
            raise DeploymentError(f"Failed to deploy container: {e}")

    def _validate_config(self, config: Dict[str, Any]):
        """Validate container configuration"""
        required = ['image', 'name']
        for field in required:
            if field not in config:
                raise ValidationError(f"Missing required field: {field}")

        # Validate port mappings
        if 'ports' in config:
            self._validate_ports(config['ports'])

        # Validate volumes
        if 'volumes' in config:
            self._validate_volumes(config['volumes'])

    def _validate_ports(self, ports: Dict[str, Any]):
        """Validate port mappings"""
        for container_port, host_port in ports.items():
            # Validate format (e.g., "80/tcp")
            if '/' not in container_port:
                raise ValidationError(
                    f"Port must include protocol: {container_port} -> 80/tcp"
                )

            # Validate host port if specified
            if host_port is not None:
                if not isinstance(host_port, int) or host_port < 1 or host_port > 65535:
                    raise ValidationError(f"Invalid host port: {host_port}")

    def _validate_volumes(self, volumes: Dict[str, Any]):
        """Validate volume mounts"""
        for host_path, config in volumes.items():
            if not isinstance(config, dict):
                raise ValidationError(f"Volume config must be dict: {host_path}")

            if 'bind' not in config:
                raise ValidationError(f"Volume missing 'bind' path: {host_path}")

            # Security: prevent mounting sensitive paths
            dangerous_paths = ['/etc', '/boot', '/sys', '/proc', '/dev']
            if any(config['bind'].startswith(p) for p in dangerous_paths):
                raise SecurityError(
                    f"Cannot mount sensitive system path: {config['bind']}"
                )

    async def _pull_image(self, client: DockerClient, image: str):
        """Pull Docker image if not present"""
        from utils.async_docker import async_docker_call

        try:
            # Check if image exists locally
            await async_docker_call(client.images.get, image)
            logger.info(f"Image {image} already present")
        except Exception:
            # Pull image
            logger.info(f"Pulling image {image}")
            await async_docker_call(client.images.pull, image)

    def _prepare_container_config(
        self,
        config: Dict[str, Any],
        deployment_id: str
    ) -> Dict[str, Any]:
        """
        Prepare Docker SDK container config from user input

        Transforms user-friendly config to Docker SDK format
        """
        container_config = {
            'image': config['image'],
            'name': config['name'],
            'detach': True,
        }

        # Add DockMon management label
        labels = config.get('labels', {})
        labels['dockmon.managed'] = 'true'
        labels['dockmon.deployment_id'] = deployment_id
        container_config['labels'] = labels

        # Port mappings
        if 'ports' in config:
            container_config['ports'] = config['ports']

        # Environment variables
        if 'environment' in config:
            container_config['environment'] = config['environment']

        # Volumes
        if 'volumes' in config:
            container_config['volumes'] = config['volumes']

        # Network
        if 'network' in config:
            container_config['network'] = config['network']

        # Restart policy
        restart_policy = config.get('restart_policy', 'no')
        if isinstance(restart_policy, str):
            container_config['restart_policy'] = {'Name': restart_policy}
        else:
            container_config['restart_policy'] = restart_policy

        # Resource limits (optional)
        if 'cpu_limit' in config or 'memory_limit' in config:
            container_config['host_config'] = {}
            if 'cpu_limit' in config:
                container_config['host_config']['nano_cpus'] = int(
                    config['cpu_limit'] * 1e9
                )
            if 'memory_limit' in config:
                container_config['host_config']['mem_limit'] = config['memory_limit']

        return container_config

    async def remove(self, host_id: str, deployment_id: str, container_id: str):
        """Remove a deployed container"""
        from utils.async_docker import async_docker_call

        client = self.clients[host_id]

        try:
            container = await async_docker_call(client.containers.get, container_id)
            await async_docker_call(container.stop, timeout=10)
            await async_docker_call(container.remove)

            logger.info(f"Removed container {container_id}")

            self.event_logger.log_deployment_event(
                action="container_removed",
                deployment_id=deployment_id,
                container_id=container_id,
                host_id=host_id,
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to remove container: {e}")
            raise DeploymentError(f"Failed to remove container: {e}")


class DeploymentError(Exception):
    """Deployment operation failed"""
    pass


class ValidationError(DeploymentError):
    """Configuration validation failed"""
    pass


class SecurityError(DeploymentError):
    """Security validation failed"""
    pass
```

#### `stack_deployer.py`

```python
import os
import tempfile
import subprocess
import yaml
from pathlib import Path
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class StackDeployer:
    """Handles Docker Compose stack deployment"""

    def __init__(self, stacks_dir: str = "/opt/dockmon/stacks"):
        self.stacks_dir = Path(stacks_dir)
        self.stacks_dir.mkdir(parents=True, exist_ok=True)

    async def deploy(
        self,
        host_id: str,
        deployment_id: str,
        stack_name: str,
        compose_file: str,
        env_vars: Optional[Dict[str, str]] = None
    ) -> List[str]:
        """
        Deploy a Docker Compose stack

        Args:
            host_id: Target Docker host
            deployment_id: Deployment record ID
            stack_name: Stack name (project name)
            compose_file: docker-compose.yml content
            env_vars: Environment variables

        Returns:
            container_ids: List of container IDs created

        Raises:
            DeploymentError: If deployment fails
        """

        # Create stack directory
        stack_dir = self.stacks_dir / stack_name
        stack_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Write compose file
            compose_path = stack_dir / "docker-compose.yml"
            compose_path.write_text(compose_file)

            # Write env file if provided
            if env_vars:
                env_path = stack_dir / ".env"
                env_content = "\n".join(f"{k}={v}" for k, v in env_vars.items())
                env_path.write_text(env_content)

            # Validate compose file
            self._validate_compose_file(compose_path)

            # Deploy stack
            logger.info(f"Deploying stack {stack_name}")
            result = await self._run_compose_command(
                stack_dir,
                ["up", "-d"],
                env_vars=env_vars
            )

            if result.returncode != 0:
                raise DeploymentError(f"Compose deployment failed: {result.stderr}")

            # Get container IDs
            container_ids = await self._get_stack_containers(stack_dir, stack_name)

            logger.info(
                f"Stack {stack_name} deployed successfully, "
                f"containers: {container_ids}"
            )

            return container_ids

        except Exception as e:
            logger.error(f"Stack deployment failed: {e}")
            # Cleanup on failure
            await self._cleanup_stack(stack_dir, stack_name)
            raise DeploymentError(f"Failed to deploy stack: {e}")

    def _validate_compose_file(self, compose_path: Path):
        """Validate docker-compose.yml syntax"""
        try:
            with open(compose_path) as f:
                compose_data = yaml.safe_load(f)

            # Basic validation
            if not isinstance(compose_data, dict):
                raise ValidationError("Compose file must be a YAML dictionary")

            if 'services' not in compose_data:
                raise ValidationError("Compose file must define 'services'")

            if not compose_data['services']:
                raise ValidationError("At least one service must be defined")

            # Security validation
            self._validate_compose_security(compose_data)

        except yaml.YAMLError as e:
            raise ValidationError(f"Invalid YAML syntax: {e}")

    def _validate_compose_security(self, compose_data: Dict[str, Any]):
        """Validate compose file for security issues"""

        for service_name, service_config in compose_data.get('services', {}).items():
            # Check for privileged mode
            if service_config.get('privileged'):
                logger.warning(
                    f"Service {service_name} uses privileged mode - security risk!"
                )

            # Check for dangerous volume mounts
            volumes = service_config.get('volumes', [])
            for volume in volumes:
                if isinstance(volume, str):
                    # Parse volume string (e.g., "/etc:/etc:ro")
                    parts = volume.split(':')
                    if len(parts) >= 2:
                        host_path = parts[0]
                        dangerous_paths = ['/etc', '/boot', '/sys', '/proc', '/dev']
                        if any(host_path.startswith(p) for p in dangerous_paths):
                            raise SecurityError(
                                f"Service {service_name} mounts sensitive path: {host_path}"
                            )

            # Check for host network mode
            if service_config.get('network_mode') == 'host':
                logger.warning(
                    f"Service {service_name} uses host network mode - security risk!"
                )

    async def _run_compose_command(
        self,
        stack_dir: Path,
        command: List[str],
        env_vars: Optional[Dict[str, str]] = None
    ) -> subprocess.CompletedProcess:
        """Run docker-compose command"""

        # Build command
        cmd = ['docker-compose'] + command

        # Prepare environment
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        # Run command
        result = subprocess.run(
            cmd,
            cwd=stack_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        logger.debug(f"Compose command output: {result.stdout}")
        if result.stderr:
            logger.debug(f"Compose command stderr: {result.stderr}")

        return result

    async def _get_stack_containers(
        self,
        stack_dir: Path,
        stack_name: str
    ) -> List[str]:
        """Get container IDs for a stack"""

        result = await self._run_compose_command(
            stack_dir,
            ["ps", "-q"]
        )

        if result.returncode != 0:
            logger.warning(f"Failed to get stack containers: {result.stderr}")
            return []

        container_ids = [
            cid.strip()
            for cid in result.stdout.split('\n')
            if cid.strip()
        ]

        return container_ids

    async def remove(self, stack_name: str):
        """Remove a stack"""

        stack_dir = self.stacks_dir / stack_name

        if not stack_dir.exists():
            raise DeploymentError(f"Stack {stack_name} not found")

        try:
            # Stop and remove containers
            logger.info(f"Removing stack {stack_name}")
            result = await self._run_compose_command(
                stack_dir,
                ["down", "-v"]  # -v removes volumes
            )

            if result.returncode != 0:
                logger.warning(f"Stack removal had errors: {result.stderr}")

            # Remove stack directory
            await self._cleanup_stack(stack_dir, stack_name)

            logger.info(f"Stack {stack_name} removed successfully")

        except Exception as e:
            logger.error(f"Failed to remove stack: {e}")
            raise DeploymentError(f"Failed to remove stack: {e}")

    async def _cleanup_stack(self, stack_dir: Path, stack_name: str):
        """Clean up stack directory"""
        import shutil

        if stack_dir.exists():
            shutil.rmtree(stack_dir)
            logger.info(f"Cleaned up stack directory: {stack_dir}")

    async def validate_compose_file(self, compose_content: str) -> Dict[str, Any]:
        """
        Validate compose file and return analysis

        Returns:
        {
            "valid": true,
            "errors": [],
            "warnings": [],
            "services": ["web", "db"],
            "volumes": ["data"],
            "networks": ["default"]
        }
        """

        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "services": [],
            "volumes": [],
            "networks": []
        }

        try:
            compose_data = yaml.safe_load(compose_content)

            # Extract services
            services = compose_data.get('services', {})
            result['services'] = list(services.keys())

            # Extract volumes
            volumes = compose_data.get('volumes', {})
            result['volumes'] = list(volumes.keys()) if isinstance(volumes, dict) else []

            # Extract networks
            networks = compose_data.get('networks', {})
            result['networks'] = list(networks.keys()) if isinstance(networks, dict) else []

            # Check for deprecated version field
            if 'version' in compose_data:
                result['warnings'].append(
                    "The 'version' field is deprecated in Compose v2"
                )

            # Validate basic structure
            if not services:
                result['valid'] = False
                result['errors'].append("No services defined")

            # Security checks
            for service_name, service_config in services.items():
                if service_config.get('privileged'):
                    result['warnings'].append(
                        f"Service '{service_name}' uses privileged mode"
                    )

                if service_config.get('network_mode') == 'host':
                    result['warnings'].append(
                        f"Service '{service_name}' uses host network mode"
                    )

        except yaml.YAMLError as e:
            result['valid'] = False
            result['errors'].append(f"Invalid YAML: {str(e)}")
        except Exception as e:
            result['valid'] = False
            result['errors'].append(f"Validation error: {str(e)}")

        return result
```

### Pydantic Models

```python
# backend/deployment/models.py

from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from enum import Enum


class DeploymentType(str, Enum):
    CONTAINER = "container"
    STACK = "stack"


class DeploymentStatus(str, Enum):
    PENDING = "pending"
    DEPLOYING = "deploying"
    RUNNING = "running"
    FAILED = "failed"
    STOPPED = "stopped"
    REMOVED = "removed"


class RestartPolicy(str, Enum):
    NO = "no"
    ALWAYS = "always"
    ON_FAILURE = "on-failure"
    UNLESS_STOPPED = "unless-stopped"


class ContainerDeploymentRequest(BaseModel):
    """Request to deploy a single container"""

    host_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=255, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')
    image: str = Field(..., min_length=1)

    # Optional configuration
    ports: Optional[Dict[str, int]] = None  # {"80/tcp": 8080}
    environment: Optional[Dict[str, str]] = None
    volumes: Optional[Dict[str, Dict[str, str]]] = None  # {"/host": {"bind": "/container", "mode": "rw"}}
    network: Optional[str] = None
    restart_policy: RestartPolicy = RestartPolicy.UNLESS_STOPPED
    labels: Optional[Dict[str, str]] = None

    # Resource limits
    cpu_limit: Optional[float] = Field(None, gt=0, le=32)  # CPU cores
    memory_limit: Optional[str] = None  # e.g., "512m", "2g"

    @validator('name')
    def validate_name(cls, v):
        """Validate container name"""
        if len(v) > 255:
            raise ValueError('Name too long')
        # Container names must start with alphanumeric
        if not v[0].isalnum():
            raise ValueError('Name must start with alphanumeric character')
        return v

    @validator('image')
    def validate_image(cls, v):
        """Validate image reference"""
        # Basic validation - could be more sophisticated
        if not v or v.strip() == '':
            raise ValueError('Image cannot be empty')
        return v.strip()


class StackDeploymentRequest(BaseModel):
    """Request to deploy a Docker Compose stack"""

    host_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=255, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')
    compose_file: str = Field(..., min_length=1)
    env_vars: Optional[Dict[str, str]] = None
    working_dir: Optional[str] = None

    @validator('compose_file')
    def validate_compose_file(cls, v):
        """Basic YAML syntax check"""
        import yaml
        try:
            yaml.safe_load(v)
        except yaml.YAMLError as e:
            raise ValueError(f'Invalid YAML: {e}')
        return v


class DeploymentUpdateRequest(BaseModel):
    """Request to update a deployment"""

    config: Dict[str, Any]  # New configuration (same format as create)


class ComposeValidationRequest(BaseModel):
    """Request to validate a compose file"""

    compose_file: str = Field(..., min_length=1)


class DeploymentResponse(BaseModel):
    """Response for deployment operations"""

    deployment_id: str
    status: DeploymentStatus
    container_ids: Optional[List[str]] = None
    error_message: Optional[str] = None


class DeploymentDetails(BaseModel):
    """Full deployment details"""

    id: str
    host_id: str
    deployment_type: DeploymentType
    name: str
    status: DeploymentStatus
    config: Dict[str, Any]

    created_by: Optional[str] = None
    created_at: str
    updated_at: str
    deployed_at: Optional[str] = None

    container_ids: Optional[List[str]] = None
    error_message: Optional[str] = None
```

---

## Frontend Implementation

### New Pages/Components

#### 1. Deployment List Page

**Route:** `/deployments`

**Components:**
```
ui/src/features/deployments/
├── DeploymentsPage.tsx        # Main page
├── DeploymentTable.tsx         # Deployments table
├── DeploymentDetailsDrawer.tsx # Deployment details
└── components/
    ├── DeploymentStatusBadge.tsx
    └── DeploymentActionsMenu.tsx
```

**Features:**
- Table showing all deployments
- Filter by host, type, status
- Actions: View, Update, Remove
- Status indicators (running, failed, etc.)

#### 2. Deploy Container Page

**Route:** `/deploy/container`

**Components:**
```
ui/src/features/deployments/container/
├── DeployContainerPage.tsx       # Main form page
├── ContainerConfigForm.tsx       # Multi-step form
└── components/
    ├── ImageSelector.tsx          # Image search/select
    ├── PortMappingsInput.tsx      # Port configuration
    ├── EnvironmentVariablesInput.tsx
    ├── VolumesMountInput.tsx
    └── ResourceLimitsInput.tsx
```

**Form sections:**
1. Basic Info (host, name, image)
2. Network (ports, network)
3. Storage (volumes)
4. Environment (env vars)
5. Advanced (restart policy, resource limits)
6. Review & Deploy

#### 3. Deploy Stack Page

**Route:** `/deploy/stack`

**Components:**
```
ui/src/features/deployments/stack/
├── DeployStackPage.tsx
├── ComposeEditor.tsx          # YAML editor with validation
├── EnvVarsEditor.tsx
└── components/
    ├── ComposeValidator.tsx   # Live validation
    ├── ServicePreview.tsx     # Show services from compose
    └── TemplateSelector.tsx   # Select from templates
```

**Features:**
- YAML editor with syntax highlighting (Monaco or CodeMirror)
- Live validation
- Environment variables editor
- Template selection
- Preview services before deployment

#### 4. Templates Library

**Route:** `/templates`

**Components:**
```
ui/src/features/templates/
├── TemplatesPage.tsx
├── TemplateCard.tsx
├── TemplateDetailsModal.tsx
└── components/
    └── CategoryFilter.tsx
```

**Features:**
- Browse templates by category
- Search templates
- Preview template configuration
- One-click deploy from template

### Key UI Components

#### Port Mappings Input

```typescript
// ui/src/features/deployments/container/components/PortMappingsInput.tsx

interface PortMapping {
  containerPort: string;
  hostPort: number | null;
  protocol: 'tcp' | 'udp';
}

export function PortMappingsInput({
  value,
  onChange
}: {
  value: PortMapping[];
  onChange: (mappings: PortMapping[]) => void;
}) {
  const addMapping = () => {
    onChange([...value, { containerPort: '', hostPort: null, protocol: 'tcp' }]);
  };

  const removeMapping = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      <label className="text-sm font-medium">Port Mappings</label>
      {value.map((mapping, index) => (
        <div key={index} className="flex gap-2">
          <input
            type="number"
            placeholder="Container port"
            value={mapping.containerPort}
            onChange={(e) => {
              const newMappings = [...value];
              newMappings[index].containerPort = e.target.value;
              onChange(newMappings);
            }}
            className="flex-1"
          />
          <select
            value={mapping.protocol}
            onChange={(e) => {
              const newMappings = [...value];
              newMappings[index].protocol = e.target.value as 'tcp' | 'udp';
              onChange(newMappings);
            }}
          >
            <option value="tcp">TCP</option>
            <option value="udp">UDP</option>
          </select>
          <input
            type="number"
            placeholder="Host port (leave empty for auto)"
            value={mapping.hostPort || ''}
            onChange={(e) => {
              const newMappings = [...value];
              newMappings[index].hostPort = e.target.value ? parseInt(e.target.value) : null;
              onChange(newMappings);
            }}
            className="flex-1"
          />
          <button onClick={() => removeMapping(index)}>Remove</button>
        </div>
      ))}
      <button onClick={addMapping}>Add Port Mapping</button>
    </div>
  );
}
```

#### Compose Editor with Validation

```typescript
// ui/src/features/deployments/stack/ComposeEditor.tsx

import Editor from '@monaco-editor/react';
import { useState, useEffect } from 'react';
import { api } from '@/lib/api';

export function ComposeEditor({
  value,
  onChange
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const [validation, setValidation] = useState<any>(null);
  const [isValidating, setIsValidating] = useState(false);

  useEffect(() => {
    // Debounced validation
    const timer = setTimeout(async () => {
      if (value) {
        setIsValidating(true);
        try {
          const result = await api.post('/api/v2/deployments/stack/validate', {
            compose_file: value
          });
          setValidation(result.data);
        } catch (error) {
          setValidation({ valid: false, errors: ['Validation failed'] });
        } finally {
          setIsValidating(false);
        }
      }
    }, 1000);

    return () => clearTimeout(timer);
  }, [value]);

  return (
    <div className="space-y-4">
      <div className="border rounded-lg overflow-hidden">
        <Editor
          height="400px"
          defaultLanguage="yaml"
          value={value}
          onChange={(val) => onChange(val || '')}
          theme="vs-dark"
          options={{
            minimap: { enabled: false },
            fontSize: 14,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
          }}
        />
      </div>

      {/* Validation status */}
      {isValidating && (
        <div className="text-sm text-gray-500">Validating...</div>
      )}

      {validation && !isValidating && (
        <div className="space-y-2">
          {validation.valid ? (
            <div className="text-sm text-green-600">
              ✓ Valid compose file
              <div className="text-gray-600 mt-1">
                Services: {validation.services.join(', ')}
              </div>
            </div>
          ) : (
            <div className="text-sm text-red-600">
              ✗ Invalid compose file
              <ul className="mt-1 list-disc list-inside">
                {validation.errors.map((err: string, i: number) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            </div>
          )}

          {validation.warnings && validation.warnings.length > 0 && (
            <div className="text-sm text-yellow-600">
              <div className="font-medium">Warnings:</div>
              <ul className="mt-1 list-disc list-inside">
                {validation.warnings.map((warn: string, i: number) => (
                  <li key={i}>{warn}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

### Navigation Updates

Add to sidebar:

```typescript
// ui/src/components/layout/Sidebar.tsx

const navigation = [
  // ... existing items
  {
    name: 'Deploy',
    icon: PlusCircleIcon,
    children: [
      { name: 'Container', href: '/deploy/container' },
      { name: 'Stack', href: '/deploy/stack' },
      { name: 'Templates', href: '/templates' },
    ],
  },
  {
    name: 'Deployments',
    href: '/deployments',
    icon: RocketLaunchIcon,
  },
];
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1)

**Backend:**
- [ ] Create database schema (deployments tables)
- [ ] Create migration script
- [ ] Create Pydantic models
- [ ] Set up basic API routes structure

**Frontend:**
- [ ] Create deployment routes
- [ ] Create basic page layouts
- [ ] Set up navigation

### Phase 2: Single Container Deployment (Week 2-3)

**Backend:**
- [ ] Implement `ContainerDeployer` class
- [ ] Implement container deployment endpoint
- [ ] Implement container removal endpoint
- [ ] Add event logging for deployments
- [ ] Write unit tests

**Frontend:**
- [ ] Build container deployment form
- [ ] Implement port mappings input
- [ ] Implement environment variables input
- [ ] Implement volumes input
- [ ] Add form validation
- [ ] Add deployment progress tracking
- [ ] Show deployment status/errors

**Testing:**
- [ ] Deploy simple container (nginx)
- [ ] Deploy container with ports
- [ ] Deploy container with volumes
- [ ] Deploy container with env vars
- [ ] Test deployment failure handling
- [ ] Test container removal

### Phase 3: Stack Deployment (Week 4-5)

**Backend:**
- [ ] Implement `StackDeployer` class
- [ ] Implement stack deployment endpoint
- [ ] Implement stack removal endpoint
- [ ] Implement compose file validation endpoint
- [ ] Write unit tests

**Frontend:**
- [ ] Build stack deployment page
- [ ] Integrate Monaco/CodeMirror editor
- [ ] Implement live YAML validation
- [ ] Add environment variables editor
- [ ] Show services preview
- [ ] Add deployment progress tracking

**Testing:**
- [ ] Deploy simple stack (WordPress)
- [ ] Deploy stack with environment variables
- [ ] Deploy stack with volumes
- [ ] Test validation errors
- [ ] Test stack removal

### Phase 4: Templates (Week 6)

**Backend:**
- [ ] Seed database with official templates
- [ ] Implement template CRUD endpoints
- [ ] Implement deploy-from-template endpoint

**Frontend:**
- [ ] Build templates library page
- [ ] Build template card/grid view
- [ ] Add category filtering
- [ ] Implement template deployment flow
- [ ] Allow customization before deploy

**Templates to include:**
- Nginx
- Apache
- PostgreSQL
- MySQL
- Redis
- MongoDB
- WordPress (stack)
- LAMP stack
- Nextcloud (stack)
- Prometheus + Grafana (stack)

### Phase 5: Polish & Integration (Week 7)

**Features:**
- [ ] Add deployment status to dashboard
- [ ] Show deployments in host cards
- [ ] Add "Deploy" button to container list
- [ ] Link deployments to containers in UI
- [ ] Add deployment metrics to dashboard
- [ ] Improve error messages
- [ ] Add help text/tooltips

**Documentation:**
- [ ] Update user guide
- [ ] Add deployment screenshots
- [ ] Create deployment tutorials
- [ ] Update API documentation

### Phase 6: Testing & Release (Week 8)

**Testing:**
- [ ] End-to-end testing
- [ ] Multi-host testing
- [ ] Performance testing
- [ ] Security audit
- [ ] User acceptance testing

**Release:**
- [ ] Update changelog
- [ ] Create release notes
- [ ] Update Docker image
- [ ] Announce on GitHub/Discord
- [ ] Monitor for issues

---

## Security Considerations

### Input Validation

**Container names:**
- Alphanumeric, dash, underscore, period only
- Must start with alphanumeric
- Max 255 characters

**Image references:**
- Validate format (registry/repo:tag)
- Optionally restrict to approved registries
- Warn on 'latest' tag usage

**Port mappings:**
- Validate port ranges (1-65535)
- Warn on privileged ports (<1024)
- Check for port conflicts

**Volume mounts:**
- **Block sensitive paths:** `/etc`, `/boot`, `/sys`, `/proc`, `/dev`
- Warn on root filesystem mounts (`/`)
- Validate host paths exist (optional)

**Environment variables:**
- Warn on sensitive variable names (`PASSWORD`, `SECRET`, `TOKEN`)
- Don't log sensitive values

### Docker Security

**Prevent dangerous configurations:**
- Block `privileged: true` (or warn heavily)
- Block `network_mode: host` (or warn)
- Block `cap_add: SYS_ADMIN` and similar
- Warn on `user: root`

**Resource limits:**
- Enforce maximum CPU limit (e.g., 16 cores)
- Enforce maximum memory limit (e.g., 32GB)
- Prevent unbounded resources

### Stack Security

**Compose file validation:**
- Parse YAML safely
- Check for dangerous configurations
- Validate service references
- Check for circular dependencies

**File system isolation:**
- Store each stack in isolated directory
- Use restrictive permissions (700)
- Clean up on deployment failure
- Prevent directory traversal

### Audit Logging

Log all deployment operations:
```python
{
  "event": "deployment_created",
  "user": "admin@example.com",
  "deployment_id": "dep_abc123",
  "host_id": "host_123",
  "deployment_type": "container",
  "config": {...},  # Sanitized (no passwords)
  "timestamp": "2025-10-23T10:00:00Z",
  "ip_address": "192.168.1.100"
}
```

### User Permissions

Future consideration (multi-user):
- Role-based access control
- Per-host deployment permissions
- Template access control
- Deployment approval workflow

---

## Testing Strategy

### Unit Tests

**Backend:**
```python
# tests/test_container_deployer.py

def test_validate_config_valid():
    """Test config validation with valid input"""
    deployer = ContainerDeployer(clients, event_logger)
    config = {
        'image': 'nginx:latest',
        'name': 'test-nginx',
        'ports': {'80/tcp': 8080}
    }
    deployer._validate_config(config)  # Should not raise


def test_validate_config_missing_required():
    """Test config validation with missing required fields"""
    deployer = ContainerDeployer(clients, event_logger)
    config = {'ports': {'80/tcp': 8080}}

    with pytest.raises(ValidationError):
        deployer._validate_config(config)


def test_validate_ports_invalid():
    """Test port validation with invalid port"""
    deployer = ContainerDeployer(clients, event_logger)

    with pytest.raises(ValidationError):
        deployer._validate_ports({'80': 99999})  # Invalid port


def test_validate_volumes_dangerous_path():
    """Test volume validation blocks dangerous paths"""
    deployer = ContainerDeployer(clients, event_logger)

    with pytest.raises(SecurityError):
        deployer._validate_volumes({
            '/host': {'bind': '/etc', 'mode': 'rw'}
        })


def test_deploy_container_success(mock_docker_client):
    """Test successful container deployment"""
    deployer = ContainerDeployer({'host1': mock_docker_client}, event_logger)

    config = {
        'image': 'nginx:latest',
        'name': 'test-nginx',
        'ports': {'80/tcp': 8080}
    }

    container_id = await deployer.deploy('host1', 'dep_123', config)

    assert container_id is not None
    assert mock_docker_client.containers.create.called


# tests/test_stack_deployer.py

def test_validate_compose_valid():
    """Test compose validation with valid file"""
    deployer = StackDeployer()

    compose_file = """
    version: '3.8'
    services:
      web:
        image: nginx:latest
        ports:
          - "80:80"
    """

    result = await deployer.validate_compose_file(compose_file)

    assert result['valid'] is True
    assert 'web' in result['services']


def test_validate_compose_invalid_yaml():
    """Test compose validation with invalid YAML"""
    deployer = StackDeployer()

    compose_file = "invalid: yaml: syntax:"

    result = await deployer.validate_compose_file(compose_file)

    assert result['valid'] is False
    assert len(result['errors']) > 0


def test_validate_compose_security_privileged():
    """Test compose validation warns on privileged mode"""
    deployer = StackDeployer()

    compose_file = """
    services:
      web:
        image: nginx
        privileged: true
    """

    result = await deployer.validate_compose_file(compose_file)

    assert 'privileged' in ' '.join(result['warnings'])
```

### Integration Tests

**API tests:**
```python
# tests/integration/test_deployment_api.py

async def test_deploy_container_endpoint(client, auth_headers):
    """Test container deployment via API"""

    response = await client.post(
        '/api/v2/deployments/container',
        headers=auth_headers,
        json={
            'host_id': 'local',
            'name': 'test-nginx',
            'image': 'nginx:latest',
            'ports': {'80/tcp': 8080},
            'restart_policy': 'unless-stopped'
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert 'deployment_id' in data
    assert data['status'] == 'deploying'


async def test_deploy_stack_endpoint(client, auth_headers):
    """Test stack deployment via API"""

    compose_file = """
    version: '3.8'
    services:
      web:
        image: nginx:latest
        ports:
          - "8080:80"
    """

    response = await client.post(
        '/api/v2/deployments/stack',
        headers=auth_headers,
        json={
            'host_id': 'local',
            'name': 'test-stack',
            'compose_file': compose_file
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert 'deployment_id' in data
```

### End-to-End Tests

**Frontend + Backend:**
```typescript
// ui/tests/e2e/deployment.spec.ts

test('deploy container from UI', async ({ page }) => {
  await page.goto('/deploy/container');

  // Fill form
  await page.selectOption('[name="host_id"]', 'local');
  await page.fill('[name="name"]', 'test-nginx');
  await page.fill('[name="image"]', 'nginx:latest');

  // Add port mapping
  await page.click('button:has-text("Add Port Mapping")');
  await page.fill('[name="containerPort"]', '80');
  await page.selectOption('[name="protocol"]', 'tcp');
  await page.fill('[name="hostPort"]', '8080');

  // Submit
  await page.click('button:has-text("Deploy")');

  // Wait for success
  await page.waitForSelector('text=Deployment successful');

  // Verify deployment appears in list
  await page.goto('/deployments');
  await expect(page.locator('text=test-nginx')).toBeVisible();
});


test('deploy stack from template', async ({ page }) => {
  await page.goto('/templates');

  // Select WordPress template
  await page.click('[data-template="wordpress"]');

  // Customize
  await page.selectOption('[name="host_id"]', 'local');
  await page.fill('[name="DB_PASSWORD"]', 'secure-password');

  // Deploy
  await page.click('button:has-text("Deploy")');

  // Wait for success
  await page.waitForSelector('text=Stack deployed successfully');

  // Verify in deployments
  await page.goto('/deployments');
  await expect(page.locator('text=wordpress')).toBeVisible();
});
```

---

## Migration Path

### Database Migration

**Alembic migration script:**

```python
# backend/alembic/versions/20251023_1200_add_deployments.py

"""Add deployments tables

Revision ID: dep_001
Revises: <previous_revision>
Create Date: 2025-10-23 12:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = 'dep_001'
down_revision = '<previous_revision>'
branch_labels = None
depends_on = None


def upgrade():
    # Create deployments table
    op.create_table(
        'deployments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('host_id', sa.String(36), nullable=False),
        sa.Column('deployment_type', sa.String(20), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('config', mysql.JSON(), nullable=False),
        sa.Column('created_by', sa.String(255)),
        sa.Column('created_at', sa.TIMESTAMP, server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.TIMESTAMP, server_default=sa.func.current_timestamp(), onupdate=sa.func.current_timestamp()),
        sa.Column('deployed_at', sa.TIMESTAMP),
        sa.Column('container_ids', mysql.JSON()),
        sa.Column('error_message', sa.Text),
        sa.Column('last_checked', sa.TIMESTAMP),
        sa.ForeignKeyConstraint(['host_id'], ['hosts.id'], ondelete='CASCADE'),
    )

    op.create_index('idx_host_type', 'deployments', ['host_id', 'deployment_type'])
    op.create_index('idx_status', 'deployments', ['status'])
    op.create_index('idx_name', 'deployments', ['name'])

    # Create deployment_templates table
    op.create_table(
        'deployment_templates',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text),
        sa.Column('category', sa.String(50)),
        sa.Column('icon_url', sa.String(500)),
        sa.Column('template_type', sa.String(20), nullable=False),
        sa.Column('template_config', mysql.JSON(), nullable=False),
        sa.Column('is_official', sa.Boolean, default=False),
        sa.Column('is_enabled', sa.Boolean, default=True),
        sa.Column('downloads', sa.Integer, default=0),
        sa.Column('created_at', sa.TIMESTAMP, server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.TIMESTAMP, server_default=sa.func.current_timestamp(), onupdate=sa.func.current_timestamp()),
    )

    op.create_index('idx_category', 'deployment_templates', ['category'])
    op.create_index('idx_type', 'deployment_templates', ['template_type'])

    # Create deployment_history table
    op.create_table(
        'deployment_history',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column('deployment_id', sa.String(36), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('triggered_by', sa.String(255)),
        sa.Column('changes', mysql.JSON()),
        sa.Column('error_message', sa.Text),
        sa.Column('started_at', sa.TIMESTAMP, server_default=sa.func.current_timestamp()),
        sa.Column('completed_at', sa.TIMESTAMP),
        sa.Column('duration_ms', sa.Integer),
        sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id'], ondelete='CASCADE'),
    )

    op.create_index('idx_deployment', 'deployment_history', ['deployment_id'])
    op.create_index('idx_action', 'deployment_history', ['action'])
    op.create_index('idx_timestamp', 'deployment_history', ['started_at'])

    # Update containers table
    op.add_column('containers', sa.Column('deployment_id', sa.String(36)))
    op.add_column('containers', sa.Column('is_managed', sa.Boolean, default=False))
    op.create_foreign_key(
        'fk_containers_deployment',
        'containers', 'deployments',
        ['deployment_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('idx_deployment', 'containers', ['deployment_id'])


def downgrade():
    # Drop in reverse order
    op.drop_constraint('fk_containers_deployment', 'containers', type_='foreignkey')
    op.drop_index('idx_deployment', 'containers')
    op.drop_column('containers', 'is_managed')
    op.drop_column('containers', 'deployment_id')

    op.drop_index('idx_timestamp', 'deployment_history')
    op.drop_index('idx_action', 'deployment_history')
    op.drop_index('idx_deployment', 'deployment_history')
    op.drop_table('deployment_history')

    op.drop_index('idx_type', 'deployment_templates')
    op.drop_index('idx_category', 'deployment_templates')
    op.drop_table('deployment_templates')

    op.drop_index('idx_name', 'deployments')
    op.drop_index('idx_status', 'deployments')
    op.drop_index('idx_host_type', 'deployments')
    op.drop_table('deployments')
```

### Seed Official Templates

```python
# backend/deployment/seed_templates.py

from sqlalchemy.orm import Session
from models import DeploymentTemplate
import uuid


def seed_official_templates(db: Session):
    """Seed database with official templates"""

    templates = [
        # Nginx
        DeploymentTemplate(
            id=str(uuid.uuid4()),
            name="Nginx Web Server",
            description="High-performance web server and reverse proxy",
            category="web",
            icon_url="https://cdn.dockmon.io/icons/nginx.png",
            template_type="container",
            template_config={
                "image": "nginx:latest",
                "ports": {"80/tcp": None},
                "volumes": {
                    "./html": {"bind": "/usr/share/nginx/html", "mode": "ro"}
                },
                "restart_policy": {"Name": "unless-stopped"}
            },
            is_official=True
        ),

        # PostgreSQL
        DeploymentTemplate(
            id=str(uuid.uuid4()),
            name="PostgreSQL Database",
            description="Powerful open-source relational database",
            category="database",
            icon_url="https://cdn.dockmon.io/icons/postgres.png",
            template_type="container",
            template_config={
                "image": "postgres:16",
                "environment": {
                    "POSTGRES_USER": "postgres",
                    "POSTGRES_PASSWORD": "${DB_PASSWORD}",
                    "POSTGRES_DB": "mydb"
                },
                "ports": {"5432/tcp": 5432},
                "volumes": {
                    "postgres_data": {"bind": "/var/lib/postgresql/data"}
                },
                "restart_policy": {"Name": "unless-stopped"}
            },
            is_official=True
        ),

        # WordPress Stack
        DeploymentTemplate(
            id=str(uuid.uuid4()),
            name="WordPress + MySQL",
            description="Complete WordPress blog with MySQL database",
            category="web",
            icon_url="https://cdn.dockmon.io/icons/wordpress.png",
            template_type="stack",
            template_config={
                "compose_file": """version: '3.8'

services:
  wordpress:
    image: wordpress:latest
    ports:
      - '\${WP_PORT:-8080}:80'
    environment:
      WORDPRESS_DB_HOST: db
      WORDPRESS_DB_USER: wordpress
      WORDPRESS_DB_PASSWORD: \${DB_PASSWORD}
      WORDPRESS_DB_NAME: wordpress
    volumes:
      - wordpress_data:/var/www/html
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wordpress
      MYSQL_PASSWORD: \${DB_PASSWORD}
      MYSQL_RANDOM_ROOT_PASSWORD: '1'
    volumes:
      - db_data:/var/lib/mysql
    restart: unless-stopped

volumes:
  wordpress_data:
  db_data:
""",
                "required_env_vars": ["DB_PASSWORD", "WP_PORT"]
            },
            is_official=True
        ),

        # Add more templates...
    ]

    for template in templates:
        db.add(template)

    db.commit()
    print(f"Seeded {len(templates)} official templates")


if __name__ == "__main__":
    from database import SessionLocal
    db = SessionLocal()
    seed_official_templates(db)
    db.close()
```

---

## Rollout Plan

### Pre-Release Checklist

- [ ] All tests passing
- [ ] Database migration tested
- [ ] Templates seeded
- [ ] Documentation updated
- [ ] Security audit completed
- [ ] Performance testing done
- [ ] Backward compatibility verified

### Release Steps

1. **Beta Release (v2.1.0-beta.1)**
   - Release to small group of testers
   - Gather feedback
   - Fix critical bugs

2. **Release Candidate (v2.1.0-rc.1)**
   - Feature complete
   - All known bugs fixed
   - Final testing

3. **Stable Release (v2.1.0)**
   - Production ready
   - Update main Docker image
   - Announce release

### Post-Release

- Monitor GitHub issues
- Watch error logs
- Gather user feedback
- Plan v2.2 improvements

---

## Future Enhancements (v2.2+)

### Short-term (v2.2)

- [ ] Git repository integration for compose files
- [ ] Stack update detection (new image versions)
- [ ] Deployment scheduling (deploy at specific time)
- [ ] Deployment webhooks
- [ ] Template marketplace/sharing

### Medium-term (v2.3)

- [ ] Docker Swarm stack support
- [ ] Build from Dockerfile
- [ ] Multi-stage deployments (dev → staging → prod)
- [ ] Rollback deployments
- [ ] A/B deployment testing

### Long-term (v3.0)

- [ ] Kubernetes deployment support
- [ ] Infrastructure as Code export (Terraform, Pulumi)
- [ ] CI/CD pipeline integration
- [ ] Container registry management
- [ ] Image vulnerability scanning

---

## Questions & Decisions Needed

### Technical Decisions

1. **Monaco vs CodeMirror for YAML editor?**
   - Monaco: Heavier but feature-rich (VS Code editor)
   - CodeMirror: Lighter, good enough for YAML
   - **Recommendation:** CodeMirror (lighter, faster load)

2. **Store compose files in database or filesystem?**
   - Database: Easier backup, version control
   - Filesystem: Better for large files, easier debugging
   - **Recommendation:** Filesystem with DB metadata

3. **Support docker-compose v1 CLI or only v2?**
   - v1: Deprecated but still in use
   - v2: Modern, actively developed
   - **Recommendation:** v2 only, mention requirement in docs

4. **Template storage: Database or JSON files?**
   - Database: Easy CRUD via API
   - JSON files: Easy for contributors to add
   - **Recommendation:** Database (seed from JSON files)

### UX Decisions

1. **Deployment wizard vs single-page form?**
   - Wizard: Better for beginners, step-by-step
   - Single page: Faster for power users
   - **Recommendation:** Start with wizard, add quick mode later

2. **Image selection: Autocomplete or manual entry?**
   - Autocomplete: Better UX, requires Docker Hub API
   - Manual: Simple, flexible
   - **Recommendation:** Manual for MVP, autocomplete in v2.2

3. **Validation: Client-side only or server-side too?**
   - Client: Fast feedback
   - Server: Security, canonical validation
   - **Recommendation:** Both (client for UX, server for security)

---

## Resources & References

### Docker SDK Documentation

- [Docker SDK for Python](https://docker-py.readthedocs.io/)
- [Container.create() reference](https://docker-py.readthedocs.io/en/stable/containers.html#docker.models.containers.ContainerCollection.create)
- [Container.run() reference](https://docker-py.readthedocs.io/en/stable/containers.html#docker.models.containers.ContainerCollection.run)

### Docker Compose

- [Compose file reference](https://docs.docker.com/compose/compose-file/)
- [Compose CLI reference](https://docs.docker.com/compose/reference/)
- [Compose v2 migration](https://docs.docker.com/compose/migrate/)

### Frontend Libraries

- [Monaco Editor React](https://github.com/suren-atoyan/monaco-react)
- [CodeMirror 6](https://codemirror.net/)
- [React Hook Form](https://react-hook-form.com/) - For complex forms
- [Zod](https://zod.dev/) - For schema validation

### Security

- [Docker security best practices](https://docs.docker.com/engine/security/)
- [CIS Docker Benchmark](https://www.cisecurity.org/benchmark/docker)
- [OWASP Container Security](https://owasp.org/www-project-docker-security/)

---

## Success Metrics

### Technical Metrics

- Deployment success rate > 95%
- Average deployment time < 30 seconds (containers), < 2 minutes (stacks)
- Zero security vulnerabilities
- API response time < 200ms
- UI load time < 2 seconds

### User Metrics

- Number of deployments created
- Template usage rate
- User feedback/satisfaction
- GitHub stars/downloads increase
- Reduced "how do I deploy?" support questions

### Business Metrics

- User retention increase
- New user adoption
- Competitive positioning vs Portainer
- Community engagement

---

**Last Updated:** 2025-10-23
**Document Owner:** DockMon Development Team
**Next Review:** After Phase 2 completion
