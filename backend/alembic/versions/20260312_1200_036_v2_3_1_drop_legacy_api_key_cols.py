"""Drop legacy api_keys columns (user_id, scopes)

Revision ID: 036_v2_3_1_drop_legacy_api_key_cols
Revises: 035_pending_approval
Create Date: 2026-03-12

The v2.3.0 migration added group_id (replaces scopes) and
created_by_user_id (replaces user_id) but never dropped the old
columns. On upgraded databases the orphaned NOT NULL columns cause
INSERT failures because SQLAlchemy no longer includes them.

Uses batch_alter_table with recreate='always' because SQLite does
not support DROP COLUMN on older versions, and batch mode rebuilds
the table cleanly with only the columns defined in the model.
"""

from alembic import op
import sqlalchemy as sa


revision = '036_v2_3_1_drop_legacy_api_key_cols'
down_revision = '035_pending_approval'
branch_labels = None
depends_on = None


def get_inspector():
    return sa.inspect(op.get_bind())


def table_exists(table_name: str) -> bool:
    return table_name in get_inspector().get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return column_name in [col['name'] for col in get_inspector().get_columns(table_name)]


def upgrade():
    if not table_exists('api_keys'):
        return

    cols_to_drop = []
    if column_exists('api_keys', 'user_id'):
        cols_to_drop.append('user_id')
    if column_exists('api_keys', 'scopes'):
        cols_to_drop.append('scopes')

    if not cols_to_drop:
        return

    fk_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}

    with op.batch_alter_table('api_keys', recreate='always',
                              naming_convention=fk_naming) as batch_op:
        for col in cols_to_drop:
            batch_op.drop_column(col)
        # Re-establish FK constraints (batch recreate drops them)
        batch_op.alter_column('group_id', existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key('fk_api_keys_group_id_custom_groups', 'custom_groups',
                                    ['group_id'], ['id'], ondelete='RESTRICT')
        batch_op.create_foreign_key('fk_api_keys_created_by_user_id_users', 'users',
                                    ['created_by_user_id'], ['id'], ondelete='SET NULL')


def downgrade():
    if not table_exists('api_keys'):
        return

    fk_naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}

    with op.batch_alter_table('api_keys', recreate='always',
                              naming_convention=fk_naming) as batch_op:
        if not column_exists('api_keys', 'user_id'):
            batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        if not column_exists('api_keys', 'scopes'):
            batch_op.add_column(sa.Column('scopes', sa.Text(), nullable=False,
                                          server_default='read'))

    # Copy created_by_user_id back to user_id
    if column_exists('api_keys', 'user_id') and column_exists('api_keys', 'created_by_user_id'):
        bind = op.get_bind()
        bind.execute(sa.text("""
            UPDATE api_keys SET user_id = created_by_user_id
            WHERE created_by_user_id IS NOT NULL
        """))
