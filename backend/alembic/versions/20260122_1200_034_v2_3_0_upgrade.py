"""v2.3.0 Multi-User Support & Group-Based Permissions

Revision ID: 034_v2_3_0
Revises: 033_v2_2_9
Create Date: 2026-01-22

CHANGES IN v2.3.0:
- Multi-user support with group-based access control
- Users belong to groups, permissions come from groups (union semantics)
- API keys belong to exactly one group
- OIDC authentication with group mapping
- Audit columns and comprehensive audit logging
- Custom groups for organization
- Account lockout (failed_login_attempts, locked_until, must_change_password)
- OIDC PKCE control for confidential clients (disable_pkce_with_secret)

SCHEMA CHANGES:

1. User table additions:
   - email (unique, for password reset and OIDC matching)
   - auth_provider ('local' or 'oidc')
   - oidc_subject (OIDC subject identifier, unique index)
   - failed_login_attempts (account lockout counter)
   - locked_until (account lockout expiry)
   - must_change_password (force password change on next login)

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
   - global_settings: Add audit_log_retention_days, session_timeout_hours
   - custom_groups: Add is_system column
   - oidc_config: Add default_group_id, sso_default, disable_pkce_with_secret columns
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
revision = '034_v2_3_0'
down_revision = '033_v2_2_9'
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
    'oidc.manage',
    'groups.manage',
    'audit.view',
    'apikeys.manage_other',
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



def upgrade():
    """Apply v2.3.0 schema changes"""

    bind = op.get_bind()

    # =========================================================================
    # 1. USER TABLE - Add OIDC and multi-user support
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

        # Set placeholder email for existing users without one
        if column_exists('users', 'email'):
            bind.execute(sa.text("""
                UPDATE users
                SET email = username || '@localhost'
                WHERE email IS NULL
            """))

        # Account lockout columns (security hardening)
        with op.batch_alter_table('users', schema=None) as batch_op:
            if not column_exists('users', 'failed_login_attempts'):
                batch_op.add_column(sa.Column(
                    'failed_login_attempts', sa.Integer(),
                    nullable=False, server_default='0'
                ))

            if not column_exists('users', 'locked_until'):
                batch_op.add_column(sa.Column('locked_until', sa.DateTime(), nullable=True))

            if not column_exists('users', 'must_change_password'):
                batch_op.add_column(sa.Column(
                    'must_change_password', sa.Boolean(),
                    nullable=False, server_default='0'
                ))

        # Create unique index on oidc_subject (outside batch for safety)
        if column_exists('users', 'oidc_subject') and not index_exists('users', 'uq_users_oidc_subject'):
            op.create_index('uq_users_oidc_subject', 'users', ['oidc_subject'], unique=True)

    # =========================================================================
    # 1b. FK FIXES - Ensure hard-delete safety
    # =========================================================================
    # SQLite cannot ALTER FK constraints in-place. We use batch mode with
    # recreate='always' to rebuild each table, dropping the old FK and
    # creating a new one with the correct ondelete policy.

    fk_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}

    # user_prefs: add CASCADE on delete (so deleting a user removes their prefs)
    if table_exists('user_prefs'):
        with op.batch_alter_table('user_prefs', schema=None, recreate='always',
                                  naming_convention=fk_naming) as batch_op:
            batch_op.drop_constraint('fk_user_prefs_user_id_users', type_='foreignkey')
            batch_op.create_foreign_key('fk_user_prefs_user_id_users', 'users',
                                        ['user_id'], ['id'], ondelete='CASCADE')

    # registration_tokens.created_by_user_id: CASCADE -> SET NULL, make nullable
    if table_exists('registration_tokens') and column_exists('registration_tokens', 'created_by_user_id'):
        with op.batch_alter_table('registration_tokens', schema=None, recreate='always',
                                  naming_convention=fk_naming) as batch_op:
            batch_op.alter_column('created_by_user_id', existing_type=sa.Integer(),
                                  nullable=True)
            batch_op.drop_constraint('fk_registration_tokens_created_by_user_id_users',
                                     type_='foreignkey')
            batch_op.create_foreign_key('fk_registration_tokens_created_by_user_id_users',
                                        'users', ['created_by_user_id'], ['id'],
                                        ondelete='SET NULL')

    # batch_jobs.user_id: add SET NULL on delete (already nullable)
    if table_exists('batch_jobs') and column_exists('batch_jobs', 'user_id'):
        with op.batch_alter_table('batch_jobs', schema=None, recreate='always',
                                  naming_convention=fk_naming) as batch_op:
            batch_op.drop_constraint('fk_batch_jobs_user_id_users', type_='foreignkey')
            batch_op.create_foreign_key('fk_batch_jobs_user_id_users', 'users',
                                        ['user_id'], ['id'], ondelete='SET NULL')

    # deployments.user_id: CASCADE -> SET NULL, make nullable
    if table_exists('deployments') and column_exists('deployments', 'user_id'):
        with op.batch_alter_table('deployments', schema=None, recreate='always',
                                  naming_convention=fk_naming) as batch_op:
            batch_op.alter_column('user_id', existing_type=sa.Integer(),
                                  nullable=True)
            batch_op.drop_constraint('fk_deployments_user_id_users', type_='foreignkey')
            batch_op.create_foreign_key('fk_deployments_user_id_users', 'users',
                                        ['user_id'], ['id'], ondelete='SET NULL')

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

    audit_fk_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}

    for table_name in audit_tables:
        if table_exists(table_name):
            # Add columns first (plain integers — SQLite ADD COLUMN can't include FK)
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

            # Rebuild table to add FK constraints (SET NULL on user delete)
            with op.batch_alter_table(table_name, recreate='always',
                                      naming_convention=audit_fk_naming) as batch_op:
                batch_op.create_foreign_key(
                    f'fk_{table_name}_created_by_users', 'users',
                    ['created_by'], ['id'], ondelete='SET NULL')
                batch_op.create_foreign_key(
                    f'fk_{table_name}_updated_by_users', 'users',
                    ['updated_by'], ['id'], ondelete='SET NULL')

    # =========================================================================
    # 3. GLOBAL_SETTINGS - Add audit_log_retention_days
    # =========================================================================
    if table_exists('global_settings') and not column_exists('global_settings', 'audit_log_retention_days'):
        op.add_column(
            'global_settings',
            sa.Column('audit_log_retention_days', sa.Integer(), nullable=False, server_default='90')
        )

    # =========================================================================
    # 3b. GLOBAL_SETTINGS - Add session_timeout_hours
    # =========================================================================
    if table_exists('global_settings') and not column_exists('global_settings', 'session_timeout_hours'):
        op.add_column(
            'global_settings',
            sa.Column('session_timeout_hours', sa.Integer(), nullable=False, server_default='24')
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
        op.create_index('idx_password_reset_expires', 'password_reset_tokens', ['expires_at'])

    # 4c. custom_groups - Must be created before oidc_config (FK dependency)
    if not table_exists('custom_groups'):
        op.create_table(
            'custom_groups',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.Text(), nullable=False, unique=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('is_system', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )
    else:
        if not column_exists('custom_groups', 'is_system'):
            op.add_column('custom_groups', sa.Column('is_system', sa.Boolean(), nullable=False, server_default='0'))

    # 4d. oidc_config - OIDC provider configuration (singleton)
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
            sa.Column('default_group_id', sa.Integer(), sa.ForeignKey('custom_groups.id', ondelete='SET NULL'), nullable=True),
            sa.Column('sso_default', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('disable_pkce_with_secret', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.CheckConstraint('id = 1', name='ck_oidc_config_singleton'),
        )
        # Insert default disabled config
        bind.execute(sa.text("INSERT INTO oidc_config (id, enabled) VALUES (1, 0)"))
    else:
        if not column_exists('oidc_config', 'default_group_id'):
            op.add_column('oidc_config', sa.Column('default_group_id', sa.Integer(), nullable=True))
        if not column_exists('oidc_config', 'sso_default'):
            op.add_column('oidc_config', sa.Column('sso_default', sa.Boolean(), nullable=False, server_default='0'))
        if not column_exists('oidc_config', 'disable_pkce_with_secret'):
            op.add_column('oidc_config', sa.Column('disable_pkce_with_secret', sa.Boolean(), nullable=False, server_default='0'))

        # Rebuild to add FK on default_group_id → custom_groups (ADD COLUMN can't include FK in SQLite)
        if column_exists('oidc_config', 'default_group_id'):
            oidc_fk_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
            with op.batch_alter_table('oidc_config', recreate='always',
                                      naming_convention=oidc_fk_naming) as batch_op:
                batch_op.create_foreign_key(
                    'fk_oidc_config_default_group_id_custom_groups', 'custom_groups',
                    ['default_group_id'], ['id'], ondelete='SET NULL')

    # 4e. oidc_role_mappings - Legacy group to role mapping
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
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
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
    # Note: custom_groups was created in section 4c (before oidc_config, due to FK dependency)

    # 5a. user_group_memberships - User to group mapping
    if not table_exists('user_group_memberships'):
        op.create_table(
            'user_group_memberships',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('custom_groups.id', ondelete='CASCADE'), nullable=False),
            sa.Column('added_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
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
    # 8. SEED GROUP PERMISSIONS (each group checked independently for partial-apply safety)
    # Uses INSERT OR IGNORE to handle partial prior runs — if a previous run
    # seeded some but not all capabilities, this fills in the missing ones.
    # =========================================================================
    for group_id, capabilities in [
        (admin_group_id, ALL_CAPABILITIES),
        (operators_group_id, OPERATOR_CAPABILITIES),
        (readonly_group_id, READONLY_CAPABILITIES),
    ]:
        if group_id:
            for capability in capabilities:
                bind.execute(sa.text("""
                    INSERT OR IGNORE INTO group_permissions
                        (group_id, capability, allowed, created_at, updated_at)
                    VALUES (:group_id, :capability, 1, :timestamp, :timestamp)
                """), {'group_id': group_id, 'capability': capability, 'timestamp': now})

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
    # 9b. API_KEYS - Enforce NOT NULL and FK constraints
    # =========================================================================
    # Now that all api_keys have group_id set, enforce NOT NULL and add FKs.
    # Must happen after section 9 (data migration) so no NULL group_ids remain.
    if table_exists('api_keys') and column_exists('api_keys', 'group_id'):
        # Safety check: verify data migration completed before enforcing NOT NULL
        null_count = bind.execute(sa.text(
            "SELECT COUNT(*) FROM api_keys WHERE group_id IS NULL"
        )).scalar()
        if null_count > 0:
            raise RuntimeError(
                f"Cannot enforce NOT NULL on api_keys.group_id: {null_count} rows still have NULL. "
                "Ensure group seeding completed successfully."
            )
        with op.batch_alter_table('api_keys', recreate='always',
                                  naming_convention=fk_naming) as batch_op:
            batch_op.alter_column('group_id', existing_type=sa.Integer(), nullable=False)
            batch_op.create_foreign_key('fk_api_keys_group_id_custom_groups', 'custom_groups',
                                        ['group_id'], ['id'], ondelete='RESTRICT')
            batch_op.create_foreign_key('fk_api_keys_created_by_user_id_users', 'users',
                                        ['created_by_user_id'], ['id'], ondelete='SET NULL')

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
    # 12. FIX OIDC PASSWORD SENTINEL
    # =========================================================================
    # OIDC users should never have an empty password_hash (could be confused
    # with a valid empty string). Use a sentinel that no hash algorithm produces.
    if table_exists('users') and column_exists('users', 'auth_provider'):
        bind.execute(sa.text("""
            UPDATE users
            SET password_hash = '!OIDC_NO_PASSWORD'
            WHERE auth_provider = 'oidc' AND (password_hash = '' OR password_hash IS NULL)
        """))

    # =========================================================================
    # 13. VERIFICATION & FIXUP (SQLite batch mode resilience)
    # =========================================================================
    # SQLite's batch_alter_table with recreate='always' can silently fail to
    # apply schema changes. This section verifies critical changes were applied
    # and re-applies them if necessary.

    # 13a. Verify user columns were added
    if table_exists('users'):
        for col_name, col_def in [
            ('failed_login_attempts', sa.Column('failed_login_attempts', sa.Integer(), nullable=False, server_default='0')),
            ('locked_until', sa.Column('locked_until', sa.DateTime(), nullable=True)),
            ('must_change_password', sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default='0')),
        ]:
            if not column_exists('users', col_name):
                op.add_column('users', col_def)

        # Verify NOT NULL constraints (SQLite ADD COLUMN silently drops NOT NULL)
        inspector = get_inspector()
        user_cols = {col['name']: col for col in inspector.get_columns('users')}
        not_null_cols = [
            ('failed_login_attempts', sa.Integer(), '0'),
            ('must_change_password', sa.Boolean(), '0'),
        ]
        needs_rebuild = any(
            col_name in user_cols and user_cols[col_name].get('nullable', True)
            for col_name, _, _ in not_null_cols
        )
        if needs_rebuild:
            # Fill NULLs before enforcing NOT NULL
            for col_name, _, default in not_null_cols:
                bind.execute(sa.text(
                    f"UPDATE users SET {col_name} = {default} WHERE {col_name} IS NULL"
                ))
            with op.batch_alter_table('users', schema=None, recreate='always') as batch_op:
                for col_name, col_type, default in not_null_cols:
                    batch_op.alter_column(col_name, existing_type=col_type,
                                          nullable=False, server_default=default)

        # Verify unique index on oidc_subject
        if column_exists('users', 'oidc_subject'):
            if index_exists('users', 'ix_users_oidc_subject'):
                op.drop_index('ix_users_oidc_subject', 'users')
            if not index_exists('users', 'uq_users_oidc_subject'):
                op.create_index('uq_users_oidc_subject', 'users', ['oidc_subject'], unique=True)

    # 13b. Verify FK on_delete policies
    def _get_fk_ondelete(tbl: str, col: str) -> str:
        fks = bind.execute(sa.text(f"PRAGMA foreign_key_list({tbl})")).fetchall()
        for fk in fks:
            if fk[3] == col:
                return fk[6]
        return 'UNKNOWN'

    # FK fixes for tables referencing users
    user_fk_fixes = [
        ('user_prefs', 'user_id', 'CASCADE', False),
        ('registration_tokens', 'created_by_user_id', 'SET NULL', True),
        ('batch_jobs', 'user_id', 'SET NULL', False),
        ('deployments', 'user_id', 'SET NULL', True),
    ]

    for tbl, col, expected_policy, make_nullable in user_fk_fixes:
        if table_exists(tbl) and column_exists(tbl, col):
            if _get_fk_ondelete(tbl, col) != expected_policy:
                fk_name = f"fk_{tbl}_{col}_users"
                with op.batch_alter_table(tbl, recreate='always',
                                          naming_convention=fk_naming) as batch_op:
                    if make_nullable:
                        batch_op.alter_column(col, existing_type=sa.Integer(), nullable=True)
                    batch_op.drop_constraint(fk_name, type_='foreignkey')
                    batch_op.create_foreign_key(fk_name, 'users',
                                                [col], ['id'], ondelete=expected_policy)

    # FK fixes for api_keys (group_id → custom_groups, created_by_user_id → users)
    if table_exists('api_keys') and column_exists('api_keys', 'group_id'):
        actual = _get_fk_ondelete('api_keys', 'group_id')
        if actual not in ('RESTRICT', 'NO ACTION'):
            # FK missing or wrong policy — recreate table to add it
            with op.batch_alter_table('api_keys', recreate='always',
                                      naming_convention=fk_naming) as batch_op:
                batch_op.alter_column('group_id', existing_type=sa.Integer(), nullable=False)
                batch_op.create_foreign_key('fk_api_keys_group_id_custom_groups', 'custom_groups',
                                            ['group_id'], ['id'], ondelete='RESTRICT')
                batch_op.create_foreign_key('fk_api_keys_created_by_user_id_users', 'users',
                                            ['created_by_user_id'], ['id'], ondelete='SET NULL')

    # 13c. Verify oidc_config.default_group_id FK
    if table_exists('oidc_config') and column_exists('oidc_config', 'default_group_id'):
        if _get_fk_ondelete('oidc_config', 'default_group_id') != 'SET NULL':
            oidc_fk_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
            with op.batch_alter_table('oidc_config', recreate='always',
                                      naming_convention=oidc_fk_naming) as batch_op:
                batch_op.create_foreign_key(
                    'fk_oidc_config_default_group_id_custom_groups', 'custom_groups',
                    ['default_group_id'], ['id'], ondelete='SET NULL')

    # 13d. Verify audit column FKs on 8 tables
    for table_name in audit_tables:
        if table_exists(table_name) and column_exists(table_name, 'created_by'):
            if _get_fk_ondelete(table_name, 'created_by') != 'SET NULL':
                with op.batch_alter_table(table_name, recreate='always',
                                          naming_convention=audit_fk_naming) as batch_op:
                    batch_op.create_foreign_key(
                        f'fk_{table_name}_created_by_users', 'users',
                        ['created_by'], ['id'], ondelete='SET NULL')
                    batch_op.create_foreign_key(
                        f'fk_{table_name}_updated_by_users', 'users',
                        ['updated_by'], ['id'], ondelete='SET NULL')


def downgrade():
    """Revert v2.3.0 schema changes"""

    bind = op.get_bind()
    fk_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}

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
    # 2. REMOVE API_KEYS COLUMNS (have FK constraints, need batch mode)
    # =========================================================================
    if table_exists('api_keys'):
        cols_to_drop = []
        if column_exists('api_keys', 'created_by_user_id'):
            cols_to_drop.append('created_by_user_id')
        if column_exists('api_keys', 'group_id'):
            cols_to_drop.append('group_id')
        if cols_to_drop:
            with op.batch_alter_table('api_keys', recreate='always',
                                      naming_convention=fk_naming) as batch_op:
                for col in cols_to_drop:
                    batch_op.drop_column(col)

    # =========================================================================
    # 3. DROP NEW TABLES (oidc_config before custom_groups due to FK)
    # =========================================================================
    new_tables = [
        'audit_log',
        'stack_metadata',
        'oidc_role_mappings',
        'oidc_config',
        'password_reset_tokens',
        'role_permissions',
        'custom_groups',
    ]

    for table_name in new_tables:
        if table_exists(table_name):
            op.drop_table(table_name)

    # =========================================================================
    # 4. REMOVE GLOBAL_SETTINGS COLUMNS
    # =========================================================================
    if table_exists('global_settings'):
        if column_exists('global_settings', 'audit_log_retention_days'):
            op.drop_column('global_settings', 'audit_log_retention_days')
        if column_exists('global_settings', 'session_timeout_hours'):
            op.drop_column('global_settings', 'session_timeout_hours')

    # =========================================================================
    # 5. REMOVE AUDIT COLUMNS from 8 tables (have FK constraints, need batch mode)
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

    audit_fk_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}

    for table_name in audit_tables:
        if table_exists(table_name):
            cols_to_drop = []
            if column_exists(table_name, 'created_by'):
                cols_to_drop.append('created_by')
            if column_exists(table_name, 'updated_by'):
                cols_to_drop.append('updated_by')
            if cols_to_drop:
                with op.batch_alter_table(table_name, recreate='always',
                                          naming_convention=audit_fk_naming) as batch_op:
                    for col in cols_to_drop:
                        batch_op.drop_column(col)

    # =========================================================================
    # 6. REVERT FK ON_DELETE POLICIES to pre-v2.3.0 state
    # =========================================================================
    # user_prefs: CASCADE → default (no explicit ondelete)
    if table_exists('user_prefs') and column_exists('user_prefs', 'user_id'):
        with op.batch_alter_table('user_prefs', recreate='always',
                                  naming_convention=fk_naming) as batch_op:
            batch_op.drop_constraint('fk_user_prefs_user_id_users', type_='foreignkey')
            batch_op.create_foreign_key('fk_user_prefs_user_id_users', 'users',
                                        ['user_id'], ['id'])

    # registration_tokens: SET NULL + nullable → CASCADE + NOT NULL
    if table_exists('registration_tokens') and column_exists('registration_tokens', 'created_by_user_id'):
        # Fill NULLs before enforcing NOT NULL (NULLs can exist from SET NULL FK cascade)
        bind.execute(sa.text("""
            UPDATE registration_tokens SET created_by_user_id = 1
            WHERE created_by_user_id IS NULL
        """))
        with op.batch_alter_table('registration_tokens', recreate='always',
                                  naming_convention=fk_naming) as batch_op:
            batch_op.alter_column('created_by_user_id', existing_type=sa.Integer(),
                                  nullable=False)
            batch_op.drop_constraint('fk_registration_tokens_created_by_user_id_users',
                                     type_='foreignkey')
            batch_op.create_foreign_key('fk_registration_tokens_created_by_user_id_users',
                                        'users', ['created_by_user_id'], ['id'],
                                        ondelete='CASCADE')

    # batch_jobs: SET NULL → default (no explicit ondelete)
    if table_exists('batch_jobs') and column_exists('batch_jobs', 'user_id'):
        with op.batch_alter_table('batch_jobs', recreate='always',
                                  naming_convention=fk_naming) as batch_op:
            batch_op.drop_constraint('fk_batch_jobs_user_id_users', type_='foreignkey')
            batch_op.create_foreign_key('fk_batch_jobs_user_id_users', 'users',
                                        ['user_id'], ['id'])

    # deployments: SET NULL + nullable → CASCADE + NOT NULL
    if table_exists('deployments') and column_exists('deployments', 'user_id'):
        # Fill NULLs before enforcing NOT NULL (NULLs can exist from SET NULL FK cascade)
        bind.execute(sa.text("""
            UPDATE deployments SET user_id = 1
            WHERE user_id IS NULL
        """))
        with op.batch_alter_table('deployments', recreate='always',
                                  naming_convention=fk_naming) as batch_op:
            batch_op.alter_column('user_id', existing_type=sa.Integer(),
                                  nullable=False)
            batch_op.drop_constraint('fk_deployments_user_id_users', type_='foreignkey')
            batch_op.create_foreign_key('fk_deployments_user_id_users', 'users',
                                        ['user_id'], ['id'], ondelete='CASCADE')

    # =========================================================================
    # 7. REMOVE USER COLUMNS (use batch mode for SQLite)
    # =========================================================================
    if table_exists('users'):
        # Drop indexes first
        if index_exists('users', 'uq_users_oidc_subject'):
            op.drop_index('uq_users_oidc_subject', 'users')
        if index_exists('users', 'ix_users_oidc_subject'):
            op.drop_index('ix_users_oidc_subject', 'users')

        with op.batch_alter_table('users', schema=None) as batch_op:
            user_columns = [
                'email', 'auth_provider', 'oidc_subject',
                'failed_login_attempts', 'locked_until',
                'must_change_password',
            ]
            for col_name in user_columns:
                if column_exists('users', col_name):
                    batch_op.drop_column(col_name)

