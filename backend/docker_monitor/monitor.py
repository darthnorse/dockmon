"""
Docker Monitoring Core for DockMon
Main monitoring class for Docker containers and hosts
"""

import asyncio
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
from auth.session_manager import session_manager


logger = logging.getLogger(__name__)


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
                security_status=security_status
            )

            # Store client and host
            self.clients[host.id] = client
            self.hosts[host.id] = host

            # Save to database only if not reconnecting to an existing host
            if not skip_db_save:
                db_host = self.db.add_host({
                    'id': host.id,
                    'name': config.name,
                    'url': config.url,
                    'tls_cert': config.tls_cert,
                    'tls_key': config.tls_key,
                    'tls_ca': config.tls_ca,
                    'security_status': security_status
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
            updated_db_host = self.db.update_host(host_id, {
                'name': config.name,
                'url': config.url,
                'tls_cert': config.tls_cert,
                'tls_key': config.tls_key,
                'tls_ca': config.tls_ca,
                'security_status': security_status
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
                security_status=security_status
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
                # Attempt to reconnect offline hosts
                try:
                    if host.url.startswith("unix://"):
                        client = docker.DockerClient(base_url=host.url)
                    else:
                        # For TCP, try without TLS first (client won't have certs stored)
                        client = docker.DockerClient(
                            base_url=host.url,
                            timeout=self.settings.connection_timeout
                        )
                    # Test the connection
                    client.ping()
                    # Connection successful - add to clients
                    self.clients[hid] = client
                    logger.info(f"Reconnected to offline host: {host.name}")
                except Exception as e:
                    # Still offline - update status and continue
                    host.status = "offline"
                    host.error = f"Connection failed: {str(e)}"
                    host.last_checked = datetime.now()
                    continue

            client = self.clients[hid]

            try:
                docker_containers = client.containers.list(all=True)
                host.status = "online"
                host.container_count = len(docker_containers)
                host.error = None

                for dc in docker_containers:
                    try:
                        container_id = dc.id[:12]

                        # Try to get image info, but handle missing images gracefully
                        # Access dc.image first to trigger any errors before accessing its properties
                        try:
                            container_image = dc.image
                            image_name = container_image.tags[0] if container_image.tags else container_image.short_id
                        except Exception as img_error:
                            # Image may have been deleted - use image ID from container attrs
                            # This is common when containers reference deleted images
                            image_name = dc.attrs.get('Config', {}).get('Image', 'unknown')
                            if image_name == 'unknown':
                                # Try to get from ImageID in attrs
                                image_id = dc.attrs.get('Image', '')
                                if image_id.startswith('sha256:'):
                                    image_name = image_id[:19]  # sha256: + first 12 chars
                                else:
                                    image_name = image_id[:12] if image_id else 'unknown'

                        container = Container(
                            id=dc.id,
                            short_id=container_id,
                            name=dc.name,
                            state=dc.status,
                            status=dc.attrs['State']['Status'],
                            host_id=hid,
                            host_name=host.name,
                            image=image_name,
                            created=dc.attrs['Created'],
                            auto_restart=self._get_auto_restart_status(hid, container_id),
                            restart_attempts=self.restart_attempts.get(container_id, 0)
                        )
                        containers.append(container)
                    except Exception as container_error:
                        # Log but don't fail the whole host for one bad container
                        logger.warning(f"Skipping container {dc.name if hasattr(dc, 'name') else 'unknown'} on {host.name} due to error: {container_error}")
                        continue

            except Exception as e:
                logger.error(f"Error getting containers from {host.name}: {e}")
                host.status = "offline"
                host.error = str(e)

            host.last_checked = datetime.now()

        # Fetch stats from Go stats service and populate container stats
        try:
            from stats_client import get_stats_client
            stats_client = get_stats_client()
            container_stats = await stats_client.get_container_stats()

            # Populate stats for each container using composite key (host_id:container_id)
            for container in containers:
                # Use composite key to support containers with duplicate IDs on different hosts
                composite_key = f"{container.host_id}:{container.id}"
                stats = container_stats.get(composite_key, {})
                if stats:
                    container.cpu_percent = stats.get('cpu_percent')
                    container.memory_usage = stats.get('memory_usage')
                    container.memory_limit = stats.get('memory_limit')
                    container.memory_percent = stats.get('memory_percent')
                    container.network_rx = stats.get('network_rx')
                    container.network_tx = stats.get('network_tx')
                    container.disk_read = stats.get('disk_read')
                    container.disk_write = stats.get('disk_write')
                    logger.debug(f"Populated stats for {container.name} ({container.short_id}) on {container.host_name}: CPU {container.cpu_percent}%")
        except Exception as e:
            logger.warning(f"Failed to fetch container stats from stats service: {e}")

        return containers

    def restart_container(self, host_id: str, container_id: str) -> bool:
        """Restart a specific container"""
        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")

        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        start_time = time.time()
        try:
            client = self.clients[host_id]
            container = client.containers.get(container_id)
            container_name = container.name

            container.restart(timeout=10)
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(f"Restarted container '{container_name}' on host '{host_name}'")

            # Log the successful restart
            self.event_logger.log_container_action(
                action="restart",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=True,
                triggered_by="user",
                duration_ms=duration_ms
            )
            return True
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Failed to restart container '{container_name}' on host '{host_name}': {e}")

            # Log the failed restart
            self.event_logger.log_container_action(
                action="restart",
                container_name=container_id,  # Use ID if name unavailable
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=False,
                triggered_by="user",
                error_message=str(e),
                duration_ms=duration_ms
            )
            raise HTTPException(status_code=500, detail=str(e))

    def stop_container(self, host_id: str, container_id: str) -> bool:
        """Stop a specific container"""
        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")

        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        start_time = time.time()
        try:
            client = self.clients[host_id]
            container = client.containers.get(container_id)
            container_name = container.name

            container.stop(timeout=10)
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(f"Stopped container '{container_name}' on host '{host_name}'")

            # Track this user action to suppress critical severity on expected state change
            container_key = f"{host_id}:{container_id}"
            self._recent_user_actions[container_key] = time.time()
            logger.info(f"Tracked user stop action for {container_key}")

            # Log the successful stop
            self.event_logger.log_container_action(
                action="stop",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=True,
                triggered_by="user",
                duration_ms=duration_ms
            )
            return True
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Failed to stop container '{container_name}' on host '{host_name}': {e}")

            # Log the failed stop
            self.event_logger.log_container_action(
                action="stop",
                container_name=container_id,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=False,
                triggered_by="user",
                error_message=str(e),
                duration_ms=duration_ms
            )
            raise HTTPException(status_code=500, detail=str(e))

    def start_container(self, host_id: str, container_id: str) -> bool:
        """Start a specific container"""
        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")

        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        start_time = time.time()
        try:
            client = self.clients[host_id]
            container = client.containers.get(container_id)
            container_name = container.name

            container.start()
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(f"Started container '{container_name}' on host '{host_name}'")

            # Track this user action to suppress critical severity on expected state change
            container_key = f"{host_id}:{container_id}"
            self._recent_user_actions[container_key] = time.time()
            logger.info(f"Tracked user start action for {container_key}")

            # Log the successful start
            self.event_logger.log_container_action(
                action="start",
                container_name=container_name,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=True,
                triggered_by="user",
                duration_ms=duration_ms
            )
            return True
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Failed to start container '{container_name}' on host '{host_name}': {e}")

            # Log the failed start
            self.event_logger.log_container_action(
                action="start",
                container_name=container_id,
                container_id=container_id,
                host_name=host_name,
                host_id=host_id,
                success=False,
                triggered_by="user",
                error_message=str(e),
                duration_ms=duration_ms
            )
            raise HTTPException(status_code=500, detail=str(e))

    def toggle_auto_restart(self, host_id: str, container_id: str, container_name: str, enabled: bool):
        """Toggle auto-restart for a container"""
        # Get host name for logging
        host = self.hosts.get(host_id)
        host_name = host.name if host else 'Unknown Host'

        # Use host_id:container_id as key to prevent collisions between hosts
        container_key = f"{host_id}:{container_id}"
        self.auto_restart_status[container_key] = enabled
        if not enabled:
            self.restart_attempts[container_key] = 0
            self.restarting_containers[container_key] = False
        # Save to database
        self.db.set_auto_restart(host_id, container_id, container_name, enabled)
        logger.info(f"Auto-restart {'enabled' if enabled else 'disabled'} for container '{container_name}' on host '{host_name}'")

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
                    if self.stats_manager.should_broadcast_host_metrics(self.settings):
                        # Get host metrics from stats service (fast HTTP call)
                        host_metrics = await stats_client.get_host_stats()
                        logger.debug(f"Retrieved metrics for {len(host_metrics)} hosts from stats service")
                        broadcast_data["host_metrics"] = host_metrics

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
                    config = DockerHostConfig(
                        name=db_host.name,
                        url=db_host.url,
                        tls_cert=db_host.tls_cert,
                        tls_key=db_host.tls_key,
                        tls_ca=db_host.tls_ca
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
                    host = DockerHost(
                        id=db_host.id,
                        name=db_host.name,
                        url=db_host.url,
                        status="offline",
                        client=None
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
        # Use host_id:container_id as key to prevent collisions between hosts
        container_key = f"{host_id}:{container_id}"

        # Check in-memory cache first
        if container_key in self.auto_restart_status:
            return self.auto_restart_status[container_key]

        # Check database
        config = self.db.get_auto_restart_config(host_id, container_id)
        if config:
            self.auto_restart_status[container_key] = config.enabled
            return config.enabled

        return False

    async def cleanup_old_data(self):
        """Periodic cleanup of old data"""
        logger.info("Starting periodic data cleanup...")

        while True:
            try:
                settings = self.db.get_settings()

                if settings.auto_cleanup_events:
                    # Clean up old events
                    event_deleted = self.db.cleanup_old_events(settings.event_retention_days)
                    if event_deleted > 0:
                        self.event_logger.log_system_event(
                            "Automatic Event Cleanup",
                            f"Cleaned up {event_deleted} events older than {settings.event_retention_days} days",
                            EventSeverity.INFO,
                            EventType.STARTUP
                        )

                # Clean up expired sessions (runs daily regardless of event cleanup setting)
                expired_count = session_manager.cleanup_expired_sessions()
                if expired_count > 0:
                    logger.info(f"Cleaned up {expired_count} expired sessions")

                # Sleep for 24 hours before next cleanup
                await asyncio.sleep(24 * 60 * 60)  # 24 hours

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                # Wait 1 hour before retrying
                await asyncio.sleep(60 * 60)  # 1 hour