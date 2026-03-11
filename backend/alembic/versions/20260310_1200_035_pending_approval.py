"""Pending Approval for OIDC Users (v2.6.0)

Revision ID: 035_pending_approval
Revises: 034_v2_3_0
Create Date: 2026-03-10

CHANGES:
- users.approved: BOOLEAN NOT NULL DEFAULT 1 (existing users unaffected)
- oidc_config.require_approval: BOOLEAN NOT NULL DEFAULT 0
- oidc_config.approval_notify_channel_ids: TEXT, nullable (JSON array of channel IDs)

SQLite ADD COLUMN silently drops NOT NULL, so we use batch_alter_table
with recreate='always' to rebuild the table and enforce NOT NULL constraints.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '035_pending_approval'
down_revision = '034_v2_3_0'
branch_labels = None
depends_on = None


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


def _ensure_not_null(table_name: str, column_name: str, col_type, default_value: str):
    """Add column with NOT NULL constraint, handling SQLite limitations.

    SQLite ADD COLUMN silently drops NOT NULL, so this:
    1. Adds the column as nullable (if missing)
    2. Backfills NULLs with the default value
    3. Rebuilds the table to enforce NOT NULL
    4. Verifies the constraint was applied, retries if not
    """
    bind = op.get_bind()

    if not column_exists(table_name, column_name):
        op.add_column(table_name, sa.Column(
            column_name, col_type, nullable=True, server_default=default_value
        ))

    if not column_exists(table_name, column_name):
        return

    bind.execute(sa.text(
        f"UPDATE {table_name} SET {column_name} = {default_value} WHERE {column_name} IS NULL"
    ))
    with op.batch_alter_table(table_name, schema=None, recreate='always') as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=col_type,
            nullable=False,
            server_default=default_value,
        )

    inspector = get_inspector()
    for col in inspector.get_columns(table_name):
        if col['name'] == column_name:
            if col.get('nullable', True):
                bind.execute(sa.text(
                    f"UPDATE {table_name} SET {column_name} = {default_value} WHERE {column_name} IS NULL"
                ))
                with op.batch_alter_table(table_name, schema=None, recreate='always') as batch_op:
                    batch_op.alter_column(
                        column_name,
                        existing_type=col_type,
                        nullable=False,
                        server_default=default_value,
                    )
            break


def upgrade():
    """Apply pending approval schema changes."""

    # =========================================================================
    # 1. USERS TABLE - Add approved column
    # =========================================================================
    if table_exists('users'):
        _ensure_not_null('users', 'approved', sa.Boolean(), '1')

    # =========================================================================
    # 2. OIDC_CONFIG TABLE - Add require_approval and approval_notify_channel_ids
    # =========================================================================
    if table_exists('oidc_config'):
        _ensure_not_null('oidc_config', 'require_approval', sa.Boolean(), '0')

        if not column_exists('oidc_config', 'approval_notify_channel_ids'):
            op.add_column('oidc_config', sa.Column(
                'approval_notify_channel_ids', sa.Text(), nullable=True
            ))


def downgrade():
    """Remove pending approval columns."""

    # =========================================================================
    # 1. OIDC_CONFIG TABLE - Remove approval columns
    # =========================================================================
    if table_exists('oidc_config'):
        cols_to_drop = []
        if column_exists('oidc_config', 'approval_notify_channel_ids'):
            cols_to_drop.append('approval_notify_channel_ids')
        if column_exists('oidc_config', 'require_approval'):
            cols_to_drop.append('require_approval')
        if cols_to_drop:
            with op.batch_alter_table('oidc_config', schema=None, recreate='always') as batch_op:
                for col in cols_to_drop:
                    batch_op.drop_column(col)

    # =========================================================================
    # 2. USERS TABLE - Remove approved column
    # =========================================================================
    if table_exists('users'):
        if column_exists('users', 'approved'):
            with op.batch_alter_table('users', schema=None, recreate='always') as batch_op:
                batch_op.drop_column('approved')
