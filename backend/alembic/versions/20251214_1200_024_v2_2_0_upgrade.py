"""v2.2.0 upgrade - Bug fixes for remote host updates + alert timing refactor

Revision ID: 024_v2_2_0
Revises: 023_v2_2_0_beta3
Create Date: 2025-12-14

CHANGES IN v2.2.0:
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
- feat: Refactor alert timing fields for clarity (Fixes #96)
  - Rename duration_seconds -> alert_active_delay_seconds
  - Split clear_duration_seconds into:
    - alert_clear_delay_seconds (for metric clearing)
    - notification_active_delay_seconds (for notification timing)
  - Rename cooldown_seconds -> notification_cooldown_seconds
  - Adds event alert active delay support (NEW FEATURE)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '024_v2_2_0'
down_revision = '023_v2_2_0_beta3'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Upgrade to v2.2.0"""

    if table_exists('alert_rules_v2'):
        # =====================================================================
        # Part 1: Add auto_resolve_on_clear column (existing beta4 change)
        # =====================================================================
        # This splits auto_resolve into two independent behaviors:
        # - auto_resolve: Resolve immediately after notification (original behavior)
        # - auto_resolve_on_clear: Clear when condition resolves (e.g., container restarts)
        if not column_exists('alert_rules_v2', 'auto_resolve_on_clear'):
            op.add_column('alert_rules_v2',
                sa.Column('auto_resolve_on_clear', sa.Boolean(), nullable=False, server_default='0')
            )
            # Copy existing auto_resolve values to preserve current behavior
            # Users who had auto_resolve=True get BOTH behaviors initially
            op.execute(
                sa.text("UPDATE alert_rules_v2 SET auto_resolve_on_clear = auto_resolve")
            )

        # =====================================================================
        # Part 2: Refactor alert timing fields for clarity (Fixes #96)
        # =====================================================================
        # Add new columns for clear separation of concerns:
        #
        # Alert timing:
        #   - alert_active_delay_seconds: Condition must be TRUE for X seconds before alerting
        #   - alert_clear_delay_seconds: Condition must be FALSE for X seconds before clearing
        #
        # Notification timing:
        #   - notification_active_delay_seconds: Alert must be active for X seconds before notifying
        #   - notification_cooldown_seconds: Wait X seconds between notifications

        # Add alert_active_delay_seconds (replaces duration_seconds)
        if not column_exists('alert_rules_v2', 'alert_active_delay_seconds'):
            op.add_column('alert_rules_v2',
                sa.Column('alert_active_delay_seconds', sa.Integer(), nullable=True)
            )

        # Add alert_clear_delay_seconds (split from clear_duration_seconds for metrics)
        if not column_exists('alert_rules_v2', 'alert_clear_delay_seconds'):
            op.add_column('alert_rules_v2',
                sa.Column('alert_clear_delay_seconds', sa.Integer(), nullable=True)
            )

        # Add notification_active_delay_seconds (split from clear_duration_seconds for events)
        if not column_exists('alert_rules_v2', 'notification_active_delay_seconds'):
            op.add_column('alert_rules_v2',
                sa.Column('notification_active_delay_seconds', sa.Integer(), nullable=True)
            )

        # Add notification_cooldown_seconds (replaces cooldown_seconds)
        if not column_exists('alert_rules_v2', 'notification_cooldown_seconds'):
            op.add_column('alert_rules_v2',
                sa.Column('notification_cooldown_seconds', sa.Integer(), nullable=True)
            )

        # =====================================================================
        # Migrate data from old columns to new columns
        # =====================================================================

        # Migrate duration_seconds -> alert_active_delay_seconds (all rules)
        op.execute(sa.text("""
            UPDATE alert_rules_v2
            SET alert_active_delay_seconds = duration_seconds
            WHERE duration_seconds IS NOT NULL
              AND alert_active_delay_seconds IS NULL
        """))

        # Migrate cooldown_seconds -> notification_cooldown_seconds (all rules)
        op.execute(sa.text("""
            UPDATE alert_rules_v2
            SET notification_cooldown_seconds = COALESCE(cooldown_seconds, 300)
            WHERE notification_cooldown_seconds IS NULL
        """))

        # Migrate clear_duration_seconds -> split based on alert kind
        # For METRIC alerts: goes to alert_clear_delay_seconds (controls clearing)
        # Metric kinds: cpu_high, memory_high, disk_low, and any custom metric rules
        op.execute(sa.text("""
            UPDATE alert_rules_v2
            SET alert_clear_delay_seconds = clear_duration_seconds
            WHERE kind IN ('cpu_high', 'memory_high', 'disk_low', 'metric_custom')
              AND clear_duration_seconds IS NOT NULL
              AND alert_clear_delay_seconds IS NULL
        """))

        # For EVENT alerts: goes to notification_active_delay_seconds (controls notification timing)
        op.execute(sa.text("""
            UPDATE alert_rules_v2
            SET notification_active_delay_seconds = clear_duration_seconds,
                alert_clear_delay_seconds = 0
            WHERE kind NOT IN ('cpu_high', 'memory_high', 'disk_low', 'metric_custom')
              AND clear_duration_seconds IS NOT NULL
              AND notification_active_delay_seconds IS NULL
        """))

        # Set defaults for any remaining NULL values
        op.execute(sa.text("""
            UPDATE alert_rules_v2
            SET alert_active_delay_seconds = COALESCE(alert_active_delay_seconds, 0),
                alert_clear_delay_seconds = COALESCE(alert_clear_delay_seconds, 0),
                notification_active_delay_seconds = COALESCE(notification_active_delay_seconds, 0),
                notification_cooldown_seconds = COALESCE(notification_cooldown_seconds, 300)
        """))



def downgrade() -> None:
    """Downgrade to v2.2.0-beta3"""

    if table_exists('alert_rules_v2'):
        # Remove timing columns
        if column_exists('alert_rules_v2', 'alert_active_delay_seconds'):
            op.drop_column('alert_rules_v2', 'alert_active_delay_seconds')
        if column_exists('alert_rules_v2', 'alert_clear_delay_seconds'):
            op.drop_column('alert_rules_v2', 'alert_clear_delay_seconds')
        if column_exists('alert_rules_v2', 'notification_active_delay_seconds'):
            op.drop_column('alert_rules_v2', 'notification_active_delay_seconds')
        if column_exists('alert_rules_v2', 'notification_cooldown_seconds'):
            op.drop_column('alert_rules_v2', 'notification_cooldown_seconds')

        # Remove auto_resolve_on_clear column
        if column_exists('alert_rules_v2', 'auto_resolve_on_clear'):
            op.drop_column('alert_rules_v2', 'auto_resolve_on_clear')

