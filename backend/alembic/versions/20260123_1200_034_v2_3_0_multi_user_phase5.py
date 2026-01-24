"""v2.3.0 Multi-User Support Phase 5 - Custom Groups

Revision ID: 034_v2_3_0_phase5
Revises: 033_v2_3_0
Create Date: 2026-01-23

CHANGES IN v2.3.0 (Phase 5):
- Custom user groups for organization
- User to group membership mapping
- Foundation for future group-based permission inheritance

SCHEMA CHANGES:
1. New tables:
   - custom_groups (organizational groups)
   - user_group_memberships (user-group associations)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '034_v2_3_0_phase5'
down_revision = '033_v2_3_0'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    """Apply Phase 5 custom groups schema changes"""

    # =========================================================================
    # 1. CUSTOM_GROUPS TABLE - Organizational groups
    # =========================================================================
    if not table_exists('custom_groups'):
        op.create_table(
            'custom_groups',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.Text(), nullable=False, unique=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        )

    # =========================================================================
    # 2. USER_GROUP_MEMBERSHIPS TABLE - User to group mapping
    # =========================================================================
    if not table_exists('user_group_memberships'):
        op.create_table(
            'user_group_memberships',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('group_id', sa.Integer(), sa.ForeignKey('custom_groups.id', ondelete='CASCADE'), nullable=False),
            sa.Column('added_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('added_at', sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint('user_id', 'group_id', name='uq_user_group_membership'),
            sa.Index('idx_user_group_user', 'user_id'),
            sa.Index('idx_user_group_group', 'group_id'),
        )


def downgrade():
    """Remove Phase 5 custom groups schema changes"""

    # Drop tables in reverse order (respect foreign keys)
    if table_exists('user_group_memberships'):
        op.drop_table('user_group_memberships')

    if table_exists('custom_groups'):
        op.drop_table('custom_groups')
