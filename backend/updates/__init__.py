"""
Updates Module

Container update execution with routing to appropriate executors.

Architecture:
- UpdateExecutor: Router that dispatches to Docker or Agent executors
- DockerUpdateExecutor: Direct Docker SDK updates (local/mTLS hosts)
- AgentUpdateExecutor: Agent-based updates (WebSocket connection)
"""

from updates.update_executor import UpdateExecutor, get_update_executor
from updates.docker_executor import DockerUpdateExecutor
from updates.agent_executor import AgentUpdateExecutor
from updates.types import UpdateContext, UpdateResult, UpdateStage

__all__ = [
    'UpdateExecutor',
    'get_update_executor',
    'DockerUpdateExecutor',
    'AgentUpdateExecutor',
    'UpdateContext',
    'UpdateResult',
    'UpdateStage',
]
