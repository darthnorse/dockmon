"""Repair - create stats history tables missing on fresh v2.4.x installs

Revision ID: 044_repair_stats_history_tables
Revises: 043_container_update_check_status
Create Date: 2026-07-05

Fresh installs of v2.4.0-v2.4.3 stamped the database at HEAD without ever
running migration 037, and these two tables have no ORM model (the Go
stats-service owns them), so Base.metadata.create_all() did not create them
either. stats-service then disabled persistence and never registered its
/api/stats/ws/ingest endpoint, leaving agents in a "websocket: bad handshake"
retry loop and stats history silently broken.

This migration recreates exactly what 037 creates, guarded so databases that
already have the tables (any upgrade-path install) are untouched. Fresh
installs are fixed separately: database.py now carries Core Table definitions
for both tables, and tests/integration/database/test_schema_parity.py keeps
the two schema sources identical.
"""
from alembic import op
import sqlalchemy as sa

revision = '044_repair_stats_history_tables'
down_revision = '043_container_update_check_status'
branch_labels = None
depends_on = None


def get_inspector():
    return sa.inspect(op.get_bind())


def table_exists(table_name: str) -> bool:
    return table_name in get_inspector().get_table_names()


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


def downgrade():
    # Repair migration: the tables belong to 037, so downgrading 044 must not
    # drop them out from under databases where 037 created them.
    pass
