"""Drop legacy api_keys columns (user_id, scopes)

Revision ID: 036_v2_3_1_drop_legacy_api_key_cols
Revises: 035_pending_approval
Create Date: 2026-03-12

The v2.3.0 migration added group_id (replaces scopes) and
created_by_user_id (replaces user_id) but never dropped the old
columns. On upgraded databases the orphaned NOT NULL columns cause
INSERT failures because SQLAlchemy no longer includes them.

Uses explicit SQL table rebuild instead of batch_alter_table
recreate='always', which silently crashes on some database states.
Native DROP COLUMN can't be used because user_id has a FK constraint.
"""

import logging
from alembic import op
import sqlalchemy as sa

logger = logging.getLogger('alembic.migration')

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


def _fix_data_integrity(bind):
    """Ensure api_keys data won't violate constraints during table rebuild."""
    if column_exists('api_keys', 'group_id'):
        null_count = bind.execute(sa.text(
            "SELECT COUNT(*) FROM api_keys WHERE group_id IS NULL"
        )).scalar()
        if null_count > 0:
            admin_gid = bind.execute(sa.text(
                "SELECT id FROM custom_groups WHERE name = 'Administrators' LIMIT 1"
            )).scalar()
            if admin_gid:
                logger.info(f"Fixing {null_count} api_keys with NULL group_id")
                bind.execute(sa.text(
                    "UPDATE api_keys SET group_id = :gid WHERE group_id IS NULL"
                ).bindparams(gid=admin_gid))

    if column_exists('api_keys', 'created_by_user_id'):
        orphan_count = bind.execute(sa.text(
            "SELECT COUNT(*) FROM api_keys "
            "WHERE created_by_user_id IS NOT NULL "
            "AND created_by_user_id NOT IN (SELECT id FROM users)"
        )).scalar()
        if orphan_count > 0:
            logger.info(f"Clearing {orphan_count} orphaned created_by_user_id references")
            bind.execute(sa.text(
                "UPDATE api_keys SET created_by_user_id = NULL "
                "WHERE created_by_user_id IS NOT NULL "
                "AND created_by_user_id NOT IN (SELECT id FROM users)"
            ))


def upgrade():
    if not table_exists('api_keys'):
        return

    has_user_id = column_exists('api_keys', 'user_id')
    has_scopes = column_exists('api_keys', 'scopes')

    if not has_user_id and not has_scopes:
        return

    bind = op.get_bind()
    _fix_data_integrity(bind)

    logger.info(f"Dropping legacy columns from api_keys: user_id={has_user_id}, scopes={has_scopes}")

    # Manual table rebuild — avoids batch_alter_table which crashes silently,
    # and native DROP COLUMN which fails on columns with FK constraints.
    bind.execute(sa.text("""
        CREATE TABLE _api_keys_new (
            id INTEGER NOT NULL PRIMARY KEY,
            group_id INTEGER NOT NULL,
            created_by_user_id INTEGER,
            name TEXT NOT NULL,
            description TEXT,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            allowed_ips TEXT,
            last_used_at DATETIME,
            usage_count INTEGER DEFAULT 0 NOT NULL,
            expires_at DATETIME,
            revoked_at DATETIME,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(group_id) REFERENCES custom_groups(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """))

    bind.execute(sa.text("""
        INSERT INTO _api_keys_new
            (id, group_id, created_by_user_id, name, description,
             key_hash, key_prefix, allowed_ips, last_used_at, usage_count,
             expires_at, revoked_at, created_at, updated_at)
        SELECT id, group_id, created_by_user_id, name, description,
               key_hash, key_prefix, allowed_ips, last_used_at, usage_count,
               expires_at, revoked_at, created_at, updated_at
        FROM api_keys
    """))

    bind.execute(sa.text("DROP TABLE api_keys"))
    bind.execute(sa.text("ALTER TABLE _api_keys_new RENAME TO api_keys"))
    logger.info("api_keys table rebuilt without legacy columns")


def downgrade():
    if not table_exists('api_keys'):
        return

    bind = op.get_bind()

    if not column_exists('api_keys', 'user_id'):
        op.add_column('api_keys', sa.Column('user_id', sa.Integer(), nullable=True))
    if not column_exists('api_keys', 'scopes'):
        op.add_column('api_keys', sa.Column('scopes', sa.Text(), nullable=False,
                                            server_default='read'))

    if column_exists('api_keys', 'user_id') and column_exists('api_keys', 'created_by_user_id'):
        bind.execute(sa.text("""
            UPDATE api_keys SET user_id = created_by_user_id
            WHERE created_by_user_id IS NOT NULL
        """))
