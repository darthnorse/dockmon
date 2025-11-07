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
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '006_v2_1_1'
down_revision = '005_v2_1_0'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Update to v2.1.1"""

    # Only change: Update app_version
    # No schema changes in this release - configuration and correctness improvements only
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.1', id=1)
        )


def downgrade() -> None:
    """Downgrade from v2.1.1"""

    # Revert app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.0', id=1)
        )
