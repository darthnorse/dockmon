"""v2.1.4 upgrade - Alert engine fix for container stops

Revision ID: 009_v2_1_4
Revises: 008_v2_1_3
Create Date: 2025-11-09

CHANGES IN v2.1.4:
- No database schema changes
- Update app_version to '2.1.4'

BUG FIXES:
- Fix container stopped alerts not firing for clean exits (exit code 0)
  - Root cause: v2.1.1 changed stop handling to use new_state="stopped" for exit code 0,
    but alert engine only checked for ["exited", "dead"]
  - Solution: Add "stopped" to the list of states that trigger container_stopped alerts
  - Impact: Container stopped alerts now fire for all stops (clean and crashes)

Note: This is a bug fix release with no database schema changes.
The migration exists solely to update the version number for tracking.
"""
# revision identifiers, used by Alembic.
revision = '009_v2_1_4'
down_revision = '008_v2_1_3'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
