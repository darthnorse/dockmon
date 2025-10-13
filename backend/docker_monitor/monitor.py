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
from datetime import datetime
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
from notifications import NotificationService, AlertProcessor
from event_logger import EventLogger, EventSeverity, EventType
from stats_client import get_stats_client
from docker_monitor.stats_manager import StatsManager
from docker_monitor.stats_history import StatsHistoryBuffer, ContainerStatsHistoryBuffer
from docker_monitor.container_discovery import ContainerDiscovery
from docker_monitor.state_manager import StateManager
from docker_monitor.operations import ContainerOperations
from docker_monitor.cleanup import CleanupManager
from auth.session_manager import session_manager


logger = logging.getLogger(__name__)


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
        self.notification_service = NotificationService(self.db, self.event_logger)  # Notification service
        self.alert_processor = AlertProcessor(self.notification_service)  # Alert processor
        self._container_states: Dict[str, str] = {}  # Track container states for change detection
        self._recent_user_actions: Dict[str, float] = {}  # Track recent user actions: {container_key: timestamp}
        self.cleanup_task: Optional[asyncio.Task] = None  # Background cleanup task

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
        self.discovery = ContainerDiscovery(self.db, self.settings, self.hosts, self.clients)
        # Share reconnection tracking with discovery module
        self.discovery.reconnect_attempts = self.reconnect_attempts
        self.discovery.last_reconnect_attempt = self.last_reconnect_attempt

        self.state_manager = StateManager(self.db, self.hosts, self.clients)
        # Share state dictionaries with state_manager
        self.state_manager.auto_restart_status = self.auto_restart_status
        self.state_manager.restart_attempts = self.restart_attempts
        self.state_manager.restarting_containers = self.restarting_containers

        self.operations = ContainerOperations(self.hosts, self.clients, self.event_logger, self._recent_user_actions)
        self.cleanup_manager = CleanupManager(self.db, self.event_logger)

        self._load_persistent_config()  # Load saved hosts and configs

    def add_host(self, config: DockerHostConfig, existing_id: str = None, skip_db_save: bool = False, suppress_event_loop_errors: bool = False) -> DockerHost:
        """Add a new Docker host to monitor"""
        client = None  # Track client for cleanup on error
        try:
            # Validate certificates if provided (before trying to use them)
            if config.tls_cert or config.tls_key or config.tls_ca:
                self._validate_certificates(config)

            # Create Docker client
            if config.url.startswith("unix://"):
                client = docker.DockerClient(base_url=config.url)
            else:
                # For TCP connections
                tls_config = None
                if config.tls_cert and config.tls_key:
                    # Create persistent certificate storage directory
                    safe_id = sanitize_host_id(existing_id or str(uuid.uuid4()))
                    cert_dir = os.path.join(CERTS_DIR, safe_id)

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

            # Fetch system information
            try:
                system_info = client.info()
                os_type = system_info.get('OSType', None)
                os_version = system_info.get('OperatingSystem', None)
                kernel_version = system_info.get('KernelVersion', None)
                total_memory = system_info.get('MemTotal', None)  # Total memory in bytes
                num_cpus = system_info.get('NCPU', None)  # Number of CPUs

                version_info = client.version()
                docker_version = version_info.get('Version', None)

                # Get Docker daemon start time from bridge network creation
                daemon_started_at = None
                try:
                    networks = client.networks.list()
                    bridge_net = next((n for n in networks if n.name == 'bridge'), None)
                    if bridge_net:
                        daemon_started_at = bridge_net.attrs.get('Created')
                except Exception as e:
                    logger.debug(f"Failed to get daemon start time for {config.name}: {e}")
            except Exception as e:
                logger.warning(f"Failed to fetch system info for {config.name}: {e}")
                os_type = None
                os_version = None
                kernel_version = None
                docker_version = None
                daemon_started_at = None
                total_memory = None
                num_cpus = None

            # Validate TLS configuration for TCP connections
            security_status = self._validate_host_security(config)

            # Create host object with existing ID if provided (for persistence after restarts)
            # Sanitize the ID to prevent path traversal
            host_id = existing_id or str(uuid.uuid4())
            try:
                host_id = sanitize_host_id(host_id)
            except ValueError as e:
                logger.error(f"Invalid host ID: {e}")
                raise HTTPException(status_code=400, detail=str(e))

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
                num_cpus=num_cpus
            )

            # Store client and host
            self.clients[host.id] = client
            self.hosts[host.id] = host

            # Update OS info in database if reconnecting (when info wasn't saved before)
            if skip_db_save and (os_type or os_version or kernel_version or docker_version or daemon_started_at or total_memory or num_cpus):
                # Update existing host with OS info
                try:
                    session = self.db.get_session()
                    from database import DockerHostDB
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
                        session.commit()
                        logger.info(f"Updated OS info for {host.name}: {os_version} / Docker {docker_version}")
                    session.close()
                except Exception as e:
                    logger.warning(f"Failed to update OS info for {host.name}: {e}")

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
                    'num_cpus': host.num_cpus
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
                            await stats_client.add_docker_host(host.id, host.url, config.tls_ca, config.tls_cert, config.tls_key)
                            logger.info(f"Registered {host.name} ({host.id[:8]}) with stats service")

                            await stats_client.add_event_host(host.id, host.url, config.tls_ca, config.tls_cert, config.tls_key)
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
                logger.info(f"Cleaned up certificate files for host {host_id}")
            except Exception as e:
                logger.warning(f"Failed to clean up certificates for host {host_id}: {e}")

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
                logger.warning(f"Failed to remove host {host_id} from Go services: {e}")

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

            # Clean up notification service's container state tracking for this host
            notification_states_to_remove = [key for key in self.notification_service._last_container_state.keys() if key.startswith(f"{host_id}:")]
            for container_key in notification_states_to_remove:
                del self.notification_service._last_container_state[container_key]

            # Clean up alert processor's container state tracking for this host
            alert_processor_states_to_remove = [key for key in self.alert_processor._container_states.keys() if key.startswith(f"{host_id}:")]
            for container_key in alert_processor_states_to_remove:
                del self.alert_processor._container_states[container_key]

            # Clean up notification service's alert cooldown tracking for this host
            alert_cooldowns_to_remove = [key for key in self.notification_service._last_alerts.keys() if key.startswith(f"{host_id}:")]
            for container_key in alert_cooldowns_to_remove:
                del self.notification_service._last_alerts[container_key]

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

            if containers_to_remove:
                logger.debug(f"Cleaned up {len(containers_to_remove)} container state entries for removed host {host_id[:8]}")
            if notification_states_to_remove:
                logger.debug(f"Cleaned up {len(notification_states_to_remove)} notification state entries for removed host {host_id[:8]}")
            if alert_processor_states_to_remove:
                logger.debug(f"Cleaned up {len(alert_processor_states_to_remove)} alert processor state entries for removed host {host_id[:8]}")
            if alert_cooldowns_to_remove:
                logger.debug(f"Cleaned up {len(alert_cooldowns_to_remove)} alert cooldown entries for removed host {host_id[:8]}")
            if auto_restart_to_remove:
                logger.debug(f"Cleaned up {len(auto_restart_to_remove)} auto-restart entries for removed host {host_id[:8]}")

            # Log host removed
            self.event_logger.log_host_removed(
                host_name=host_name,
                host_id=host_id,
                triggered_by="user"
            )

            logger.info(f"Removed host {host_id}")

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
                    logger.info(f"Closing Docker client for host {host_id}")
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

            # Create host object with existing ID
            host = DockerHost(
                id=host_id,
                name=config.name,
                url=config.url,
                status="online",
                security_status=security_status,
                tags=config.tags,
                description=config.description
            )

            # Store client and host
            self.clients[host.id] = client
            self.hosts[host.id] = host

            # Re-register host with stats and event services (in case URL changed)
            # Note: add_docker_host() automatically closes old client if it exists
            try:
                import asyncio
                stats_client = get_stats_client()

                async def reregister_host():
                    try:
                        # Re-register with stats service (automatically closes old client)
                        await stats_client.add_docker_host(host.id, host.url, config.tls_ca, config.tls_cert, config.tls_key)
                        logger.info(f"Re-registered {host.name} ({host.id[:8]}) with stats service")

                        # Remove and re-add event monitoring
                        await stats_client.remove_event_host(host.id)
                        await stats_client.add_event_host(host.id, host.url, config.tls_ca, config.tls_cert, config.tls_key)
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

            # Try to reconnect if host exists but has no client (offline)
            if hid not in self.clients:
                reconnected = await self.discovery.attempt_reconnection(hid)
                if not reconnected:
                    continue

            # Discover containers for this host
            host_containers = self.discovery.discover_containers_for_host(hid, self._get_auto_restart_status)

            # Populate restart_attempts from monitor's state
            for container in host_containers:
                container.restart_attempts = self.restart_attempts.get(container.short_id, 0)

            containers.extend(host_containers)

        # Populate stats for all containers
        await self.discovery.populate_container_stats(containers)

        return containers

    def restart_container(self, host_id: str, container_id: str) -> bool:
        """Restart a specific container"""
        return self.operations.restart_container(host_id, container_id)

    def stop_container(self, host_id: str, container_id: str) -> bool:
        """Stop a specific container"""
        return self.operations.stop_container(host_id, container_id)

    def start_container(self, host_id: str, container_id: str) -> bool:
        """Start a specific container"""
        return self.operations.start_container(host_id, container_id)

    def toggle_auto_restart(self, host_id: str, container_id: str, container_name: str, enabled: bool):
        """Toggle auto-restart for a container"""
        return self.state_manager.toggle_auto_restart(host_id, container_id, container_name, enabled)

    def set_container_desired_state(self, host_id: str, container_id: str, container_name: str, desired_state: str):
        """Set desired state for a container"""
        return self.state_manager.set_container_desired_state(host_id, container_id, container_name, desired_state)

    # Alias methods for batch operations (consistent naming)
    def update_container_auto_restart(self, host_id: str, container_id: str, container_name: str, enabled: bool):
        """Alias for toggle_auto_restart - used by batch operations"""
        return self.toggle_auto_restart(host_id, container_id, container_name, enabled)

    def update_container_desired_state(self, host_id: str, container_id: str, container_name: str, desired_state: str):
        """Alias for set_container_desired_state - used by batch operations"""
        return self.set_container_desired_state(host_id, container_id, container_name, desired_state)

    def update_container_tags(self, host_id: str, container_id: str, container_name: str, tags_to_add: list[str], tags_to_remove: list[str]) -> dict:
        """Update container custom tags in database"""
        return self.state_manager.update_container_tags(host_id, container_id, container_name, tags_to_add, tags_to_remove)

    async def check_orphaned_alerts(self):
        """Check for alert rules that reference non-existent containers
        Returns dict mapping alert_rule_id to list of orphaned container entries"""
        orphaned = {}

        try:
            # Get all alert rules
            with self.db.get_session() as session:
                from database import AlertRuleDB, AlertRuleContainer
                alert_rules = session.query(AlertRuleDB).all()

                # Get all current containers (name + host_id pairs)
                current_containers = {}
                for container in await self.get_containers():
                    key = f"{container.host_id}:{container.name}"
                    current_containers[key] = True

                # Check each alert rule's containers
                for rule in alert_rules:
                    orphaned_containers = []
                    for alert_container in rule.containers:
                        key = f"{alert_container.host_id}:{alert_container.container_name}"
                        if key not in current_containers:
                            # Container doesn't exist anymore
                            orphaned_containers.append({
                                'host_id': alert_container.host_id,
                                'host_name': alert_container.host.name if alert_container.host else 'Unknown',
                                'container_name': alert_container.container_name
                            })

                    if orphaned_containers:
                        orphaned[rule.id] = {
                            'rule_name': rule.name,
                            'orphaned_containers': orphaned_containers
                        }

                if orphaned:
                    logger.info(f"Found {len(orphaned)} alert rules with orphaned containers")

                return orphaned

        except Exception as e:
            logger.error(f"Error checking orphaned alerts: {e}")
            return {}

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

            # Only log important events
            important_events = ['create', 'start', 'stop', 'die', 'kill', 'destroy', 'pause', 'unpause', 'restart', 'oom', 'health_status']
            if action in important_events:
                logger.info(f"Docker event: {action} - {container_name} ({container_id[:12]}) on host {host_id[:8]}")

            # Process event for notifications/alerts
            if self.notification_service and action in ['die', 'oom', 'kill', 'health_status', 'restart']:
                # Parse timestamp
                from datetime import datetime
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except (ValueError, AttributeError, TypeError) as e:
                    logger.warning(f"Failed to parse timestamp '{timestamp_str}': {e}, using current time")
                    timestamp = datetime.now()

                # Get exit code for die events
                exit_code = None
                if action == 'die':
                    exit_code_str = attributes.get('exitCode', '0')
                    try:
                        exit_code = int(exit_code_str)
                    except (ValueError, TypeError):
                        exit_code = None

                # Create alert event
                from notifications import DockerEventAlert
                alert_event = DockerEventAlert(
                    container_id=container_id,
                    container_name=container_name,
                    host_id=host_id,
                    event_type=action,
                    timestamp=timestamp,
                    attributes=attributes,
                    exit_code=exit_code
                )

                # Process in background to not block event monitoring
                task = asyncio.create_task(self.notification_service.process_docker_event(alert_event))
                task.add_done_callback(_handle_task_exception)

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
                session = self.db.get_session()
                try:
                    db_host = session.query(DockerHostDB).filter_by(id=host_id).first()
                    tls_ca = db_host.tls_ca if db_host else None
                    tls_cert = db_host.tls_cert if db_host else None
                    tls_key = db_host.tls_key if db_host else None
                finally:
                    session.close()

                # Register with stats service
                await stats_client.add_docker_host(host_id, host.url, tls_ca, tls_cert, tls_key)
                logger.info(f"Registered host {host.name} ({host_id[:8]}) with stats service")

                # Register with event service
                await stats_client.add_event_host(host_id, host.url, tls_ca, tls_cert, tls_key)
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

                # Centralized stats collection decision using StatsManager
                has_viewers = self.manager.has_active_connections()
                logger.info(f"Monitor loop: has_viewers={has_viewers}, active_connections={len(self.manager.active_connections)}")

                if has_viewers:
                    # Determine which containers need stats (centralized logic)
                    containers_needing_stats = self.stats_manager.determine_containers_needing_stats(
                        containers,
                        self.settings
                    )

                    # Sync streams with what's needed (start new, stop old)
                    await self.stats_manager.sync_container_streams(
                        containers,
                        containers_needing_stats,
                        stats_client,
                        _handle_task_exception
                    )
                else:
                    # No active viewers - stop all streams
                    await self.stats_manager.stop_all_streams(stats_client, _handle_task_exception)

                # Track container state changes and log them
                for container in containers:
                    container_key = f"{container.host_id}:{container.id}"
                    current_state = container.status

                    # Hold lock during entire read-process-write to prevent race conditions
                    async with self._state_lock:
                        previous_state = self._container_states.get(container_key)

                        # Log state changes
                        if previous_state is not None and previous_state != current_state:
                            # Check if this state change was expected (recent user action)
                            async with self._actions_lock:
                                last_user_action = self._recent_user_actions.get(container_key, 0)
                            time_since_action = time.time() - last_user_action
                            is_user_initiated = time_since_action < 30  # Within 30 seconds

                            logger.info(f"State change for {container_key}: {previous_state} → {current_state}, "
                                      f"time_since_action={time_since_action:.1f}s, user_initiated={is_user_initiated}")

                            # Clean up old tracking entries (5 minutes or older)
                            if time_since_action >= 300:
                                async with self._actions_lock:
                                    self._recent_user_actions.pop(container_key, None)

                            self.event_logger.log_container_state_change(
                                container_name=container.name,
                                container_id=container.short_id,
                                host_name=container.host_name,
                                host_id=container.host_id,
                                old_state=previous_state,
                                new_state=current_state,
                                triggered_by="user" if is_user_initiated else "system"
                            )

                        # Update tracked state (still inside lock)
                        self._container_states[container_key] = current_state

                # Check for containers that need auto-restart
                for container in containers:
                    if (container.status == "exited" and
                        self._get_auto_restart_status(container.host_id, container.short_id)):

                        # Use host_id:container_id as key to prevent collisions between hosts
                        container_key = f"{container.host_id}:{container.short_id}"
                        attempts = self.restart_attempts.get(container_key, 0)
                        is_restarting = self.restarting_containers.get(container_key, False)

                        if attempts < self.settings.max_retries and not is_restarting:
                            self.restarting_containers[container_key] = True
                            task = asyncio.create_task(
                                self.auto_restart_container(container)
                            )
                            task.add_done_callback(_handle_task_exception)

                # Process alerts for container state changes
                await self.alert_processor.process_container_update(containers, self.hosts)

                # Only fetch and broadcast stats if there are active viewers
                if has_viewers:
                    # Prepare broadcast data
                    broadcast_data = {
                        "containers": [c.dict() for c in containers],
                        "hosts": [h.dict() for h in self.hosts.values()],
                        "timestamp": datetime.now().isoformat()
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
                        logger.info(f"Aggregated metrics for {len(host_metrics)} hosts from {len(containers)} containers")

                    # Collect container sparklines for all containers
                    container_sparklines = {}
                    for container in containers:
                        # Use composite key: host_id:container_id
                        container_key = f"{container.host_id}:{container.id}"

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

            await asyncio.sleep(self.settings.polling_interval)

    async def auto_restart_container(self, container: Container):
        """Attempt to auto-restart a container"""
        container_id = container.short_id
        # Use host_id:container_id as key to prevent collisions between hosts
        container_key = f"{container.host_id}:{container_id}"

        self.restart_attempts[container_key] = self.restart_attempts.get(container_key, 0) + 1
        attempt = self.restart_attempts[container_key]

        correlation_id = self.event_logger.create_correlation_id()

        logger.info(
            f"Auto-restart attempt {attempt}/{self.settings.max_retries} "
            f"for container '{container.name}' on host '{container.host_name}'"
        )

        # Wait before attempting restart
        await asyncio.sleep(self.settings.retry_delay)

        try:
            success = self.restart_container(container.host_id, container.id)
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

            # Auto-add local Docker only on first run (outside session context)
            with self.db.get_session() as session:
                settings = session.query(GlobalSettings).first()
                if settings and not settings.first_run_complete and not db_hosts and os.path.exists('/var/run/docker.sock'):
                    logger.info("First run detected - adding local Docker automatically")
                    host_added = False
                    try:
                        config = DockerHostConfig(
                            name="Local Docker",
                            url="unix:///var/run/docker.sock",
                            tls_cert=None,
                            tls_key=None,
                            tls_ca=None
                        )
                        self.add_host(config, suppress_event_loop_errors=True)
                        host_added = True
                        logger.info("Successfully added local Docker host")
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
                configs = self.db.get_session().query(AutoRestartConfig).filter(
                    AutoRestartConfig.host_id == host_id,
                    AutoRestartConfig.enabled == True
                ).all()
                for config in configs:
                    # Use host_id:container_id as key to prevent collisions between hosts
                    container_key = f"{config.host_id}:{config.container_id}"
                    self.auto_restart_status[container_key] = True
                    self.restart_attempts[container_key] = config.restart_count

            logger.info(f"Loaded {len(self.hosts)} hosts from database")
        except Exception as e:
            logger.error(f"Error loading persistent config: {e}")

    def _get_auto_restart_status(self, host_id: str, container_id: str) -> bool:
        """Get auto-restart status for a container"""
        return self.state_manager.get_auto_restart_status(host_id, container_id)

    async def cleanup_old_data(self):
        """Periodic cleanup of old data"""
        await self.cleanup_manager.cleanup_old_data()