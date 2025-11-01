"""
Agent Connection Manager for DockMon v2.2.0

Manages WebSocket connections to remote DockMon agents.
Separate from the UI WebSocket ConnectionManager.

Architecture:
- Tracks active agent WebSocket connections by agent_id
- Provides command routing to specific agents
- Handles agent lifecycle (connect, disconnect, status updates)
- Thread-safe with asyncio locks
"""
import asyncio
import json
import logging
from typing import Dict, Optional
from datetime import datetime, timezone

from fastapi import WebSocket

from database import Agent, DatabaseManager

logger = logging.getLogger(__name__)


class AgentConnectionManager:
    """
    Manages WebSocket connections to DockMon agents.

    Singleton pattern - only one instance should exist per backend process.
    """

    _instance: Optional['AgentConnectionManager'] = None

    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize connection manager (idempotent)"""
        if self._initialized:
            return

        self.connections: Dict[str, WebSocket] = {}  # agent_id -> WebSocket
        self._connection_lock = asyncio.Lock()
        self.db_manager = DatabaseManager()  # For creating short-lived sessions
        self._initialized = True
        logger.info("AgentConnectionManager initialized")

    async def register_connection(self, agent_id: str, websocket: WebSocket):
        """
        Register a new agent WebSocket connection.

        Args:
            agent_id: Agent UUID
            websocket: WebSocket connection
        """
        async with self._connection_lock:
            # Close existing connection if any
            if agent_id in self.connections:
                old_ws = self.connections[agent_id]
                try:
                    await old_ws.close(code=1000, reason="New connection established")
                except Exception as e:
                    logger.warning(f"Error closing old connection for agent {agent_id}: {e}")

            # Register new connection
            self.connections[agent_id] = websocket

        # Update agent status in database (short-lived session)
        with self.db_manager.get_session() as session:
            agent = session.query(Agent).filter_by(id=agent_id).first()
            if agent:
                agent.status = "online"
                agent.last_seen_at = datetime.now(timezone.utc)
                session.commit()

        logger.info(f"Agent {agent_id} connected. Total agents: {len(self.connections)}")

    async def unregister_connection(self, agent_id: str):
        """
        Unregister an agent WebSocket connection.

        Args:
            agent_id: Agent UUID
        """
        async with self._connection_lock:
            if agent_id in self.connections:
                del self.connections[agent_id]

        # Update agent status in database (short-lived session)
        with self.db_manager.get_session() as session:
            agent = session.query(Agent).filter_by(id=agent_id).first()
            if agent:
                agent.status = "offline"
                agent.last_seen_at = datetime.now(timezone.utc)
                session.commit()

        logger.info(f"Agent {agent_id} disconnected. Total agents: {len(self.connections)}")

    async def send_command(self, agent_id: str, command: dict) -> bool:
        """
        Send a command to a specific agent.

        Args:
            agent_id: Agent UUID
            command: Command dict (must have 'type' field)

        Returns:
            bool: True if sent successfully, False if agent not connected
        """
        async with self._connection_lock:
            websocket = self.connections.get(agent_id)

        if not websocket:
            logger.warning(f"Cannot send command to agent {agent_id}: not connected")
            return False

        try:
            await websocket.send_json(command)
            logger.debug(f"Sent command to agent {agent_id}: {command.get('type')}")
            return True
        except Exception as e:
            logger.error(f"Error sending command to agent {agent_id}: {e}")
            # Connection might be dead, will be cleaned up on next message attempt
            return False

    def is_connected(self, agent_id: str) -> bool:
        """Check if an agent is currently connected"""
        return agent_id in self.connections

    def get_connected_agent_ids(self) -> list:
        """Get list of all connected agent IDs"""
        return list(self.connections.keys())

    def get_connection_count(self) -> int:
        """Get number of connected agents"""
        return len(self.connections)


# Global singleton instance
agent_connection_manager = AgentConnectionManager()
