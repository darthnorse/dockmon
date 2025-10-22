"""add changelog URL columns to container_updates

Revision ID: 002_add_changelog
Revises: 001_v1_to_v2
Create Date: 2025-10-22

This migration adds changelog URL resolution columns to container_updates table.
Defensive: checks if columns exist before adding (handles v1→v2.0.1 upgrades where
Base.metadata.create_all() already created the table with these columns).

CHANGES:
- container_updates: Add changelog_url (TEXT, nullable)
- container_updates: Add changelog_source (TEXT, nullable)
- container_updates: Add changelog_checked_at (DATETIME, nullable)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '002_add_changelog'
down_revision = '001_v1_to_v2'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """
    Add changelog columns to container_updates table.

    Defensive: Only adds columns if they don't exist.
    Handles both v2.0.0→v2.0.1 (columns don't exist) and
    v1→v2.0.1 (columns already exist from Base.metadata.create_all()).
    """

    # Add changelog_url column
    if not column_exists('container_updates', 'changelog_url'):
        op.add_column('container_updates',
            sa.Column('changelog_url', sa.Text(), nullable=True))

    # Add changelog_source column
    if not column_exists('container_updates', 'changelog_source'):
        op.add_column('container_updates',
            sa.Column('changelog_source', sa.Text(), nullable=True))

    # Add changelog_checked_at column
    if not column_exists('container_updates', 'changelog_checked_at'):
        op.add_column('container_updates',
            sa.Column('changelog_checked_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """
    Remove changelog columns from container_updates table.

    Note: Downgrade is rarely used in production, but provided for completeness.
    """
    op.drop_column('container_updates', 'changelog_checked_at')
    op.drop_column('container_updates', 'changelog_source')
    op.drop_column('container_updates', 'changelog_url')
