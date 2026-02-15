"""v2.1.1 upgrade - Reverse proxy and container state improvements

Revision ID: 006_v2_1_1
Revises: 005_v2_1_0
Create Date: 2025-11-07

CHANGES IN v2.1.1:
- No database schema changes
- Update app_version to '2.1.1'

NEW FEATURES:
- BASE_PATH support for reverse proxy subpath deployment (Issue #22)
  - Configure BASE_PATH build arg and environment variable
  - Enables deployment at subpaths like /dockmon/
  - Frontend automatically uses BASE_PATH for routing
- Exit code handling for container events (Issue #23)
  - Distinguish clean stops (exit code 0) from crashes (non-zero)
  - Accurate container state reporting for TrueNAS and other orchestrators
- Reverse proxy mode configuration (Issue #25)
  - REVERSE_PROXY_MODE environment variable
  - Automatic nginx HTTP/HTTPS mode selection
  - Clear deployment examples in docker-compose.yml

Note: This is primarily a configuration and correctness release with no database schema changes.
The migration exists solely to update the version number for tracking.
"""
# revision identifiers, used by Alembic.
revision = '006_v2_1_1'
down_revision = '005_v2_1_0'
branch_labels = None
depends_on = None


def upgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass


def downgrade():
    """No-op: version is now injected at build time via /app/VERSION"""
    pass
