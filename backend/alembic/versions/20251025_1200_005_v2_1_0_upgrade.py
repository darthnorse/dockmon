"""v2.1.0 upgrade - Complete deployment feature system

Revision ID: 005_v2_1_0
Revises: 004_v2_0_3
Create Date: 2025-10-25

CHANGES IN v2.1.0:
- Create deployments table (deployment tracking with state machine)
  - Includes display_name (user-friendly name, design spec line 116)
  - Includes created_by (username who created deployment, design spec line 124)
  - Includes stage_percent (granular progress within each stage, 0-100)
- Create deployment_containers table (junction table for stack deployments)
- Create deployment_templates table (reusable deployment templates)
- Create deployment_metadata table (track deployment-created containers)
  - Tracks which containers were created by deployments
  - Enables deployment filtering and status display
  - Supports stack service role tracking (e.g., 'web', 'db')
  - Follows existing metadata pattern (like container_desired_states, container_updates)
- Add indexes for performance (host_id, status, created_at)
- Add unique constraints (host+name, template name)
- Add image pruning settings to global_settings:
  - prune_images_enabled (default: True)
  - image_retention_count (default: 2, keeps last N versions per image)
  - image_prune_grace_hours (default: 48, grace period in hours)
- Update app_version to '2.1.0'

NEW FEATURES:
- Deploy containers via API with progress tracking
- Deploy Docker Compose stacks
- Save and reuse deployment templates
- Security validation before deployment
- Rollback support with commitment point tracking
- Track deployment ownership of containers
- Layer-by-layer image pull progress
- Nested progress structure: {overall_percent, stage, stage_percent}
- Automatic Docker image pruning to free disk space
- Configurable retention policies (keep last N versions, grace period)
- Manual prune trigger via API
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '005_v2_1_0'
down_revision = '004_v2_0_3'
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
    """Add v2.1.0 deployment features"""

    # Change 1: Create deployments table
    # Tracks deployment operations with state machine and progress tracking
    if not table_exists('deployments'):
        op.create_table(
            'deployments',
            sa.Column('id', sa.String(), nullable=False),  # Composite: {host_id}:{deployment_short_id}
            sa.Column('host_id', sa.String(), sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('deployment_type', sa.String(), nullable=False),  # 'container' | 'stack'
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('display_name', sa.String(), nullable=True),  # User-friendly name (design spec line 116)
            sa.Column('status', sa.String(), nullable=False, server_default='planning'),  # State machine: planning, executing, completed, failed, rolled_back
            sa.Column('definition', sa.Text(), nullable=False),  # JSON: container/stack configuration
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('progress_percent', sa.Integer(), nullable=False, server_default='0'),  # 0-100 overall
            sa.Column('stage_percent', sa.Integer(), nullable=False, server_default='0'),  # 0-100 within current stage
            sa.Column('current_stage', sa.Text(), nullable=True),  # e.g., 'Pulling image', 'Creating container'
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('created_by', sa.String(), nullable=True),  # Username who created deployment (design spec line 124)
            sa.Column('committed', sa.Boolean(), nullable=False, server_default='0'),  # Commitment point tracking
            sa.Column('rollback_on_failure', sa.Boolean(), nullable=False, server_default='1'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('host_id', 'name', name='uq_deployment_host_name'),
            sqlite_autoincrement=False,
        )

        # Add indexes for performance
        op.create_index('idx_deployment_host_id', 'deployments', ['host_id'])
        op.create_index('idx_deployment_status', 'deployments', ['status'])
        op.create_index('idx_deployment_created_at', 'deployments', ['created_at'])

    # Change 2: Create deployment_containers table
    # Junction table linking deployments to containers (supports stack deployments)
    if not table_exists('deployment_containers'):
        op.create_table(
            'deployment_containers',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('deployment_id', sa.String(), sa.ForeignKey('deployments.id', ondelete='CASCADE'), nullable=False),
            sa.Column('container_id', sa.String(), nullable=False),  # SHORT ID (12 chars)
            sa.Column('service_name', sa.String(), nullable=True),  # NULL for single containers, service name for stacks
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )

    # Change 3: Create deployment_templates table
    # Reusable deployment templates with variable substitution
    if not table_exists('deployment_templates'):
        op.create_table(
            'deployment_templates',
            sa.Column('id', sa.String(), primary_key=True),  # e.g., 'tpl_nginx_001'
            sa.Column('name', sa.String(), nullable=False, unique=True),
            sa.Column('category', sa.String(), nullable=True),  # e.g., 'web-servers', 'databases'
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('deployment_type', sa.String(), nullable=False),  # 'container' | 'stack'
            sa.Column('template_definition', sa.Text(), nullable=False),  # JSON with variables like ${PORT}
            sa.Column('variables', sa.Text(), nullable=True),  # JSON: {"PORT": {"default": 8080, "type": "integer", ...}}
            sa.Column('is_builtin', sa.Boolean(), nullable=False, server_default='0'),  # System templates vs user templates
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sqlite_autoincrement=False,
        )

    # Change 4: Create deployment_metadata table
    # Tracks which containers were created by deployments following existing metadata pattern
    if not table_exists('deployment_metadata'):
        op.create_table(
            'deployment_metadata',
            sa.Column('container_id', sa.Text(), nullable=False),  # Composite: {host_id}:{container_short_id}
            sa.Column('host_id', sa.Text(), sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('deployment_id', sa.String(), sa.ForeignKey('deployments.id', ondelete='SET NULL'), nullable=True),
            sa.Column('is_managed', sa.Boolean(), nullable=False, server_default='0'),  # True if created by deployment system
            sa.Column('service_name', sa.String(), nullable=True),  # NULL for single containers, service name for stacks
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('container_id'),
            sqlite_autoincrement=False,
        )

        # Add indexes for performance
        if not index_exists('deployment_metadata', 'idx_deployment_metadata_host'):
            op.create_index('idx_deployment_metadata_host', 'deployment_metadata', ['host_id'])

        if not index_exists('deployment_metadata', 'idx_deployment_metadata_deployment'):
            op.create_index('idx_deployment_metadata_deployment', 'deployment_metadata', ['deployment_id'])

    # Change 5: Add image pruning settings to global_settings
    if table_exists('global_settings'):
        # Add prune_images_enabled column (default: True)
        if not column_exists('global_settings', 'prune_images_enabled'):
            op.add_column('global_settings',
                sa.Column('prune_images_enabled', sa.Boolean(), server_default='1', nullable=False)
            )

        # Add image_retention_count column (default: 2)
        if not column_exists('global_settings', 'image_retention_count'):
            op.add_column('global_settings',
                sa.Column('image_retention_count', sa.Integer(), server_default='2', nullable=False)
            )

        # Add image_prune_grace_hours column (default: 48)
        if not column_exists('global_settings', 'image_prune_grace_hours'):
            op.add_column('global_settings',
                sa.Column('image_prune_grace_hours', sa.Integer(), server_default='48', nullable=False)
            )

    # Change 6: Update app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.0', id=1)
        )


def downgrade() -> None:
    """Remove v2.1.0 deployment and image pruning features"""

    # Reverse order of upgrade
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.0.3', id=1)
        )

        # Remove image pruning columns
        if column_exists('global_settings', 'image_prune_grace_hours'):
            op.drop_column('global_settings', 'image_prune_grace_hours')

        if column_exists('global_settings', 'image_retention_count'):
            op.drop_column('global_settings', 'image_retention_count')

        if column_exists('global_settings', 'prune_images_enabled'):
            op.drop_column('global_settings', 'prune_images_enabled')

    # Drop tables in reverse dependency order
    if table_exists('deployment_metadata'):
        # Drop indexes first
        if index_exists('deployment_metadata', 'idx_deployment_metadata_deployment'):
            op.drop_index('idx_deployment_metadata_deployment', 'deployment_metadata')
        if index_exists('deployment_metadata', 'idx_deployment_metadata_host'):
            op.drop_index('idx_deployment_metadata_host', 'deployment_metadata')
        # Drop table
        op.drop_table('deployment_metadata')

    if table_exists('deployment_templates'):
        op.drop_table('deployment_templates')

    if table_exists('deployment_containers'):
        op.drop_table('deployment_containers')

    if table_exists('deployments'):
        # Drop indexes first
        if index_exists('deployments', 'idx_deployment_created_at'):
            op.drop_index('idx_deployment_created_at', 'deployments')
        if index_exists('deployments', 'idx_deployment_status'):
            op.drop_index('idx_deployment_status', 'deployments')
        if index_exists('deployments', 'idx_deployment_host_id'):
            op.drop_index('idx_deployment_host_id', 'deployments')

        # Drop table
        op.drop_table('deployments')
