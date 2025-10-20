"""v1.1.3 to v2.0.0 comprehensive upgrade

Revision ID: 001_v1_to_v2
Revises:
Create Date: 2025-10-17 12:00:00

This migration handles the complete upgrade from DockMon v1.1.3 to v2.0.0.
It is fully defensive and checks for existing tables/columns before creating them.

CHANGES:
- GlobalSettings: Add missing v2 columns (unused_tag_retention_days, alert templates, update settings, etc.)
- Users: Add role, display_name, prefs, simplified_workflow, view_mode columns
- user_prefs table: New table for database-backed user preferences
- container_desired_states: Add custom_tags column
- event_logs: Add source column and indexes
- DockerHosts: Add tags, description columns
- container_http_health_checks: New table for HTTP/HTTPS health monitoring
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '001_v1_to_v2'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if a table exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _table_exists(table_name):
        return False
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _index_exists(index_name: str) -> bool:
    """Check if an index exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    for table_name in inspector.get_table_names():
        indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
        if index_name in indexes:
            return True
    return False


def upgrade() -> None:
    """
    Upgrade v1.1.3 database to v2.0.0 schema.

    This migration is fully defensive - it checks what exists before making changes.
    Safe to run multiple times (idempotent).
    """

    # ==================== GlobalSettings Table ====================
    # Add missing v2 columns

    if not _column_exists('global_settings', 'unused_tag_retention_days'):
        op.add_column('global_settings', sa.Column('unused_tag_retention_days', sa.Integer(), server_default='30'))

    if not _column_exists('global_settings', 'alert_template_metric'):
        op.add_column('global_settings', sa.Column('alert_template_metric', sa.Text(), nullable=True))

    if not _column_exists('global_settings', 'alert_template_state_change'):
        op.add_column('global_settings', sa.Column('alert_template_state_change', sa.Text(), nullable=True))

    if not _column_exists('global_settings', 'alert_template_health'):
        op.add_column('global_settings', sa.Column('alert_template_health', sa.Text(), nullable=True))

    if not _column_exists('global_settings', 'alert_template_update'):
        op.add_column('global_settings', sa.Column('alert_template_update', sa.Text(), nullable=True))

    if not _column_exists('global_settings', 'auto_update_enabled_default'):
        op.add_column('global_settings', sa.Column('auto_update_enabled_default', sa.Boolean(), server_default='0'))

    if not _column_exists('global_settings', 'update_check_interval_hours'):
        op.add_column('global_settings', sa.Column('update_check_interval_hours', sa.Integer(), server_default='24'))

    if not _column_exists('global_settings', 'update_check_time'):
        op.add_column('global_settings', sa.Column('update_check_time', sa.Text(), server_default='02:00'))

    if not _column_exists('global_settings', 'skip_compose_containers'):
        op.add_column('global_settings', sa.Column('skip_compose_containers', sa.Boolean(), server_default='1'))

    if not _column_exists('global_settings', 'health_check_timeout_seconds'):
        op.add_column('global_settings', sa.Column('health_check_timeout_seconds', sa.Integer(), server_default='120'))

    # Version tracking columns (for upgrade notice)
    if not _column_exists('global_settings', 'app_version'):
        op.add_column('global_settings', sa.Column('app_version', sa.String(), server_default='2.0.0'))
        # Set to 2.0.0 for all existing installations
        op.execute("UPDATE global_settings SET app_version = '2.0.0' WHERE id = 1")

    if not _column_exists('global_settings', 'upgrade_notice_dismissed'):
        op.add_column('global_settings', sa.Column('upgrade_notice_dismissed', sa.Boolean(), nullable=True))
        # Set to False for v1→v2 upgrades (show the upgrade notice)
        op.execute("UPDATE global_settings SET upgrade_notice_dismissed = 0 WHERE id = 1")

    if not _column_exists('global_settings', 'last_viewed_release_notes'):
        op.add_column('global_settings', sa.Column('last_viewed_release_notes', sa.String(), nullable=True))


    # ==================== Users Table ====================
    # Add v2 columns for future RBAC and user preferences
    # Use direct op.add_column() instead of batch mode for performance (no table rebuild)

    if _table_exists('users'):
        if not _column_exists('users', 'role'):
            op.add_column('users', sa.Column('role', sa.String(), server_default='owner'))

        if not _column_exists('users', 'display_name'):
            op.add_column('users', sa.Column('display_name', sa.String(), nullable=True))

        if not _column_exists('users', 'prefs'):
            op.add_column('users', sa.Column('prefs', sa.Text(), nullable=True))

        if not _column_exists('users', 'simplified_workflow'):
            op.add_column('users', sa.Column('simplified_workflow', sa.Boolean(), server_default='1'))
            # Enable simplified workflow for all existing v1 users (better UX)
            op.execute("UPDATE users SET simplified_workflow = 1")

        if not _column_exists('users', 'view_mode'):
            op.add_column('users', sa.Column('view_mode', sa.String(), server_default='standard'))

        # v2 renamed dashboard_layout -> dashboard_layout_v2
        if not _column_exists('users', 'dashboard_layout_v2'):
            op.add_column('users', sa.Column('dashboard_layout_v2', sa.Text(), nullable=True))

        # v2 added sidebar collapsed state
        if not _column_exists('users', 'sidebar_collapsed'):
            op.add_column('users', sa.Column('sidebar_collapsed', sa.Boolean(), server_default='0'))


    # ==================== user_prefs Table ====================
    # New table for database-backed user preferences (replaces localStorage)

    if not _table_exists('user_prefs'):
        op.create_table(
            'user_prefs',
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('theme', sa.String(), server_default='dark'),
            sa.Column('defaults_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('user_id')
        )


    # ==================== container_desired_states Table ====================
    # Add custom_tags column for tag support

    if not _column_exists('container_desired_states', 'custom_tags'):
        op.add_column('container_desired_states', sa.Column('custom_tags', sa.Text(), nullable=True))

    # Add update_policy column for per-container update protection
    if not _column_exists('container_desired_states', 'update_policy'):
        op.add_column('container_desired_states', sa.Column('update_policy', sa.Text(), nullable=True))


    # ==================== docker_hosts Table ====================
    # Add tags, description, and Phase 5 system information columns

    if _table_exists('docker_hosts'):
        if not _column_exists('docker_hosts', 'tags'):
            op.add_column('docker_hosts', sa.Column('tags', sa.Text(), nullable=True))

        if not _column_exists('docker_hosts', 'description'):
            op.add_column('docker_hosts', sa.Column('description', sa.Text(), nullable=True))

        # Phase 5 - System information columns
        if not _column_exists('docker_hosts', 'os_type'):
            op.add_column('docker_hosts', sa.Column('os_type', sa.String(), nullable=True))

        if not _column_exists('docker_hosts', 'os_version'):
            op.add_column('docker_hosts', sa.Column('os_version', sa.String(), nullable=True))

        if not _column_exists('docker_hosts', 'kernel_version'):
            op.add_column('docker_hosts', sa.Column('kernel_version', sa.String(), nullable=True))

        if not _column_exists('docker_hosts', 'docker_version'):
            op.add_column('docker_hosts', sa.Column('docker_version', sa.String(), nullable=True))

        if not _column_exists('docker_hosts', 'daemon_started_at'):
            op.add_column('docker_hosts', sa.Column('daemon_started_at', sa.String(), nullable=True))

        # System resources
        if not _column_exists('docker_hosts', 'total_memory'):
            op.add_column('docker_hosts', sa.Column('total_memory', sa.BigInteger(), nullable=True))

        if not _column_exists('docker_hosts', 'num_cpus'):
            op.add_column('docker_hosts', sa.Column('num_cpus', sa.Integer(), nullable=True))


    # ==================== event_logs Table ====================
    # Add source column and create indexes

    if _table_exists('event_logs'):
        if not _column_exists('event_logs', 'source'):
            op.add_column('event_logs', sa.Column('source', sa.String(), server_default='docker'))

    # Create indexes for faster event log queries
    if not _index_exists('idx_event_logs_category'):
        op.create_index('idx_event_logs_category', 'event_logs', ['category'])

    if not _index_exists('idx_event_logs_source'):
        op.create_index('idx_event_logs_source', 'event_logs', ['source'])


    # ==================== container_http_health_checks Table ====================
    # New table for HTTP/HTTPS health monitoring

    if not _table_exists('container_http_health_checks'):
        op.create_table(
            'container_http_health_checks',
            sa.Column('container_id', sa.Text(), nullable=False),
            sa.Column('host_id', sa.Text(), nullable=False),

            # Configuration
            sa.Column('enabled', sa.Boolean(), server_default='0', nullable=False),
            sa.Column('url', sa.Text(), nullable=False),
            sa.Column('method', sa.Text(), server_default='GET', nullable=False),
            sa.Column('expected_status_codes', sa.Text(), server_default='200', nullable=False),
            sa.Column('timeout_seconds', sa.Integer(), server_default='10', nullable=False),
            sa.Column('check_interval_seconds', sa.Integer(), server_default='60', nullable=False),
            sa.Column('follow_redirects', sa.Boolean(), server_default='1', nullable=False),
            sa.Column('verify_ssl', sa.Boolean(), server_default='1', nullable=False),

            # Advanced config (JSON)
            sa.Column('headers_json', sa.Text(), nullable=True),
            sa.Column('auth_config_json', sa.Text(), nullable=True),

            # State tracking
            sa.Column('current_status', sa.Text(), server_default='unknown', nullable=False),
            sa.Column('last_checked_at', sa.DateTime(), nullable=True),
            sa.Column('last_success_at', sa.DateTime(), nullable=True),
            sa.Column('last_failure_at', sa.DateTime(), nullable=True),
            sa.Column('consecutive_successes', sa.Integer(), server_default='0', nullable=False),
            sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False),
            sa.Column('last_response_time_ms', sa.Integer(), nullable=True),
            sa.Column('last_error_message', sa.Text(), nullable=True),

            # Auto-restart integration
            sa.Column('auto_restart_on_failure', sa.Boolean(), server_default='0', nullable=False),
            sa.Column('failure_threshold', sa.Integer(), server_default='3', nullable=False),
            sa.Column('success_threshold', sa.Integer(), server_default='1', nullable=False),

            # Metadata
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),

            sa.PrimaryKeyConstraint('container_id')
        )

        # Create indexes
        op.create_index('idx_http_health_enabled', 'container_http_health_checks', ['enabled'])
        op.create_index('idx_http_health_host', 'container_http_health_checks', ['host_id'])
        op.create_index('idx_http_health_status', 'container_http_health_checks', ['current_status'])


    # ==================== Fix Foreign Keys (CASCADE DELETE) ====================
    # Add CASCADE DELETE to auto_restart_configs so hosts can be deleted cleanly.
    # container_desired_states doesn't exist in v1, so it's created fresh with CASCADE DELETE.
    #
    # NOTE: This is a slow operation in SQLite (requires rebuilding the table).
    # The idempotent check in migrate.py prevents restart loops if this times out.

    if _table_exists('auto_restart_configs'):
        print("Adding CASCADE DELETE to auto_restart_configs (rebuilding table, may take 10-30 seconds)...")
        # SQLite doesn't support ALTER CONSTRAINT, must use batch mode (rebuilds entire table)
        # Note: We recreate the foreign key without dropping first because SQLite auto-generated
        # constraint names may not match 'auto_restart_configs_host_id_fkey'
        try:
            with op.batch_alter_table('auto_restart_configs', schema=None, recreate='always') as batch_op:
                # Batch mode with recreate='always' will rebuild table with new foreign keys
                # We don't need to explicitly drop/add - just declare the foreign key we want
                batch_op.create_foreign_key(
                    'fk_auto_restart_configs_host_id',
                    'docker_hosts',
                    ['host_id'],
                    ['id'],
                    ondelete='CASCADE'
                )
            print("✓ CASCADE DELETE added to auto_restart_configs")
        except Exception as e:
            print(f"WARNING: Could not add CASCADE DELETE to auto_restart_configs: {e}")
            print("Non-fatal - hosts with auto-restart configs cannot be deleted without manually removing configs first")
            # Non-fatal - make this a warning instead of fatal error

    print("CASCADE DELETE section complete, moving to update_policies...")

    # ==================== update_policies Table ====================
    # New table for configurable update validation rules

    if not _table_exists('update_policies'):
        print("Creating update_policies table...")
        op.create_table(
            'update_policies',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('category', sa.Text(), nullable=False),
            sa.Column('pattern', sa.Text(), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.UniqueConstraint('category', 'pattern', name='uq_update_policies_category_pattern')
        )
        print("✓ update_policies table created")
    else:
        print("update_policies table already exists, skipping creation")

    # Insert default validation patterns (separate from table creation)
    # Check if table is empty to handle case where Base.metadata.create_all() created empty table
    try:
        bind = op.get_bind()
        result = bind.execute(sa.text("SELECT COUNT(*) FROM update_policies")).scalar()

        if result == 0:
            print("Inserting default update validation policies...")
            # Table exists but is empty - insert default patterns
            op.execute("""
            INSERT INTO update_policies (category, pattern, enabled) VALUES
            ('databases', 'postgres', 1),
            ('databases', 'mysql', 1),
            ('databases', 'mariadb', 1),
            ('databases', 'mongodb', 1),
            ('databases', 'mongo', 1),
            ('databases', 'redis', 1),
            ('databases', 'sqlite', 1),
            ('databases', 'mssql', 1),
            ('databases', 'cassandra', 1),
            ('databases', 'influxdb', 1),
            ('databases', 'elasticsearch', 1),
            ('proxies', 'traefik', 1),
            ('proxies', 'nginx', 1),
            ('proxies', 'caddy', 1),
            ('proxies', 'haproxy', 1),
            ('proxies', 'envoy', 1),
            ('monitoring', 'grafana', 1),
            ('monitoring', 'prometheus', 1),
            ('monitoring', 'alertmanager', 1),
            ('monitoring', 'uptime-kuma', 1),
            ('critical', 'portainer', 1),
            ('critical', 'watchtower', 1),
            ('critical', 'dockmon', 1)
        """)
            print("✓ Default update validation policies inserted")
        else:
            print(f"Skipping update_policies insert - table already has {result} records")
    except Exception as e:
        print(f"WARNING: Could not insert default update_policies: {e}")
        print("Non-fatal - update validation will work but may not have default patterns")


def downgrade() -> None:
    """
    Downgrade v2.0.0 to v1.1.3 schema.

    Note: This removes v2 features. Data in v2-only columns will be lost.
    """

    # Drop container_http_health_checks table
    if _table_exists('container_http_health_checks'):
        if _index_exists('idx_http_health_status'):
            op.drop_index('idx_http_health_status', table_name='container_http_health_checks')
        if _index_exists('idx_http_health_host'):
            op.drop_index('idx_http_health_host', table_name='container_http_health_checks')
        if _index_exists('idx_http_health_enabled'):
            op.drop_index('idx_http_health_enabled', table_name='container_http_health_checks')
        op.drop_table('container_http_health_checks')

    # Drop update_policies table
    if _table_exists('update_policies'):
        op.drop_table('update_policies')

    # Remove update_policy column from container_desired_states
    if _column_exists('container_desired_states', 'update_policy'):
        with op.batch_alter_table('container_desired_states', schema=None) as batch_op:
            batch_op.drop_column('update_policy')

    # Drop indexes
    if _index_exists('idx_event_logs_source'):
        op.drop_index('idx_event_logs_source', table_name='event_logs')

    if _index_exists('idx_event_logs_category'):
        op.drop_index('idx_event_logs_category', table_name='event_logs')

    # Remove event_logs columns
    if _column_exists('event_logs', 'source'):
        with op.batch_alter_table('event_logs', schema=None) as batch_op:
            batch_op.drop_column('source')

    # Remove docker_hosts columns
    if _column_exists('docker_hosts', 'num_cpus'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            batch_op.drop_column('num_cpus')

    if _column_exists('docker_hosts', 'total_memory'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            batch_op.drop_column('total_memory')

    if _column_exists('docker_hosts', 'daemon_started_at'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            batch_op.drop_column('daemon_started_at')

    if _column_exists('docker_hosts', 'docker_version'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            batch_op.drop_column('docker_version')

    if _column_exists('docker_hosts', 'kernel_version'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            batch_op.drop_column('kernel_version')

    if _column_exists('docker_hosts', 'os_version'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            batch_op.drop_column('os_version')

    if _column_exists('docker_hosts', 'os_type'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            batch_op.drop_column('os_type')

    if _column_exists('docker_hosts', 'description'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            batch_op.drop_column('description')

    if _column_exists('docker_hosts', 'tags'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            batch_op.drop_column('tags')

    # Remove container_desired_states columns
    if _column_exists('container_desired_states', 'custom_tags'):
        with op.batch_alter_table('container_desired_states', schema=None) as batch_op:
            batch_op.drop_column('custom_tags')

    # Drop user_prefs table
    if _table_exists('user_prefs'):
        op.drop_table('user_prefs')

    # Remove users columns
    if _column_exists('users', 'sidebar_collapsed'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('sidebar_collapsed')

    if _column_exists('users', 'dashboard_layout_v2'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('dashboard_layout_v2')

    if _column_exists('users', 'view_mode'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('view_mode')

    if _column_exists('users', 'simplified_workflow'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('simplified_workflow')

    if _column_exists('users', 'prefs'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('prefs')

    if _column_exists('users', 'display_name'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('display_name')

    if _column_exists('users', 'role'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('role')

    # Remove global_settings v2 columns
    if _column_exists('global_settings', 'last_viewed_release_notes'):
        op.drop_column('global_settings', 'last_viewed_release_notes')

    if _column_exists('global_settings', 'upgrade_notice_dismissed'):
        op.drop_column('global_settings', 'upgrade_notice_dismissed')

    if _column_exists('global_settings', 'app_version'):
        op.drop_column('global_settings', 'app_version')

    if _column_exists('global_settings', 'health_check_timeout_seconds'):
        op.drop_column('global_settings', 'health_check_timeout_seconds')

    if _column_exists('global_settings', 'skip_compose_containers'):
        op.drop_column('global_settings', 'skip_compose_containers')

    if _column_exists('global_settings', 'update_check_time'):
        op.drop_column('global_settings', 'update_check_time')

    if _column_exists('global_settings', 'update_check_interval_hours'):
        op.drop_column('global_settings', 'update_check_interval_hours')

    if _column_exists('global_settings', 'auto_update_enabled_default'):
        op.drop_column('global_settings', 'auto_update_enabled_default')

    if _column_exists('global_settings', 'alert_template_update'):
        op.drop_column('global_settings', 'alert_template_update')

    if _column_exists('global_settings', 'alert_template_health'):
        op.drop_column('global_settings', 'alert_template_health')

    if _column_exists('global_settings', 'alert_template_state_change'):
        op.drop_column('global_settings', 'alert_template_state_change')

    if _column_exists('global_settings', 'alert_template_metric'):
        op.drop_column('global_settings', 'alert_template_metric')

    if _column_exists('global_settings', 'unused_tag_retention_days'):
        op.drop_column('global_settings', 'unused_tag_retention_days')
