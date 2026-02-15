"""v2.2.9 upgrade - Bug fixes and improvements

Revision ID: 033_v2_2_9
Revises: 032_v2_2_8
Create Date: 2026-02-06

CHANGES IN v2.2.9:
- fix: Multiple notification channels of same type not selectable (#167)
- fix: Backend validation and dependent alerts for multi-channel support (#167)
- fix: Notification channels remaining in alert rules after deletion (#166)
- fix: Alert not clearing on container stop/destroy for local hosts (#160)
- fix: Certificate key permissions (PR #169, thanks to @SmollClover)
- fix: .env file loading for compose stack deployments
- fix: Blocking Docker SDK calls in async handlers
- feat: Log agent authentication failures in DockMon Core
- chore: Add version="auto" to Docker SDK calls
- chore: Agent version bump to 1.0.4

SCHEMA CHANGES:
- None (version bump only)
"""
# revision identifiers, used by Alembic.
revision = '033_v2_2_9'
down_revision = '032_v2_2_8'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
