"""Schema parity: fresh installs vs upgraded databases.

DockMon builds its schema through two different pipelines:

- Fresh install: migrate.py _handle_fresh_install -> Base.metadata.create_all()
  + stamp HEAD (no migrations execute).
- Upgrade: migrate.py runs the Alembic chain (oldest supported baseline is a
  v1.1.3 database; migration 001 ALTERs those tables rather than creating them).

Both are followed by the DatabaseManager startup pass (create_all for missing
model tables + its ad-hoc column migrations), which is part of the production
pipeline and therefore part of what these tests build.

If a table or column exists in only one pipeline, one class of user gets a
broken schema. That is exactly how fresh v2.4.x installs shipped without the
stats history tables: migration 037 created tables that deliberately have no
ORM model (the Go stats-service owns them), so create_all() never made them
and stats-service silently disabled itself.

These tests fail on ANY new divergence. Known historical leftovers that only
exist on upgraded databases are frozen in LEGACY_UPGRADED_ONLY_COLUMNS below;
do not add entries for new code.
"""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

import database as database_module
from database import Base, DatabaseManager
from migrate import run_migrations

BACKEND_DIR = Path(__file__).parents[3]
FIXTURE = Path(__file__).parents[2] / "fixtures" / "v1_1_3_schema.sql"

# Columns that exist ONLY on upgraded databases: created by old migrations,
# since removed from (or never added to) the ORM models, unused by current
# code, and never dropped from user databases. Candidates for a cleanup
# migration; frozen here so new drift cannot hide behind them.
LEGACY_UPGRADED_ONLY_COLUMNS = {
    "event_logs": {"source"},
    "global_settings": {"log_retention_days"},
    "users": {"dashboard_layout"},
}


def _run_startup_pass(db_path: str):
    """Run the DatabaseManager init exactly as backend startup does."""
    database_module._database_manager_instance = None
    try:
        dm = DatabaseManager(db_path=db_path)
        dm.engine.dispose()
    finally:
        database_module._database_manager_instance = None


def _build_fresh_install(db_path: str, monkeypatch) -> None:
    """Production fresh-install pipeline: migrate.py on a missing DB file."""
    monkeypatch.setenv("DATABASE_PATH", db_path)
    assert run_migrations(), "migrate.py failed on a fresh install"
    _run_startup_pass(db_path)


def _build_upgraded(db_path: str, monkeypatch) -> None:
    """Production upgrade pipeline: v1.1.3 baseline through the full chain."""
    conn = sqlite3.connect(db_path)
    conn.executescript(FIXTURE.read_text())
    conn.commit()
    conn.close()
    monkeypatch.setenv("DATABASE_PATH", db_path)
    assert run_migrations(), "migrate.py failed upgrading a v1.1.3 database"
    _run_startup_pass(db_path)


def _snapshot(db_path: str) -> dict:
    """Map of table name -> set of column names (user tables only)."""
    conn = sqlite3.connect(db_path)
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
        )
    ]
    snap = {
        t: {r[1] for r in conn.execute(f"PRAGMA table_info('{t}')")} for t in tables
    }
    conn.close()
    return snap


def _index_names(db_path: str, table: str) -> set:
    conn = sqlite3.connect(db_path)
    names = {r[1] for r in conn.execute(f"PRAGMA index_list('{table}')")}
    conn.close()
    return names


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "fresh.db")
    _build_fresh_install(db_path, monkeypatch)
    return db_path


@pytest.fixture
def upgraded_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "upgraded.db")
    _build_upgraded(db_path, monkeypatch)
    return db_path


class TestSchemaParity:
    def test_fresh_and_upgraded_have_same_tables(self, fresh_db, upgraded_db):
        fresh, upgraded = _snapshot(fresh_db), _snapshot(upgraded_db)
        assert set(fresh) == set(upgraded), (
            f"Tables only on fresh installs: {sorted(set(fresh) - set(upgraded))}; "
            f"tables only on upgraded databases: {sorted(set(upgraded) - set(fresh))}. "
            "A table created only by a migration needs a Core Table definition in "
            "database.py (see container_stats_history); a table created only by a "
            "model needs a migration."
        )

    def test_fresh_and_upgraded_have_same_columns(self, fresh_db, upgraded_db):
        fresh, upgraded = _snapshot(fresh_db), _snapshot(upgraded_db)
        problems = []
        for table in sorted(set(fresh) & set(upgraded)):
            allowed = LEGACY_UPGRADED_ONLY_COLUMNS.get(table, set())
            only_fresh = fresh[table] - upgraded[table]
            only_upgraded = upgraded[table] - fresh[table] - allowed
            if only_fresh:
                problems.append(f"{table}: only on fresh installs: {sorted(only_fresh)}")
            if only_upgraded:
                problems.append(
                    f"{table}: only on upgraded databases: {sorted(only_upgraded)}"
                )
        assert not problems, (
            "Column drift between fresh installs and upgraded databases:\n  "
            + "\n  ".join(problems)
        )

    def test_legacy_allowlist_is_not_stale(self, upgraded_db):
        """Each allowlisted legacy column must still exist on upgraded DBs.

        When a cleanup migration finally drops one, its entry here must be
        removed so the allowlist cannot mask a future reintroduction.
        """
        upgraded = _snapshot(upgraded_db)
        stale = [
            f"{table}.{col}"
            for table, cols in LEGACY_UPGRADED_ONLY_COLUMNS.items()
            for col in cols
            if col not in upgraded.get(table, set())
        ]
        assert not stale, f"Allowlist entries no longer present: {stale}"


class TestStatsHistoryTablesOnFreshInstall:
    """Regression: fresh v2.4.0-v2.4.3 installs shipped without the stats
    history tables, so stats-service disabled persistence and the agent
    ingest endpoint 404'd ("websocket: bad handshake" loop on agents)."""

    def test_stats_history_tables_exist(self, fresh_db):
        snap = _snapshot(fresh_db)
        assert "container_stats_history" in snap
        assert "host_stats_history" in snap

    def test_container_stats_history_columns_match_migration_037(self, fresh_db):
        snap = _snapshot(fresh_db)
        assert snap["container_stats_history"] == {
            "id", "container_id", "host_id", "timestamp", "resolution",
            "cpu_percent", "memory_usage", "memory_limit", "network_bps",
        }
        assert snap["host_stats_history"] == {
            "id", "host_id", "timestamp", "resolution", "cpu_percent",
            "memory_percent", "memory_used_bytes", "memory_limit_bytes",
            "network_bps", "container_count",
        }

    def test_container_stats_host_index_exists(self, fresh_db):
        assert "idx_container_stats_host" in _index_names(
            fresh_db, "container_stats_history"
        )


class TestRepairMigration044:
    def test_broken_fresh_install_is_repaired_on_upgrade(self, tmp_path, monkeypatch):
        """A v2.4.0-v2.4.3 fresh install (full model schema, no stats history
        tables, stamped at 043) must gain the tables when migrations next run."""
        db_path = str(tmp_path / "broken.db")
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(bind=engine)
        engine.dispose()
        conn = sqlite3.connect(db_path)
        conn.execute("DROP TABLE container_stats_history")
        conn.execute("DROP TABLE host_stats_history")
        conn.commit()
        conn.close()
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
        command.stamp(cfg, "043_container_update_check_status")

        monkeypatch.setenv("DATABASE_PATH", db_path)
        assert run_migrations(), "migrate.py failed on a broken fresh install"

        snap = _snapshot(db_path)
        assert "container_stats_history" in snap
        assert "host_stats_history" in snap
        assert "idx_container_stats_host" in _index_names(
            db_path, "container_stats_history"
        )
