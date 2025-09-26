#!/usr/bin/env python3
"""
DockMon Backend - Docker Container Monitoring System
Supports multiple Docker hosts with auto-restart and alerts
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

import docker
import uvicorn
from docker import DockerClient
from docker.errors import DockerException, APIError
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends, status, Cookie, Response
from fastapi.middleware.cors import CORSMiddleware
# Session-based auth - no longer need HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import DatabaseManager
from realtime import RealtimeMonitor, LiveUpdateManager
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
from websocket.connection import ConnectionManager, DateTimeEncoder
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
async def root():
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
    monitor.remove_host(host_id)
    return {"status": "success", "message": f"Host {host_id} removed"}

@app.get("/api/containers")
async def get_containers(host_id: Optional[str] = None, authenticated: bool = Depends(verify_session_auth)):
    """Get all containers"""
    return monitor.get_containers(host_id)

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
    authenticated: bool = Depends(verify_session_auth),
    rate_limit_check: bool = rate_limit_containers
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

        # Return logs as array of lines
        log_lines = [line for line in logs.split('\n') if line.strip()]

        return {
            "container_id": container_id,
            "logs": log_lines,
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
        "enable_notifications": settings.enable_notifications
    }

@app.post("/api/settings")
async def update_settings(settings: GlobalSettings, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_default):
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
        "containers": [{"host_id": c.host_id, "container_name": c.container_name}
                      for c in rule.containers] if rule.containers else [],
        "trigger_events": rule.trigger_events,
        "trigger_states": rule.trigger_states,
        "notification_channels": rule.notification_channels,
        "cooldown_minutes": rule.cooldown_minutes,
        "enabled": rule.enabled,
        "last_triggered": rule.last_triggered.isoformat() if rule.last_triggered else None,
        "created_at": rule.created_at.isoformat(),
        "updated_at": rule.updated_at.isoformat()
    } for rule in rules]


@app.post("/api/alerts")
async def create_alert_rule(rule: AlertRuleCreate, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_default):
    """Create a new alert rule"""
    try:
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

        # Refresh in-memory alert rules
        monitor.refresh_alert_rules()

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
        # Include all fields that are explicitly set, even if empty
        # This allows clearing trigger_events or trigger_states
        update_data = {}
        for k, v in updates.dict().items():
            if v is not None:
                # Convert empty lists to None for trigger fields
                if k in ['trigger_events', 'trigger_states'] and isinstance(v, list) and len(v) == 0:
                    update_data[k] = None
                # Handle containers field separately
                elif k == 'containers' and v is not None:
                    # v is already a list of dicts after .dict() call
                    update_data[k] = v
                else:
                    update_data[k] = v

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
        monitor.refresh_alert_rules()

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
async def create_notification_channel(channel: NotificationChannelCreate, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_notifications):
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

@app.delete("/api/notifications/channels/{channel_id}")
async def delete_notification_channel(channel_id: int, authenticated: bool = Depends(verify_session_auth), rate_limit_check: bool = rate_limit_notifications):
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
    import os
    # Disable reload in production/container environment
    reload_enabled = os.getenv("DEV_MODE", "false").lower() == "true"

    uvicorn.run(
        "main:app",
        host="0.0.0.0",  # Accept connections from any interface
        port=8080,
        reload=reload_enabled,
        log_level="info"
    )