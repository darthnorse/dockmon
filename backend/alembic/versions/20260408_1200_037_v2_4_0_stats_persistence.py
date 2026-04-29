"""v2.4.0 upgrade - Persistent stats history

Revision ID: 037_v2_4_0_stats_persistence
Revises: 036_v2_3_1_drop_legacy_api_key_cols
Create Date: 2026-04-08

CHANGES:
- New container_stats_history table (CPU/mem/net, 5 RRD tiers, 30d retention)
- New host_stats_history table (aggregated from /host/proc when available)
- New global_settings columns: stats_persistence_enabled, stats_retention_days,
  stats_points_per_view
- UNIQUE constraints on (entity_id, resolution, timestamp) act as both dedup
  enforcement and read indexes
- stats_persistence_enabled defaults to OFF so upgrades don't change behavior
  for existing users; opt-in via the settings UI.
"""
from alembic import op
import sqlalchemy as sa

revision = '037_v2_4_0_stats_persistence'
down_revision = '036_v2_3_1_drop_legacy_api_key_cols'
branch_labels = None
depends_on = None


def get_inspector():
    return sa.inspect(op.get_bind())


def table_exists(table_name: str) -> bool:
    return table_name in get_inspector().get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return column_name in {c['name'] for c in get_inspector().get_columns(table_name)}


def upgrade():
    if not table_exists('container_stats_history'):
        op.create_table(
            'container_stats_history',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('container_id', sa.Text, nullable=False),
            sa.Column('host_id', sa.Text,
                      sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('timestamp', sa.Integer, nullable=False),
            sa.Column('resolution', sa.Text, nullable=False),
            sa.Column('cpu_percent', sa.Float, nullable=True),
            sa.Column('memory_usage', sa.BigInteger, nullable=True),
            sa.Column('memory_limit', sa.BigInteger, nullable=True),
            sa.Column('network_bps', sa.Float, nullable=True),
            sa.UniqueConstraint('container_id', 'resolution', 'timestamp',
                                name='uq_container_stats'),
        )
        # host_stats_history doesn't need a host index because its UNIQUE
        # constraint already leads with host_id; this table's UNIQUE leads
        # with container_id, so a separate host index is needed for the
        # CASCADE delete and host-scoped retention sweeps.
        op.create_index('idx_container_stats_host', 'container_stats_history',
                        ['host_id'])

    if not table_exists('host_stats_history'):
        op.create_table(
            'host_stats_history',
            sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
            sa.Column('host_id', sa.Text,
                      sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'),
                      nullable=False),
            sa.Column('timestamp', sa.Integer, nullable=False),
            sa.Column('resolution', sa.Text, nullable=False),
            sa.Column('cpu_percent', sa.Float, nullable=True),
            sa.Column('memory_percent', sa.Float, nullable=True),
            sa.Column('memory_used_bytes', sa.BigInteger, nullable=True),
            sa.Column('memory_limit_bytes', sa.BigInteger, nullable=True),
            sa.Column('network_bps', sa.Float, nullable=True),
            sa.Column('container_count', sa.Integer, nullable=True),
            sa.UniqueConstraint('host_id', 'resolution', 'timestamp',
                                name='uq_host_stats'),
        )

    if not column_exists('global_settings', 'stats_persistence_enabled'):
        op.add_column('global_settings',
                      sa.Column('stats_persistence_enabled', sa.Boolean,
                                server_default='0', nullable=False))
    if not column_exists('global_settings', 'stats_retention_days'):
        op.add_column('global_settings',
                      sa.Column('stats_retention_days', sa.Integer,
                                server_default='30', nullable=False))
    if not column_exists('global_settings', 'stats_points_per_view'):
        op.add_column('global_settings',
                      sa.Column('stats_points_per_view', sa.Integer,
                                server_default='500', nullable=False))


def downgrade():
    if table_exists('container_stats_history'):
        op.drop_index('idx_container_stats_host',
                      table_name='container_stats_history')
        op.drop_table('container_stats_history')
    if table_exists('host_stats_history'):
        op.drop_table('host_stats_history')
    if column_exists('global_settings', 'stats_persistence_enabled'):
        op.drop_column('global_settings', 'stats_persistence_enabled')
    if column_exists('global_settings', 'stats_retention_days'):
        op.drop_column('global_settings', 'stats_retention_days')
    if column_exists('global_settings', 'stats_points_per_view'):
        op.drop_column('global_settings', 'stats_points_per_view')
