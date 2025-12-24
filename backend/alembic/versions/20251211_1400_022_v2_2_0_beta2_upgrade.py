"""v2.2.0-beta2 upgrade - Bug fixes for reverse proxy deployments

Revision ID: 022_v2_2_0_beta2
Revises: 021_v2_2_0
Create Date: 2025-12-11

CHANGES IN v2.2.0-beta2:
- fix: Add agent WebSocket endpoint to nginx-http.conf
  - Critical fix for REVERSE_PROXY_MODE users
  - Agent connections were failing with 'websocket: bad handshake'
  - The /api/agent/ws path was missing WebSocket upgrade headers
- feat: Add compose build support for images with build directives
  - Compose files with build: directives now work correctly
  - Agent calls Build() before Up() (same pattern as Portainer)
- fix: Remove auto-release from agent workflow
  - Agent releases are now manually controlled
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '022_v2_2_0_beta2'
down_revision = '021_v2_2_0'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Upgrade to v2.2.0-beta2"""

    # Update app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.0-beta2', id=1)
        )


def downgrade() -> None:
    """Downgrade to v2.2.0-beta1"""

    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.0-beta1', id=1)
        )
