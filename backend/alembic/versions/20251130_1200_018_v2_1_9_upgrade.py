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
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '018_v2_1_9'
down_revision = '017_v2_1_9_beta1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade to v2.1.9 (version bump only, no schema changes)"""
    # Update app_version to 2.1.9
    op.execute(
        sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
        .bindparams(version='2.1.9', id=1)
    )


def downgrade() -> None:
    """Downgrade from v2.1.9 to v2.1.9-beta1"""
    # Revert app_version
    op.execute(
        sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
        .bindparams(version='2.1.9-beta1', id=1)
    )
