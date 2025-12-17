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
- feat: Split auto_resolve into two independent behaviors (Fixes #96)
  - Add auto_resolve_on_clear column for condition-based clearing
  - Preserves existing auto_resolve for immediate-after-notification
  - Allows users to choose each behavior independently
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

    # Add auto_resolve_on_clear column for condition-based alert clearing
    # This splits auto_resolve into two independent behaviors:
    # - auto_resolve: Resolve immediately after notification (original behavior)
    # - auto_resolve_on_clear: Clear when condition resolves (e.g., container restarts)
    if table_exists('alert_rules_v2'):
        # Add column with default False
        op.add_column('alert_rules_v2',
            sa.Column('auto_resolve_on_clear', sa.Boolean(), nullable=False, server_default='0')
        )

        # Copy existing auto_resolve values to preserve current behavior
        # Users who had auto_resolve=True get BOTH behaviors initially
        op.execute(
            sa.text("UPDATE alert_rules_v2 SET auto_resolve_on_clear = auto_resolve")
        )

    # Update app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.0-beta4', id=1)
        )


def downgrade() -> None:
    """Downgrade to v2.2.0-beta3"""

    # Remove auto_resolve_on_clear column
    if table_exists('alert_rules_v2'):
        op.drop_column('alert_rules_v2', 'auto_resolve_on_clear')

    # Downgrade app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.0-beta3', id=1)
        )
