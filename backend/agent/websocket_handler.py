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
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from agent.manager import AgentManager
from agent.connection_manager import agent_connection_manager
from database import Agent, DatabaseManager

logger = logging.getLogger(__name__)


class AgentWebSocketHandler:
    """Handles WebSocket connections from agents"""

    def __init__(self, websocket: WebSocket):
        """
        Initialize handler.

        Args:
            websocket: FastAPI WebSocket connection
        """
        self.websocket = websocket
        self.agent_manager = AgentManager()  # Creates short-lived sessions internally
        self.db_manager = DatabaseManager()  # For heartbeat updates
        self.agent_id: Optional[str] = None
        self.authenticated = False

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

            # Send success response
            await self.websocket.send_json({
                "type": "auth_success",
                "agent_id": self.agent_id,
                "host_id": auth_result.get("host_id"),
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
            result = self.agent_manager.register_agent({
                "token": message.get("token"),
                "engine_id": message.get("engine_id"),
                "version": message.get("version"),
                "proto_version": message.get("proto_version"),
                "capabilities": message.get("capabilities", {})
            })

            if result["success"]:
                self.agent_id = result["agent_id"]
                self.authenticated = True

            return result

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

        Args:
            message: Message dict from agent (must have 'type' field)
        """
        msg_type = message.get("type")

        if msg_type == "stats":
            # TODO: Forward stats to monitoring system
            # For now, just log
            logger.debug(f"Received stats from agent {self.agent_id}")

        elif msg_type == "progress":
            # TODO: Forward progress to UI via WebSocket broadcast
            logger.info(f"Agent {self.agent_id} progress: {message.get('message')}")

        elif msg_type == "error":
            # TODO: Log error and notify user
            logger.error(f"Agent {self.agent_id} error: {message.get('error')}")

        elif msg_type == "heartbeat":
            # Update last_seen_at (short-lived session)
            with self.db_manager.get_session() as session:
                agent = session.query(Agent).filter_by(id=self.agent_id).first()
                if agent:
                    agent.last_seen_at = datetime.utcnow()
                    session.commit()

        elif msg_type == "event":
            # Handle agent events (container events, stats, etc.)
            event_type = message.get("command")
            payload = message.get("payload", {})

            if event_type == "container_event":
                # Container lifecycle event (start, stop, die, etc.)
                logger.info(f"Agent {self.agent_id} container event: {payload.get('action')} for {payload.get('container_name')}")
                # TODO: Store event in database, trigger alerts, broadcast to UI

            elif event_type == "container_stats":
                # Real-time container stats
                logger.debug(f"Agent {self.agent_id} container stats for {payload.get('container_id')}")
                # TODO: Store in container_stats_history, broadcast to UI

            else:
                logger.warning(f"Unknown event type from agent {self.agent_id}: {event_type}")

        else:
            logger.warning(f"Unknown message type from agent {self.agent_id}: {msg_type}")


async def handle_agent_websocket(websocket: WebSocket):
    """
    FastAPI endpoint handler for agent WebSocket connections.

    Usage in main.py:
        @app.websocket("/api/agent/ws")
        async def agent_websocket_endpoint(websocket: WebSocket):
            await handle_agent_websocket(websocket)

    Args:
        websocket: FastAPI WebSocket connection
    """
    handler = AgentWebSocketHandler(websocket)
    await handler.handle_connection()
