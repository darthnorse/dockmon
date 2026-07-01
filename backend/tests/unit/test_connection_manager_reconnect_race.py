"""
Regression tests for the agent reconnect race (Issue #224).

Symptom: an agent is connected and healthy, but DockMon shows the host as
"down" and fires a host_down alert that never clears.

Root cause: when an agent reconnects, the new WebSocket registers first, then
the superseded OLD socket's teardown runs. The old teardown unregistered by
agent_id alone, so it evicted the LIVE (new) connection from the registry and
marked the agent offline. The handler then emitted HOST_DISCONNECTED for a host
that was actually up.

These tests pin the fix: unregister must be identity-aware (only the connection
that is still the agent's active socket may tear down its registry/DB state).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from agent.connection_manager import AgentConnectionManager
from database import Agent, DockerHostDB

AGENT_ID = "11812892-bb54-4e98-97e7-c408f355a64d"
HOST_ID = "ebe8b950-6e8f-4901-8585-8b63b65949db"


@pytest.fixture
def conn_manager(test_database_manager):
    """A fresh AgentConnectionManager wired to the test database.

    AgentConnectionManager is a process-wide singleton; reset it so each test
    gets an empty connection registry, and inject the test DB session factory.
    """
    AgentConnectionManager._instance = None
    mgr = AgentConnectionManager()
    mgr.db_manager = test_database_manager
    yield mgr
    AgentConnectionManager._instance = None


def _seed_agent(session, status):
    """Create a host + agent row so status transitions can be asserted."""
    session.add(DockerHostDB(
        id=HOST_ID, name="OPTIMIZACION RUTAS", url="agent://",
        is_active=True, created_at=datetime.now(timezone.utc),
    ))
    session.flush()
    session.add(Agent(
        id=AGENT_ID, host_id=HOST_ID, engine_id="engine-abc",
        version="2.2.0", proto_version="1", capabilities={}, status=status,
    ))
    session.commit()


async def test_superseded_disconnect_keeps_live_reconnection(conn_manager, test_db):
    """A stale teardown from a superseded socket must not evict the live
    reconnection or mark the agent offline (Issue #224)."""
    _seed_agent(test_db, status="offline")

    old_ws = AsyncMock()
    new_ws = AsyncMock()

    # Agent connects, then reconnects: new socket supersedes the old one.
    await conn_manager.register_connection(AGENT_ID, old_ws)
    await conn_manager.register_connection(AGENT_ID, new_ws)

    # The OLD socket's teardown fires AFTER the reconnect — the #224 race.
    removed = await conn_manager.unregister_connection(AGENT_ID, old_ws)

    assert removed is False, "superseded teardown must be a no-op"
    assert conn_manager.is_connected(AGENT_ID) is True, "live connection was evicted"
    assert conn_manager.connections[AGENT_ID] is new_ws, "registry no longer points at the live socket"

    test_db.expire_all()
    agent = test_db.query(Agent).filter_by(id=AGENT_ID).first()
    assert agent.status == "online", "superseded teardown wrongly marked the agent offline"


async def test_active_disconnect_removes_connection_and_marks_offline(conn_manager, test_db):
    """A genuine disconnect (no reconnect) removes the active connection and
    marks the agent offline."""
    _seed_agent(test_db, status="online")

    ws = AsyncMock()
    await conn_manager.register_connection(AGENT_ID, ws)

    removed = await conn_manager.unregister_connection(AGENT_ID, ws)

    assert removed is True, "active connection teardown should report removal"
    assert conn_manager.is_connected(AGENT_ID) is False, "active connection was not removed"

    test_db.expire_all()
    agent = test_db.query(Agent).filter_by(id=AGENT_ID).first()
    assert agent.status == "offline", "active disconnect should mark the agent offline"
