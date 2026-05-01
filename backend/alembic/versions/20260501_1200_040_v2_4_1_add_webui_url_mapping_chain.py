"""v2.4.1 upgrade - Add webui_url_mapping_chain column to global_settings

Revision ID: 040_v2_4_1_add_webui_url_mapping_chain
Revises: 039_v2_4_1_add_force_unique_partial_index
Create Date: 2026-05-01

CHANGES:
- Add `global_settings.webui_url_mapping_chain` JSON column (nullable). Ordered
  list of URL templates with `${env:NAME}` / `${label:NAME}` placeholders.
  Used to auto-derive a container's WebUI URL when no manual web_ui_url is
  set (Issue #207).
"""
from alembic import op
import sqlalchemy as sa


revision = '040_v2_4_1_add_webui_url_mapping_chain'
down_revision = '039_v2_4_1_add_force_unique_partial_index'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'global_settings',
        sa.Column('webui_url_mapping_chain', sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('global_settings', 'webui_url_mapping_chain')
