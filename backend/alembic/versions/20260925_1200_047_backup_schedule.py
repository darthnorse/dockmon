"""v2.5.x upgrade - global_settings scheduled backup columns

Revision ID: 047_backup_schedule
Revises: 046_group_tag_scopes
Create Date: 2026-09-25

CHANGES:
- global_settings: backup_schedule_enabled, backup_schedule, backup_retention,
  backup_include_stats, backup_passphrase_encrypted (Fernet), backup_last_run_at,
  backup_last_status, backup_last_error, backup_last_file.
"""
from alembic import op
import sqlalchemy as sa

revision = '047_backup_schedule'
down_revision = '046_group_tag_scopes'
branch_labels = None
depends_on = None

COLUMNS = (
    sa.Column('backup_schedule_enabled', sa.Boolean, nullable=False, server_default='0'),
    sa.Column('backup_schedule', sa.Text, nullable=False, server_default='03:00'),
    sa.Column('backup_retention', sa.Integer, nullable=False, server_default='7'),
    sa.Column('backup_include_stats', sa.Boolean, nullable=False, server_default='1'),
    sa.Column('backup_passphrase_encrypted', sa.Text, nullable=True),
    sa.Column('backup_last_run_at', sa.DateTime, nullable=True),
    sa.Column('backup_last_status', sa.Text, nullable=True),
    sa.Column('backup_last_error', sa.Text, nullable=True),
    sa.Column('backup_last_file', sa.Text, nullable=True),
)


def column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {c['name'] for c in inspector.get_columns(table_name)}


def upgrade():
    for column in COLUMNS:
        if not column_exists('global_settings', column.name):
            op.add_column('global_settings', column.copy())


def downgrade():
    for column in reversed(COLUMNS):
        if column_exists('global_settings', column.name):
            op.drop_column('global_settings', column.name)
