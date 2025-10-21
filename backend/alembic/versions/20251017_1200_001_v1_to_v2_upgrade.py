"""v1.1.3 to v2.0.0 comprehensive upgrade

Revision ID: 001_v1_to_v2
Revises:
Create Date: 2025-10-17 12:00:00

This migration handles the complete upgrade from DockMon v1.1.3 to v2.0.0.
It is fully defensive and checks for existing tables/columns before creating them.

CHANGES:
- GlobalSettings: Add missing v2 columns (unused_tag_retention_days, alert_retention_days, alert templates, update settings, etc.)
- Users: Add role, display_name, prefs, simplified_workflow, view_mode columns
- user_prefs table: New table for database-backed user preferences
- container_desired_states: New table (includes custom_tags, web_ui_url, desired_state, etc.)
- event_logs: Add source column and indexes
- DockerHosts: Add tags, description columns
- container_http_health_checks: New table for HTTP/HTTPS health monitoring
- registry_credentials: New table for private registry authentication (v2.0.1+)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '001_v1_to_v2'
down_revision = None
branch_labels = None
depends_on = None


class MigrationHelper:
    """Helper class that reuses database inspector for efficiency."""

    def __init__(self):
        self.bind = op.get_bind()
        self.inspector = inspect(self.bind)
        self._table_cache = None

    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        if self._table_cache is None:
            self._table_cache = set(self.inspector.get_table_names())
        return table_name in self._table_cache

    def column_exists(self, table_name: str, column_name: str) -> bool:
        """Check if a column exists in a table."""
        if not self.table_exists(table_name):
            return False
        columns = [col['name'] for col in self.inspector.get_columns(table_name)]
        return column_name in columns

    def index_exists(self, index_name: str) -> bool:
        """Check if an index exists."""
        if self._table_cache is None:
            self._table_cache = set(self.inspector.get_table_names())
        for table_name in self._table_cache:
            indexes = [idx['name'] for idx in self.inspector.get_indexes(table_name)]
            if index_name in indexes:
                return True
        return False

    def add_column_if_missing(self, table_name: str, column: sa.Column):
        """Add a column if it doesn't exist."""
        if not self.column_exists(table_name, column.name):
            op.add_column(table_name, column)

    def add_columns_if_missing(self, table_name: str, columns: list):
        """Add multiple columns if they don't exist."""
        for column in columns:
            self.add_column_if_missing(table_name, column)

    def execute_if_zero_rows(self, table_name: str, insert_sql: str) -> bool:
        """Execute INSERT only if table is empty. Returns True if executed."""
        result = self.bind.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        if result == 0:
            op.execute(insert_sql)
            return True
        return False


def upgrade() -> None:
    """
    Upgrade v1.1.3 database to v2.0.0 schema.

    This migration is fully defensive - it checks what exists before making changes.
    Safe to run multiple times (idempotent).

    TABLE EXISTENCE IN v1.1.3:
    - global_settings: EXISTS (adding columns)
    - users: EXISTS (adding columns)
    - user_prefs: DOES NOT EXIST (new in v2)
    - container_desired_states: DOES NOT EXIST (new in v2, created by Base.metadata.create_all())
    - docker_hosts: EXISTS (adding columns)
    - event_logs: EXISTS (adding column + indexes)
    - container_http_health_checks: DOES NOT EXIST (new in v2)
    - auto_restart_configs: EXISTS (needs CASCADE DELETE fix)
    - update_policies: DOES NOT EXIST (new in v2)
    """
    helper = MigrationHelper()

    # ==================== GlobalSettings Table ====================
    # Add missing v2 columns (v1 table exists)

    global_settings_columns = [
        sa.Column('unused_tag_retention_days', sa.Integer(), server_default='30'),
        sa.Column('alert_template_metric', sa.Text(), nullable=True),
        sa.Column('alert_template_state_change', sa.Text(), nullable=True),
        sa.Column('alert_template_health', sa.Text(), nullable=True),
        sa.Column('alert_template_update', sa.Text(), nullable=True),
        sa.Column('auto_update_enabled_default', sa.Boolean(), server_default='0'),
        sa.Column('update_check_interval_hours', sa.Integer(), server_default='24'),
        sa.Column('update_check_time', sa.Text(), server_default='02:00'),
        sa.Column('skip_compose_containers', sa.Boolean(), server_default='1'),
        sa.Column('health_check_timeout_seconds', sa.Integer(), server_default='120'),
        sa.Column('alert_retention_days', sa.Integer(), server_default='90'),
        sa.Column('app_version', sa.String(), server_default='2.0.0'),
        sa.Column('upgrade_notice_dismissed', sa.Boolean(), nullable=True),
        sa.Column('last_viewed_release_notes', sa.String(), nullable=True),
    ]
    # Check if app_version exists before adding columns (to know if this is a v1→v2 upgrade)
    is_v1_upgrade = not helper.column_exists('global_settings', 'app_version')

    helper.add_columns_if_missing('global_settings', global_settings_columns)

    # Set version and upgrade notice for v1→v2 upgrades
    if is_v1_upgrade:
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.0.0', id=1)
        )
        op.execute(
            sa.text("UPDATE global_settings SET upgrade_notice_dismissed = :dismissed WHERE id = :id")
            .bindparams(dismissed=0, id=1)
        )


    # ==================== Users Table ====================
    # Add v2 columns for future RBAC and user preferences (v1 table exists)

    if helper.table_exists('users'):
        users_columns = [
            sa.Column('role', sa.String(), server_default='owner'),
            sa.Column('display_name', sa.String(), nullable=True),
            sa.Column('prefs', sa.Text(), nullable=True),
            sa.Column('simplified_workflow', sa.Boolean(), server_default='1'),
            sa.Column('view_mode', sa.String(), server_default='standard'),
            sa.Column('dashboard_layout_v2', sa.Text(), nullable=True),
            sa.Column('sidebar_collapsed', sa.Boolean(), server_default='0'),
        ]
        helper.add_columns_if_missing('users', users_columns)

        # Enable simplified workflow for all existing v1 users (better UX)
        op.execute(sa.text("UPDATE users SET simplified_workflow = 1"))


    # ==================== New Tables Created by Base.metadata.create_all() ====================
    # The following tables do NOT exist in v1.1.3 and are created by Base.metadata.create_all()
    # in migrate.py with all columns and CASCADE DELETE constraints already defined:
    # - user_prefs
    # - container_desired_states
    # - container_updates
    # - container_http_health_checks (also created below for completeness)
    # - update_policies (also created below for completeness)
    # - alert_rule_containers
    # - alert_annotations
    # - rule_runtime
    # - tag_assignments
    #
    # No migration code needed for these tables - they're already created with correct schema.


    # ==================== docker_hosts Table ====================
    # Add tags, description, and system information columns (v1 table exists)

    if helper.table_exists('docker_hosts'):
        docker_hosts_columns = [
            sa.Column('tags', sa.Text(), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            # Phase 5 - System information columns
            sa.Column('os_type', sa.String(), nullable=True),
            sa.Column('os_version', sa.String(), nullable=True),
            sa.Column('kernel_version', sa.String(), nullable=True),
            sa.Column('docker_version', sa.String(), nullable=True),
            sa.Column('daemon_started_at', sa.String(), nullable=True),
            # System resources
            sa.Column('total_memory', sa.BigInteger(), nullable=True),
            sa.Column('num_cpus', sa.Integer(), nullable=True),
        ]
        helper.add_columns_if_missing('docker_hosts', docker_hosts_columns)


    # ==================== event_logs Table ====================
    # Add source column and create indexes (v1 table exists)

    if helper.table_exists('event_logs'):
        helper.add_column_if_missing('event_logs', sa.Column('source', sa.String(), server_default='docker'))

    # Create indexes for faster event log queries
    if not helper.index_exists('idx_event_logs_category'):
        op.create_index('idx_event_logs_category', 'event_logs', ['category'])

    if not helper.index_exists('idx_event_logs_source'):
        op.create_index('idx_event_logs_source', 'event_logs', ['source'])


    # container_http_health_checks is created by Base.metadata.create_all() with all
    # columns, indexes, and CASCADE DELETE - no migration code needed


    # ==================== Fix Foreign Keys (CASCADE DELETE) ====================
    # Add CASCADE DELETE to auto_restart_configs so hosts can be deleted cleanly.
    # v1 databases have unnamed foreign key constraints, so we use recreate='always' to
    # rebuild the table with the correct named constraint with CASCADE DELETE.
    #
    # NOTE: This is a slow operation in SQLite (requires rebuilding the entire table).
    # The idempotent check in migrate.py prevents restart loops if this times out.

    if helper.table_exists('auto_restart_configs'):
        # SQLite doesn't support ALTER CONSTRAINT, must use batch mode (rebuilds entire table)
        with op.batch_alter_table('auto_restart_configs', schema=None, recreate='always') as batch_op:
            batch_op.create_foreign_key(
                'fk_auto_restart_configs_host_id',
                'docker_hosts',
                ['host_id'],
                ['id'],
                ondelete='CASCADE'
            )


    # ==================== alerts_v2 Table ====================
    # Add suppressed_by_blackout column for blackout window support
    # Add retry tracking columns for exponential backoff (v2.0.1+)
    # Table created by Base.metadata.create_all() for fresh installs, but we need
    # to add the columns for any existing v2.0.x installations that don't have them yet

    if helper.table_exists('alerts_v2'):
        helper.add_columns_if_missing('alerts_v2', [
            sa.Column('suppressed_by_blackout', sa.Boolean(), server_default='0', nullable=False),
            sa.Column('last_notification_attempt_at', sa.DateTime(), nullable=True),
            sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        ])


    # ==================== update_policies Table ====================
    # Table created by Base.metadata.create_all(), but we need to populate default patterns

    # Insert default validation patterns
    # Table may exist but be empty if created by Base.metadata.create_all()
    # Wrapped in try/except to handle duplicate key errors on retry
    try:
        if helper.execute_if_zero_rows('update_policies', """
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
            ('critical', 'dockmon', 1),
            ('critical', 'komodo', 1)
        """):
            pass  # Successfully inserted default policies
    except Exception as e:
        # Non-fatal: Table may already have policies from previous migration attempt
        # or Base.metadata.create_all() may have populated it
        pass


def downgrade() -> None:
    """
    Downgrade not supported.

    V2 is a major upgrade from V1 with significant schema changes.
    Downgrading would result in data loss and is not supported.
    """
    raise NotImplementedError("Downgrade from V2 to V1 is not supported")
