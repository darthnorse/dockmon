#!/usr/bin/env python3
"""
DockMon Backend - Docker Container Monitoring System
Supports multiple Docker hosts with auto-restart and alerts

IMPORTANT: Container Identification
-----------------------------------
All container-related API endpoints MUST use both host_id AND container_id
to uniquely identify containers. This is because container IDs can collide
across different Docker hosts (e.g., cloned VMs, LXC containers).

URL Pattern: /api/hosts/{host_id}/containers/{container_id}/...
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

import docker
from docker import DockerClient
from docker.errors import DockerException, APIError
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends, status, Cookie, Response, Query
from fastapi.middleware.cors import CORSMiddleware
# Session-based auth - no longer need HTTPBearer
from fastapi.responses import FileResponse
from database import DatabaseManager
from realtime import RealtimeMonitor
from notifications import NotificationService, AlertProcessor
from event_logger import EventLogger, EventContext, EventCategory, EventType, EventSeverity, PerformanceTimer

# Import extracted modules
from config.settings import AppConfig, get_cors_origins, setup_logging, HealthCheckFilter
from models.docker_models import DockerHostConfig, DockerHost
from models.settings_models import GlobalSettings, AlertRule, AlertRuleV2Create, AlertRuleV2Update
from models.request_models import (
    AutoRestartRequest, DesiredStateRequest, AlertRuleCreate, AlertRuleUpdate,
    NotificationChannelCreate, NotificationChannelUpdate, EventLogFilter, BatchJobCreate, ContainerTagUpdate, HostTagUpdate
)
from security.audit import security_audit
from security.rate_limiting import rate_limiter, rate_limit_auth, rate_limit_hosts, rate_limit_containers, rate_limit_notifications, rate_limit_default
from auth.routes import router as auth_router, verify_frontend_session
from auth.v2_routes import get_current_user  # v2 cookie-based auth
verify_session_auth = verify_frontend_session  # Keep v1 for backward compat
from websocket.connection import ConnectionManager, DateTimeEncoder
from websocket.rate_limiter import ws_rate_limiter
from docker_monitor.monitor import DockerMonitor
from batch_manager import BatchJobManager

# Configure logging
setup_logging()
logger = logging.getLogger(__name__)






# ==================== FastAPI Application ====================

# Create monitor instance
monitor = DockerMonitor()

# Global instances (initialized in lifespan)
batch_manager: Optional[BatchJobManager] = None


# ==================== Authentication ====================

# Session-based authentication only - no API keys needed

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    logger.info("Starting DockMon backend...")

    # Reapply health check filter to uvicorn access logger (must be done after uvicorn starts)
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.addFilter(HealthCheckFilter())

    # Ensure default user exists
    monitor.db.get_or_create_default_user()

    # Note: Timezone offset is auto-synced from the browser when the UI loads
    # This ensures timestamps are always displayed in the user's local timezone

    await monitor.event_logger.start()
    monitor.event_logger.log_system_event("DockMon Backend Starting", "DockMon backend is initializing", EventSeverity.INFO, EventType.STARTUP)

    # Connect security audit logger to event logger
    security_audit.set_event_logger(monitor.event_logger)
    monitor.monitoring_task = asyncio.create_task(monitor.monitor_containers())
    monitor.maintenance_task = asyncio.create_task(monitor.run_daily_maintenance())

    # Start blackout window monitoring with WebSocket support
    await monitor.notification_service.blackout_manager.start_monitoring(
        monitor.notification_service,
        monitor,  # Pass DockerMonitor instance to avoid re-initialization
        monitor.manager  # Pass ConnectionManager for WebSocket broadcasts
    )

    # Initialize batch job manager
    global batch_manager
    batch_manager = BatchJobManager(monitor.db, monitor, monitor.manager)
    logger.info("Batch job manager initialized")

    # Initialize alert evaluation service
    from alerts.evaluation_service import AlertEvaluationService
    from stats_client import get_stats_client
    global alert_evaluation_service
    alert_evaluation_service = AlertEvaluationService(
        db=monitor.db,
        monitor=monitor,  # Pass monitor for container lookups
        stats_client=get_stats_client(),
        event_logger=monitor.event_logger,
        notification_service=monitor.notification_service,
        evaluation_interval=10  # Evaluate every 10 seconds
    )
    # Attach to monitor for event handling
    monitor.alert_evaluation_service = alert_evaluation_service
    await alert_evaluation_service.start()
    logger.info("Alert evaluation service started")

    yield
    # Shutdown
    logger.info("Shutting down DockMon backend...")
    monitor.event_logger.log_system_event("DockMon Backend Shutting Down", "DockMon backend is shutting down", EventSeverity.INFO, EventType.SHUTDOWN)
    if monitor.monitoring_task:
        monitor.monitoring_task.cancel()
    if monitor.maintenance_task:
        monitor.maintenance_task.cancel()
    # Stop blackout monitoring
    monitor.notification_service.blackout_manager.stop_monitoring()
    # Stop alert evaluation service
    if 'alert_evaluation_service' in globals():
        await alert_evaluation_service.stop()
        logger.info("Alert evaluation service stopped")
    # Close stats client (HTTP session and WebSocket)
    from stats_client import get_stats_client
    await get_stats_client().close()
    # Close notification service
    await monitor.notification_service.close()
    # Stop event logger
    await monitor.event_logger.stop()
    # Dispose SQLAlchemy engine
    monitor.db.engine.dispose()
    logger.info("SQLAlchemy engine disposed")

app = FastAPI(
    title="DockMon API",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS - Production ready with environment-based configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=AppConfig.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

logger.info(f"CORS configured for origins: {AppConfig.CORS_ORIGINS}")

# ==================== API Routes ====================

# Register authentication routers
app.include_router(auth_router)  # v1 auth (existing)

# Register v2 API routers
from auth.v2_routes import router as auth_v2_router
from api.v2.user import router as user_v2_router
# NOTE: alerts_router is registered AFTER v2 rules routes are defined below (around line 1060)
# This is to ensure v2 /api/alerts/rules routes take precedence over the /api/alerts/ router

app.include_router(auth_v2_router)  # v2 cookie-based auth
app.include_router(user_v2_router)  # v2 user preferences
# app.include_router(alerts_router)  # MOVED: Registered after v2 rules routes

@app.get("/")
async def root(current_user: dict = Depends(get_current_user)):
    """Backend API root - frontend is served separately"""
    return {"message": "DockMon Backend API", "version": "1.0.0", "docs": "/docs"}

@app.get("/health")
async def health_check():
    """Health check endpoint for Docker health checks - no authentication required"""
    return {"status": "healthy", "service": "dockmon-backend"}

def _is_localhost_or_internal(ip: str) -> bool:
    """Check if IP is localhost or internal network (Docker networks, private networks)"""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)

        # Allow localhost
        if addr.is_loopback:
            return True

        # Allow private networks (RFC 1918) - for Docker networks and internal deployments
        if addr.is_private:
            return True

        return False
    except ValueError:
        # Invalid IP format
        return False


# ==================== Frontend Authentication ====================

async def verify_session_auth(request: Request):
    """Verify authentication via session cookie only"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    # Since backend only listens on 127.0.0.1, all requests must come through nginx
    # No need to check client IP - the backend binding ensures security

    # Check session authentication
    session_id = _get_session_from_cookie(request)
    if session_id and session_manager.validate_session(session_id, request):
        return True

    # No valid session found
    raise HTTPException(
        status_code=401,
        detail="Authentication required - please login"
    )



@app.get("/api/hosts")
async def get_hosts(current_user: dict = Depends(get_current_user)):
    """Get all configured Docker hosts"""
    return list(monitor.hosts.values())

@app.post("/api/hosts")
async def add_host(config: DockerHostConfig, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_hosts, request: Request = None):
    """Add a new Docker host"""
    try:
        host = monitor.add_host(config)

        # Security audit log - successful privileged action
        if request:
            security_audit.log_privileged_action(
                client_ip=request.client.host if hasattr(request, 'client') else "unknown",
                action="ADD_DOCKER_HOST",
                target=f"{config.name} ({config.url})",
                success=True,
                user_agent=request.headers.get('user-agent', 'unknown')
            )

        # Broadcast host addition to WebSocket clients so they refresh
        await monitor.manager.broadcast({
            "type": "host_added",
            "data": {"host_id": host.id, "host_name": host.name}
        })

        return host
    except Exception as e:
        # Security audit log - failed privileged action
        if request:
            security_audit.log_privileged_action(
                client_ip=request.client.host if hasattr(request, 'client') else "unknown",
                action="ADD_DOCKER_HOST",
                target=f"{config.name} ({config.url})",
                success=False,
                user_agent=request.headers.get('user-agent', 'unknown')
            )
        raise

@app.post("/api/hosts/test-connection")
async def test_host_connection(config: DockerHostConfig, current_user: dict = Depends(get_current_user)):
    """Test connection to a Docker host without adding it

    For existing hosts with mTLS, if certs are null, we'll retrieve them from the database.
    """
    import tempfile
    import os
    import shutil

    temp_dir = None

    try:
        logger.info(f"Testing connection to {config.url}")

        # Check if this is an existing host (by matching URL)
        # If certs are null, try to load from database
        if (config.tls_ca is None or config.tls_cert is None or config.tls_key is None):
            # Try to find existing host by URL to get certificates
            from database import DockerHostDB
            db_session = monitor.db.get_session()
            try:
                existing_host = db_session.query(DockerHostDB).filter(DockerHostDB.url == config.url).first()
                if existing_host:
                    logger.info(f"Found existing host for URL {config.url}, using stored certificates")
                    if config.tls_ca is None and existing_host.tls_ca:
                        config.tls_ca = existing_host.tls_ca
                    if config.tls_cert is None and existing_host.tls_cert:
                        config.tls_cert = existing_host.tls_cert
                    if config.tls_key is None and existing_host.tls_key:
                        config.tls_key = existing_host.tls_key
            finally:
                db_session.close()

        # Build Docker client kwargs
        kwargs = {}

        # Handle TLS/mTLS certificates
        if config.tls_ca or config.tls_cert or config.tls_key:
            # Create temp directory for certificates
            temp_dir = tempfile.mkdtemp()
            tls_config = {}

            # Write certificates to temp files
            if config.tls_ca:
                ca_path = os.path.join(temp_dir, 'ca.pem')
                with open(ca_path, 'w') as f:
                    f.write(config.tls_ca)
                tls_config['ca_cert'] = ca_path

            if config.tls_cert:
                cert_path = os.path.join(temp_dir, 'cert.pem')
                with open(cert_path, 'w') as f:
                    f.write(config.tls_cert)
                tls_config['client_cert'] = (cert_path,)

            if config.tls_key:
                key_path = os.path.join(temp_dir, 'key.pem')
                with open(key_path, 'w') as f:
                    f.write(config.tls_key)
                # Add key to cert tuple
                if 'client_cert' in tls_config:
                    tls_config['client_cert'] = (tls_config['client_cert'][0], key_path)

            # Create TLS config
            tls = docker.tls.TLSConfig(
                verify=tls_config.get('ca_cert'),
                client_cert=tls_config.get('client_cert')
            )
            kwargs['tls'] = tls

        # Create Docker client
        client = docker.DockerClient(base_url=config.url, **kwargs)

        try:
            # Test connection by pinging
            info = client.ping()

            # Get some basic info
            version_info = client.version()

            logger.info(f"Connection test successful for {config.url}")
            return {
                "success": True,
                "message": "Connection successful",
                "docker_version": version_info.get('Version', 'unknown'),
                "api_version": version_info.get('ApiVersion', 'unknown')
            }
        finally:
            # Close client
            client.close()

            # Clean up temp files
            if temp_dir:
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    # Silently ignore cleanup errors
                    pass

    except Exception as e:
        # Clean up temp files on error too
        if temp_dir:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                # Silently ignore cleanup errors
                pass

        logger.error(f"Connection test failed for {config.url}: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Connection failed: {str(e)}")

@app.put("/api/hosts/{host_id}")
async def update_host(host_id: str, config: DockerHostConfig, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_hosts):
    """Update an existing Docker host"""
    host = monitor.update_host(host_id, config)
    return host

@app.delete("/api/hosts/{host_id}")
async def remove_host(host_id: str, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_hosts):
    """Remove a Docker host"""
    try:
        await monitor.remove_host(host_id)

        # Broadcast host removal to WebSocket clients so they refresh
        await monitor.manager.broadcast({
            "type": "host_removed",
            "data": {"host_id": host_id}
        })

        return {"status": "success", "message": f"Host {host_id} removed"}
    except ValueError as e:
        # Host not found or invalid host_id format
        logger.warning(f"Failed to remove host {host_id}: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # Unexpected error during removal
        logger.error(f"Error removing host {host_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to remove host: {str(e)}")

@app.patch("/api/hosts/{host_id}/tags")
async def update_host_tags(
    host_id: str,
    request: HostTagUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update tags for a host

    Add or remove custom tags for organizing hosts (e.g., 'prod', 'dev', 'us-west-1').
    Host tags are separate from container tags and used for filtering/grouping hosts.
    """
    # Get host from monitor
    host = monitor.hosts.get(host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")

    # Update tags using normalized schema
    updated_tags = monitor.db.update_subject_tags(
        'host',
        host_id,
        request.tags_to_add,
        request.tags_to_remove,
        host_id_at_attach=host_id,
        container_name_at_attach=host.name  # Use host name for logging
    )

    # Update in-memory host object so changes are immediately visible
    host.tags = updated_tags

    logger.info(f"User {current_user.get('username')} updated tags for host {host.name}")

    return {"tags": updated_tags}

@app.get("/api/hosts/{host_id}/metrics")
async def get_host_metrics(host_id: str, current_user: dict = Depends(get_current_user)):
    """Get aggregated metrics for a Docker host (CPU, RAM, Network)"""
    try:
        host = monitor.hosts.get(host_id)
        if not host:
            raise HTTPException(status_code=404, detail="Host not found")

        client = monitor.clients.get(host_id)
        if not client:
            raise HTTPException(status_code=503, detail="Host client not available")

        # Get all running containers on this host
        containers = client.containers.list(filters={'status': 'running'})

        total_cpu = 0.0
        total_memory_used = 0
        total_memory_limit = 0
        total_net_rx = 0
        total_net_tx = 0
        container_count = 0

        for container in containers:
            try:
                stats = container.stats(stream=False)

                # Calculate CPU percentage
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                           stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                              stats['precpu_stats']['system_cpu_usage']

                if system_delta > 0:
                    num_cpus = len(stats['cpu_stats']['cpu_usage'].get('percpu_usage', [1]))
                    cpu_percent = (cpu_delta / system_delta) * num_cpus * 100.0
                    total_cpu += cpu_percent

                # Memory
                mem_usage = stats['memory_stats'].get('usage', 0)
                mem_limit = stats['memory_stats'].get('limit', 1)
                total_memory_used += mem_usage
                total_memory_limit += mem_limit

                # Network I/O
                networks = stats.get('networks', {})
                for net_stats in networks.values():
                    total_net_rx += net_stats.get('rx_bytes', 0)
                    total_net_tx += net_stats.get('tx_bytes', 0)

                container_count += 1

            except Exception as e:
                logger.warning(f"Failed to get stats for container {container.id}: {e}")
                continue

        # Calculate percentages
        avg_cpu = round(total_cpu / container_count, 1) if container_count > 0 else 0.0
        memory_percent = round((total_memory_used / total_memory_limit) * 100, 1) if total_memory_limit > 0 else 0.0

        return {
            "cpu_percent": avg_cpu,
            "memory_percent": memory_percent,
            "memory_used_bytes": total_memory_used,
            "memory_limit_bytes": total_memory_limit,
            "network_rx_bytes": total_net_rx,
            "network_tx_bytes": total_net_tx,
            "container_count": container_count,
            "timestamp": int(time.time())
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching metrics for host {host_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/containers")
async def get_containers(host_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    """Get all containers"""
    return await monitor.get_containers(host_id)

@app.post("/api/hosts/{host_id}/containers/{container_id}/restart")
async def restart_container(host_id: str, container_id: str, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_containers):
    """Restart a container"""
    success = monitor.restart_container(host_id, container_id)
    return {"status": "success" if success else "failed"}

@app.post("/api/hosts/{host_id}/containers/{container_id}/stop")
async def stop_container(host_id: str, container_id: str, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_containers):
    """Stop a container"""
    success = monitor.stop_container(host_id, container_id)
    return {"status": "success" if success else "failed"}

@app.post("/api/hosts/{host_id}/containers/{container_id}/start")
async def start_container(host_id: str, container_id: str, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_containers):
    """Start a container"""
    success = monitor.start_container(host_id, container_id)
    return {"status": "success" if success else "failed"}

@app.get("/api/hosts/{host_id}/containers/{container_id}/logs")
async def get_container_logs(
    host_id: str,
    container_id: str,
    tail: int = 100,
    since: Optional[str] = None,  # ISO timestamp for getting logs since a specific time
    current_user: dict = Depends(get_current_user)
    # No rate limiting - authenticated users can poll logs freely
):
    """Get container logs - Portainer-style polling approach"""
    if host_id not in monitor.clients:
        raise HTTPException(status_code=404, detail="Host not found")

    try:
        client = monitor.clients[host_id]

        # Run blocking Docker calls in executor with timeout
        loop = asyncio.get_event_loop()

        # Get container with timeout
        try:
            container = await asyncio.wait_for(
                loop.run_in_executor(None, client.containers.get, container_id),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Timeout getting container")

        # Prepare log options
        log_kwargs = {
            'timestamps': True,
            'tail': tail
        }

        # Add since parameter if provided (for getting only new logs)
        if since:
            try:
                # Parse ISO timestamp and convert to Unix timestamp for Docker
                import dateutil.parser
                dt = dateutil.parser.parse(since)
                # Docker's 'since' expects Unix timestamp as float
                import time
                unix_ts = time.mktime(dt.timetuple())
                log_kwargs['since'] = unix_ts
                log_kwargs['tail'] = 'all'  # Get all logs since timestamp
            except Exception as e:
                logger.debug(f"Could not parse 'since' parameter: {e}")
                pass  # Invalid timestamp, ignore

        # Fetch logs with timeout
        try:
            logs = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: container.logs(**log_kwargs).decode('utf-8', errors='ignore')
                ),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Timeout fetching logs")

        # Parse logs and extract timestamps
        # Docker log format with timestamps: "2025-09-30T19:30:45.123456789Z actual log message"
        parsed_logs = []
        for line in logs.split('\n'):
            if not line.strip():
                continue

            # Try to extract timestamp (Docker format: ISO8601 with nanoseconds)
            try:
                # Find the space after timestamp
                space_idx = line.find(' ')
                if space_idx > 0:
                    timestamp_str = line[:space_idx]
                    log_text = line[space_idx + 1:]

                    # Parse timestamp (remove nanoseconds for Python datetime)
                    # Format: 2025-09-30T19:30:45.123456789Z -> 2025-09-30T19:30:45.123456Z
                    if 'T' in timestamp_str and timestamp_str.endswith('Z'):
                        # Truncate to microseconds (6 digits) if nanoseconds present
                        parts = timestamp_str[:-1].split('.')
                        if len(parts) == 2 and len(parts[1]) > 6:
                            timestamp_str = f"{parts[0]}.{parts[1][:6]}Z"

                        parsed_logs.append({
                            "timestamp": timestamp_str,
                            "log": log_text
                        })
                    else:
                        # No valid timestamp, use current time
                        parsed_logs.append({
                            "timestamp": datetime.utcnow().isoformat() + 'Z',
                            "log": line
                        })
                else:
                    # No space found, treat whole line as log
                    parsed_logs.append({
                        "timestamp": datetime.utcnow().isoformat() + 'Z',
                        "log": line
                    })
            except (ValueError, IndexError, AttributeError) as e:
                # If timestamp parsing fails, use current time
                logger.debug(f"Failed to parse log timestamp: {e}")
                parsed_logs.append({
                    "timestamp": datetime.utcnow().isoformat() + 'Z',
                    "log": line
                })

        return {
            "container_id": container_id,
            "logs": parsed_logs,
            "last_timestamp": datetime.utcnow().isoformat() + 'Z'  # For next 'since' parameter
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get logs for {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Container exec endpoint removed for security reasons
# Users should use direct SSH, Docker CLI, or other appropriate tools for container access


# WebSocket log streaming removed in favor of HTTP polling (Portainer-style)
# This is more reliable for remote Docker hosts


@app.post("/api/hosts/{host_id}/containers/{container_id}/auto-restart")
async def toggle_auto_restart(host_id: str, container_id: str, request: AutoRestartRequest, current_user: dict = Depends(get_current_user)):
    """Toggle auto-restart for a container"""
    # Normalize to short ID (12 chars) for consistency with monitor's internal tracking
    short_id = container_id[:12] if len(container_id) > 12 else container_id
    monitor.toggle_auto_restart(host_id, short_id, request.container_name, request.enabled)
    return {"host_id": host_id, "container_id": container_id, "auto_restart": request.enabled}

@app.post("/api/hosts/{host_id}/containers/{container_id}/desired-state")
async def set_desired_state(host_id: str, container_id: str, request: DesiredStateRequest, current_user: dict = Depends(get_current_user)):
    """Set desired state for a container"""
    # Normalize to short ID (12 chars) for consistency
    short_id = container_id[:12] if len(container_id) > 12 else container_id
    monitor.set_container_desired_state(host_id, short_id, request.container_name, request.desired_state)
    return {"host_id": host_id, "container_id": container_id, "desired_state": request.desired_state}

@app.patch("/api/hosts/{host_id}/containers/{container_id}/tags")
async def update_container_tags(
    host_id: str,
    container_id: str,
    request: ContainerTagUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update tags for a container

    Add or remove custom tags. Tags are stored in DockMon's database and merged with
    tags derived from Docker labels (compose:project, swarm:service).
    """
    # Get container name from monitor
    containers = await monitor.get_containers()
    container = next((c for c in containers if c.id == container_id and c.host_id == host_id), None)

    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    result = monitor.update_container_tags(
        host_id,
        container_id,
        container.name,
        request.tags_to_add,
        request.tags_to_remove
    )

    logger.info(f"User {current_user.get('username')} updated tags for container {container.name}")

    return result

@app.get("/api/tags/suggest")
async def suggest_tags(
    q: str = "",
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """
    Get container tag suggestions for autocomplete

    Returns a list of existing container tags that match the query string.
    Used by the bulk tag management UI for containers.
    """
    tags = monitor.db.get_all_tags_v2(query=q, limit=limit, subject_type="container")
    return {"tags": tags}

@app.get("/api/hosts/tags/suggest")
async def suggest_host_tags(
    q: str = "",
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """
    Get host tag suggestions for autocomplete

    Returns a list of existing host tags that match the query string.
    """
    tags = monitor.db.get_all_tags_v2(query=q, limit=limit, subject_type="host")
    return {"tags": tags}


# ==================== Batch Operations ====================

@app.post("/api/batch", status_code=201)
async def create_batch_job(request: BatchJobCreate, current_user: dict = Depends(get_current_user)):
    """
    Create a batch job for bulk operations on containers

    Currently supports: start, stop, restart
    """
    if not batch_manager:
        raise HTTPException(status_code=500, detail="Batch manager not initialized")

    try:
        job_id = await batch_manager.create_job(
            user_id=current_user.get('id'),
            scope=request.scope,
            action=request.action,
            container_ids=request.ids,
            params=request.params
        )

        logger.info(f"User {current_user.get('username')} created batch job {job_id}: {request.action} on {len(request.ids)} containers")

        return {"job_id": job_id}
    except Exception as e:
        logger.error(f"Error creating batch job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/batch/{job_id}")
async def get_batch_job(job_id: str, current_user: dict = Depends(get_current_user)):
    """Get status and results of a batch job"""
    if not batch_manager:
        raise HTTPException(status_code=500, detail="Batch manager not initialized")

    job_status = batch_manager.get_job_status(job_id)

    if not job_status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return job_status

@app.get("/api/rate-limit/stats")
async def get_rate_limit_stats(current_user: dict = Depends(get_current_user)):
    """Get rate limiter statistics - admin only"""
    return rate_limiter.get_stats()

@app.get("/api/security/audit")
async def get_security_audit_stats(current_user: dict = Depends(get_current_user), request: Request = None):
    """Get security audit statistics - admin only"""
    if request:
        security_audit.log_privileged_action(
            client_ip=request.client.host if hasattr(request, 'client') else "unknown",
            action="VIEW_SECURITY_AUDIT",
            target="security_audit_logs",
            success=True,
            user_agent=request.headers.get('user-agent', 'unknown')
        )
    return security_audit.get_security_stats()

@app.get("/api/settings")
async def get_settings(current_user: dict = Depends(get_current_user)):
    """Get global settings"""
    settings = monitor.db.get_settings()
    return {
        "max_retries": settings.max_retries,
        "retry_delay": settings.retry_delay,
        "default_auto_restart": settings.default_auto_restart,
        "polling_interval": settings.polling_interval,
        "connection_timeout": settings.connection_timeout,
        "enable_notifications": settings.enable_notifications,
        "alert_template": getattr(settings, 'alert_template', None),
        "alert_template_metric": getattr(settings, 'alert_template_metric', None),
        "alert_template_state_change": getattr(settings, 'alert_template_state_change', None),
        "alert_template_health": getattr(settings, 'alert_template_health', None),
        "blackout_windows": getattr(settings, 'blackout_windows', None),
        "timezone_offset": getattr(settings, 'timezone_offset', 0),
        "show_host_stats": getattr(settings, 'show_host_stats', True),
        "show_container_stats": getattr(settings, 'show_container_stats', True),
        "unused_tag_retention_days": getattr(settings, 'unused_tag_retention_days', 30),
        "event_retention_days": getattr(settings, 'event_retention_days', 60)
    }

@app.post("/api/settings")
@app.put("/api/settings")
async def update_settings(settings: dict, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_default):
    """Update global settings (partial updates supported)"""
    # Check if stats settings changed
    old_show_host_stats = monitor.settings.show_host_stats
    old_show_container_stats = monitor.settings.show_container_stats

    updated = monitor.db.update_settings(settings)
    monitor.settings = updated  # Update in-memory settings

    # Log stats collection changes
    if 'show_host_stats' in settings and old_show_host_stats != updated.show_host_stats:
        logger.info(f"Host stats collection {'enabled' if updated.show_host_stats else 'disabled'}")
    if 'show_container_stats' in settings and old_show_container_stats != updated.show_container_stats:
        logger.info(f"Container stats collection {'enabled' if updated.show_container_stats else 'disabled'}")

    # Broadcast blackout status change to all clients
    is_blackout, window_name = monitor.notification_service.blackout_manager.is_in_blackout_window()
    await monitor.manager.broadcast({
        'type': 'blackout_status_changed',
        'data': {
            'is_blackout': is_blackout,
            'window_name': window_name
        }
    })

    # Return the updated settings from database (not the input dict)
    return {
        "max_retries": updated.max_retries,
        "retry_delay": updated.retry_delay,
        "default_auto_restart": updated.default_auto_restart,
        "polling_interval": updated.polling_interval,
        "connection_timeout": updated.connection_timeout,
        "enable_notifications": updated.enable_notifications,
        "alert_template": getattr(updated, 'alert_template', None),
        "alert_template_metric": getattr(updated, 'alert_template_metric', None),
        "alert_template_state_change": getattr(updated, 'alert_template_state_change', None),
        "alert_template_health": getattr(updated, 'alert_template_health', None),
        "blackout_windows": getattr(updated, 'blackout_windows', None),
        "timezone_offset": getattr(updated, 'timezone_offset', 0),
        "show_host_stats": getattr(updated, 'show_host_stats', True),
        "show_container_stats": getattr(updated, 'show_container_stats', True),
        "unused_tag_retention_days": getattr(updated, 'unused_tag_retention_days', 30),
        "event_retention_days": getattr(updated, 'event_retention_days', 60)
    }


# ==================== Alert Rules V2 Routes ====================
# IMPORTANT: These routes must be defined BEFORE the alerts_router is registered
# Otherwise FastAPI will match /api/alerts/ before /api/alerts/rules

@app.get("/api/alerts/rules")
async def get_alert_rules_v2(current_user: dict = Depends(get_current_user)):
    """Get all alert rules (v2)"""
    from models.settings_models import AlertRuleV2Create

    rules = monitor.db.get_alert_rules_v2()
    return {
        "rules": [{
            "id": rule.id,
            "name": rule.name,
            "description": rule.description,
            "scope": rule.scope,
            "kind": rule.kind,
            "enabled": rule.enabled,
            "severity": rule.severity,
            "metric": rule.metric,
            "threshold": rule.threshold,
            "operator": rule.operator,
            "duration_seconds": rule.duration_seconds,
            "occurrences": rule.occurrences,
            "clear_threshold": rule.clear_threshold,
            "clear_duration_seconds": rule.clear_duration_seconds,
            "cooldown_seconds": rule.cooldown_seconds,
            "host_selector_json": rule.host_selector_json,
            "container_selector_json": rule.container_selector_json,
            "labels_json": rule.labels_json,
            "notify_channels_json": rule.notify_channels_json,
            "created_at": rule.created_at.isoformat() + 'Z',
            "updated_at": rule.updated_at.isoformat() + 'Z',
            "version": rule.version,
        } for rule in rules],
        "total": len(rules)
    }


@app.post("/api/alerts/rules")
async def create_alert_rule_v2(
    rule: AlertRuleV2Create,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default
):
    """Create a new alert rule (v2)"""
    from models.settings_models import AlertRuleV2Create

    try:
        new_rule = monitor.db.create_alert_rule_v2(
            name=rule.name,
            description=rule.description,
            scope=rule.scope,
            kind=rule.kind,
            enabled=rule.enabled,
            severity=rule.severity,
            metric=rule.metric,
            threshold=rule.threshold,
            operator=rule.operator,
            duration_seconds=rule.duration_seconds,
            occurrences=rule.occurrences,
            clear_threshold=rule.clear_threshold,
            clear_duration_seconds=rule.clear_duration_seconds,
            cooldown_seconds=rule.cooldown_seconds,
            host_selector_json=rule.host_selector_json,
            container_selector_json=rule.container_selector_json,
            labels_json=rule.labels_json,
            notify_channels_json=rule.notify_channels_json,
            created_by=current_user.get("username", "unknown"),
        )

        logger.info(f"Created alert rule v2: {new_rule.name} (ID: {new_rule.id})")

        # Log event
        channels = []
        if new_rule.notify_channels_json:
            try:
                import json
                channels = json.loads(new_rule.notify_channels_json)
            except:
                channels = []

        monitor.event_logger.log_alert_rule_created(
            rule_name=new_rule.name,
            rule_id=new_rule.id,
            container_count=0,  # v2 rules use selectors, not direct container count
            channels=channels if isinstance(channels, list) else [],
            triggered_by=current_user.get("username", "user")
        )

        return {
            "id": new_rule.id,
            "name": new_rule.name,
            "description": new_rule.description,
            "scope": new_rule.scope,
            "kind": new_rule.kind,
            "enabled": new_rule.enabled,
            "severity": new_rule.severity,
            "created_at": new_rule.created_at.isoformat() + 'Z',
        }
    except Exception as e:
        logger.error(f"Failed to create alert rule v2: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/alerts/rules/{rule_id}")
async def update_alert_rule_v2(
    rule_id: str,
    updates: AlertRuleV2Update,
    current_user: dict = Depends(get_current_user)
):
    """Update an alert rule (v2)"""
    from models.settings_models import AlertRuleV2Update

    try:
        # Build update dict with only provided fields
        # exclude_unset=True means only fields explicitly set are included
        # We don't filter out None/0/False because those are valid values (e.g., cooldown_seconds=0)
        update_data = updates.dict(exclude_unset=True)

        # Track who updated the rule
        update_data['updated_by'] = current_user.get("username", "unknown")

        updated_rule = monitor.db.update_alert_rule_v2(rule_id, **update_data)

        if not updated_rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        logger.info(f"Updated alert rule v2: {rule_id}")

        return {
            "id": updated_rule.id,
            "name": updated_rule.name,
            "updated_at": updated_rule.updated_at.isoformat() + 'Z',
            "version": updated_rule.version,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update alert rule v2: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/alerts/rules/{rule_id}")
async def delete_alert_rule_v2(
    rule_id: str,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default
):
    """Delete an alert rule (v2)"""
    try:
        # Get rule info before deleting for event logging
        rule = monitor.db.get_alert_rule_v2(rule_id)

        success = monitor.db.delete_alert_rule_v2(rule_id)

        if not success:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        logger.info(f"Deleted alert rule v2: {rule_id}")

        # Log event
        if rule:
            monitor.event_logger.log_alert_rule_deleted(
                rule_name=rule.name,
                rule_id=rule.id,
                triggered_by=current_user.get("username", "user")
            )

        return {"success": True, "message": "Alert rule deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete alert rule v2: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/api/alerts/rules/{rule_id}/toggle")
async def toggle_alert_rule_v2(
    rule_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Toggle an alert rule enabled/disabled state (v2)"""
    try:
        rule = monitor.db.get_alert_rule_v2(rule_id)

        if not rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        new_enabled = not rule.enabled
        updated_rule = monitor.db.update_alert_rule_v2(rule_id, enabled=new_enabled)

        logger.info(f"Toggled alert rule v2: {rule_id} to {new_enabled}")

        return {
            "id": updated_rule.id,
            "enabled": updated_rule.enabled,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to toggle alert rule v2: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Register Alerts Router (AFTER v2 rules routes) ====================
# The alerts_router must be registered AFTER the v2 alert rules routes above
# so that FastAPI matches /api/alerts/rules before /api/alerts/
from alerts.api import router as alerts_router
app.include_router(alerts_router)  # Alert instances (not rules - rules are defined above)


# ==================== Blackout Window Routes ====================

@app.get("/api/blackout/status")
async def get_blackout_status(current_user: dict = Depends(get_current_user)):
    """Get current blackout window status"""
    try:
        is_blackout, window_name = monitor.notification_service.blackout_manager.is_in_blackout_window()
        return {
            "is_blackout": is_blackout,
            "current_window": window_name
        }
    except Exception as e:
        logger.error(f"Error getting blackout status: {e}")
        return {"is_blackout": False, "current_window": None}

# ==================== Notification Channel Routes ====================


@app.get("/api/notifications/template-variables")
async def get_template_variables(current_user: dict = Depends(get_current_user)):
    """Get available template variables for notification messages"""
    return {
        "variables": [
            # Basic entity info
            {"name": "{CONTAINER_NAME}", "description": "Name of the container"},
            {"name": "{CONTAINER_ID}", "description": "Short container ID (12 characters)"},
            {"name": "{HOST_NAME}", "description": "Name of the Docker host"},
            {"name": "{HOST_ID}", "description": "ID of the Docker host"},
            {"name": "{IMAGE}", "description": "Docker image name"},

            # State changes (event-driven alerts)
            {"name": "{OLD_STATE}", "description": "Previous state of the container"},
            {"name": "{NEW_STATE}", "description": "New state of the container"},
            {"name": "{EVENT_TYPE}", "description": "Docker event type (if applicable)"},
            {"name": "{EXIT_CODE}", "description": "Container exit code (if applicable)"},

            # Metrics (metric-driven alerts)
            {"name": "{CURRENT_VALUE}", "description": "Current metric value (e.g., 92.5 for CPU)"},
            {"name": "{THRESHOLD}", "description": "Threshold that was breached (e.g., 90)"},
            {"name": "{KIND}", "description": "Alert kind (cpu_high, memory_high, unhealthy, etc.)"},
            {"name": "{SEVERITY}", "description": "Alert severity (info, warning, critical)"},
            {"name": "{SCOPE_TYPE}", "description": "Alert scope (host, container, group)"},

            # Temporal info
            {"name": "{TIMESTAMP}", "description": "Full timestamp (YYYY-MM-DD HH:MM:SS)"},
            {"name": "{TIME}", "description": "Time only (HH:MM:SS)"},
            {"name": "{DATE}", "description": "Date only (YYYY-MM-DD)"},
            {"name": "{FIRST_SEEN}", "description": "When alert first triggered"},
            {"name": "{OCCURRENCES}", "description": "Number of times this alert has fired"},

            # Rule context
            {"name": "{RULE_NAME}", "description": "Name of the alert rule"},
            {"name": "{RULE_ID}", "description": "ID of the alert rule"},
            {"name": "{TRIGGERED_BY}", "description": "What triggered the alert"},

            # Tags/Labels
            {"name": "{LABELS}", "description": "Container/host labels as JSON (env=prod, app=web, etc.)"},
        ],
        "default_template": """🚨 **{SEVERITY} Alert: {KIND}**

**{SCOPE_TYPE}:** `{CONTAINER_NAME}`
**Host:** {HOST_NAME}
**Current Value:** {CURRENT_VALUE} (threshold: {THRESHOLD})
**Occurrences:** {OCCURRENCES}
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}
───────────────────────""",
        "examples": {
            "simple": "Alert: {CONTAINER_NAME} on {HOST_NAME} - {KIND} ({SEVERITY})",
            "metric_based": """⚠️ **Metric Alert**
{SCOPE_TYPE}: {CONTAINER_NAME}
Metric: {KIND}
Current: {CURRENT_VALUE} | Threshold: {THRESHOLD}
Severity: {SEVERITY}
First seen: {FIRST_SEEN} | Occurrences: {OCCURRENCES}""",
            "state_change": """🔴 **State Change Alert**
Container: {CONTAINER_NAME} ({CONTAINER_ID})
Host: {HOST_NAME}
Status: {OLD_STATE} → {NEW_STATE}
Image: {IMAGE}
Time: {TIMESTAMP}
Rule: {RULE_NAME}""",
            "minimal": "{CONTAINER_NAME}: {KIND} at {TIME}"
        }
    }

@app.get("/api/notifications/channels")
async def get_notification_channels(current_user: dict = Depends(get_current_user)):
    """Get all notification channels"""
    channels = monitor.db.get_notification_channels(enabled_only=False)
    return [{
        "id": ch.id,
        "name": ch.name,
        "type": ch.type,
        "config": ch.config,
        "enabled": ch.enabled,
        "created_at": ch.created_at.isoformat() + 'Z',
        "updated_at": ch.updated_at.isoformat() + 'Z'
    } for ch in channels]

@app.post("/api/notifications/channels")
async def create_notification_channel(channel: NotificationChannelCreate, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_notifications):
    """Create a new notification channel"""
    try:
        db_channel = monitor.db.add_notification_channel({
            "name": channel.name,
            "type": channel.type,
            "config": channel.config,
            "enabled": channel.enabled
        })

        # Log notification channel creation
        monitor.event_logger.log_notification_channel_created(
            channel_name=db_channel.name,
            channel_type=db_channel.type,
            triggered_by="user"
        )

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
async def update_notification_channel(channel_id: int, updates: NotificationChannelUpdate, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_notifications):
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

@app.get("/api/notifications/channels/{channel_id}/dependent-alerts")
async def get_dependent_alerts(channel_id: int, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_notifications):
    """Get alerts that would be orphaned if this channel is deleted"""
    try:
        dependent_alerts = monitor.db.get_alerts_dependent_on_channel(channel_id)
        return {"alerts": dependent_alerts}
    except Exception as e:
        logger.error(f"Failed to get dependent alerts: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/notifications/channels/{channel_id}")
async def delete_notification_channel(channel_id: int, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_notifications):
    """Delete a notification channel and cascade delete alerts that would become orphaned"""
    try:
        # Find alerts that would be orphaned (only have this channel)
        affected_alerts = monitor.db.get_alerts_dependent_on_channel(channel_id)

        # Find all alerts that use this channel (for removal from multi-channel alerts)
        all_alerts = monitor.db.get_alert_rules()

        # Delete the channel
        success = monitor.db.delete_notification_channel(channel_id)
        if not success:
            raise HTTPException(status_code=404, detail="Channel not found")

        # Delete orphaned alerts
        deleted_alerts = []
        for alert in affected_alerts:
            if monitor.db.delete_alert_rule(alert['id']):
                deleted_alerts.append(alert['name'])

        # Remove channel from multi-channel alerts
        updated_alerts = []
        for alert in all_alerts:
            # Skip if already deleted
            if alert.id in [a['id'] for a in affected_alerts]:
                continue

            # Check if this alert uses the deleted channel
            channels = alert.notification_channels if isinstance(alert.notification_channels, list) else []
            if channel_id in channels:
                # Remove the channel
                new_channels = [ch for ch in channels if ch != channel_id]
                monitor.db.update_alert_rule(alert.id, {'notification_channels': new_channels})
                updated_alerts.append(alert.name)

        result = {
            "status": "success",
            "message": f"Channel {channel_id} deleted"
        }

        if deleted_alerts:
            result["deleted_alerts"] = deleted_alerts
            result["message"] += f" and {len(deleted_alerts)} orphaned alert(s) removed"

        if updated_alerts:
            result["updated_alerts"] = updated_alerts
            if "deleted_alerts" in result:
                result["message"] += f", {len(updated_alerts)} alert(s) updated"
            else:
                result["message"] += f" and {len(updated_alerts)} alert(s) updated"

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete notification channel: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/notifications/channels/{channel_id}/test")
async def test_notification_channel(channel_id: int, current_user: dict = Depends(get_current_user), rate_limit_check: bool = rate_limit_notifications):
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

@app.get("/api/events")
async def get_events(
    category: Optional[List[str]] = Query(None),
    event_type: Optional[str] = None,
    severity: Optional[List[str]] = Query(None),
    host_id: Optional[List[str]] = Query(None),
    container_id: Optional[List[str]] = Query(None),
    container_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    correlation_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    hours: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default
):
    """
    Get events with filtering and pagination

    Query parameters:
    - category: Filter by category (container, host, system, alert, notification)
    - event_type: Filter by event type (state_change, action_taken, etc.)
    - severity: Filter by severity (debug, info, warning, error, critical)
    - host_id: Filter by specific host
    - container_id: Filter by specific container
    - container_name: Filter by container name (partial match)
    - start_date: Filter events after this date (ISO 8601 format)
    - end_date: Filter events before this date (ISO 8601 format)
    - hours: Shortcut to get events from last X hours (overrides start_date)
    - correlation_id: Get related events
    - search: Search in title, message, and container name
    - limit: Number of results per page (default 100, max 500)
    - offset: Pagination offset
    """
    try:
        # Validate and parse dates
        start_datetime = None
        end_datetime = None

        # If hours parameter is provided, calculate start_date
        if hours is not None:
            start_datetime = datetime.now() - timedelta(hours=hours)
        elif start_date:
            try:
                start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use ISO 8601 format.")

        if end_date:
            try:
                end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use ISO 8601 format.")

        # Limit maximum results per page
        if limit > 500:
            limit = 500

        # Get user's sort order preference
        username = current_user.get('username')
        sort_order = monitor.db.get_event_sort_order(username) if username else 'desc'
        logger.info(f"Getting events for user {username}, sort_order: {sort_order}")

        # Query events from database
        events, total_count = monitor.db.get_events(
            category=category,
            event_type=event_type,
            severity=severity,
            host_id=host_id,
            container_id=container_id,
            container_name=container_name,
            start_date=start_datetime,
            end_date=end_datetime,
            correlation_id=correlation_id,
            search=search,
            limit=limit,
            offset=offset,
            sort_order=sort_order
        )

        # Convert to JSON-serializable format
        events_json = []
        for event in events:
            events_json.append({
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
                "timestamp": event.timestamp.isoformat() + 'Z'
            })

        return {
            "events": events_json,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/{event_id}")
async def get_event_by_id(
    event_id: int,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default
):
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
        logger.error(f"Failed to get event: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/correlation/{correlation_id}")
async def get_events_by_correlation(
    correlation_id: str,
    current_user: dict = Depends(get_current_user),
    rate_limit_check: bool = rate_limit_default
):
    """Get all events with the same correlation ID (related events)"""
    try:
        events = monitor.db.get_events_by_correlation(correlation_id)

        events_json = []
        for event in events:
            events_json.append({
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
                "timestamp": event.timestamp.isoformat() + 'Z'
            })

        return {"events": events_json, "count": len(events_json)}
    except Exception as e:
        logger.error(f"Failed to get events by correlation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== User Dashboard Routes ====================

@app.get("/api/user/dashboard-layout")
async def get_dashboard_layout(request: Request, current_user: dict = Depends(get_current_user)):
    """Get dashboard layout for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    layout = monitor.db.get_dashboard_layout(username)
    return {"layout": layout}

@app.post("/api/user/dashboard-layout")
async def save_dashboard_layout(request: Request, current_user: dict = Depends(get_current_user)):
    """Save dashboard layout for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    try:
        body = await request.json()
        layout_json = body.get('layout')

        if layout_json is None:
            raise HTTPException(status_code=400, detail="Layout is required")

        # Validate JSON structure
        if layout_json:
            try:
                parsed_layout = json.loads(layout_json) if isinstance(layout_json, str) else layout_json

                # Validate it's a list
                if not isinstance(parsed_layout, list):
                    raise HTTPException(status_code=400, detail="Layout must be an array of widget positions")

                # Validate each widget has required fields
                required_fields = ['x', 'y', 'w', 'h']
                for widget in parsed_layout:
                    if not isinstance(widget, dict):
                        raise HTTPException(status_code=400, detail="Each widget must be an object")
                    for field in required_fields:
                        if field not in widget:
                            raise HTTPException(status_code=400, detail=f"Widget missing required field: {field}")
                        if not isinstance(widget[field], (int, float)):
                            raise HTTPException(status_code=400, detail=f"Widget field '{field}' must be a number")

                # Convert back to string for storage
                layout_json = json.dumps(parsed_layout)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON format for layout")

        success = monitor.db.save_dashboard_layout(username, layout_json)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save layout")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save dashboard layout: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/user/event-sort-order")
async def get_event_sort_order(request: Request, current_user: dict = Depends(get_current_user)):
    """Get event sort order preference for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    sort_order = monitor.db.get_event_sort_order(username)
    return {"sort_order": sort_order}

@app.post("/api/user/event-sort-order")
async def save_event_sort_order(request: Request, current_user: dict = Depends(get_current_user)):
    """Save event sort order preference for current user"""
    try:
        # Get username from current_user (already authenticated)
        username = current_user.get('username')
        if not username:
            raise HTTPException(status_code=401, detail="User not authenticated")

        body = await request.json()
        sort_order = body.get('sort_order')
        logger.info(f"Saving sort_order for {username}: {sort_order}")

        if sort_order not in ['asc', 'desc']:
            raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

        success = monitor.db.save_event_sort_order(username, sort_order)
        logger.info(f"Save result: {success}")
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save sort order")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save event sort order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/user/container-sort-order")
async def get_container_sort_order(request: Request, current_user: dict = Depends(get_current_user)):
    """Get container sort order preference for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    sort_order = monitor.db.get_container_sort_order(username)
    return {"sort_order": sort_order}

@app.post("/api/user/container-sort-order")
async def save_container_sort_order(request: Request, current_user: dict = Depends(get_current_user)):
    """Save container sort order preference for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    try:
        body = await request.json()
        sort_order = body.get('sort_order')

        valid_sorts = ['name-asc', 'name-desc', 'status', 'memory-desc', 'memory-asc', 'cpu-desc', 'cpu-asc']
        if sort_order not in valid_sorts:
            raise HTTPException(status_code=400, detail=f"sort_order must be one of: {', '.join(valid_sorts)}")

        success = monitor.db.save_container_sort_order(username, sort_order)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save sort order")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save container sort order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/user/modal-preferences")
async def get_modal_preferences(request: Request, current_user: dict = Depends(get_current_user)):
    """Get modal preferences for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    preferences = monitor.db.get_modal_preferences(username)
    return {"preferences": preferences}

@app.post("/api/user/modal-preferences")
async def save_modal_preferences(request: Request, current_user: dict = Depends(get_current_user)):
    """Save modal preferences for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    try:
        body = await request.json()
        preferences = body.get('preferences')

        if preferences is None:
            raise HTTPException(status_code=400, detail="Preferences are required")

        success = monitor.db.save_modal_preferences(username, preferences)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save preferences")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save modal preferences: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== Phase 4: View Mode Preference ====================

@app.get("/api/user/view-mode")
async def get_view_mode(request: Request, current_user: dict = Depends(get_current_user)):
    """Get dashboard view mode preference for current user"""
    # Get username directly from current_user dependency
    username = current_user.get('username')

    if not username:
        return {"view_mode": "compact"}  # Default if no username

    try:
        session = monitor.db.get_session()
        try:
            from database import User
            user = session.query(User).filter(User.username == username).first()
            if user:
                return {"view_mode": user.view_mode or "compact"}  # Default to compact
            return {"view_mode": "compact"}
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Failed to get view mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/user/view-mode")
async def save_view_mode(request: Request, current_user: dict = Depends(get_current_user)):
    """Save dashboard view mode preference for current user"""
    # Get username directly from current_user dependency
    username = current_user.get('username')

    if not username:
        logger.error(f"No username in current_user: {current_user}")
        raise HTTPException(status_code=401, detail="Username not found in session")

    try:
        body = await request.json()
        view_mode = body.get('view_mode')

        if view_mode not in ['compact', 'standard', 'expanded']:
            raise HTTPException(status_code=400, detail="Invalid view_mode. Must be 'compact', 'standard', or 'expanded'")

        session = monitor.db.get_session()
        try:
            from database import User
            from datetime import datetime

            user = session.query(User).filter(User.username == username).first()
            if user:
                user.view_mode = view_mode
                user.updated_at = datetime.now()
                session.commit()
                return {"success": True}

            raise HTTPException(status_code=404, detail="User not found")
        finally:
            session.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save view mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== Phase 4c: Dashboard Hosts with Stats ====================

@app.get("/api/dashboard/hosts")
async def get_dashboard_hosts(
    group_by: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    alerts: Optional[bool] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Get hosts with aggregated stats for dashboard view

    Returns hosts grouped by tag (if group_by specified) with:
    - Current stats (CPU, Memory, Network)
    - Sparkline data (last 30-40 data points)
    - Top 3 containers by CPU
    - Container count, alerts, updates
    """
    try:
        # Get all hosts
        hosts_list = list(monitor.hosts.values())

        # Filter by status if specified
        if status:
            hosts_list = [h for h in hosts_list if h.status == status]

        # Get containers for all hosts
        all_containers = await monitor.get_containers()

        # Build host data with stats
        host_data = []
        for host in hosts_list:
            # Filter containers for this host
            host_containers = [c for c in all_containers if c.host_id == host.id]
            running_containers = [c for c in host_containers if c.status == 'running']

            # Get top 3 containers by CPU
            top_containers = sorted(
                [c for c in running_containers if c.cpu_percent is not None],
                key=lambda x: x.cpu_percent or 0,
                reverse=True
            )[:3]

            # Calculate aggregate stats from containers
            total_cpu = sum(c.cpu_percent or 0 for c in running_containers)
            total_mem_used = sum(c.memory_usage or 0 for c in running_containers) / (1024 * 1024 * 1024)  # Convert to GB

            # Get real sparkline data from stats history buffer (Phase 4c)
            # Uses EMA smoothing (α = 0.3) and maintains 60-90s of history
            sparklines = monitor.stats_history.get_sparklines(host.id, num_points=30)

            # Calculate current memory percent (TODO: Get actual host total memory from stats service)
            mem_percent = (total_mem_used / 16 * 100) if running_containers else 0

            # Parse tags
            tags = []
            if host.tags:
                try:
                    tags = json.loads(host.tags) if isinstance(host.tags, str) else host.tags
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    logger.warning(f"Failed to parse tags for host {host.id}: {e}")
                    tags = []

            # Apply search filter
            if search:
                search_lower = search.lower()
                if not (search_lower in host.name.lower() or
                       search_lower in host.url.lower() or
                       any(search_lower in tag.lower() for tag in tags)):
                    continue

            host_data.append({
                "id": host.id,
                "name": host.name,
                "url": host.url,
                "status": host.status,
                "tags": tags,
                "stats": {
                    "cpu_percent": round(sparklines["cpu"][-1] if sparklines["cpu"] else total_cpu, 1),
                    "mem_percent": round(sparklines["mem"][-1] if sparklines["mem"] else mem_percent, 1),
                    "mem_used_gb": round(total_mem_used, 1),
                    "mem_total_gb": 16.0,  # TODO: Get from host metrics
                    "net_bytes_per_sec": int(sparklines["net"][-1]) if sparklines["net"] else 0
                },
                "sparklines": sparklines,
                "containers": {
                    "total": len(host_containers),
                    "running": len(running_containers),
                    "stopped": len(host_containers) - len(running_containers),
                    "top": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "state": c.status,
                            "cpu_percent": round(c.cpu_percent or 0, 1)
                        }
                        for c in top_containers
                    ]
                },
                "alerts": {
                    "open": 0,  # TODO: Get from alert rules
                    "snoozed": 0
                },
                "updates_available": 0  # TODO: Implement update detection
            })

        # Group hosts if group_by is specified
        if group_by and group_by in ['env', 'region', 'datacenter', 'compose.project']:
            groups = {}
            ungrouped = []

            for host in host_data:
                # Find matching tag
                group_value = None
                for tag in host.get('tags', []):
                    if ':' in tag:
                        key, value = tag.split(':', 1)
                        if key == group_by or (group_by == 'compose.project' and key == 'compose' and tag.startswith('compose:')):
                            group_value = value
                            break
                    elif group_by == tag:  # Simple tag without value
                        group_value = tag
                        break

                if group_value:
                    if group_value not in groups:
                        groups[group_value] = []
                    groups[group_value].append(host)
                else:
                    ungrouped.append(host)

            # Add ungrouped hosts
            if ungrouped:
                groups["(ungrouped)"] = ungrouped

            return {
                "groups": groups,
                "group_by": group_by,
                "total_hosts": len(host_data)
            }
        else:
            # No grouping - return all in single group
            return {
                "groups": {"All Hosts": host_data},
                "group_by": None,
                "total_hosts": len(host_data)
            }

    except Exception as e:
        logger.error(f"Failed to get dashboard hosts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ==================== Event Log Routes ====================
# Note: Main /api/events endpoints are defined earlier (lines 1185-1367) with full feature set
# including rate limiting. Additional event endpoints below:

@app.get("/api/events/statistics")
async def get_event_statistics(start_date: Optional[str] = None,
                             end_date: Optional[str] = None,
                             current_user: dict = Depends(get_current_user)):
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

@app.get("/api/hosts/{host_id}/events/container/{container_id}")
async def get_container_events(host_id: str, container_id: str, limit: int = 50, current_user: dict = Depends(get_current_user)):
    """Get events for a specific container"""
    try:
        events, total_count = monitor.db.get_events(
            host_id=host_id,
            container_id=container_id,
            limit=limit,
            offset=0
        )

        return {
            "host_id": host_id,
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
                "timestamp": event.timestamp.isoformat() + 'Z'
            } for event in events],
            "total_count": total_count
        }
    except Exception as e:
        logger.error(f"Failed to get events for container {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events/host/{host_id}")
async def get_host_events(host_id: str, limit: int = 50, current_user: dict = Depends(get_current_user)):
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
                "timestamp": event.timestamp.isoformat() + 'Z'
            } for event in events],
            "total_count": total_count
        }
    except Exception as e:
        logger.error(f"Failed to get events for host {host_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/events/cleanup")
async def cleanup_old_events(days: int = 30, current_user: dict = Depends(get_current_user)):
    """Clean up old events - DANGEROUS: Can delete audit logs"""
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
@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket, session_id: Optional[str] = Cookie(None)):
    """WebSocket endpoint for real-time updates with authentication"""
    # Generate a unique connection ID for rate limiting
    connection_id = f"ws_{id(websocket)}_{time.time()}"

    # Authenticate before accepting connection
    if not session_id:
        logger.warning("WebSocket connection attempted without session cookie")
        await websocket.close(code=1008, reason="Authentication required")
        return

    # Validate session using v2 auth
    from auth.cookie_sessions import cookie_session_manager
    client_ip = websocket.client.host if websocket.client else "unknown"
    session_data = cookie_session_manager.validate_session(session_id, client_ip)

    if not session_data:
        logger.warning(f"WebSocket connection with invalid session from {client_ip}")
        await websocket.close(code=1008, reason="Invalid or expired session")
        return

    logger.info(f"WebSocket authenticated for user: {session_data.get('username')}")

    try:
        # Accept connection and subscribe to events
        await monitor.manager.connect(websocket)
        await monitor.realtime.subscribe_to_events(websocket)

        # Send initial state
        settings_dict = {
            "max_retries": monitor.settings.max_retries,
            "retry_delay": monitor.settings.retry_delay,
            "default_auto_restart": monitor.settings.default_auto_restart,
            "polling_interval": monitor.settings.polling_interval,
            "connection_timeout": monitor.settings.connection_timeout,
            "enable_notifications": monitor.settings.enable_notifications,
            "alert_template": getattr(monitor.settings, 'alert_template', None),
            "blackout_windows": getattr(monitor.settings, 'blackout_windows', None),
            "timezone_offset": getattr(monitor.settings, 'timezone_offset', 0),
            "show_host_stats": getattr(monitor.settings, 'show_host_stats', True),
            "show_container_stats": getattr(monitor.settings, 'show_container_stats', True)
        }

        initial_state = {
            "type": "initial_state",
            "data": {
                "hosts": [h.dict() for h in monitor.hosts.values()],
                "containers": [c.dict() for c in await monitor.get_containers()],
                "settings": settings_dict
            }
        }
        await websocket.send_text(json.dumps(initial_state, cls=DateTimeEncoder))

        while True:
            # Keep connection alive and handle incoming messages
            message = await websocket.receive_json()

            # Check rate limit for incoming messages
            allowed, reason = ws_rate_limiter.check_rate_limit(connection_id)
            if not allowed:
                # Send rate limit error to client
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "error": "rate_limit",
                    "message": reason
                }))
                # Don't process the message
                continue

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
                        except Exception as e:
                            logger.debug(f"Container {container_id} not found on host {host_id[:8]}: {e}")
                            continue

            elif message.get("type") == "unsubscribe_stats":
                container_id = message.get("container_id")
                if container_id:
                    await monitor.realtime.unsubscribe_from_stats(websocket, container_id)

            elif message.get("type") == "modal_opened":
                # Track that a container modal is open - keep stats running for this container
                container_id = message.get("container_id")
                host_id = message.get("host_id")
                if container_id and host_id:
                    # Verify container exists and user has access to it
                    try:
                        containers = await monitor.get_containers()  # Must await async function
                        container_exists = any(
                            c.id == container_id and c.host_id == host_id
                            for c in containers
                        )
                        if container_exists:
                            monitor.stats_manager.add_modal_container(container_id, host_id)
                        else:
                            logger.warning(f"User attempted to access stats for non-existent container: {container_id[:12]} on host {host_id[:8]}")
                    except Exception as e:
                        logger.error(f"Error validating container access: {e}")

            elif message.get("type") == "modal_closed":
                # Remove container from modal tracking
                container_id = message.get("container_id")
                host_id = message.get("host_id")
                if container_id and host_id:
                    monitor.stats_manager.remove_modal_container(container_id, host_id)

            elif message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}, cls=DateTimeEncoder))

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {connection_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {connection_id}: {e}", exc_info=True)
    finally:
        # Always cleanup, regardless of how we exited
        await monitor.manager.disconnect(websocket)
        await monitor.realtime.unsubscribe_from_events(websocket)
        # Unsubscribe from all stats
        for container_id in list(monitor.realtime.stats_subscribers):
            await monitor.realtime.unsubscribe_from_stats(websocket, container_id)
        # Clear modal containers (user disconnected, modals are closed)
        monitor.stats_manager.clear_modal_containers()
        # Clean up rate limiter tracking
        ws_rate_limiter.cleanup_connection(connection_id)
        logger.debug(f"WebSocket cleanup completed for {connection_id}")