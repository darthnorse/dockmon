"""v2.3.0 Multi-User Support Phase 6 - Audit Log UI

Revision ID: 035_v2_3_0_phase6
Revises: 034_v2_3_0_phase5
Create Date: 2026-01-23

CHANGES IN v2.3.0 (Phase 6):
- Add audit_log_retention_days to global_settings
- Default 90 days retention for audit log entries

SCHEMA CHANGES:
1. Modified tables:
   - global_settings: Add audit_log_retention_days column
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '035_v2_3_0_phase6'
down_revision = '034_v2_3_0_phase5'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    """Apply Phase 6 audit log UI schema changes"""

    # =========================================================================
    # 1. ADD AUDIT_LOG_RETENTION_DAYS TO GLOBAL_SETTINGS
    # =========================================================================
    if not column_exists('global_settings', 'audit_log_retention_days'):
        op.add_column(
            'global_settings',
            sa.Column('audit_log_retention_days', sa.Integer(), nullable=False, server_default='90')
        )


def downgrade():
    """Remove Phase 6 audit log UI schema changes"""

    if column_exists('global_settings', 'audit_log_retention_days'):
        op.drop_column('global_settings', 'audit_log_retention_days')
