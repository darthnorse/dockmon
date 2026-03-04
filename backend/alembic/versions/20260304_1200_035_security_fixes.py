"""Security fixes - PKCE for confidential clients

Revision ID: 035_security_fixes
Revises: 034_v2_3_0
Create Date: 2026-03-04

CHANGES:
- Add disable_pkce_with_secret boolean column to OIDCConfig table
  (providers that reject client_secret + PKCE together can set this flag)
"""

revision = '035_security_fixes'
down_revision = '034_v2_3_0'

from alembic import op
import sqlalchemy as sa


def upgrade():
    # Add disable_pkce_with_secret column with default False
    with op.batch_alter_table('oidc_config') as batch_op:
        batch_op.add_column(
            sa.Column('disable_pkce_with_secret', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )


def downgrade():
    with op.batch_alter_table('oidc_config') as batch_op:
        batch_op.drop_column('disable_pkce_with_secret')
