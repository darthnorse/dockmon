"""Tests for resolve/recovery notifications (issue #189)."""

import pytest
from sqlalchemy import inspect

import database as database_module
from database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    """Temporary file-backed test database with full schema and migrations.

    Uses the singleton reset pattern from tests/integration/test_discovery_gating.py
    because DatabaseManager is a singleton and DatabaseManager.__init__ expects a
    plain file path (not a sqlite:// URL) and calls os.makedirs on the parent dir.
    """
    db_path = str(tmp_path / "test.db")
    # Reset singleton so DatabaseManager initialises a fresh instance with our path
    database_module._database_manager_instance = None
    db_manager = DatabaseManager(db_path=db_path)
    try:
        yield db_manager
    finally:
        if hasattr(db_manager, "engine"):
            db_manager.engine.dispose()
        database_module._database_manager_instance = None


def test_alert_rules_v2_has_notify_on_resolve_column(db):
    """Migration adds notify_on_resolve column to alert_rules_v2."""
    with db.get_session() as session:
        inspector = inspect(session.connection())
        cols = {c["name"]: c for c in inspector.get_columns("alert_rules_v2")}
        assert "notify_on_resolve" in cols
        col = cols["notify_on_resolve"]
        # Column must be NOT NULL
        assert col["nullable"] is False
        # Default is False / 0; SQLite reflection returns '0' for SQL DEFAULT 0
        # and None for a Python-side default (create_all path). Both are correct.
        assert col["default"] in (0, "0", False, "false", None)


def test_alerts_v2_has_resolve_notified_at_column(db):
    """Migration adds resolve_notified_at column to alerts_v2."""
    with db.get_session() as session:
        inspector = inspect(session.connection())
        cols = {c["name"] for c in inspector.get_columns("alerts_v2")}
        assert "resolve_notified_at" in cols
