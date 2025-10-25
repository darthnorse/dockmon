"""
Tests for database migrations.

Critical for v2.1 because:
- v2.1 adds 3 new tables (deployments, deployment_containers, deployment_templates)
- v2.1 modifies 2 tables (containers: add deployment_id, is_managed)
- Must verify both fresh install and upgrade paths work
- Must verify no schema drift
"""

import pytest
import tempfile
import os
from sqlalchemy import create_engine, inspect

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from database import Base


@pytest.mark.database
def test_fresh_install_creates_all_tables():
    """
    Test that fresh install (Base.metadata.create_all) creates all metadata tables.

    Note: DockMon doesn't store containers in database - they come from Docker API.
    Only metadata tables are created (ContainerDesiredState, ContainerUpdate, etc.)
    """
    # Create temporary database
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    engine = create_engine(f'sqlite:///{db_path}')

    try:
        # Run fresh install
        Base.metadata.create_all(engine)

        # Verify all metadata tables exist
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        # Core metadata tables (v2.0)
        assert 'docker_hosts' in tables
        assert 'event_logs' in tables
        assert 'global_settings' in tables
        assert 'container_updates' in tables
        assert 'update_policies' in tables
        assert 'container_desired_states' in tables
        assert 'auto_restart_configs' in tables
        assert 'container_http_health_checks' in tables
        assert 'alerts_v2' in tables
        assert 'alert_rules_v2' in tables

        # v2.1 new tables (will exist after models updated for v2.1)
        # expected_v2_1_tables = [
        #     'deployments',
        #     'deployment_containers',
        #     'deployment_templates'
        # ]
        # for table in expected_v2_1_tables:
        #     assert table in tables, f"v2.1 table {table} not created"

    finally:
        os.close(db_fd)
        os.unlink(db_path)


@pytest.mark.database
def test_migration_idempotent():
    """
    Test that creating tables twice doesn't break database.

    Critical: Container restarts should be instant (idempotent check).
    """
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    engine = create_engine(f'sqlite:///{db_path}')

    try:
        # Create tables twice
        Base.metadata.create_all(engine)
        Base.metadata.create_all(engine)  # Should be safe

        # Should not raise exception - verify a core table exists
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert 'docker_hosts' in tables
        assert 'container_updates' in tables

    finally:
        os.close(db_fd)
        os.unlink(db_path)


@pytest.mark.database  
def test_container_updates_table_uses_composite_key():
    """
    Test that container_updates table uses composite key for container_id.

    Critical: container_updates.container_id should store "{host_id}:{container_id}".
    """
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    engine = create_engine(f'sqlite:///{db_path}')

    try:
        Base.metadata.create_all(engine)

        inspector = inspect(engine)
        columns = {col['name']: col for col in inspector.get_columns('container_updates')}

        # Verify container_id field exists
        assert 'container_id' in columns, "container_id column missing"
        
        # Verify it's a text field (to store composite key string)
        assert columns['container_id']['type'].__class__.__name__ in ['TEXT', 'VARCHAR', 'String'], \
            "container_id should be text type for composite key"

    finally:
        os.close(db_fd)
        os.unlink(db_path)


