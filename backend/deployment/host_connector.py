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

from utils.async_docker import async_docker_call
from utils.container_health import wait_for_container_health
from utils.image_pull_progress import ImagePullProgress
from utils.network_helpers import manually_connect_networks

logger = logging.getLogger(__name__)

# Import constants from stack_orchestrator (same keys used for network config)
# Import moved here to avoid circular dependency
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

        # If deployment_id provided, use layer-by-layer progress tracking
        if deployment_id:
            # Get connection_manager from docker_monitor for WebSocket broadcasting
            if self._docker_monitor is None:
                import main
                self._docker_monitor = main.docker_monitor

            connection_manager = getattr(self._docker_monitor, 'manager', None)

            # Create image pull tracker (shares code with update system)
            tracker = ImagePullProgress(
                loop=asyncio.get_event_loop(),
                connection_manager=connection_manager,
                progress_callback=progress_callback
            )

            # Pull with layer-by-layer progress broadcasting
            await tracker.pull_with_progress(
                client=client,
                image=image,
                host_id=self.host_id,
                entity_id=deployment_id,
                event_type="deployment_layer_progress",
                timeout=1800  # 30 minutes
            )
        else:
            # Fallback: Simple pull without progress (for backward compatibility)
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
        containers = await async_docker_call(client.containers.list)

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


def get_host_connector(host_id: str, docker_monitor=None) -> HostConnector:
    """
    Factory function to get appropriate HostConnector for a host.

    In v2.1: Always returns DirectDockerConnector (local or TCP+TLS)
    In v2.2: Will check host type and return AgentRPCConnector for agent hosts

    Args:
        host_id: Docker host ID
        docker_monitor: Optional DockerMonitor instance. If not provided,
                       will attempt to lazy-load from main.docker_monitor

    Returns:
        HostConnector implementation for the host
    """
    # v2.1: All hosts use DirectDockerConnector
    # v2.2: Will add logic to check host.type and return AgentRPCConnector
    return DirectDockerConnector(host_id, docker_monitor)
