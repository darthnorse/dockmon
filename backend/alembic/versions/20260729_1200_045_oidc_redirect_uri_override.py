"""v2.4.x upgrade - oidc_config.redirect_uri_override

Revision ID: 045_oidc_redirect_uri_override
Revises: 044_repair_stats_history_tables
Create Date: 2026-07-29

CHANGES:
- New oidc_config column: redirect_uri_override (TEXT NULL). NULL = derive the
  OIDC redirect_uri from the request as before; a value pins it verbatim, for
  proxy chains that forward no header identifying the public origin (so the
  detected URI cannot match what is registered with the provider).
"""
from alembic import op
import sqlalchemy as sa

revision = '045_oidc_redirect_uri_override'
down_revision = '044_repair_stats_history_tables'
branch_labels = None
depends_on = None


def get_inspector():
    return sa.inspect(op.get_bind())


def column_exists(table_name: str, column_name: str) -> bool:
    if table_name not in get_inspector().get_table_names():
        return False
    return column_name in {c['name'] for c in get_inspector().get_columns(table_name)}


def upgrade():
    if not column_exists('oidc_config', 'redirect_uri_override'):
        op.add_column('oidc_config',
                      sa.Column('redirect_uri_override', sa.Text, nullable=True))


def downgrade():
    if column_exists('oidc_config', 'redirect_uri_override'):
        op.drop_column('oidc_config', 'redirect_uri_override')
