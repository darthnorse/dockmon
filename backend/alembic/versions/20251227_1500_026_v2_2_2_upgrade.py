"""v2.2.2 upgrade - Version correction

Revision ID: 026_v2_2_2
Revises: 025_v2_2_1
Create Date: 2025-12-27

CHANGES IN v2.2.2:
- fix: Correct app_version (was missing in v2.2.1 migration)

NO SCHEMA CHANGES - Version bump only.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '026_v2_2_2'
down_revision = '025_v2_2_1'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    """Update app_version to v2.2.2"""
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.2', id=1)
        )


def downgrade():
    """Downgrade app_version to v2.2.0 (v2.2.1 never set version)"""
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.0', id=1)
        )
