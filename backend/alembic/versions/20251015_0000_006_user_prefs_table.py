"""Add user_prefs table and prefs/simplified_workflow columns to users

Revision ID: 006_user_prefs_table
Revises: 005_container_custom_tags
Create Date: 2025-10-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006_user_prefs_table'
down_revision = '005_container_custom_tags'
branch_labels = None
depends_on = None


def upgrade():
    # Create user_prefs table
    op.create_table(
        'user_prefs',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('theme', sa.String(), nullable=True, server_default='dark'),
        sa.Column('defaults_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('user_id')
    )

    # Add prefs and simplified_workflow columns to users table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('prefs', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('simplified_workflow', sa.Boolean(), nullable=True, server_default='0'))


def downgrade():
    # Remove prefs and simplified_workflow columns from users table
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('simplified_workflow')
        batch_op.drop_column('prefs')

    # Drop user_prefs table
    op.drop_table('user_prefs')
