"""Rename network_rx_bytes/network_tx_bytes to network_bytes_per_sec

Revision ID: 039_rename_network_columns
Revises: 038_stats_rrd_tiers
Create Date: 2026-03-16

CHANGES:
- container_stats_history: rename network_rx_bytes -> network_bytes_per_sec (Float)
- container_stats_history: drop network_tx_bytes (was never populated)
"""
from alembic import op
import sqlalchemy as sa


revision = '039_rename_network_columns'
down_revision = '038_stats_rrd_tiers'
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
        return

    # Add new column, copy data from old column, then drop old columns.
    # SQLite supports ADD COLUMN and DROP COLUMN (3.35+).
    if not column_exists('container_stats_history', 'network_bytes_per_sec'):
        op.add_column('container_stats_history',
                      sa.Column('network_bytes_per_sec', sa.Float(), nullable=True))

    if column_exists('container_stats_history', 'network_rx_bytes'):
        op.execute("UPDATE container_stats_history SET network_bytes_per_sec = network_rx_bytes")
        op.drop_column('container_stats_history', 'network_rx_bytes')

    if column_exists('container_stats_history', 'network_tx_bytes'):
        op.drop_column('container_stats_history', 'network_tx_bytes')


def downgrade():
    if not table_exists('container_stats_history'):
        return

    if not column_exists('container_stats_history', 'network_rx_bytes'):
        op.add_column('container_stats_history',
                      sa.Column('network_rx_bytes', sa.BigInteger(), nullable=True))

    if column_exists('container_stats_history', 'network_bytes_per_sec'):
        op.execute("UPDATE container_stats_history SET network_rx_bytes = CAST(network_bytes_per_sec AS INTEGER)")
        op.drop_column('container_stats_history', 'network_bytes_per_sec')

    if not column_exists('container_stats_history', 'network_tx_bytes'):
        op.add_column('container_stats_history',
                      sa.Column('network_tx_bytes', sa.BigInteger(), nullable=True))
