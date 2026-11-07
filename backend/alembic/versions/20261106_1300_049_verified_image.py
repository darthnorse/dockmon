"""v2.5.x upgrade - container_updates.verified_image

Revision ID: 049_verified_image
Revises: 048_registry_leak_cleanup
Create Date: 2026-11-06

CHANGES:
- container_updates: verified_image (JSON, nullable), the image ID last seen matching its
  reference in the registry. No backfill: it can only be established by a check.
"""
from alembic import op
import sqlalchemy as sa

revision = '049_verified_image'
down_revision = '048_registry_leak_cleanup'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {c['name'] for c in inspector.get_columns(table_name)}


def upgrade():
    if not column_exists('container_updates', 'verified_image'):
        op.add_column('container_updates', sa.Column('verified_image', sa.Text, nullable=True))


def downgrade():
    if column_exists('container_updates', 'verified_image'):
        op.drop_column('container_updates', 'verified_image')
