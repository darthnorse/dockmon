"""v2.0.0 upgrade - Major upgrade from v1.1.3

Revision ID: 001_v2_0_0
Revises: None
Create Date: 2025-10-17 12:00:00

This migration handles the complete upgrade from DockMon v1.1.3 to v2.0.0.
It explicitly creates all new v2 tables and adds columns to existing v1 tables.

CHANGES IN v2.0.0:
- GlobalSettings: Add v2 columns (unused_tag_retention_days, alert templates, update settings, app_version, etc.)
- Users: Add role, display_name, prefs, simplified_workflow, view_mode columns
- DockerHosts: Add tags, description, system info columns
- EventLogs: Add source column and indexes
- AutoRestartConfigs: Fix foreign key to use CASCADE DELETE

NEW TABLES IN v2.0.0:
- user_prefs: User preferences (theme, defaults)
- container_desired_states: Desired state management
- batch_jobs, batch_job_items: Bulk operations
- container_updates: Update tracking (v2.0.0 WITHOUT changelog columns)
- container_http_health_checks: HTTP/HTTPS health monitoring
- update_policies: Update validation patterns with defaults
- notification_channels: Notification configuration
- alert_rules_v2: New alerting engine rules
- alerts_v2: New alerting engine instances (v2.0.0 WITH suppressed_by_blackout, WITHOUT retry columns)
- alert_annotations: User annotations on alerts
- rule_runtime: Rule evaluation state
- rule_evaluations: Rule evaluation history
- notification_retries: Notification retry queue
- tags: Tag definitions
- tag_assignments: Tag to entity assignments
- registry_credentials: Private registry authentication
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '001_v2_0_0'
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
        # Validate table_name is a valid SQL identifier (prevent SQL injection)
        if not table_name.replace('_', '').isalnum():
            raise ValueError(f"Invalid table name: {table_name}")

        # Note: SQLite doesn't support parameterized table names, so we validate instead
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

    EXISTING TABLES IN v1.1.3:
    - global_settings: EXISTS (adding columns)
    - users: EXISTS (adding columns)
    - docker_hosts: EXISTS (adding columns)
    - event_logs: EXISTS (adding column + indexes)
    - auto_restart_configs: EXISTS (needs CASCADE DELETE fix)

    NEW TABLES IN v2.0.0:
    All created explicitly by this migration with proper schemas.
    """
    helper = MigrationHelper()

    # ==================== ALTER EXISTING v1 TABLES ====================

    # GlobalSettings Table: Add v2 columns
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

    # Set upgrade notice for v1→v2 upgrades
    if is_v1_upgrade:
        op.execute(
            sa.text("UPDATE global_settings SET upgrade_notice_dismissed = :dismissed WHERE id = :id")
            .bindparams(dismissed=0, id=1)
        )

    # Users Table: Add v2 columns
    if helper.table_exists('users'):
        users_columns = [
            sa.Column('role', sa.String(), server_default='admin'),  # Changed from 'owner' in v2.1.8
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

    # DockerHosts Table: Add tags, description, and system information columns
    if helper.table_exists('docker_hosts'):
        docker_hosts_columns = [
            sa.Column('tags', sa.Text(), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            # System information columns
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

    # EventLogs Table: Add source column
    if helper.table_exists('event_logs'):
        helper.add_column_if_missing('event_logs', sa.Column('source', sa.String(), server_default='docker'))

    # Create indexes for faster event log queries
    if not helper.index_exists('idx_event_logs_category'):
        op.create_index('idx_event_logs_category', 'event_logs', ['category'])

    if not helper.index_exists('idx_event_logs_source'):
        op.create_index('idx_event_logs_source', 'event_logs', ['source'])

    # AutoRestartConfigs: Fix foreign key to use CASCADE DELETE
    # SQLite doesn't support ALTER CONSTRAINT, must use batch mode (rebuilds entire table)
    if helper.table_exists('auto_restart_configs'):
        with op.batch_alter_table('auto_restart_configs', schema=None, recreate='always') as batch_op:
            batch_op.create_foreign_key(
                'fk_auto_restart_configs_host_id',
                'docker_hosts',
                ['host_id'],
                ['id'],
                ondelete='CASCADE'
            )

    # ==================== CREATE NEW v2.0.0 TABLES ====================

    # User Preferences Table
    if not helper.table_exists('user_prefs'):
        op.create_table(
            'user_prefs',
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
            sa.Column('theme', sa.String(), server_default='dark'),
            sa.Column('defaults_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )

    # Container Desired States Table
    if not helper.table_exists('container_desired_states'):
        op.create_table(
            'container_desired_states',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('host_id', sa.String(), sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('container_id', sa.String(), nullable=False),
            sa.Column('container_name', sa.String(), nullable=False),
            sa.Column('desired_state', sa.String(), server_default='unspecified'),
            sa.Column('custom_tags', sa.Text(), nullable=True),
            sa.Column('web_ui_url', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )

    # Batch Jobs Tables
    if not helper.table_exists('batch_jobs'):
        op.create_table(
            'batch_jobs',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
            sa.Column('scope', sa.String(), nullable=False),
            sa.Column('action', sa.String(), nullable=False),
            sa.Column('params', sa.Text(), nullable=True),
            sa.Column('status', sa.String(), server_default='queued'),
            sa.Column('total_items', sa.Integer(), server_default='0'),
            sa.Column('completed_items', sa.Integer(), server_default='0'),
            sa.Column('success_items', sa.Integer(), server_default='0'),
            sa.Column('error_items', sa.Integer(), server_default='0'),
            sa.Column('skipped_items', sa.Integer(), server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
        )

    if not helper.table_exists('batch_job_items'):
        op.create_table(
            'batch_job_items',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('job_id', sa.String(), sa.ForeignKey('batch_jobs.id'), nullable=False),
            sa.Column('container_id', sa.String(), nullable=False),
            sa.Column('container_name', sa.String(), nullable=False),
            sa.Column('host_id', sa.String(), nullable=False),
            sa.Column('host_name', sa.String(), nullable=True),
            sa.Column('status', sa.String(), server_default='queued'),
            sa.Column('message', sa.Text(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
        )

    # Container Updates Table (v2.0.0 WITHOUT changelog columns - those are v2.0.1)
    if not helper.table_exists('container_updates'):
        op.create_table(
            'container_updates',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('container_id', sa.Text(), nullable=False, unique=True),
            sa.Column('host_id', sa.Text(), sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'), nullable=False),
            # Current state
            sa.Column('current_image', sa.Text(), nullable=False),
            sa.Column('current_digest', sa.Text(), nullable=False),
            # Latest available
            sa.Column('latest_image', sa.Text(), nullable=True),
            sa.Column('latest_digest', sa.Text(), nullable=True),
            sa.Column('update_available', sa.Boolean(), server_default='0', nullable=False),
            # Tracking settings
            sa.Column('floating_tag_mode', sa.Text(), server_default='exact', nullable=False),
            sa.Column('auto_update_enabled', sa.Boolean(), server_default='0', nullable=False),
            sa.Column('update_policy', sa.Text(), nullable=True),
            sa.Column('health_check_strategy', sa.Text(), server_default='docker', nullable=False),
            sa.Column('health_check_url', sa.Text(), nullable=True),
            # Metadata
            sa.Column('last_checked_at', sa.DateTime(), nullable=True),
            sa.Column('last_updated_at', sa.DateTime(), nullable=True),
            sa.Column('registry_url', sa.Text(), nullable=True),
            sa.Column('platform', sa.Text(), nullable=True),
            # NOTE: changelog columns (changelog_url, changelog_source, changelog_checked_at)
            # are NOT in v2.0.0 - they will be added in migration 002_v2_0_1
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )

    # Container HTTP Health Checks Table
    if not helper.table_exists('container_http_health_checks'):
        op.create_table(
            'container_http_health_checks',
            sa.Column('container_id', sa.Text(), primary_key=True),
            sa.Column('host_id', sa.Text(), sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'), nullable=False),
            # Configuration
            sa.Column('enabled', sa.Boolean(), server_default='0', nullable=False),
            sa.Column('url', sa.Text(), nullable=False),
            sa.Column('method', sa.Text(), server_default='GET', nullable=False),
            sa.Column('expected_status_codes', sa.Text(), server_default='200', nullable=False),
            sa.Column('timeout_seconds', sa.Integer(), server_default='10', nullable=False),
            sa.Column('check_interval_seconds', sa.Integer(), server_default='60', nullable=False),
            sa.Column('follow_redirects', sa.Boolean(), server_default='1', nullable=False),
            sa.Column('verify_ssl', sa.Boolean(), server_default='1', nullable=False),
            # Advanced config
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
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('idx_http_health_enabled', 'container_http_health_checks', ['enabled'])
        op.create_index('idx_http_health_host', 'container_http_health_checks', ['host_id'])
        op.create_index('idx_http_health_status', 'container_http_health_checks', ['current_status'])

    # Update Policies Table
    if not helper.table_exists('update_policies'):
        op.create_table(
            'update_policies',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('category', sa.Text(), nullable=False),
            sa.Column('pattern', sa.Text(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default='1', nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        # Populate default validation patterns (only if table is empty)
        try:
            helper.execute_if_zero_rows('update_policies', """
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
            """)
        except Exception:
            # Non-fatal: Table may already have policies
            pass

    # Notification Channels Table
    if not helper.table_exists('notification_channels'):
        op.create_table(
            'notification_channels',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.String(), nullable=False, unique=True),
            sa.Column('type', sa.String(), nullable=False),
            sa.Column('config', sa.JSON(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )

    # Alert Rules v2 Table
    if not helper.table_exists('alert_rules_v2'):
        op.create_table(
            'alert_rules_v2',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('scope', sa.String(), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default='1'),
            # Selectors
            sa.Column('host_selector_json', sa.Text(), nullable=True),
            sa.Column('container_selector_json', sa.Text(), nullable=True),
            sa.Column('labels_json', sa.Text(), nullable=True),
            # Conditions
            sa.Column('metric', sa.String(), nullable=True),
            sa.Column('operator', sa.String(), nullable=True),
            sa.Column('threshold', sa.Float(), nullable=True),
            sa.Column('duration_seconds', sa.Integer(), nullable=True),
            sa.Column('occurrences', sa.Integer(), nullable=True),
            # Clearing
            sa.Column('clear_threshold', sa.Float(), nullable=True),
            sa.Column('clear_duration_seconds', sa.Integer(), nullable=True),
            # Behavior
            sa.Column('severity', sa.String(), nullable=False),
            sa.Column('cooldown_seconds', sa.Integer(), server_default='300'),
            sa.Column('depends_on_json', sa.Text(), nullable=True),
            sa.Column('auto_resolve', sa.Boolean(), server_default='0'),
            sa.Column('suppress_during_updates', sa.Boolean(), server_default='0'),
            # Notifications
            sa.Column('notify_channels_json', sa.Text(), nullable=True),
            sa.Column('custom_template', sa.Text(), nullable=True),
            # Lifecycle
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('created_by', sa.String(), nullable=True),
            sa.Column('updated_by', sa.String(), nullable=True),
            sa.Column('version', sa.Integer(), server_default='1'),
        )

    # Alerts v2 Table (v2.0.0 WITH suppressed_by_blackout, WITHOUT retry columns)
    if not helper.table_exists('alerts_v2'):
        op.create_table(
            'alerts_v2',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('dedup_key', sa.String(), nullable=False, unique=True),
            sa.Column('scope_type', sa.String(), nullable=False),
            sa.Column('scope_id', sa.String(), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('severity', sa.String(), nullable=False),
            sa.Column('state', sa.String(), nullable=False),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('message', sa.Text(), nullable=False),
            # Timestamps
            sa.Column('first_seen', sa.DateTime(), nullable=False),
            sa.Column('last_seen', sa.DateTime(), nullable=False),
            sa.Column('occurrences', sa.Integer(), server_default='1', nullable=False),
            sa.Column('snoozed_until', sa.DateTime(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(), nullable=True),
            sa.Column('resolved_reason', sa.String(), nullable=True),
            # Context
            sa.Column('rule_id', sa.String(), sa.ForeignKey('alert_rules_v2.id', ondelete='SET NULL'), nullable=True),
            sa.Column('rule_version', sa.Integer(), nullable=True),
            sa.Column('current_value', sa.Float(), nullable=True),
            sa.Column('threshold', sa.Float(), nullable=True),
            sa.Column('rule_snapshot', sa.Text(), nullable=True),
            sa.Column('labels_json', sa.Text(), nullable=True),
            sa.Column('host_name', sa.String(), nullable=True),
            sa.Column('host_id', sa.String(), nullable=True),
            sa.Column('container_name', sa.String(), nullable=True),
            sa.Column('event_context_json', sa.Text(), nullable=True),
            # Notification tracking
            sa.Column('notified_at', sa.DateTime(), nullable=True),
            sa.Column('notification_count', sa.Integer(), server_default='0'),
            # Blackout window support (v2.0.0)
            sa.Column('suppressed_by_blackout', sa.Boolean(), server_default='0', nullable=False),
            # NOTE: Retry tracking columns (last_notification_attempt_at, next_retry_at)
            # are NOT in v2.0.0 - they will be added in a future migration
        )
        # Create indexes
        op.create_index('idx_alertv2_state', 'alerts_v2', ['state'])
        op.create_index('idx_alertv2_scope', 'alerts_v2', ['scope_type', 'scope_id'])
        op.create_index('idx_alertv2_severity', 'alerts_v2', ['severity'])
        op.create_index('idx_alertv2_first_seen', 'alerts_v2', ['first_seen'])
        op.create_index('idx_alertv2_last_seen', 'alerts_v2', [sa.text('last_seen DESC')])
        op.create_index('idx_alertv2_host_id', 'alerts_v2', ['host_id'])
        op.create_index('idx_alertv2_rule_id', 'alerts_v2', ['rule_id'])

    # Alert Annotations Table
    if not helper.table_exists('alert_annotations'):
        op.create_table(
            'alert_annotations',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('alert_id', sa.String(), sa.ForeignKey('alerts_v2.id', ondelete='CASCADE'), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('user', sa.String(), nullable=True),
            sa.Column('text', sa.Text(), nullable=False),
        )

    # Rule Runtime Table
    if not helper.table_exists('rule_runtime'):
        op.create_table(
            'rule_runtime',
            sa.Column('dedup_key', sa.String(), primary_key=True),
            sa.Column('rule_id', sa.String(), sa.ForeignKey('alert_rules_v2.id', ondelete='CASCADE'), nullable=False),
            sa.Column('state_json', sa.Text(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )

    # Rule Evaluations Table
    if not helper.table_exists('rule_evaluations'):
        op.create_table(
            'rule_evaluations',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('rule_id', sa.String(), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('scope_id', sa.String(), nullable=False),
            sa.Column('value', sa.Float(), nullable=False),
            sa.Column('breached', sa.Boolean(), nullable=False),
            sa.Column('action', sa.String(), nullable=True),
        )
        op.create_index('idx_rule_eval_timestamp', 'rule_evaluations', ['timestamp'])

    # Notification Retries Table
    if not helper.table_exists('notification_retries'):
        op.create_table(
            'notification_retries',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('alert_id', sa.String(), sa.ForeignKey('alerts_v2.id', ondelete='CASCADE'), nullable=False),
            sa.Column('rule_id', sa.String(), nullable=True),
            sa.Column('attempt_count', sa.Integer(), server_default='0'),
            sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
            sa.Column('next_retry_at', sa.DateTime(), nullable=False),
            sa.Column('channel_ids_json', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('error_message', sa.Text(), nullable=True),
        )
        op.create_index('idx_notification_retry_next', 'notification_retries', ['next_retry_at'])

    # Tags Table
    if not helper.table_exists('tags'):
        op.create_table(
            'tags',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False, unique=True),
            sa.Column('color', sa.String(), nullable=True),
            sa.Column('kind', sa.String(), server_default='user', nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_used_at', sa.DateTime(), nullable=True),
        )

    # Tag Assignments Table
    if not helper.table_exists('tag_assignments'):
        op.create_table(
            'tag_assignments',
            sa.Column('tag_id', sa.String(), sa.ForeignKey('tags.id', ondelete='CASCADE'), nullable=False, primary_key=True),
            sa.Column('subject_type', sa.String(), nullable=False, primary_key=True),
            sa.Column('subject_id', sa.String(), nullable=False, primary_key=True),
            # Logical identity fields
            sa.Column('compose_project', sa.String(), nullable=True),
            sa.Column('compose_service', sa.String(), nullable=True),
            sa.Column('host_id_at_attach', sa.String(), nullable=True),
            sa.Column('container_name_at_attach', sa.String(), nullable=True),
            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        )
        op.create_index('idx_tag_assignment_subject', 'tag_assignments', ['subject_type', 'subject_id'])
        op.create_index('idx_tag_assignment_sticky', 'tag_assignments', ['compose_project', 'compose_service', 'host_id_at_attach'])

    # Registry Credentials Table
    if not helper.table_exists('registry_credentials'):
        op.create_table(
            'registry_credentials',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('registry_url', sa.String(), nullable=False, unique=True),
            sa.Column('username', sa.String(), nullable=False),
            sa.Column('password_encrypted', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    """
    Downgrade not supported.

    V2 is a major upgrade from V1 with significant schema changes.
    Downgrading would result in data loss and is not supported.
    """
    raise NotImplementedError("Downgrade from V2 to V1 is not supported")
