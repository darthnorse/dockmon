"""v2.5.x upgrade - clear update state left by the registry-identity bugs

Revision ID: 048_registry_leak_cleanup
Revises: 047_backup_schedule
Create Date: 2026-11-06

CHANGES:
- container_updates: clear the update target on rows whose latest_image was computed
  from an untagged registry-with-port ref in latest mode (registry:5000/app became
  registry:latest). An update would otherwise pull that image from Docker Hub. The
  tracking mode is not checked because it can change after the row was written.
- image_digest_cache: delete all rows, because lookalike registries cached Docker Hub
  digests under their own keys. Refilled by the next check.

Data only. The next successful check recomputes everything cleared here.
"""
from alembic import op
import sqlalchemy as sa

revision = '048_registry_leak_cleanup'
down_revision = '047_backup_schedule'
branch_labels = None
depends_on = None


def table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if table_exists('container_updates'):
        op.execute("""
            UPDATE container_updates
            SET update_available = 0, latest_image = NULL, latest_digest = NULL, latest_version = NULL
            WHERE instr(current_image, '/') > 0
              AND instr(substr(current_image, 1, instr(current_image, '/') - 1), ':') > 0
              AND instr(substr(current_image, instr(current_image, '/')), ':') = 0
              AND latest_image IS NOT NULL
              AND instr(latest_image, '/') = 0
        """)
    if table_exists('image_digest_cache'):
        op.execute("DELETE FROM image_digest_cache")


def downgrade():
    pass
