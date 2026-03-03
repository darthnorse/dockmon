"""Remove unused apikeys.manage_own capability

Revision ID: 035_remove_apikeys_manage_own
Revises: 034_v2_3_0
Create Date: 2026-03-02

The apikeys.manage_own capability was intended for a two-tier API key
permission system (operators manage own keys, admins manage all) that was
never implemented. Remove any seeded GroupPermission records referencing it.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '035_remove_apikeys_manage_own'
down_revision = '034_v2_3_0'
branch_labels = None
depends_on = None


def upgrade():
    """Remove apikeys.manage_own from group_permissions."""
    op.execute(
        "DELETE FROM group_permissions WHERE capability = 'apikeys.manage_own'"
    )


def downgrade():
    """No-op: the capability was unused and should not be re-added."""
    pass
