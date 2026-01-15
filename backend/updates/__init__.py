"""
Updates Module

Container update execution with routing to appropriate executors.

Architecture:
- UpdateExecutor: Router that dispatches to Go service or Agent executors
- Go compose-service: Handles local/mTLS hosts via Unix socket
- AgentUpdateExecutor: Agent-based updates (WebSocket connection)
"""

from updates.update_executor import UpdateExecutor, get_update_executor
from updates.agent_executor import AgentUpdateExecutor
from updates.types import UpdateContext, UpdateResult, UpdateStage

__all__ = [
    'UpdateExecutor',
    'get_update_executor',
    'AgentUpdateExecutor',
    'UpdateContext',
    'UpdateResult',
    'UpdateStage',
]
