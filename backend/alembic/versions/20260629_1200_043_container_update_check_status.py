"""v2.4.x upgrade - container_updates.check_status

Revision ID: 043_container_update_check_status
Revises: 042_live_chart_window
Create Date: 2026-06-29

CHANGES:
- New container_updates column: check_status (TEXT NULL). NULL = normal update
  record; 'local_image' = image built locally / not resolvable in a registry,
  so the UI can show a "nothing to check" state (with a last_checked stamp)
  that survives a page refresh instead of reverting to "Not Checked".
"""
from alembic import op
import sqlalchemy as sa

revision = '043_container_update_check_status'
down_revision = '042_live_chart_window'
branch_labels = None
depends_on = None


def get_inspector():
    return sa.inspect(op.get_bind())


def column_exists(table_name: str, column_name: str) -> bool:
    if table_name not in get_inspector().get_table_names():
        return False
    return column_name in {c['name'] for c in get_inspector().get_columns(table_name)}


def upgrade():
    if not column_exists('container_updates', 'check_status'):
        op.add_column('container_updates',
                      sa.Column('check_status', sa.Text, nullable=True))


def downgrade():
    if column_exists('container_updates', 'check_status'):
        op.drop_column('container_updates', 'check_status')
