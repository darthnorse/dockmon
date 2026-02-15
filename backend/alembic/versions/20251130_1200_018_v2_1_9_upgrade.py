"""v2.1.9 release - ntfy notification support

Revision ID: 018_v2_1_9
Revises: 017_v2_1_9_beta1
Create Date: 2025-11-30

CHANGES IN v2.1.9:

New Features:
- Native ntfy notification channel support (Issue #80)
  - Self-hosted or ntfy.sh public instance
  - Access token and basic auth support
  - Priority mapping based on event severity
  - Tags for critical events

All changes from v2.1.9-beta1:
- Update Improvements (Passthrough Refactor)
- Deployment Improvements (resources, healthcheck, labels, PID, security_opt)
- Bug Fixes (static IP, duplicate mounts, labels list format)

No schema changes - version bump only.
"""
# revision identifiers, used by Alembic.
revision = '018_v2_1_9'
down_revision = '017_v2_1_9_beta1'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
