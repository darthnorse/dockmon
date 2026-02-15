"""v2.2.3 upgrade - Add container_name to update and health check tables

Revision ID: 027_v2_2_3
Revises: 026_v2_2_2
Create Date: 2025-12-28

CHANGES IN v2.2.3:
- fix: Add container_name column to ContainerUpdate and ContainerHttpHealthCheck
  - Fixes reattachment of settings when containers are recreated (TrueNAS, etc.)
  - Previously relied on AutoRestartConfig table to find container names
  - Now stores container_name directly for independent reattachment
  - Fixes GitHub Issue #114

SCHEMA CHANGES:
- container_updates: Add container_name column (nullable for migration)
- container_http_health_checks: Add container_name column (nullable for migration)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '027_v2_2_3'
down_revision = '026_v2_2_2'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    """Add container_name to ContainerUpdate and ContainerHttpHealthCheck tables"""

    # Add container_name to container_updates table
    if table_exists('container_updates'):
        if not column_exists('container_updates', 'container_name'):
            op.add_column('container_updates', sa.Column('container_name', sa.Text(), nullable=True))

            # Try to populate container_name from AutoRestartConfig or ContainerDesiredState
            # This handles existing records that don't have a name yet
            op.execute(sa.text("""
                UPDATE container_updates
                SET container_name = (
                    SELECT COALESCE(arc.container_name, cds.container_name)
                    FROM (SELECT 1) dummy
                    LEFT JOIN auto_restart_configs arc
                        ON arc.host_id = container_updates.host_id
                        AND (arc.container_id = SUBSTR(container_updates.container_id, INSTR(container_updates.container_id, ':') + 1)
                             OR arc.container_id = container_updates.container_id)
                    LEFT JOIN container_desired_states cds
                        ON cds.host_id = container_updates.host_id
                        AND (cds.container_id = SUBSTR(container_updates.container_id, INSTR(container_updates.container_id, ':') + 1)
                             OR cds.container_id = container_updates.container_id)
                    LIMIT 1
                )
                WHERE container_updates.container_name IS NULL
            """))

    # Add container_name to container_http_health_checks table
    if table_exists('container_http_health_checks'):
        if not column_exists('container_http_health_checks', 'container_name'):
            op.add_column('container_http_health_checks', sa.Column('container_name', sa.Text(), nullable=True))

            # Try to populate container_name from AutoRestartConfig or ContainerDesiredState
            op.execute(sa.text("""
                UPDATE container_http_health_checks
                SET container_name = (
                    SELECT COALESCE(arc.container_name, cds.container_name)
                    FROM (SELECT 1) dummy
                    LEFT JOIN auto_restart_configs arc
                        ON arc.host_id = container_http_health_checks.host_id
                        AND (arc.container_id = SUBSTR(container_http_health_checks.container_id, INSTR(container_http_health_checks.container_id, ':') + 1)
                             OR arc.container_id = container_http_health_checks.container_id)
                    LEFT JOIN container_desired_states cds
                        ON cds.host_id = container_http_health_checks.host_id
                        AND (cds.container_id = SUBSTR(container_http_health_checks.container_id, INSTR(container_http_health_checks.container_id, ':') + 1)
                             OR cds.container_id = container_http_health_checks.container_id)
                    LIMIT 1
                )
                WHERE container_http_health_checks.container_name IS NULL
            """))



def downgrade():
    """Remove container_name columns"""

    if table_exists('container_updates'):
        if column_exists('container_updates', 'container_name'):
            op.drop_column('container_updates', 'container_name')

    if table_exists('container_http_health_checks'):
        if column_exists('container_http_health_checks', 'container_name'):
            op.drop_column('container_http_health_checks', 'container_name')

