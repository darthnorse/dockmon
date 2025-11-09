"""v2.1.3 upgrade - Digest-based container pull fix

Revision ID: 008_v2_1_3
Revises: 007_v2_1_2
Create Date: 2025-11-09

CHANGES IN v2.1.3:
- No database schema changes
- Update app_version to '2.1.3'

BUG FIXES:
- Fix manual update checks failing with 503 error for digest-based containers
  - Root cause: Containers pulled by digest had image name extracted as "sha256:abc123"
  - Solution: Use Config.Image which preserves full repository name
  - Impact: Manual update checks now work for all containers (especially those updated via DockMon)

Note: This is a bug fix release with no database schema changes.
The migration exists solely to update the version number for tracking.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '008_v2_1_3'
down_revision = '007_v2_1_2'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Update to v2.1.3"""

    # Only change: Update app_version
    # No schema changes in this release - bug fix only
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.3', id=1)
        )


def downgrade() -> None:
    """Downgrade from v2.1.3"""

    # Revert app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.2', id=1)
        )
