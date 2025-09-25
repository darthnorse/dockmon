#!/usr/bin/env python3
"""
DockMon Backend - Docker Container Monitoring System
Supports multiple Docker hosts with auto-restart and alerts
"""

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

import docker
import uvicorn
from docker import DockerClient
from docker.errors import DockerException, APIError
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from database import DatabaseManager, DockerHostDB
from realtime import RealtimeMonitor, LiveUpdateManager
from notifications import NotificationService, AlertProcessor
from event_logger import EventLogger, EventContext, EventCategory, EventType, EventSeverity, PerformanceTimer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Custom JSON encoder for datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

# ==================== Data Models ====================

class DockerHostConfig(BaseModel):
    """Configuration for a Docker host"""
    name: str
    url: str
    tls_cert: Optional[str] = None
    tls_key: Optional[str] = None
    tls_ca: Optional[str] = None

class DockerHost(BaseModel):
    """Docker host with connection status"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    url: str
    status: str = "offline"
    security_status: Optional[str] = None  # "secure", "insecure", "unknown"
    last_checked: datetime = Field(default_factory=datetime.now)
    container_count: int = 0
    error: Optional[str] = None

class Container(BaseModel):
    """Container information"""
    id: str
    short_id: str
    name: str
    state: str
    status: str
    host_id: str
    host_name: str
    image: str
    created: str
    auto_restart: bool = False
    restart_attempts: int = 0

class GlobalSettings(BaseModel):
    """Global monitoring settings"""
    max_retries: int = 3
    retry_delay: int = 30
    default_auto_restart: bool = False
    polling_interval: int = 10
    connection_timeout: int = 10

class AlertRule(BaseModel):
    """Alert rule configuration"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    host_id: Optional[str] = None
    container_pattern: str
    trigger_states: List[str]
    notification_channels: List[int]
    cooldown_minutes: int = 15
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_triggered: Optional[datetime] = None

class NotificationSettings(BaseModel):
    """Notification channel settings"""
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    discord_webhook: Optional[str] = None
    pushover_app_token: Optional[str] = None
    pushover_user_key: Optional[str] = None

# ==================== Connection Manager ====================

class ConnectionManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New WebSocket connection. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send message to all connected clients"""
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message, cls=DateTimeEncoder))
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                dead_connections.append(connection)
        
        # Clean up dead connections
        for conn in dead_connections:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

# ==================== Docker Monitor ====================

class DockerMonitor:
    """Main monitoring class for Docker containers"""
    
    def __init__(self):
        self.hosts: Dict[str, DockerHost] = {}
        self.clients: Dict[str, DockerClient] = {}
        self.db = DatabaseManager()  # Initialize database
        self.settings = self.db.get_settings()  # Load settings from DB
        self.alert_rules: List[AlertRule] = self._load_alert_rules()  # Load alert rules from DB
        self.notification_settings = NotificationSettings()
        self.auto_restart_status: Dict[str, bool] = {}
        self.restart_attempts: Dict[str, int] = {}
        self.monitoring_task: Optional[asyncio.Task] = None
        self.manager = ConnectionManager()
        self.realtime = RealtimeMonitor()  # Real-time monitoring
        self.live_updates = LiveUpdateManager()  # Live update batching
        self.notification_service = NotificationService(self.db)  # Notification service
        self.alert_processor = AlertProcessor(self.notification_service)  # Alert processor
        self.event_logger = EventLogger(self.db)  # Event logging service
        self._container_states: Dict[str, str] = {}  # Track container states for change detection
        self.cleanup_task: Optional[asyncio.Task] = None  # Background cleanup task
        self._load_persistent_config()  # Load saved hosts and configs
        
    def add_host(self, config: DockerHostConfig, existing_id: str = None) -> DockerHost:
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
                    import os
                    cert_dir = os.path.join('data', 'certs', existing_id or str(uuid.uuid4()))
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

            # Save to database
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
        import shutil
        import os
        cert_dir = os.path.join('data', 'certs', host_id)
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
                    cert_dir = os.path.join('data', 'certs', host_id)
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

            # Validate TLS configuration
            security_status = self._validate_host_security(config)

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
                        if attempts < self.settings.max_retries:
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
                    # Try to connect to the host with existing ID
                    self.add_host(config, existing_id=db_host.id)
                except Exception as e:
                    logger.error(f"Failed to reconnect to saved host {db_host.name}: {e}")

            # Load auto-restart configurations
            for host_id in self.hosts.keys():
                configs = self.db.get_session().query(self.db.AutoRestartConfig).filter(
                    self.db.AutoRestartConfig.host_id == host_id,
                    self.db.AutoRestartConfig.enabled == True
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

# ==================== FastAPI Application ====================

# Create monitor instance
monitor = DockerMonitor()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    logger.info("Starting DockMon backend...")
    await monitor.event_logger.start()
    monitor.event_logger.log_system_event("DockMon Backend Starting", "DockMon backend is initializing", EventSeverity.INFO, EventType.STARTUP)
    monitor.monitoring_task = asyncio.create_task(monitor.monitor_containers())
    monitor.cleanup_task = asyncio.create_task(monitor.cleanup_old_data())
    yield
    # Shutdown
    logger.info("Shutting down DockMon backend...")
    monitor.event_logger.log_system_event("DockMon Backend Shutting Down", "DockMon backend is shutting down", EventSeverity.INFO, EventType.SHUTDOWN)
    if monitor.monitoring_task:
        monitor.monitoring_task.cancel()
    if monitor.cleanup_task:
        monitor.cleanup_task.cancel()
    # Close notification service
    await monitor.notification_service.close()
    # Stop event logger
    await monitor.event_logger.stop()

app = FastAPI(
    title="DockMon API",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== API Routes ====================

@app.get("/")
async def root():
    """Backend API root - frontend is served separately"""
    return {"message": "DockMon Backend API", "version": "1.0.0", "docs": "/docs"}

@app.get("/api/hosts")
async def get_hosts():
    """Get all configured Docker hosts"""
    return list(monitor.hosts.values())

@app.post("/api/hosts")
async def add_host(config: DockerHostConfig):
    """Add a new Docker host"""
    host = monitor.add_host(config)
    return host

@app.put("/api/hosts/{host_id}")
async def update_host(host_id: str, config: DockerHostConfig):
    """Update an existing Docker host"""
    host = monitor.update_host(host_id, config)
    return host

@app.delete("/api/hosts/{host_id}")
async def remove_host(host_id: str):
    """Remove a Docker host"""
    monitor.remove_host(host_id)
    return {"status": "success", "message": f"Host {host_id} removed"}

@app.get("/api/containers")
async def get_containers(host_id: Optional[str] = None):
    """Get all containers"""
    return monitor.get_containers(host_id)

@app.post("/api/hosts/{host_id}/containers/{container_id}/restart")
async def restart_container(host_id: str, container_id: str):
    """Restart a container"""
    success = monitor.restart_container(host_id, container_id)
    return {"status": "success" if success else "failed"}

@app.post("/api/hosts/{host_id}/containers/{container_id}/stop")
async def stop_container(host_id: str, container_id: str):
    """Stop a container"""
    success = monitor.stop_container(host_id, container_id)
    return {"status": "success" if success else "failed"}

@app.post("/api/hosts/{host_id}/containers/{container_id}/start")
async def start_container(host_id: str, container_id: str):
    """Start a container"""
    success = monitor.start_container(host_id, container_id)
    return {"status": "success" if success else "failed"}

@app.get("/api/hosts/{host_id}/containers/{container_id}/logs")
async def get_container_logs(host_id: str, container_id: str, tail: int = 100):
    """Get container logs"""
    if host_id not in monitor.clients:
        raise HTTPException(status_code=404, detail="Host not found")
    
    try:
        client = monitor.clients[host_id]
        container = client.containers.get(container_id)
        logs = container.logs(tail=tail, timestamps=True).decode('utf-8')
        return {
            "container_id": container_id,
            "logs": logs.split('\n')
        }
    except Exception as e:
        logger.error(f"Failed to get logs for {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/hosts/{host_id}/containers/{container_id}/exec")
async def exec_container(host_id: str, container_id: str, command: str):
    """Execute command in container"""
    if host_id not in monitor.clients:
        raise HTTPException(status_code=404, detail="Host not found")
    
    try:
        client = monitor.clients[host_id]
        container = client.containers.get(container_id)
        result = container.exec_run(command, tty=True)
        return {
            "container_id": container_id,
            "command": command,
            "exit_code": result.exit_code,
            "output": result.output.decode('utf-8')
        }
    except Exception as e:
        logger.error(f"Failed to exec in {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/logs/{host_id}/{container_id}")
async def stream_logs(websocket: WebSocket, host_id: str, container_id: str):
    """WebSocket endpoint for streaming container logs"""
    await websocket.accept()
    
    if host_id not in monitor.clients:
        await websocket.close(code=4004, reason="Host not found")
        return
    
    try:
        client = monitor.clients[host_id]
        container = client.containers.get(container_id)
        
        # Stream logs
        for line in container.logs(stream=True, follow=True, timestamps=True):
            await websocket.send_text(line.decode('utf-8'))
            
    except WebSocketDisconnect:
        logger.info(f"Log stream disconnected for {container_id}")
    except Exception as e:
        logger.error(f"Error streaming logs: {e}")
        await websocket.close(code=4000, reason=str(e))

class AutoRestartRequest(BaseModel):
    host_id: str
    container_name: str
    enabled: bool

@app.post("/api/containers/{container_id}/auto-restart")
async def toggle_auto_restart(container_id: str, request: AutoRestartRequest):
    """Toggle auto-restart for a container"""
    monitor.toggle_auto_restart(request.host_id, container_id, request.container_name, request.enabled)
    return {"container_id": container_id, "auto_restart": request.enabled}

@app.get("/api/settings")
async def get_settings():
    """Get global settings"""
    settings = monitor.db.get_settings()
    return {
        "max_retries": settings.max_retries,
        "retry_delay": settings.retry_delay,
        "default_auto_restart": settings.default_auto_restart,
        "polling_interval": settings.polling_interval,
        "connection_timeout": settings.connection_timeout,
        "log_retention_days": settings.log_retention_days,
        "enable_notifications": settings.enable_notifications
    }

@app.post("/api/settings")
async def update_settings(settings: GlobalSettings):
    """Update global settings"""
    updated = monitor.db.update_settings(settings.dict())
    monitor.settings = updated  # Update in-memory settings
    return settings

@app.get("/api/alerts")
async def get_alert_rules():
    """Get all alert rules"""
    rules = monitor.db.get_alert_rules(enabled_only=False)
    logger.info(f"Retrieved {len(rules)} alert rules from database")
    return [{
        "id": rule.id,
        "name": rule.name,
        "host_id": rule.host_id,
        "container_pattern": rule.container_pattern,
        "trigger_states": rule.trigger_states,
        "notification_channels": rule.notification_channels,
        "cooldown_minutes": rule.cooldown_minutes,
        "enabled": rule.enabled,
        "last_triggered": rule.last_triggered.isoformat() if rule.last_triggered else None,
        "created_at": rule.created_at.isoformat(),
        "updated_at": rule.updated_at.isoformat()
    } for rule in rules]

class AlertRuleCreate(BaseModel):
    """Request model for creating alert rules"""
    name: str
    host_id: Optional[str] = None  # None means all hosts
    container_pattern: str
    trigger_states: List[str]
    notification_channels: List[int]
    cooldown_minutes: int = 15
    enabled: bool = True

class AlertRuleUpdate(BaseModel):
    """Request model for updating alert rules"""
    name: Optional[str] = None
    host_id: Optional[str] = None
    container_pattern: Optional[str] = None
    trigger_states: Optional[List[str]] = None
    notification_channels: Optional[List[int]] = None
    cooldown_minutes: Optional[int] = None
    enabled: Optional[bool] = None

@app.post("/api/alerts")
async def create_alert_rule(rule: AlertRuleCreate):
    """Create a new alert rule"""
    try:
        rule_id = str(uuid.uuid4())
        logger.info(f"Creating alert rule: {rule.name} for container: {rule.container_pattern}")
        db_rule = monitor.db.add_alert_rule({
            "id": rule_id,
            "name": rule.name,
            "host_id": rule.host_id,
            "container_pattern": rule.container_pattern,
            "trigger_states": rule.trigger_states,
            "notification_channels": rule.notification_channels,
            "cooldown_minutes": rule.cooldown_minutes,
            "enabled": rule.enabled
        })
        logger.info(f"Successfully created alert rule with ID: {db_rule.id}")

        # Refresh in-memory alert rules
        monitor.refresh_alert_rules()

        return {
            "id": db_rule.id,
            "name": db_rule.name,
            "host_id": db_rule.host_id,
            "container_pattern": db_rule.container_pattern,
            "trigger_states": db_rule.trigger_states,
            "notification_channels": db_rule.notification_channels,
            "cooldown_minutes": db_rule.cooldown_minutes,
            "enabled": db_rule.enabled,
            "last_triggered": None,
            "created_at": db_rule.created_at.isoformat(),
            "updated_at": db_rule.updated_at.isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to create alert rule: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/alerts/{rule_id}")
async def update_alert_rule(rule_id: str, updates: AlertRuleUpdate):
    """Update an alert rule"""
    try:
        update_data = {k: v for k, v in updates.dict().items() if v is not None}
        db_rule = monitor.db.update_alert_rule(rule_id, update_data)

        if not db_rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        # Refresh in-memory alert rules
        monitor.refresh_alert_rules()

        return {
            "id": db_rule.id,
            "name": db_rule.name,
            "host_id": db_rule.host_id,
            "container_pattern": db_rule.container_pattern,
            "trigger_states": db_rule.trigger_states,
            "notification_channels": db_rule.notification_channels,
            "cooldown_minutes": db_rule.cooldown_minutes,
            "enabled": db_rule.enabled,
            "last_triggered": db_rule.last_triggered.isoformat() if db_rule.last_triggered else None,
            "created_at": db_rule.created_at.isoformat(),
            "updated_at": db_rule.updated_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update alert rule: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/alerts/{rule_id}")
async def delete_alert_rule(rule_id: str):
    """Delete an alert rule"""
    try:
        success = monitor.db.delete_alert_rule(rule_id)
        if not success:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        # Refresh in-memory alert rules
        monitor.refresh_alert_rules()

        return {"status": "success", "message": f"Alert rule {rule_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete alert rule: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ==================== Notification Channel Routes ====================

class NotificationChannelCreate(BaseModel):
    """Request model for creating notification channels"""
    name: str
    type: str  # telegram, discord, pushover
    config: Dict[str, Any]  # Channel-specific configuration
    enabled: bool = True

class NotificationChannelUpdate(BaseModel):
    """Request model for updating notification channels"""
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None

@app.get("/api/notifications/channels")
async def get_notification_channels():
    """Get all notification channels"""
    channels = monitor.db.get_notification_channels(enabled_only=False)
    return [{
        "id": ch.id,
        "name": ch.name,
        "type": ch.type,
        "config": ch.config,
        "enabled": ch.enabled,
        "created_at": ch.created_at.isoformat(),
        "updated_at": ch.updated_at.isoformat()
    } for ch in channels]

@app.post("/api/notifications/channels")
async def create_notification_channel(channel: NotificationChannelCreate):
    """Create a new notification channel"""
    try:
        db_channel = monitor.db.add_notification_channel({
            "name": channel.name,
            "type": channel.type,
            "config": channel.config,
            "enabled": channel.enabled
        })
        return {
            "id": db_channel.id,
            "name": db_channel.name,
            "type": db_channel.type,
            "config": db_channel.config,
            "enabled": db_channel.enabled,
            "created_at": db_channel.created_at.isoformat(),
            "updated_at": db_channel.updated_at.isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to create notification channel: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/notifications/channels/{channel_id}")
async def update_notification_channel(channel_id: int, updates: NotificationChannelUpdate):
    """Update a notification channel"""
    try:
        update_data = {k: v for k, v in updates.dict().items() if v is not None}
        db_channel = monitor.db.update_notification_channel(channel_id, update_data)

        if not db_channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        return {
            "id": db_channel.id,
            "name": db_channel.name,
            "type": db_channel.type,
            "config": db_channel.config,
            "enabled": db_channel.enabled,
            "created_at": db_channel.created_at.isoformat(),
            "updated_at": db_channel.updated_at.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update notification channel: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/notifications/channels/{channel_id}")
async def delete_notification_channel(channel_id: int):
    """Delete a notification channel"""
    try:
        success = monitor.db.delete_notification_channel(channel_id)
        if not success:
            raise HTTPException(status_code=404, detail="Channel not found")
        return {"status": "success", "message": f"Channel {channel_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete notification channel: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/notifications/channels/{channel_id}/test")
async def test_notification_channel(channel_id: int):
    """Test a notification channel"""
    try:
        if not hasattr(monitor, 'notification_service'):
            raise HTTPException(status_code=503, detail="Notification service not available")

        result = await monitor.notification_service.test_channel(channel_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test notification channel: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== Event Log Routes ====================

class EventLogFilter(BaseModel):
    """Request model for filtering events"""
    category: Optional[str] = None
    event_type: Optional[str] = None
    severity: Optional[str] = None
    host_id: Optional[str] = None
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    correlation_id: Optional[str] = None
    search: Optional[str] = None
    limit: int = 100
    offset: int = 0

@app.get("/api/events")
async def get_events(category: Optional[str] = None,
                    event_type: Optional[str] = None,
                    severity: Optional[str] = None,
                    host_id: Optional[str] = None,
                    container_id: Optional[str] = None,
                    container_name: Optional[str] = None,
                    start_date: Optional[str] = None,
                    end_date: Optional[str] = None,
                    correlation_id: Optional[str] = None,
                    search: Optional[str] = None,
                    limit: int = 100,
                    offset: int = 0):
    """Get events with filtering and pagination"""
    try:
        # Parse dates
        parsed_start_date = None
        parsed_end_date = None

        if start_date:
            try:
                parsed_start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")

        if end_date:
            try:
                parsed_end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")

        events, total_count = monitor.db.get_events(
            category=category,
            event_type=event_type,
            severity=severity,
            host_id=host_id,
            container_id=container_id,
            container_name=container_name,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
            correlation_id=correlation_id,
            search=search,
            limit=limit,
            offset=offset
        )

        return {
            "events": [{
                "id": event.id,
                "correlation_id": event.correlation_id,
                "category": event.category,
                "event_type": event.event_type,
                "severity": event.severity,
                "host_id": event.host_id,
                "host_name": event.host_name,
                "container_id": event.container_id,
                "container_name": event.container_name,
                "title": event.title,
                "message": event.message,
                "old_state": event.old_state,
                "new_state": event.new_state,
                "triggered_by": event.triggered_by,
                "details": event.details,
                "duration_ms": event.duration_ms,
                "timestamp": event.timestamp.isoformat()
            } for event in events],
            "pagination": {
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total_count
            }
        }
    except Exception as e:
        logger.error(f"Failed to get events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/{event_id}")
async def get_event(event_id: int):
    """Get a specific event by ID"""
    try:
        event = monitor.db.get_event_by_id(event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")

        return {
            "id": event.id,
            "correlation_id": event.correlation_id,
            "category": event.category,
            "event_type": event.event_type,
            "severity": event.severity,
            "host_id": event.host_id,
            "host_name": event.host_name,
            "container_id": event.container_id,
            "container_name": event.container_name,
            "title": event.title,
            "message": event.message,
            "old_state": event.old_state,
            "new_state": event.new_state,
            "triggered_by": event.triggered_by,
            "details": event.details,
            "duration_ms": event.duration_ms,
            "timestamp": event.timestamp.isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get event {event_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/correlation/{correlation_id}")
async def get_events_by_correlation(correlation_id: str):
    """Get all events with the same correlation ID"""
    try:
        events = monitor.db.get_events_by_correlation(correlation_id)

        return {
            "correlation_id": correlation_id,
            "events": [{
                "id": event.id,
                "correlation_id": event.correlation_id,
                "category": event.category,
                "event_type": event.event_type,
                "severity": event.severity,
                "host_id": event.host_id,
                "host_name": event.host_name,
                "container_id": event.container_id,
                "container_name": event.container_name,
                "title": event.title,
                "message": event.message,
                "old_state": event.old_state,
                "new_state": event.new_state,
                "triggered_by": event.triggered_by,
                "details": event.details,
                "duration_ms": event.duration_ms,
                "timestamp": event.timestamp.isoformat()
            } for event in events]
        }
    except Exception as e:
        logger.error(f"Failed to get events by correlation {correlation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/statistics")
async def get_event_statistics(start_date: Optional[str] = None,
                             end_date: Optional[str] = None):
    """Get event statistics for dashboard"""
    try:
        # Parse dates
        parsed_start_date = None
        parsed_end_date = None

        if start_date:
            try:
                parsed_start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")

        if end_date:
            try:
                parsed_end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")

        stats = monitor.db.get_event_statistics(
            start_date=parsed_start_date,
            end_date=parsed_end_date
        )

        return stats
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get event statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/container/{container_id}")
async def get_container_events(container_id: str, limit: int = 50):
    """Get events for a specific container"""
    try:
        events, total_count = monitor.db.get_events(
            container_id=container_id,
            limit=limit,
            offset=0
        )

        return {
            "container_id": container_id,
            "events": [{
                "id": event.id,
                "correlation_id": event.correlation_id,
                "category": event.category,
                "event_type": event.event_type,
                "severity": event.severity,
                "host_id": event.host_id,
                "host_name": event.host_name,
                "container_id": event.container_id,
                "container_name": event.container_name,
                "title": event.title,
                "message": event.message,
                "old_state": event.old_state,
                "new_state": event.new_state,
                "triggered_by": event.triggered_by,
                "details": event.details,
                "duration_ms": event.duration_ms,
                "timestamp": event.timestamp.isoformat()
            } for event in events],
            "total_count": total_count
        }
    except Exception as e:
        logger.error(f"Failed to get events for container {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/host/{host_id}")
async def get_host_events(host_id: str, limit: int = 50):
    """Get events for a specific host"""
    try:
        events, total_count = monitor.db.get_events(
            host_id=host_id,
            limit=limit,
            offset=0
        )

        return {
            "host_id": host_id,
            "events": [{
                "id": event.id,
                "correlation_id": event.correlation_id,
                "category": event.category,
                "event_type": event.event_type,
                "severity": event.severity,
                "host_id": event.host_id,
                "host_name": event.host_name,
                "container_id": event.container_id,
                "container_name": event.container_name,
                "title": event.title,
                "message": event.message,
                "old_state": event.old_state,
                "new_state": event.new_state,
                "triggered_by": event.triggered_by,
                "details": event.details,
                "duration_ms": event.duration_ms,
                "timestamp": event.timestamp.isoformat()
            } for event in events],
            "total_count": total_count
        }
    except Exception as e:
        logger.error(f"Failed to get events for host {host_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/events/cleanup")
async def cleanup_old_events(days: int = 30):
    """Clean up old events"""
    try:
        if days < 1:
            raise HTTPException(status_code=400, detail="Days must be at least 1")

        deleted_count = monitor.db.cleanup_old_events(days)

        monitor.event_logger.log_system_event(
            "Event Cleanup Completed",
            f"Cleaned up {deleted_count} events older than {days} days",
            EventSeverity.INFO,
            EventType.STARTUP
        )

        return {
            "status": "success",
            "message": f"Cleaned up {deleted_count} events older than {days} days",
            "deleted_count": deleted_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cleanup events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await monitor.manager.connect(websocket)
    await monitor.realtime.subscribe_to_events(websocket)

    # Send initial state
    initial_state = {
        "type": "initial_state",
        "data": {
            "hosts": [h.dict() for h in monitor.hosts.values()],
            "containers": [c.dict() for c in monitor.get_containers()],
            "settings": monitor.settings.dict() if hasattr(monitor.settings, 'dict') else {},
            "alerts": [r.dict() for r in monitor.alert_rules]
        }
    }
    logger.info(f"Sending initial_state with {len(monitor.alert_rules)} alert rules via WebSocket")
    await websocket.send_text(json.dumps(initial_state, cls=DateTimeEncoder))

    try:
        while True:
            # Keep connection alive and handle incoming messages
            message = await websocket.receive_json()

            # Handle different message types
            if message.get("type") == "subscribe_stats":
                container_id = message.get("container_id")
                if container_id:
                    await monitor.realtime.subscribe_to_stats(websocket, container_id)
                    # Find the host and start monitoring
                    for host_id, client in monitor.clients.items():
                        try:
                            client.containers.get(container_id)
                            await monitor.realtime.start_container_stats_stream(
                                client, container_id, interval=2
                            )
                            break
                        except:
                            continue

            elif message.get("type") == "unsubscribe_stats":
                container_id = message.get("container_id")
                if container_id:
                    await monitor.realtime.unsubscribe_from_stats(websocket, container_id)

            elif message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}, cls=DateTimeEncoder))

    except WebSocketDisconnect:
        monitor.manager.disconnect(websocket)
        await monitor.realtime.unsubscribe_from_events(websocket)
        # Unsubscribe from all stats
        for container_id in list(monitor.realtime.stats_subscribers.keys()):
            await monitor.realtime.unsubscribe_from_stats(websocket, container_id)

# Mount static files (optional - only if directory exists)
import os
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info"
    )