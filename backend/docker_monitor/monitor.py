"""
Docker Monitoring Core for DockMon
Main monitoring class for Docker containers and hosts
"""

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

import docker
from docker import DockerClient
from fastapi import HTTPException

from config.paths import DATABASE_PATH, CERTS_DIR
from database import DatabaseManager, AutoRestartConfig, GlobalSettings, DockerHostDB
from models.docker_models import DockerHost, DockerHostConfig, Container
from models.settings_models import AlertRule, NotificationSettings
from websocket.connection import ConnectionManager
from realtime import RealtimeMonitor
from notifications import NotificationService
from event_logger import EventLogger, EventSeverity, EventType
from event_bus import Event, EventType as BusEventType, get_event_bus
from stats_client import get_stats_client
from docker_monitor.stats_manager import StatsManager
from docker_monitor.stats_history import StatsHistoryBuffer, ContainerStatsHistoryBuffer
from docker_monitor.container_discovery import ContainerDiscovery
from docker_monitor.state_manager import StateManager
from docker_monitor.operations import ContainerOperations
from docker_monitor.periodic_jobs import PeriodicJobsManager
from auth.session_manager import session_manager
from utils.keys import make_composite_key


logger = logging.getLogger(__name__)

# State update race condition prevention (Issue #3 fix)
# Reject polling updates within this window if recent event exists
STATE_UPDATE_STALE_THRESHOLD = 2.0  # seconds


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


def _fetch_system_info_from_docker(client: DockerClient, host_name: str) -> dict:
    """
    Fetch system information from Docker daemon.

    Args:
        client: Docker client instance
        host_name: Name of the host (for logging)

    Returns:
        Dict with system info keys (os_type, os_version, etc.)
        Returns dict with None values if fetch fails
    """

    try:
        # Fetch system information
        system_info = client.info()
        version_info = client.version()

        os_type = system_info.get('OSType', None)
        os_version = system_info.get('OperatingSystem', None)
        kernel_version = system_info.get('KernelVersion', None)
        total_memory = system_info.get('MemTotal', None)
        num_cpus = system_info.get('NCPU', None)

        docker_version = version_info.get('Version', None)

        # Detect Podman vs Docker (Issue #20)
        # Check Platform.Name first (some Podman versions)
        platform_name = version_info.get('Platform', {}).get('Name', '')
        is_podman = 'podman' in platform_name.lower()

        # Also check Components array (Podman 5.x puts "Podman Engine" there)
        if not is_podman:
            components = version_info.get('Components', [])
            for component in components:
                if 'podman' in component.get('Name', '').lower():
                    is_podman = True
                    break

        # Get Docker daemon start time from bridge network creation
        daemon_started_at = None
        try:
            networks = client.networks.list()
            bridge_net = next((n for n in networks if n.name == 'bridge'), None)
            if bridge_net:
                daemon_started_at = bridge_net.attrs.get('Created')
        except Exception as e:
            logger.debug(f"Failed to get daemon start time for {host_name}: {e}")

        return {
            'os_type': os_type,
            'os_version': os_version,
            'kernel_version': kernel_version,
            'docker_version': docker_version,
            'daemon_started_at': daemon_started_at,
            'total_memory': total_memory,
            'num_cpus': num_cpus,
            'is_podman': is_podman
        }
    except Exception as e:
        logger.warning(f"Failed to fetch system info for {host_name}: {e}")
        return {
            'os_type': None,
            'os_version': None,
            'kernel_version': None,
            'docker_version': None,
            'daemon_started_at': None,
            'total_memory': None,
            'num_cpus': None,
            'is_podman': False  # Default to Docker behavior on failure
        }


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
        Example: [{'Type': 'bind', 'Source': '/var/www', 'Destination': '/usr/share/nginx/html'}]

    Returns:
        List of formatted volume strings like ["/var/www:/usr/share/nginx/html", "volume-name:/data"]
    """
    if not mounts:
        return []

    volumes = []
    for mount in mounts:
        mount_type = mount.get('Type', '')
        source = mount.get('Source', '')
        destination = mount.get('Destination', '')

        if source and destination:
            # Format: source:destination (works for both bind mounts and named volumes)
            volumes.append(f"{source}:{destination}")
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


def _handle_task_exception(task: asyncio.Task) -> None:
    """Handle exceptions from fire-and-forget async tasks"""
    try:
        task.result()
    except asyncio.CancelledError:
        pass  # Task was cancelled, this is normal
    except Exception as e:
        logger.error(f"Unhandled exception in background task: {e}", exc_info=True)


def sanitize_host_id(host_id: str) -> str:
    """
    Sanitize host ID to prevent path traversal attacks.
    Only allows valid UUID format or alphanumeric + dash characters.
    """
    if not host_id:
        raise ValueError("Host ID cannot be empty")

    # Check for path traversal attempts
    if ".." in host_id or "/" in host_id or "\\" in host_id:
        raise ValueError(f"Invalid host ID format: {host_id}")

    # Try to validate as UUID first
    try:
        uuid.UUID(host_id)
        return host_id
    except ValueError:
        # If not a valid UUID, only allow alphanumeric and dashes
        import re
        if re.match(r'^[a-zA-Z0-9\-]+$', host_id):
            return host_id
        else:
            raise ValueError(f"Invalid host ID format: {host_id}")


class DockerMonitor:
    """Main monitoring class for Docker containers"""

    def __init__(self):
        self.hosts: Dict[str, DockerHost] = {}
        self.clients: Dict[str, DockerClient] = {}
        self.db = DatabaseManager(DATABASE_PATH)  # Initialize database with centralized path
        self.settings = self.db.get_settings()  # Load settings from DB
        self.notification_settings = NotificationSettings()
        self.auto_restart_status: Dict[str, bool] = {}
        self.restart_attempts: Dict[str, int] = {}
        self.restarting_containers: Dict[str, bool] = {}  # Track containers currently being restarted
        self.monitoring_task: Optional[asyncio.Task] = None

        # Reconnection tracking with exponential backoff
        self.reconnect_attempts: Dict[str, int] = {}  # Track reconnect attempts per host
        self.last_reconnect_attempt: Dict[str, float] = {}  # Track last attempt time per host
        self.manager = ConnectionManager()
        self.realtime = RealtimeMonitor()  # Real-time monitoring
        self.event_logger = EventLogger(self.db, self.manager)  # Event logging service with WebSocket support
        self.notification_service = NotificationService(self.db, self.event_logger)  # Notification service (v1 - for channels only)
        self._container_states: Dict[str, str] = {}  # Track container states for change detection
        self._container_state_timestamps: Dict[str, datetime] = {}  # Track when state last updated (Issue #3 fix)
        self._container_state_sources: Dict[str, str] = {}  # Track update source: 'event' or 'poll' (Issue #3 fix)
        self._last_containers: List = []  # Cache of containers from last monitor cycle (for alert evaluation)
        self._recent_user_actions: Dict[str, float] = {}  # Track recent user actions: {container_key: timestamp}
        self.alert_evaluation_service = None  # Will be set by main.py after initialization
        self.maintenance_task: Optional[asyncio.Task] = None  # Background maintenance task (daily cleanup, updates, etc.)

        # Locks for shared data structures to prevent race conditions
        self._state_lock = asyncio.Lock()
        self._actions_lock = asyncio.Lock()
        self._restart_lock = asyncio.Lock()

        # Stats collection manager
        self.stats_manager = StatsManager()

        # Stats history buffer for sparklines (Phase 4c)
        self.stats_history = StatsHistoryBuffer()
        self.container_stats_history = ContainerStatsHistoryBuffer()

        # Track previous network stats for rate calculation (Phase 4c)
        self._last_net_stats: Dict[str, float] = {}  # host_id -> cumulative bytes

        # Initialize specialized modules
        self.discovery = ContainerDiscovery(
            self.db,
            self.settings,
            self.hosts,
            self.clients,
            event_logger=self.event_logger,
            alert_evaluation_service=None,  # Will be set after alert_evaluation_service is initialized
            websocket_manager=self.manager,  # Pass ConnectionManager for real-time host status updates
            monitor=self  # Pass self for EventBus access
        )
        # Share reconnection tracking with discovery module
        self.discovery.reconnect_attempts = self.reconnect_attempts
        self.discovery.last_reconnect_attempt = self.last_reconnect_attempt

        self.state_manager = StateManager(self.db, self.hosts, self.clients, self.settings)
        # Share state dictionaries with state_manager
        self.state_manager.auto_restart_status = self.auto_restart_status
        self.state_manager.restart_attempts = self.restart_attempts
        self.state_manager.restarting_containers = self.restarting_containers

        self.operations = ContainerOperations(self.hosts, self.clients, self.event_logger, self._recent_user_actions, self.db, self)
        self.periodic_jobs = PeriodicJobsManager(self.db, self.event_logger)
        self.periodic_jobs.monitor = self  # Set monitor reference for auto-resolve

        self._load_persistent_config()  # Load saved hosts and configs

    def add_host(self, config: DockerHostConfig, existing_id: str = None, skip_db_save: bool = False, suppress_event_loop_errors: bool = False) -> DockerHost:
        """Add a new Docker host to monitor"""
        client = None  # Track client for cleanup on error
        cert_dir = None  # Track cert directory for cleanup on error
        try:
            # Check if host URL already exists (prevent duplicates)
            if not skip_db_save:  # Only check for new hosts, not when loading from DB
                for existing_host in self.hosts.values():
                    if existing_host.url == config.url:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Host with URL '{config.url}' already exists as '{existing_host.name}'"
                        )

            # Validate certificates if provided (before trying to use them)
            if config.tls_cert or config.tls_key or config.tls_ca:
                self._validate_certificates(config)

            # Generate and sanitize host ID ONCE (used for both cert storage and host record)
            # This ensures cert directory cleanup works correctly when host is removed
            host_id = existing_id or str(uuid.uuid4())
            try:
                host_id = sanitize_host_id(host_id)
            except ValueError as e:
                logger.error(f"Invalid host ID: {e}")
                raise HTTPException(status_code=400, detail=str(e))

            # Create Docker client
            if config.url.startswith("unix://"):
                client = docker.DockerClient(base_url=config.url)
            else:
                # For TCP connections
                tls_config = None
                if config.tls_cert and config.tls_key:
                    # Create persistent certificate storage directory using the host ID
                    cert_dir = os.path.join(CERTS_DIR, host_id)

                    # Create with secure permissions - handle TOCTOU race condition
                    try:
                        os.makedirs(cert_dir, mode=0o700, exist_ok=False)
                    except FileExistsError:
                        # Verify it's actually a directory and not a symlink/file
                        import stat
                        st = os.lstat(cert_dir)  # Use lstat to not follow symlinks
                        if not stat.S_ISDIR(st.st_mode):
                            raise ValueError("Certificate path exists but is not a directory")

                    # Write certificate files
                    cert_file = os.path.join(cert_dir, 'client-cert.pem')
                    key_file = os.path.join(cert_dir, 'client-key.pem')
                    ca_file = os.path.join(cert_dir, 'ca.pem') if config.tls_ca else None

                    with open(cert_file, 'w') as f:
                        f.write(config.tls_cert)
                    with open(key_file, 'w') as f:
                        f.write(config.tls_key)
                    if ca_file and config.tls_ca:
                        with open(ca_file, 'w') as f:
                            f.write(config.tls_ca)

                    # Set secure permissions
                    os.chmod(cert_file, 0o600)
                    os.chmod(key_file, 0o600)
                    if ca_file:
                        os.chmod(ca_file, 0o600)

                    tls_config = docker.tls.TLSConfig(
                        client_cert=(cert_file, key_file),
                        ca_cert=ca_file,
                        verify=bool(config.tls_ca)
                    )

                client = docker.DockerClient(
                    base_url=config.url,
                    tls=tls_config,
                    timeout=self.settings.connection_timeout
                )

            # Test connection
            client.ping()

            # Fetch system information using shared helper
            sys_info = _fetch_system_info_from_docker(client, config.name)
            os_type = sys_info['os_type']
            os_version = sys_info['os_version']
            kernel_version = sys_info['kernel_version']
            docker_version = sys_info['docker_version']
            daemon_started_at = sys_info['daemon_started_at']
            total_memory = sys_info['total_memory']
            num_cpus = sys_info['num_cpus']
            is_podman = sys_info.get('is_podman', False)

            # Validate TLS configuration for TCP connections
            security_status = self._validate_host_security(config)

            # Create host object (host_id already generated and sanitized above)
            host = DockerHost(
                id=host_id,
                name=config.name,
                url=config.url,
                status="online",
                security_status=security_status,
                tags=config.tags,
                description=config.description,
                os_type=os_type,
                os_version=os_version,
                kernel_version=kernel_version,
                docker_version=docker_version,
                daemon_started_at=daemon_started_at,
                total_memory=total_memory,
                num_cpus=num_cpus,
                is_podman=is_podman
            )

            # Store client and host
            self.clients[host.id] = client
            self.hosts[host.id] = host

            # Update OS info in database if reconnecting (when info wasn't saved before)
            if skip_db_save and (os_type or os_version or kernel_version or docker_version or daemon_started_at or total_memory or num_cpus):
                # Update existing host with OS info
                try:
                    with self.db.get_session() as session:
                        db_host = session.query(DockerHostDB).filter(DockerHostDB.id == host.id).first()
                        if db_host:
                            if os_type:
                                db_host.os_type = os_type
                            if os_version:
                                db_host.os_version = os_version
                            if kernel_version:
                                db_host.kernel_version = kernel_version
                            if docker_version:
                                db_host.docker_version = docker_version
                            if daemon_started_at:
                                db_host.daemon_started_at = daemon_started_at
                            if total_memory:
                                db_host.total_memory = total_memory
                            if num_cpus:
                                db_host.num_cpus = num_cpus
                            # Always update is_podman (Issue #20)
                            db_host.is_podman = is_podman
                            session.commit()
                except Exception as e:
                    logger.warning(f"Failed to update OS info for {host.name}: {e}")
                else:
                    platform_type = "Podman" if is_podman else "Docker"
                    logger.info(f"Updated OS info for {host.name}: {os_version} / {platform_type} {docker_version}")

            # Save to database only if not reconnecting to an existing host
            if not skip_db_save:
                # Serialize tags as JSON for database storage
                tags_json = json.dumps(config.tags) if config.tags else None

                db_host = self.db.add_host({
                    'id': host.id,
                    'name': config.name,
                    'url': config.url,
                    'tls_cert': config.tls_cert,
                    'tls_key': config.tls_key,
                    'tls_ca': config.tls_ca,
                    'security_status': security_status,
                    'tags': tags_json,
                    'description': config.description,
                    'os_type': host.os_type,
                    'os_version': host.os_version,
                    'kernel_version': host.kernel_version,
                    'docker_version': host.docker_version,
                    'daemon_started_at': host.daemon_started_at,
                    'total_memory': host.total_memory,
                    'num_cpus': host.num_cpus,
                    'is_podman': host.is_podman
                })

            # Register host with stats and event services
            # Only register if we're adding a NEW host (not during startup/reconnect)
            # During startup, monitor_containers() handles all registrations
            if not skip_db_save:  # New host being added by user
                try:
                    import asyncio
                    stats_client = get_stats_client()

                    async def register_host():
                        try:
                            await stats_client.add_docker_host(host.id, host.name, host.url, config.tls_ca, config.tls_cert, config.tls_key)
                            logger.info(f"Registered {host.name} ({host.id[:8]}) with stats service")

                            await stats_client.add_event_host(host.id, host.name, host.url, config.tls_ca, config.tls_cert, config.tls_key)
                            logger.info(f"Registered {host.name} ({host.id[:8]}) with event service")
                        except Exception as e:
                            logger.error(f"Failed to register {host.name} with Go services: {e}")

                    # Try to create task if event loop is running
                    try:
                        task = asyncio.create_task(register_host())
                        task.add_done_callback(_handle_task_exception)
                    except RuntimeError:
                        # No event loop running - will be registered by monitor_containers()
                        logger.debug(f"No event loop yet - {host.name} will be registered when monitoring starts")
                except Exception as e:
                    logger.warning(f"Could not register {host.name} with Go services: {e}")

            # Log host connection
            self.event_logger.log_host_connection(
                host_name=host.name,
                host_id=host.id,
                host_url=config.url,
                connected=True
            )

            # Log host added (only for new hosts, not reconnects)
            if not skip_db_save:
                self.event_logger.log_host_added(
                    host_name=host.name,
                    host_id=host.id,
                    host_url=config.url,
                    triggered_by="user"
                )

            logger.info(f"Added Docker host: {host.name} ({host.url})")
            return host

        except Exception as e:
            # Clean up client if it was created but not stored
            if client is not None:
                try:
                    client.close()
                    logger.debug(f"Closed orphaned Docker client for {config.name}")
                except Exception as close_error:
                    logger.debug(f"Error closing Docker client: {close_error}")

            # SECURITY: Clean up certificate directory if created but host add failed
            # This prevents private key leaks when TLS handshake or connection fails
            if cert_dir is not None and os.path.exists(cert_dir):
                try:
                    shutil.rmtree(cert_dir)
                    logger.info(f"Cleaned up certificate directory after failed host add: {cert_dir}")
                except Exception as cleanup_error:
                    logger.error(f"Failed to cleanup certificate directory {cert_dir}: {cleanup_error}")

            # Suppress event loop errors during first run startup
            if suppress_event_loop_errors and "no running event loop" in str(e):
                logger.debug(f"Event loop warning for {config.name} (expected during startup): {e}")
                # Re-raise so the caller knows host was added but with event loop issue
                raise
            else:
                logger.error(f"Failed to add host {config.name}: {e}")
                error_msg = self._get_user_friendly_error(str(e))
                raise HTTPException(status_code=400, detail=error_msg)

    def _get_user_friendly_error(self, error: str) -> str:
        """Convert technical Docker errors to user-friendly messages"""
        error_lower = error.lower()

        # SSL/TLS certificate errors
        if 'ssl' in error_lower or 'tls' in error_lower:
            if 'pem lib' in error_lower or 'pem' in error_lower:
                return (
                    "SSL certificate error: The certificates provided appear to be invalid or don't match. "
                    "Please verify:\n"
                    "• The certificates are for the correct server (check hostname/IP)\n"
                    "• The client certificate and private key are a matching pair\n"
                    "• The CA certificate matches the server's certificate\n"
                    "• The certificates haven't expired"
                )
            elif 'certificate verify failed' in error_lower:
                return (
                    "SSL certificate verification failed: The server's certificate is not trusted by the CA certificate you provided. "
                    "Make sure you're using the correct CA certificate that signed the server's certificate."
                )
            elif 'ssleof' in error_lower or 'connection reset' in error_lower:
                return (
                    "SSL connection failed: The server closed the connection during SSL handshake. "
                    "This usually means the server doesn't recognize the certificates. "
                    "Verify you're using the correct certificates for this server."
                )
            else:
                return f"SSL/TLS error: Unable to establish secure connection. {error}"

        # Connection errors
        elif 'connection refused' in error_lower:
            return (
                "Connection refused: The Docker daemon is not accepting connections on this address. "
                "Make sure:\n"
                "• Docker is running on the remote host\n"
                "• The Docker daemon is configured to listen on the specified port\n"
                "• Firewall allows connections to the port"
            )
        elif 'timeout' in error_lower or 'timed out' in error_lower:
            return (
                "Connection timeout: Unable to reach the Docker daemon. "
                "Check that the host address is correct and the host is reachable on your network."
            )
        elif 'no route to host' in error_lower or 'network unreachable' in error_lower:
            return (
                "Network unreachable: Cannot reach the specified host. "
                "Verify the IP address/hostname is correct and the host is on your network."
            )
        elif 'http request to an https server' in error_lower:
            return (
                "Protocol mismatch: You're trying to connect without TLS to a server that requires TLS. "
                "The server expects HTTPS connections. Please provide TLS certificates or change the server configuration."
            )

        # Return original error if we don't have a friendly version
        return error

    def _validate_certificates(self, config: DockerHostConfig):
        """Validate certificate format before attempting to use them"""

        def check_cert_format(cert_data: str, cert_type: str):
            """Check if certificate has proper PEM format markers"""
            if not cert_data or not cert_data.strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"{cert_type} is empty. Please paste the certificate content."
                )

            cert_data = cert_data.strip()

            # Check for BEGIN marker
            if "-----BEGIN" not in cert_data:
                raise HTTPException(
                    status_code=400,
                    detail=f"{cert_type} is missing the '-----BEGIN' header. Make sure you copied the complete certificate including the BEGIN line."
                )

            # Check for END marker
            if "-----END" not in cert_data:
                raise HTTPException(
                    status_code=400,
                    detail=f"{cert_type} is missing the '-----END' footer. Make sure you copied the complete certificate including the END line."
                )

            # Check BEGIN comes before END
            begin_pos = cert_data.find("-----BEGIN")
            end_pos = cert_data.find("-----END")
            if begin_pos >= end_pos:
                raise HTTPException(
                    status_code=400,
                    detail=f"{cert_type} format is invalid. The '-----BEGIN' line should come before the '-----END' line."
                )

            # Check for certificate data between markers
            cert_content = cert_data[begin_pos:end_pos + 50]  # Include END marker
            lines = cert_content.split('\n')
            if len(lines) < 3:  # Should have BEGIN, at least one data line, and END
                raise HTTPException(
                    status_code=400,
                    detail=f"{cert_type} appears to be incomplete. Make sure you copied all lines between BEGIN and END."
                )

        # Validate each certificate type
        if config.tls_ca:
            check_cert_format(config.tls_ca, "CA Certificate")

        if config.tls_cert:
            check_cert_format(config.tls_cert, "Client Certificate")

        if config.tls_key:
            # Private keys can be PRIVATE KEY or RSA PRIVATE KEY
            key_data = config.tls_key.strip()
            if "-----BEGIN" not in key_data or "-----END" not in key_data:
                raise HTTPException(
                    status_code=400,
                    detail="Client Private Key is incomplete. Make sure you copied the complete key including both '-----BEGIN' and '-----END' lines."
                )

    def _validate_host_security(self, config: DockerHostConfig) -> str:
        """Validate the security configuration of a Docker host"""
        if config.url.startswith("unix://"):
            return "secure"  # Unix sockets are secure (local only)
        elif config.url.startswith("tcp://"):
            if config.tls_cert and config.tls_key and config.tls_ca:
                return "secure"  # Has TLS certificates
            else:
                logger.warning(f"Host {config.name} configured without TLS - connection is insecure!")
                return "insecure"  # TCP without TLS
        else:
            return "unknown"  # Unknown protocol

    def _cleanup_host_certificates(self, host_id: str):
        """Clean up certificate files for a host"""
        safe_id = sanitize_host_id(host_id)
        cert_dir = os.path.join(CERTS_DIR, safe_id)

        # Defense in depth: verify path is within CERTS_DIR
        abs_cert_dir = os.path.abspath(cert_dir)
        abs_certs_dir = os.path.abspath(CERTS_DIR)
        if not abs_cert_dir.startswith(abs_certs_dir):
            logger.error(f"Path traversal attempt detected: {host_id}")
            raise ValueError("Invalid certificate path")

        if os.path.exists(cert_dir):
            try:
                shutil.rmtree(cert_dir)
                logger.info(f"Cleaned up certificate files for host {host_id[:8]}")
            except Exception as e:
                logger.warning(f"Failed to clean up certificates for host {host_id[:8]}: {e}")

    def cleanup_orphaned_certificates(self):
        """
        Clean up orphaned certificate directories on startup.
        Removes cert directories that don't match any existing host ID in the database.
        This handles the legacy bug where cert dirs and host IDs could differ.
        """
        try:
            if not os.path.exists(CERTS_DIR):
                return

            # Get all valid host IDs from database
            with self.db.get_session() as session:
                valid_host_ids = {host.id for host in session.query(DockerHostDB).all()}

            # List all cert directories
            cert_dirs = [d for d in os.listdir(CERTS_DIR)
                        if os.path.isdir(os.path.join(CERTS_DIR, d))]

            # Remove orphaned directories
            orphaned_count = 0
            for cert_dir_name in cert_dirs:
                if cert_dir_name not in valid_host_ids:
                    cert_path = os.path.join(CERTS_DIR, cert_dir_name)

                    # Defense in depth: verify path is within CERTS_DIR
                    abs_cert_path = os.path.abspath(cert_path)
                    abs_certs_dir = os.path.abspath(CERTS_DIR)
                    if not abs_cert_path.startswith(abs_certs_dir):
                        logger.error(f"Path traversal detected during cleanup: {cert_dir_name}")
                        continue

                    try:
                        shutil.rmtree(cert_path)
                        orphaned_count += 1
                        logger.info(f"Removed orphaned certificate directory: {cert_dir_name[:8]}...")
                    except Exception as e:
                        logger.warning(f"Failed to remove orphaned cert directory {cert_dir_name[:8]}: {e}")

            if orphaned_count > 0:
                logger.info(f"Cleaned up {orphaned_count} orphaned certificate director{'y' if orphaned_count == 1 else 'ies'}")

        except Exception as e:
            logger.error(f"Failed to cleanup orphaned certificates: {e}")

    async def remove_host(self, host_id: str):
        """Remove a Docker host"""
        # Validate host_id to prevent path traversal
        try:
            host_id = sanitize_host_id(host_id)
        except ValueError as e:
            logger.error(f"Invalid host ID: {e}")
            raise HTTPException(status_code=400, detail=str(e))

        if host_id in self.hosts:
            # Get host info before removing
            host = self.hosts[host_id]
            host_name = host.name

            del self.hosts[host_id]
            if host_id in self.clients:
                self.clients[host_id].close()
                del self.clients[host_id]

            # Remove from Go stats and event services (await to ensure cleanup completes before returning)
            try:
                stats_client = get_stats_client()

                try:
                    # Remove from stats service (closes Docker client and stops all container streams)
                    await stats_client.remove_docker_host(host_id)
                    logger.info(f"Removed {host_name} ({host_id[:8]}) from stats service")

                    # Remove from event service
                    await stats_client.remove_event_host(host_id)
                    logger.info(f"Removed {host_name} ({host_id[:8]}) from event service")
                except asyncio.TimeoutError:
                    # Timeout during cleanup is expected - Go service closes connections immediately
                    logger.debug(f"Timeout removing {host_name} from Go services (expected during cleanup)")
                except Exception as e:
                    logger.error(f"Failed to remove {host_name} from Go services: {e}")
            except Exception as e:
                logger.warning(f"Failed to remove host {host_name} ({host_id[:8]}) from Go services: {e}")

            # Clean up certificate files
            self._cleanup_host_certificates(host_id)
            # Remove from database
            self.db.delete_host(host_id)

            # Clean up container state tracking for this host
            async with self._state_lock:
                containers_to_remove = [key for key in self._container_states.keys() if key.startswith(f"{host_id}:")]
                for container_key in containers_to_remove:
                    del self._container_states[container_key]

            # Clean up recent user actions for this host
            async with self._actions_lock:
                actions_to_remove = [key for key in self._recent_user_actions.keys() if key.startswith(f"{host_id}:")]
                for container_key in actions_to_remove:
                    del self._recent_user_actions[container_key]

            # Clean up reconnection tracking for this host
            if host_id in self.reconnect_attempts:
                del self.reconnect_attempts[host_id]
            if host_id in self.last_reconnect_attempt:
                del self.last_reconnect_attempt[host_id]

            # Clean up auto-restart tracking for this host
            async with self._restart_lock:
                auto_restart_to_remove = [key for key in self.auto_restart_status.keys() if key.startswith(f"{host_id}:")]
                for container_key in auto_restart_to_remove:
                    del self.auto_restart_status[container_key]
                    if container_key in self.restart_attempts:
                        del self.restart_attempts[container_key]
                    if container_key in self.restarting_containers:
                        del self.restarting_containers[container_key]

            # Clean up stats manager's streaming containers for this host
            # Remove using the full composite key (format: "host_id:container_id")
            for container_key in containers_to_remove:
                self.stats_manager.streaming_containers.discard(container_key)

            # Clean up network stats tracking for this host (prevent memory leak)
            if host_id in self._last_net_stats:
                del self._last_net_stats[host_id]

            # Clean up stats history buffers for this host (prevent memory leak)
            self.stats_history.remove_host(host_id)
            # Clean up container stats history for each container on this host
            for container_key in containers_to_remove:
                self.container_stats_history.remove_container(container_key)

            if containers_to_remove:
                logger.debug(f"Cleaned up {len(containers_to_remove)} container state entries for removed host {host_id[:8]}")
            # V1 alert processor cleanup removed - v2 uses event-driven architecture
            if auto_restart_to_remove:
                logger.debug(f"Cleaned up {len(auto_restart_to_remove)} auto-restart entries for removed host {host_id[:8]}")

            # Log host removed
            self.event_logger.log_host_removed(
                host_name=host_name,
                host_id=host_id,
                triggered_by="user"
            )

            logger.info(f"Removed host {host_name} ({host_id[:8]})")

    def update_host(self, host_id: str, config: DockerHostConfig):
        """Update an existing Docker host"""
        # Validate host_id to prevent path traversal
        try:
            host_id = sanitize_host_id(host_id)
        except ValueError as e:
            logger.error(f"Invalid host ID: {e}")
            raise HTTPException(status_code=400, detail=str(e))

        client = None  # Track client for cleanup on error
        try:
            # Get existing host from database to check if we need to preserve certificates
            existing_host = self.db.get_host(host_id)
            if not existing_host:
                raise HTTPException(status_code=404, detail=f"Host {host_id} not found")

            # If certificates are not provided in the update, use existing ones
            # This allows updating just the name without providing certificates again
            if not config.tls_cert and existing_host.tls_cert:
                config.tls_cert = existing_host.tls_cert
            if not config.tls_key and existing_host.tls_key:
                config.tls_key = existing_host.tls_key
            if not config.tls_ca and existing_host.tls_ca:
                config.tls_ca = existing_host.tls_ca

            # If tags are not provided in the update (None or empty list), preserve existing ones
            # Tags are managed through a separate endpoint, so they shouldn't be cleared on update
            # Load from normalized tag_assignments table (tags column is legacy)
            if config.tags is None or len(config.tags) == 0:
                existing_tags = self.db.get_tags_for_subject('host', host_id)
                if existing_tags:
                    config.tags = existing_tags
                    logger.debug(f"Preserved {len(config.tags)} existing tags for host {config.name}")
                else:
                    logger.debug(f"No existing tags found for host {config.name}")

            # Only validate certificates if NEW ones are provided (not using existing)
            # Check if any NEW certificate data was actually sent in the request
            if (config.tls_cert and config.tls_cert != existing_host.tls_cert) or \
               (config.tls_key and config.tls_key != existing_host.tls_key) or \
               (config.tls_ca and config.tls_ca != existing_host.tls_ca):
                self._validate_certificates(config)

            # Remove the existing host from memory first
            if host_id in self.hosts:
                # Close existing client first (this should stop the monitoring task)
                if host_id in self.clients:
                    host_name = self.hosts[host_id].name
                    logger.info(f"Closing Docker client for host {host_name} ({host_id[:8]})")
                    self.clients[host_id].close()
                    del self.clients[host_id]

                # Remove from memory
                del self.hosts[host_id]

            # Validate TLS configuration
            security_status = self._validate_host_security(config)

            # Update database
            # Serialize tags as JSON for database storage
            tags_json = json.dumps(config.tags) if config.tags else None

            updated_db_host = self.db.update_host(host_id, {
                'name': config.name,
                'url': config.url,
                'tls_cert': config.tls_cert,
                'tls_key': config.tls_key,
                'tls_ca': config.tls_ca,
                'security_status': security_status,
                'tags': tags_json,
                'description': config.description
            })

            if not updated_db_host:
                raise Exception(f"Host {host_id} not found in database")

            # Create new Docker client with updated config
            if config.url.startswith("unix://"):
                client = docker.DockerClient(base_url=config.url)
            else:
                # For TCP connections
                tls_config = None
                if config.tls_cert and config.tls_key:
                    # Create persistent certificate storage directory
                    safe_id = sanitize_host_id(host_id)
                    cert_dir = os.path.join(CERTS_DIR, safe_id)
                    # Create with secure permissions to avoid TOCTOU race condition
                    os.makedirs(cert_dir, mode=0o700, exist_ok=True)

                    # Write certificate files
                    cert_file = os.path.join(cert_dir, 'client-cert.pem')
                    key_file = os.path.join(cert_dir, 'client-key.pem')
                    ca_file = os.path.join(cert_dir, 'ca.pem') if config.tls_ca else None

                    with open(cert_file, 'w') as f:
                        f.write(config.tls_cert)
                    with open(key_file, 'w') as f:
                        f.write(config.tls_key)
                    if ca_file and config.tls_ca:
                        with open(ca_file, 'w') as f:
                            f.write(config.tls_ca)

                    # Set secure permissions
                    os.chmod(cert_file, 0o600)
                    os.chmod(key_file, 0o600)
                    if ca_file:
                        os.chmod(ca_file, 0o600)

                    tls_config = docker.tls.TLSConfig(
                        client_cert=(cert_file, key_file),
                        ca_cert=ca_file,
                        verify=bool(config.tls_ca)
                    )

                client = docker.DockerClient(
                    base_url=config.url,
                    tls=tls_config,
                    timeout=self.settings.connection_timeout
                )

            # Test connection
            client.ping()

            # Fetch fresh system information immediately after connecting
            sys_info = _fetch_system_info_from_docker(client, config.name)
            os_type = sys_info['os_type']
            os_version = sys_info['os_version']
            kernel_version = sys_info['kernel_version']
            docker_version = sys_info['docker_version']
            daemon_started_at = sys_info['daemon_started_at']
            total_memory = sys_info['total_memory']
            num_cpus = sys_info['num_cpus']
            is_podman = sys_info.get('is_podman', False)

            # Create host object with existing ID and fresh system info
            host = DockerHost(
                id=host_id,
                name=config.name,
                url=config.url,
                status="online",
                security_status=security_status,
                tags=config.tags,
                description=config.description,
                os_type=os_type,
                os_version=os_version,
                kernel_version=kernel_version,
                docker_version=docker_version,
                daemon_started_at=daemon_started_at,
                total_memory=total_memory,
                num_cpus=num_cpus,
                is_podman=is_podman
            )

            # Store client and host
            self.clients[host.id] = client
            self.hosts[host.id] = host

            # Update database with fresh system info
            try:
                with self.db.get_session() as session:
                    db_host = session.query(DockerHostDB).filter(DockerHostDB.id == host_id).first()
                    if db_host:
                        db_host.os_type = os_type
                        db_host.os_version = os_version
                        db_host.kernel_version = kernel_version
                        db_host.docker_version = docker_version
                        db_host.daemon_started_at = daemon_started_at
                        db_host.total_memory = total_memory
                        db_host.num_cpus = num_cpus
                        db_host.is_podman = is_podman
                        session.commit()
            except Exception as e:
                logger.warning(f"Failed to update system info for {host.name}: {e}")
            else:
                platform_type = "Podman" if is_podman else "Docker"
                logger.info(f"Updated system info for {host.name}: {os_version} / {platform_type} {docker_version}")

            # Re-register host with stats and event services (in case URL changed)
            # Note: add_docker_host() automatically closes old client if it exists
            try:
                import asyncio
                stats_client = get_stats_client()

                async def reregister_host():
                    try:
                        # Re-register with stats service (automatically closes old client)
                        await stats_client.add_docker_host(host.id, host.name, host.url, config.tls_ca, config.tls_cert, config.tls_key)
                        logger.info(f"Re-registered {host.name} ({host.id[:8]}) with stats service")

                        # Remove and re-add event monitoring
                        await stats_client.remove_event_host(host.id)
                        await stats_client.add_event_host(host.id, host.name, host.url, config.tls_ca, config.tls_cert, config.tls_key)
                        logger.info(f"Re-registered {host.name} ({host.id[:8]}) with event service")
                    except Exception as e:
                        logger.error(f"Failed to re-register {host.name} with Go services: {e}")

                # Create task to re-register (fire and forget)
                task = asyncio.create_task(reregister_host())
                task.add_done_callback(_handle_task_exception)
            except Exception as e:
                logger.warning(f"Could not re-register {host.name} with Go services: {e}")

            # Log host update
            self.event_logger.log_host_connection(
                host_name=host.name,
                host_id=host.id,
                host_url=config.url,
                connected=True
            )

            logger.info(f"Successfully updated host {host_id}: {host.name} ({host.url})")
            return host

        except Exception as e:
            # Clean up client if it was created but not stored
            if client and host_id not in self.clients:
                try:
                    client.close()
                    logger.debug(f"Closed orphaned Docker client for host {host_id[:8]}")
                except Exception as close_error:
                    logger.debug(f"Error closing Docker client: {close_error}")

            logger.error(f"Failed to update host {host_id}: {e}")
            error_msg = self._get_user_friendly_error(str(e))
            raise HTTPException(status_code=400, detail=error_msg)

    async def get_containers(self, host_id: Optional[str] = None) -> List[Container]:
        """Get containers from one or all hosts"""
        containers = []
        hosts_to_check = [host_id] if host_id else list(self.hosts.keys())

        for hid in hosts_to_check:
            host = self.hosts.get(hid)
            if not host:
                continue

            # Try to reconnect if host is offline or has no client
            # This ensures backoff logic is used for both cases
            if hid not in self.clients or host.status == "offline":
                reconnected = await self.discovery.attempt_reconnection(hid)
                if not reconnected:
                    continue

            # Discover containers for this host
            host_containers = await self.discovery.discover_containers_for_host(hid, self._get_auto_restart_status)

            # Populate restart_attempts from monitor's state using composite key to prevent collisions
            for container in host_containers:
                container_key = make_composite_key(container.host_id, container.short_id)
                container.restart_attempts = self.restart_attempts.get(container_key, 0)

            containers.extend(host_containers)

        # Populate stats for all containers
        await self.discovery.populate_container_stats(containers)

        return containers

    def get_last_containers(self) -> List:
        """
        Get cached container list from last monitor cycle.
        Data is max 2 seconds old (refreshed by monitor loop).
        Used by alert evaluation to avoid redundant Docker API queries.
        """
        return self._last_containers

    async def restart_container(self, host_id: str, container_id: str) -> bool:
        """Restart a specific container"""
        return await self.operations.restart_container(host_id, container_id)

    async def stop_container(self, host_id: str, container_id: str) -> bool:
        """Stop a specific container"""
        return await self.operations.stop_container(host_id, container_id)

    async def start_container(self, host_id: str, container_id: str) -> bool:
        """Start a specific container"""
        return await self.operations.start_container(host_id, container_id)

    async def delete_container(self, host_id: str, container_id: str, container_name: str, remove_volumes: bool = False) -> dict:
        """Delete a specific container"""
        return await self.operations.delete_container(host_id, container_id, container_name, remove_volumes)

    def toggle_auto_restart(self, host_id: str, container_id: str, container_name: str, enabled: bool):
        """Toggle auto-restart for a container"""
        return self.state_manager.toggle_auto_restart(host_id, container_id, container_name, enabled)

    def set_container_desired_state(self, host_id: str, container_id: str, container_name: str, desired_state: str, web_ui_url: str = None):
        """Set desired state for a container"""
        return self.state_manager.set_container_desired_state(host_id, container_id, container_name, desired_state, web_ui_url)

    # Alias methods for batch operations (consistent naming)
    def update_container_auto_restart(self, host_id: str, container_id: str, container_name: str, enabled: bool):
        """Alias for toggle_auto_restart - used by batch operations"""
        return self.toggle_auto_restart(host_id, container_id, container_name, enabled)

    def update_container_auto_update(self, host_id: str, container_id: str, container_name: str, enabled: bool, floating_tag_mode: str = 'exact'):
        """Enable/disable auto-update for a container with specified tracking mode"""
        container_key = make_composite_key(host_id, container_id)
        return self.db.set_container_auto_update(container_key, enabled, floating_tag_mode)

    def update_container_desired_state(self, host_id: str, container_id: str, container_name: str, desired_state: str, web_ui_url: str = None):
        """Alias for set_container_desired_state - used by batch operations"""
        return self.set_container_desired_state(host_id, container_id, container_name, desired_state, web_ui_url)

    async def update_container_tags(
        self,
        host_id: str,
        container_id: str,
        container_name: str,
        tags_to_add: list[str] = None,
        tags_to_remove: list[str] = None,
        ordered_tags: list[str] = None
    ) -> dict:
        """
        Update container custom tags in database

        Supports two modes:
        1. Delta mode: tags_to_add/tags_to_remove (backwards compatible)
        2. Ordered mode: ordered_tags (for reordering, v2.1.8-hotfix.1+)
        """
        return await self.state_manager.update_container_tags(
            host_id, container_id, container_name,
            tags_to_add=tags_to_add,
            tags_to_remove=tags_to_remove,
            ordered_tags=ordered_tags
        )


    async def _handle_docker_event(self, event: dict):
        """Handle Docker events from Go service"""
        try:
            action = event.get('action', '')
            container_id = event.get('container_id', '')
            container_name = event.get('container_name', '')
            host_id = event.get('host_id', '')
            attributes = event.get('attributes', {})
            timestamp_str = event.get('timestamp', '')

            # Filter out noisy exec_* events (health checks, etc.)
            if action.startswith('exec_'):
                return

            # Get host name for logging
            host_name = self.hosts.get(host_id).name if host_id in self.hosts else host_id[:8]

            # Only log important events
            important_events = ['create', 'start', 'stop', 'die', 'kill', 'destroy', 'pause', 'unpause', 'restart', 'oom', 'health_status']
            if action in important_events:
                logger.debug(f"Docker event: {action} - {container_name} ({container_id[:12]}) on {host_name} ({host_id[:8]})")

            # Process event using EventBus
            # Only process final/definitive events to avoid duplicate evaluations:
            # - die (not kill/stop) for container stopped
            # - start for container started
            # - restart for container restarted (emitted after restart completes)
            # - oom, health_status for their respective conditions
            logger.debug(f"V2 alert check: alert_evaluation_service={self.alert_evaluation_service is not None}, action={action}")
            if self.alert_evaluation_service and action in ['die', 'oom', 'health_status', 'start', 'restart']:
                logger.debug(f"V2: Processing {action} event for {container_name} ({container_id[:12]}) on {host_name} ({host_id[:8]})")

                # Parse timestamp
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError, TypeError) as e:
                    logger.warning(f"Failed to parse timestamp '{timestamp_str}': {e}, using current time")
                    timestamp = datetime.now(timezone.utc)

                # Map Docker events to EventBus event types
                bus_event_type = None
                new_state = None
                exit_code = None

                if action == 'die':
                    # Docker sends exitCode in attributes
                    exit_code_str = attributes.get('exitCode')
                    if exit_code_str is not None:
                        try:
                            exit_code = int(exit_code_str)
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid exit code format: {exit_code_str}")
                            exit_code = None
                    else:
                        exit_code = 0  # Default to 0 if not provided

                    # Issue #23: Distinguish clean stops (exit 0) from crashes (exit != 0)
                    if exit_code == 0:
                        bus_event_type = BusEventType.CONTAINER_STOPPED
                        new_state = "stopped"
                    else:
                        bus_event_type = BusEventType.CONTAINER_DIED
                        new_state = "exited"
                elif action == 'start':
                    bus_event_type = BusEventType.CONTAINER_STARTED
                    new_state = "running"
                elif action == 'restart':
                    # Docker 'restart' event is emitted AFTER the container has been restarted
                    # Log as distinct CONTAINER_RESTARTED event (not just CONTAINER_STARTED)
                    bus_event_type = BusEventType.CONTAINER_RESTARTED
                    new_state = "running"
                elif action == 'health_status':
                    # Health status change
                    health_status = attributes.get('health_status', attributes.get('health', 'unhealthy'))
                    bus_event_type = BusEventType.CONTAINER_HEALTH_CHANGED
                    new_state = health_status
                elif action == 'oom':
                    bus_event_type = BusEventType.CONTAINER_DIED
                    new_state = "oom"

                # Get old state from container state tracking (with lock to prevent race with polling loop)
                container_key = make_composite_key(host_id, container_id)
                async with self._state_lock:
                    old_state = self._container_states.get(container_key)
                    # Update state tracking immediately so polling loop doesn't think there's drift
                    if new_state:
                        # Update state with timestamp and source tracking (Issue #3 fix)
                        self._container_states[container_key] = new_state
                        self._container_state_timestamps[container_key] = datetime.now(timezone.utc)
                        self._container_state_sources[container_key] = 'event'

                # Get host name
                host_name = self.hosts.get(host_id).name if host_id in self.hosts else host_id

                # Emit event via EventBus (in background to not block event monitoring)
                if bus_event_type:
                    task = asyncio.create_task(
                        get_event_bus(self).emit(Event(
                            event_type=bus_event_type,
                            scope_type='container',
                            scope_id=make_composite_key(host_id, container_id),
                            scope_name=container_name,
                            host_id=host_id,
                            host_name=host_name,
                            timestamp=timestamp,
                            data={
                                'new_state': new_state,
                                'old_state': old_state,
                                'exit_code': exit_code,
                                'image': attributes.get('image', ''),
                                'attributes': attributes
                            }
                        ))
                    )
                    task.add_done_callback(_handle_task_exception)

            # Event-driven auto-restart: Check if container needs auto-restart on 'die' events
            if action == 'die':
                # Skip backup containers (created during updates with -backup- suffix)
                if '-backup-' in container_name:
                    logger.debug(f"Skipping auto-restart for {container_name} - backup container")
                    return

                # Check if container is being updated - skip auto-restart to avoid conflicts
                is_updating = False
                try:
                    from updates.update_executor import get_update_executor
                    update_executor = get_update_executor()
                    is_updating = update_executor.is_container_updating(host_id, container_id)
                    if is_updating:
                        logger.info(f"Skipping auto-restart for {container_name} - container is being updated")
                except Exception as e:
                    logger.warning(f"Could not check update status: {e}")

                # Skip auto-restart if container is being updated
                if is_updating:
                    return

                # Get container from cache to check auto-restart status
                auto_restart_enabled = self._get_auto_restart_status(host_id, container_id)

                if auto_restart_enabled:
                    # Find container in cache
                    # Note: Events use short_id (12 chars), containers have both id (64 chars) and short_id
                    container = None
                    for c in self._last_containers:
                        # Match against both full ID and short ID
                        if (c.id == container_id or c.short_id == container_id) and c.host_id == host_id:
                            container = c
                            break

                    if container:
                        # 'die' event means container just died - don't wait for cache to update
                        # Restart immediately for instant response
                        container_key = make_composite_key(host_id, container_id)

                        # Atomically check and set the restarting flag to prevent duplicate restarts (with lock)
                        async with self._state_lock:
                            is_restarting = self.restarting_containers.get(container_key, False)
                            if not is_restarting:
                                attempts = self.restart_attempts.get(container_key, 0)
                                if attempts < self.settings.max_retries:
                                    # Set restarting flag BEFORE spawning task to prevent race condition
                                    self.restarting_containers[container_key] = True
                                    should_restart = True
                                else:
                                    should_restart = False
                            else:
                                should_restart = False

                        # Spawn restart task outside lock (IO operations shouldn't hold locks)
                        if should_restart:
                            logger.info(f"Auto-restart triggered by 'die' event for {container_name} (attempt {attempts + 1}/{self.settings.max_retries})")
                            task = asyncio.create_task(
                                self.auto_restart_container(container)
                            )
                            task.add_done_callback(_handle_task_exception)
                    else:
                        logger.warning(f"Container {container_name} not found in cache for event-driven auto-restart")

        except Exception as e:
            logger.error(f"Error handling Docker event from Go service: {e}")

    async def monitor_containers(self):
        """Main monitoring loop"""
        logger.info("Starting container monitoring...")

        # Get stats client instance
        # Note: streaming_containers is now managed by self.stats_manager
        stats_client = get_stats_client()

        # Register all hosts with the stats and event services on startup
        for host_id, host in self.hosts.items():
            try:
                # Get TLS certificates from database
                with self.db.get_session() as session:
                    db_host = session.query(DockerHostDB).filter_by(id=host_id).first()
                    tls_ca = db_host.tls_ca if db_host else None
                    tls_cert = db_host.tls_cert if db_host else None
                    tls_key = db_host.tls_key if db_host else None

                # Register with stats service
                await stats_client.add_docker_host(host_id, host.name, host.url, tls_ca, tls_cert, tls_key)
                logger.info(f"Registered host {host.name} ({host_id[:8]}) with stats service")

                # Register with event service
                await stats_client.add_event_host(host_id, host.name, host.url, tls_ca, tls_cert, tls_key)
                logger.info(f"Registered host {host.name} ({host_id[:8]}) with event service")
            except Exception as e:
                logger.error(f"Failed to register host {host_id} with services: {e}")

        # Connect to event stream WebSocket
        try:
            await stats_client.connect_event_stream(self._handle_docker_event)
            logger.info("Connected to Go event stream")
        except Exception as e:
            logger.error(f"Failed to connect to event stream: {e}")

        while True:
            try:
                containers = await self.get_containers()

                # Cache containers for alert evaluation (avoid redundant Docker API queries)
                self._last_containers = containers

                # Check if we have active viewers (for adaptive polling interval)
                has_viewers = self.manager.has_active_connections()
                logger.debug(f"Monitor loop: has_viewers={has_viewers}, active_connections={len(self.manager.active_connections)}")

                # Periodic stats stream reconciliation (safety net for cleanup)
                # This ensures stale streams (e.g., from recreated containers with new IDs) are stopped
                # and new containers get streams started even if no WebSocket reconnect happens
                if has_viewers and containers:
                    try:
                        containers_needing_stats = self.stats_manager.determine_containers_needing_stats(
                            containers,
                            self.settings
                        )
                        await self.stats_manager.sync_container_streams(
                            containers,
                            containers_needing_stats,
                            stats_client,
                            _handle_task_exception
                        )
                        logger.debug(f"Periodic stream sync: {len(self.stats_manager.streaming_containers)} active streams")
                    except Exception as e:
                        logger.error(f"Error syncing container streams: {e}")

                # Stats streams are now managed by WebSocket connect/disconnect events (event-driven)
                # This provides instant start/stop instead of waiting for next poll cycle
                # Periodic sync above acts as a safety net for cleanup

                # Reconcile container states (silent sync - events handle logging)
                # This acts as a safety net to catch any states that events might have missed
                for container in containers:
                    # Use short_id to match event handler's key format
                    container_key = make_composite_key(container.host_id, container.short_id)
                    current_state = container.status

                    # Hold lock during entire read-process-write to prevent race conditions
                    async with self._state_lock:
                        previous_state = self._container_states.get(container_key)

                        # Check if update is stale (Issue #3 fix)
                        if container_key in self._container_state_timestamps:
                            last_update = self._container_state_timestamps[container_key]
                            last_source = self._container_state_sources.get(container_key)
                            time_since_update = (datetime.now(timezone.utc) - last_update).total_seconds()

                            # Reject stale polling update if recent event exists
                            if time_since_update < STATE_UPDATE_STALE_THRESHOLD and last_source == 'event':
                                logger.debug(
                                    f"Rejecting stale polling update for {container.name}: "
                                    f"state={current_state}, last_event={previous_state} "
                                    f"({time_since_update:.1f}s ago). Event-driven state is authoritative."
                                )
                                continue  # Skip this container's state update

                        # Detect state drift (state changed but we didn't get an event)
                        # Normalize states for comparison: "stopped" and "exited" are equivalent
                        def normalize_state(state):
                            return "exited" if state in ["stopped", "exited"] else state

                        normalized_previous = normalize_state(previous_state) if previous_state else None
                        normalized_current = normalize_state(current_state)

                        if normalized_previous is not None and normalized_previous != normalized_current:
                            # This should be rare - events should have caught this
                            logger.warning(
                                f"State drift detected for {container.name}: {previous_state} → {current_state}. "
                                f"Event may have been missed. Reconciling internal state."
                            )
                            # Don't log to event_logger - events already handle state change logging
                            # This is just to keep our internal state tracking in sync

                        # Always update tracked state to stay in sync with Docker reality
                        self._container_states[container_key] = current_state
                        self._container_state_timestamps[container_key] = datetime.now(timezone.utc)
                        self._container_state_sources[container_key] = 'poll'

                # Auto-restart reconciliation (safety net - events handle primary auto-restart)
                # This catches containers that need restart if 'die' event was missed
                for container in containers:
                    # Skip backup containers (created during updates with -backup- suffix)
                    if '-backup-' in container.name:
                        continue

                    if (container.status == "exited" and
                        self._get_auto_restart_status(container.host_id, container.short_id)):

                        # Use host_id:container_id as key to prevent collisions between hosts
                        container_key = make_composite_key(container.host_id, container.short_id)

                        # Atomically check and set restart flag (with lock)
                        async with self._state_lock:
                            attempts = self.restart_attempts.get(container_key, 0)
                            is_restarting = self.restarting_containers.get(container_key, False)

                            if attempts < self.settings.max_retries and not is_restarting:
                                self.restarting_containers[container_key] = True
                                should_restart = True
                            else:
                                should_restart = False

                        # Spawn restart task outside lock
                        if should_restart:
                            # This should be rare - events should trigger auto-restart immediately
                            logger.info(f"Auto-restart reconciliation triggered for {container.name} (polling safety net)")
                            task = asyncio.create_task(
                                self.auto_restart_container(container)
                            )
                            task.add_done_callback(_handle_task_exception)

                # V1 alert processor removed - v2 uses event-driven alerts via handle_container_event()
                # Container state changes are detected via Docker events in _handle_go_event()

                # Only fetch and broadcast stats if there are active viewers
                if has_viewers:
                    # Prepare broadcast data
                    broadcast_data = {
                        "containers": [c.dict() for c in containers],
                        "hosts": [h.dict() for h in self.hosts.values()],
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }

                    # Only include host metrics if host stats are enabled
                    should_broadcast = self.stats_manager.should_broadcast_host_metrics(self.settings)
                    if should_broadcast:
                        # Aggregate host metrics from container stats (Phase 4c)
                        host_metrics = {}
                        host_sparklines = {}

                        # Group containers by host and aggregate stats
                        for host_id in self.hosts.keys():
                            host_containers = [c for c in containers if c.host_id == host_id]
                            running_containers = [c for c in host_containers if c.status == 'running']
                            host = self.hosts[host_id]

                            if running_containers:
                                # Aggregate CPU: Σ(container_cpu_percent) / num_cpus - per spec line 99
                                total_cpu_sum = sum(c.cpu_percent or 0 for c in running_containers)
                                # Use actual num_cpus from Docker info, fallback to 4 if not available
                                num_cpus = host.num_cpus or 4
                                total_cpu = total_cpu_sum / num_cpus

                                # Aggregate Memory: Σ(container_mem_usage) / host_mem_total * 100 - per spec line 138
                                total_mem_bytes = sum(c.memory_usage or 0 for c in running_containers)
                                # Use actual host total memory from Docker info, fallback to 16GB if not available
                                total_mem_limit = host.total_memory or (16 * 1024 * 1024 * 1024)
                                mem_percent = (total_mem_bytes / total_mem_limit * 100) if total_mem_limit > 0 else 0

                                # Aggregate Network: Σ(container_rx_rate + container_tx_rate) - per spec line 122-123
                                # Calculate rate by tracking delta from previous measurement
                                total_net_rx = sum(c.network_rx or 0 for c in running_containers)
                                total_net_tx = sum(c.network_tx or 0 for c in running_containers)
                                total_net_bytes = total_net_rx + total_net_tx

                                # Calculate bytes per second from delta
                                if host_id in self._last_net_stats:
                                    net_delta = total_net_bytes - self._last_net_stats[host_id]

                                    # Handle counter reset (container restart) - Fix #4
                                    if net_delta < 0:
                                        logger.debug(f"Network counter reset detected for host {host_id[:8]}")
                                        # Reset baseline, no rate this cycle
                                        net_bytes_per_sec = 0
                                    else:
                                        # Normal case: Delta / polling_interval = bytes per second
                                        net_bytes_per_sec = net_delta / self.settings.polling_interval

                                        # Sanity check: Cap at 100 Gbps (reasonable max for aggregated hosts)
                                        max_rate = 100 * 1024 * 1024 * 1024  # 100 GB/s
                                        if net_bytes_per_sec > max_rate:
                                            logger.warning(f"Network rate outlier detected for host {host_id[:8]}: {net_bytes_per_sec / (1024**3):.2f} GB/s, capping")
                                            net_bytes_per_sec = 0  # Drop outlier
                                else:
                                    # First measurement - prime baseline, no rate yet (Fix #1)
                                    net_bytes_per_sec = 0

                                # Store for next calculation
                                self._last_net_stats[host_id] = total_net_bytes

                                host_metrics[host_id] = {
                                    "cpu_percent": total_cpu,
                                    "mem_percent": mem_percent,
                                    "mem_bytes": total_mem_bytes,
                                    "net_bytes_per_sec": net_bytes_per_sec
                                }

                                # Feed stats history buffer for sparklines
                                self.stats_history.add_stats(
                                    host_id=host_id,
                                    cpu=total_cpu,
                                    mem=mem_percent,
                                    net=net_bytes_per_sec
                                )

                                # Get sparklines for this host (last 30 points)
                                host_sparklines[host_id] = self.stats_history.get_sparklines(host_id, num_points=30)

                        broadcast_data["host_metrics"] = host_metrics
                        broadcast_data["host_sparklines"] = host_sparklines
                        logger.debug(f"Aggregated metrics for {len(host_metrics)} hosts from {len(containers)} containers")

                    # Collect container sparklines for all containers
                    container_sparklines = {}
                    for container in containers:
                        # Use composite key with SHORT ID: host_id:container_id (12 chars)
                        container_key = make_composite_key(container.host_id, container.short_id)

                        # Collect sparklines for ALL containers (running or not)
                        # This ensures we always send sparkline data in every broadcast
                        if container.state == 'running':
                            # Feed stats to history buffer (use 0 for missing values)
                            cpu_val = container.cpu_percent if container.cpu_percent is not None else 0
                            mem_val = container.memory_percent if container.memory_percent is not None else 0
                            net_val = container.net_bytes_per_sec if container.net_bytes_per_sec is not None else 0

                            self.container_stats_history.add_stats(
                                container_key=container_key,
                                cpu=cpu_val,
                                mem=mem_val,
                                net=net_val
                            )

                        # Always get sparklines (even for stopped containers) to maintain consistency
                        sparklines = self.container_stats_history.get_sparklines(container_key, num_points=30)
                        container_sparklines[container_key] = sparklines

                    broadcast_data["container_sparklines"] = container_sparklines

                    # Broadcast update to all connected clients
                    await self.manager.broadcast({
                        "type": "containers_update",
                        "data": broadcast_data
                    })

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")

            # Adaptive polling: respect user's polling_interval when viewers present, 10s when idle for efficiency
            interval = self.settings.polling_interval if has_viewers else 10
            await asyncio.sleep(interval)

    async def auto_restart_container(self, container: Container):
        """Attempt to auto-restart a container"""
        container_id = container.short_id
        # Use host_id:container_id as key to prevent collisions between hosts
        container_key = make_composite_key(container.host_id, container_id)

        self.restart_attempts[container_key] = self.restart_attempts.get(container_key, 0) + 1
        attempt = self.restart_attempts[container_key]

        correlation_id = self.event_logger.create_correlation_id()

        logger.info(
            f"Auto-restart attempt {attempt}/{self.settings.max_retries} "
            f"for container '{container.name}' on host '{container.host_name}'"
        )

        # Wait before attempting restart (skip delay for first attempt for instant response)
        if attempt > 1:
            await asyncio.sleep(self.settings.retry_delay)

        try:
            # Use start instead of restart since we know the container is stopped (from 'die' event)
            # This avoids unnecessary kill/die events that restart would generate
            # Docker API accepts short IDs
            success = await self.start_container(container.host_id, container.short_id)
            if success:
                self.restart_attempts[container_key] = 0

                # Log successful auto-restart
                self.event_logger.log_auto_restart_attempt(
                    container_name=container.name,
                    container_id=container_id,
                    host_name=container.host_name,
                    host_id=container.host_id,
                    attempt=attempt,
                    max_attempts=self.settings.max_retries,
                    success=True,
                    correlation_id=correlation_id
                )

                await self.manager.broadcast({
                    "type": "auto_restart_success",
                    "data": {
                        "container_id": container_id,
                        "container_name": container.name,
                        "host": container.host_name
                    }
                })
        except Exception as e:
            logger.error(f"Auto-restart failed for {container.name}: {e}")

            # Log failed auto-restart
            self.event_logger.log_auto_restart_attempt(
                container_name=container.name,
                container_id=container_id,
                host_name=container.host_name,
                host_id=container.host_id,
                attempt=attempt,
                max_attempts=self.settings.max_retries,
                success=False,
                error_message=str(e),
                correlation_id=correlation_id
            )

            if attempt >= self.settings.max_retries:
                self.auto_restart_status[container_key] = False
                await self.manager.broadcast({
                    "type": "auto_restart_failed",
                    "data": {
                        "container_id": container_id,
                        "container_name": container.name,
                        "attempts": attempt,
                        "max_retries": self.settings.max_retries
                    }
                })
        finally:
            # Always clear the restarting flag when done (success or failure)
            self.restarting_containers[container_key] = False

    def _load_persistent_config(self):
        """Load saved configuration from database"""
        try:
            # Load saved hosts
            db_hosts = self.db.get_hosts(active_only=True)

            # Detect and warn about duplicate hosts (same URL)
            seen_urls = {}
            for host in db_hosts:
                if host.url in seen_urls:
                    logger.warning(
                        f"Duplicate host detected: '{host.name}' ({host.id}) and "
                        f"'{seen_urls[host.url]['name']}' ({seen_urls[host.url]['id']}) "
                        f"both use URL '{host.url}'. Consider removing duplicates."
                    )
                else:
                    seen_urls[host.url] = {'name': host.name, 'id': host.id}

            # Check if this is first run
            with self.db.get_session() as session:
                settings = session.query(GlobalSettings).first()
                if not settings:
                    # Create default settings
                    settings = GlobalSettings()
                    session.add(settings)
                    session.commit()

            # Auto-add local Docker/Podman only on first run (outside session context)
            with self.db.get_session() as session:
                settings = session.query(GlobalSettings).first()

                # Detect socket path (Docker, rootful Podman, or rootless Podman)
                socket_path = None
                socket_name = None

                if os.path.exists('/var/run/docker.sock'):
                    socket_path = '/var/run/docker.sock'
                    socket_name = 'Docker'
                elif os.path.exists('/var/run/podman/podman.sock'):
                    socket_path = '/var/run/podman/podman.sock'
                    socket_name = 'Podman'
                elif 'XDG_RUNTIME_DIR' in os.environ:
                    runtime_dir = os.environ['XDG_RUNTIME_DIR']
                    rootless_sock = f"{runtime_dir}/podman/podman.sock"
                    if os.path.exists(rootless_sock):
                        socket_path = rootless_sock
                        socket_name = 'Podman (Rootless)'

                if settings and not settings.first_run_complete and not db_hosts and socket_path:
                    logger.info(f"First run detected - adding local {socket_name} automatically")
                    host_added = False
                    try:
                        # Detect platform (Docker vs Podman) via API
                        temp_client = None
                        try:
                            temp_client = docker.DockerClient(base_url=f"unix://{socket_path}")
                            version_info = temp_client.version()
                            platform_name = version_info.get('Platform', {}).get('Name', '')

                            # Detect Podman from API response
                            if 'podman' in platform_name.lower():
                                # Check if rootless (socket must be within XDG_RUNTIME_DIR)
                                if 'XDG_RUNTIME_DIR' in os.environ and socket_path.startswith(os.environ['XDG_RUNTIME_DIR']):
                                    detected_name = "Local Podman (Rootless)"
                                else:
                                    detected_name = "Local Podman"
                            else:
                                detected_name = "Local Docker"
                        except Exception as detect_err:
                            # Fallback to socket-based detection
                            logger.debug(f"Could not detect platform via API: {detect_err}")
                            detected_name = f"Local {socket_name}"
                        finally:
                            # Always close client to prevent resource leak
                            if temp_client:
                                try:
                                    temp_client.close()
                                except Exception:
                                    pass  # Ignore cleanup errors

                        config = DockerHostConfig(
                            name=detected_name,
                            url=f"unix://{socket_path}",
                            tls_cert=None,
                            tls_key=None,
                            tls_ca=None
                        )
                        self.add_host(config, suppress_event_loop_errors=True)
                        host_added = True
                        logger.info(f"Successfully added {detected_name} host")
                    except Exception as e:
                        # Check if this is the benign "no running event loop" error during startup
                        # The host is actually added successfully despite this error
                        error_str = str(e)
                        if "no running event loop" in error_str:
                            host_added = True
                            logger.debug(f"Event loop warning during first run (host added successfully): {e}")
                        else:
                            logger.error(f"Failed to add local Docker: {e}")
                            session.rollback()

                    # Mark first run as complete if host was added
                    if host_added:
                        settings.first_run_complete = True
                        session.commit()
                        logger.info("First run setup complete")

            for db_host in db_hosts:
                try:
                    # Load tags from normalized schema
                    tags = self.db.get_tags_for_subject('host', db_host.id)

                    config = DockerHostConfig(
                        name=db_host.name,
                        url=db_host.url,
                        tls_cert=db_host.tls_cert,
                        tls_key=db_host.tls_key,
                        tls_ca=db_host.tls_ca,
                        tags=tags,
                        description=db_host.description
                    )
                    # Try to connect to the host with existing ID and preserve security status
                    host = self.add_host(config, existing_id=db_host.id, skip_db_save=True, suppress_event_loop_errors=True)
                    # Override with stored security status
                    if hasattr(host, 'security_status') and db_host.security_status:
                        host.security_status = db_host.security_status
                except Exception as e:
                    # Suppress event loop errors during startup
                    error_str = str(e)
                    if "no running event loop" not in error_str:
                        logger.error(f"Failed to reconnect to saved host {db_host.name}: {e}")
                    # Add host to UI even if connection failed, mark as offline
                    # This prevents "disappearing hosts" bug after restart
                    # Load tags from normalized schema for offline host
                    tags = self.db.get_tags_for_subject('host', db_host.id)

                    host = DockerHost(
                        id=db_host.id,
                        name=db_host.name,
                        url=db_host.url,
                        status="offline",
                        client=None,
                        tags=tags,
                        description=db_host.description
                    )
                    host.security_status = db_host.security_status or "unknown"
                    self.hosts[db_host.id] = host
                    logger.info(f"Added host {db_host.name} in offline mode - connection will retry")

            # Load auto-restart configurations
            for host_id in self.hosts:
                with self.db.get_session() as session:
                    configs = session.query(AutoRestartConfig).filter(
                        AutoRestartConfig.host_id == host_id,
                        AutoRestartConfig.enabled == True
                    ).all()
                    for config in configs:
                        # Use host_id:container_id as key to prevent collisions between hosts
                        container_key = make_composite_key(config.host_id, config.container_id)
                        self.auto_restart_status[container_key] = True
                        self.restart_attempts[container_key] = config.restart_count

            logger.info(f"Loaded {len(self.hosts)} hosts from database")
        except Exception as e:
            logger.error(f"Error loading persistent config: {e}")

    def _get_auto_restart_status(self, host_id: str, container_id: str) -> bool:
        """Get auto-restart status for a container"""
        return self.state_manager.get_auto_restart_status(host_id, container_id)

    async def run_daily_maintenance(self):
        """Run daily maintenance tasks"""
        await self.periodic_jobs.daily_maintenance()

    async def cleanup_stale_container_state(self):
        """
        Clean up state dictionaries for containers that no longer exist.
        Called periodically to prevent unbounded memory growth.
        """
        try:
            # Get current containers
            containers = await self.get_containers()
            current_container_keys = {
                make_composite_key(c.host_id, c.short_id) for c in containers
            }

            # Clean up _container_states and timestamps/sources (Issue #3 fix)
            async with self._state_lock:
                stale_keys = [k for k in self._container_states.keys() if k not in current_container_keys]
                for key in stale_keys:
                    del self._container_states[key]
                    # Also clean up timestamps and sources (Issue #3 fix)
                    if key in self._container_state_timestamps:
                        del self._container_state_timestamps[key]
                    if key in self._container_state_sources:
                        del self._container_state_sources[key]
                if stale_keys:
                    logger.info(f"Cleaned up {len(stale_keys)} stale entries from _container_states")

            # Clean up auto-restart tracking
            async with self._restart_lock:
                stale_restart_keys = [k for k in self.auto_restart_status.keys() if k not in current_container_keys]
                for key in stale_restart_keys:
                    del self.auto_restart_status[key]
                    if key in self.restart_attempts:
                        del self.restart_attempts[key]
                    if key in self.restarting_containers:
                        del self.restarting_containers[key]
                if stale_restart_keys:
                    logger.info(f"Cleaned up {len(stale_restart_keys)} stale entries from auto-restart tracking")

            # Clean up recent user actions (keep only last 24 hours)
            async with self._actions_lock:
                current_time = time.time()
                cutoff_time = current_time - (24 * 60 * 60)  # 24 hours ago
                stale_action_keys = [
                    k for k, timestamp in self._recent_user_actions.items()
                    if timestamp < cutoff_time or k not in current_container_keys
                ]
                for key in stale_action_keys:
                    del self._recent_user_actions[key]
                if stale_action_keys:
                    logger.info(f"Cleaned up {len(stale_action_keys)} stale entries from _recent_user_actions")

        except Exception as e:
            logger.error(f"Error during container state cleanup: {e}")

    async def refresh_all_hosts_system_info(self):
        """
        Refresh OS and Docker version information for all connected hosts.

        Called by periodic maintenance job (daily) to keep host info current.
        Updates both in-memory DockerHost objects and database records.
        """
        if not self.hosts or not self.clients:
            logger.debug("No hosts to refresh system info for")
            return

        updated_count = 0
        failed_count = 0

        for host_id, host in list(self.hosts.items()):  # Use list() to avoid dict iteration issues
            try:
                # Get client for this host
                client = self.clients.get(host_id)
                if not client:
                    logger.warning(f"No client found for host {host.name} ({host_id[:8]}), skipping system info refresh")
                    failed_count += 1
                    continue

                # Fetch fresh system info using shared helper (run in thread pool to avoid blocking)
                from utils.async_docker import async_docker_call
                sys_info = await async_docker_call(_fetch_system_info_from_docker, client, host.name)

                # Check if anything changed (avoid unnecessary DB writes)
                changed = (
                    sys_info['os_type'] != host.os_type or
                    sys_info['os_version'] != host.os_version or
                    sys_info['kernel_version'] != host.kernel_version or
                    sys_info['docker_version'] != host.docker_version or
                    sys_info['daemon_started_at'] != host.daemon_started_at or
                    sys_info['total_memory'] != host.total_memory or
                    sys_info['num_cpus'] != host.num_cpus or
                    sys_info.get('is_podman', False) != host.is_podman
                )

                if not changed:
                    logger.debug(f"System info unchanged for {host.name} ({host_id[:8]})")
                    continue

                # Update in-memory DockerHost object
                host.os_type = sys_info['os_type']
                host.os_version = sys_info['os_version']
                host.kernel_version = sys_info['kernel_version']
                host.docker_version = sys_info['docker_version']
                host.daemon_started_at = sys_info['daemon_started_at']
                host.total_memory = sys_info['total_memory']
                host.num_cpus = sys_info['num_cpus']
                host.is_podman = sys_info.get('is_podman', False)

                # Update database (in separate session to avoid blocking)
                with self.db.get_session() as session:
                    db_host = session.query(DockerHostDB).filter(DockerHostDB.id == host_id).first()
                    if db_host:
                        db_host.os_type = sys_info['os_type']
                        db_host.os_version = sys_info['os_version']
                        db_host.kernel_version = sys_info['kernel_version']
                        db_host.docker_version = sys_info['docker_version']
                        db_host.daemon_started_at = sys_info['daemon_started_at']
                        db_host.total_memory = sys_info['total_memory']
                        db_host.num_cpus = sys_info['num_cpus']
                        db_host.is_podman = sys_info.get('is_podman', False)
                        session.commit()

                        platform_type = "Podman" if sys_info.get('is_podman', False) else "Docker"
                        logger.info(f"Refreshed system info for {host.name} ({host_id[:8]}): {sys_info['os_version']} / {platform_type} {sys_info['docker_version']}")
                        updated_count += 1
                    else:
                        logger.warning(f"Host {host.name} ({host_id[:8]}) not found in database")
                        failed_count += 1

            except Exception as e:
                logger.error(f"Failed to refresh system info for {host.name} ({host_id[:8]}): {e}")
                failed_count += 1

        if updated_count > 0 or failed_count > 0:
            logger.info(f"Host system info refresh complete: {updated_count} updated, {failed_count} failed")
        else:
            logger.debug("Host system info refresh complete: no changes detected")