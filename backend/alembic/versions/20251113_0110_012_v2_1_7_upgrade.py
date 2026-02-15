"""v2.1.7 upgrade - Bug fix release

Revision ID: 012_v2_1_7
Revises: 011_v2_1_6
Create Date: 2025-11-13

CHANGES IN v2.1.7:
- Fix host tags being cleared on update (GitHub Issue #39)
- Fix OS/version info disappearing after host update
- Update app_version to '2.1.7'

BUG FIXES:
- Host tags were being cleared when updating host configuration
  - Root cause: Frontend sent empty tags array, backend overwrote with empty array
  - Fix: Preserve existing tags from normalized tag_assignments table if not provided
  - Impact: Host tags now persist through host configuration updates

- Host OS/version info disappeared for up to 24 hours after host update
  - Root cause: update_host() created new in-memory object without OS info,
    which was only refreshed by daily maintenance job (24h interval)
  - Fix: Immediately fetch fresh system info after establishing Docker connection
  - Impact: OS/version info displays immediately and detects Docker/OS updates

Note: This is a bug fix release with no database schema changes.
"""
# revision identifiers, used by Alembic.
revision = '012_v2_1_7'
down_revision = '011_v2_1_6'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
