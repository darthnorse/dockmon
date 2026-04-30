"""v2.4.1 upgrade - Drop UNIQUE constraint on agents.engine_id

Revision ID: 038_v2_4_1_drop_agent_engine_id_unique
Revises: 037_v2_4_0_stats_persistence
Create Date: 2026-04-30

CHANGES:
- Drop the implicit UNIQUE constraint on agents.engine_id (originally
  created by the `unique=True` shorthand in the v2.2.0 migration).
- The non-unique index `idx_agent_engine_id` (also created in v2.2.0)
  is retained for query performance on the migration-detection query.
- This unblocks cloned-VM agents that share /var/lib/docker/engine-id
  from registering as distinct hosts when FORCE_UNIQUE_REGISTRATION
  is opted into.

Note on dialects:
- SQLite: the `unique=True` shorthand produces an unnamed UNIQUE clause
  in the table definition. SQLAlchemy's inspector reflects it with
  `name: None`, so we use a `naming_convention` to give it a stable name
  inside `batch_alter_table` and then drop it. The batch operation
  recreates the table without the constraint.
- Postgres: the implicit UNIQUE has an auto-generated constraint name
  (e.g., `agents_engine_id_key`). The same `naming_convention` produces
  a deterministic name for the drop.
"""
import logging

from alembic import op
import sqlalchemy as sa


revision = '038_v2_4_1_drop_agent_engine_id_unique'
down_revision = '037_v2_4_0_stats_persistence'
branch_labels = None
depends_on = None


# Naming convention so reflected anonymous unique constraints become
# `uq_<table>_<column>` inside batch_alter_table — required for SQLite,
# harmless for Postgres.
NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}


def _has_engine_id_unique() -> bool:
    """Return True iff agents.engine_id currently has a unique constraint
    or a separate unique index (excluding the explicit idx_agent_engine_id)."""
    inspector = sa.inspect(op.get_bind())
    for c in inspector.get_unique_constraints('agents'):
        if c.get('column_names') == ['engine_id']:
            return True
    for idx in inspector.get_indexes('agents'):
        if (
            idx.get('column_names') == ['engine_id']
            and idx.get('unique')
            and idx.get('name') != 'idx_agent_engine_id'
        ):
            return True
    return False


def upgrade():
    if not _has_engine_id_unique():
        # Idempotent: re-running on an already-migrated DB, or applying to a
        # fresh DB created directly from current models, has nothing to drop.
        logging.getLogger('alembic.runtime.migration').info(
            "agents.engine_id has no unique constraint or unique index to drop "
            "(already removed, or DB created from current models). Migration is a no-op."
        )
        return

    with op.batch_alter_table('agents', naming_convention=NAMING_CONVENTION) as batch_op:
        # The naming_convention reflects the unnamed UNIQUE on engine_id as
        # `uq_agents_engine_id`, which we can then drop. host_id's UNIQUE
        # constraint is reflected as `uq_agents_host_id` and preserved.
        batch_op.drop_constraint('uq_agents_engine_id', type_='unique')


def downgrade():
    # Recreate the unique constraint. This will fail if duplicate engine_ids
    # exist (i.e., users are actively using FORCE_UNIQUE_REGISTRATION); they
    # must clean those rows up before downgrading.
    with op.batch_alter_table('agents', naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.create_unique_constraint('uq_agents_engine_id', ['engine_id'])
