"""Pending Approval for OIDC Users

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


def upgrade():
    """Apply pending approval schema changes."""

    bind = op.get_bind()

    # =========================================================================
    # 1. USERS TABLE - Add approved column
    # =========================================================================
    if table_exists('users'):
        if not column_exists('users', 'approved'):
            # Add column first (SQLite ADD COLUMN ignores NOT NULL)
            op.add_column('users', sa.Column(
                'approved', sa.Boolean(), nullable=True, server_default='1'
            ))

        # Set any NULL values to 1 (approved) before enforcing NOT NULL
        if column_exists('users', 'approved'):
            bind.execute(sa.text(
                "UPDATE users SET approved = 1 WHERE approved IS NULL"
            ))

            # Rebuild table to enforce NOT NULL constraint
            with op.batch_alter_table('users', schema=None, recreate='always') as batch_op:
                batch_op.alter_column(
                    'approved',
                    existing_type=sa.Boolean(),
                    nullable=False,
                    server_default='1',
                )

    # =========================================================================
    # 2. OIDC_CONFIG TABLE - Add require_approval and approval_notify_channel_ids
    # =========================================================================
    if table_exists('oidc_config'):
        if not column_exists('oidc_config', 'require_approval'):
            # Add column first (SQLite ADD COLUMN ignores NOT NULL)
            op.add_column('oidc_config', sa.Column(
                'require_approval', sa.Boolean(), nullable=True, server_default='0'
            ))

        if not column_exists('oidc_config', 'approval_notify_channel_ids'):
            op.add_column('oidc_config', sa.Column(
                'approval_notify_channel_ids', sa.Text(), nullable=True
            ))

        # Set any NULL values to 0 (not required) before enforcing NOT NULL
        if column_exists('oidc_config', 'require_approval'):
            bind.execute(sa.text(
                "UPDATE oidc_config SET require_approval = 0 WHERE require_approval IS NULL"
            ))

            # Rebuild table to enforce NOT NULL constraint on require_approval
            with op.batch_alter_table('oidc_config', schema=None, recreate='always') as batch_op:
                batch_op.alter_column(
                    'require_approval',
                    existing_type=sa.Boolean(),
                    nullable=False,
                    server_default='0',
                )

    # =========================================================================
    # 3. VERIFICATION - Confirm NOT NULL constraints were applied
    # =========================================================================
    if table_exists('users') and column_exists('users', 'approved'):
        inspector = get_inspector()
        for col in inspector.get_columns('users'):
            if col['name'] == 'approved':
                if col.get('nullable', True):
                    # NOT NULL was not applied (SQLite batch mode failure) - retry
                    bind.execute(sa.text(
                        "UPDATE users SET approved = 1 WHERE approved IS NULL"
                    ))
                    with op.batch_alter_table('users', schema=None, recreate='always') as batch_op:
                        batch_op.alter_column(
                            'approved',
                            existing_type=sa.Boolean(),
                            nullable=False,
                            server_default='1',
                        )
                break

    if table_exists('oidc_config') and column_exists('oidc_config', 'require_approval'):
        inspector = get_inspector()
        for col in inspector.get_columns('oidc_config'):
            if col['name'] == 'require_approval':
                if col.get('nullable', True):
                    # NOT NULL was not applied - retry
                    bind.execute(sa.text(
                        "UPDATE oidc_config SET require_approval = 0 WHERE require_approval IS NULL"
                    ))
                    with op.batch_alter_table('oidc_config', schema=None, recreate='always') as batch_op:
                        batch_op.alter_column(
                            'require_approval',
                            existing_type=sa.Boolean(),
                            nullable=False,
                            server_default='0',
                        )
                break


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
