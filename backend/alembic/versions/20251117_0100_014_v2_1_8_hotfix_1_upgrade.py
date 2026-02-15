"""v2.1.8-hotfix.1 upgrade - Add tag ordering support

Revision ID: 014_v2_1_8_hotfix_1
Revises: 013_v2_1_8
Create Date: 2025-11-17

CHANGES IN v2.1.8-hotfix.1:
- Add order_index column to tag_assignments table
- Enables user-defined tag ordering (fixes host tag reordering bug)
- Populates existing assignments with alphabetical order for upgrade path
- Primary tag is first in ordered list
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision = '014_v2_1_8_hotfix_1'
down_revision = '013_v2_1_8'
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


def upgrade() -> None:
    """Add order_index to tag_assignments for tag ordering"""

    # Add order_index column (nullable initially for safe migration)
    if not column_exists('tag_assignments', 'order_index'):
        op.add_column('tag_assignments',
            sa.Column('order_index', sa.Integer(), nullable=True))

    # Populate order_index for existing assignments
    # Group by subject_type + subject_id, order alphabetically by tag name
    # This ensures no NULL values and smooth upgrade path
    bind = op.get_bind()

    # Get all existing assignments with tag names, ordered alphabetically
    result = bind.execute(text("""
        SELECT ta.tag_id, ta.subject_type, ta.subject_id, t.name
        FROM tag_assignments ta
        JOIN tags t ON ta.tag_id = t.id
        ORDER BY ta.subject_type, ta.subject_id, t.name
    """)).fetchall()

    # Group assignments by subject and assign sequential order_index
    current_subject = None
    order_idx = 0
    updates = []

    for tag_id, subject_type, subject_id, tag_name in result:
        subject_key = (subject_type, subject_id)

        # Reset counter for each new subject
        if subject_key != current_subject:
            current_subject = subject_key
            order_idx = 0

        # Store update for batch execution
        updates.append({
            'tag_id': tag_id,
            'subject_type': subject_type,
            'subject_id': subject_id,
            'order_idx': order_idx
        })

        order_idx += 1

    # Execute batch update (more efficient than individual updates)
    for update in updates:
        bind.execute(text("""
            UPDATE tag_assignments
            SET order_index = :order_idx
            WHERE tag_id = :tag_id
              AND subject_type = :subject_type
              AND subject_id = :subject_id
        """), update)

    # Now make order_index NOT NULL (safe after population)
    # For SQLite, we need to recreate the table (ALTER COLUMN not supported)
    with op.batch_alter_table('tag_assignments') as batch_op:
        batch_op.alter_column('order_index',
                              existing_type=sa.Integer(),
                              nullable=False,
                              server_default='0')



def downgrade() -> None:
    """Remove order_index from tag_assignments"""
    if column_exists('tag_assignments', 'order_index'):
        op.drop_column('tag_assignments', 'order_index')

