"""v2.0.1 upgrade - Changelog URL + Alert retry + DockMon update notifications

Revision ID: 002_v2_0_1
Revises: 001_v2_0_0
Create Date: 2025-10-22

This migration adds changelog URL resolution, alert retry tracking, and DockMon update notifications.
All additions are defensive (checks if columns exist before adding).

CHANGES IN v2.0.1:
- container_updates: Add changelog_url, changelog_source, changelog_checked_at
- alerts_v2: Add last_notification_attempt_at, next_retry_at (exponential backoff)
- global_settings: Add latest_available_version, last_dockmon_update_check_at
- user_prefs: Add dismissed_dockmon_update_version
- global_settings: Update app_version to '2.0.1'
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '002_v2_0_1'
down_revision = '001_v2_0_0'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)

    # Check table exists first (belts and braces)
    if table_name not in inspector.get_table_names():
        return False

    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """
    Add changelog columns and alert retry tracking.

    Defensive: Only adds columns if they don't exist.
    Safe to run multiple times (idempotent).
    """

    # ==================== container_updates: Add changelog columns ====================
    if not column_exists('container_updates', 'changelog_url'):
        op.add_column('container_updates',
            sa.Column('changelog_url', sa.Text(), nullable=True))

    if not column_exists('container_updates', 'changelog_source'):
        op.add_column('container_updates',
            sa.Column('changelog_source', sa.Text(), nullable=True))

    if not column_exists('container_updates', 'changelog_checked_at'):
        op.add_column('container_updates',
            sa.Column('changelog_checked_at', sa.DateTime(), nullable=True))

    # ==================== alerts_v2: Add retry tracking columns ====================
    # Exponential backoff for notification retries
    if not column_exists('alerts_v2', 'last_notification_attempt_at'):
        op.add_column('alerts_v2',
            sa.Column('last_notification_attempt_at', sa.DateTime(), nullable=True))

    if not column_exists('alerts_v2', 'next_retry_at'):
        op.add_column('alerts_v2',
            sa.Column('next_retry_at', sa.DateTime(), nullable=True))

    # ==================== DockMon Update Notifications ====================
    # Track DockMon application updates from GitHub (not container updates)
    if not column_exists('global_settings', 'latest_available_version'):
        op.add_column('global_settings',
            sa.Column('latest_available_version', sa.Text(), nullable=True))

    if not column_exists('global_settings', 'last_dockmon_update_check_at'):
        op.add_column('global_settings',
            sa.Column('last_dockmon_update_check_at', sa.DateTime(), nullable=True))

    if not column_exists('user_prefs', 'dismissed_dockmon_update_version'):
        op.add_column('user_prefs',
            sa.Column('dismissed_dockmon_update_version', sa.Text(), nullable=True))

    # ==================== global_settings: Update app_version ====================
    op.execute(
        sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
        .bindparams(version='2.0.1', id=1)
    )


def downgrade() -> None:
    """
    Remove v2.0.1 columns.

    Note: Downgrade is rarely used in production, but provided for completeness.
    """
    # Remove container_updates changelog columns
    op.drop_column('container_updates', 'changelog_checked_at')
    op.drop_column('container_updates', 'changelog_source')
    op.drop_column('container_updates', 'changelog_url')

    # Remove alerts_v2 retry tracking columns
    op.drop_column('alerts_v2', 'next_retry_at')
    op.drop_column('alerts_v2', 'last_notification_attempt_at')

    # Remove DockMon update notification columns
    op.drop_column('user_prefs', 'dismissed_dockmon_update_version')
    op.drop_column('global_settings', 'last_dockmon_update_check_at')
    op.drop_column('global_settings', 'latest_available_version')

    # Revert app_version to 2.0.0
    op.execute(
        sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
        .bindparams(version='2.0.0', id=1)
    )
