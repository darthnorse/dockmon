"""Add version tracking to GlobalSettings

Revision ID: 008
Revises: 007
Create Date: 2025-10-17 00:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '008'
down_revision = '007_add_display_name'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Add version tracking fields to global_settings"""
    # Add app_version column
    if not _column_exists('global_settings', 'app_version'):
        op.add_column('global_settings', sa.Column('app_version', sa.String(), nullable=True))
        # Set default value for existing row
        op.execute("UPDATE global_settings SET app_version = '2.0.0' WHERE id = 1")

    # Add upgrade_notice_dismissed column
    if not _column_exists('global_settings', 'upgrade_notice_dismissed'):
        op.add_column('global_settings', sa.Column('upgrade_notice_dismissed', sa.Boolean(), nullable=True))
        # Set default to False for existing row (show upgrade notice on first login after upgrade)
        op.execute("UPDATE global_settings SET upgrade_notice_dismissed = 0 WHERE id = 1")

    # Add last_viewed_release_notes column
    if not _column_exists('global_settings', 'last_viewed_release_notes'):
        op.add_column('global_settings', sa.Column('last_viewed_release_notes', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove version tracking fields from global_settings"""
    if _column_exists('global_settings', 'last_viewed_release_notes'):
        op.drop_column('global_settings', 'last_viewed_release_notes')

    if _column_exists('global_settings', 'upgrade_notice_dismissed'):
        op.drop_column('global_settings', 'upgrade_notice_dismissed')

    if _column_exists('global_settings', 'app_version'):
        op.drop_column('global_settings', 'app_version')
