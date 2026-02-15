"""v2.2.8 upgrade - Editor theme preference

Revision ID: 032_v2_2_8
Revises: 031_v2_2_7
Create Date: 2026-01-18

CHANGES IN v2.2.8:
- feat: Add YAML syntax highlighting to stack editor (Issue #152)
  - CodeMirror 6 integration for YAML/JSON editing
  - Configurable editor theme preference in Settings
  - Available themes: GitHub Dark, VS Code Dark, Dracula, Material Dark, Nord
- feat: Interactive shell access for containers (PR #148)
  - WebSocket-based terminal using xterm.js
  - Supports both agent-based and direct Docker connections
  - Shell tab in container details modal
- fix: Handle mTLS connections for shell sessions
  - SSLSocket compatibility for TLS Docker connections
- fix: Resolve "latest" tag to actual version for agent self-updates
  - Fetch fresh version from GitHub when updating agents tracking "latest"

SCHEMA CHANGES:
- global_settings: Add editor_theme column (default: 'github-dark')
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '032_v2_2_8'
down_revision = '031_v2_2_7'
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
    """Add editor_theme to global_settings table"""

    # Add editor_theme column to global_settings
    if table_exists('global_settings'):
        if not column_exists('global_settings', 'editor_theme'):
            op.add_column('global_settings', sa.Column('editor_theme', sa.Text(), nullable=True))

            # Set default value for existing row
            op.execute(sa.text("""
                UPDATE global_settings
                SET editor_theme = 'github-dark'
                WHERE editor_theme IS NULL
            """))



def downgrade():
    """Remove editor_theme column"""

    if table_exists('global_settings'):
        if column_exists('global_settings', 'editor_theme'):
            op.drop_column('global_settings', 'editor_theme')
