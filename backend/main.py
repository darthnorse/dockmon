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
from config.settings import AppConfig, get_cors_origins, setup_logging
from models.docker_models import DockerHostConfig, DockerHost
from models.settings_models import GlobalSettings, AlertRule
from models.request_models import (
    AutoRestartRequest, AlertRuleCreate, AlertRuleUpdate,
    NotificationChannelCreate, NotificationChannelUpdate, EventLogFilter
)
from security.audit import security_audit
from security.rate_limiting import rate_limiter, rate_limit_auth, rate_limit_hosts, rate_limit_containers, rate_limit_notifications, rate_limit_default
from auth.routes import router as auth_router, verify_frontend_session
verify_session_auth = verify_frontend_session
from websocket.connection import ConnectionManager, DateTimeEncoder
from websocket.rate_limiter import ws_rate_limiter
from docker_monitor.monitor import DockerMonitor

# Configure logging
setup_logging()
logger = logging.getLogger(__name__)






# ==================== FastAPI Application ====================

# Create monitor instance
monitor = DockerMonitor()


# ==================== Authentication ====================

# Session-based authentication only - no API keys needed

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    logger.info("Starting DockMon backend...")

    # Ensure default user exists
    monitor.db.get_or_create_default_user()

    await monitor.event_logger.start()
    monitor.event_logger.log_system_event("DockMon Backend Starting", "DockMon backend is initializing", EventSeverity.INFO, EventType.STARTUP)

    # Connect security audit logger to event logger
    security_audit.set_event_logger(monitor.event_logger)
    monitor.monitoring_task = asyncio.create_task(monitor.monitor_containers())
    monitor.cleanup_task = asyncio.create_task(monitor.cleanup_old_data())

    # Start blackout window monitoring with WebSocket support
    await monitor.notification_service.blackout_manager.start_monitoring(
        monitor.notification_service,
        monitor,  # Pass DockerMonitor instance to avoid re-initialization
        monitor.manager  # Pass ConnectionManager for WebSocket broadcasts
    )
    yield
    # Shutdown
    logger.info("Shutting down DockMon backend...")
    monitor.event_logger.log_system_event("DockMon Backend Shutting Down", "DockMon backend is shutting down", EventSeverity.INFO, EventType.SHUTDOWN)
    if monitor.monitoring_task:
        monitor.monitoring_task.cancel()
    if monitor.cleanup_task:
        monitor.cleanup_task.cancel()
    # Stop blackout monitoring
    monitor.notification_service.blackout_manager.stop_monitoring()
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

# Register authentication router
app.include_router(auth_router)

@app.get("/")
async def root(authenticated: bool = Depends(verify_session_auth)):
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
async def get_hosts(authenticated: bool = Depends(verify_session_auth)):
    """Get all configured Docker hosts"""
    return list(monitor.hosts.values())

@app.post("/api/hosts")
async def add_host(config: DockerHostConfig, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_hosts, request: Request = None):
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

@app.put("/api/hosts/{host_id}")
async def update_host(host_id: str, config: DockerHostConfig, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_hosts):
    """Update an existing Docker host"""
    host = monitor.update_host(host_id, config)
    return host

@app.delete("/api/hosts/{host_id}")
async def remove_host(host_id: str, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_hosts):
    """Remove a Docker host"""
    await monitor.remove_host(host_id)

    # Broadcast host removal to WebSocket clients so they refresh
    await monitor.manager.broadcast({
        "type": "host_removed",
        "data": {"host_id": host_id}
    })

    return {"status": "success", "message": f"Host {host_id} removed"}

@app.get("/api/hosts/{host_id}/metrics")
async def get_host_metrics(host_id: str, authenticated: bool = Depends(verify_session_auth)):
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
async def get_containers(host_id: Optional[str] = None, authenticated: bool = Depends(verify_session_auth)):
    """Get all containers"""
    return await monitor.get_containers(host_id)

@app.post("/api/hosts/{host_id}/containers/{container_id}/restart")
async def restart_container(host_id: str, container_id: str, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_containers):
    """Restart a container"""
    success = monitor.restart_container(host_id, container_id)
    return {"status": "success" if success else "failed"}

@app.post("/api/hosts/{host_id}/containers/{container_id}/stop")
async def stop_container(host_id: str, container_id: str, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_containers):
    """Stop a container"""
    success = monitor.stop_container(host_id, container_id)
    return {"status": "success" if success else "failed"}

@app.post("/api/hosts/{host_id}/containers/{container_id}/start")
async def start_container(host_id: str, container_id: str, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_containers):
    """Start a container"""
    success = monitor.start_container(host_id, container_id)
    return {"status": "success" if success else "failed"}

@app.get("/api/hosts/{host_id}/containers/{container_id}/logs")
async def get_container_logs(
    host_id: str,
    container_id: str,
    tail: int = 100,
    since: Optional[str] = None,  # ISO timestamp for getting logs since a specific time
    authenticated: bool = Depends(verify_session_auth)
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
            except Exception:
                # If parsing fails, use current time
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


@app.post("/api/containers/{container_id}/auto-restart")
async def toggle_auto_restart(container_id: str, request: AutoRestartRequest, authenticated: bool = Depends(verify_session_auth)):
    """Toggle auto-restart for a container"""
    monitor.toggle_auto_restart(request.host_id, container_id, request.container_name, request.enabled)
    return {"container_id": container_id, "auto_restart": request.enabled}

@app.get("/api/rate-limit/stats")
async def get_rate_limit_stats(authenticated: bool = Depends(verify_session_auth)):
    """Get rate limiter statistics - admin only"""
    return rate_limiter.get_stats()

@app.get("/api/security/audit")
async def get_security_audit_stats(authenticated: bool = Depends(verify_session_auth), request: Request = None):
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
async def get_settings(authenticated: bool = Depends(verify_session_auth)):
    """Get global settings"""
    settings = monitor.db.get_settings()
    return {
        "max_retries": settings.max_retries,
        "retry_delay": settings.retry_delay,
        "default_auto_restart": settings.default_auto_restart,
        "polling_interval": settings.polling_interval,
        "connection_timeout": settings.connection_timeout,
        "log_retention_days": settings.log_retention_days,
        "enable_notifications": settings.enable_notifications,
        "alert_template": getattr(settings, 'alert_template', None),
        "blackout_windows": getattr(settings, 'blackout_windows', None),
        "timezone_offset": getattr(settings, 'timezone_offset', 0),
        "show_host_stats": getattr(settings, 'show_host_stats', True),
        "show_container_stats": getattr(settings, 'show_container_stats', True)
    }

@app.post("/api/settings")
async def update_settings(settings: GlobalSettings, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_default):
    """Update global settings"""
    # Check if stats settings changed
    old_show_host_stats = monitor.settings.show_host_stats
    old_show_container_stats = monitor.settings.show_container_stats

    updated = monitor.db.update_settings(settings.dict())
    monitor.settings = updated  # Update in-memory settings

    # Log stats collection changes
    if old_show_host_stats != updated.show_host_stats:
        logger.info(f"Host stats collection {'enabled' if updated.show_host_stats else 'disabled'}")
    if old_show_container_stats != updated.show_container_stats:
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

    return settings

@app.get("/api/alerts")
async def get_alert_rules(authenticated: bool = Depends(verify_session_auth)):
    """Get all alert rules"""
    rules = monitor.db.get_alert_rules(enabled_only=False)
    logger.info(f"Retrieved {len(rules)} alert rules from database")

    # Check for orphaned alerts
    orphaned = await monitor.check_orphaned_alerts()

    return [{
        "id": rule.id,
        "name": rule.name,
        "containers": [{"host_id": c.host_id, "container_name": c.container_name}
                      for c in rule.containers] if rule.containers else [],
        "trigger_events": rule.trigger_events,
        "trigger_states": rule.trigger_states,
        "notification_channels": rule.notification_channels,
        "cooldown_minutes": rule.cooldown_minutes,
        "enabled": rule.enabled,
        "last_triggered": rule.last_triggered.isoformat() if rule.last_triggered else None,
        "created_at": rule.created_at.isoformat(),
        "updated_at": rule.updated_at.isoformat(),
        "is_orphaned": rule.id in orphaned,
        "orphaned_containers": orphaned.get(rule.id, {}).get('orphaned_containers', []) if rule.id in orphaned else []
    } for rule in rules]


@app.post("/api/alerts")
async def create_alert_rule(rule: AlertRuleCreate, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_default):
    """Create a new alert rule"""
    try:
        # Validate cooldown_minutes
        if rule.cooldown_minutes < 0 or rule.cooldown_minutes > 10080:  # Max 1 week
            raise HTTPException(status_code=400, detail="Cooldown must be between 0 and 10080 minutes (1 week)")

        rule_id = str(uuid.uuid4())

        # Convert ContainerHostPair objects to dicts for database
        containers_data = None
        if rule.containers:
            containers_data = [{"host_id": c.host_id, "container_name": c.container_name}
                             for c in rule.containers]

        logger.info(f"Creating alert rule: {rule.name} with {len(containers_data) if containers_data else 0} container+host pairs")

        db_rule = monitor.db.add_alert_rule({
            "id": rule_id,
            "name": rule.name,
            "containers": containers_data,
            "trigger_events": rule.trigger_events,
            "trigger_states": rule.trigger_states,
            "notification_channels": rule.notification_channels,
            "cooldown_minutes": rule.cooldown_minutes,
            "enabled": rule.enabled
        })
        logger.info(f"Successfully created alert rule with ID: {db_rule.id}")

        # Log alert rule creation
        monitor.event_logger.log_alert_rule_created(
            rule_name=db_rule.name,
            rule_id=db_rule.id,
            container_count=len(db_rule.containers) if db_rule.containers else 0,
            channels=db_rule.notification_channels or [],
            triggered_by="user"
        )

        return {
            "id": db_rule.id,
            "name": db_rule.name,
            "containers": [{"host_id": c.host_id, "container_name": c.container_name}
                          for c in db_rule.containers] if db_rule.containers else [],
            "trigger_events": db_rule.trigger_events,
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
async def update_alert_rule(rule_id: str, updates: AlertRuleUpdate, authenticated: bool = Depends(verify_session_auth)):
    """Update an alert rule"""
    try:
        # Validate cooldown_minutes if provided
        if updates.cooldown_minutes is not None:
            if updates.cooldown_minutes < 0 or updates.cooldown_minutes > 10080:  # Max 1 week
                raise HTTPException(status_code=400, detail="Cooldown must be between 0 and 10080 minutes (1 week)")

        # Include all fields that are explicitly set, even if empty
        # This allows clearing trigger_events or trigger_states
        update_data = {}
        for k, v in updates.dict().items():
            if v is not None:
                # Convert empty lists to None for trigger fields
                if k in ['trigger_events', 'trigger_states'] and isinstance(v, list) and not v:
                    update_data[k] = None
                # Handle containers field separately
                elif k == 'containers':
                    # v is already a list of dicts after .dict() call
                    # Include it even if None to clear the containers (set to "all containers")
                    update_data[k] = v
                else:
                    update_data[k] = v
            elif k == 'containers':
                # Explicitly handle containers=None to clear specific container selection
                update_data[k] = None

        # Validate that at least one trigger type remains after update
        if 'trigger_events' in update_data or 'trigger_states' in update_data:
            # Get current rule to check what will remain
            current_rule = monitor.db.get_alert_rule(rule_id)
            if current_rule:
                final_events = update_data.get('trigger_events', current_rule.trigger_events)
                final_states = update_data.get('trigger_states', current_rule.trigger_states)

                if not final_events and not final_states:
                    raise HTTPException(status_code=400,
                        detail="Alert rule must have at least one trigger event or state")

        db_rule = monitor.db.update_alert_rule(rule_id, update_data)

        if not db_rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        # Refresh in-memory alert rules
        return {
            "id": db_rule.id,
            "name": db_rule.name,
            "containers": [{"host_id": c.host_id, "container_name": c.container_name}
                          for c in db_rule.containers] if db_rule.containers else [],
            "trigger_events": db_rule.trigger_events,
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
async def delete_alert_rule(rule_id: str, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_default):
    """Delete an alert rule"""
    try:
        # Get rule info before deleting for logging
        rule = monitor.db.get_alert_rule(rule_id)
        if not rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        rule_name = rule.name
        success = monitor.db.delete_alert_rule(rule_id)
        if not success:
            raise HTTPException(status_code=404, detail="Alert rule not found")

        # Refresh in-memory alert rules
        # Log alert rule deletion
        monitor.event_logger.log_alert_rule_deleted(
            rule_name=rule_name,
            rule_id=rule_id,
            triggered_by="user"
        )

        return {"status": "success", "message": f"Alert rule {rule_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete alert rule: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/alerts/orphaned")
async def get_orphaned_alerts(authenticated: bool = Depends(verify_session_auth)):
    """Get alert rules that reference non-existent containers"""
    try:
        orphaned = await monitor.check_orphaned_alerts()
        return {
            "count": len(orphaned),
            "orphaned_rules": orphaned
        }
    except Exception as e:
        logger.error(f"Failed to check orphaned alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== Blackout Window Routes ====================

@app.get("/api/blackout/status")
async def get_blackout_status(authenticated: bool = Depends(verify_session_auth)):
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
async def get_template_variables(authenticated: bool = Depends(verify_session_auth)):
    """Get available template variables for notification messages"""
    return {
        "variables": [
            {"name": "{CONTAINER_NAME}", "description": "Name of the container"},
            {"name": "{CONTAINER_ID}", "description": "Short container ID (12 characters)"},
            {"name": "{HOST_NAME}", "description": "Name of the Docker host"},
            {"name": "{HOST_ID}", "description": "ID of the Docker host"},
            {"name": "{OLD_STATE}", "description": "Previous state of the container"},
            {"name": "{NEW_STATE}", "description": "New state of the container"},
            {"name": "{IMAGE}", "description": "Docker image name"},
            {"name": "{TIMESTAMP}", "description": "Full timestamp (YYYY-MM-DD HH:MM:SS)"},
            {"name": "{TIME}", "description": "Time only (HH:MM:SS)"},
            {"name": "{DATE}", "description": "Date only (YYYY-MM-DD)"},
            {"name": "{RULE_NAME}", "description": "Name of the alert rule"},
            {"name": "{RULE_ID}", "description": "ID of the alert rule"},
            {"name": "{TRIGGERED_BY}", "description": "What triggered the alert"},
            {"name": "{EVENT_TYPE}", "description": "Docker event type (if applicable)"},
            {"name": "{EXIT_CODE}", "description": "Container exit code (if applicable)"}
        ],
        "default_template": """🚨 **DockMon Alert**

**Container:** `{CONTAINER_NAME}`
**Host:** {HOST_NAME}
**State Change:** `{OLD_STATE}` → `{NEW_STATE}`
**Image:** {IMAGE}
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}
───────────────────────""",
        "examples": {
            "simple": "Alert: {CONTAINER_NAME} on {HOST_NAME} changed from {OLD_STATE} to {NEW_STATE}",
            "detailed": """🔴 Container Alert
Container: {CONTAINER_NAME} ({CONTAINER_ID})
Host: {HOST_NAME}
Status: {OLD_STATE} → {NEW_STATE}
Image: {IMAGE}
Time: {TIMESTAMP}
Triggered by: {RULE_NAME}""",
            "minimal": "{CONTAINER_NAME}: {NEW_STATE} at {TIME}"
        }
    }

@app.get("/api/notifications/channels")
async def get_notification_channels(authenticated: bool = Depends(verify_session_auth)):
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
async def create_notification_channel(channel: NotificationChannelCreate, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_notifications):
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
async def update_notification_channel(channel_id: int, updates: NotificationChannelUpdate, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_notifications):
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
async def get_dependent_alerts(channel_id: int, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_notifications):
    """Get alerts that would be orphaned if this channel is deleted"""
    try:
        dependent_alerts = monitor.db.get_alerts_dependent_on_channel(channel_id)
        return {"alerts": dependent_alerts}
    except Exception as e:
        logger.error(f"Failed to get dependent alerts: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/notifications/channels/{channel_id}")
async def delete_notification_channel(channel_id: int, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_notifications):
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
async def test_notification_channel(channel_id: int, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_notifications):
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
    container_id: Optional[str] = None,
    container_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    correlation_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    hours: Optional[int] = None,
    authenticated: bool = Depends(verify_session_auth),
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
            offset=offset
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
                "timestamp": event.timestamp.isoformat()
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
    authenticated: bool = Depends(verify_session_auth),
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
    authenticated: bool = Depends(verify_session_auth),
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
                "timestamp": event.timestamp.isoformat()
            })

        return {"events": events_json, "count": len(events_json)}
    except Exception as e:
        logger.error(f"Failed to get events by correlation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== User Dashboard Routes ====================

@app.get("/api/user/dashboard-layout")
async def get_dashboard_layout(request: Request, authenticated: bool = Depends(verify_session_auth)):
    """Get dashboard layout for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    layout = monitor.db.get_dashboard_layout(username)
    return {"layout": layout}

@app.post("/api/user/dashboard-layout")
async def save_dashboard_layout(request: Request, authenticated: bool = Depends(verify_session_auth)):
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
async def get_event_sort_order(request: Request, authenticated: bool = Depends(verify_session_auth)):
    """Get event sort order preference for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    sort_order = monitor.db.get_event_sort_order(username)
    return {"sort_order": sort_order}

@app.post("/api/user/event-sort-order")
async def save_event_sort_order(request: Request, authenticated: bool = Depends(verify_session_auth)):
    """Save event sort order preference for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    try:
        body = await request.json()
        sort_order = body.get('sort_order')

        if sort_order not in ['asc', 'desc']:
            raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

        success = monitor.db.save_event_sort_order(username, sort_order)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save sort order")

        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save event sort order: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/user/container-sort-order")
async def get_container_sort_order(request: Request, authenticated: bool = Depends(verify_session_auth)):
    """Get container sort order preference for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    sort_order = monitor.db.get_container_sort_order(username)
    return {"sort_order": sort_order}

@app.post("/api/user/container-sort-order")
async def save_container_sort_order(request: Request, authenticated: bool = Depends(verify_session_auth)):
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
async def get_modal_preferences(request: Request, authenticated: bool = Depends(verify_session_auth)):
    """Get modal preferences for current user"""
    from auth.routes import _get_session_from_cookie
    from auth.session_manager import session_manager

    session_id = _get_session_from_cookie(request)
    username = session_manager.get_session_username(session_id)

    preferences = monitor.db.get_modal_preferences(username)
    return {"preferences": preferences}

@app.post("/api/user/modal-preferences")
async def save_modal_preferences(request: Request, authenticated: bool = Depends(verify_session_auth)):
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

# ==================== Event Log Routes ====================
# Note: Main /api/events endpoint is defined earlier with full feature set

@app.get("/api/events/{event_id}")
async def get_event(event_id: int, authenticated: bool = Depends(verify_session_auth)):
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
async def get_events_by_correlation(correlation_id: str, authenticated: bool = Depends(verify_session_auth)):
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
                             end_date: Optional[str] = None,
                             authenticated: bool = Depends(verify_session_auth)):
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
async def get_container_events(container_id: str, limit: int = 50, authenticated: bool = Depends(verify_session_auth)):
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
async def get_host_events(host_id: str, limit: int = 50, authenticated: bool = Depends(verify_session_auth)):
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
async def cleanup_old_events(days: int = 30, authenticated: bool = Depends(verify_session_auth)):
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
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    # Generate a unique connection ID for rate limiting
    connection_id = f"ws_{id(websocket)}_{time.time()}"

    await monitor.manager.connect(websocket)
    await monitor.realtime.subscribe_to_events(websocket)

    # Send initial state
    settings_dict = {
        "max_retries": monitor.settings.max_retries,
        "retry_delay": monitor.settings.retry_delay,
        "default_auto_restart": monitor.settings.default_auto_restart,
        "polling_interval": monitor.settings.polling_interval,
        "connection_timeout": monitor.settings.connection_timeout,
        "log_retention_days": monitor.settings.log_retention_days,
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

    try:
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
        await monitor.manager.disconnect(websocket)
        await monitor.realtime.unsubscribe_from_events(websocket)
        # Unsubscribe from all stats
        for container_id in list(monitor.realtime.stats_subscribers):
            await monitor.realtime.unsubscribe_from_stats(websocket, container_id)
        # Clear modal containers (user disconnected, modals are closed)
        monitor.stats_manager.clear_modal_containers()
        # Clean up rate limiter tracking
        ws_rate_limiter.cleanup_connection(connection_id)