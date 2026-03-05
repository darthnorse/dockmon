"""Fixup: add missing columns, indexes, and FK policies from 034

Revision ID: 036_account_lockout_fixup
Revises: 035_security_fixes
Create Date: 2026-03-04

CHANGES:
- Add failed_login_attempts and locked_until columns to users table
- Ensure unique index on oidc_subject exists
- Fix FK on_delete policies for user_prefs, registration_tokens, batch_jobs
  (034 batch mode in SQLite sometimes fails to apply schema changes silently)
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


def _get_fk_ondelete(table_name: str, column_name: str) -> str:
    """Get the on_delete policy for a specific FK column."""
    conn = op.get_bind()
    fks = conn.execute(sa.text(f"PRAGMA foreign_key_list({table_name})")).fetchall()
    for fk in fks:
        if fk[3] == column_name:
            return fk[6]
    return 'UNKNOWN'


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
        if _index_exists('users', 'ix_users_oidc_subject'):
            op.drop_index('ix_users_oidc_subject', 'users')
        if not _index_exists('users', 'uq_users_oidc_subject'):
            op.create_index('uq_users_oidc_subject', 'users', ['oidc_subject'], unique=True)

    # Fix FK on_delete policies that 034 batch mode failed to apply.
    # SQLite requires table rebuild to change FK constraints.
    fk_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}

    # user_prefs.user_id should be CASCADE (deleting user deletes their prefs)
    if _get_fk_ondelete('user_prefs', 'user_id') == 'NO ACTION':
        with op.batch_alter_table('user_prefs', recreate='always', naming_convention=fk_naming) as batch_op:
            batch_op.drop_constraint('fk_user_prefs_user_id_users', type_='foreignkey')
            batch_op.create_foreign_key('fk_user_prefs_user_id_users', 'users',
                                        ['user_id'], ['id'], ondelete='CASCADE')

    # registration_tokens.created_by_user_id should be SET NULL
    if _column_exists('registration_tokens', 'created_by_user_id'):
        if _get_fk_ondelete('registration_tokens', 'created_by_user_id') == 'NO ACTION':
            with op.batch_alter_table('registration_tokens', recreate='always', naming_convention=fk_naming) as batch_op:
                batch_op.alter_column('created_by_user_id', existing_type=sa.Integer(), nullable=True)
                batch_op.drop_constraint('fk_registration_tokens_created_by_user_id_users', type_='foreignkey')
                batch_op.create_foreign_key('fk_registration_tokens_created_by_user_id_users', 'users',
                                            ['created_by_user_id'], ['id'], ondelete='SET NULL')

    # batch_jobs.user_id should be SET NULL
    if _column_exists('batch_jobs', 'user_id'):
        if _get_fk_ondelete('batch_jobs', 'user_id') == 'NO ACTION':
            with op.batch_alter_table('batch_jobs', recreate='always', naming_convention=fk_naming) as batch_op:
                batch_op.drop_constraint('fk_batch_jobs_user_id_users', type_='foreignkey')
                batch_op.create_foreign_key('fk_batch_jobs_user_id_users', 'users',
                                            ['user_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('users') as batch_op:
        if _column_exists('users', 'failed_login_attempts'):
            batch_op.drop_column('failed_login_attempts')
        if _column_exists('users', 'locked_until'):
            batch_op.drop_column('locked_until')
