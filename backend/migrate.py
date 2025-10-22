#!/usr/bin/env python3
"""
Standalone database migration script with rock-solid upgrade strategy.

This script runs database migrations BEFORE the application starts.
Handles fresh installs, version upgrades, and idempotent restarts.

Workflow:
1. Detect: Fresh install OR existing database
2. Fresh install: Create tables + stamp as HEAD (no migrations run)
3. Existing: Migrate old revision IDs + run pending migrations + validate schema
4. Idempotent: Container restarts detect "already at latest" instantly

Exit codes:
    0: Migrations completed successfully
    1: Migration failed

Design Philosophy (Per CLAUDE.md):
- Separate fresh install from upgrade paths (no defensive checks needed)
- Version-aware idempotency (compare current vs HEAD, not just "exists")
- Automatic backup before migrations
- Schema validation after migrations
- Clear logging with migration plan
- One migration file per version release
"""

import sys
import os
import logging
import shutil
from sqlalchemy import create_engine, text, inspect

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _alembic_version_table_exists(engine) -> bool:
    """
    Check if alembic_version table exists.

    Returns:
        True if table exists (indicates existing database with migrations)
        False if table doesn't exist (indicates fresh install)
    """
    inspector = inspect(engine)
    return 'alembic_version' in inspector.get_table_names()


def _get_current_version(engine) -> str:
    """
    Get current database version from alembic_version table.

    Args:
        engine: SQLAlchemy engine

    Returns:
        Current revision ID (e.g., '002_v2_0_1') or None if not found
    """
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        return result.scalar()


def _get_head_revision(alembic_cfg) -> str:
    """
    Get the HEAD (latest) revision from Alembic migration files.

    Args:
        alembic_cfg: Alembic configuration object

    Returns:
        HEAD revision ID (e.g., '002_v2_0_1')
    """
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(alembic_cfg)
    return script.get_current_head()


def _migrate_old_revision_ids(engine):
    """
    One-time fix for existing installations with old revision IDs.
    Maps old sequential IDs to new version-aligned IDs.

    This ensures smooth upgrades for users on v2.0.0 when we changed
    the naming convention from '001_v1_to_v2' to '001_v2_0_0'.

    Args:
        engine: SQLAlchemy engine
    """
    # Map old revision IDs to new version-aligned IDs
    migration_map = {
        '001_v1_to_v2': '001_v2_0_0',
        '002_add_changelog': '002_v2_0_1',
    }

    with engine.connect() as conn:
        result = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        current = result.scalar()

        if current and current in migration_map:
            new_id = migration_map[current]
            logger.info(f"🔄 Updating revision ID: {current} → {new_id}")
            conn.execute(
                text("UPDATE alembic_version SET version_num = :new_id")
                .bindparams(new_id=new_id)
            )
            conn.commit()
            logger.info("✓ Revision ID updated")


def _log_migration_plan(alembic_cfg, current: str, target: str):
    """
    Show user what migrations will be applied.

    Args:
        alembic_cfg: Alembic configuration object
        current: Current revision ID
        target: Target revision ID
    """
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_cfg)

    # Get list of revisions between current and target
    try:
        revisions = list(script.iterate_revisions(current, target))
    except Exception as e:
        logger.warning(f"Could not determine migration plan: {e}")
        return

    if revisions:
        logger.info(f"📋 Migration plan ({len(revisions)} step(s)):")
        for rev in reversed(revisions):  # Show in execution order
            # Extract version from revision ID (e.g., '002_v2_0_1' → 'v2.0.1')
            if '_' in rev.revision:
                version = rev.revision.split('_', 1)[1].replace('_', '.')
            else:
                version = rev.revision

            # Get first line of docstring as description
            doc = rev.doc.split('\n')[0] if rev.doc else 'No description'
            logger.info(f"   → {version}: {doc}")


def _validate_schema(engine, version: str):
    """
    Validate expected schema exists for given version.

    This provides an extra safety check that migrations actually created
    the expected tables/columns. Catches migration bugs early.

    Args:
        engine: SQLAlchemy engine
        version: Revision ID to validate (e.g., '002_v2_0_1')

    Raises:
        RuntimeError: If expected schema is missing
    """
    inspector = inspect(engine)

    # Version-specific validation rules
    # Add new rules here when creating new migrations
    validations = {
        '001_v2_0_0': {
            'tables': ['containers', 'container_updates', 'docker_hosts', 'event_logs'],
        },
        '002_v2_0_1': {
            'container_updates_columns': ['changelog_url', 'changelog_source', 'changelog_checked_at'],
        },
        # Add validations for future versions here:
        # '003_v2_0_2': {
        #     'tables': ['backup_configs'],
        #     'container_updates_columns': ['last_backup_at'],
        # },
    }

    if version in validations:
        rules = validations[version]

        # Validate tables exist
        if 'tables' in rules:
            existing_tables = set(inspector.get_table_names())
            required = set(rules['tables'])
            missing = required - existing_tables
            if missing:
                raise RuntimeError(f"Schema validation failed: Missing tables: {missing}")

        # Validate columns exist (format: {table_name}_columns: [col1, col2, ...])
        for key, required_cols in rules.items():
            if key.endswith('_columns'):
                table_name = key.replace('_columns', '')

                # Check table exists first
                if table_name not in inspector.get_table_names():
                    raise RuntimeError(f"Schema validation failed: Table '{table_name}' does not exist")

                existing_cols = {col['name'] for col in inspector.get_columns(table_name)}
                required = set(required_cols)
                missing = required - existing_cols
                if missing:
                    raise RuntimeError(f"Schema validation failed: Missing columns in {table_name}: {missing}")

    logger.info(f"✓ Schema validation passed for version: {version}")


def _handle_fresh_install(engine, alembic_cfg) -> bool:
    """
    Handle fresh installation: Create tables with latest schema, stamp as HEAD.

    Fresh installs don't need to run migrations - we create all tables at once
    with the latest schema, then stamp the database as HEAD.

    Args:
        engine: SQLAlchemy engine
        alembic_cfg: Alembic configuration object

    Returns:
        True on success, False on failure
    """
    from database import Base
    from alembic import command

    logger.info("🆕 Fresh installation detected")

    try:
        # Create all tables with current schema
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Tables created")

        # Get HEAD revision
        head_revision = _get_head_revision(alembic_cfg)

        # Stamp database as HEAD without running migrations
        logger.info(f"Stamping database at version: {head_revision}")
        command.stamp(alembic_cfg, head_revision)
        logger.info(f"✓ Database initialized at version: {head_revision}")

        # Validate schema was created correctly
        _validate_schema(engine, head_revision)

        return True

    except Exception as e:
        logger.error(f"❌ Fresh installation failed: {e}", exc_info=True)
        return False


def _handle_upgrade(engine, alembic_cfg, db_path: str) -> bool:
    """
    Handle existing database: Check version and run pending migrations.

    Upgrade path:
    1. Migrate old revision IDs (one-time fix)
    2. Compare current vs HEAD
    3. If already at HEAD, skip (idempotent)
    4. Otherwise: backup → migrate → validate → cleanup

    Args:
        engine: SQLAlchemy engine
        alembic_cfg: Alembic configuration object
        db_path: Path to database file (for backup)

    Returns:
        True on success, False on failure
    """
    from alembic import command

    try:
        # ONE-TIME FIX: Update old revision IDs to new naming convention
        _migrate_old_revision_ids(engine)

        # Get current and target versions
        current_version = _get_current_version(engine)
        head_version = _get_head_revision(alembic_cfg)

        logger.info(f"📊 Database version: {current_version}")
        logger.info(f"📊 Target version: {head_version}")

        # Already at latest? (Idempotent check)
        if current_version == head_version:
            logger.info("✓ Already at latest version")

            # Clean up V1 alert tables if they still exist (legacy cleanup)
            _cleanup_v1_tables(engine)

            return True

        # Show migration plan
        _log_migration_plan(alembic_cfg, current_version, head_version)

        # Create backup before migration
        backup_path = f"{db_path}.backup-{current_version}-to-{head_version}"
        logger.info(f"💾 Creating backup: {backup_path}")
        try:
            shutil.copy2(db_path, backup_path)
            logger.info("✓ Backup created")
        except Exception as e:
            logger.error(f"❌ Backup creation failed: {e}")
            logger.error("Aborting migration - cannot proceed without backup")
            return False

        # Run migrations
        logger.info("🔄 Applying migrations...")
        try:
            command.upgrade(alembic_cfg, "head")
            logger.info("✓ Migrations completed successfully")

            # Validate schema
            _validate_schema(engine, head_version)

            # Clean up V1 alert tables (legacy cleanup)
            _cleanup_v1_tables(engine)

            # Clean up backup on success
            try:
                os.remove(backup_path)
                logger.info("✓ Backup removed (migration successful)")
            except Exception as e:
                logger.warning(f"Could not remove backup: {e}")
                logger.info(f"Manual cleanup: rm {backup_path}")

            return True

        except Exception as e:
            logger.error(f"❌ Migration failed: {e}", exc_info=True)
            logger.error(f"💾 Backup preserved at: {backup_path}")
            logger.error(f"To restore: docker cp {backup_path} dockmon:/app/data/dockmon.db")
            return False

    except Exception as e:
        logger.error(f"❌ Upgrade process failed: {e}", exc_info=True)
        return False


def _cleanup_v1_tables(engine):
    """
    Clean up legacy V1 alert tables (may exist on upgraded systems).

    V1 used 'alert_rules' and 'alert_rule_containers' tables.
    V2 uses 'alerts_v2' and 'alert_rules_v2' tables.

    This cleanup is safe to run multiple times (idempotent).

    Args:
        engine: SQLAlchemy engine
    """
    try:
        with engine.connect() as conn:
            # Check if V1 tables exist
            result = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('alert_rules', 'alert_rule_containers')"
            ))
            v1_tables = result.fetchall()

            if v1_tables:
                logger.info(f"Dropping legacy V1 alert tables: {[t[0] for t in v1_tables]}...")
                conn.execute(text("DROP TABLE IF EXISTS alert_rule_containers"))
                conn.execute(text("DROP TABLE IF EXISTS alert_rules"))
                conn.commit()
                logger.info("✓ V1 alert tables dropped")
    except Exception as e:
        logger.warning(f"Could not clean up V1 tables (non-fatal): {e}")


def run_migrations() -> bool:
    """
    Run database migrations to upgrade schema to latest version.

    Rock-solid migration strategy:
    1. Detect: Fresh install OR existing database
    2. Fresh install: create_all() → stamp HEAD (no migrations run)
    3. Existing: Compare current vs HEAD → Run pending migrations only
    4. Idempotent: Container restarts see current == head and skip instantly

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        from alembic.config import Config

        # Get the directory where this script is located (/app/backend in container)
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        alembic_dir = os.path.join(backend_dir, "alembic")
        alembic_ini = os.path.join(backend_dir, "alembic.ini")

        # Database path
        db_path = os.environ.get('DATABASE_PATH', '/app/data/dockmon.db')

        # Ensure data directory exists
        data_dir = os.path.dirname(db_path)
        os.makedirs(data_dir, exist_ok=True)
        logger.info(f"Data directory: {data_dir}")

        # Create SQLAlchemy engine
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30}
        )
        logger.info(f"Connected to database: {db_path}")

        # Verify alembic directory exists
        if not os.path.exists(alembic_dir):
            logger.warning(f"Alembic directory not found at {alembic_dir}, skipping migrations")
            logger.info("✓ Migration completed (no Alembic migrations available)")
            return True

        # Create Alembic configuration object
        alembic_cfg = Config(alembic_ini)
        alembic_cfg.set_main_option("script_location", alembic_dir)
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        # DETECT: Fresh install or existing database?
        if not _alembic_version_table_exists(engine):
            # Fresh install path
            return _handle_fresh_install(engine, alembic_cfg)
        else:
            # Upgrade path
            return _handle_upgrade(engine, alembic_cfg, db_path)

    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Ensure all required packages are installed")
        return False
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        return False


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("DockMon Database Migration")
    logger.info("=" * 60)

    success = run_migrations()

    if success:
        logger.info("Migration completed successfully")
        sys.exit(0)
    else:
        logger.error("Migration failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
