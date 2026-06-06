"""Disable local login (SSO-only enforcement)

Revision ID: 041_disable_local_login
Revises: 040_v2_4_1_add_webui_url_mapping_chain
Create Date: 2026-06-05

CHANGES:
- oidc_config.local_login_disabled: BOOLEAN NOT NULL DEFAULT 0

When set, POST /api/v2/auth/login rejects all local password logins (API keys
stay exempt). The DOCKMON_FORCE_LOCAL_LOGIN env override forces local login back
on as a break-glass.

SQLite ADD COLUMN silently drops NOT NULL, so we use batch_alter_table with
recreate='always' to rebuild the table and enforce the NOT NULL constraint.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '041_disable_local_login'
down_revision = '040_v2_4_1_add_webui_url_mapping_chain'
branch_labels = None
depends_on = None


# =============================================================================
# Helper Functions
# =============================================================================

def get_inspector():
    """Get SQLAlchemy inspector for the current database connection."""
    bind = op.get_bind()
    return sa.inspect(bind)


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    inspector = get_inspector()
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    if not table_exists(table_name):
        return False
    inspector = get_inspector()
    column_names = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in column_names


def _ensure_not_null(table_name: str, column_name: str, col_type, default_value: str):
    """Add column with NOT NULL constraint, handling SQLite limitations.

    SQLite ADD COLUMN silently drops NOT NULL, so this:
    1. Adds the column as nullable (if missing)
    2. Backfills NULLs with the default value
    3. Rebuilds the table to enforce NOT NULL
    """
    bind = op.get_bind()

    if not column_exists(table_name, column_name):
        op.add_column(table_name, sa.Column(
            column_name, col_type, nullable=True, server_default=default_value
        ))

    if not column_exists(table_name, column_name):
        return

    bind.execute(sa.text(
        f"UPDATE {table_name} SET {column_name} = {default_value} WHERE {column_name} IS NULL"
    ))
    with op.batch_alter_table(table_name, schema=None, recreate='always') as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=col_type,
            nullable=False,
            server_default=default_value,
        )


def upgrade():
    """Add local_login_disabled to oidc_config.

    The runtime self-heal in DatabaseManager (database.py) may have already added
    this column on boot. _ensure_not_null is idempotent: if the column exists it
    skips the add and only re-asserts NOT NULL, so running both mechanisms is safe.
    """
    if table_exists('oidc_config'):
        _ensure_not_null('oidc_config', 'local_login_disabled', sa.Boolean(), '0')


def downgrade():
    """Remove local_login_disabled from oidc_config."""
    if table_exists('oidc_config') and column_exists('oidc_config', 'local_login_disabled'):
        with op.batch_alter_table('oidc_config', schema=None, recreate='always') as batch_op:
            batch_op.drop_column('local_login_disabled')
