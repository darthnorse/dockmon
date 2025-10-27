"""v2.1.1 - Add image pruning settings

Revision ID: 006_v2_1_1
Revises: 005_v2_1_0
Create Date: 2025-10-27

CHANGES IN v2.1.1:
- Add prune_images_enabled to global_settings (default: True)
- Add image_retention_count to global_settings (default: 2, keeps last N versions)
- Add image_prune_grace_hours to global_settings (default: 48, grace period in hours)

NEW FEATURES:
- Automatic image pruning to free disk space
- Configurable retention policies (keep last N versions, grace period)
- Manual prune trigger via API
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '006_v2_1_1'
down_revision = '005_v2_1_0'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Add image pruning settings to global_settings"""

    # Add prune_images_enabled column (default: True)
    if not column_exists('global_settings', 'prune_images_enabled'):
        op.add_column('global_settings',
            sa.Column('prune_images_enabled', sa.Boolean(), server_default='1', nullable=False)
        )

    # Add image_retention_count column (default: 2)
    if not column_exists('global_settings', 'image_retention_count'):
        op.add_column('global_settings',
            sa.Column('image_retention_count', sa.Integer(), server_default='2', nullable=False)
        )

    # Add image_prune_grace_hours column (default: 48)
    if not column_exists('global_settings', 'image_prune_grace_hours'):
        op.add_column('global_settings',
            sa.Column('image_prune_grace_hours', sa.Integer(), server_default='48', nullable=False)
        )


def downgrade() -> None:
    """Remove image pruning settings from global_settings"""

    if column_exists('global_settings', 'image_prune_grace_hours'):
        op.drop_column('global_settings', 'image_prune_grace_hours')

    if column_exists('global_settings', 'image_retention_count'):
        op.drop_column('global_settings', 'image_retention_count')

    if column_exists('global_settings', 'prune_images_enabled'):
        op.drop_column('global_settings', 'prune_images_enabled')
