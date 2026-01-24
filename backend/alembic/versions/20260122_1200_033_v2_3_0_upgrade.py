"""v2.3.0 Multi-User Support & Group-Based Permissions

Revision ID: 033_v2_3_0
Revises: 032_v2_2_8
Create Date: 2026-01-22

CHANGES IN v2.3.0:
- Multi-user support with group-based access control
- Users belong to groups, permissions come from groups (union semantics)
- API keys belong to exactly one group
- OIDC authentication with group mapping
- Audit columns and comprehensive audit logging
- Custom groups for organization

SCHEMA CHANGES:

1. User table additions:
   - email (unique, for password reset and OIDC matching)
   - auth_provider ('local' or 'oidc')
   - oidc_subject (OIDC subject identifier)
   - deleted_at/deleted_by (soft delete support)

2. Audit columns added to 8 tables:
   - docker_hosts, notification_channels, tags, registry_credentials
   - container_desired_states, container_http_health_checks
   - update_policies, auto_restart_configs

3. New tables:
   - role_permissions (legacy, kept for backwards compatibility)
   - password_reset_tokens (self-service password reset)
   - oidc_config (OIDC provider configuration)
   - oidc_role_mappings (legacy OIDC role mapping)
   - stack_metadata (audit trail for filesystem stacks)
   - audit_log (comprehensive action audit trail)
   - custom_groups (user groups with permissions)
   - user_group_memberships (user-group associations)
   - group_permissions (capabilities assigned to groups)
   - oidc_group_mappings (OIDC to DockMon group mapping)

4. Modified tables:
   - global_settings: Add audit_log_retention_days
   - custom_groups: Add is_system column
   - oidc_config: Add default_group_id column
   - api_keys: Add group_id, created_by_user_id columns

5. Default system groups seeded:
   - Administrators (full access)
   - Operators (container operations)
   - Read Only (view only)
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '033_v2_3_0'
down_revision = '032_v2_2_8'
branch_labels = None
depends_on = None


# =============================================================================
# Default Group Permissions
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
    'apikeys.manage_other', 'apikeys.manage_own',
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


def index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    if not table_exists(table_name):
        return False
    inspector = get_inspector()
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def seed_group_permissions(bind, group_id: int, capabilities: list, timestamp: str) -> None:
    """Insert permission records for a group."""
    for capability in capabilities:
        bind.execute(sa.text("""
            INSERT INTO group_permissions (group_id, capability, allowed, created_at, updated_at)
            VALUES (:group_id, :capability, 1, :timestamp, :timestamp)
        """), {'group_id': group_id, 'capability': capability, 'timestamp': timestamp})


def upgrade():
    """Apply v2.3.0 schema changes"""

    bind = op.get_bind()

    # =========================================================================
    # 1. USER TABLE - Add OIDC and soft delete support
    # =========================================================================
    if table_exists('users'):
        # Use batch mode for SQLite compatibility when adding unique constraint
        with op.batch_alter_table('users', schema=None) as batch_op:
            # Email - required for password reset and OIDC matching
            if not column_exists('users', 'email'):
                batch_op.add_column(sa.Column('email', sa.Text(), nullable=True))

            # Auth provider - 'local' or 'oidc'
            if not column_exists('users', 'auth_provider'):
                batch_op.add_column(sa.Column('auth_provider', sa.Text(), server_default='local', nullable=False))

            # OIDC subject identifier
            if not column_exists('users', 'oidc_subject'):
                batch_op.add_column(sa.Column('oidc_subject', sa.Text(), nullable=True))

            # Soft delete support
            if not column_exists('users', 'deleted_at'):
                batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

            if not column_exists('users', 'deleted_by'):
                batch_op.add_column(sa.Column('deleted_by', sa.Integer(), nullable=True))

        # Set placeholder email for existing users
        if column_exists('users', 'email'):
            bind.execute(sa.text("""
                UPDATE users
                SET email = username || '@localhost'
                WHERE email IS NULL
            """))

        # Create index on oidc_subject (outside batch for safety)
        if column_exists('users', 'oidc_subject') and not index_exists('users', 'ix_users_oidc_subject'):
            op.create_index('ix_users_oidc_subject', 'users', ['oidc_subject'])

    # =========================================================================
    # 2. AUDIT COLUMNS - Add created_by/updated_by to 8 tables
    # =========================================================================
    audit_tables = [
        'docker_hosts',
        'notification_channels',
        'tags',
        'registry_credentials',
        'container_desired_states',
        'container_http_health_checks',
        'update_policies',
        'auto_restart_configs',
    ]

    for table_name in audit_tables:
        if table_exists(table_name):
            if not column_exists(table_name, 'created_by'):
                op.add_column(table_name, sa.Column('created_by', sa.Integer(), nullable=True))

            if not column_exists(table_name, 'updated_by'):
                op.add_column(table_name, sa.Column('updated_by', sa.Integer(), nullable=True))

            # Set existing records to created_by = 1 (first user, typically admin)
            bind.execute(sa.text(f"""
                UPDATE {table_name}
                SET created_by = 1
                WHERE created_by IS NULL
            """))

    # =========================================================================
    # 3. GLOBAL_SETTINGS - Add audit_log_retention_days
    # =========================================================================
    if table_exists('global_settings') and not column_exists('global_settings', 'audit_log_retention_days'):
        op.add_column(
            'global_settings',
            sa.Column('audit_log_retention_days', sa.Integer(), nullable=False, server_default='90')
        )

    # =========================================================================
    # 4. NEW TABLES - Legacy role-based tables (kept for compatibility)
    # =========================================================================

    # 4a. role_permissions - Legacy customizable role capabilities
    if not table_exists('role_permissions'):
        op.create_table(
            'role_permissions',
            sa.Column('role', sa.Text(), nullable=False),
            sa.Column('capability', sa.Text(), nullable=False),
            sa.Column('allowed', sa.Boolean(), nullable=False, server_default='0'),
            sa.PrimaryKeyConstraint('role', 'capability')
        )

    # 4b. password_reset_tokens - Self-service password reset
    if not table_exists('password_reset_tokens'):
        op.create_table(
            'password_reset_tokens',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('token_hash', sa.Text(), nullable=False, unique=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )
        op.create_index('idx_password_reset_token_hash', 'password_reset_tokens', ['token_hash'])
        op.create_index('idx_password_reset_expires', 'password_reset_tokens', ['expires_at'])

    # 4c. oidc_config - OIDC provider configuration (singleton)
    if not table_exists('oidc_config'):
        op.create_table(
            'oidc_config',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('provider_url', sa.Text(), nullable=True),
            sa.Column('client_id', sa.Text(), nullable=True),
            sa.Column('client_secret_encrypted', sa.Text(), nullable=True),
            sa.Column('scopes', sa.Text(), nullable=False, server_default='openid profile email groups'),
            sa.Column('claim_for_groups', sa.Text(), nullable=False, server_default='groups'),
            sa.Column('default_group_id', sa.Integer(), nullable=True),  # Added for group-based permissions
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.CheckConstraint('id = 1', name='ck_oidc_config_singleton'),
        )
        # Insert default disabled config
        bind.execute(sa.text("INSERT INTO oidc_config (id, enabled) VALUES (1, 0)"))
    else:
        # Add default_group_id if table exists but column doesn't
        if not column_exists('oidc_config', 'default_group_id'):
            op.add_column('oidc_config', sa.Column('default_group_id', sa.Integer(), nullable=True))

    # 4d. oidc_role_mappings - Legacy group to role mapping
    if not table_exists('oidc_role_mappings'):
        op.create_table(
            'oidc_role_mappings',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('oidc_value', sa.Text(), nullable=False),
            sa.Column('dockmon_role', sa.Text(), nullable=False),
            sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )
        op.create_index('idx_oidc_mapping_value', 'oidc_role_mappings', ['oidc_value'])

    # 4e. stack_metadata - Audit trail for filesystem-based stacks
    if not table_exists('stack_metadata'):
        op.create_table(
            'stack_metadata',
            sa.Column('stack_name', sa.Text(), primary_key=True),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('updated_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )

    # 4f. audit_log - Comprehensive action audit trail
    if not table_exists('audit_log'):
        op.create_table(
            'audit_log',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('username', sa.Text(), nullable=False),
            sa.Column('action', sa.Text(), nullable=False),
            sa.Column('entity_type', sa.Text(), nullable=False),
            sa.Column('entity_id', sa.Text(), nullable=True),
            sa.Column('entity_name', sa.Text(), nullable=True),
            sa.Column('host_id', sa.Text(), nullable=True),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('ip_address', sa.Text(), nullable=True),
            sa.Column('user_agent', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )
        op.create_index('idx_audit_log_user', 'audit_log', ['user_id'])
        op.create_index('idx_audit_log_entity', 'audit_log', ['entity_type', 'entity_id'])
        op.create_index('idx_audit_log_created', 'audit_log', ['created_at'])
        op.create_index('idx_audit_log_action', 'audit_log', ['action'])

    # =========================================================================
    # 5. NEW TABLES - Group-based permissions system
    # =========================================================================

    # 5a. custom_groups - User groups with permissions
    if not table_exists('custom_groups'):
        op.create_table(
            'custom_groups',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.Text(), nullable=False, unique=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('is_system', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('updated_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )
    else:
        # Add is_system if table exists but column doesn't
        if not column_exists('custom_groups', 'is_system'):
            op.add_column('custom_groups', sa.Column('is_system', sa.Boolean(), nullable=False, server_default='0'))

    # 5b. user_group_memberships - User to group mapping
    if not table_exists('user_group_memberships'):
        op.create_table(
            'user_group_memberships',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('custom_groups.id', ondelete='CASCADE'), nullable=False),
            sa.Column('added_by', sa.Integer(), nullable=True),
            sa.Column('added_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint('user_id', 'group_id', name='uq_user_group_membership'),
        )
        op.create_index('idx_user_group_user', 'user_group_memberships', ['user_id'])
        op.create_index('idx_user_group_group', 'user_group_memberships', ['group_id'])

    # 5c. group_permissions - Capabilities assigned to groups
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
        )
        op.create_index('idx_group_permissions_group', 'group_permissions', ['group_id'])

    # 5d. oidc_group_mappings - OIDC to DockMon group mapping
    if not table_exists('oidc_group_mappings'):
        op.create_table(
            'oidc_group_mappings',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('oidc_value', sa.Text(), nullable=False, unique=True),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('custom_groups.id', ondelete='CASCADE'), nullable=False),
            sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )
        op.create_index('idx_oidc_group_mapping_value', 'oidc_group_mappings', ['oidc_value'])

    # =========================================================================
    # 6. API_KEYS TABLE - Add group_id and created_by_user_id
    # =========================================================================
    if table_exists('api_keys'):
        if not column_exists('api_keys', 'group_id'):
            op.add_column('api_keys', sa.Column('group_id', sa.Integer(), nullable=True))

        if not column_exists('api_keys', 'created_by_user_id'):
            op.add_column('api_keys', sa.Column('created_by_user_id', sa.Integer(), nullable=True))

    # =========================================================================
    # 7. SEED DEFAULT SYSTEM GROUPS
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
    # 8. SEED GROUP PERMISSIONS
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
    # 9. MIGRATE EXISTING API KEYS
    # =========================================================================
    if table_exists('api_keys') and admin_group_id:
        # Assign existing API keys to Administrators group if they have no group
        if column_exists('api_keys', 'user_id') and column_exists('api_keys', 'group_id'):
            bind.execute(sa.text("""
                UPDATE api_keys
                SET group_id = :admin_gid,
                    created_by_user_id = user_id
                WHERE group_id IS NULL
            """), {'admin_gid': admin_group_id})
        elif column_exists('api_keys', 'group_id'):
            # No user_id column, just set group_id
            bind.execute(sa.text("""
                UPDATE api_keys
                SET group_id = :admin_gid
                WHERE group_id IS NULL
            """), {'admin_gid': admin_group_id})

    # =========================================================================
    # 10. SET default_group_id FOR OIDC CONFIG
    # =========================================================================
    if table_exists('oidc_config') and readonly_group_id:
        bind.execute(sa.text("""
            UPDATE oidc_config
            SET default_group_id = :gid
            WHERE default_group_id IS NULL
        """), {'gid': readonly_group_id})

    # =========================================================================
    # 11. ADD FIRST USER TO ADMINISTRATORS GROUP
    # =========================================================================
    if admin_group_id:
        # Check if any user-group memberships exist
        result = bind.execute(sa.text("SELECT COUNT(*) FROM user_group_memberships"))
        memberships_exist = result.scalar() > 0

        if not memberships_exist:
            # Get the first user (ID 1, typically the admin created during setup)
            result = bind.execute(sa.text("SELECT id FROM users WHERE id = 1"))
            first_user = result.scalar()

            if first_user:
                bind.execute(sa.text("""
                    INSERT INTO user_group_memberships (user_id, group_id, added_at)
                    VALUES (:user_id, :group_id, :now)
                """), {'user_id': first_user, 'group_id': admin_group_id, 'now': now})

    # =========================================================================
    # 12. UPDATE APP VERSION
    # =========================================================================
    if table_exists('global_settings'):
        bind.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.3.0', id=1)
        )


def downgrade():
    """Revert v2.3.0 schema changes"""

    bind = op.get_bind()

    # =========================================================================
    # 1. DROP GROUP-BASED PERMISSIONS TABLES
    # =========================================================================
    tables_to_drop = [
        'oidc_group_mappings',
        'group_permissions',
        'user_group_memberships',
    ]

    for table_name in tables_to_drop:
        if table_exists(table_name):
            op.drop_table(table_name)

    # =========================================================================
    # 2. REMOVE API_KEYS COLUMNS
    # =========================================================================
    if table_exists('api_keys'):
        if column_exists('api_keys', 'created_by_user_id'):
            op.drop_column('api_keys', 'created_by_user_id')
        if column_exists('api_keys', 'group_id'):
            op.drop_column('api_keys', 'group_id')

    # =========================================================================
    # 3. REMOVE CUSTOM_GROUPS is_system COLUMN (keep table for user data)
    # =========================================================================
    if table_exists('custom_groups') and column_exists('custom_groups', 'is_system'):
        # Delete system groups first
        bind.execute(sa.text("DELETE FROM custom_groups WHERE is_system = 1"))
        op.drop_column('custom_groups', 'is_system')

    # =========================================================================
    # 4. REMOVE OIDC_CONFIG default_group_id COLUMN
    # =========================================================================
    if table_exists('oidc_config') and column_exists('oidc_config', 'default_group_id'):
        op.drop_column('oidc_config', 'default_group_id')

    # =========================================================================
    # 5. DROP LEGACY TABLES
    # =========================================================================
    legacy_tables = [
        'audit_log',
        'stack_metadata',
        'oidc_role_mappings',
        'password_reset_tokens',
        'role_permissions',
        'custom_groups',
    ]

    for table_name in legacy_tables:
        if table_exists(table_name):
            op.drop_table(table_name)

    # Drop oidc_config separately (has CHECK constraint)
    if table_exists('oidc_config'):
        op.drop_table('oidc_config')

    # =========================================================================
    # 6. REMOVE GLOBAL_SETTINGS audit_log_retention_days
    # =========================================================================
    if table_exists('global_settings') and column_exists('global_settings', 'audit_log_retention_days'):
        op.drop_column('global_settings', 'audit_log_retention_days')

    # =========================================================================
    # 7. REMOVE AUDIT COLUMNS from 8 tables
    # =========================================================================
    audit_tables = [
        'docker_hosts',
        'notification_channels',
        'tags',
        'registry_credentials',
        'container_desired_states',
        'container_http_health_checks',
        'update_policies',
        'auto_restart_configs',
    ]

    for table_name in audit_tables:
        if table_exists(table_name):
            if column_exists(table_name, 'created_by'):
                op.drop_column(table_name, 'created_by')
            if column_exists(table_name, 'updated_by'):
                op.drop_column(table_name, 'updated_by')

    # =========================================================================
    # 8. REMOVE USER COLUMNS (use batch mode for SQLite)
    # =========================================================================
    if table_exists('users'):
        # Drop index first
        if index_exists('users', 'ix_users_oidc_subject'):
            op.drop_index('ix_users_oidc_subject', 'users')

        with op.batch_alter_table('users', schema=None) as batch_op:
            user_columns = ['email', 'auth_provider', 'oidc_subject', 'deleted_at', 'deleted_by']
            for col_name in user_columns:
                if column_exists('users', col_name):
                    batch_op.drop_column(col_name)

    # =========================================================================
    # 9. DOWNGRADE APP VERSION
    # =========================================================================
    if table_exists('global_settings'):
        bind.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.8', id=1)
        )
