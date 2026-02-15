"""v2.1.8-hotfix.2 upgrade - Add image digest cache table

Revision ID: 015_v2_1_8_hotfix_2
Revises: 014_v2_1_8_hotfix_1
Create Date: 2025-11-18

CHANGES IN v2.1.8-hotfix.2:
- Create image_digest_cache table for registry rate limit mitigation
- Caches registry digest lookups by image:tag:platform
- Reduces API calls to Docker Hub and other registries

Issue #62: Registry rate limit handling
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '015_v2_1_8_hotfix_2'
down_revision = '014_v2_1_8_hotfix_1'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Create image_digest_cache table"""

    # Create image_digest_cache table
    if not table_exists('image_digest_cache'):
        op.create_table(
            'image_digest_cache',
            sa.Column('cache_key', sa.Text(), primary_key=True),
            sa.Column('latest_digest', sa.Text(), nullable=False),
            sa.Column('registry_url', sa.Text(), nullable=True),
            sa.Column('manifest_json', sa.Text(), nullable=True),
            sa.Column('ttl_seconds', sa.Integer(), nullable=False, server_default='21600'),
            sa.Column('checked_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )



def downgrade() -> None:
    """Remove image_digest_cache table"""

    # Drop table
    if table_exists('image_digest_cache'):
        op.drop_table('image_digest_cache')
