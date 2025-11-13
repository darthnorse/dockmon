"""v2.1.6 upgrade - Bug fix release

Revision ID: 011_v2_1_6
Revises: 010_v2_1_5
Create Date: 2025-11-12

CHANGES IN v2.1.6:
- Fix host offline alert auto-resolve bug
- Update app_version to '2.1.6'

BUG FIXES:
- Host offline alerts were being incorrectly auto-resolved even when host remained offline
  - Root cause: Alert verification checked if Docker client object exists, but client
    objects persist even when host is offline
  - Fix: Changed to check monitor.hosts[host_id].status == 'online' instead
  - Impact: Host offline alerts now correctly trigger notifications when host stays offline
    past the clear_duration grace period

Note: This is a bug fix release with no database schema changes.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '011_v2_1_6'
down_revision = '010_v2_1_5'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Update to v2.1.6"""

    # No schema changes in this version - just update version number
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.6', id=1)
        )


def downgrade() -> None:
    """Downgrade from v2.1.6"""

    # Revert app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.5', id=1)
        )
