"""Stats persistence - Persistent container statistics

Revision ID: 037_stats_persistence
Revises: 036_v2_3_1_drop_legacy_api_key_cols
Create Date: 2026-03-15

CHANGES IN v2.3.0:
- feat: Add persistent container statistics with 30-day tiered retention
  - New container_stats_history table for CPU, Memory, Network metrics
  - Background stats collector (configurable interval, default 60s)
  - Tiered retention: 1m (24h), 5m (7d), 1h (30d)
  - Historical stats API endpoint
  - Time-range filter in container detail view (Live, 1h, 8h, 24h, 7d, 30d)

SCHEMA CHANGES:
- NEW TABLE: container_stats_history (id, container_id, host_id, timestamp,
  cpu_percent, memory_usage, memory_limit, network_bytes_per_sec, resolution)
- NEW INDEXES: idx_stats_lookup (container_id, resolution, timestamp),
  idx_stats_host (host_id)
- global_settings: Add stats_retention_enabled, stats_collection_interval,
  stats_retention_days columns
"""
from alembic import op
import sqlalchemy as sa


revision = '037_stats_persistence'
down_revision = '036_v2_3_1_drop_legacy_api_key_cols'
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
    if not table_exists('container_stats_history'):
        op.create_table(
            'container_stats_history',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('container_id', sa.String(), nullable=False),
            sa.Column('host_id', sa.String(), sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('timestamp', sa.DateTime(), nullable=False),
            sa.Column('cpu_percent', sa.Float(), nullable=True),
            sa.Column('memory_usage', sa.BigInteger(), nullable=True),
            sa.Column('memory_limit', sa.BigInteger(), nullable=True),
            sa.Column('network_bytes_per_sec', sa.Float(), nullable=True),
            sa.Column('resolution', sa.String(), nullable=False, server_default='1m'),
        )
        op.create_index('idx_stats_lookup', 'container_stats_history',
                        ['container_id', 'resolution', 'timestamp'])
        op.create_index('idx_stats_host', 'container_stats_history', ['host_id'])

    if table_exists('global_settings'):
        if not column_exists('global_settings', 'stats_retention_enabled'):
            op.add_column('global_settings',
                          sa.Column('stats_retention_enabled', sa.Boolean(), server_default='1'))
        if not column_exists('global_settings', 'stats_collection_interval'):
            op.add_column('global_settings',
                          sa.Column('stats_collection_interval', sa.Integer(), server_default='60'))
        if not column_exists('global_settings', 'stats_retention_days'):
            op.add_column('global_settings',
                          sa.Column('stats_retention_days', sa.Integer(), server_default='30'))


def downgrade():
    if table_exists('container_stats_history'):
        op.drop_index('idx_stats_host', table_name='container_stats_history')
        op.drop_index('idx_stats_lookup', table_name='container_stats_history')
        op.drop_table('container_stats_history')

    if table_exists('global_settings'):
        if column_exists('global_settings', 'stats_retention_enabled'):
            op.drop_column('global_settings', 'stats_retention_enabled')
        if column_exists('global_settings', 'stats_collection_interval'):
            op.drop_column('global_settings', 'stats_collection_interval')
        if column_exists('global_settings', 'stats_retention_days'):
            op.drop_column('global_settings', 'stats_retention_days')
