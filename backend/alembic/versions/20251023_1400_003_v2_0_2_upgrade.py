"""v2.0.2 upgrade - HTTP health check retry configuration

Revision ID: 003_v2_0_2
Revises: 002_v2_0_1
Create Date: 2025-10-23

CHANGES IN v2.0.2:
- Add max_restart_attempts column to container_http_health_checks (default: 3)
- Add restart_retry_delay_seconds column to container_http_health_checks (default: 120)
- Update app_version to '2.0.2'
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '003_v2_0_2'
down_revision = '002_v2_0_1'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if column exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def table_exists(table_name: str) -> bool:
    """Check if table exists (defensive pattern)"""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Add v2.0.2 features"""

    # Change 1: Add max_restart_attempts column to container_http_health_checks
    if table_exists('container_http_health_checks'):
        if not column_exists('container_http_health_checks', 'max_restart_attempts'):
            op.add_column('container_http_health_checks',
                sa.Column('max_restart_attempts', sa.Integer(), server_default='3', nullable=False))

    # Change 2: Add restart_retry_delay_seconds column to container_http_health_checks
    if table_exists('container_http_health_checks'):
        if not column_exists('container_http_health_checks', 'restart_retry_delay_seconds'):
            op.add_column('container_http_health_checks',
                sa.Column('restart_retry_delay_seconds', sa.Integer(), server_default='120', nullable=False))

    # Change 3: Update app_version
    op.execute(
        sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
        .bindparams(version='2.0.2', id=1)
    )


def downgrade() -> None:
    """Remove v2.0.2 features"""
    # Reverse order of upgrade
    op.execute(
        sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
        .bindparams(version='2.0.1', id=1)
    )

    if table_exists('container_http_health_checks'):
        if column_exists('container_http_health_checks', 'restart_retry_delay_seconds'):
            op.drop_column('container_http_health_checks', 'restart_retry_delay_seconds')
        if column_exists('container_http_health_checks', 'max_restart_attempts'):
            op.drop_column('container_http_health_checks', 'max_restart_attempts')
