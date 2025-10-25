"""v2.0.3 upgrade - Change version number to 2.0.3

Revision ID: 004_v2_0_3
Revises: 003_v2_0_2
Create Date: 2025-10-24

CHANGES IN v2.0.3:
- No database schema changes
- Update app_version to '2.0.3'

Note: This is a code-only release with no database schema changes.
The migration exists solely to update the version number for tracking.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '004_v2_0_3'
down_revision = '003_v2_0_2'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Update to v2.0.3"""

    # Only change: Update app_version
    # No schema changes in this release - security and correctness fixes only
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.0.3', id=1)
        )


def downgrade() -> None:
    """Downgrade from v2.0.3"""

    # Revert app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.0.2', id=1)
        )
