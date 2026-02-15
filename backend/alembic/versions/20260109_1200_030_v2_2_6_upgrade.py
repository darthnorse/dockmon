"""v2.2.6 upgrade - Alert cooldown and orphan cleanup fixes

Revision ID: 030_v2_2_6
Revises: 029_v2_2_5
Create Date: 2026-01-09

CHANGES IN v2.2.6:
- fix: Alert notification cooldown now uses notified_at instead of last_seen (Issue #137)
  - Cooldown was checking time since last evaluation (~10s) instead of last notification
  - This caused notification spam regardless of cooldown_seconds setting
- fix: Delete associated alerts when rule is deleted (Issue #137)
  - Prevents orphaned alerts (rule_id=NULL) from persisting in the UI
  - Orphaned alerts showed stale threshold/current_value causing confusion
- fix: Clean up existing orphaned alerts from database
  - One-time migration to remove alerts with rule_id=NULL
  - These alerts were disconnected from rules and showing stale data
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '030_v2_2_6'
down_revision = '029_v2_2_5'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    """Clean up orphaned alerts"""

    # Clean up orphaned alerts (alerts with rule_id=NULL)
    # These were created when rules were deleted before this fix
    # They cause confusion by showing stale threshold/current_value data
    if table_exists('alerts_v2'):
        result = op.get_bind().execute(
            sa.text("DELETE FROM alerts_v2 WHERE rule_id IS NULL")
        )
        # Note: rowcount may not be available on all backends, but SQLite supports it
        print(f"Cleaned up orphaned alerts (rule_id IS NULL)")



def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
