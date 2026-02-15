"""v2.1.5 upgrade - Add OCI version label support

Revision ID: 010_v2_1_5
Revises: 009_v2_1_4
Create Date: 2025-11-09

CHANGES IN v2.1.5:
- Add current_version and latest_version columns to container_updates table
- Update app_version to '2.1.5'

NEW FEATURES:
- Display semantic versions (e.g., "v1.0.2" → "v1.1.0") in Updates tab and update alerts
  - Extracted from org.opencontainers.image.version OCI label
  - Falls back to digest display if version labels not available
  - Improves readability and understanding of what updates entail

Note: This is a feature release with database schema changes.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '010_v2_1_5'
down_revision = '009_v2_1_4'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Update to v2.1.5"""

    # Add version columns to container_updates table
    if table_exists('container_updates'):
        # Check if columns already exist (defensive)
        bind = op.get_bind()
        inspector = inspect(bind)
        columns = [col['name'] for col in inspector.get_columns('container_updates')]

        if 'current_version' not in columns:
            op.add_column('container_updates', sa.Column('current_version', sa.Text(), nullable=True))

        if 'latest_version' not in columns:
            op.add_column('container_updates', sa.Column('latest_version', sa.Text(), nullable=True))



def downgrade() -> None:
    """Downgrade from v2.1.5"""

    # Remove version columns
    if table_exists('container_updates'):
        bind = op.get_bind()
        inspector = inspect(bind)
        columns = [col['name'] for col in inspector.get_columns('container_updates')]

        if 'latest_version' in columns:
            op.drop_column('container_updates', 'latest_version')

        if 'current_version' in columns:
            op.drop_column('container_updates', 'current_version')

