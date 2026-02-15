"""v2.2.2 upgrade - Version correction

Revision ID: 026_v2_2_2
Revises: 025_v2_2_1
Create Date: 2025-12-27

CHANGES IN v2.2.2:
- fix: Correct app_version (was missing in v2.2.1 migration)

NO SCHEMA CHANGES - Version bump only.
"""
# revision identifiers, used by Alembic.
revision = '026_v2_2_2'
down_revision = '025_v2_2_1'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
