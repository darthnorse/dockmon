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
- SQLite: implicit UNIQUE comes from the column declaration; we use
  alembic's batch_alter_table to recreate the table without it.
- Postgres: the implicit UNIQUE has an auto-generated constraint name
  (typically `agents_engine_id_key`); we look it up via inspection
  rather than guessing.
"""
from alembic import op
import sqlalchemy as sa


revision = '038_v2_4_1_drop_agent_engine_id_unique'
down_revision = '037_v2_4_0_stats_persistence'
branch_labels = None
depends_on = None


def _find_engine_id_unique_constraint_name() -> str | None:
    """Locate the engine_id unique constraint via inspection (cross-dialect)."""
    inspector = sa.inspect(op.get_bind())
    for c in inspector.get_unique_constraints('agents'):
        if c.get('column_names') == ['engine_id']:
            return c.get('name')
    return None


def _find_engine_id_unique_index_name() -> str | None:
    """Locate a unique index on engine_id that is NOT idx_agent_engine_id."""
    inspector = sa.inspect(op.get_bind())
    for idx in inspector.get_indexes('agents'):
        if (
            idx.get('column_names') == ['engine_id']
            and idx.get('unique')
            and idx.get('name') != 'idx_agent_engine_id'
        ):
            return idx.get('name')
    return None


def upgrade():
    # Try the named-constraint path first (works on Postgres and named SQLite constraints)
    constraint_name = _find_engine_id_unique_constraint_name()
    if constraint_name:
        with op.batch_alter_table('agents') as batch_op:
            batch_op.drop_constraint(constraint_name, type_='unique')

    # SQLite often expresses the implicit UNIQUE as an auto-named unique INDEX
    # rather than a named constraint, so also drop any unique index on engine_id
    # (excluding the explicit idx_agent_engine_id which we want to keep).
    index_name = _find_engine_id_unique_index_name()
    if index_name:
        with op.batch_alter_table('agents') as batch_op:
            batch_op.drop_index(index_name)


def downgrade():
    # Recreate the unique constraint. This will fail if duplicate engine_ids
    # exist (i.e., users are actively using FORCE_UNIQUE_REGISTRATION); they
    # must clean those rows up before downgrading.
    with op.batch_alter_table('agents') as batch_op:
        batch_op.create_unique_constraint('agents_engine_id_key', ['engine_id'])
