"""v2.3.0 Multi-User Support Phase 1 - Database & Audit Foundation

Revision ID: 033_v2_3_0
Revises: 032_v2_2_8
Create Date: 2026-01-22

CHANGES IN v2.3.0 (Phase 1):
- Multi-user support foundation with role-based access control
- Audit columns (created_by, updated_by) added to 8 key tables
- New User columns for OIDC authentication and soft delete
- New tables: role_permissions, oidc_config, oidc_role_mappings,
  stack_metadata, audit_log, password_reset_token
- Comprehensive audit logging infrastructure

SCHEMA CHANGES:
1. User table additions:
   - email (for password reset and OIDC matching)
   - auth_provider ('local' or 'oidc')
   - oidc_subject (OIDC subject identifier)
   - deleted_at (soft delete timestamp)
   - deleted_by (admin who deleted)

2. Audit columns added to:
   - docker_hosts
   - notification_channels
   - tags
   - registry_credentials
   - container_desired_states
   - container_http_health_checks
   - update_policies
   - auto_restart_configs

3. New tables:
   - role_permissions (customizable role capabilities)
   - password_reset_token (self-service password reset)
   - oidc_config (OIDC provider configuration)
   - oidc_role_mappings (group to role mapping)
   - stack_metadata (audit trail for filesystem stacks)
   - audit_log (comprehensive action audit trail)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '033_v2_3_0'
down_revision = '032_v2_2_8'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade():
    """Apply Phase 1 multi-user support schema changes"""

    # =========================================================================
    # 1. USER TABLE - Add OIDC and soft delete support
    # =========================================================================
    if table_exists('users'):
        # Email - required for password reset and OIDC matching
        if not column_exists('users', 'email'):
            op.add_column('users', sa.Column('email', sa.Text(), nullable=True))
            # Set placeholder email for existing users (admin should update)
            op.execute(sa.text("""
                UPDATE users
                SET email = username || '@localhost'
                WHERE email IS NULL
            """))
            # Add unique constraint for email
            op.create_unique_constraint('uq_users_email', 'users', ['email'])

        # Auth provider - 'local' or 'oidc'
        if not column_exists('users', 'auth_provider'):
            op.add_column('users', sa.Column('auth_provider', sa.Text(), server_default='local', nullable=False))

        # OIDC subject identifier (indexed for login performance)
        if not column_exists('users', 'oidc_subject'):
            op.add_column('users', sa.Column('oidc_subject', sa.Text(), nullable=True))
            op.create_index('ix_users_oidc_subject', 'users', ['oidc_subject'])

        # Soft delete support
        if not column_exists('users', 'deleted_at'):
            op.add_column('users', sa.Column('deleted_at', sa.DateTime(), nullable=True))

        if not column_exists('users', 'deleted_by'):
            op.add_column('users', sa.Column('deleted_by', sa.Integer(), nullable=True))

    # =========================================================================
    # 2. AUDIT COLUMNS - Add created_by/updated_by to 8 tables
    # =========================================================================

    # Tables requiring audit columns
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
            # created_by - foreign key to users.id
            if not column_exists(table_name, 'created_by'):
                op.add_column(table_name, sa.Column('created_by', sa.Integer(), nullable=True))

            # updated_by - foreign key to users.id
            if not column_exists(table_name, 'updated_by'):
                op.add_column(table_name, sa.Column('updated_by', sa.Integer(), nullable=True))

            # Set existing records to created_by = 1 (first user, typically admin)
            # NOTE: User ID 1 is the initial admin user created during setup.
            # This ensures pre-existing records have a valid audit trail owner.
            op.execute(sa.text(f"""
                UPDATE {table_name}
                SET created_by = 1
                WHERE created_by IS NULL
            """))

    # =========================================================================
    # 3. NEW TABLES
    # =========================================================================

    # 3a. role_permissions - Customizable role capabilities
    if not table_exists('role_permissions'):
        op.create_table(
            'role_permissions',
            sa.Column('role', sa.Text(), nullable=False),
            sa.Column('capability', sa.Text(), nullable=False),
            sa.Column('allowed', sa.Boolean(), nullable=False, server_default='0'),
            sa.PrimaryKeyConstraint('role', 'capability')
        )

        # Insert default permissions based on capability matrix
        default_permissions = [
            # Admin capabilities (all allowed)
            ('admin', 'hosts.manage', True),
            ('admin', 'hosts.view', True),
            ('admin', 'stacks.edit', True),
            ('admin', 'stacks.deploy', True),
            ('admin', 'stacks.view', True),
            ('admin', 'stacks.view_env', True),
            ('admin', 'containers.operate', True),
            ('admin', 'containers.shell', True),
            ('admin', 'containers.update', True),
            ('admin', 'containers.view', True),
            ('admin', 'containers.logs', True),
            ('admin', 'containers.view_env', True),
            ('admin', 'healthchecks.manage', True),
            ('admin', 'healthchecks.test', True),
            ('admin', 'healthchecks.view', True),
            ('admin', 'batch.create', True),
            ('admin', 'batch.view', True),
            ('admin', 'policies.manage', True),
            ('admin', 'policies.view', True),
            ('admin', 'alerts.manage', True),
            ('admin', 'alerts.view', True),
            ('admin', 'notifications.manage', True),
            ('admin', 'notifications.view', True),
            ('admin', 'registry.manage', True),
            ('admin', 'registry.view', True),
            ('admin', 'agents.manage', True),
            ('admin', 'agents.view', True),
            ('admin', 'settings.manage', True),
            ('admin', 'users.manage', True),
            ('admin', 'audit.view', True),
            ('admin', 'apikeys.manage_own', True),
            ('admin', 'apikeys.manage_other', True),
            ('admin', 'tags.manage', True),
            ('admin', 'tags.view', True),
            ('admin', 'events.view', True),

            # User capabilities (operators - can use, limited config)
            ('user', 'hosts.view', True),
            ('user', 'stacks.deploy', True),
            ('user', 'stacks.view', True),
            ('user', 'stacks.view_env', True),
            ('user', 'containers.operate', True),
            ('user', 'containers.view', True),
            ('user', 'containers.logs', True),
            ('user', 'containers.view_env', True),
            ('user', 'healthchecks.test', True),
            ('user', 'healthchecks.view', True),
            ('user', 'batch.create', True),
            ('user', 'batch.view', True),
            ('user', 'policies.view', True),
            ('user', 'alerts.view', True),
            ('user', 'notifications.view', True),
            ('user', 'agents.view', True),
            ('user', 'apikeys.manage_own', True),
            ('user', 'tags.manage', True),
            ('user', 'tags.view', True),
            ('user', 'events.view', True),

            # Readonly capabilities (view only)
            ('readonly', 'hosts.view', True),
            ('readonly', 'stacks.view', True),
            ('readonly', 'containers.view', True),
            ('readonly', 'containers.logs', True),
            ('readonly', 'healthchecks.view', True),
            ('readonly', 'batch.view', True),
            ('readonly', 'policies.view', True),
            ('readonly', 'alerts.view', True),
            ('readonly', 'notifications.view', True),
            ('readonly', 'agents.view', True),
            ('readonly', 'tags.view', True),
            ('readonly', 'events.view', True),
        ]

        for role, capability, allowed in default_permissions:
            op.execute(sa.text("""
                INSERT INTO role_permissions (role, capability, allowed)
                VALUES (:role, :capability, :allowed)
            """).bindparams(role=role, capability=capability, allowed=allowed))

    # 3b. password_reset_token - Self-service password reset
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

    # 3c. oidc_config - OIDC provider configuration (singleton)
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
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.CheckConstraint('id = 1', name='ck_oidc_config_singleton'),
        )

        # Insert default disabled config
        op.execute(sa.text("""
            INSERT INTO oidc_config (id, enabled)
            VALUES (1, 0)
        """))

    # 3d. oidc_role_mappings - Group to role mapping
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

        # Insert default mappings
        default_mappings = [
            ('dockmon-admins', 'admin', 100),
            ('dockmon-operators', 'user', 50),
            ('dockmon-viewers', 'readonly', 10),
        ]

        for oidc_value, dockmon_role, priority in default_mappings:
            op.execute(sa.text("""
                INSERT INTO oidc_role_mappings (oidc_value, dockmon_role, priority)
                VALUES (:oidc_value, :dockmon_role, :priority)
            """).bindparams(oidc_value=oidc_value, dockmon_role=dockmon_role, priority=priority))

    # 3e. stack_metadata - Audit trail for filesystem-based stacks
    if not table_exists('stack_metadata'):
        op.create_table(
            'stack_metadata',
            sa.Column('stack_name', sa.Text(), primary_key=True),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('updated_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )

    # 3f. audit_log - Comprehensive action audit trail
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
    # 4. UPDATE APP VERSION
    # =========================================================================
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.3.0', id=1)
        )


def downgrade():
    """Revert Phase 1 multi-user support schema changes"""

    # =========================================================================
    # 1. DROP NEW TABLES (reverse order)
    # =========================================================================
    tables_to_drop = [
        'audit_log',
        'stack_metadata',
        'oidc_role_mappings',
        'oidc_config',
        'password_reset_tokens',
        'role_permissions',
    ]

    for table_name in tables_to_drop:
        if table_exists(table_name):
            op.drop_table(table_name)

    # =========================================================================
    # 2. REMOVE AUDIT COLUMNS from 8 tables
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
    # 3. REMOVE USER COLUMNS
    # =========================================================================
    if table_exists('users'):
        # Drop unique constraint on email first (if it exists)
        try:
            op.drop_constraint('uq_users_email', 'users', type_='unique')
        except Exception:
            pass  # Constraint may not exist

        # Drop index on oidc_subject (if it exists)
        try:
            op.drop_index('ix_users_oidc_subject', 'users')
        except Exception:
            pass  # Index may not exist

        user_columns_to_remove = ['email', 'auth_provider', 'oidc_subject', 'deleted_at', 'deleted_by']
        for col_name in user_columns_to_remove:
            if column_exists('users', col_name):
                op.drop_column('users', col_name)

    # =========================================================================
    # 4. DOWNGRADE APP VERSION
    # =========================================================================
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.8', id=1)
        )
