"""Tests for migration 042 (live_chart_window_seconds column).

create_all() already builds the final ORM schema (which includes the new
column), so to prove the migration's ADD COLUMN actually does the work we drop
the column after create_all, stamp the prior head (041), then upgrade to 042
and assert the column is re-added with the right default.
"""
import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from alembic.config import Config
from alembic import command

from database import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def migrated_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    try:
        Base.metadata.create_all(bind=engine)
        # Drop the column so migration 042 has real work to do.
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE global_settings DROP COLUMN live_chart_window_seconds"
            ))
        engine.dispose()

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
        command.stamp(cfg, "041_disable_local_login")
        command.upgrade(cfg, "042_live_chart_window")

        yield create_engine(f"sqlite:///{path}")
    finally:
        os.unlink(path)


def test_migration_adds_live_chart_window_column(migrated_db):
    insp = inspect(migrated_db)
    cols = {c["name"]: c for c in insp.get_columns("global_settings")}
    assert "live_chart_window_seconds" in cols, "migration did not add the column"
    assert cols["live_chart_window_seconds"]["nullable"] is False, \
        "live_chart_window_seconds should be NOT NULL"


def test_migration_backfills_default_window(migrated_db):
    # Seed a row, then confirm the server_default applied 600 on add_column.
    with migrated_db.begin() as conn:
        conn.execute(text("INSERT INTO global_settings (id) VALUES (1)"))
        value = conn.execute(text(
            "SELECT live_chart_window_seconds FROM global_settings WHERE id = 1"
        )).scalar()
    assert value == 600
