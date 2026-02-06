"""
Container Discovery Module for DockMon
Handles container scanning, reconnection logic, and stats population
"""

import logging
import os
import time
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Optional

import docker
from docker import DockerClient

from config.paths import CERTS_DIR
from database import DatabaseManager, DockerHostDB
from models.docker_models import DockerHost, Container, derive_container_tags
from event_bus import Event, EventType as BusEventType, get_event_bus
from stats_client import get_stats_client
from utils.async_docker import async_docker_call, async_client_ping
from utils.keys import make_composite_key
from utils.ip_extraction import extract_container_ips
from utils.cache import async_ttl_cache

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

        For agent-based hosts, checks if agent is connected.
        For legacy hosts (tcp/unix), creates new Docker client.

        Returns:
            True if reconnection successful, False otherwise
        """
        host = self.hosts.get(host_id)
        if not host:
            return False

        # Agent-based hosts use WebSocket connection, not Docker client
        if host.connection_type == "agent":
            from agent.connection_manager import agent_connection_manager
            from database import Agent

            # Check if agent is connected
            with self.db.get_session() as session:
                agent = session.query(Agent).filter_by(host_id=host_id).first()
                if not agent:
                    logger.warning(f"Agent host {host.name} has no associated agent record")
                    host.status = "offline"
                    host.error = "No agent record found"
                    return False

                agent_id = agent.id

            # Check if agent is connected via WebSocket
            if agent_connection_manager.is_connected(agent_id):
                # Agent is connected - mark host as online
                host.status = "online"
                host.error = None
                logger.debug(f"Agent host {host.name} is connected via agent {agent_id[:8]}...")

                # Reset reconnection attempts
                self.reconnect_attempts[host_id] = 0

                return True
            else:
                # Agent is not connected - host is offline
                logger.debug(f"Agent host {host.name} is offline - agent {agent_id[:8]}... not connected")
                host.status = "offline"
                host.error = "Agent not connected"
                return False

        # Legacy host (tcp/unix) - use Docker client reconnection
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
                client = await async_docker_call(docker.DockerClient, base_url=host.url, version="auto")
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

                client = await async_docker_call(
                    docker.DockerClient,
                    base_url=host.url,
                    tls=tls_config,
                    timeout=self.settings.connection_timeout,
                    version="auto",
                )
            else:
                # Reconnect without TLS
                client = await async_docker_call(
                    docker.DockerClient,
                    base_url=host.url,
                    timeout=self.settings.connection_timeout,
                    version="auto",
                )

            # Test the connection
            await async_client_ping(client)
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
            # Skip agent hosts - they use WebSocket for stats/events
            if host.connection_type != "agent":
                try:
                    stats_client = get_stats_client()
                    tls_ca = db_host.tls_ca if db_host else None
                    tls_cert = db_host.tls_cert if db_host else None
                    tls_key = db_host.tls_key if db_host else None
                    num_cpus = db_host.num_cpus if db_host else None

                    is_local = host.url.startswith("unix://")
                    await stats_client.add_docker_host(host_id, host.name, host.url, tls_ca, tls_cert, tls_key, num_cpus, is_local)
                    await stats_client.add_event_host(host_id, host.name, host.url, tls_ca, tls_cert, tls_key)
                    logger.info(f"Re-registered {host.name} ({host_id[:8]}) with stats/events service after reconnection")
                except Exception as e:
                    logger.warning(f"Failed to re-register {host.name} with Go services after reconnection: {e}")
            else:
                logger.debug(f"Skipped stats/event service re-registration for agent host {host.name} (uses WebSocket)")

            return True

        except Exception as e:
            # Increment reconnection attempts on failure
            self.reconnect_attempts[host_id] = attempts + 1

            # Still offline - update status
            host.status = "offline"
            host.error = f"Connection failed: {str(e)}"
            host.last_checked = datetime.now(timezone.utc)

            # Log with backoff info to help debugging
            # Next backoff will be based on new attempt count (attempts + 1)
            next_attempt_in = min(5 * (2 ** max(0, attempts)), 300)
            logger.debug(f"Host {host.name} still offline (attempt {attempts + 1}). Next retry in {next_attempt_in}s")
            return False

    @async_ttl_cache(ttl_seconds=5)
    async def discover_containers_for_host(self, host_id: str, get_auto_restart_status_fn) -> List[Container]:
        """
        Discover all containers for a single host.

        For agent-based hosts, requests container data via WebSocket.
        For legacy hosts, queries Docker API directly.

        Args:
            host_id: The host ID to discover containers for
            get_auto_restart_status_fn: Function to get auto-restart status

        Returns:
            List of Container objects
        """
        from utils.async_docker import async_containers_list

        containers = []
        host = self.hosts.get(host_id)
        if not host:
            return containers

        # Agent-based hosts - get container data from agent via WebSocket
        if host.connection_type == "agent":
            from agent.command_executor import get_agent_command_executor
            from database import Agent

            # Get agent ID
            with self.db.get_session() as session:
                agent = session.query(Agent).filter_by(host_id=host_id).first()
                if not agent:
                    logger.warning(f"No agent record for host {host.name}")
                    return containers

                agent_id = agent.id

            # Request container list from agent using command executor
            try:
                executor = get_agent_command_executor()

                # Use legacy command protocol (agent supports both legacy and new protocol)
                command = {
                    "type": "command",
                    "command": "list_containers"
                }

                result = await executor.execute_command(
                    agent_id,
                    command,
                    timeout=30.0
                )

                if not result.success:
                    logger.error(f"Failed to get containers from agent {agent_id[:8]}...: {result.error}")
                    host.status = "offline"
                    host.error = f"Agent error: {result.error}"
                    return containers

                # Parse container data from agent response
                # Agent returns Docker API format: list of container objects
                docker_containers = result.response if isinstance(result.response, list) else []

                host.status = "online"
                host.container_count = len(docker_containers)
                host.error = None

                # Convert Docker API container data to Container objects
                # Agent returns same format as Docker Python SDK
                for dc_data in docker_containers:
                    try:
                        # Extract container info from Docker API response
                        container_id = dc_data.get("Id", "")[:12]  # Use short ID (12 chars)

                        # Container name (remove leading slash)
                        # Use `or []` pattern to handle both missing keys AND null values
                        names = dc_data.get("Names") or []
                        container_name = names[0].lstrip("/") if names else "unknown"

                        # Image name
                        container_image = dc_data.get("Image", "unknown")

                        # Status and state
                        container_state = dc_data.get("State", "unknown")

                        # Map Docker state to DockMon status
                        if container_state in ["running", "paused", "restarting"]:
                            status = container_state
                        elif container_state in ["exited", "dead", "created"]:
                            status = "exited"
                        else:
                            status = "unknown"

                        # Extract labels and compose metadata
                        labels = dc_data.get("Labels") or {}
                        compose_project = labels.get("com.docker.compose.project")
                        compose_service = labels.get("com.docker.compose.service")

                        # Reattach tags (sticky tags feature)
                        container_key = make_composite_key(host_id, container_id)
                        existing_tags = self.db.get_tags_for_subject('container', container_key)
                        if not existing_tags:
                            try:
                                reattached_tags = self.db.reattach_tags_for_container(
                                    host_id=host_id,
                                    container_id=container_id,
                                    container_name=container_name,
                                    compose_project=compose_project,
                                    compose_service=compose_service
                                )
                                if reattached_tags:
                                    logger.debug(f"Reattached {len(reattached_tags)} tags to container {container_name}")
                            except Exception as e:
                                logger.warning(f"Failed to reattach tags: {e}")

                        # Reattach update settings (Issue #116 - settings were lost for agent hosts)
                        try:
                            self.db.reattach_update_settings_for_container(
                                host_id=host_id,
                                container_id=container_id,
                                container_name=container_name,
                                current_image=container_image,
                                compose_project=compose_project,
                                compose_service=compose_service
                            )
                        except Exception as e:
                            logger.warning(f"Failed to reattach update settings for {container_name}: {e}")

                        # Reattach HTTP health check configuration
                        try:
                            self.db.reattach_http_health_check_for_container(
                                host_id=host_id,
                                container_id=container_id,
                                container_name=container_name,
                                compose_project=compose_project,
                                compose_service=compose_service
                            )
                        except Exception as e:
                            logger.warning(f"Failed to reattach HTTP health check for {container_name}: {e}")

                        # Reattach deployment metadata
                        try:
                            self.db.reattach_deployment_metadata_for_container(
                                host_id=host_id,
                                container_id=container_id,
                                container_name=container_name,
                                compose_project=compose_project,
                                compose_service=compose_service
                            )
                        except Exception as e:
                            logger.warning(f"Failed to reattach deployment metadata for {container_name}: {e}")

                        # Derive tags from labels (compose:*, swarm:*, dockmon.tag)
                        derived_tags = derive_container_tags(labels)

                        # Get custom tags from database
                        custom_tags = self.db.get_tags_for_subject('container', container_key)

                        # Combine tags: custom tags first, then derived (remove duplicates)
                        tags = []
                        seen = set()
                        for tag in custom_tags + derived_tags:
                            if tag not in seen:
                                tags.append(tag)
                                seen.add(tag)

                        # Get auto-restart status
                        auto_restart = get_auto_restart_status_fn(host_id, container_id)

                        # Get desired state and web UI URL from database
                        desired_state, web_ui_url = self.db.get_desired_state(host_id, container_id)

                        # Extract ports - convert Docker API format to string list
                        # Docker API returns: [{"PrivatePort": 80, "PublicPort": 8080, "Type": "tcp", "IP": "0.0.0.0"}]
                        # We need: ["8080:80/tcp"]
                        # Use `or []` pattern to handle both missing keys AND null values
                        ports_data = dc_data.get("Ports") or []
                        ports = []
                        for port in ports_data:
                            private_port = port.get("PrivatePort")
                            public_port = port.get("PublicPort")
                            port_type = port.get("Type", "tcp")

                            if public_port:
                                # Published port: "host:container/type"
                                ports.append(f"{public_port}:{private_port}/{port_type}")
                            elif private_port:
                                # Exposed but not published: "container/type"
                                ports.append(f"{private_port}/{port_type}")

                        # Extract mounts/volumes - use existing helper function
                        # Use `or []` pattern to handle both missing keys AND null values
                        mounts = dc_data.get("Mounts") or []
                        volumes = parse_container_volumes(mounts)

                        # Restart policy (from HostConfig)
                        # Use `or {}` pattern to handle both missing keys AND null values
                        host_config = dc_data.get("HostConfig") or {}
                        restart_policy_data = host_config.get("RestartPolicy") or {}
                        restart_policy = restart_policy_data.get("Name", "no")

                        # Convert created timestamp if it's an int (Unix timestamp)
                        created_value = dc_data.get("Created", "")
                        if isinstance(created_value, int):
                            # Convert Unix timestamp to ISO 8601 string
                            created_str = datetime.fromtimestamp(created_value, tz=timezone.utc).isoformat()
                        else:
                            created_str = str(created_value) if created_value else ""

                        # Extract started_at from agent response (agent v1.0.1+ includes this)
                        started_at_str = dc_data.get("StartedAt")
                        if started_at_str:
                            started_at_str = str(started_at_str)

                        # Extract RepoDigests from agent response (v2.2.0+ agents)
                        # Use `or []` pattern to handle both missing keys AND null values
                        repo_digests = dc_data.get("RepoDigests") or []

                        # Extract Docker network IPs (GitHub Issue #37)
                        # Use `or {}` pattern to handle both missing keys AND null values
                        network_settings = dc_data.get("NetworkSettings") or {}
                        docker_ip, docker_ips = extract_container_ips(network_settings)

                        # Create Container object
                        container = Container(
                            id=container_id,  # Short 12-char ID (per CLAUDE.md spec)
                            short_id=container_id,  # Short 12-char ID
                            name=container_name,
                            image=container_image,
                            status=status,
                            state=container_state,
                            created=created_str,
                            started_at=started_at_str,
                            host_id=host_id,
                            host_name=host.name,
                            ports=ports,
                            volumes=volumes,
                            restart_policy=restart_policy,
                            auto_restart=auto_restart,
                            desired_state=desired_state,
                            web_ui_url=web_ui_url,
                            labels=labels,
                            compose_project=compose_project,
                            compose_service=compose_service,
                            tags=tags,
                            environment={},  # Not available in list response
                            repo_digests=repo_digests,  # Image digests for update checking
                            docker_ip=docker_ip,
                            docker_ips=docker_ips
                        )

                        containers.append(container)

                    except Exception as e:
                        # Log container info to help debug which container is failing
                        container_info = f"id={dc_data.get('Id', 'unknown')[:12]}, names={dc_data.get('Names', 'unknown')}"
                        logger.error(f"Error parsing agent container data ({container_info}): {e}\n{traceback.format_exc()}")
                        continue

                logger.debug(f"Discovered {len(containers)} containers from agent {agent_id[:8]}... for host {host.name}")
                return containers

            except Exception as e:
                logger.error(f"Error getting containers from agent {agent_id[:8]}...: {e}", exc_info=True)
                host.status = "offline"
                host.error = f"Agent error: {str(e)}"
                return containers

        # Legacy host (tcp/unix) - use Docker client
        client = self.clients.get(host_id)
        if not client:
            return containers

        try:
            docker_containers = await async_containers_list(client, all=True)

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
                        config_image_name = dc.attrs.get('Config', {}).get('Image', container_image.short_id)
                        if ":" not in config_image_name:
                            # Add implicit :latest if tag is missing
                            config_image_name = f"{config_image_name}:latest"

                        if container_image.tags:
                            if config_image_name in container_image.tags:
                                # Container has tags and one of the tags matches the config
                                image_name = config_image_name
                                logger.debug(f"Container has tags and one of the tags matches the config {image_name}")
                            else:
                                # Container has tags but no config matches - use first tag
                                image_name = container_image.tags[0]
                                logger.debug(f"Container has tags {container_image.tags} but none of the tags matches the config {config_image_name} using {image_name}")
                        else:
                            # No tags (digest-based pull) - use the image reference from container config
                            # This preserves the full repository name even for digest-based pulls
                            # e.g., "portainer/portainer-ce@sha256:abc123" instead of just "sha256:abc123"
                            image_name = config_image_name
                            logger.debug(f"Container has no tags, using the config {config_image_name}")
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
                    container_key = make_composite_key(host_id, dc.id[:12])
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

                    # Reattach configuration from previous containers (TrueNAS container recreation support)
                    # These methods are idempotent and safe to call on every discovery

                    # Reattach auto-restart configuration
                    try:
                        self.db.reattach_auto_restart_for_container(
                            host_id=host_id,
                            container_id=dc.id[:12],
                            container_name=dc.name,
                            compose_project=compose_project,
                            compose_service=compose_service
                        )
                    except Exception as e:
                        logger.warning(f"Failed to reattach auto-restart for {dc.name}: {e}")

                    # Reattach desired state
                    try:
                        self.db.reattach_desired_state_for_container(
                            host_id=host_id,
                            container_id=dc.id[:12],
                            container_name=dc.name,
                            compose_project=compose_project,
                            compose_service=compose_service
                        )
                    except Exception as e:
                        logger.warning(f"Failed to reattach desired state for {dc.name}: {e}")

                    # Reattach HTTP health check
                    try:
                        self.db.reattach_http_health_check_for_container(
                            host_id=host_id,
                            container_id=dc.id[:12],
                            container_name=dc.name,
                            compose_project=compose_project,
                            compose_service=compose_service
                        )
                    except Exception as e:
                        logger.warning(f"Failed to reattach HTTP health check for {dc.name}: {e}")

                    # Reattach update settings
                    try:
                        self.db.reattach_update_settings_for_container(
                            host_id=host_id,
                            container_id=dc.id[:12],
                            container_name=dc.name,
                            current_image=image_name,
                            compose_project=compose_project,
                            compose_service=compose_service
                        )
                    except Exception as e:
                        logger.warning(f"Failed to reattach update settings for {dc.name}: {e}")

                    # Reattach deployment metadata
                    try:
                        self.db.reattach_deployment_metadata_for_container(
                            host_id=host_id,
                            container_id=dc.id[:12],
                            container_name=dc.name,
                            compose_project=compose_project,
                            compose_service=compose_service
                        )
                    except Exception as e:
                        logger.warning(f"Failed to reattach deployment metadata for {dc.name}: {e}")

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

                    # Get desired state and web UI URL from database
                    desired_state, web_ui_url = self.db.get_desired_state(host_id, container_id)

                    # Extract ports, restart policy, volumes, env
                    network_settings = dc.attrs.get('NetworkSettings', {})
                    port_bindings = network_settings.get('Ports', {})
                    ports = parse_container_ports(port_bindings)

                    # Extract container Docker network IPs (GitHub Issue #37)
                    docker_ip, docker_ips = extract_container_ips(network_settings)

                    host_config = dc.attrs.get('HostConfig', {})
                    restart_policy = parse_restart_policy(host_config)

                    mounts = dc.attrs.get('Mounts', [])
                    volumes = parse_container_volumes(mounts)

                    env_list = dc.attrs.get('Config', {}).get('Env', [])
                    env = parse_container_env(env_list)

                    container = Container(
                        id=container_id,  # Short 12-char ID (per CLAUDE.md spec)
                        short_id=container_id,  # Short 12-char ID
                        name=dc.name,
                        state=dc.status,
                        status=dc.attrs['State']['Status'],
                        host_id=host_id,
                        host_name=host.name,
                        image=image_name,
                        created=dc.attrs['Created'],
                        started_at=dc.attrs['State'].get('StartedAt'),
                        auto_restart=get_auto_restart_status_fn(host_id, container_id),
                        restart_attempts=0,  # Will be populated by caller
                        desired_state=desired_state,
                        web_ui_url=web_ui_url,
                        ports=ports,
                        restart_policy=restart_policy,
                        volumes=volumes,
                        env=env,
                        labels=labels,
                        tags=tags,
                        docker_ip=docker_ip,
                        docker_ips=docker_ips
                    )
                    containers.append(container)
                except Exception as container_error:
                    # Log but don't fail the whole host for one bad container
                    logger.warning(f"Skipping container {dc.name if hasattr(dc, 'name') else 'unknown'} on {host.name} due to error: {container_error}")
                    continue

        except docker.errors.NotFound as e:
            # Container was deleted between list() and attribute access - this is normal during bulk deletions
            logger.debug(f"Container not found on {host.name} (likely deleted during discovery): {e}")
            # Don't mark host as offline for missing containers
            return containers

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

        host.last_checked = datetime.now(timezone.utc)
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
                composite_key = make_composite_key(container.host_id, container.short_id)

                # For agent hosts, get stats from WebSocket cache instead of stats service
                # Agent containers send stats via WebSocket, not Docker API polling
                if hasattr(self, 'monitor') and self.monitor:
                    host = self.monitor.hosts.get(container.host_id)
                    if host and host.connection_type == "agent":
                        # Get latest full stats from agent cache (includes all fields: cpu, memory_usage, memory_limit, etc.)
                        if hasattr(self.monitor, 'agent_container_stats_cache'):
                            cached_stats = self.monitor.agent_container_stats_cache.get(composite_key, {})
                            if cached_stats:
                                # Populate all stats fields from agent cache
                                container.cpu_percent = cached_stats.get('cpu_percent')
                                container.memory_usage = cached_stats.get('memory_usage')
                                container.memory_limit = cached_stats.get('memory_limit')
                                container.memory_percent = cached_stats.get('memory_percent')
                                container.network_rx = cached_stats.get('network_rx')
                                container.network_tx = cached_stats.get('network_tx')
                                # Use pre-calculated net_bytes_per_sec from WebSocket handler
                                container.net_bytes_per_sec = cached_stats.get('net_bytes_per_sec', 0)
                                container.disk_read = cached_stats.get('disk_read')
                                container.disk_write = cached_stats.get('disk_write')
                                logger.debug(f"Populated stats for agent container {container.name} from WebSocket cache: CPU {container.cpu_percent}%, RAM {container.memory_percent}%")
                        continue  # Skip stats service lookup for agent containers

                # For non-agent hosts, use stats service (existing logic)
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
