#!/usr/bin/env python3
"""
DockMon Backend - Docker Container Monitoring System
Supports multiple Docker hosts with auto-restart and alerts
"""

import asyncio
import json
import logging
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    container: str
    states: List[str]
    channels: List[str]

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
                await connection.send_json(message)
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
        self.settings = GlobalSettings()
        self.alert_rules: List[AlertRule] = []
        self.notification_settings = NotificationSettings()
        self.auto_restart_status: Dict[str, bool] = {}
        self.restart_attempts: Dict[str, int] = {}
        self.monitoring_task: Optional[asyncio.Task] = None
        self.manager = ConnectionManager()
        
    def add_host(self, config: DockerHostConfig) -> DockerHost:
        """Add a new Docker host to monitor"""
        try:
            # Create Docker client
            if config.url.startswith("unix://"):
                client = docker.DockerClient(base_url=config.url)
            else:
                # For TCP connections
                tls_config = None
                if config.tls_cert and config.tls_key:
                    tls_config = docker.tls.TLSConfig(
                        client_cert=(config.tls_cert, config.tls_key),
                        ca_cert=config.tls_ca,
                        verify=True
                    )
                client = docker.DockerClient(
                    base_url=config.url,
                    tls=tls_config,
                    timeout=self.settings.connection_timeout
                )
            
            # Test connection
            client.ping()
            
            # Create host object
            host = DockerHost(
                name=config.name,
                url=config.url,
                status="online"
            )
            
            # Store client and host
            self.clients[host.id] = client
            self.hosts[host.id] = host
            
            logger.info(f"Added Docker host: {host.name} ({host.url})")
            return host
            
        except Exception as e:
            logger.error(f"Failed to add host {config.name}: {e}")
            raise HTTPException(status_code=400, detail=str(e))
    
    def remove_host(self, host_id: str):
        """Remove a Docker host"""
        if host_id in self.hosts:
            del self.hosts[host_id]
            if host_id in self.clients:
                self.clients[host_id].close()
                del self.clients[host_id]
            logger.info(f"Removed host {host_id}")
    
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
                        auto_restart=self.auto_restart_status.get(container_id, False),
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
            
        try:
            client = self.clients[host_id]
            container = client.containers.get(container_id)
            container.restart(timeout=10)
            logger.info(f"Restarted container {container_id} on host {host_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to restart container {container_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def stop_container(self, host_id: str, container_id: str) -> bool:
        """Stop a specific container"""
        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")
            
        try:
            client = self.clients[host_id]
            container = client.containers.get(container_id)
            container.stop(timeout=10)
            logger.info(f"Stopped container {container_id} on host {host_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop container {container_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def start_container(self, host_id: str, container_id: str) -> bool:
        """Start a specific container"""
        if host_id not in self.clients:
            raise HTTPException(status_code=404, detail="Host not found")
            
        try:
            client = self.clients[host_id]
            container = client.containers.get(container_id)
            container.start()
            logger.info(f"Started container {container_id} on host {host_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to start container {container_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def toggle_auto_restart(self, container_id: str, enabled: bool):
        """Toggle auto-restart for a container"""
        self.auto_restart_status[container_id] = enabled
        if not enabled:
            self.restart_attempts[container_id] = 0
        logger.info(f"Auto-restart {'enabled' if enabled else 'disabled'} for {container_id}")
    
    async def monitor_containers(self):
        """Main monitoring loop"""
        logger.info("Starting container monitoring...")
        
        while True:
            try:
                containers = self.get_containers()
                
                # Check for containers that need auto-restart
                for container in containers:
                    if (container.status == "exited" and 
                        self.auto_restart_status.get(container.short_id, False)):
                        
                        attempts = self.restart_attempts.get(container.short_id, 0)
                        if attempts < self.settings.max_retries:
                            asyncio.create_task(
                                self.auto_restart_container(container)
                            )
                
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

# ==================== FastAPI Application ====================

# Create monitor instance
monitor = DockerMonitor()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    logger.info("Starting DockMon backend...")
    monitor.monitoring_task = asyncio.create_task(monitor.monitor_containers())
    yield
    # Shutdown
    logger.info("Shutting down DockMon backend...")
    if monitor.monitoring_task:
        monitor.monitoring_task.cancel()

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
    """Serve the frontend"""
    return FileResponse("static/index.html")

@app.get("/api/hosts")
async def get_hosts():
    """Get all configured Docker hosts"""
    return list(monitor.hosts.values())

@app.post("/api/hosts")
async def add_host(config: DockerHostConfig):
    """Add a new Docker host"""
    host = monitor.add_host(config)
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

@app.post("/api/containers/{container_id}/auto-restart")
async def toggle_auto_restart(container_id: str, enabled: bool):
    """Toggle auto-restart for a container"""
    monitor.toggle_auto_restart(container_id, enabled)
    return {"container_id": container_id, "auto_restart": enabled}

@app.get("/api/settings")
async def get_settings():
    """Get global settings"""
    return monitor.settings

@app.post("/api/settings")
async def update_settings(settings: GlobalSettings):
    """Update global settings"""
    monitor.settings = settings
    return settings

@app.get("/api/alerts")
async def get_alert_rules():
    """Get all alert rules"""
    return monitor.alert_rules

@app.post("/api/alerts")
async def create_alert_rule(rule: AlertRule):
    """Create a new alert rule"""
    monitor.alert_rules.append(rule)
    return rule

@app.delete("/api/alerts/{rule_id}")
async def delete_alert_rule(rule_id: str):
    """Delete an alert rule"""
    monitor.alert_rules = [r for r in monitor.alert_rules if r.id != rule_id]
    return {"status": "success"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await monitor.manager.connect(websocket)
    
    # Send initial state
    initial_state = {
        "type": "initial_state",
        "data": {
            "hosts": [h.dict() for h in monitor.hosts.values()],
            "containers": [c.dict() for c in monitor.get_containers()],
            "settings": monitor.settings.dict(),
            "alerts": [r.dict() for r in monitor.alert_rules]
        }
    }
    await websocket.send_json(initial_state)
    
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            # Process any incoming messages if needed
    except WebSocketDisconnect:
        monitor.manager.disconnect(websocket)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info"
    )