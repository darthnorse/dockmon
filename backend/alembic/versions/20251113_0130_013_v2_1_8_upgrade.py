"""v2.1.8 upgrade - Bug fix release + API Key Authentication

Revision ID: 013_v2_1_8
Revises: 012_v2_1_7
Create Date: 2025-11-13

CHANGES IN v2.1.8:
- Fix custom template persistence in alert rules (GitHub Issue #43)
- Add API key authentication system (Beta feature - GitHub Issue #35)
- Add role column to users table (future-proofing for RBAC)
- Add api_keys table for programmatic authentication
- Migrate legacy 'owner' role to 'admin' for consistency
- Update app_version to '2.1.8'

BUG FIXES:
- Custom message templates in alert rules didn't persist
  - Root cause: API data flow asymmetry - GET endpoint didn't return custom_template,
    CREATE endpoint didn't pass it to database
  - Fix: Added custom_template to GET response and CREATE flow
  - Impact: Custom templates now persist across page refreshes and edits
  - Note: Data was always saved in database, just not returned to frontend

NEW FEATURES:
- API key authentication for external tools (Ansible, Homepage, etc.)
- SHA256 key hashing for secure storage
- Scope-based permissions (read/write/admin)
- Optional IP allowlists and expiration dates
- Usage tracking and revocation support
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '013_v2_1_8'
down_revision = '012_v2_1_7'
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


def upgrade() -> None:
    """Update to v2.1.8"""

    # 1. Add role column to users (future-proofing for RBAC)
    if not column_exists('users', 'role'):
        op.add_column('users',
            sa.Column('role', sa.Text(), nullable=False, server_default='admin'))

    # 1b. Migrate legacy 'owner' role to 'admin' (v2.0.0 used 'owner' as default)
    # This ensures consistency - 'admin' is the canonical admin role going forward
    if table_exists('users'):
        op.execute(
            sa.text("UPDATE users SET role = 'admin' WHERE role = 'owner'")
        )

    # 2. Create api_keys table
    if not table_exists('api_keys'):
        op.create_table(
            'api_keys',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('key_hash', sa.Text(), nullable=False, unique=True),
            sa.Column('key_prefix', sa.Text(), nullable=False),
            sa.Column('scopes', sa.Text(), nullable=False, server_default='read'),
            sa.Column('allowed_ips', sa.Text(), nullable=True),
            sa.Column('last_used_at', sa.DateTime(), nullable=True),
            sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.Column('revoked_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )

        # Create indexes for performance
        op.create_index('idx_api_keys_user_id', 'api_keys', ['user_id'])
        op.create_index('idx_api_keys_key_hash', 'api_keys', ['key_hash'])



def downgrade() -> None:
    """Downgrade from v2.1.8"""

    # Drop indexes and table
    if table_exists('api_keys'):
        op.drop_index('idx_api_keys_key_hash', 'api_keys')
        op.drop_index('idx_api_keys_user_id', 'api_keys')
        op.drop_table('api_keys')

    # Remove role column
    if column_exists('users', 'role'):
        op.drop_column('users', 'role')
