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
from database import DatabaseManager, AutoRestartConfig
from models.docker_models import DockerHost, DockerHostConfig, Container
from models.settings_models import AlertRule, NotificationSettings
from websocket.connection import ConnectionManager
from realtime import RealtimeMonitor, LiveUpdateManager
from notifications import NotificationService, AlertProcessor
from event_logger import EventLogger, EventSeverity, EventType


logger = logging.getLogger(__name__)


class DockerMonitor:
    """Main monitoring class for Docker containers"""

    def __init__(self):
        self.hosts: Dict[str, DockerHost] = {}
        self.clients: Dict[str, DockerClient] = {}
        self.db = DatabaseManager(DATABASE_PATH)  # Initialize database with centralized path
        self.settings = self.db.get_settings()  # Load settings from DB
        self.alert_rules: List[AlertRule] = self._load_alert_rules()  # Load alert rules from DB
        self.notification_settings = NotificationSettings()
        self.auto_restart_status: Dict[str, bool] = {}
        self.restart_attempts: Dict[str, int] = {}
        self.restarting_containers: Dict[str, bool] = {}  # Track containers currently being restarted
        self.monitoring_task: Optional[asyncio.Task] = None
        self.manager = ConnectionManager()
        self.realtime = RealtimeMonitor()  # Real-time monitoring
        self.live_updates = LiveUpdateManager()  # Live update batching
        self.notification_service = NotificationService(self.db)  # Notification service
        self.alert_processor = AlertProcessor(self.notification_service)  # Alert processor
        self.event_logger = EventLogger(self.db)  # Event logging service

        # Connect the notification service to the realtime monitor for Docker event alerts
        self.realtime.notification_service = self.notification_service
        self._container_states: Dict[str, str] = {}  # Track container states for change detection
        self.cleanup_task: Optional[asyncio.Task] = None  # Background cleanup task
        self._load_persistent_config()  # Load saved hosts and configs

    def add_host(self, config: DockerHostConfig, existing_id: str = None, skip_db_save: bool = False) -> DockerHost:
        """Add a new Docker host to monitor"""
        try:
            # Create Docker client
            if config.url.startswith("unix://"):
                client = docker.DockerClient(base_url=config.url)
            else:
                # For TCP connections
                tls_config = None
                if config.tls_cert and config.tls_key:
                    # Create persistent certificate storage directory
                    cert_dir = os.path.join(CERTS_DIR, existing_id or str(uuid.uuid4()))
                    os.makedirs(cert_dir, exist_ok=True)

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
            host = DockerHost(
                id=existing_id or str(uuid.uuid4()),
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

            # Start Docker event monitoring for this host
            self.realtime.start_event_monitor(client, host.id)

            # Log host connection
            self.event_logger.log_host_connection(
                host_name=host.name,
                host_id=host.id,
                host_url=config.url,
                connected=True
            )

            logger.info(f"Added Docker host: {host.name} ({host.url})")
            return host

        except Exception as e:
            logger.error(f"Failed to add host {config.name}: {e}")
            raise HTTPException(status_code=400, detail=str(e))

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
        cert_dir = os.path.join(CERTS_DIR, host_id)
        if os.path.exists(cert_dir):
            try:
                shutil.rmtree(cert_dir)
                logger.info(f"Cleaned up certificate files for host {host_id}")
            except Exception as e:
                logger.warning(f"Failed to clean up certificates for host {host_id}: {e}")

    def remove_host(self, host_id: str):
        """Remove a Docker host"""
        if host_id in self.hosts:
            del self.hosts[host_id]
            if host_id in self.clients:
                self.clients[host_id].close()
                del self.clients[host_id]
            # Stop event monitoring
            self.realtime.stop_event_monitoring(host_id)
            # Clean up certificate files
            self._cleanup_host_certificates(host_id)
            # Remove from database
            self.db.delete_host(host_id)
            # Refresh alert rules cache since host-specific rules may have been deleted
            self.refresh_alert_rules()
            logger.info(f"Removed host {host_id}")

    def update_host(self, host_id: str, config: DockerHostConfig):
        """Update an existing Docker host"""
        try:
            # Remove the existing host from memory first
            if host_id in self.hosts:
                # Close existing client first (this should stop the monitoring task)
                if host_id in self.clients:
                    logger.info(f"Closing Docker client for host {host_id}")
                    self.clients[host_id].close()
                    del self.clients[host_id]

                # Then explicitly stop event monitoring
                logger.info(f"Stopping event monitoring for host {host_id}")
                self.realtime.stop_event_monitoring(host_id)

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
                    cert_dir = os.path.join(CERTS_DIR, host_id)
                    os.makedirs(cert_dir, exist_ok=True)

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

            # Start Docker event monitoring for this host
            logger.info(f"Starting event monitoring for updated host {host.id}")
            self.realtime.start_event_monitor(client, host.id)

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
            logger.error(f"Failed to update host {host_id}: {e}")
            raise

    def get_containers(self, host_id: Optional[str] = None) -> List[Container]:
        """Get containers from one or all hosts"""
        containers = []

        hosts_to_check = [host_id] if host_id else list(self.hosts.keys())

        for hid in hosts_to_check:
            if hid not in self.clients:
                continue

            host = self.hosts[hid]
            client = self.clients[hid]

            try:
                docker_containers = client.containers.list(all=True)
                host.status = "online"
                host.container_count = len(docker_containers)
                host.error = None

                for dc in docker_containers:
                    container_id = dc.id[:12]
                    container = Container(
                        id=dc.id,
                        short_id=container_id,
                        name=dc.name,
                        state=dc.status,
                        status=dc.attrs['State']['Status'],
                        host_id=hid,
                        host_name=host.name,
                        image=dc.image.tags[0] if dc.image.tags else dc.image.short_id,
                        created=dc.attrs['Created'],
                        auto_restart=self._get_auto_restart_status(hid, container_id),
                        restart_attempts=self.restart_attempts.get(container_id, 0)
                    )
                    containers.append(container)

            except Exception as e:
                logger.error(f"Error getting containers from {host.name}: {e}")
                host.status = "offline"
                host.error = str(e)

            host.last_checked = datetime.now()

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

            logger.info(f"Restarted container {container_id} on host {host_id}")

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
            logger.error(f"Failed to restart container {container_id}: {e}")

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

            logger.info(f"Stopped container {container_id} on host {host_id}")

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
            logger.error(f"Failed to stop container {container_id}: {e}")

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

            logger.info(f"Started container {container_id} on host {host_id}")

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
            logger.error(f"Failed to start container {container_id}: {e}")

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
        self.auto_restart_status[container_id] = enabled
        if not enabled:
            self.restart_attempts[container_id] = 0
            self.restarting_containers[container_id] = False
        # Save to database
        self.db.set_auto_restart(host_id, container_id, container_name, enabled)
        logger.info(f"Auto-restart {'enabled' if enabled else 'disabled'} for {container_id}")

    async def monitor_containers(self):
        """Main monitoring loop"""
        logger.info("Starting container monitoring...")

        while True:
            try:
                containers = self.get_containers()

                # Track container state changes and log them
                for container in containers:
                    container_key = f"{container.host_id}:{container.id}"
                    current_state = container.status
                    previous_state = self._container_states.get(container_key)

                    # Log state changes
                    if previous_state is not None and previous_state != current_state:
                        self.event_logger.log_container_state_change(
                            container_name=container.name,
                            container_id=container.short_id,
                            host_name=container.host_name,
                            host_id=container.host_id,
                            old_state=previous_state,
                            new_state=current_state,
                            triggered_by="system"
                        )

                    # Update tracked state
                    self._container_states[container_key] = current_state

                # Check for containers that need auto-restart
                for container in containers:
                    if (container.status == "exited" and
                        self._get_auto_restart_status(container.host_id, container.short_id)):

                        attempts = self.restart_attempts.get(container.short_id, 0)
                        is_restarting = self.restarting_containers.get(container.short_id, False)

                        if attempts < self.settings.max_retries and not is_restarting:
                            self.restarting_containers[container.short_id] = True
                            asyncio.create_task(
                                self.auto_restart_container(container)
                            )

                # Process alerts for container state changes
                await self.alert_processor.process_container_update(containers, self.hosts)

                # Broadcast update to all connected clients
                await self.manager.broadcast({
                    "type": "containers_update",
                    "data": {
                        "containers": [c.dict() for c in containers],
                        "hosts": [h.dict() for h in self.hosts.values()],
                        "timestamp": datetime.now().isoformat()
                    }
                })

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")

            await asyncio.sleep(self.settings.polling_interval)

    async def auto_restart_container(self, container: Container):
        """Attempt to auto-restart a container"""
        container_id = container.short_id
        self.restart_attempts[container_id] = self.restart_attempts.get(container_id, 0) + 1
        attempt = self.restart_attempts[container_id]

        correlation_id = self.event_logger.create_correlation_id()

        logger.info(
            f"Auto-restart attempt {attempt}/{self.settings.max_retries} "
            f"for {container.name}"
        )

        # Wait before attempting restart
        await asyncio.sleep(self.settings.retry_delay)

        try:
            success = self.restart_container(container.host_id, container.id)
            if success:
                self.restart_attempts[container_id] = 0

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
                self.auto_restart_status[container_id] = False
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
            self.restarting_containers[container_id] = False

    def _load_persistent_config(self):
        """Load saved configuration from database"""
        try:
            # Load saved hosts
            db_hosts = self.db.get_hosts(active_only=True)
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
                    host = self.add_host(config, existing_id=db_host.id, skip_db_save=True)
                    # Override with stored security status
                    if hasattr(host, 'security_status') and db_host.security_status:
                        host.security_status = db_host.security_status
                except Exception as e:
                    logger.error(f"Failed to reconnect to saved host {db_host.name}: {e}")

            # Load auto-restart configurations
            for host_id in self.hosts.keys():
                configs = self.db.get_session().query(AutoRestartConfig).filter(
                    AutoRestartConfig.host_id == host_id,
                    AutoRestartConfig.enabled == True
                ).all()
                for config in configs:
                    self.auto_restart_status[config.container_id] = True
                    self.restart_attempts[config.container_id] = config.restart_count

            logger.info(f"Loaded {len(self.hosts)} hosts from database")
        except Exception as e:
            logger.error(f"Error loading persistent config: {e}")

    def _load_alert_rules(self) -> List[AlertRule]:
        """Load alert rules from database"""
        try:
            db_rules = self.db.get_alert_rules(enabled_only=False)
            alert_rules = []
            for rule in db_rules:
                alert_rule = AlertRule(
                    id=rule.id,
                    name=rule.name,
                    host_id=rule.host_id,
                    container_pattern=rule.container_pattern,
                    trigger_states=rule.trigger_states,
                    notification_channels=rule.notification_channels,
                    cooldown_minutes=rule.cooldown_minutes,
                    enabled=rule.enabled,
                    created_at=rule.created_at,
                    last_triggered=rule.last_triggered
                )
                alert_rules.append(alert_rule)
            logger.info(f"Loaded {len(alert_rules)} alert rules from database")
            return alert_rules
        except Exception as e:
            logger.error(f"Error loading alert rules: {e}")
            return []

    def refresh_alert_rules(self):
        """Refresh alert rules from database"""
        self.alert_rules = self._load_alert_rules()

    def _get_auto_restart_status(self, host_id: str, container_id: str) -> bool:
        """Get auto-restart status for a container"""
        # Check in-memory cache first
        if container_id in self.auto_restart_status:
            return self.auto_restart_status[container_id]

        # Check database
        config = self.db.get_auto_restart_config(host_id, container_id)
        if config:
            self.auto_restart_status[container_id] = config.enabled
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

                    # Clean up old container history (legacy table)
                    self.db.cleanup_old_history(settings.log_retention_days)

                # Sleep for 24 hours before next cleanup
                await asyncio.sleep(24 * 60 * 60)  # 24 hours

            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                # Wait 1 hour before retrying
                await asyncio.sleep(60 * 60)  # 1 hour