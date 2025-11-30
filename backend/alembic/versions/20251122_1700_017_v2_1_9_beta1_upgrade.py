"""v2.1.9-beta1 upgrade - Passthrough refactor and deployment improvements

Revision ID: 017_v2_1_9_beta1
Revises: 016_v2_1_8_hotfix_3
Create Date: 2025-11-22

CHANGES IN v2.1.9-beta1:

Update Improvements (Passthrough Refactor):
- API version-aware networking (efficient 1-call creation for API >= 1.44)
- Improved NetworkMode resolution (container:ID → container:name)
- Auto-restart race condition fix (Issue #69)
- Container name preservation during updates

Deployment Improvements:
- Docker Compose v3 deploy.resources support (memory/CPU limits)
- Docker Compose healthcheck support (all timing fields)
- Labels list format support
- PID mode support (pid: host)
- Security options support (security_opt: [apparmor:unconfined])
- Smart network IPAM reconciliation (auto-heal orphaned networks)

Bug Fixes:
- Fixed static IP preservation
- Fixed duplicate mount errors (Issue #68)
- Fixed labels being lost during deployment with list format
- Fixed netdata deployment failures (pid + security_opt missing)

No schema changes - version bump only.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '017_v2_1_9_beta1'
down_revision = '016_v2_1_8_hotfix_3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade to v2.1.9-beta1 (version bump only, no schema changes)"""
    # Update app_version to 2.1.9-beta1
    op.execute(
        sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
        .bindparams(version='2.1.9-beta1', id=1)
    )


def downgrade() -> None:
    """Downgrade from v2.1.9-beta1 to v2.1.8-hotfix.3"""
    # Revert app_version
    op.execute(
        sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
        .bindparams(version='2.1.8-hotfix.3', id=1)
    )
