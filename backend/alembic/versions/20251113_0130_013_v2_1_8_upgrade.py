"""v2.1.8 upgrade - Bug fix release

Revision ID: 013_v2_1_8
Revises: 012_v2_1_7
Create Date: 2025-11-13

CHANGES IN v2.1.8:
- Fix custom template persistence in alert rules (GitHub Issue #43)
- Update app_version to '2.1.8'

BUG FIXES:
- Custom message templates in alert rules didn't persist
  - Root cause: API data flow asymmetry - GET endpoint didn't return custom_template,
    CREATE endpoint didn't pass it to database
  - Fix: Added custom_template to GET response and CREATE flow
  - Impact: Custom templates now persist across page refreshes and edits
  - Note: Data was always saved in database, just not returned to frontend

Note: This is a bug fix release with no database schema changes.
The custom_template column already exists in the alert_rules_v2 table.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '013_v2_1_8'
down_revision = '012_v2_1_7'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Update to v2.1.8"""

    # No schema changes in this version - just update version number
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.8', id=1)
        )


def downgrade() -> None:
    """Downgrade from v2.1.8"""

    # Revert app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.1.7', id=1)
        )
