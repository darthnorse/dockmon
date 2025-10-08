"""react preferences - dashboard_layout_v2 and sidebar_collapsed

Revision ID: 002
Revises: 001
Create Date: 2025-10-07 10:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _table_exists(table_name: str) -> bool:
    """Check if a table exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """
    Add React (v2) user preferences:
    1. dashboard_layout_v2 - react-grid-layout format (separate from v1 GridStack layout)
    2. sidebar_collapsed - Boolean for sidebar state

    DEFENSIVE: Checks if columns exist before creating.
    """

    if _table_exists('users'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            if not _column_exists('users', 'dashboard_layout_v2'):
                batch_op.add_column(sa.Column('dashboard_layout_v2', sa.Text, nullable=True))
            if not _column_exists('users', 'sidebar_collapsed'):
                batch_op.add_column(sa.Column('sidebar_collapsed', sa.Boolean, nullable=True, server_default='0'))


def downgrade() -> None:
    """
    Rollback React preferences

    DEFENSIVE: Checks if columns exist before dropping.
    """

    if _table_exists('users'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            if _column_exists('users', 'sidebar_collapsed'):
                batch_op.drop_column('sidebar_collapsed')
            if _column_exists('users', 'dashboard_layout_v2'):
                batch_op.drop_column('dashboard_layout_v2')
