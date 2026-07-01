"""Tests for migration 043 (container_updates.check_status column).

create_all() already builds the final ORM schema (which includes the new
column), so to prove the migration's ADD COLUMN does the work we drop the
column after create_all, stamp the prior head (042), then upgrade to 043 and
assert the column is re-added (nullable).
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
        # Drop the column so migration 043 has real work to do.
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE container_updates DROP COLUMN check_status"))
        engine.dispose()

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
        command.stamp(cfg, "042_live_chart_window")
        command.upgrade(cfg, "043_container_update_check_status")

        yield create_engine(f"sqlite:///{path}")
    finally:
        os.unlink(path)


def test_migration_adds_check_status_column(migrated_db):
    insp = inspect(migrated_db)
    cols = {c["name"]: c for c in insp.get_columns("container_updates")}
    assert "check_status" in cols, "migration did not add the check_status column"
    assert cols["check_status"]["nullable"] is True, "check_status should be nullable"
