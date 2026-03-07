"""v2.3.0 upgrade - Cascading RRD stats tiers

Revision ID: 035_v2_3_0_rrd
Revises: 034_v2_3_0
Create Date: 2026-03-07

CHANGES:
- Add stats_points_per_view column to global_settings (default 500)
- Truncate container_stats_history (old resolution scheme incompatible with RRD tiers)
- Resolution column values change from '1m'/'5m'/'1h' to tier names '1h'/'8h'/'24h'/'7d'/'30d'
"""
from alembic import op
import sqlalchemy as sa


revision = '035_v2_3_0_rrd'
down_revision = '034_v2_3_0'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    if table_exists('global_settings'):
        if not column_exists('global_settings', 'stats_points_per_view'):
            op.add_column('global_settings',
                          sa.Column('stats_points_per_view', sa.Integer(), server_default='500'))

    # Truncate old stats data — resolution scheme changed from interval-based to tier-based
    if table_exists('container_stats_history'):
        op.execute("DELETE FROM container_stats_history")


def downgrade():
    if table_exists('global_settings'):
        if column_exists('global_settings', 'stats_points_per_view'):
            op.drop_column('global_settings', 'stats_points_per_view')
