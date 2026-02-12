"""
Agent WebSocket Handler for DockMon v2.2.0

Handles WebSocket connections from DockMon agents.

Protocol Flow:
1. Agent connects to /api/agent/ws
2. Agent sends authentication message (register or reconnect)
3. Backend validates and responds with success/error
4. Bidirectional message exchange (commands from backend, events from agent)
5. Agent disconnects (gracefully or due to error)

Message Types:
- Agent → Backend: register, reconnect, stats, progress, error, heartbeat
- Backend → Agent: auth_success, auth_error, collect_stats, update_container, self_update
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from agent.manager import AgentManager
from agent.connection_manager import agent_connection_manager
from agent.command_executor import get_agent_command_executor
from agent.models import AgentRegistrationRequest
from database import (
    Agent,
    ContainerHttpHealthCheck,
    ContainerUpdate,
    DatabaseManager,
)
from event_bus import Event, EventType, get_event_bus
from event_logger import EventCategory, EventType as LogEventType, EventSeverity, EventContext
from utils.keys import make_composite_key

logger = logging.getLogger(__name__)


class AgentWebSocketHandler:
    """Handles WebSocket connections from agents"""

    def __init__(self, websocket: WebSocket, monitor=None):
        """
        Initialize handler.

        Args:
            websocket: FastAPI WebSocket connection
            monitor: DockerMonitor instance (for EventBus, WebSocket broadcast, stats)
        """
        self.websocket = websocket
        self.monitor = monitor
        # Track previous network readings for rate calculation (key: container_key, value: {rx, tx, timestamp})
        self.prev_network_stats = {}
        self.agent_manager = AgentManager(monitor=monitor)  # Pass monitor for host registration
        self.db_manager = DatabaseManager()  # For heartbeat updates
        self.agent_id: Optional[str] = None
        self.agent_hostname: Optional[str] = None  # For event logging
        self.host_id: Optional[str] = None  # For mapping agent to host
        self.authenticated = False

    def _truncate_container_id(self, container_id: Optional[str]) -> str:
        """
        Truncate container ID to 12 characters (short ID format).

        Agent sends full 64-char Docker IDs, but DockMon uses 12-char short IDs
        consistently throughout the codebase for composite keys and database storage.

        Args:
            container_id: Container ID (12 or 64 characters)

        Returns:
            Short container ID (12 characters) or empty string if invalid
        """
        if not container_id:
            return ""
        return container_id[:12] if len(container_id) > 12 else container_id

    async def handle_connection(self):
        """
        Handle complete WebSocket connection lifecycle.

        - Accept connection
        - Authenticate agent (register or reconnect)
        - Process messages until disconnect
        - Clean up on disconnect
        """
        try:
            # Accept WebSocket connection
            await self.websocket.accept()
            logger.info("Agent WebSocket connection accepted, awaiting authentication")

            # Wait for authentication message (30 second timeout)
            auth_message = await asyncio.wait_for(
                self.websocket.receive_json(),
                timeout=30.0
            )

            # Authenticate
            auth_result = await self.authenticate(auth_message)
            if not auth_result["success"]:
                logger.warning(
                    f"Agent authentication failed: {auth_result.get('error')} "
                    f"(hostname: {auth_message.get('hostname', 'unknown')}, "
                    f"engine_id: {auth_message.get('engine_id', 'unknown')[:12] if auth_message.get('engine_id') else 'unknown'})"
                )
                await self.websocket.send_json({
                    "type": "auth_error",
                    "error": auth_result.get("error", "Authentication failed")
                })
                await self.websocket.close(code=1008, reason="Authentication failed")
                return

            # Store agent details for event logging
            self.host_id = auth_result.get("host_id")
            self.agent_hostname = auth_message.get("hostname") or self.agent_id

            # Send success response
            await self.websocket.send_json({
                "type": "auth_success",
                "agent_id": self.agent_id,
                "host_id": self.host_id,
                "permanent_token": auth_result.get("permanent_token")
            })

            # Register connection
            await agent_connection_manager.register_connection(
                self.agent_id,
                self.websocket
            )

            logger.info(f"Agent {self.agent_id} authenticated successfully")

            # Sync health check configs to agent
            await self._sync_health_check_configs()

            # Emit HOST_CONNECTED event via EventBus
            if self.monitor and self.host_id:
                try:
                    event = Event(
                        event_type=EventType.HOST_CONNECTED,
                        scope_type='host',
                        scope_id=self.host_id,
                        scope_name=self.agent_hostname or self.agent_id,
                        host_id=self.host_id,
                        host_name=self.agent_hostname or self.agent_id,
                        data={"url": "agent://", "agent_id": self.agent_id}
                    )
                    await get_event_bus(self.monitor).emit(event)
                    logger.debug(f"Emitted HOST_CONNECTED event for agent {self.agent_id}")
                except Exception as e:
                    logger.warning(f"Failed to emit HOST_CONNECTED event: {e}")

            # Message processing loop
            await self.message_loop()

        except asyncio.TimeoutError:
            logger.warning("Agent authentication timeout")
            try:
                await self.websocket.send_json({
                    "type": "auth_error",
                    "error": "Authentication timeout"
                })
                await self.websocket.close(code=1008, reason="Authentication timeout")
            except:
                pass

        except WebSocketDisconnect:
            logger.info(f"Agent {self.agent_id or 'unknown'} disconnected")

        except Exception as e:
            logger.error(f"Error in agent WebSocket handler: {e}", exc_info=True)
            try:
                await self.websocket.close(code=1011, reason="Internal error")
            except:
                pass

        finally:
            # Emit HOST_DISCONNECTED event via EventBus (before cleanup)
            if self.monitor and self.host_id and self.authenticated:
                try:
                    event = Event(
                        event_type=EventType.HOST_DISCONNECTED,
                        scope_type='host',
                        scope_id=self.host_id,
                        scope_name=self.agent_hostname or self.agent_id,
                        host_id=self.host_id,
                        host_name=self.agent_hostname or self.agent_id,
                        data={"error": "Agent disconnected", "agent_id": self.agent_id}
                    )
                    await get_event_bus(self.monitor).emit(event)
                    logger.debug(f"Emitted HOST_DISCONNECTED event for agent {self.agent_id}")
                except Exception as e:
                    logger.warning(f"Failed to emit HOST_DISCONNECTED event: {e}")

            # Close any shell sessions for this agent
            if self.agent_id:
                try:
                    from agent.shell_manager import get_shell_manager
                    await get_shell_manager().close_sessions_for_agent(self.agent_id)
                except Exception as e:
                    logger.warning(f"Error closing shell sessions for agent: {e}")

            # Clean up connection
            if self.agent_id:
                await agent_connection_manager.unregister_connection(
                    self.agent_id
                )

    async def authenticate(self, message: dict) -> dict:
        """
        Authenticate agent via registration or reconnection.

        Args:
            message: Authentication message from agent

        Returns:
            dict: {"success": bool, "agent_id": str, "host_id": str} or {"success": False, "error": str}
        """
        msg_type = message.get("type")

        if msg_type == "register":
            # New agent registration with token
            try:
                # Validate registration data (prevents XSS, type confusion, DoS)
                validated_data = AgentRegistrationRequest(**message)

                # Pass validated data to registration manager
                result = self.agent_manager.register_agent(validated_data.model_dump())

                if result["success"]:
                    self.agent_id = result["agent_id"]
                    self.authenticated = True

                    # Broadcast migration notification if this was a migration
                    if result.get("migration_detected") and self.monitor:
                        old_host_id = result["migrated_from"]["host_id"]
                        old_host_name = result["migrated_from"]["host_name"]
                        new_host_name = validated_data.hostname

                        try:
                            await self.monitor.manager.broadcast({
                                "type": "host_migrated",
                                "data": {
                                    "old_host_id": old_host_id,
                                    "old_host_name": old_host_name,
                                    "new_host_id": result["host_id"],
                                    "new_host_name": new_host_name
                                }
                            })
                            logger.info(f"Broadcast migration notification: {old_host_name} → {new_host_name}")
                        except Exception as e:
                            logger.error(f"Failed to broadcast migration notification: {e}")

                        # Clean up old host from monitor's in-memory state and Go services
                        # Database record is preserved (marked inactive) for audit trail
                        try:
                            # Remove from in-memory hosts dictionary
                            if old_host_id in self.monitor.hosts:
                                del self.monitor.hosts[old_host_id]
                                logger.info(f"Removed old host {old_host_name} ({old_host_id[:8]}...) from monitor hosts")

                            # Close and remove Docker client
                            if old_host_id in self.monitor.clients:
                                try:
                                    self.monitor.clients[old_host_id].close()
                                    logger.debug(f"Closed Docker client for old host {old_host_name}")
                                except Exception as e:
                                    logger.warning(f"Error closing Docker client for old host: {e}")
                                del self.monitor.clients[old_host_id]

                            # Unregister from Go stats and event services
                            from stats_client import get_stats_client
                            stats_client = get_stats_client()

                            try:
                                await stats_client.remove_docker_host(old_host_id)
                                logger.info(f"Unregistered old host {old_host_name} from stats service")
                            except asyncio.TimeoutError:
                                logger.debug(f"Timeout unregistering {old_host_name} from stats service (expected during cleanup)")
                            except Exception as e:
                                logger.warning(f"Error unregistering from stats service: {e}")

                            try:
                                await stats_client.remove_event_host(old_host_id)
                                logger.info(f"Unregistered old host {old_host_name} from event service")
                            except Exception as e:
                                logger.warning(f"Error unregistering from event service: {e}")

                            logger.info(f"Migration cleanup complete: old host {old_host_name} removed from active monitoring")

                        except Exception as e:
                            logger.error(f"Error during migration cleanup: {e}", exc_info=True)

                    # Broadcast migration choice needed if multiple hosts share engine_id
                    if result.get("migration_choice_required") and self.monitor:
                        candidates = result.get("migration_candidates", [])
                        new_host_name = validated_data.hostname

                        try:
                            await self.monitor.manager.broadcast({
                                "type": "migration_choice_needed",
                                "data": {
                                    "agent_id": result["agent_id"],
                                    "host_id": result["host_id"],
                                    "host_name": new_host_name,
                                    "candidates": candidates
                                }
                            })
                            logger.info(f"Broadcast migration choice needed: {len(candidates)} candidates for agent {new_host_name}")
                        except Exception as e:
                            logger.error(f"Failed to broadcast migration choice needed: {e}")

                return result

            except ValidationError as e:
                # Return clear error message for invalid data
                error_details = e.errors()[0]
                logger.warning(
                    f"Agent registration validation failed: {error_details['msg']} "
                    f"(field: {error_details['loc']}, value: {error_details.get('input', 'N/A')})"
                )
                return {
                    "success": False,
                    "error": f"Invalid registration data: {error_details['msg']} (field: {error_details['loc'][0]})"
                }

        else:
            return {"success": False, "error": f"Invalid authentication type: {msg_type}"}

    async def message_loop(self):
        """
        Main message processing loop.

        Receives messages from agent and processes them.
        Commands TO the agent are sent via AgentConnectionManager.send_command().
        """
        try:
            while True:
                # Wait for message from agent
                message = await self.websocket.receive_json()
                await self.handle_agent_message(message)

        except WebSocketDisconnect:
            logger.info(f"Agent {self.agent_id} disconnected")
            raise

        except Exception as e:
            logger.error(f"Error in message loop for agent {self.agent_id}: {e}", exc_info=True)
            raise

    async def handle_agent_message(self, message: dict):
        """
        Handle a message from the agent.

        Message types:
        - stats: Container statistics
        - progress: Operation progress update
        - error: Operation error
        - heartbeat: Keep-alive ping
        - response / messages with correlation_id: Command responses

        Args:
            message: Message dict from agent (must have 'type' field)
        """
        # Check if this is a command response (has correlation_id or id)
        # Command responses should be routed to AgentCommandExecutor
        # Note: Legacy protocol uses "id", new protocol uses "correlation_id"
        msg_type = message.get("type")

        if "correlation_id" in message or ("id" in message and msg_type == "response"):
            command_executor = get_agent_command_executor()
            # Normalize legacy "id" to "correlation_id" for command executor
            if "id" in message and "correlation_id" not in message:
                message["correlation_id"] = message["id"]
            command_executor.handle_agent_response(message)
            return

        if msg_type == "stats":
            # Forward system stats to monitoring (in-memory buffer for sparklines)
            await self._handle_system_stats(message)

        elif msg_type == "progress":
            # Forward progress to UI via WebSocket broadcast (for update progress bars)
            await self._handle_progress(message)

        elif msg_type == "error":
            # Log error via EventBus (stores in database, triggers alerts, broadcasts to UI)
            await self._handle_error(message)

        elif msg_type == "heartbeat":
            # Update last_seen_at (short-lived session)
            with self.db_manager.get_session() as session:
                agent = session.query(Agent).filter_by(id=self.agent_id).first()
                if agent:
                    agent.last_seen_at = datetime.now(timezone.utc)
                    session.commit()

        elif msg_type == "event":
            # Handle agent events (container events, stats, etc.)
            event_type = message.get("command")
            payload = message.get("payload", {})

            if event_type == "container_event":
                # Container lifecycle event (start, stop, die, etc.)
                # Emit via EventBus: stores in database, triggers alerts, broadcasts to UI
                await self._handle_container_event(payload)

            elif event_type == "container_stats":
                # Real-time container stats
                # Forward to stats system: in-memory buffer + WebSocket broadcast
                await self._handle_container_stats(payload)

            elif event_type == "health_check_result":
                # Health check result from agent
                # Updates database and triggers auto-restart if needed
                await self._handle_health_check_result(payload)

            elif event_type == "update_progress":
                # Container update progress from agent
                # Forward to UI for real-time progress display
                await self._handle_update_progress(payload)

            elif event_type == "update_layer_progress":
                # Layer-by-layer image pull progress from agent
                # Forward to UI for real-time layer progress display
                await self._handle_update_layer_progress(payload)

            elif event_type == "update_complete":
                # Container update completed - contains new container ID
                # Must update database records with new ID
                await self._handle_update_complete(payload)

            elif event_type == "selfupdate_progress":
                # Agent self-update progress
                # Forward to UI for real-time progress display
                await self._handle_selfupdate_progress(payload)

            elif event_type == "deploy_progress":
                # Compose deployment progress from agent
                # Forward to AgentDeploymentExecutor for status updates
                await self._handle_deploy_progress(payload)

            elif event_type == "deploy_complete":
                # Compose deployment completed - contains container IDs
                # Must update database with deployed containers
                await self._handle_deploy_complete(payload)

            elif event_type == "shell_data":
                # Shell session data from agent
                # Forward to browser via shell manager
                await self._handle_shell_data(payload)

            else:
                logger.warning(f"Unknown event type from agent {self.agent_id}: {event_type}")

        else:
            logger.warning(f"Unknown message type from agent {self.agent_id}: {msg_type}")

    async def _handle_system_stats(self, message: dict):
        """
        Handle system stats from agent.

        Stores stats in in-memory circular buffer for sparklines (no database).
        """
        try:
            if not self.monitor or not hasattr(self.monitor, 'stats_history'):
                logger.debug(f"Stats history not available for agent {self.agent_id}")
                return

            stats = message.get("stats", {})
            cpu = stats.get("cpu_percent", 0.0)
            mem = stats.get("mem_percent", 0.0)
            net = stats.get("net_bytes_per_sec", 0.0)

            host_id = self.host_id or self.agent_id

            # Mark this host as receiving agent-fed stats (systemd mode)
            # This prevents the broadcast loop from overwriting with container aggregation
            self.monitor.stats_history.mark_agent_fed(host_id)

            # Store in circular buffer (50 points = ~90 seconds)
            self.monitor.stats_history.add_stats(
                host_id=host_id,
                cpu=cpu,
                mem=mem,
                net=net
            )

            logger.debug(f"Stored system stats for agent {self.agent_id}: CPU={cpu:.1f}%, MEM={mem:.1f}%, NET={net:.0f} B/s")

        except Exception as e:
            logger.error(f"Error handling system stats from agent {self.agent_id}: {e}", exc_info=True)

    async def _handle_progress(self, message: dict):
        """
        Handle progress update from agent.

        Broadcasts to UI for real-time progress bars (image pull, etc.).
        """
        try:
            if not self.monitor or not hasattr(self.monitor, 'manager'):
                logger.debug(f"WebSocket manager not available for agent {self.agent_id}")
                return

            # Truncate container ID to short format (12 chars)
            container_id = self._truncate_container_id(message.get("container_id"))

            # Forward progress to UI via WebSocket
            await self.monitor.manager.broadcast({
                "type": "agent_update_progress",
                "data": {
                    "agent_id": self.agent_id,
                    "host_id": self.host_id or self.agent_id,
                    "container_id": container_id,
                    "stage": message.get("stage"),
                    "progress": message.get("percent"),
                    "message": message.get("message"),
                    "download_speed": message.get("download_speed"),
                    "layer_info": message.get("layer_info")
                }
            })

            logger.info(f"Agent {self.agent_id} progress: {message.get('message')}")

        except Exception as e:
            logger.error(f"Error broadcasting progress from agent {self.agent_id}: {e}", exc_info=True)

    async def _handle_error(self, message: dict):
        """
        Handle error from agent.

        Logs via EventLogger for database storage and UI notification.
        """
        try:
            if not self.monitor or not hasattr(self.monitor, 'event_logger'):
                logger.error(f"Agent {self.agent_id} error: {message.get('error')}")
                return

            error_msg = message.get("error", "Unknown error")
            details = message.get("details")

            # Truncate container ID if present (optional field)
            container_id = self._truncate_container_id(message.get("container_id"))

            # Log via EventLogger (stores in database + broadcasts to UI)
            context = EventContext(
                host_id=self.host_id or self.agent_id,
                host_name=self.agent_hostname or self.agent_id,
                container_id=container_id if container_id else None
            )

            self.monitor.event_logger.log_event(
                category=EventCategory.HOST,
                event_type=LogEventType.ERROR,
                severity=EventSeverity.ERROR,
                title=f"Agent error: {error_msg}",
                message=details,
                context=context
            )

            logger.error(f"Agent {self.agent_id} error logged: {error_msg}")

        except Exception as e:
            logger.error(f"Error logging agent error from {self.agent_id}: {e}", exc_info=True)

    async def _handle_container_event(self, payload: dict):
        """
        Handle container lifecycle event from agent.

        Updates monitor's _container_states synchronously (like local Docker events do)
        to prevent "state drift detected" warnings during polling.

        Then emits via EventBus: database logging, alert triggers, UI broadcast.
        """
        try:
            if not self.monitor:
                logger.warning(f"Monitor not available for container event from agent {self.agent_id}")
                return

            action = payload.get("action")  # 'start', 'stop', 'die', 'restart', 'destroy'
            container_id = self._truncate_container_id(payload.get("container_id"))
            container_name = payload.get("container_name")

            # Validate required fields
            if not container_id:
                logger.warning(f"Container event missing container_id from agent {self.agent_id}")
                return

            # Map Docker actions to EventBus event types
            # Note: 'stop' is intentionally omitted - Docker emits both 'stop' and 'die' when
            # a container stops. We only process 'die' (which includes exit code) to avoid
            # duplicate events. This matches the logic in monitor.py (process_docker_events).
            event_type_map = {
                "start": EventType.CONTAINER_STARTED,
                "restart": EventType.CONTAINER_RESTARTED,
                "destroy": EventType.CONTAINER_DELETED
            }

            # Handle 'die' events specially - check exit code to determine event type
            # Issue #23/#104: Clean exits (exit 0) → STOPPED, crashes (exit != 0) → DIED
            if action == "die":
                attributes = payload.get("attributes", {})
                exit_code_str = attributes.get("exitCode")
                exit_code = 0  # Default to 0 if not provided
                if exit_code_str is not None:
                    try:
                        exit_code = int(exit_code_str)
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid exit code format: {exit_code_str}")

                if exit_code == 0:
                    event_type = EventType.CONTAINER_STOPPED
                else:
                    event_type = EventType.CONTAINER_DIED
                # Store exit_code in payload for event message generation
                payload["exit_code"] = exit_code
            else:
                event_type = event_type_map.get(action)
                if not event_type:
                    logger.debug(f"No event mapping for action '{action}' from agent {self.agent_id}")
                    return

            # Create composite key using utility function (validates 12-char format)
            composite_key = make_composite_key(self.host_id, container_id)

            # Update _container_states synchronously BEFORE emitting EventBus event
            # This matches how local Docker events work (see monitor.py process_docker_events)
            # and prevents "State drift detected" warnings during polling
            state_map = {
                'start': 'running',
                'stop': 'exited',
                'die': 'exited',
                'kill': 'exited',
                'pause': 'paused',
                'unpause': 'running',
                'restart': 'running',
            }
            new_state = state_map.get(action)

            # For 'die' events, use exit code to determine new_state (Issue #96)
            # exit_code=0 → "stopped" (clean exit), exit_code!=0 → "exited" (crash)
            if action == "die":
                exit_code = payload.get("exit_code", 0)
                new_state = "stopped" if exit_code == 0 else "exited"

            if new_state and hasattr(self.monitor, '_state_lock'):
                async with self.monitor._state_lock:
                    self.monitor._container_states[composite_key] = new_state
                    self.monitor._container_state_timestamps[composite_key] = datetime.now(timezone.utc)
                    self.monitor._container_state_sources[composite_key] = 'event'
                logger.debug(f"Updated _container_states for {container_name}: {new_state} (agent event)")

            # Add new_state to payload for alert rule matching (Issue #96)
            # The alert engine expects event_data.new_state for container_stopped rules
            if new_state:
                payload["new_state"] = new_state

            # Emit via EventBus (automatic: database, alerts, UI broadcast)
            event = Event(
                event_type=event_type,
                scope_type='container',
                scope_id=composite_key,
                scope_name=container_name,
                host_id=self.host_id or self.agent_id,
                host_name=self.agent_hostname or self.agent_id,
                data=payload
            )

            event_bus = get_event_bus(self.monitor)
            await event_bus.emit(event)

            logger.info(f"Container event emitted: {action} for {container_name} (agent {self.agent_id})")

        except Exception as e:
            logger.error(f"Error handling container event from agent {self.agent_id}: {e}", exc_info=True)

    async def _handle_container_stats(self, payload: dict):
        """
        Handle real-time container stats from agent.

        Stores in in-memory buffer and broadcasts to UI for real-time graphs.
        """
        try:
            if not self.monitor:
                logger.debug(f"Monitor not available for container stats from agent {self.agent_id}")
                return

            container_id = self._truncate_container_id(payload.get("container_id"))
            # Agent sends stats at top level, not nested under "stats" key
            stats = payload

            # Validate required fields
            if not container_id:
                logger.debug(f"Container stats missing container_id from agent {self.agent_id}")
                return

            # Create composite key for stats storage (validates 12-char format)
            container_key = make_composite_key(self.host_id, container_id)

            # Calculate network rate (bytes/sec) by comparing with previous reading
            current_time = time.time()
            net_rx = stats.get("network_rx", 0)
            net_tx = stats.get("network_tx", 0)
            net_total = net_rx + net_tx if isinstance(net_rx, (int, float)) and isinstance(net_tx, (int, float)) else 0

            # Calculate rate if we have previous reading
            net_bytes_per_sec = 0
            if container_key in self.prev_network_stats:
                prev = self.prev_network_stats[container_key]
                time_delta = current_time - prev['timestamp']
                if time_delta > 0:
                    bytes_delta = net_total - prev['total']
                    # Prevent negative values (can happen if container restarted)
                    if bytes_delta > 0:
                        net_bytes_per_sec = bytes_delta / time_delta

            # Update previous reading for next calculation
            self.prev_network_stats[container_key] = {
                'total': net_total,
                'timestamp': current_time
            }

            # Store in circular buffer (no database)
            if hasattr(self.monitor, 'container_stats_history'):
                cpu = stats.get("cpu_percent", 0.0)
                mem = stats.get("memory_percent", 0.0)  # Agent sends "memory_percent" not "mem_percent"

                self.monitor.container_stats_history.add_stats(
                    container_key=container_key,
                    cpu=cpu,
                    mem=mem,
                    net=net_bytes_per_sec  # Use calculated rate, not cumulative total
                )

            # Cache latest full stats for REST API endpoints (not just sparkline data)
            # This allows populate_container_stats() to access memory_usage, memory_limit, etc.
            # Add the calculated net_bytes_per_sec to the stats
            stats_with_rate = {**stats, 'net_bytes_per_sec': net_bytes_per_sec}
            if hasattr(self.monitor, 'agent_container_stats_cache'):
                self.monitor.agent_container_stats_cache[container_key] = stats_with_rate
            else:
                # Initialize cache if it doesn't exist
                self.monitor.agent_container_stats_cache = {container_key: stats_with_rate}

            # Broadcast to UI clients subscribed to this container
            if hasattr(self.monitor, 'manager'):
                await self.monitor.manager.broadcast({
                    "type": "container_stats",
                    "container_id": container_id,
                    "host_id": self.host_id or self.agent_id,
                    "stats": stats
                })

            logger.debug(f"Container stats processed for {container_id} (agent {self.agent_id})")

        except Exception as e:
            logger.error(f"Error handling container stats from agent {self.agent_id}: {e}", exc_info=True)

    async def _sync_health_check_configs(self):
        """
        Send all health check configs for this host to the agent.

        Called after agent authentication to sync agent-based health checks.
        Only sends configs where check_from='agent'.
        """
        try:
            if not self.host_id:
                logger.warning("Cannot sync health check configs: host_id not set")
                return

            # Build config list inside session, send outside session
            config_list = []

            with self.db_manager.get_session() as session:
                # Get all agent-based health checks for this host
                configs = session.query(ContainerHttpHealthCheck).filter(
                    ContainerHttpHealthCheck.host_id == self.host_id,
                    ContainerHttpHealthCheck.check_from == 'agent'
                ).all()

                if not configs:
                    logger.debug(f"No agent-based health checks for host {self.host_id}")
                    return

                # Convert to agent protocol format
                for config in configs:
                    # Extract container_id from composite key (host_id:container_id)
                    container_id = config.container_id.split(':')[-1] if ':' in config.container_id else config.container_id

                    config_list.append({
                        "container_id": container_id,
                        "host_id": config.host_id,
                        "enabled": config.enabled,
                        "url": config.url,
                        "method": config.method,
                        "expected_status_codes": config.expected_status_codes,
                        "timeout_seconds": config.timeout_seconds,
                        "check_interval_seconds": config.check_interval_seconds,
                        "follow_redirects": config.follow_redirects,
                        "verify_ssl": config.verify_ssl,
                        "headers_json": config.headers_json,
                        "auth_config_json": config.auth_config_json,
                    })

            # Send sync message to agent (outside session)
            if config_list:
                await self.websocket.send_json({
                    "type": "health_check_configs_sync",
                    "payload": {
                        "configs": config_list
                    }
                })
                logger.info(f"Synced {len(config_list)} health check configs to agent {self.agent_id}")

        except Exception as e:
            logger.error(f"Error syncing health check configs to agent {self.agent_id}: {e}", exc_info=True)

    async def _handle_health_check_result(self, payload: dict):
        """
        Handle health check result from agent.

        Updates database with check result and triggers auto-restart if configured.
        """
        try:
            container_id = self._truncate_container_id(payload.get("container_id"))
            if not container_id:
                logger.warning(f"Health check result missing container_id from agent {self.agent_id}")
                return

            healthy = payload.get("healthy", False)
            status_code = payload.get("status_code", 0)
            response_time_ms = payload.get("response_time_ms", 0)
            error_message = payload.get("error_message")
            timestamp_str = payload.get("timestamp")

            # Parse timestamp
            try:
                check_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')) if timestamp_str else datetime.now(timezone.utc)
            except (ValueError, AttributeError):
                check_time = datetime.now(timezone.utc)

            # Create composite key
            composite_key = make_composite_key(self.host_id, container_id)

            # Track if we need to trigger auto-restart (do it outside session)
            should_restart = False

            with self.db_manager.get_session() as session:
                health_check = session.query(ContainerHttpHealthCheck).filter(
                    ContainerHttpHealthCheck.container_id == composite_key
                ).first()

                if not health_check:
                    logger.warning(f"No health check config found for {composite_key}")
                    return

                # Update state
                health_check.last_checked_at = check_time
                health_check.last_response_time_ms = response_time_ms

                if healthy:
                    health_check.last_success_at = check_time
                    health_check.consecutive_successes += 1
                    health_check.consecutive_failures = 0
                    health_check.last_error_message = None

                    # Check if recovered (consecutive_successes >= success_threshold)
                    if health_check.consecutive_successes >= health_check.success_threshold:
                        if health_check.current_status != 'healthy':
                            health_check.current_status = 'healthy'
                            logger.info(f"Container {container_id} health check recovered (agent)")
                else:
                    health_check.last_failure_at = check_time
                    health_check.consecutive_failures += 1
                    health_check.consecutive_successes = 0
                    health_check.last_error_message = error_message

                    # Check if failed (consecutive_failures >= failure_threshold)
                    if health_check.consecutive_failures >= health_check.failure_threshold:
                        if health_check.current_status != 'unhealthy':
                            health_check.current_status = 'unhealthy'
                            logger.warning(f"Container {container_id} health check failed (agent): {error_message}")

                            # Mark for auto-restart (triggered outside session)
                            if health_check.auto_restart_on_failure:
                                should_restart = True

                session.commit()

            # Trigger auto-restart outside session to avoid holding DB connection during slow operation
            if should_restart:
                await self._trigger_auto_restart(container_id, error_message)

            logger.debug(f"Health check result processed for {container_id}: healthy={healthy}")

        except Exception as e:
            logger.error(f"Error handling health check result from agent {self.agent_id}: {e}", exc_info=True)

    async def _trigger_auto_restart(self, container_id: str, error_message: str):
        """
        Trigger auto-restart for a container via the agent.

        Args:
            container_id: Short container ID
            error_message: Reason for restart
        """
        try:
            if not self.monitor:
                logger.warning("Cannot trigger auto-restart: monitor not available")
                return

            # Import here to avoid circular dependency
            from docker_monitor.operations import DockerOperations

            ops = DockerOperations(self.monitor)
            success = await ops.restart_container(self.host_id, container_id)

            if success:
                logger.info(f"Auto-restart triggered for {container_id} due to health check failure")
            else:
                logger.error(f"Failed to auto-restart {container_id}")

        except Exception as e:
            logger.error(f"Error triggering auto-restart for {container_id}: {e}", exc_info=True)

    async def _handle_update_progress(self, payload: dict):
        """
        Handle update progress event from agent.

        Broadcasts to UI for real-time progress bars during container updates.
        This uses the existing WebSocket infrastructure but with update-specific data.
        """
        try:
            if not self.monitor or not hasattr(self.monitor, 'manager'):
                logger.debug(f"WebSocket manager not available for agent {self.agent_id}")
                return

            container_id = self._truncate_container_id(payload.get("container_id"))

            await self.monitor.manager.broadcast({
                "type": "container_update_progress",
                "data": {
                    "host_id": self.host_id or self.agent_id,
                    "container_id": container_id,
                    "stage": payload.get("stage"),
                    "message": payload.get("message"),
                    "error": payload.get("error"),
                }
            })

            logger.debug(
                f"Forwarded update progress for {container_id}: "
                f"{payload.get('stage')} - {payload.get('message')}"
            )

        except Exception as e:
            logger.error(f"Error handling update progress: {e}", exc_info=True)

    async def _handle_update_layer_progress(self, payload: dict):
        """
        Handle layer-by-layer image pull progress from agent.

        Broadcasts detailed layer progress to UI for real-time display during
        container updates. Uses same format as local Docker SDK updates.
        """
        try:
            if not self.monitor or not hasattr(self.monitor, 'manager'):
                logger.debug(f"WebSocket manager not available for agent {self.agent_id}")
                return

            container_id = self._truncate_container_id(payload.get("container_id"))

            # Forward layer progress to UI with correct event type
            await self.monitor.manager.broadcast({
                "type": "container_update_layer_progress",
                "data": {
                    "host_id": self.host_id or self.agent_id,
                    "entity_id": container_id,
                    "overall_progress": payload.get("overall_progress", 0),
                    "layers": payload.get("layers", []),
                    "total_layers": payload.get("total_layers", 0),
                    "remaining_layers": payload.get("remaining_layers", 0),
                    "summary": payload.get("summary", ""),
                    "speed_mbps": payload.get("speed_mbps", 0.0),
                }
            })

        except Exception as e:
            logger.error(f"Error handling update layer progress: {e}", exc_info=True)

    async def _handle_selfupdate_progress(self, payload: dict):
        """
        Handle agent self-update progress event.

        Broadcasts to UI and logs to event log for real-time progress display
        during agent self-updates.
        """
        try:
            if not self.monitor or not hasattr(self.monitor, 'manager'):
                logger.debug(f"WebSocket manager not available for agent {self.agent_id}")
                return

            stage = payload.get("stage", "")
            message = payload.get("message", "")
            error = payload.get("error")

            # Broadcast to UI
            await self.monitor.manager.broadcast({
                "type": "agent_update_progress",
                "data": {
                    "host_id": self.host_id or self.agent_id,
                    "agent_id": self.agent_id,
                    "stage": stage,
                    "message": message,
                    "error": error,
                }
            })

            # Log to event logger (use monitor's event_logger if available)
            # Only log errors to the event logger - progress is sent via WebSocket
            if self.monitor and hasattr(self.monitor, 'event_logger') and error:
                self.monitor.event_logger.log_event(
                    category=EventCategory.HOST,
                    event_type=LogEventType.ERROR,
                    severity=EventSeverity.ERROR,
                    title=f"Agent self-update error: {error}",
                    context=EventContext(host_id=self.host_id),
                    details={"stage": stage, "agent_id": self.agent_id}
                )

            logger.info(f"Agent {self.agent_id} self-update progress: {stage} - {message}")

        except Exception as e:
            logger.error(f"Error handling selfupdate progress: {e}", exc_info=True)

    async def _handle_update_complete(self, payload: dict):
        """
        Handle update completion event from agent.

        This handler's responsibilities:
        1. Signal the PendingUpdatesRegistry to unblock AgentUpdateExecutor
        2. Emit event_bus event for subscribers (event logger, notifications)
        3. Broadcast to UI for real-time updates

        NOTE: Database updates are handled by AgentUpdateExecutor using the shared
        database_updater.py module. This avoids duplicate database update logic
        and ensures consistency with DockerUpdateExecutor.
        """
        try:
            old_container_id = self._truncate_container_id(payload.get("old_container_id"))
            new_container_id = self._truncate_container_id(payload.get("new_container_id"))
            container_name = payload.get("container_name")
            failed_dependents = payload.get("failed_dependents", [])
            host_id = self.host_id or self.agent_id

            logger.info(
                f"Agent update complete: {container_name} "
                f"({old_container_id} -> {new_container_id}) on host {host_id}"
            )

            # Signal pending update registry that update is complete
            # This unblocks the AgentUpdateExecutor waiting for this event
            try:
                from updates.pending_updates import get_pending_updates_registry
                registry = get_pending_updates_registry()
                await registry.signal_complete(
                    host_id=host_id,
                    old_container_id=old_container_id,
                    new_container_id=new_container_id,
                    success=True,
                )
            except Exception as e:
                logger.warning(f"Failed to signal pending update registry: {e}")

            if failed_dependents:
                logger.warning(
                    f"Dependent containers failed to recreate: {failed_dependents}"
                )

            new_composite_key = make_composite_key(host_id, new_container_id)

            # Query by old key — the executor hasn't migrated the record yet
            old_composite_key = make_composite_key(host_id, old_container_id)
            update_info = {}
            try:
                with self.db_manager.get_session() as session:
                    update_record = session.query(ContainerUpdate).filter_by(
                        container_id=old_composite_key
                    ).first()
                    if update_record:
                        update_info = {
                            "previous_image": update_record.current_image,
                            "new_image": update_record.latest_image,
                            "current_version": update_record.current_version,
                            "latest_version": update_record.latest_version,
                            "current_digest": update_record.current_digest,
                            "latest_digest": update_record.latest_digest,
                            "changelog_url": update_record.changelog_url,
                        }
            except Exception as e:
                logger.debug(f"Could not look up update record for version data: {e}")

            try:
                if self.monitor:
                    event_data = {
                        "old_container_id": old_container_id,
                        "new_container_id": new_container_id,
                        "failed_dependents": failed_dependents,
                        "source": "agent",
                        **update_info,
                    }

                    event = Event(
                        event_type=EventType.UPDATE_COMPLETED,
                        scope_type='container',
                        scope_id=new_composite_key,
                        scope_name=container_name,
                        host_id=host_id,
                        host_name=self.agent_hostname or self.agent_id,
                        data=event_data,
                    )
                    await get_event_bus(self.monitor).emit(event)
            except Exception as e:
                logger.error(f"Event bus emit failed: {e}")

            # Broadcast completion to UI
            try:
                if self.monitor and hasattr(self.monitor, 'manager'):
                    broadcast_data = {
                        "host_id": host_id,
                        "old_container_id": old_container_id,
                        "new_container_id": new_container_id,
                        "container_name": container_name,
                    }
                    if failed_dependents:
                        broadcast_data["failed_dependents"] = failed_dependents
                        broadcast_data["warning"] = (
                            f"Container updated but {len(failed_dependents)} dependent container(s) "
                            f"failed to recreate: {', '.join(failed_dependents)}"
                        )

                    await self.monitor.manager.broadcast({
                        "type": "container_update_complete",
                        "data": broadcast_data
                    })
            except Exception as e:
                logger.error(f"UI broadcast failed: {e}")

        except Exception as e:
            logger.error(f"Error handling update complete: {e}", exc_info=True)

    async def _handle_deploy_progress(self, payload: dict):
        """
        Handle deployment progress event from agent.

        Forwards to AgentDeploymentExecutor for database updates and UI broadcast.
        """
        logger.debug(f"Received deploy_progress event: deployment_id={payload.get('deployment_id')}, stage={payload.get('stage')}")
        try:
            from deployment.agent_executor import get_agent_deployment_executor

            executor = get_agent_deployment_executor(self.monitor)
            await executor.handle_deploy_progress(payload)

            logger.debug(
                f"Deploy progress for {payload.get('deployment_id')}: "
                f"{payload.get('stage')} - {payload.get('message')}"
            )

        except Exception as e:
            logger.error(f"Error handling deploy progress: {e}", exc_info=True)

    async def _handle_shell_data(self, payload: dict):
        """
        Handle shell data event from agent.

        Forwards shell output to browser WebSocket via shell manager.
        """
        try:
            from agent.shell_manager import get_shell_manager

            session_id = payload.get("session_id")
            action = payload.get("action")
            data = payload.get("data")
            error = payload.get("error")

            if not session_id:
                logger.warning(f"Shell data missing session_id from agent {self.agent_id}")
                return

            shell_manager = get_shell_manager()
            await shell_manager.handle_shell_data(session_id, action, data, error)

        except Exception as e:
            logger.error(f"Error handling shell data from agent {self.agent_id}: {e}", exc_info=True)

    async def _handle_deploy_complete(self, payload: dict):
        """
        Handle deployment completion event from agent.

        Forwards to AgentDeploymentExecutor for database updates with container IDs.
        """
        logger.debug(f"Received deploy_complete event: deployment_id={payload.get('deployment_id')}, success={payload.get('success')}")
        try:
            from deployment.agent_executor import get_agent_deployment_executor

            executor = get_agent_deployment_executor(self.monitor)
            await executor.handle_deploy_complete(payload)

            deployment_id = payload.get("deployment_id")
            success = payload.get("success", False)
            services = payload.get("services", {})

            logger.info(
                f"Deploy complete for {deployment_id}: success={success}, "
                f"services={len(services)}"
            )

            # Note: Broadcast handled by AgentDeploymentExecutor._emit_deployment_event()
            # which uses correct event type (deployment_completed) and payload format

        except Exception as e:
            logger.error(f"Error handling deploy complete: {e}", exc_info=True)

async def handle_agent_websocket(websocket: WebSocket, monitor=None):
    """
    FastAPI endpoint handler for agent WebSocket connections.

    Usage in main.py:
        @app.websocket("/api/agent/ws")
        async def agent_websocket_endpoint(websocket: WebSocket):
            await handle_agent_websocket(websocket, monitor)

    Args:
        websocket: FastAPI WebSocket connection
        monitor: DockerMonitor instance (for EventBus, WebSocket broadcast, stats)
    """
    handler = AgentWebSocketHandler(websocket, monitor)
    await handler.handle_connection()
