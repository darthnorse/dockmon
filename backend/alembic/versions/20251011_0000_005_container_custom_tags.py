"""Add custom_tags column to container_desired_states

Revision ID: 005_container_custom_tags
Revises: 004_dashboard_view_mode
Create Date: 2025-10-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_container_custom_tags'
down_revision = '004_dashboard_view_mode'
branch_labels = None
depends_on = None


def upgrade():
    # Add custom_tags column to container_desired_states table
    with op.batch_alter_table('container_desired_states', schema=None) as batch_op:
        batch_op.add_column(sa.Column('custom_tags', sa.Text(), nullable=True))


def downgrade():
    # Remove custom_tags column from container_desired_states table
    with op.batch_alter_table('container_desired_states', schema=None) as batch_op:
        batch_op.drop_column('custom_tags')
