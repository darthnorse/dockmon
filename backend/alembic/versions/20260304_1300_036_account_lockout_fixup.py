"""Fixup: add missing columns and indexes from 034

Revision ID: 036_account_lockout_fixup
Revises: 035_security_fixes
Create Date: 2026-03-04

CHANGES:
- Add failed_login_attempts and locked_until columns to users table
- Ensure unique index on oidc_subject exists
  (034 batch mode in SQLite sometimes drops columns/indexes silently)
"""

revision = '036_account_lockout_fixup'
down_revision = '035_security_fixes'

from alembic import op
import sqlalchemy as sa


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    column_names = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in column_names


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return index_name in [idx['name'] for idx in inspector.get_indexes(table_name)]


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

    # Fix unique index on oidc_subject (034 may have created non-unique or skipped it)
    if _column_exists('users', 'oidc_subject'):
        # Drop non-unique version if it exists
        if _index_exists('users', 'ix_users_oidc_subject'):
            op.drop_index('ix_users_oidc_subject', 'users')
        # Create unique version if missing
        if not _index_exists('users', 'uq_users_oidc_subject'):
            op.create_index('uq_users_oidc_subject', 'users', ['oidc_subject'], unique=True)


def downgrade():
    with op.batch_alter_table('users') as batch_op:
        if _column_exists('users', 'failed_login_attempts'):
            batch_op.drop_column('failed_login_attempts')
        if _column_exists('users', 'locked_until'):
            batch_op.drop_column('locked_until')
