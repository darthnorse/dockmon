"""v2.1.8-hotfix.3 upgrade - Add is_podman column to docker_hosts

Revision ID: 016_v2_1_8_hotfix_3
Revises: 015_v2_1_8_hotfix_2
Create Date: 2025-11-19

CHANGES IN v2.1.8-hotfix.3:
- Add is_podman column to docker_hosts table
- Enables filtering of incompatible parameters during container updates
- NanoCPUs and MemorySwappiness are not supported by Podman

Issue #20: Container update failures on Podman hosts
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '016_v2_1_8_hotfix_3'
down_revision = '015_v2_1_8_hotfix_2'
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
    """Add is_podman column to docker_hosts"""

    # Add is_podman column to docker_hosts
    if not column_exists('docker_hosts', 'is_podman'):
        op.add_column('docker_hosts',
            sa.Column('is_podman', sa.Boolean(), server_default='0', nullable=False))



def downgrade() -> None:
    """Remove is_podman column from docker_hosts"""

    # Drop column
    if column_exists('docker_hosts', 'is_podman'):
        op.drop_column('docker_hosts', 'is_podman')
