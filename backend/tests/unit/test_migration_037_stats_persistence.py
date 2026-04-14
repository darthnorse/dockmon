"""Tests for migration 037 (stats persistence schema)."""
import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import Boolean, Integer, create_engine, inspect
from alembic.config import Config
from alembic import command

from database import Base, GlobalSettings

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def fresh_db():
    """Bootstrap a sqlite db the way DockMon fresh installs do, then apply
    migration 037.

    Running the full migration chain from empty isn't supported — migration
    001 assumes a pre-existing v1 database. So we mirror the production
    fresh-install flow: Base.metadata.create_all() to build the current ORM
    schema, alembic stamp the prior head (036), then upgrade to 037.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    try:
        Base.metadata.create_all(bind=engine)
        engine.dispose()

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
        command.stamp(cfg, "036_v2_3_1_drop_legacy_api_key_cols")
        command.upgrade(cfg, "037_v2_4_0_stats_persistence")

        yield engine
    finally:
        engine.dispose()
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

    required_not_null = {
        "container_id", "host_id", "timestamp", "resolution",
    }
    for name in required_not_null:
        assert cols[name]["nullable"] is False, \
            f"{name} should be NOT NULL"


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
    cols = {c["name"]: c for c in insp.get_columns("host_stats_history")}
    assert set(cols) == {
        "id", "host_id", "timestamp", "resolution",
        "cpu_percent", "memory_percent",
        "memory_used_bytes", "memory_limit_bytes",
        "network_bps", "container_count",
    }

    required_not_null = {"host_id", "timestamp", "resolution"}
    for name in required_not_null:
        assert cols[name]["nullable"] is False, \
            f"{name} should be NOT NULL"


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
        assert cols[col]["nullable"] is False, \
            f"{col} should be NOT NULL"


def test_foreign_keys_cascade_to_docker_hosts(fresh_db):
    insp = inspect(fresh_db)
    for table in ("container_stats_history", "host_stats_history"):
        fks = insp.get_foreign_keys(table)
        host_fk = next(
            (fk for fk in fks if fk["referred_table"] == "docker_hosts"),
            None,
        )
        assert host_fk is not None, f"{table} missing FK to docker_hosts"
        assert host_fk.get("options", {}).get("ondelete") == "CASCADE", \
            f"{table} FK to docker_hosts must CASCADE on delete"


def test_downgrade_removes_stats_schema(fresh_db):
    """Smoke-test the downgrade path — everything 037 created must come back off."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", str(fresh_db.url))

    command.downgrade(cfg, "036_v2_3_1_drop_legacy_api_key_cols")

    insp = inspect(fresh_db)
    tables = insp.get_table_names()
    assert "container_stats_history" not in tables
    assert "host_stats_history" not in tables
    settings_cols = {c["name"] for c in insp.get_columns("global_settings")}
    assert "stats_persistence_enabled" not in settings_cols
    assert "stats_retention_days" not in settings_cols
    assert "stats_points_per_view" not in settings_cols


def test_global_settings_orm_has_new_fields():
    """ORM columns must mirror migration 037 so fresh installs (create_all)
    and legacy upgrades (alembic) converge on identical schemas."""
    cols = {c.name: c for c in GlobalSettings.__table__.columns}

    expected = {
        "stats_persistence_enabled": (Boolean, True, "1"),
        "stats_retention_days": (Integer, 90, "90"),
        "stats_points_per_view": (Integer, 500, "500"),
    }
    assert expected.keys() <= cols.keys()

    for name, (col_type, py_default, ddl_default) in expected.items():
        col = cols[name]
        assert isinstance(col.type, col_type)
        assert col.nullable is False
        assert col.default.arg == py_default
        assert col.server_default is not None
        assert col.server_default.arg == ddl_default
