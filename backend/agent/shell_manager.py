"""
Agent Shell Session Manager for DockMon

Manages shell sessions that proxy through agent WebSocket connections.
Browser WebSocket <-> Backend <-> Agent WebSocket <-> Docker exec
"""
import asyncio
import base64
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import WebSocket

from agent.connection_manager import agent_connection_manager

logger = logging.getLogger(__name__)


@dataclass
class ShellSession:
    """Represents an active shell session"""
    session_id: str
    host_id: str
    container_id: str
    agent_id: str
    websocket: WebSocket  # Browser WebSocket
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentShellManager:
    """Manages shell sessions proxied through agents"""

    _instance: Optional['AgentShellManager'] = None

    def __init__(self):
        self.sessions: Dict[str, ShellSession] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> 'AgentShellManager':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start_session(
        self,
        host_id: str,
        container_id: str,
        agent_id: str,
        websocket: WebSocket
    ) -> str:
        """
        Start a new shell session through the agent.

        Args:
            host_id: Docker host ID
            container_id: Container ID to exec into
            agent_id: Agent ID for this host
            websocket: Browser WebSocket connection

        Returns:
            Session ID for this shell session
        """
        session_id = str(uuid.uuid4())

        async with self._lock:
            session = ShellSession(
                session_id=session_id,
                host_id=host_id,
                container_id=container_id,
                agent_id=agent_id,
                websocket=websocket
            )
            self.sessions[session_id] = session

        # Send start command to agent
        await agent_connection_manager.send_command(
            agent_id,
            {
                "type": "shell_session",
                "payload": {
                    "action": "start",
                    "container_id": container_id,
                    "session_id": session_id
                }
            }
        )

        logger.info(f"Shell session started: {session_id[:8]} for container {container_id[:12]} on host {host_id[:8]}")
        return session_id

    async def handle_shell_data(self, session_id: str, action: str, data: Optional[str] = None, error: Optional[str] = None):
        """
        Handle shell data from agent - forward to browser WebSocket.

        Args:
            session_id: Shell session ID
            action: Action type (started, data, closed, error)
            data: Base64-encoded terminal data (for action=data)
            error: Error message (for action=error)
        """
        async with self._lock:
            session = self.sessions.get(session_id)

        if not session:
            logger.debug(f"Shell session not found for data: {session_id[:8]}")
            return

        try:
            if action == "data" and data:
                # Decode base64 and forward to browser as binary
                decoded = base64.b64decode(data)
                await session.websocket.send_bytes(decoded)

            elif action == "started":
                logger.debug(f"Shell session {session_id[:8]} started on agent")

            elif action == "closed":
                logger.info(f"Shell session {session_id[:8]} closed by agent")
                await self._cleanup_session(session_id)

            elif action == "error":
                logger.warning(f"Shell session {session_id[:8]} error: {error}")
                # Try to close the browser WebSocket with error
                try:
                    await session.websocket.close(code=1011, reason=error or "Shell error")
                except Exception:
                    pass
                await self._cleanup_session(session_id)

        except Exception as e:
            logger.error(f"Error forwarding shell data to browser: {e}")

    async def handle_browser_input(self, session_id: str, data: bytes):
        """
        Forward terminal input from browser to agent.

        Args:
            session_id: Shell session ID
            data: Raw terminal input bytes
        """
        async with self._lock:
            session = self.sessions.get(session_id)

        if not session:
            logger.debug(f"Shell session not found for input: {session_id[:8]}")
            return

        # Encode as base64 and send to agent
        encoded = base64.b64encode(data).decode('ascii')
        await agent_connection_manager.send_command(
            session.agent_id,
            {
                "type": "shell_session",
                "payload": {
                    "action": "data",
                    "session_id": session_id,
                    "data": encoded
                }
            }
        )

    async def handle_resize(self, session_id: str, cols: int, rows: int):
        """
        Send terminal resize to agent.

        Args:
            session_id: Shell session ID
            cols: Terminal columns
            rows: Terminal rows
        """
        async with self._lock:
            session = self.sessions.get(session_id)

        if not session:
            logger.debug(f"Shell session not found for resize: {session_id[:8]}")
            return

        await agent_connection_manager.send_command(
            session.agent_id,
            {
                "type": "shell_session",
                "payload": {
                    "action": "resize",
                    "session_id": session_id,
                    "cols": cols,
                    "rows": rows
                }
            }
        )

    async def close_session(self, session_id: str):
        """
        Close a shell session and notify the agent.

        Args:
            session_id: Shell session ID
        """
        async with self._lock:
            session = self.sessions.get(session_id)

        if not session:
            return

        # Send close command to agent
        try:
            await agent_connection_manager.send_command(
                session.agent_id,
                {
                    "type": "shell_session",
                    "payload": {
                        "action": "close",
                        "session_id": session_id
                    }
                }
            )
        except Exception as e:
            logger.debug(f"Error sending close to agent: {e}")

        await self._cleanup_session(session_id)
        logger.info(f"Shell session closed: {session_id[:8]}")

    async def _cleanup_session(self, session_id: str):
        """Remove session from tracking"""
        async with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]

    async def close_sessions_for_agent(self, agent_id: str):
        """
        Close all shell sessions for a specific agent.

        Called when an agent disconnects.

        Args:
            agent_id: Agent ID
        """
        async with self._lock:
            sessions_to_close = [
                session for session in self.sessions.values()
                if session.agent_id == agent_id
            ]

        for session in sessions_to_close:
            try:
                await session.websocket.close(code=1001, reason="Agent disconnected")
            except Exception:
                pass
            await self._cleanup_session(session.session_id)

        if sessions_to_close:
            logger.info(f"Closed {len(sessions_to_close)} shell sessions for agent {agent_id[:8]}")


def get_shell_manager() -> AgentShellManager:
    """Get the global shell manager instance"""
    return AgentShellManager.get_instance()
