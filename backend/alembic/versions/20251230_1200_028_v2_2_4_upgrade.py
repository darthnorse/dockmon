"""v2.2.4 upgrade - Updates filter cache fix

Revision ID: 028_v2_2_4
Revises: 027_v2_2_3
Create Date: 2025-12-30

CHANGES IN v2.2.4:
- fix: "Updates Available" filter now works immediately after checking for updates
  - Fixed cache invalidation in Settings page "Check All Now" button
  - Fixed cache invalidation in batch check-updates action
  - Fixes GitHub Issue #115

NO SCHEMA CHANGES - Frontend cache invalidation fix only.
"""
# revision identifiers, used by Alembic.
revision = '028_v2_2_4'
down_revision = '027_v2_2_3'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
