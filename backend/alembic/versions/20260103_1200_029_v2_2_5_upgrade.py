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
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '029_v2_2_5'
down_revision = '028_v2_2_4'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    """Update app_version to v2.2.5"""
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.5', id=1)
        )


def downgrade():
    """Downgrade app_version to v2.2.4"""
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.4', id=1)
        )
