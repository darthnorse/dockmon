"""
HostConnector abstraction layer for deployment system.

Provides a unified interface for communicating with Docker hosts:
- v2.1: DirectDockerConnector (local socket or TCP+TLS)
- v2.2: AgentRPCConnector (agent-based remote hosts)

This abstraction decouples the deployment executor from Docker SDK,
making it easy to add agent support in v2.2 without refactoring.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
import logging

from database import DatabaseManager
from utils.async_docker import async_docker_call, async_containers_list
from utils.container_health import wait_for_container_health
from utils.image_pull_progress import ImagePullProgress
from utils.network_helpers import manually_connect_networks
from utils.registry_credentials import get_registry_credentials

logger = logging.getLogger(__name__)

# Constants for manual network handling in container configs
# Used when containers need to be connected to networks after creation
_MANUAL_NETWORKS_KEY = '_dockmon_manual_networks'
_MANUAL_NETWORKING_CONFIG_KEY = '_dockmon_manual_networking_config'


class HostConnector(ABC):
    """
    Abstract interface for communicating with Docker hosts.

    All Docker operations go through this interface, allowing
    deployments to work with both direct connections and agent-based hosts.
    """

    def __init__(self, host_id: str):
        self.host_id = host_id

    @abstractmethod
    async def ping(self) -> bool:
        """
        Test connectivity to Docker host.

        Returns:
            True if Docker daemon is reachable, False otherwise
        """
        pass

    @abstractmethod
    async def create_container(
        self,
        config: Dict[str, Any],
        labels: Dict[str, str]
    ) -> str:
        """
        Create container on remote host.

        Args:
            config: Container creation config (image, name, ports, etc.)
            labels: Labels to apply to container (merged with config.labels)

        Returns:
            Container SHORT ID (12 characters)

        Raises:
            DockerException: If container creation fails
        """
        pass

    @abstractmethod
    async def start_container(self, container_id: str) -> None:
        """
        Start container by SHORT ID.

        Args:
            container_id: Container SHORT ID (12 chars)

        Raises:
            DockerException: If container doesn't exist or fails to start
        """
        pass

    @abstractmethod
    async def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """
        Stop container by SHORT ID.

        Args:
            container_id: Container SHORT ID (12 chars)
            timeout: Seconds to wait before killing container

        Raises:
            DockerException: If container doesn't exist or fails to stop
        """
        pass

    @abstractmethod
    async def remove_container(self, container_id: str, force: bool = False) -> None:
        """
        Remove container by SHORT ID.

        Args:
            container_id: Container SHORT ID (12 chars)
            force: Force removal even if running

        Raises:
            DockerException: If container doesn't exist or fails to remove
        """
        pass

    @abstractmethod
    async def get_container_status(self, container_id: str) -> str:
        """
        Get container status (running, exited, etc.).

        Args:
            container_id: Container SHORT ID (12 chars)

        Returns:
            Container status string (running, exited, created, etc.)

        Raises:
            DockerException: If container doesn't exist
        """
        pass

    @abstractmethod
    async def get_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        since: Optional[str] = None
    ) -> str:
        """
        Get container logs.

        Args:
            container_id: Container SHORT ID (12 chars)
            tail: Number of lines to return (default 100)
            since: Timestamp filter (ISO format)

        Returns:
            Container logs as string

        Raises:
            DockerException: If container doesn't exist
        """
        pass

    @abstractmethod
    async def pull_image(
        self,
        image: str,
        deployment_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> None:
        """
        Pull container image from registry.

        Args:
            image: Image name with tag (e.g., nginx:1.25-alpine)
            deployment_id: Optional deployment ID for progress tracking
            progress_callback: Optional callback for progress updates

        Raises:
            DockerException: If image pull fails
        """
        pass

    @abstractmethod
    async def list_networks(self) -> List[Dict[str, Any]]:
        """
        List Docker networks on host.

        Returns:
            List of network objects with name, id, driver, etc.
        """
        pass

    @abstractmethod
    async def create_network(self, name: str, driver: str = "bridge", ipam = None) -> str:
        """
        Create Docker network.

        Args:
            name: Network name
            driver: Network driver (bridge, overlay, etc.)
            ipam: Optional IPAMConfig for subnet/gateway configuration

        Returns:
            Network ID

        Raises:
            DockerException: If network creation fails
        """
        pass

    @abstractmethod
    async def list_volumes(self) -> List[Dict[str, Any]]:
        """
        List Docker volumes on host.

        Returns:
            List of volume objects with name, driver, mountpoint, etc.
        """
        pass

    @abstractmethod
    async def create_volume(self, name: str) -> str:
        """
        Create Docker volume.

        Args:
            name: Volume name

        Returns:
            Volume name

        Raises:
            DockerException: If volume creation fails
        """
        pass

    @abstractmethod
    async def validate_port_availability(self, ports: Dict[str, int]) -> None:
        """
        Validate that ports are available (not used by other containers).

        Args:
            ports: Port mapping dict (e.g., {"80/tcp": 80})

        Raises:
            ValidationError: If any port is already in use
        """
        pass

    @abstractmethod
    async def verify_container_running(self, container_id: str, max_wait_seconds: int = 60) -> bool:
        """
        Verify container is healthy and running.

        Waits for container to become healthy (if it has HEALTHCHECK) or stable (if not).

        Args:
            container_id: Container SHORT ID (12 chars)
            max_wait_seconds: Maximum time to wait for health check (default 60s)

        Returns:
            True if container is healthy/stable, False otherwise
        """
        pass


class DirectDockerConnector(HostConnector):
    """
    Direct connection to Docker daemon (local socket or TCP+TLS).

    Uses Docker SDK for Python to communicate with Docker API.
    Wraps all calls with async_docker_call() to prevent event loop blocking.
    """

    def __init__(self, host_id: str, docker_monitor=None):
        """
        Initialize DirectDockerConnector.

        Args:
            host_id: Docker host ID
            docker_monitor: Optional DockerMonitor instance (for accessing clients dict)
                           If None, will be lazy-loaded from main module
        """
        super().__init__(host_id)
        self._docker_monitor = docker_monitor

    def _get_client(self):
        """
        Get Docker client for this host.

        Returns:
            DockerClient instance

        Raises:
            RuntimeError: If docker_monitor not available
            ValueError: If client not found for host
        """
        # Lazy load docker_monitor only as fallback
        if self._docker_monitor is None:
            try:
                import main
                if hasattr(main, 'docker_monitor'):
                    self._docker_monitor = main.docker_monitor
                else:
                    raise RuntimeError(
                        "DockerMonitor not provided to connector and not available in main module. "
                        "Pass docker_monitor to get_host_connector() or ensure main.docker_monitor is initialized."
                    )
            except ImportError:
                raise RuntimeError(
                    "DockerMonitor not provided to connector and main module not available. "
                    "Pass docker_monitor to get_host_connector()."
                )

        client = self._docker_monitor.clients.get(self.host_id)
        if not client:
            raise ValueError(f"Docker client not found for host {self.host_id}")
        return client

    async def ping(self) -> bool:
        """Test Docker daemon connectivity"""
        try:
            client = self._get_client()
            result = await async_docker_call(client.ping)
            return result is True
        except Exception as e:
            logger.error(f"Failed to ping Docker host {self.host_id}: {e}")
            return False

    async def create_container(
        self,
        config: Dict[str, Any],
        labels: Dict[str, str]
    ) -> str:
        """
        Create container via Docker SDK.

        Handles manual network connection for networks that require it:
        - Multiple networks (can't use 'network' parameter for multiple)
        - Static IPs / aliases (need network.connect() to set these)

        Returns SHORT ID (12 chars) - CRITICAL for DockMon standards.
        """
        client = self._get_client()

        # Extract manual network connection instructions (if present)
        # These are set by stack_orchestrator when networking_config doesn't work
        manual_networks = config.pop(_MANUAL_NETWORKS_KEY, None)
        manual_networking_config = config.pop(_MANUAL_NETWORKING_CONFIG_KEY, None)

        # Merge labels into config
        final_config = config.copy()
        final_config['labels'] = {
            **config.get('labels', {}),
            **labels
        }

        # Create container
        container = await async_docker_call(
            client.containers.create,
            **final_config
        )

        # Manually connect to networks if needed (Bug fix: networking_config doesn't work)
        # This must happen BEFORE starting the container
        try:
            await manually_connect_networks(
                container=container,
                manual_networks=manual_networks,
                manual_networking_config=manual_networking_config,
                client=client,
                async_docker_call=async_docker_call,
                container_id=container.short_id
            )
        except Exception:
            # Clean up: remove container since we failed to configure it properly
            await async_docker_call(container.remove, force=True)
            raise

        # CRITICAL: Return SHORT ID (12 chars), NOT full 64-char ID
        return container.short_id

    async def start_container(self, container_id: str) -> None:
        """Start container by SHORT ID"""
        client = self._get_client()
        container = await async_docker_call(client.containers.get, container_id)
        await async_docker_call(container.start)

    async def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop container by SHORT ID"""
        client = self._get_client()
        container = await async_docker_call(client.containers.get, container_id)
        await async_docker_call(container.stop, timeout=timeout)

    async def remove_container(self, container_id: str, force: bool = False) -> None:
        """Remove container by SHORT ID"""
        client = self._get_client()
        container = await async_docker_call(client.containers.get, container_id)
        await async_docker_call(container.remove, force=force)

    async def get_container_status(self, container_id: str) -> str:
        """Get container status"""
        client = self._get_client()
        container = await async_docker_call(client.containers.get, container_id)
        await async_docker_call(container.reload)
        return container.status

    async def get_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        since: Optional[str] = None
    ) -> str:
        """Get container logs"""
        client = self._get_client()
        container = await async_docker_call(client.containers.get, container_id)

        logs_kwargs = {'tail': tail}
        if since:
            logs_kwargs['since'] = since

        logs = await async_docker_call(container.logs, **logs_kwargs)
        return logs.decode('utf-8') if isinstance(logs, bytes) else logs

    async def pull_image(
        self,
        image: str,
        deployment_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> None:
        """
        Pull image from registry with layer-by-layer progress tracking.

        Args:
            image: Image name with tag (e.g., "nginx:1.25-alpine")
            deployment_id: Optional deployment ID for progress tracking (composite key format)
            progress_callback: Optional callback for progress updates (deprecated, use WebSocket events)

        Progress Tracking:
            If deployment_id is provided, broadcasts real-time layer-by-layer progress
            via WebSocket events (event_type: "deployment_layer_progress").

            Event structure:
            {
                "type": "deployment_layer_progress",
                "data": {
                    "host_id": "...",
                    "entity_id": "deployment_id",
                    "overall_progress": 45,
                    "layers": [...],
                    "summary": "Downloading 3 of 8 layers (45%) @ 12.5 MB/s",
                    "speed_mbps": 12.5
                }
            }
        """
        import asyncio

        client = self._get_client()

        # Look up registry credentials for the image
        auth_config = None
        try:
            db = DatabaseManager()
            auth_config = get_registry_credentials(db, image)
            if auth_config:
                logger.debug(f"Using registry credentials for deployment image pull: {image}")
        except Exception as e:
            logger.warning(f"Failed to get registry credentials for deployment: {e}")

        # If deployment_id provided, use layer-by-layer progress tracking
        if deployment_id:
            # Get connection_manager from docker_monitor for WebSocket broadcasting
            if self._docker_monitor is None:
                import main
                self._docker_monitor = main.docker_monitor

            connection_manager = getattr(self._docker_monitor, 'manager', None)

            # Create image pull tracker (shares code with update system)
            tracker = ImagePullProgress(
                loop=asyncio.get_running_loop(),
                connection_manager=connection_manager,
                progress_callback=progress_callback
            )

            # Pull with layer-by-layer progress broadcasting
            await tracker.pull_with_progress(
                client=client,
                image=image,
                host_id=self.host_id,
                entity_id=deployment_id,
                auth_config=auth_config,
                event_type="deployment_layer_progress",
                timeout=1800  # 30 minutes
            )
        else:
            # Fallback: Simple pull without progress (for backward compatibility)
            # Also use auth_config if available
            if auth_config:
                await async_docker_call(client.images.pull, image, auth_config=auth_config)
            else:
                await async_docker_call(client.images.pull, image)

    async def list_networks(self) -> List[Dict[str, Any]]:
        """List Docker networks"""
        client = self._get_client()
        networks = await async_docker_call(client.networks.list)

        return [
            {
                'id': net.id,
                'name': net.name,
                'driver': net.attrs.get('Driver'),
                'scope': net.attrs.get('Scope'),
            }
            for net in networks
        ]

    async def create_network(self, name: str, driver: str = "bridge", ipam = None) -> str:
        """Create Docker network with optional IPAM configuration"""
        client = self._get_client()
        network = await async_docker_call(client.networks.create, name, driver=driver, ipam=ipam)
        return network.id

    async def list_volumes(self) -> List[Dict[str, Any]]:
        """List Docker volumes"""
        client = self._get_client()
        volumes = await async_docker_call(client.volumes.list)

        return [
            {
                'name': vol.name,
                'driver': vol.attrs.get('Driver'),
                'mountpoint': vol.attrs.get('Mountpoint'),
            }
            for vol in volumes
        ]

    async def create_volume(self, name: str) -> str:
        """Create Docker volume"""
        client = self._get_client()
        volume = await async_docker_call(client.volumes.create, name)
        return volume.name

    async def validate_port_availability(self, ports: Dict[str, int]) -> None:
        """
        Check if ports are available (not used by other containers).

        Raises ValidationError if any port is in use.
        """
        client = self._get_client()
        # Only running containers (no all=True) — stopped containers don't bind host ports
        containers = await async_containers_list(client)

        # Check each requested port
        for port_spec, host_port in ports.items():
            for container in containers:
                container_ports = container.ports
                if container_ports and port_spec in container_ports:
                    bindings = container_ports[port_spec]
                    if bindings:
                        for binding in bindings:
                            if binding.get('HostPort') == str(host_port):
                                raise ValueError(
                                    f"Port {host_port} is already used by container {container.name}"
                                )

    async def verify_container_running(self, container_id: str, max_wait_seconds: int = 60) -> bool:
        """
        Verify container is healthy and running.

        Uses the proven wait_for_container_health() utility that handles:
        - Containers with Docker HEALTHCHECK (waits for 'healthy' status)
        - Containers without HEALTHCHECK (waits 3s for stability)

        Args:
            container_id: Container SHORT ID (12 chars)
            max_wait_seconds: Maximum time to wait for health check (default 60s)

        Returns:
            True if container is healthy/stable, False otherwise
        """
        try:
            client = self._get_client()
            return await wait_for_container_health(
                client=client,
                container_id=container_id,
                timeout=max_wait_seconds
            )
        except Exception as e:
            logger.error(f"Error verifying container health: {e}")
            return False


class AgentConnector(HostConnector):
    """
    Agent-based connection to remote Docker daemon via WebSocket.

    Routes all Docker operations through AgentCommandExecutor to
    communicate with DockMon Agent running on remote host.
    """

    def __init__(self, host_id: str, agent_command_executor=None, agent_manager=None):
        """
        Initialize AgentConnector.

        Args:
            host_id: Docker host ID
            agent_command_executor: AgentCommandExecutor instance
            agent_manager: AgentManager instance (to resolve host_id -> agent_id)
        """
        super().__init__(host_id)
        self._agent_command_executor = agent_command_executor
        self._agent_manager = agent_manager
        self._agent_id = None  # Cached agent ID

    def _get_agent_id(self) -> str:
        """
        Get agent_id for this host.

        Returns:
            Agent ID

        Raises:
            ValueError: If no agent registered for host
        """
        if self._agent_id is not None:
            return self._agent_id

        # Lazy load dependencies if not provided
        if self._agent_manager is None:
            from agent.manager import AgentManager
            self._agent_manager = AgentManager()

        if self._agent_command_executor is None:
            from agent.command_executor import get_agent_command_executor
            self._agent_command_executor = get_agent_command_executor()

        # Resolve host_id -> agent_id
        agent_id = self._agent_manager.get_agent_for_host(self.host_id)
        if not agent_id:
            raise ValueError(f"No agent registered for host {self.host_id}")

        self._agent_id = agent_id
        return agent_id

    async def _execute_command(self, command: dict, timeout: float = 30.0) -> dict:
        """
        Execute command on agent and return response data.

        Args:
            command: Command dict
            timeout: Timeout in seconds

        Returns:
            Response data dict

        Raises:
            RuntimeError: If command fails
        """
        agent_id = self._get_agent_id()

        result = await self._agent_command_executor.execute_command(
            agent_id,
            command,
            timeout=timeout
        )

        if not result.success:
            raise RuntimeError(f"Agent command failed: {result.error}")

        return result.response

    async def ping(self) -> bool:
        """Test connectivity to agent"""
        try:
            agent_id = self._get_agent_id()
            # Check if agent is connected
            return self._agent_command_executor.connection_manager.is_connected(agent_id)
        except Exception as e:
            logger.error(f"Failed to ping agent for host {self.host_id}: {e}")
            return False

    async def create_container(
        self,
        config: Dict[str, Any],
        labels: Dict[str, str]
    ) -> str:
        """
        Create container via agent.

        Returns container SHORT ID (12 characters)
        """
        # Merge labels into config
        final_config = config.copy()
        final_config['labels'] = {
            **config.get('labels', {}),
            **labels
        }

        command = {
            "type": "container_operation",
            "payload": {
                "action": "create",
                "config": final_config
            }
        }

        response = await self._execute_command(command, timeout=60.0)
        container_id = response.get("container_id")

        if not container_id:
            raise RuntimeError("Agent did not return container_id")

        # Ensure SHORT ID (12 chars)
        return container_id[:12] if len(container_id) > 12 else container_id

    async def start_container(self, container_id: str) -> None:
        """Start container by SHORT ID"""
        command = {
            "type": "container_operation",
            "payload": {
                "action": "start",
                "container_id": container_id
            }
        }

        await self._execute_command(command, timeout=30.0)

    async def stop_container(self, container_id: str, timeout: int = 10) -> None:
        """Stop container by SHORT ID"""
        command = {
            "type": "container_operation",
            "payload": {
                "action": "stop",
                "container_id": container_id,
                "timeout": timeout
            }
        }

        await self._execute_command(command, timeout=float(timeout + 20))

    async def remove_container(self, container_id: str, force: bool = False) -> None:
        """Remove container by SHORT ID"""
        command = {
            "type": "container_operation",
            "payload": {
                "action": "remove",
                "container_id": container_id,
                "force": force
            }
        }

        await self._execute_command(command, timeout=30.0)

    async def get_container_status(self, container_id: str) -> str:
        """
        Get container status string.

        Returns: 'running', 'exited', 'created', etc.
        """
        command = {
            "type": "container_operation",
            "payload": {
                "action": "get_status",
                "container_id": container_id
            }
        }

        response = await self._execute_command(command, timeout=15.0)
        return response.get("status", "unknown")

    async def get_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        since: Optional[str] = None
    ) -> str:
        """Get container logs"""
        payload = {
            "action": "get_logs",
            "container_id": container_id,
            "tail": tail
        }
        if since:
            payload["since"] = since

        command = {
            "type": "container_operation",
            "payload": payload
        }

        response = await self._execute_command(command, timeout=30.0)
        return response.get("logs", "")

    async def pull_image(
        self,
        image: str,
        deployment_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> None:
        """
        Pull container image from registry.

        Note: Agent handles progress tracking internally and broadcasts
        via WebSocket. The deployment_id is passed for correlation.
        """
        payload = {
            "action": "pull_image",
            "image": image
        }
        if deployment_id:
            payload["deployment_id"] = deployment_id

        command = {
            "type": "container_operation",
            "payload": payload
        }

        # Image pulls can take a long time (30 minutes timeout)
        await self._execute_command(command, timeout=1800.0)

    async def list_networks(self) -> List[Dict[str, Any]]:
        """List Docker networks on host"""
        command = {
            "type": "container_operation",
            "payload": {
                "action": "list_networks"
            }
        }

        response = await self._execute_command(command, timeout=15.0)
        return response.get("networks", [])

    async def create_network(self, name: str, driver: str = "bridge") -> str:
        """Create Docker network"""
        command = {
            "type": "container_operation",
            "payload": {
                "action": "create_network",
                "name": name,
                "driver": driver
            }
        }

        response = await self._execute_command(command, timeout=30.0)
        return response.get("network_id", "")

    async def list_volumes(self) -> List[Dict[str, Any]]:
        """List Docker volumes on host"""
        command = {
            "type": "container_operation",
            "payload": {
                "action": "list_volumes"
            }
        }

        response = await self._execute_command(command, timeout=15.0)
        return response.get("volumes", [])

    async def create_volume(self, name: str) -> str:
        """Create Docker volume"""
        command = {
            "type": "container_operation",
            "payload": {
                "action": "create_volume",
                "name": name
            }
        }

        response = await self._execute_command(command, timeout=30.0)
        return response.get("volume_name", name)

    async def validate_port_availability(self, ports: Dict[str, int]) -> None:
        """
        Validate that ports are available.

        Agent will check and raise error if ports in use.
        """
        command = {
            "type": "container_operation",
            "payload": {
                "action": "validate_ports",
                "ports": ports
            }
        }

        # This will raise RuntimeError if validation fails
        await self._execute_command(command, timeout=15.0)

    async def verify_container_running(self, container_id: str, max_wait_seconds: int = 60) -> bool:
        """
        Verify container is healthy and running.

        Waits for container health check or stability.
        """
        command = {
            "type": "container_operation",
            "payload": {
                "action": "verify_running",
                "container_id": container_id,
                "max_wait_seconds": max_wait_seconds
            }
        }

        try:
            response = await self._execute_command(command, timeout=float(max_wait_seconds + 10))
            return response.get("is_healthy", False)
        except Exception as e:
            logger.error(f"Error verifying container health: {e}")
            return False


def get_host_connector(host_id: str, docker_monitor=None) -> HostConnector:
    """
    Factory function to get appropriate HostConnector for a host.

    Checks host.connection_type in database and returns:
    - DirectDockerConnector for 'local' and 'remote' hosts (Docker SDK)
    - AgentConnector for 'agent' hosts (WebSocket commands)

    Args:
        host_id: Docker host ID
        docker_monitor: Optional DockerMonitor instance. If not provided,
                       will attempt to lazy-load from main.docker_monitor

    Returns:
        HostConnector implementation for the host

    Raises:
        ValueError: If host not found or connection_type invalid
    """
    from database import DatabaseManager, DockerHostDB

    # Get database manager
    db = DatabaseManager()

    # Query host to determine connection type
    with db.get_session() as session:
        host = session.query(DockerHostDB).filter_by(id=host_id).first()

        if not host:
            raise ValueError(f"Host {host_id} not found in database")

        connection_type = host.connection_type

    # Route based on connection type
    if connection_type in ('local', 'remote'):
        # Use direct Docker SDK connection
        return DirectDockerConnector(host_id, docker_monitor)

    elif connection_type == 'agent':
        # Use agent-based WebSocket connection
        # Lazy-load agent dependencies
        from agent.command_executor import get_agent_command_executor
        from agent.manager import AgentManager

        return AgentConnector(
            host_id,
            agent_command_executor=get_agent_command_executor(),
            agent_manager=AgentManager()
        )

    else:
        raise ValueError(
            f"Unknown connection_type '{connection_type}' for host {host_id}. "
            f"Expected: 'local', 'remote', or 'agent'"
        )
