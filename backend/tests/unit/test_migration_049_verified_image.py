"""Migration 049 adds container_updates.verified_image."""
import os
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from database import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def migrated_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE container_updates DROP COLUMN verified_image"))
        engine.dispose()

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.stamp(cfg, "048_registry_leak_cleanup")
        command.upgrade(cfg, "049_verified_image")
        command.upgrade(cfg, "049_verified_image")

        migrated = create_engine(url)
        yield migrated
        migrated.dispose()
    finally:
        os.unlink(path)


def test_migration_adds_nullable_verified_image(migrated_db):
    columns = {c["name"]: c for c in inspect(migrated_db).get_columns("container_updates")}

    assert columns["verified_image"]["nullable"] is True
