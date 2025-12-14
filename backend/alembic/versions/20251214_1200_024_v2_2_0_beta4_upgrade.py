"""v2.2.0-beta4 upgrade - Bug fixes for remote host updates

Revision ID: 024_v2_2_0_beta4
Revises: 023_v2_2_0_beta3
Create Date: 2025-12-14

CHANGES IN v2.2.0-beta4:
- fix: Correct DockerHostDB attribute from docker_url to url
  - Auto-updates and stack deployments now work on remote/mTLS hosts
  - Fixed AttributeError in update_executor._execute_go_update()
  - Fixed AttributeError in stack_executor._get_host_config()
- test: Add unit tests for DockerHostDB url attribute
  - Prevents regression of docker_url bug
  - Tests all connection_types: local, remote, agent
- ci: Restore agent builds on branch pushes
  - Enables testing with feature branch images
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '024_v2_2_0_beta4'
down_revision = '023_v2_2_0_beta3'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Upgrade to v2.2.0-beta4"""

    # No schema changes in this release - only bug fixes in Python code
    # Update app_version only
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.0-beta4', id=1)
        )


def downgrade() -> None:
    """Downgrade to v2.2.0-beta3"""

    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.0-beta3', id=1)
        )
