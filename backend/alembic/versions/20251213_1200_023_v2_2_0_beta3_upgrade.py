"""v2.2.0-beta3 upgrade - Multi-use registration tokens

Revision ID: 023_v2_2_0_beta3
Revises: 022_v2_2_0_beta2
Create Date: 2025-12-13

CHANGES IN v2.2.0-beta3:
- feat: Allow registration tokens to be used by multiple agents
  - Added max_uses column (default 1 for single use, NULL for unlimited)
  - Added use_count column to track number of registrations
  - Removed single-use 'used' boolean column
  - UI checkbox: "Allow multiple agents to use this token"
- fix: Security dependency updates
  - containerd/v2: v2.1.4 → v2.1.5 (CVE-2024-25621, CVE-2025-64329)
  - golang.org/x/crypto: v0.38.0 → v0.43.0 (CVE-2025-47913, CVE-2025-58181, CVE-2025-47914)
- feat: mTLS setup script detects and offers to fix insecure Docker exposure
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '023_v2_2_0_beta3'
down_revision = '022_v2_2_0_beta2'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists in table"""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Upgrade to v2.2.0-beta3"""

    # Update registration_tokens table for multi-use support
    if table_exists('registration_tokens'):
        # Add max_uses column (1 = single use, NULL = unlimited)
        if not column_exists('registration_tokens', 'max_uses'):
            op.add_column('registration_tokens',
                sa.Column('max_uses', sa.Integer, nullable=True, server_default='1')
            )

        # Add use_count column
        if not column_exists('registration_tokens', 'use_count'):
            op.add_column('registration_tokens',
                sa.Column('use_count', sa.Integer, nullable=False, server_default='0')
            )

            # Migrate existing data: if used=True, set use_count=1
            op.execute(
                sa.text("UPDATE registration_tokens SET use_count = 1 WHERE used = 1")
            )

        # Rename used_at to last_used_at for clarity
        if column_exists('registration_tokens', 'used_at') and not column_exists('registration_tokens', 'last_used_at'):
            op.alter_column('registration_tokens', 'used_at', new_column_name='last_used_at')

        # Drop the old 'used' boolean column (no longer needed)
        if column_exists('registration_tokens', 'used'):
            op.drop_column('registration_tokens', 'used')



def downgrade() -> None:
    """Downgrade to v2.2.0-beta2"""

    if table_exists('registration_tokens'):
        # Re-add the 'used' column
        if not column_exists('registration_tokens', 'used'):
            op.add_column('registration_tokens',
                sa.Column('used', sa.Boolean, nullable=False, server_default='0')
            )

            # Migrate data back: if use_count > 0, set used=True
            op.execute(
                sa.text("UPDATE registration_tokens SET used = 1 WHERE use_count > 0")
            )

        # Rename last_used_at back to used_at
        if column_exists('registration_tokens', 'last_used_at') and not column_exists('registration_tokens', 'used_at'):
            op.alter_column('registration_tokens', 'last_used_at', new_column_name='used_at')

        # Drop new columns
        if column_exists('registration_tokens', 'use_count'):
            op.drop_column('registration_tokens', 'use_count')

        if column_exists('registration_tokens', 'max_uses'):
            op.drop_column('registration_tokens', 'max_uses')

