"""Add display_name column to users table

Revision ID: 007_add_display_name
Revises: 006_user_prefs_table
Create Date: 2025-10-15 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '007_add_display_name'
down_revision = '006_user_prefs_table'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    # Add display_name column to users table (defensive)
    if not _column_exists('users', 'display_name'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.add_column(sa.Column('display_name', sa.String(), nullable=True))


def downgrade():
    # Remove display_name column from users table
    if _column_exists('users', 'display_name'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('display_name')
