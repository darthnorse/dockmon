"""host tags and description - Phase 3d

Revision ID: 003
Revises: 002
Create Date: 2025-10-07 16:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
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


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    """
    Add host tags and description (Phase 3d):
    1. tags - JSON array of tag strings for host organization
    2. description - Optional text field for host notes
    3. idx_docker_hosts_tags - Index on tags for fast filtering (SQLite JSON1)

    DEFENSIVE: Checks if columns/indexes exist before creating.
    """

    if _table_exists('docker_hosts'):
        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            # Add tags column (JSON array)
            if not _column_exists('docker_hosts', 'tags'):
                batch_op.add_column(
                    sa.Column('tags', sa.Text, nullable=True, comment='JSON array of tags')
                )

            # Add description column
            if not _column_exists('docker_hosts', 'description'):
                batch_op.add_column(
                    sa.Column('description', sa.Text, nullable=True, comment='Optional host description')
                )

        # Create index on tags for filtering
        # Note: SQLite JSON1 extension required for json_each
        # Index format: CREATE INDEX idx_docker_hosts_tags ON docker_hosts(json_each.value)
        # For compatibility, we'll use a simpler index on the tags column itself
        if not _index_exists('docker_hosts', 'idx_docker_hosts_tags'):
            try:
                op.create_index('idx_docker_hosts_tags', 'docker_hosts', ['tags'])
            except Exception as e:
                # If JSON index fails, log but don't fail migration
                print(f"Warning: Could not create JSON index on tags: {e}")
                print("Tag filtering will work but may be slower for large host counts")


def downgrade() -> None:
    """
    Rollback host tags and description

    DEFENSIVE: Checks if columns/indexes exist before dropping.
    """

    if _table_exists('docker_hosts'):
        # Drop index first
        if _index_exists('docker_hosts', 'idx_docker_hosts_tags'):
            op.drop_index('idx_docker_hosts_tags', table_name='docker_hosts')

        with op.batch_alter_table('docker_hosts', schema=None) as batch_op:
            if _column_exists('docker_hosts', 'description'):
                batch_op.drop_column('description')
            if _column_exists('docker_hosts', 'tags'):
                batch_op.drop_column('tags')
