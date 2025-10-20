#!/usr/bin/env python3
"""
Standalone database migration script.

This script runs database migrations BEFORE the application starts.
Handles both fresh v2 installations and v1→v2 upgrades.

Workflow:
1. Create missing tables (handles fresh installs)
2. Run Alembic migrations (handles v1→v2 upgrades)

Usage:
    python migrate.py

Exit codes:
    0: Migrations completed successfully
    1: Migration failed
"""

import sys
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_migrations():
    """
    Run database migrations to upgrade schema to latest version.

    Steps:
    1. Acquire migration lock (prevents concurrent migrations)
    2. Create tables that don't exist (fresh install scenario)
    3. Run Alembic migrations (v1→v2 upgrade scenario)
    4. Release lock

    Returns:
        bool: True if successful, False otherwise
    """
    import fcntl
    import time

    lock_file = None
    try:
        from sqlalchemy import create_engine
        from database import Base  # Import ORM Base to get table definitions
        from alembic.config import Config
        from alembic import command

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

        # Acquire exclusive lock to prevent concurrent migrations
        lock_path = os.path.join(data_dir, '.migration.lock')
        lock_file = open(lock_path, 'w')

        logger.info("Waiting for migration lock...")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info("✓ Migration lock acquired")
        except IOError:
            # Another process is running migrations, wait for it
            logger.info("Another migration in progress, waiting...")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            logger.info("✓ Migration lock acquired")

            # Check if migration was already completed by other process
            # If alembic_version table exists and has 001_v1_to_v2, skip
            try:
                engine_check = create_engine(f"sqlite:///{db_path}")
                with engine_check.connect() as conn:
                    result = conn.execute("SELECT version_num FROM alembic_version LIMIT 1")
                    version = result.scalar()
                    if version:
                        logger.info(f"Migration already completed by another process (version: {version})")
                        logger.info("✓ All migrations completed successfully")
                        return True
            except:
                # Table doesn't exist or error checking - proceed with migration
                pass

        # Create SQLAlchemy engine
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False}
        )
        logger.info(f"Connected to database: {db_path}")

        # Step 1: Create tables that don't exist (handles fresh v2 installs)
        logger.info("Creating missing tables (if any)...")
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Table creation complete")

        # Step 2: Run Alembic migrations (handles v1→v2 upgrades)
        # Verify alembic directory exists
        if not os.path.exists(alembic_dir):
            logger.warning(f"Alembic directory not found at {alembic_dir}, skipping Alembic migrations")
            logger.info("✓ Migration completed (no Alembic migrations available)")
            return True

        # Create Alembic configuration object
        alembic_cfg = Config(alembic_ini)

        # Override configuration to use current database path
        alembic_cfg.set_main_option("script_location", alembic_dir)
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        # Run all pending migrations to bring database to latest version ("head")
        logger.info("Running Alembic migrations...")
        command.upgrade(alembic_cfg, "head")
        logger.info("✓ Alembic migrations complete")

        logger.info("✓ All migrations completed successfully")
        return True

    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Ensure all required packages are installed")
        return False
    except Exception as e:
        logger.error(f"Migration error: {e}", exc_info=True)
        return False
    finally:
        # Release lock
        if lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                logger.debug("Migration lock released")
            except:
                pass


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
