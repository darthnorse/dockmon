"""v2.5.x upgrade - group_tag_scopes (tag-based host visibility)

Revision ID: 046_group_tag_scopes
Revises: 045_oidc_redirect_uri_override
Create Date: 2026-09-16

CHANGES:
- New table group_tag_scopes(group_id, tag_id): a group whose rows are non-empty
  sees only hosts carrying any of the listed tags; zero rows = unrestricted, so
  every existing group keeps seeing everything.
- tag_id is ON DELETE RESTRICT: a tag that scopes a group cannot be deleted
  (a cascade would silently make the group unrestricted).
"""
from alembic import op
import sqlalchemy as sa

revision = '046_group_tag_scopes'
down_revision = '045_oidc_redirect_uri_override'
branch_labels = None
depends_on = None


def get_inspector():
    return sa.inspect(op.get_bind())


def table_exists(table_name: str) -> bool:
    return table_name in get_inspector().get_table_names()


def upgrade():
    if table_exists('group_tag_scopes'):
        return
    op.create_table(
        'group_tag_scopes',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('group_id', sa.Integer,
                  sa.ForeignKey('custom_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tag_id', sa.String,
                  sa.ForeignKey('tags.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.UniqueConstraint('group_id', 'tag_id', name='uq_group_tag_scope'),
    )
    op.create_index('idx_group_tag_scopes_group', 'group_tag_scopes', ['group_id'])
    op.create_index('idx_group_tag_scopes_tag', 'group_tag_scopes', ['tag_id'])


def downgrade():
    if not table_exists('group_tag_scopes'):
        return
    op.drop_index('idx_group_tag_scopes_tag', table_name='group_tag_scopes')
    op.drop_index('idx_group_tag_scopes_group', table_name='group_tag_scopes')
    op.drop_table('group_tag_scopes')
