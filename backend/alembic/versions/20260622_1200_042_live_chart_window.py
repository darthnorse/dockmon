"""v2.4.x upgrade - Configurable live chart window

Revision ID: 042_live_chart_window
Revises: 041_disable_local_login
Create Date: 2026-06-22

CHANGES:
- New global_settings column: live_chart_window_seconds (INTEGER NOT NULL,
  server_default '600' = 10 min, range 60..1800 enforced at the API layer).
  Bounds the in-memory live buffer per entity via age-trim; backend + frontend
  only -- NOT pushed to the Go stats-service. Default 600 so upgrades are
  seamless and don't change behavior for existing users.
"""
from alembic import op
import sqlalchemy as sa

revision = '042_live_chart_window'
down_revision = '041_disable_local_login'
branch_labels = None
depends_on = None


def get_inspector():
    return sa.inspect(op.get_bind())


def column_exists(table_name: str, column_name: str) -> bool:
    if table_name not in get_inspector().get_table_names():
        return False
    return column_name in {c['name'] for c in get_inspector().get_columns(table_name)}


def upgrade():
    if not column_exists('global_settings', 'live_chart_window_seconds'):
        op.add_column('global_settings',
                      sa.Column('live_chart_window_seconds', sa.Integer,
                                server_default='600', nullable=False))


def downgrade():
    if column_exists('global_settings', 'live_chart_window_seconds'):
        op.drop_column('global_settings', 'live_chart_window_seconds')
