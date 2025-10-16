"""
Container Discovery Module for DockMon
Handles container scanning, reconnection logic, and stats population
"""

import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import docker
from docker import DockerClient

from config.paths import CERTS_DIR
from database import DatabaseManager, DockerHostDB
from models.docker_models import DockerHost, Container, derive_container_tags
from event_bus import Event, EventType as BusEventType, get_event_bus
from stats_client import get_stats_client

logger = logging.getLogger(__name__)


def _handle_task_exception(task):
    """Handle exceptions from fire-and-forget async tasks"""
    try:
        task.result()
    except Exception as e:
        logger.error(f"Unhandled exception in background task: {e}", exc_info=True)


def parse_container_ports(port_bindings: dict) -> list[str]:
    """
    Parse Docker port bindings into human-readable format.

    Args:
        port_bindings: Docker NetworkSettings.Ports dict
        Example: {'80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8080'}], '443/tcp': None}

    Returns:
        List of formatted port strings like ["8080:80/tcp", "443/tcp"]

    Note:
        Deduplicates IPv4 and IPv6 bindings for the same port (e.g., 0.0.0.0 and ::)
    """
    if not port_bindings:
        return []

    ports_set = set()
    for container_port, host_bindings in port_bindings.items():
        if host_bindings:
            # Port is exposed to host
            # Track seen ports to avoid IPv4/IPv6 duplicates
            seen_host_ports = set()
            for binding in host_bindings:
                host_port = binding.get('HostPort', '')
                if host_port and host_port not in seen_host_ports:
                    ports_set.add(f"{host_port}:{container_port}")
                    seen_host_ports.add(host_port)
                elif not host_port:
                    ports_set.add(container_port)
        else:
            # Port is exposed but not bound to host
            ports_set.add(container_port)

    return sorted(list(ports_set))


def parse_restart_policy(host_config: dict) -> str:
    """
    Parse Docker restart policy from HostConfig.

    Args:
        host_config: Docker HostConfig dict

    Returns:
        Restart policy name (e.g., "always", "unless-stopped", "on-failure", "no")
    """
    restart_policy = host_config.get('RestartPolicy', {})
    policy_name = restart_policy.get('Name', 'no')

    # Include max retry count for on-failure policy
    if policy_name == 'on-failure':
        max_retry = restart_policy.get('MaximumRetryCount', 0)
        if max_retry > 0:
            return f"{policy_name}:{max_retry}"

    return policy_name if policy_name else 'no'


def parse_container_volumes(mounts: list) -> list[str]:
    """
    Parse Docker volume mounts into human-readable format.

    Args:
        mounts: Docker Mounts list from container attrs
        Example: [{'Type': 'bind', 'Source': '/host/path', 'Destination': '/container/path', 'Mode': 'rw'}]

    Returns:
        List of formatted volume strings like ["/host/path:/container/path:rw", "/container/anonymous"]
    """
    if not mounts:
        return []

    volumes = []
    for mount in mounts:
        mount_type = mount.get('Type', '')
        source = mount.get('Source', '')
        destination = mount.get('Destination', '')
        mode = mount.get('Mode', '')

        if mount_type == 'bind' and source and destination:
            # Bind mount: source:destination:mode
            vol_str = f"{source}:{destination}"
            if mode:
                vol_str += f":{mode}"
            volumes.append(vol_str)
        elif mount_type == 'volume' and source and destination:
            # Named volume: volume_name:destination:mode
            vol_str = f"{source}:{destination}"
            if mode:
                vol_str += f":{mode}"
            volumes.append(vol_str)
        elif destination:
            # Just destination (anonymous volume)
            volumes.append(destination)

    return volumes


def parse_container_env(env_list: list) -> dict[str, str]:
    """
    Parse Docker environment variables into dict.

    Args:
        env_list: Docker Env list from container Config
        Example: ['PATH=/usr/bin', 'NGINX_VERSION=1.21.0']

    Returns:
        Dict of environment variables like {'PATH': '/usr/bin', 'NGINX_VERSION': '1.21.0'}
    """
    if not env_list:
        return {}

    env_dict = {}
    for env_var in env_list:
        if '=' in env_var:
            key, value = env_var.split('=', 1)
            env_dict[key] = value

    return env_dict


class ContainerDiscovery:
    """Handles container discovery and reconnection logic"""

    def __init__(self, db: DatabaseManager, settings, hosts: Dict[str, DockerHost], clients: Dict[str, DockerClient], event_logger=None, alert_evaluation_service=None, websocket_manager=None, monitor=None):
        self.db = db
        self.settings = settings
        self.hosts = hosts
        self.clients = clients
        self.event_logger = event_logger
        self.alert_evaluation_service = alert_evaluation_service
        self.websocket_manager = websocket_manager
        self.monitor = monitor

        # Reconnection tracking with exponential backoff
        self.reconnect_attempts: Dict[str, int] = {}  # Track reconnect attempts per host
        self.last_reconnect_attempt: Dict[str, float] = {}  # Track last attempt time per host
        self.host_previous_status: Dict[str, str] = {}  # Track previous host status to detect transitions

    async def attempt_reconnection(self, host_id: str) -> bool:
        """
        Attempt to reconnect to an offline host with exponential backoff.

        Returns:
            True if reconnection successful, False otherwise
        """
        host = self.hosts.get(host_id)
        if not host:
            return False

        # Exponential backoff: 5s, 10s, 20s, 40s, 80s, max 5 minutes
        # attempts represents number of failures so far
        # First retry (after 1 failure, attempts=1) should wait 5s
        # Second retry (after 2 failures, attempts=2) should wait 10s, etc.
        now = time.time()
        attempts = self.reconnect_attempts.get(host_id, 0)
        last_attempt = self.last_reconnect_attempt.get(host_id, 0)
        # Subtract 1 from attempts to get correct backoff sequence: 5s, 10s, 20s, 40s...
        backoff_seconds = min(5 * (2 ** max(0, attempts - 1)), 300) if attempts > 0 else 0

        # Skip reconnection if we're in backoff period
        if now - last_attempt < backoff_seconds:
            time_remaining = backoff_seconds - (now - last_attempt)
            logger.debug(f"Skipping reconnection for {host.name} - backoff active (attempt {attempts}, {time_remaining:.1f}s remaining)")
            host.status = "offline"
            return False

        # Record this reconnection attempt
        self.last_reconnect_attempt[host_id] = now
        logger.info(f"Attempting to reconnect to offline host {host.name} (attempt {attempts + 1})")

        try:
            # Fetch TLS certs from database for reconnection
            with self.db.get_session() as session:
                db_host = session.query(DockerHostDB).filter_by(id=host_id).first()

            if host.url.startswith("unix://"):
                client = docker.DockerClient(base_url=host.url)
            elif db_host and db_host.tls_cert and db_host.tls_key and db_host.tls_ca:
                # Reconnect with TLS using certs from database
                logger.debug(f"Reconnecting to {host.name} with TLS")

                # Write certs to temporary files for TLS config
                # SECURITY: Protect against TOCTOU race conditions with exist_ok=False on first attempt
                cert_dir = os.path.join(CERTS_DIR, host_id)
                try:
                    os.makedirs(cert_dir, exist_ok=False)
                except FileExistsError:
                    # Directory already exists, verify it's actually a directory
                    if not os.path.isdir(cert_dir):
                        raise ValueError(f"Certificate path exists but is not a directory: {cert_dir}")

                cert_file = os.path.join(cert_dir, 'cert.pem')
                key_file = os.path.join(cert_dir, 'key.pem')
                ca_file = os.path.join(cert_dir, 'ca.pem') if db_host.tls_ca else None

                with open(cert_file, 'w') as f:
                    f.write(db_host.tls_cert)
                with open(key_file, 'w') as f:
                    f.write(db_host.tls_key)
                if ca_file:
                    with open(ca_file, 'w') as f:
                        f.write(db_host.tls_ca)

                # Set secure permissions
                os.chmod(cert_file, 0o600)
                os.chmod(key_file, 0o600)
                if ca_file:
                    os.chmod(ca_file, 0o600)

                tls_config = docker.tls.TLSConfig(
                    client_cert=(cert_file, key_file),
                    ca_cert=ca_file,
                    verify=bool(db_host.tls_ca)
                )

                client = docker.DockerClient(
                    base_url=host.url,
                    tls=tls_config,
                    timeout=self.settings.connection_timeout
                )
            else:
                # Reconnect without TLS
                client = docker.DockerClient(
                    base_url=host.url,
                    timeout=self.settings.connection_timeout
                )

            # Test the connection
            client.ping()
            # Connection successful - add to clients
            self.clients[host_id] = client

            # Reset reconnection attempts on success
            self.reconnect_attempts[host_id] = 0
            logger.info(f"Reconnected to offline host: {host.name}")

            # Log host reconnection event
            if self.event_logger:
                self.event_logger.log_host_connection(
                    host_name=host.name,
                    host_id=host_id,
                    host_url=host.url,
                    connected=True
                )

            # Broadcast host status change via WebSocket for real-time UI updates
            if self.websocket_manager:
                await self.websocket_manager.broadcast({
                    "type": "host_status_changed",
                    "data": {
                        "host_id": host_id,
                        "status": "online"
                    }
                })

            # Re-register with stats and events service
            try:
                stats_client = get_stats_client()
                tls_ca = db_host.tls_ca if db_host else None
                tls_cert = db_host.tls_cert if db_host else None
                tls_key = db_host.tls_key if db_host else None

                await stats_client.add_docker_host(host_id, host.url, tls_ca, tls_cert, tls_key)
                await stats_client.add_event_host(host_id, host.url, tls_ca, tls_cert, tls_key)
                logger.info(f"Re-registered {host.name} ({host_id[:8]}) with stats/events service after reconnection")
            except Exception as e:
                logger.warning(f"Failed to re-register {host.name} with Go services after reconnection: {e}")

            return True

        except Exception as e:
            # Increment reconnection attempts on failure
            self.reconnect_attempts[host_id] = attempts + 1

            # Still offline - update status
            host.status = "offline"
            host.error = f"Connection failed: {str(e)}"
            host.last_checked = datetime.now()

            # Log with backoff info to help debugging
            # Next backoff will be based on new attempt count (attempts + 1)
            next_attempt_in = min(5 * (2 ** max(0, attempts)), 300)
            logger.debug(f"Host {host.name} still offline (attempt {attempts + 1}). Next retry in {next_attempt_in}s")
            return False

    def discover_containers_for_host(self, host_id: str, get_auto_restart_status_fn) -> List[Container]:
        """
        Discover all containers for a single host.

        Args:
            host_id: The host ID to discover containers for
            get_auto_restart_status_fn: Function to get auto-restart status

        Returns:
            List of Container objects
        """
        containers = []
        host = self.hosts.get(host_id)
        if not host:
            return containers

        client = self.clients.get(host_id)
        if not client:
            return containers

        try:
            docker_containers = client.containers.list(all=True)

            # Track status transition to detect when host comes back online
            previous_status = self.host_previous_status.get(host_id, "unknown")
            host.status = "online"
            host.container_count = len(docker_containers)
            host.error = None

            # If host just came back online from offline, emit reconnection event
            if previous_status == "offline":
                logger.info(f"Host {host.name} reconnected (transitioned from offline to online)")

                # Emit host connected event via EventBus
                if self.alert_evaluation_service:
                    import asyncio
                    try:
                        task = asyncio.create_task(
                            get_event_bus(self.monitor).emit(Event(
                                event_type=BusEventType.HOST_CONNECTED,
                                scope_type='host',
                                scope_id=host_id,
                                scope_name=host.name,
                                host_id=host_id,
                                host_name=host.name,
                                data={"url": host.url}
                            ))
                        )
                        task.add_done_callback(_handle_task_exception)
                    except Exception as e:
                        logger.error(f"Failed to emit host connected event: {e}")

            # Update previous status
            self.host_previous_status[host_id] = "online"

            for dc in docker_containers:
                try:
                    container_id = dc.id[:12]

                    # Try to get image info, but handle missing images gracefully
                    try:
                        container_image = dc.image
                        image_name = container_image.tags[0] if container_image.tags else container_image.short_id
                    except Exception:
                        # Image may have been deleted - use image ID from container attrs
                        image_name = dc.attrs.get('Config', {}).get('Image', 'unknown')
                        if image_name == 'unknown':
                            # Try to get from ImageID in attrs
                            image_id = dc.attrs.get('Image', '')
                            if image_id.startswith('sha256:'):
                                image_name = image_id[:19]  # sha256: + first 12 chars
                            else:
                                image_name = image_id[:12] if image_id else 'unknown'

                    # Extract labels from Docker container
                    labels = dc.attrs.get('Config', {}).get('Labels', {}) or {}

                    # Extract compose project/service for sticky tags
                    compose_project = labels.get('com.docker.compose.project')
                    compose_service = labels.get('com.docker.compose.service')

                    # Reattach tags from previous containers with same logical identity (sticky tags)
                    # Only do this for NEW containers that don't have existing tag assignments
                    # Use SHORT ID (12 chars) for consistency with database storage
                    container_key = f"{host_id}:{dc.id[:12]}"
                    existing_tags = self.db.get_tags_for_subject('container', container_key)
                    if not existing_tags:  # Only reattach if no tags exist yet (new container)
                        try:
                            reattached_tags = self.db.reattach_tags_for_container(
                                host_id=host_id,
                                container_id=dc.id[:12],
                                container_name=dc.name,
                                compose_project=compose_project,
                                compose_service=compose_service
                            )
                            if reattached_tags:
                                # Log tag count only to avoid excessive logging
                                logger.debug(f"Reattached {len(reattached_tags)} tags to container {dc.name}")
                        except Exception as e:
                            # Don't fail container discovery if tag reattachment fails
                            logger.warning(f"Failed to reattach tags for container {dc.name}: {e}")

                    # Derive tags from labels
                    derived_tags = derive_container_tags(labels)

                    # Get custom tags from database (use SHORT ID for lookup)
                    custom_tags = self.db.get_tags_for_subject('container', container_key)

                    # Combine tags: custom tags first, then derived tags (remove duplicates)
                    tags = []
                    seen = set()
                    for tag in custom_tags + derived_tags:
                        if tag not in seen:
                            tags.append(tag)
                            seen.add(tag)

                    # Get desired state from database
                    desired_state = self.db.get_desired_state(host_id, container_id)

                    # Extract ports, restart policy, volumes, env
                    port_bindings = dc.attrs.get('NetworkSettings', {}).get('Ports', {})
                    ports = parse_container_ports(port_bindings)

                    host_config = dc.attrs.get('HostConfig', {})
                    restart_policy = parse_restart_policy(host_config)

                    mounts = dc.attrs.get('Mounts', [])
                    volumes = parse_container_volumes(mounts)

                    env_list = dc.attrs.get('Config', {}).get('Env', [])
                    env = parse_container_env(env_list)

                    container = Container(
                        id=dc.id[:12],  # Use SHORT ID consistently (12 chars)
                        short_id=container_id,
                        name=dc.name,
                        state=dc.status,
                        status=dc.attrs['State']['Status'],
                        host_id=host_id,
                        host_name=host.name,
                        image=image_name,
                        created=dc.attrs['Created'],
                        auto_restart=get_auto_restart_status_fn(host_id, container_id),
                        restart_attempts=0,  # Will be populated by caller
                        desired_state=desired_state,
                        ports=ports,
                        restart_policy=restart_policy,
                        volumes=volumes,
                        env=env,
                        labels=labels,
                        tags=tags
                    )
                    containers.append(container)
                except Exception as container_error:
                    # Log but don't fail the whole host for one bad container
                    logger.warning(f"Skipping container {dc.name if hasattr(dc, 'name') else 'unknown'} on {host.name} due to error: {container_error}")
                    continue

        except Exception as e:
            logger.error(f"Error getting containers from {host.name}: {e}")

            # Track status transition to detect when host goes offline
            previous_status = self.host_previous_status.get(host_id, "unknown")
            host.status = "offline"
            host.error = str(e)

            # If host just went from online to offline, log event and trigger alert
            if previous_status != "offline":
                logger.warning(f"Host {host.name} transitioned from {previous_status} to offline")

                # Log host disconnection event
                if self.event_logger:
                    self.event_logger.log_host_connection(
                        host_name=host.name,
                        host_id=host_id,
                        host_url=host.url,
                        connected=False,
                        error_message=str(e)
                    )

                # Broadcast host status change via WebSocket for real-time UI updates
                if self.websocket_manager:
                    import asyncio
                    try:
                        asyncio.create_task(
                            self.websocket_manager.broadcast({
                                "type": "host_status_changed",
                                "data": {
                                    "host_id": host_id,
                                    "status": "offline"
                                }
                            })
                        )
                    except Exception as ws_error:
                        logger.error(f"Failed to broadcast host status change: {ws_error}")

                # Emit host disconnection event via EventBus
                if self.alert_evaluation_service:
                    import asyncio
                    # Run async event emission in background
                    try:
                        task = asyncio.create_task(
                            get_event_bus(self.monitor).emit(Event(
                                event_type=BusEventType.HOST_DISCONNECTED,
                                scope_type='host',
                                scope_id=host_id,
                                scope_name=host.name,
                                host_id=host_id,
                                host_name=host.name,
                                data={
                                    "error": str(e),
                                    "url": host.url
                                }
                            ))
                        )
                        task.add_done_callback(_handle_task_exception)
                    except Exception as alert_error:
                        logger.error(f"Failed to emit host disconnection event: {alert_error}")

            # Update previous status
            self.host_previous_status[host_id] = "offline"

        host.last_checked = datetime.now()
        return containers

    async def populate_container_stats(self, containers: List[Container]) -> None:
        """
        Fetch stats from Go stats service and populate container stats.

        Args:
            containers: List of Container objects to populate with stats
        """
        try:
            stats_client = get_stats_client()
            container_stats = await stats_client.get_container_stats()

            # Populate stats for each container using composite key (host_id:container_id)
            for container in containers:
                # Use short_id for consistency with all other container operations
                composite_key = f"{container.host_id}:{container.short_id}"
                stats = container_stats.get(composite_key, {})
                if stats:
                    container.cpu_percent = stats.get('cpu_percent')
                    container.memory_usage = stats.get('memory_usage')
                    container.memory_limit = stats.get('memory_limit')
                    container.memory_percent = stats.get('memory_percent')
                    container.network_rx = stats.get('network_rx')
                    container.network_tx = stats.get('network_tx')
                    container.net_bytes_per_sec = stats.get('net_bytes_per_sec')
                    container.disk_read = stats.get('disk_read')
                    container.disk_write = stats.get('disk_write')
                    logger.debug(f"Populated stats for {container.name} ({container.short_id}) on {container.host_name}: CPU {container.cpu_percent}%")
        except Exception as e:
            logger.warning(f"Failed to fetch container stats from stats service: {e}")
