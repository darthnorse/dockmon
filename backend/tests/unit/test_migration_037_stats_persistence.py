"""Tests for migration 037 (stats persistence schema)."""
import os
import sys
import tempfile

import pytest
from sqlalchemy import create_engine, inspect
from alembic.config import Config
from alembic import command

# Mirror conftest.py: make backend/ importable so `from database import Base` works.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database import Base  # noqa: E402


@pytest.fixture
def fresh_db():
    """Bootstrap a fresh sqlite db the same way DockMon fresh installs do:
    Base.metadata.create_all() to build the current ORM schema, then
    alembic stamp the prior head (036), then upgrade to 037.

    This mirrors DockMon's production fresh-install flow (see
    DatabaseManager.__init__ in backend/database.py and the migration
    runner comments: "fresh installs where Base.metadata.create_all() +
    stamp HEAD skips"). Running the full migration chain from an empty
    sqlite file is not supported — migration 001 assumes a v1 database
    where global_settings already exists.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{path}")
        # Bootstrap ORM schema (as DockMon fresh installs do). This creates
        # global_settings and all other tables defined in database.py. It
        # does NOT create container_stats_history / host_stats_history —
        # those belong to migration 037 under test.
        Base.metadata.create_all(bind=engine)
        engine.dispose()

        cfg = Config(os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"))
        cfg.set_main_option(
            "script_location",
            os.path.join(os.path.dirname(__file__), "..", "..", "alembic"),
        )
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")

        # Mark all pre-037 migrations as already applied (fresh-install pattern).
        command.stamp(cfg, "036_v2_3_1_drop_legacy_api_key_cols")
        # Now run the migration under test.
        command.upgrade(cfg, "037_v2_4_0_stats_persistence")
        yield create_engine(f"sqlite:///{path}")
    finally:
        os.unlink(path)


def test_container_stats_history_table_exists(fresh_db):
    insp = inspect(fresh_db)
    assert "container_stats_history" in insp.get_table_names()


def test_container_stats_history_columns(fresh_db):
    insp = inspect(fresh_db)
    cols = {c["name"]: c for c in insp.get_columns("container_stats_history")}
    assert set(cols) == {
        "id", "container_id", "host_id", "timestamp", "resolution",
        "cpu_percent", "memory_usage", "memory_limit", "network_bps",
    }
    assert "INT" in str(cols["timestamp"]["type"]).upper()
    assert "REAL" in str(cols["network_bps"]["type"]).upper() \
        or "FLOAT" in str(cols["network_bps"]["type"]).upper()


def test_container_stats_history_unique_constraint(fresh_db):
    insp = inspect(fresh_db)
    uniques = insp.get_unique_constraints("container_stats_history")
    cols_sets = [tuple(sorted(u["column_names"])) for u in uniques]
    assert ("container_id", "resolution", "timestamp") in cols_sets


def test_container_stats_history_host_index(fresh_db):
    insp = inspect(fresh_db)
    indexes = insp.get_indexes("container_stats_history")
    assert any(idx["column_names"] == ["host_id"] for idx in indexes)


def test_host_stats_history_table_exists(fresh_db):
    insp = inspect(fresh_db)
    assert "host_stats_history" in insp.get_table_names()


def test_host_stats_history_columns(fresh_db):
    insp = inspect(fresh_db)
    cols = {c["name"] for c in insp.get_columns("host_stats_history")}
    assert cols == {
        "id", "host_id", "timestamp", "resolution",
        "cpu_percent", "memory_percent",
        "memory_used_bytes", "memory_limit_bytes",
        "network_bps", "container_count",
    }


def test_host_stats_history_unique_constraint(fresh_db):
    insp = inspect(fresh_db)
    uniques = insp.get_unique_constraints("host_stats_history")
    cols_sets = [tuple(sorted(u["column_names"])) for u in uniques]
    assert ("host_id", "resolution", "timestamp") in cols_sets


def test_global_settings_new_columns(fresh_db):
    insp = inspect(fresh_db)
    cols = {c["name"]: c for c in insp.get_columns("global_settings")}
    for col in ("stats_persistence_enabled",
                "stats_retention_days", "stats_points_per_view"):
        assert col in cols, f"missing column {col}"


def test_foreign_keys_to_docker_hosts(fresh_db):
    insp = inspect(fresh_db)
    for table in ("container_stats_history", "host_stats_history"):
        fks = insp.get_foreign_keys(table)
        assert any(fk["referred_table"] == "docker_hosts" for fk in fks), \
            f"{table} missing FK to docker_hosts"
