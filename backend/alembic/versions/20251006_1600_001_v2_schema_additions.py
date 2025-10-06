"""v2 schema additions - user preferences and RBAC foundation

Revision ID: 001
Revises:
Create Date: 2025-10-06 16:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
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


def _index_exists(index_name: str) -> bool:
    """Check if an index exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    # Check all tables for this index
    for table_name in inspector.get_table_names():
        indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
        if index_name in indexes:
            return True
    return False


def upgrade() -> None:
    """
    Add v2.0 schema changes:
    1. User preferences table (replaces localStorage)
    2. Role and display_name columns for future RBAC (v2.1)
    3. Event categorization columns (if not exist)

    DEFENSIVE: Uses try-except to handle existing tables/columns gracefully.
    """

    # Create user_prefs table (database-backed preferences)
    # SECURITY: user_id has CASCADE delete to prevent orphaned data
    try:
        op.create_table(
            'user_prefs',
            sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('theme', sa.String, nullable=True, server_default='dark'),
            sa.Column('refresh_profile', sa.String, nullable=True, server_default='normal'),
            sa.Column('defaults_json', sa.Text, nullable=True)  # JSON: {groupBy, compactView, collapsedGroups, filterDefaults}
        )
    except Exception:
        pass  # Table already exists

    # Extend users table for future RBAC (v2.1)
    # NOTE: These columns are not used in v2.0, but prevent migration in v2.1
    try:
        with op.batch_alter_table('users', schema=None) as batch_op:
            try:
                batch_op.add_column(sa.Column('role', sa.String, nullable=True, server_default='owner'))
            except Exception:
                pass  # Column already exists
            try:
                batch_op.add_column(sa.Column('display_name', sa.String, nullable=True))
            except Exception:
                pass  # Column already exists
    except Exception:
        pass  # Table doesn't exist or other error

    # Extend event_logs for better filtering
    # NOTE: v1.1.2 already has 'category' column, so only add 'source'
    try:
        with op.batch_alter_table('event_logs', schema=None) as batch_op:
            try:
                batch_op.add_column(sa.Column('source', sa.String, nullable=True, server_default='docker'))
            except Exception:
                pass  # Column already exists
    except Exception:
        pass  # Table doesn't exist or other error

    # Create indexes on event_logs for faster queries
    try:
        op.create_index('idx_event_logs_category', 'event_logs', ['category'])
    except Exception:
        pass  # Index already exists
    try:
        op.create_index('idx_event_logs_source', 'event_logs', ['source'])
    except Exception:
        pass  # Index already exists


def downgrade() -> None:
    """
    Rollback v2.0 schema changes

    DEFENSIVE: Checks if columns/tables/indexes exist before dropping.
    """

    # Drop indexes (only if they exist)
    if _index_exists('idx_event_logs_source'):
        op.drop_index('idx_event_logs_source', table_name='event_logs')
    if _index_exists('idx_event_logs_category'):
        op.drop_index('idx_event_logs_category', table_name='event_logs')

    # Remove event_logs columns (only if they exist)
    if _table_exists('event_logs'):
        with op.batch_alter_table('event_logs', schema=None) as batch_op:
            # Don't drop 'category' - it existed in v1.1.2
            if _column_exists('event_logs', 'source'):
                batch_op.drop_column('source')

    # Remove users columns (only if they exist)
    if _table_exists('users'):
        with op.batch_alter_table('users', schema=None) as batch_op:
            if _column_exists('users', 'display_name'):
                batch_op.drop_column('display_name')
            if _column_exists('users', 'role'):
                batch_op.drop_column('role')

    # Drop user_prefs table (only if it exists)
    if _table_exists('user_prefs'):
        op.drop_table('user_prefs')
