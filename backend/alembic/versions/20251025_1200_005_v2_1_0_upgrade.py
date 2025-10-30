"""v2.1.0 upgrade - Complete deployment feature system with integrity constraints

Revision ID: 005_v2_1_0
Revises: 004_v2_0_3
Create Date: 2025-10-25

CHANGES IN v2.1.0:
- Create deployments table (deployment tracking with state machine)
  - Includes created_by (username who created deployment, design spec line 124)
- Create deployment_containers table (junction table for stack deployments)
- Create deployment_templates table (reusable deployment templates)
- Create deployment_metadata table (track deployment-created containers)
  - Tracks which containers were created by deployments
  - Enables deployment filtering and status display
  - Supports stack service role tracking (e.g., 'web', 'db')
  - Follows existing metadata pattern (like container_desired_states, container_updates)
- Add indexes for performance (host_id, status, created_at)
- Add unique constraints (host+name, template name)
- Add CHECK constraints for data validation:
  - deployments.status must be one of 7 valid states
  - deployment_metadata.is_managed must be boolean
- Add composite indexes for common queries:
  - deployments(host_id, status) for deployment filtering by host
  - deployment_containers(deployment_id, service_name) for service lookup
  - deployment_metadata(host_id, deployment_id) for deployment ownership tracking
- Add unique constraint on deployment_containers(deployment_id, container_id) to prevent duplicates
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


def constraint_exists(table_name: str, constraint_name: str) -> bool:
    """Check if constraint exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    constraints = [c['name'] for c in inspector.get_check_constraints(table_name)]
    return constraint_name in constraints


def upgrade() -> None:
    """Add v2.1.0 deployment features"""
    import logging
    logger = logging.getLogger('alembic.migration')

    logger.info("Starting v2.1.0 migration...")

    # Verify prerequisite tables exist
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()
    logger.info(f"Existing tables: {existing_tables}")

    required_tables = ['docker_hosts', 'users', 'global_settings']
    missing_tables = [t for t in required_tables if t not in existing_tables]
    if missing_tables:
        raise RuntimeError(f"Cannot run v2.1.0 migration: Missing required tables: {missing_tables}")

    logger.info("All prerequisite tables exist, proceeding with migration...")

    # Change 1: Create deployments table
    # Tracks deployment operations with state machine and progress tracking
    if not table_exists('deployments'):
        logger.info("Creating deployments table...")
        op.create_table(
            'deployments',
            sa.Column('id', sa.String(), nullable=False),  # Composite: {host_id}:{deployment_short_id}
            sa.Column('host_id', sa.String(), sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),  # User who created deployment (for authorization)
            sa.Column('deployment_type', sa.String(), nullable=False),  # 'container' | 'stack'
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='planning'),  # State machine: planning → validating → pulling_image → creating → starting → running → completed/failed/rolled_back
            sa.Column('definition', sa.Text(), nullable=False),  # JSON: container/stack configuration
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('progress_percent', sa.Integer(), nullable=False, server_default='0'),  # 0-100 overall
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

        # Add indexes for performance and authorization
        logger.info("Creating indexes for deployments table...")
        op.create_index('idx_deployment_user_id', 'deployments', ['user_id'])  # Authorization: filter by user
        op.create_index('idx_deployment_host_id', 'deployments', ['host_id'])
        op.create_index('idx_deployment_status', 'deployments', ['status'])
        op.create_index('idx_deployment_created_at', 'deployments', ['created_at'])
        op.create_index('idx_deployment_user_host', 'deployments', ['user_id', 'host_id'])  # User's deployments on specific host
        logger.info("Deployments table created successfully")
    else:
        logger.info("Deployments table already exists, skipping creation")

    # Change 2: Create deployment_containers table
    # Junction table linking deployments to containers (supports stack deployments)
    if not table_exists('deployment_containers'):
        logger.info("Creating deployment_containers table...")
        op.create_table(
            'deployment_containers',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('deployment_id', sa.String(), sa.ForeignKey('deployments.id', ondelete='CASCADE'), nullable=False),
            sa.Column('container_id', sa.String(), nullable=False),  # SHORT ID (12 chars)
            sa.Column('service_name', sa.String(), nullable=True),  # NULL for single containers, service name for stacks
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )

        # Add indexes for performance
        op.create_index('idx_deployment_container_deployment', 'deployment_containers', ['deployment_id'])
        op.create_index('idx_deployment_container_container', 'deployment_containers', ['container_id'])
        logger.info("Deployment_containers table created successfully")
    else:
        logger.info("Deployment_containers table already exists, skipping creation")

    # Change 3: Create deployment_templates table
    # Reusable deployment templates with variable substitution
    if not table_exists('deployment_templates'):
        logger.info("Creating deployment_templates table...")
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

        # Add indexes for performance
        op.create_index('idx_deployment_template_name', 'deployment_templates', ['name'])
        op.create_index('idx_deployment_template_category', 'deployment_templates', ['category'])
        logger.info("Deployment_templates table created successfully")
    else:
        logger.info("Deployment_templates table already exists, skipping creation")

    # Change 4: Create deployment_metadata table
    # Tracks which containers were created by deployments following existing metadata pattern
    if not table_exists('deployment_metadata'):
        logger.info("Creating deployment_metadata table...")
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

        logger.info("Deployment_metadata table created successfully")
    else:
        logger.info("Deployment_metadata table already exists, skipping creation")

    # Change 4b: Add additional constraints and indexes for data integrity (v2.1.1 enhancements)
    # These provide better data consistency and query performance
    # Defensive checks ensure they work for both fresh installs and upgrades

    logger.info("Starting Change 4b: Adding constraints and indexes...")

    # Add status validation constraint to deployments table
    try:
        if table_exists('deployments') and not constraint_exists('deployments', 'ck_deployment_valid_status'):
            logger.info("Adding status validation constraint to deployments...")
            op.create_check_constraint(
                'ck_deployment_valid_status',
                'deployments',
                "status IN ('planning', 'validating', 'pulling_image', 'creating', 'starting', 'running', 'failed', 'rolled_back')"
            )
            logger.info("Status validation constraint added")
        else:
            logger.info("Status validation constraint already exists or table missing")
    except Exception as e:
        logger.error(f"Failed to add status validation constraint: {e}")
        raise

    # Add composite index for host_id + status (common filter combination)
    try:
        if table_exists('deployments') and not index_exists('deployments', 'idx_deployment_host_status'):
            logger.info("Adding composite index idx_deployment_host_status...")
            op.create_index('idx_deployment_host_status', 'deployments', ['host_id', 'status'])
            logger.info("Composite index added")
        else:
            logger.info("Composite index idx_deployment_host_status already exists or table missing")
    except Exception as e:
        logger.error(f"Failed to add composite index: {e}")
        raise

    # Add unique constraint on deployment_containers to prevent duplicates
    logger.info("Adding constraints to deployment_containers...")
    if table_exists('deployment_containers'):
        try:
            bind = op.get_bind()
            inspector = inspect(bind)
            constraints = {c['name'] for c in inspector.get_unique_constraints('deployment_containers')}

            if 'uq_deployment_container_link' not in constraints:
                logger.info("Adding unique constraint uq_deployment_container_link...")
                op.create_unique_constraint(
                    'uq_deployment_container_link',
                    'deployment_containers',
                    ['deployment_id', 'container_id']
                )
                logger.info("Unique constraint added")
            else:
                logger.info("Unique constraint uq_deployment_container_link already exists")

            # Add composite index for deployment + service_name lookup
            if not index_exists('deployment_containers', 'idx_deployment_container_deployment_service'):
                logger.info("Adding index idx_deployment_container_deployment_service...")
                op.create_index(
                    'idx_deployment_container_deployment_service',
                    'deployment_containers',
                    ['deployment_id', 'service_name']
                )
                logger.info("Index added")
            else:
                logger.info("Index idx_deployment_container_deployment_service already exists")
        except Exception as e:
            logger.error(f"Failed to add deployment_containers constraints: {e}")
            raise

    # Add constraints and indexes to deployment_metadata
    logger.info("Adding constraints to deployment_metadata...")
    if table_exists('deployment_metadata'):
        try:
            # Add is_managed check constraint
            if not constraint_exists('deployment_metadata', 'ck_deployment_metadata_managed'):
                logger.info("Adding check constraint ck_deployment_metadata_managed...")
                op.create_check_constraint(
                    'ck_deployment_metadata_managed',
                    'deployment_metadata',
                    "is_managed IN (0, 1)"
                )
                logger.info("Check constraint added")
            else:
                logger.info("Check constraint ck_deployment_metadata_managed already exists")

            # Add composite index for host + deployment lookup
            if not index_exists('deployment_metadata', 'idx_deployment_metadata_host_deployment'):
                logger.info("Adding index idx_deployment_metadata_host_deployment...")
                op.create_index(
                    'idx_deployment_metadata_host_deployment',
                    'deployment_metadata',
                    ['host_id', 'deployment_id']
                )
                logger.info("Index added")
            else:
                logger.info("Index idx_deployment_metadata_host_deployment already exists")
        except Exception as e:
            logger.error(f"Failed to add deployment_metadata constraints: {e}")
            raise

    logger.info("Change 4b completed successfully")

    # Change 5: Add image pruning settings to global_settings
    logger.info("Starting Change 5: Adding image pruning settings...")
    if table_exists('global_settings'):
        # Add prune_images_enabled column (default: True)
        try:
            if not column_exists('global_settings', 'prune_images_enabled'):
                logger.info("Adding prune_images_enabled column...")
                op.add_column('global_settings',
                    sa.Column('prune_images_enabled', sa.Boolean(), server_default='1', nullable=False)
                )
                logger.info("prune_images_enabled column added")
        except Exception as e:
            logger.error(f"Failed to add prune_images_enabled column: {e}")
            raise

        # Add image_retention_count column (default: 2)
        try:
            if not column_exists('global_settings', 'image_retention_count'):
                logger.info("Adding image_retention_count column...")
                op.add_column('global_settings',
                    sa.Column('image_retention_count', sa.Integer(), server_default='2', nullable=False)
                )
                logger.info("image_retention_count column added")
        except Exception as e:
            logger.error(f"Failed to add image_retention_count column: {e}")
            raise

        # Add image_prune_grace_hours column (default: 48)
        try:
            if not column_exists('global_settings', 'image_prune_grace_hours'):
                logger.info("Adding image_prune_grace_hours column...")
                op.add_column('global_settings',
                    sa.Column('image_prune_grace_hours', sa.Integer(), server_default='48', nullable=False)
                )
                logger.info("image_prune_grace_hours column added")
        except Exception as e:
            logger.error(f"Failed to add image_prune_grace_hours column: {e}")
            raise

    # Change 6: Update app_version
    if table_exists('global_settings'):
        logger.info("Updating app_version to 2.1.0...")
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.0', id=1)
        )
        logger.info("App version updated successfully")

    logger.info("v2.1.0 migration completed successfully!")


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
        # Drop indexes and constraints in reverse order
        if index_exists('deployment_metadata', 'idx_deployment_metadata_host_deployment'):
            op.drop_index('idx_deployment_metadata_host_deployment', 'deployment_metadata')
        if constraint_exists('deployment_metadata', 'ck_deployment_metadata_managed'):
            op.drop_constraint('ck_deployment_metadata_managed', 'deployment_metadata', type_='check')
        if index_exists('deployment_metadata', 'idx_deployment_metadata_deployment'):
            op.drop_index('idx_deployment_metadata_deployment', 'deployment_metadata')
        if index_exists('deployment_metadata', 'idx_deployment_metadata_host'):
            op.drop_index('idx_deployment_metadata_host', 'deployment_metadata')
        # Drop table
        op.drop_table('deployment_metadata')

    if table_exists('deployment_templates'):
        # Drop indexes first
        if index_exists('deployment_templates', 'idx_deployment_template_category'):
            op.drop_index('idx_deployment_template_category', 'deployment_templates')
        if index_exists('deployment_templates', 'idx_deployment_template_name'):
            op.drop_index('idx_deployment_template_name', 'deployment_templates')
        # Drop table
        op.drop_table('deployment_templates')

    if table_exists('deployment_containers'):
        # Drop indexes and constraints in reverse order
        if index_exists('deployment_containers', 'idx_deployment_container_deployment_service'):
            op.drop_index('idx_deployment_container_deployment_service', 'deployment_containers')
        bind = op.get_bind()
        inspector = inspect(bind)
        constraints = {c['name'] for c in inspector.get_unique_constraints('deployment_containers')}
        if 'uq_deployment_container_link' in constraints:
            op.drop_constraint('uq_deployment_container_link', 'deployment_containers', type_='unique')
        if index_exists('deployment_containers', 'idx_deployment_container_container'):
            op.drop_index('idx_deployment_container_container', 'deployment_containers')
        if index_exists('deployment_containers', 'idx_deployment_container_deployment'):
            op.drop_index('idx_deployment_container_deployment', 'deployment_containers')
        # Drop table
        op.drop_table('deployment_containers')

    if table_exists('deployments'):
        # Drop indexes and constraints in reverse order
        if index_exists('deployments', 'idx_deployment_user_host'):
            op.drop_index('idx_deployment_user_host', 'deployments')
        if index_exists('deployments', 'idx_deployment_host_status'):
            op.drop_index('idx_deployment_host_status', 'deployments')
        if constraint_exists('deployments', 'ck_deployment_valid_status'):
            op.drop_constraint('ck_deployment_valid_status', 'deployments', type_='check')
        if index_exists('deployments', 'idx_deployment_created_at'):
            op.drop_index('idx_deployment_created_at', 'deployments')
        if index_exists('deployments', 'idx_deployment_status'):
            op.drop_index('idx_deployment_status', 'deployments')
        if index_exists('deployments', 'idx_deployment_host_id'):
            op.drop_index('idx_deployment_host_id', 'deployments')
        if index_exists('deployments', 'idx_deployment_user_id'):
            op.drop_index('idx_deployment_user_id', 'deployments')

        # Drop table
        op.drop_table('deployments')
