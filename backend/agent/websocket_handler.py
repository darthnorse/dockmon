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
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from agent.manager import AgentManager
from agent.connection_manager import agent_connection_manager
from agent.command_executor import get_agent_command_executor
from agent.models import AgentRegistrationRequest
from database import Agent, DatabaseManager
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
        self.agent_manager = AgentManager()  # Creates short-lived sessions internally
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

        elif msg_type == "reconnect":
            # Existing agent reconnection
            result = self.agent_manager.reconnect_agent({
                "agent_id": message.get("agent_id"),
                "engine_id": message.get("engine_id")
            })

            if result["success"]:
                self.agent_id = result["agent_id"]
                self.authenticated = True

            return result

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
        # Check if this is a command response (has correlation_id)
        # Command responses should be routed to AgentCommandExecutor
        if "correlation_id" in message:
            command_executor = get_agent_command_executor()
            command_executor.handle_agent_response(message)
            return

        msg_type = message.get("type")

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

            else:
                logger.warning(f"Unknown event type from agent {self.agent_id}: {event_type}")

        else:
            logger.warning(f"Unknown message type from agent {self.agent_id}: {msg_type}")

    async def _handle_system_stats(self, message: dict):
        """
        Handle system stats from agent (TODO #1).

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

            # Store in circular buffer (50 points = ~90 seconds)
            self.monitor.stats_history.add_stats(
                host_id=self.host_id or self.agent_id,
                cpu=cpu,
                mem=mem,
                net=net
            )

            logger.debug(f"Stored system stats for agent {self.agent_id}: CPU={cpu:.1f}%, MEM={mem:.1f}%, NET={net:.0f} B/s")

        except Exception as e:
            logger.error(f"Error handling system stats from agent {self.agent_id}: {e}", exc_info=True)

    async def _handle_progress(self, message: dict):
        """
        Handle progress update from agent (TODO #2).

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
        Handle error from agent (TODO #3).

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
        Handle container lifecycle event from agent (TODO #4).

        Emits via EventBus: database logging, alert triggers, UI broadcast.
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
            event_type_map = {
                "start": EventType.CONTAINER_STARTED,
                "stop": EventType.CONTAINER_STOPPED,
                "restart": EventType.CONTAINER_RESTARTED,
                "die": EventType.CONTAINER_DIED,
                "destroy": EventType.CONTAINER_DELETED
            }

            event_type = event_type_map.get(action)
            if not event_type:
                logger.debug(f"No event mapping for action '{action}' from agent {self.agent_id}")
                return

            # Create composite key using utility function (validates 12-char format)
            composite_key = make_composite_key(self.host_id, container_id)

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
        Handle real-time container stats from agent (TODO #5).

        Stores in in-memory buffer and broadcasts to UI for real-time graphs.
        """
        try:
            if not self.monitor:
                logger.debug(f"Monitor not available for container stats from agent {self.agent_id}")
                return

            container_id = self._truncate_container_id(payload.get("container_id"))
            stats = payload.get("stats", {})

            # Validate required fields
            if not container_id:
                logger.debug(f"Container stats missing container_id from agent {self.agent_id}")
                return

            # Create composite key for stats storage (validates 12-char format)
            container_key = make_composite_key(self.host_id, container_id)

            # Store in circular buffer (no database)
            if hasattr(self.monitor, 'container_stats_history'):
                cpu = stats.get("cpu_percent", 0.0)
                mem = stats.get("mem_percent", 0.0)
                net = stats.get("net_bytes_per_sec", 0.0)

                self.monitor.container_stats_history.add_stats(
                    container_key=container_key,
                    cpu=cpu,
                    mem=mem,
                    net=net
                )

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
