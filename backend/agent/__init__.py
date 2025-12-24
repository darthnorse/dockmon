"""
Agent management package for DockMon v2.2.0.

Handles agent registration, authentication, lifecycle management,
and WebSocket communication with remote agents.
"""
from .manager import AgentManager
from .connection_manager import AgentConnectionManager, agent_connection_manager
from .websocket_handler import AgentWebSocketHandler, handle_agent_websocket

__all__ = [
    'AgentManager',
    'AgentConnectionManager',
    'agent_connection_manager',
    'AgentWebSocketHandler',
    'handle_agent_websocket'
]
