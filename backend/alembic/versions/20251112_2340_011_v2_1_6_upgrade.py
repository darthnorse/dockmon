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
# revision identifiers, used by Alembic.
revision = '011_v2_1_6'
down_revision = '010_v2_1_5'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
