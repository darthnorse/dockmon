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


def _find_engine_id_unique() -> tuple:
    """Inspect the agents table and return (constraint_name, index_name) for the
    unique-on-engine_id artifact, if any. Both can be None (no constraint and
    no extra unique index) or one of them set depending on the dialect.

    - SQLite: the implicit UNIQUE from `unique=True` reflects as a unique
      *constraint* with name=None; we substitute the convention-supplied
      `uq_agents_engine_id` so batch_alter_table can address it.
    - Postgres: the implicit UNIQUE typically reflects as a *constraint* with
      an auto-generated name like `agents_engine_id_key`. Some versions of
      SQLAlchemy reflect it as a unique *index* of the same name instead;
      we handle both forms.
    The non-unique `idx_agent_engine_id` (created explicitly in v2.2.0) is
    retained — it is excluded from the index path here.
    """
    inspector = sa.inspect(op.get_bind())
    constraint_name = None
    for c in inspector.get_unique_constraints('agents'):
        if c.get('column_names') == ['engine_id']:
            # name may be None (SQLite anonymous constraint) — substitute the
            # convention-supplied name; for Postgres we use the actual name.
            constraint_name = c.get('name') or 'uq_agents_engine_id'
            break
    index_name = None
    for idx in inspector.get_indexes('agents'):
        if (
            idx.get('column_names') == ['engine_id']
            and idx.get('unique')
            and idx.get('name') != 'idx_agent_engine_id'
        ):
            index_name = idx.get('name')
            break
    return constraint_name, index_name


def upgrade():
    constraint_name, index_name = _find_engine_id_unique()

    if not constraint_name and not index_name:
        # Idempotent: re-running on an already-migrated DB, or applying to a
        # fresh DB created directly from current models, has nothing to drop.
        logging.getLogger('alembic.runtime.migration').info(
            "agents.engine_id has no unique constraint or unique index to drop "
            "(already removed, or DB created from current models). Migration is a no-op."
        )
        return

    with op.batch_alter_table('agents', naming_convention=NAMING_CONVENTION) as batch_op:
        if constraint_name:
            batch_op.drop_constraint(constraint_name, type_='unique')
        if index_name:
            batch_op.drop_index(index_name)


def downgrade():
    # Recreate the unique constraint. This will fail if duplicate engine_ids
    # exist (i.e., users are actively using FORCE_UNIQUE_REGISTRATION); they
    # must clean those rows up before downgrading.
    with op.batch_alter_table('agents', naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.create_unique_constraint('uq_agents_engine_id', ['engine_id'])
