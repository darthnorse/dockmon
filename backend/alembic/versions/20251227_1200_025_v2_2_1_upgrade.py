"""v2.2.1 upgrade - Bug fixes and improvements

Revision ID: 025_v2_2_1
Revises: 024_v2_2_0
Create Date: 2025-12-27

CHANGES IN v2.2.1:
- fix: Treat one-shot container exit 0 as success during updates (Fixes #110)
  - Containers with restart:no/on-failure that exit with code 0 are now
    considered successful, not failures requiring rollback
  - Aligns with Docker semantics for one-shot tasks
- feat: Apply schedule changes without restart (Issue #103)
  - Changing update_check_time now wakes the periodic job immediately
  - No container restart required to apply new schedule
- fix: Accept legacy Docker Engine ID format with colons (Fixes #112)
  - Supports older Docker installations with XXXX:XXXX:XXXX:... format
- chore: Remove stale Python tests (moved to Go)
  - Test coverage now in shared/update/ and shared/compose/ Go packages

NO SCHEMA CHANGES - Version bump only.
"""
# revision identifiers, used by Alembic.
revision = '025_v2_2_1'
down_revision = '024_v2_2_0'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
