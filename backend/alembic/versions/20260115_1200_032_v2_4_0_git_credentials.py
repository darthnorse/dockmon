"""v2.4.0 - Git-based stack management: credentials and repositories

Revision ID: 032_v2_4_0_git
Revises: 031_v2_2_7_filesystem_storage
Create Date: 2026-01-15

CHANGES IN v2.4.0:
- Add git_credentials table for storing Git authentication credentials
  - Supports HTTPS (username/password) and SSH (private key) authentication
  - All sensitive fields encrypted at rest using existing encryption utility
- Add git_repositories table for defining Git repository sources
  - Supports auto-sync via cron schedule
  - Tracks sync status, last commit, and errors
  - Links to optional credential for authentication

Git-backed stacks feature allows:
- Cloning/pulling repositories on demand or schedule
- Deploying stacks from compose files in git repos
- Auto-redeploy when changes are detected

See docs/plans/git-based-stack-management.md for full design.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '032_v2_4_0_git'
down_revision = '031_v2_2_7_filesystem_storage'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    """Create git_credentials and git_repositories tables"""

    # Create git_credentials table
    if not table_exists('git_credentials'):
        op.create_table(
            'git_credentials',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.String(), nullable=False, unique=True),
            sa.Column('auth_type', sa.String(), nullable=False),  # 'none', 'https', 'ssh'

            # HTTPS authentication (encrypted)
            sa.Column('username', sa.String(), nullable=True),
            sa.Column('password', sa.Text(), nullable=True),  # Fernet-encrypted

            # SSH authentication (encrypted, passphrase-less keys only)
            sa.Column('ssh_private_key', sa.Text(), nullable=True),  # Fernet-encrypted

            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        print("Created git_credentials table")

    # Create git_repositories table
    if not table_exists('git_repositories'):
        op.create_table(
            'git_repositories',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('name', sa.String(), nullable=False, unique=True),
            sa.Column('url', sa.String(), nullable=False),
            sa.Column('branch', sa.String(), nullable=False, server_default='main'),
            sa.Column('credential_id', sa.Integer(),
                      sa.ForeignKey('git_credentials.id', ondelete='SET NULL'),
                      nullable=True),

            # Auto-sync configuration (opt-in, disabled by default)
            sa.Column('auto_sync_enabled', sa.Boolean(), nullable=False, server_default='0'),
            sa.Column('auto_sync_cron', sa.String(), nullable=False, server_default='0 3 * * *'),

            # Sync status tracking
            sa.Column('last_sync_at', sa.DateTime(), nullable=True),
            sa.Column('last_commit', sa.String(40), nullable=True),  # Full SHA for comparison
            sa.Column('sync_status', sa.String(), nullable=False, server_default='pending'),
            sa.Column('sync_error', sa.Text(), nullable=True),

            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        print("Created git_repositories table")

    # Update app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.4.0', id=1)
        )


def downgrade():
    """Drop git tables and revert app_version"""

    # Drop tables in reverse order (due to foreign key)
    if table_exists('git_repositories'):
        op.drop_table('git_repositories')
        print("Dropped git_repositories table")

    if table_exists('git_credentials'):
        op.drop_table('git_credentials')
        print("Dropped git_credentials table")

    # Revert app_version
    if table_exists('global_settings'):
        op.execute(
            sa.text("UPDATE global_settings SET app_version = :version WHERE id = :id")
            .bindparams(version='2.2.7', id=1)
        )
