"""Fixup: add missing account lockout columns

Revision ID: 036_account_lockout_fixup
Revises: 035_security_fixes
Create Date: 2026-03-04

CHANGES:
- Add failed_login_attempts and locked_until columns to users table
  (should have been added by 034 but were missed due to SQLite batch mode issue)
"""

revision = '036_account_lockout_fixup'
down_revision = '035_security_fixes'

from alembic import op
import sqlalchemy as sa


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    column_names = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in column_names


def upgrade():
    if not _column_exists('users', 'failed_login_attempts'):
        with op.batch_alter_table('users') as batch_op:
            batch_op.add_column(sa.Column(
                'failed_login_attempts', sa.Integer(),
                nullable=False, server_default='0'
            ))

    if not _column_exists('users', 'locked_until'):
        with op.batch_alter_table('users') as batch_op:
            batch_op.add_column(sa.Column(
                'locked_until', sa.DateTime(), nullable=True
            ))


def downgrade():
    with op.batch_alter_table('users') as batch_op:
        if _column_exists('users', 'failed_login_attempts'):
            batch_op.drop_column('failed_login_attempts')
        if _column_exists('users', 'locked_until'):
            batch_op.drop_column('locked_until')
