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
# revision identifiers, used by Alembic.
revision = '022_v2_2_0_beta2'
down_revision = '021_v2_2_0'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
