"""v2.1.2 upgrade - Update progress UI and constraint fixes

Revision ID: 007_v2_1_2
Revises: 006_v2_1_1
Create Date: 2025-11-08

CHANGES IN v2.1.2:
- No database schema changes
- Update app_version to '2.1.2'

BUG FIXES:
- Fix layer-by-layer image pull progress not displaying in UI during container updates
  - Root cause: ImagePullProgress tracker initialized without connection_manager
  - Solution: Re-initialize tracker when monitor is added to UpdateExecutor singleton
  - Impact: Users now see real-time layer progress with download speeds during updates

- Fix UNIQUE constraint error during container updates (Issue #30)
  - Root cause: Race condition or stale records causing duplicate container_id
  - Solution: Delete conflicting ContainerUpdate records before updating container_id
  - Impact: Prevents sqlite3.IntegrityError during manual container updates

Note: This is a bug fix release with no database schema changes.
The migration exists solely to update the version number for tracking.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '007_v2_1_2'
down_revision = '006_v2_1_1'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Update to v2.1.2"""

    # Only change: Update app_version
    # No schema changes in this release - bug fixes only
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.2', id=1)
        )


def downgrade() -> None:
    """Downgrade from v2.1.2"""

    # Revert app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.1', id=1)
        )
