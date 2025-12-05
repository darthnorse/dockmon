"""v2.2.0-beta1 upgrade - Agent infrastructure for remote Docker host monitoring

Revision ID: 021_v2_2_0
Revises: 020_v2_1_10
Create Date: 2025-11-24

CHANGES IN v2.2.0-beta1:
- Create registration_tokens table (agent registration system)
  - Single-use tokens with 15-minute expiry
  - Tracks which user created token and when used
  - Enables secure agent registration without exposing credentials
- Create agents table (agent lifecycle management)
  - Stores agent registration info (engine_id, version, capabilities)
  - 1:1 relationship with docker_hosts via foreign key
  - Unique constraint on engine_id (prevents duplicate registrations)
  - Status tracking (online/offline/degraded)
  - JSON capabilities field for feature flags
  - agent_os/agent_arch columns for platform-specific binary downloads
- Add connection_type column to docker_hosts
  - Values: 'local', 'remote', 'agent'
  - Differentiates connection methods for hosts
- Add engine_id column to docker_hosts (for migration detection)
  - Enables automatic migration from mTLS to agent connection
  - Detects when agent registers with same Docker engine as existing host
- Add replaced_by_host_id column to docker_hosts (migration tracking)
  - Foreign key to docker_hosts.id
  - Tracks which host replaced this one during migration
  - Enables audit trail of host migrations
- Add check_from column to container_http_health_checks
  - Values: 'backend' (default) or 'agent'
  - Enables health checks to be performed by remote agent
- Add indexes for performance (engine_id, host_id, status)
- Add event_suppression_patterns column to global_settings
  - JSON array of glob patterns (e.g., ["runner-*", "*-cronjob-*"])
  - Events from containers matching these patterns are not logged
  - Reduces database size for users with many temporary containers
- Remove unused auto_cleanup_events column from global_settings
- Add agent version tracking to global_settings
  - latest_agent_version: Latest available agent version from GitHub
  - latest_agent_release_url: URL to release page
  - last_agent_update_check_at: Last time we checked for agent updates
- Add dismissed_agent_update_version to user_prefs
  - Allows per-user dismissal of agent update notifications
- Update app_version to '2.2.0-beta1'

NEW FEATURES:
- Agent registration via time-limited tokens
- WebSocket-based agent communication
- Remote Docker host monitoring without direct Docker socket access
- Agent-based container updates (network resilient)
- Agent self-update capability
- Agent update notifications (systemd deployments)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '021_v2_2_0'
down_revision = '020_v2_1_10'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def index_exists(table_name: str, index_name: str) -> bool:
    """Check if index exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    """Add v2.2.0-beta1 agent infrastructure"""

    # Change 1: Create registration_tokens table
    # Tracks single-use tokens for agent registration with 15-minute expiry
    if not table_exists('registration_tokens'):
        op.create_table(
            'registration_tokens',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('token', sa.String(), nullable=False, unique=True),  # UUID format
            sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),  # 15 minute expiry
            sa.Column('used', sa.Boolean(), server_default='0', nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sqlite_autoincrement=True,
        )

        # Add indexes for performance
        if not index_exists('registration_tokens', 'idx_registration_token_token'):
            op.create_index('idx_registration_token_token', 'registration_tokens', ['token'])
        if not index_exists('registration_tokens', 'idx_registration_token_user'):
            op.create_index('idx_registration_token_user', 'registration_tokens', ['created_by_user_id'])
        if not index_exists('registration_tokens', 'idx_registration_token_expires'):
            op.create_index('idx_registration_token_expires', 'registration_tokens', ['expires_at'])

    # Change 2: Create agents table
    # Stores agent registration info and lifecycle management
    if not table_exists('agents'):
        op.create_table(
            'agents',
            sa.Column('id', sa.String(), primary_key=True),  # UUID generated by backend
            sa.Column('host_id', sa.String(), sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'), nullable=False, unique=True),
            sa.Column('engine_id', sa.String(), nullable=False, unique=True),  # Docker engine ID
            sa.Column('version', sa.String(), nullable=False),  # Agent version (e.g., '2.2.0')
            sa.Column('proto_version', sa.String(), nullable=False),  # Protocol version (e.g., '1.0')
            sa.Column('capabilities', sa.Text(), nullable=False),  # JSON: {"stats_collection": true, ...}
            sa.Column('status', sa.String(), nullable=False),  # 'online', 'offline', 'degraded'
            sa.Column('last_seen_at', sa.DateTime(), nullable=False),
            sa.Column('registered_at', sa.DateTime(), nullable=False),
            # Agent runtime info (for binary downloads during self-update)
            sa.Column('agent_os', sa.String(), nullable=True),    # linux, darwin, windows (GOOS)
            sa.Column('agent_arch', sa.String(), nullable=True),  # amd64, arm64, arm (GOARCH)
            sqlite_autoincrement=False,
        )

        # Add indexes for performance
        if not index_exists('agents', 'idx_agent_host_id'):
            op.create_index('idx_agent_host_id', 'agents', ['host_id'])
        if not index_exists('agents', 'idx_agent_engine_id'):
            op.create_index('idx_agent_engine_id', 'agents', ['engine_id'])
        if not index_exists('agents', 'idx_agent_status'):
            op.create_index('idx_agent_status', 'agents', ['status'])
        if not index_exists('agents', 'idx_agent_last_seen'):
            op.create_index('idx_agent_last_seen', 'agents', ['last_seen_at'])

    # Defensive: Add agent_os/agent_arch columns if table exists but columns don't
    # (for beta users who ran migration before these columns were added)
    if table_exists('agents'):
        if not column_exists('agents', 'agent_os'):
            op.add_column('agents', sa.Column('agent_os', sa.String(), nullable=True))
        if not column_exists('agents', 'agent_arch'):
            op.add_column('agents', sa.Column('agent_arch', sa.String(), nullable=True))

    # Change 3: Add connection_type column to docker_hosts
    # Differentiates: 'local' (Docker socket), 'remote' (mTLS/Docker API), 'agent' (DockMon agent)
    if table_exists('docker_hosts'):
        if not column_exists('docker_hosts', 'connection_type'):
            op.add_column('docker_hosts',
                sa.Column('connection_type', sa.String(), server_default='local', nullable=False)
            )

            # Update connection_type based on URL (unix:// = local, tcp://, http://, https:// = remote)
            bind = op.get_bind()
            bind.execute(sa.text("""
                UPDATE docker_hosts
                SET connection_type = 'remote'
                WHERE url LIKE 'tcp://%' OR url LIKE 'http://%' OR url LIKE 'https://%'
            """))

    # Change 4: Add engine_id column to docker_hosts (for migration detection)
    # Enables detection of duplicate registrations (same Docker engine, different connection method)
    if table_exists('docker_hosts'):
        if not column_exists('docker_hosts', 'engine_id'):
            op.add_column('docker_hosts',
                sa.Column('engine_id', sa.String(), nullable=True)
            )
        # Add index for efficient duplicate detection
        if not index_exists('docker_hosts', 'idx_docker_hosts_engine_id'):
            op.create_index('idx_docker_hosts_engine_id', 'docker_hosts', ['engine_id'])

    # Change 5: Add replaced_by_host_id column to docker_hosts (migration tracking)
    # Tracks which host replaced this one during mTLS->agent migration
    # Note: No FK constraint because SQLite doesn't support adding FK via ALTER
    # App logic handles the relationship
    if table_exists('docker_hosts'):
        if not column_exists('docker_hosts', 'replaced_by_host_id'):
            op.add_column('docker_hosts',
                sa.Column('replaced_by_host_id', sa.String(), nullable=True)
            )

    # Change 6: Add check_from column to container_http_health_checks
    # Allows health checks to be performed by agent instead of backend
    # Values: 'backend' (default), 'agent'
    if table_exists('container_http_health_checks'):
        if not column_exists('container_http_health_checks', 'check_from'):
            op.add_column('container_http_health_checks',
                sa.Column('check_from', sa.Text(), server_default='backend', nullable=False)
            )

    # Change 7: Add event_suppression_patterns column to global_settings
    # Stores JSON array of glob patterns for container name matching
    if table_exists('global_settings'):
        if not column_exists('global_settings', 'event_suppression_patterns'):
            op.add_column('global_settings',
                sa.Column('event_suppression_patterns', sa.JSON(), nullable=True)
            )

    # Change 8: Remove unused auto_cleanup_events column from global_settings
    # This column was defined but never used anywhere in the codebase
    if table_exists('global_settings'):
        if column_exists('global_settings', 'auto_cleanup_events'):
            # SQLite requires batch mode for DROP COLUMN
            with op.batch_alter_table('global_settings') as batch_op:
                batch_op.drop_column('auto_cleanup_events')

    # Change 9: Add agent version tracking to global_settings
    # Enables tracking of latest available agent version from GitHub
    if table_exists('global_settings'):
        if not column_exists('global_settings', 'latest_agent_version'):
            op.add_column('global_settings',
                sa.Column('latest_agent_version', sa.Text(), nullable=True)
            )
        if not column_exists('global_settings', 'latest_agent_release_url'):
            op.add_column('global_settings',
                sa.Column('latest_agent_release_url', sa.Text(), nullable=True)
            )
        if not column_exists('global_settings', 'last_agent_update_check_at'):
            op.add_column('global_settings',
                sa.Column('last_agent_update_check_at', sa.DateTime(), nullable=True)
            )

    # Change 10: Add agent update dismissal to user_prefs
    # Allows users to dismiss agent update notifications per version
    if table_exists('user_prefs'):
        if not column_exists('user_prefs', 'dismissed_agent_update_version'):
            op.add_column('user_prefs',
                sa.Column('dismissed_agent_update_version', sa.Text(), nullable=True)
            )

    # Change 11: Update app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.0-beta1', id=1)
        )


def downgrade() -> None:
    """Remove v2.2.0-beta1 agent infrastructure"""

    # Reverse order of upgrade
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.9', id=1)
        )

    # Remove agent update dismissal from user_prefs
    if table_exists('user_prefs'):
        if column_exists('user_prefs', 'dismissed_agent_update_version'):
            with op.batch_alter_table('user_prefs') as batch_op:
                batch_op.drop_column('dismissed_agent_update_version')

    # Remove agent version tracking from global_settings
    if table_exists('global_settings'):
        if column_exists('global_settings', 'last_agent_update_check_at'):
            with op.batch_alter_table('global_settings') as batch_op:
                batch_op.drop_column('last_agent_update_check_at')
        if column_exists('global_settings', 'latest_agent_release_url'):
            with op.batch_alter_table('global_settings') as batch_op:
                batch_op.drop_column('latest_agent_release_url')
        if column_exists('global_settings', 'latest_agent_version'):
            with op.batch_alter_table('global_settings') as batch_op:
                batch_op.drop_column('latest_agent_version')

    # Restore auto_cleanup_events column
    if table_exists('global_settings'):
        if not column_exists('global_settings', 'auto_cleanup_events'):
            op.add_column('global_settings',
                sa.Column('auto_cleanup_events', sa.Boolean(), server_default='1', nullable=True)
            )

    # Remove event_suppression_patterns column
    if table_exists('global_settings'):
        if column_exists('global_settings', 'event_suppression_patterns'):
            with op.batch_alter_table('global_settings') as batch_op:
                batch_op.drop_column('event_suppression_patterns')

    # Remove check_from column from container_http_health_checks
    if table_exists('container_http_health_checks'):
        if column_exists('container_http_health_checks', 'check_from'):
            op.drop_column('container_http_health_checks', 'check_from')

    # Remove replaced_by_host_id column from docker_hosts
    if table_exists('docker_hosts'):
        if column_exists('docker_hosts', 'replaced_by_host_id'):
            op.drop_column('docker_hosts', 'replaced_by_host_id')

    # Remove engine_id column and index from docker_hosts
    if table_exists('docker_hosts'):
        if index_exists('docker_hosts', 'idx_docker_hosts_engine_id'):
            op.drop_index('idx_docker_hosts_engine_id', 'docker_hosts')
        if column_exists('docker_hosts', 'engine_id'):
            op.drop_column('docker_hosts', 'engine_id')

    # Remove connection_type column from docker_hosts
    if table_exists('docker_hosts'):
        if column_exists('docker_hosts', 'connection_type'):
            op.drop_column('docker_hosts', 'connection_type')

    # Drop agents table
    if table_exists('agents'):
        # Drop indexes first
        if index_exists('agents', 'idx_agent_last_seen'):
            op.drop_index('idx_agent_last_seen', 'agents')
        if index_exists('agents', 'idx_agent_status'):
            op.drop_index('idx_agent_status', 'agents')
        if index_exists('agents', 'idx_agent_engine_id'):
            op.drop_index('idx_agent_engine_id', 'agents')
        if index_exists('agents', 'idx_agent_host_id'):
            op.drop_index('idx_agent_host_id', 'agents')
        # Drop table
        op.drop_table('agents')

    # Drop registration_tokens table
    if table_exists('registration_tokens'):
        # Drop indexes first
        if index_exists('registration_tokens', 'idx_registration_token_expires'):
            op.drop_index('idx_registration_token_expires', 'registration_tokens')
        if index_exists('registration_tokens', 'idx_registration_token_user'):
            op.drop_index('idx_registration_token_user', 'registration_tokens')
        if index_exists('registration_tokens', 'idx_registration_token_token'):
            op.drop_index('idx_registration_token_token', 'registration_tokens')
        # Drop table
        op.drop_table('registration_tokens')
