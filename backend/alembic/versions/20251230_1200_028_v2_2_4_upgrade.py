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
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '028_v2_2_4'
down_revision = '027_v2_2_3'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    """Update app_version to v2.2.4"""
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.4', id=1)
        )


def downgrade():
    """Downgrade app_version to v2.2.3"""
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.3', id=1)
        )
