"""v2.0.3 upgrade - Change version number to 2.0.3

Revision ID: 004_v2_0_3
Revises: 003_v2_0_2
Create Date: 2025-10-24

CHANGES IN v2.0.3:
- No database schema changes
- Update app_version to '2.0.3'

Note: This is a code-only release with no database schema changes.
The migration exists solely to update the version number for tracking.
"""
# revision identifiers, used by Alembic.
revision = '004_v2_0_3'
down_revision = '003_v2_0_2'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
