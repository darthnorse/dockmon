"""Add display_name column to users table

Revision ID: 007_add_display_name
Revises: 006_user_prefs_table
Create Date: 2025-10-15 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007_add_display_name'
down_revision = '006_user_prefs_table'
branch_labels = None
depends_on = None


def upgrade():
    # Add display_name column to users table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('display_name', sa.String(), nullable=True))


def downgrade():
    # Remove display_name column from users table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('display_name')
