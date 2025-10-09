"""Add dashboard view_mode preference

Revision ID: 004_dashboard_view_mode
Revises: 003_host_tags
Create Date: 2025-10-08 21:00:00

Phase 4: Dashboard View Modes
Adds view_mode column to users table for dashboard view preference (compact/standard/expanded)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004_dashboard_view_mode'
down_revision = '003_host_tags'
branch_labels = None
depends_on = None


def upgrade():
    """Add view_mode column to users table"""
    # Check if column exists before adding (defensive migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('users')]

    if 'view_mode' not in columns:
        op.add_column('users', sa.Column('view_mode', sa.String(), nullable=True))
        print("✓ Added view_mode column to users table")
    else:
        print("✓ view_mode column already exists, skipping")


def downgrade():
    """Remove view_mode column from users table"""
    op.drop_column('users', 'view_mode')
    print("✓ Removed view_mode column from users table")
