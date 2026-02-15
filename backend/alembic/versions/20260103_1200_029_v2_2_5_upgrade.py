"""v2.2.5 upgrade - Import Stack and preferences fixes

Revision ID: 029_v2_2_5
Revises: 028_v2_2_4
Create Date: 2026-01-03

CHANGES IN v2.2.5:
- feat: Add Select All and batch import for stack discovery (Issue #119)
- feat: Resolve stack project names from container labels during scan
  - Handles Portainer-style numeric directories correctly
- fix: Validate layout fields when loading preferences (Issue #124)
  - Prevents crash when old preferences have invalid data types
- fix: Include changelog_url in UPDATE_COMPLETED events (Issue #118)

NO SCHEMA CHANGES - Frontend and backend logic fixes only.
"""
# revision identifiers, used by Alembic.
revision = '029_v2_2_5'
down_revision = '028_v2_2_4'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
