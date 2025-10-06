"""v2 schema additions - user preferences and RBAC foundation

Revision ID: 001
Revises:
Create Date: 2025-10-06 16:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add v2.0 schema changes:
    1. User preferences table (replaces localStorage)
    2. Role and display_name columns for future RBAC (v2.1)
    3. Event categorization columns
    """

    # Create user_prefs table (database-backed preferences)
    # SECURITY: user_id has CASCADE delete to prevent orphaned data
    op.create_table(
        'user_prefs',
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('theme', sa.String, nullable=True, server_default='dark'),
        sa.Column('refresh_profile', sa.String, nullable=True, server_default='normal'),
        sa.Column('defaults_json', sa.Text, nullable=True)  # JSON: {groupBy, compactView, collapsedGroups, filterDefaults}
    )

    # Extend users table for future RBAC (v2.1)
    # NOTE: These columns are not used in v2.0, but prevent migration in v2.1
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('role', sa.String, nullable=True, server_default='owner'))
        batch_op.add_column(sa.Column('display_name', sa.String, nullable=True))

    # Extend event_logs for better filtering
    with op.batch_alter_table('event_logs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String, nullable=True, server_default='docker'))
        batch_op.add_column(sa.Column('category', sa.String, nullable=True))

    # Create index on event_logs for faster queries
    op.create_index('idx_event_logs_category', 'event_logs', ['category'])
    op.create_index('idx_event_logs_source', 'event_logs', ['source'])


def downgrade() -> None:
    """
    Rollback v2.0 schema changes
    """

    # Drop indexes
    op.drop_index('idx_event_logs_source', table_name='event_logs')
    op.drop_index('idx_event_logs_category', table_name='event_logs')

    # Remove event_logs columns
    with op.batch_alter_table('event_logs', schema=None) as batch_op:
        batch_op.drop_column('category')
        batch_op.drop_column('source')

    # Remove users columns
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('display_name')
        batch_op.drop_column('role')

    # Drop user_prefs table (CASCADE will handle cleanup)
    op.drop_table('user_prefs')
