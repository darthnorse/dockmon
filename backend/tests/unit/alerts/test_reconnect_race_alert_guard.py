"""Reconnect-race alert guard (Issue #224).

A superseded agent socket's teardown can still emit HOST_DISCONNECTED after the
agent has reconnected: the event bus processes the old disconnect and the new
connect as separate interleaving tasks, so the disconnect can be evaluated after
the reconnect already cleared the host_down alert, leaving a stuck false down.

handle_host_event must drop a host disconnect whose agent is already reconnected
(checked at event-processing time, which is naturally after the reconnect), so it
never raises a host_down alert that nothing will clear.
"""
import types
from unittest.mock import MagicMock

import pytest

import database as database_module
from agent.connection_manager import agent_connection_manager
from alerts.evaluation_service import AlertEvaluationService
from database import DatabaseManager

HOST = "ebe8b950-6e8f-4901-8585-8b63b65949db"
AGENT_ID = "11812892-bb54-4e98-97e7-c408f355a64d"


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database_module._database_manager_instance = None
    db_manager = DatabaseManager(db_path=db_path)
    try:
        yield db_manager
    finally:
        if hasattr(db_manager, "engine"):
            db_manager.engine.dispose()
        database_module._database_manager_instance = None


def _service(db):
    """Service with a spy engine so we can assert whether the disconnect was evaluated."""
    service = AlertEvaluationService(db=db, monitor=types.SimpleNamespace())
    service.engine = MagicMock()
    service.engine.evaluate_event.return_value = []
    service.engine.cancel_pending_clears_for_scope.return_value = 0
    service.engine.clear_pending_for_scope.return_value = 0
    return service


async def test_disconnect_dropped_when_agent_already_reconnected(db, monkeypatch):
    """A stale disconnect whose agent is already reconnected must not raise host_down."""
    monkeypatch.setattr(agent_connection_manager, "is_connected", lambda aid: True)
    service = _service(db)

    await service.handle_host_event("disconnection", HOST, {"agent_id": AGENT_ID})

    service.engine.evaluate_event.assert_not_called()


async def test_disconnect_evaluated_when_agent_not_connected(db, monkeypatch):
    """A genuine disconnect (agent really gone) is still evaluated normally."""
    monkeypatch.setattr(agent_connection_manager, "is_connected", lambda aid: False)
    service = _service(db)

    await service.handle_host_event("disconnection", HOST, {"agent_id": AGENT_ID})

    service.engine.evaluate_event.assert_called_once()


async def test_non_agent_disconnect_still_evaluated(db, monkeypatch):
    """A disconnect with no agent_id (non-agent host) is unaffected by the guard."""
    monkeypatch.setattr(agent_connection_manager, "is_connected", lambda aid: True)
    service = _service(db)

    await service.handle_host_event("disconnection", HOST, {"error": "connection lost"})

    service.engine.evaluate_event.assert_called_once()
