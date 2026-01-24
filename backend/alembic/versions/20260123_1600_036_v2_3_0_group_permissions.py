"""v2.3.0 Group-Based Permissions Refactor

Revision ID: 036_v2_3_0_group_perms
Revises: 035_v2_3_0_phase6
Create Date: 2026-01-23

CHANGES IN v2.3.0 (Group Permissions Refactor):
- Groups are now the permission source (not roles)
- Users can belong to multiple groups (union of permissions)
- API keys belong to exactly one group
- OIDC maps to groups instead of roles

SCHEMA CHANGES:
1. Modified tables:
   - custom_groups: Add is_system column
   - oidc_config: Add default_group_id column
   - api_keys: Replace user_id/scopes with group_id/created_by_user_id

2. New tables:
   - group_permissions (replaces role_permissions concept)
   - oidc_group_mappings (replaces oidc_role_mappings)

3. Data seeding:
   - Create default system groups (Administrators, Operators, Read Only)
   - Seed permissions for default groups
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '036_v2_3_0_group_perms'
down_revision = '035_v2_3_0_phase6'
branch_labels = None
depends_on = None


# =============================================================================
# Default Group Permissions (from capabilities.py)
# =============================================================================

ALL_CAPABILITIES = [
    'hosts.manage', 'hosts.view',
    'stacks.edit', 'stacks.deploy', 'stacks.view', 'stacks.view_env',
    'containers.operate', 'containers.shell', 'containers.update',
    'containers.view', 'containers.logs', 'containers.view_env',
    'healthchecks.manage', 'healthchecks.test', 'healthchecks.view',
    'batch.create', 'batch.view',
    'policies.manage', 'policies.view',
    'alerts.manage', 'alerts.view',
    'notifications.manage', 'notifications.view',
    'registry.manage', 'registry.view',
    'agents.manage', 'agents.view',
    'settings.manage',
    'users.manage',
    'groups.manage',
    'audit.view',
    'apikeys.manage_own', 'apikeys.manage_other',
    'tags.manage', 'tags.view',
    'events.view',
]

OPERATOR_CAPABILITIES = [
    'hosts.view',
    'stacks.deploy', 'stacks.view', 'stacks.view_env',
    'containers.operate', 'containers.view', 'containers.logs', 'containers.view_env',
    'healthchecks.test', 'healthchecks.view',
    'batch.create', 'batch.view',
    'policies.view',
    'alerts.view',
    'notifications.view',
    'agents.view',
    'apikeys.manage_own',
    'tags.manage', 'tags.view',
    'events.view',
]

READONLY_CAPABILITIES = [
    'hosts.view',
    'stacks.view',
    'containers.view', 'containers.logs',
    'healthchecks.view',
    'batch.view',
    'policies.view',
    'alerts.view',
    'notifications.view',
    'agents.view',
    'tags.view',
    'events.view',
]


# =============================================================================
# Helper Functions
# =============================================================================

def get_inspector():
    """Get SQLAlchemy inspector for the current database connection."""
    bind = op.get_bind()
    return sa.inspect(bind)


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    inspector = get_inspector()
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    if not table_exists(table_name):
        return False
    inspector = get_inspector()
    column_names = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in column_names


def seed_group_permissions(bind, group_id: int, capabilities: list, timestamp: str) -> None:
    """Insert permission records for a group."""
    for capability in capabilities:
        bind.execute(sa.text("""
            INSERT INTO group_permissions (group_id, capability, allowed, created_at, updated_at)
            VALUES (:group_id, :capability, 1, :timestamp, :timestamp)
        """), {'group_id': group_id, 'capability': capability, 'timestamp': timestamp})


def upgrade():
    """Apply group-based permissions schema changes"""

    bind = op.get_bind()

    # =========================================================================
    # 1. ADD is_system COLUMN TO custom_groups
    # =========================================================================
    if not column_exists('custom_groups', 'is_system'):
        op.add_column(
            'custom_groups',
            sa.Column('is_system', sa.Boolean(), nullable=False, server_default='0')
        )

    # =========================================================================
    # 2. CREATE group_permissions TABLE
    # =========================================================================
    if not table_exists('group_permissions'):
        op.create_table(
            'group_permissions',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('custom_groups.id', ondelete='CASCADE'), nullable=False),
            sa.Column('capability', sa.Text(), nullable=False),
            sa.Column('allowed', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint('group_id', 'capability', name='uq_group_capability'),
            sa.Index('idx_group_permissions_group', 'group_id'),
        )

    # =========================================================================
    # 3. CREATE oidc_group_mappings TABLE
    # =========================================================================
    if not table_exists('oidc_group_mappings'):
        op.create_table(
            'oidc_group_mappings',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('oidc_value', sa.Text(), nullable=False, unique=True, index=True),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('custom_groups.id', ondelete='CASCADE'), nullable=False),
            sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )

    # =========================================================================
    # 4. ADD default_group_id TO oidc_config
    # =========================================================================
    if table_exists('oidc_config') and not column_exists('oidc_config', 'default_group_id'):
        op.add_column(
            'oidc_config',
            sa.Column('default_group_id', sa.Integer(), sa.ForeignKey('custom_groups.id', ondelete='SET NULL'), nullable=True)
        )

    # =========================================================================
    # 5. MODIFY api_keys TABLE
    # =========================================================================
    if table_exists('api_keys'):
        # Add new columns first
        if not column_exists('api_keys', 'group_id'):
            # Add as nullable first (we'll set values and then make required)
            op.add_column(
                'api_keys',
                sa.Column('group_id', sa.Integer(), nullable=True)
            )

        if not column_exists('api_keys', 'created_by_user_id'):
            op.add_column(
                'api_keys',
                sa.Column('created_by_user_id', sa.Integer(), nullable=True)
            )

    # =========================================================================
    # 6. SEED DEFAULT SYSTEM GROUPS
    # =========================================================================
    now = datetime.now(timezone.utc).isoformat()

    # Check if default groups already exist
    result = bind.execute(sa.text("SELECT COUNT(*) FROM custom_groups WHERE name = 'Administrators'"))
    admin_exists = result.scalar() > 0

    if not admin_exists:
        # Create Administrators group
        bind.execute(sa.text("""
            INSERT INTO custom_groups (name, description, is_system, created_at, updated_at)
            VALUES ('Administrators', 'Full access to all features', 1, :now, :now)
        """), {'now': now})

        # Create Operators group
        bind.execute(sa.text("""
            INSERT INTO custom_groups (name, description, is_system, created_at, updated_at)
            VALUES ('Operators', 'Can operate containers and deploy stacks, limited configuration access', 1, :now, :now)
        """), {'now': now})

        # Create Read Only group
        bind.execute(sa.text("""
            INSERT INTO custom_groups (name, description, is_system, created_at, updated_at)
            VALUES ('Read Only', 'View-only access to all features', 1, :now, :now)
        """), {'now': now})

    # Get group IDs
    result = bind.execute(sa.text("SELECT id FROM custom_groups WHERE name = 'Administrators'"))
    admin_group_id = result.scalar()

    result = bind.execute(sa.text("SELECT id FROM custom_groups WHERE name = 'Operators'"))
    operators_group_id = result.scalar()

    result = bind.execute(sa.text("SELECT id FROM custom_groups WHERE name = 'Read Only'"))
    readonly_group_id = result.scalar()

    # =========================================================================
    # 7. SEED GROUP PERMISSIONS
    # =========================================================================
    if admin_group_id:
        # Check if permissions already seeded
        result = bind.execute(sa.text(
            "SELECT COUNT(*) FROM group_permissions WHERE group_id = :group_id"
        ), {'group_id': admin_group_id})
        permissions_exist = result.scalar() > 0

        if not permissions_exist:
            seed_group_permissions(bind, admin_group_id, ALL_CAPABILITIES, now)
            seed_group_permissions(bind, operators_group_id, OPERATOR_CAPABILITIES, now)
            seed_group_permissions(bind, readonly_group_id, READONLY_CAPABILITIES, now)

    # =========================================================================
    # 8. MIGRATE EXISTING API KEYS
    # =========================================================================
    if table_exists('api_keys') and admin_group_id:
        # Assign existing API keys to Administrators group if they have no group
        # Also copy user_id to created_by_user_id for audit trail
        if column_exists('api_keys', 'user_id'):
            bind.execute(sa.text("""
                UPDATE api_keys
                SET group_id = :admin_gid,
                    created_by_user_id = user_id
                WHERE group_id IS NULL
            """), {'admin_gid': admin_group_id})

        # Now make group_id NOT NULL (SQLite doesn't support ALTER COLUMN, so we skip this)
        # The application will enforce NOT NULL via the model

    # =========================================================================
    # 9. SET default_group_id FOR OIDC CONFIG
    # =========================================================================
    if table_exists('oidc_config') and readonly_group_id:
        # Set default group to Read Only for OIDC users without mappings
        bind.execute(sa.text("""
            UPDATE oidc_config
            SET default_group_id = :gid
            WHERE default_group_id IS NULL
        """), {'gid': readonly_group_id})


def downgrade():
    """Remove group-based permissions schema changes"""

    # Note: This is a destructive downgrade - data will be lost

    # Drop new tables
    if table_exists('oidc_group_mappings'):
        op.drop_table('oidc_group_mappings')

    if table_exists('group_permissions'):
        op.drop_table('group_permissions')

    # Remove columns from api_keys
    if table_exists('api_keys'):
        if column_exists('api_keys', 'created_by_user_id'):
            op.drop_column('api_keys', 'created_by_user_id')
        if column_exists('api_keys', 'group_id'):
            op.drop_column('api_keys', 'group_id')

    # Remove default_group_id from oidc_config
    if table_exists('oidc_config') and column_exists('oidc_config', 'default_group_id'):
        op.drop_column('oidc_config', 'default_group_id')

    # Remove is_system from custom_groups
    if column_exists('custom_groups', 'is_system'):
        op.drop_column('custom_groups', 'is_system')

    # Note: We don't delete the system groups - they may have user memberships
