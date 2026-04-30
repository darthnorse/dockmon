"""v2.4.1 upgrade - Add force_unique column + partial unique index on engine_id

Revision ID: 039_v2_4_1_add_force_unique_partial_index
Revises: 038_v2_4_1_drop_agent_engine_id_unique
Create Date: 2026-04-30

CHANGES:
- Add `agents.force_unique` BOOLEAN column (default false). Records whether
  the agent registered with FORCE_UNIQUE_REGISTRATION=true. Persisted
  per-row so the partial unique index can use it as a predicate.
- Heal any pre-existing duplicate engine_ids by marking all but the first
  registered as `force_unique = true`. In production this is a no-op
  (migration 037 prevented duplicates), but in dev/test environments where
  the constraint may have been dropped while data already had duplicates
  this prevents the partial unique index creation from failing.
- Restore the non-unique `idx_agent_engine_id` performance index if it was
  accidentally dropped by migration 038's batch_alter_table table-recreation.
- Add a PARTIAL UNIQUE INDEX `idx_agent_engine_id_strict` on
  `agents.engine_id WHERE force_unique = false`. This restores
  schema-level uniqueness enforcement for the default registration path,
  closing the TOCTOU window between the application-level read-then-insert
  introduced when migration 038 dropped the unconditional UNIQUE
  constraint. Forced (cloned-VM) registrations are exempt and can share
  engine_ids freely.

Both SQLite (>= 3.8.0) and Postgres support partial indexes
(`CREATE UNIQUE INDEX ... WHERE ...`).
"""
from alembic import op
import sqlalchemy as sa


revision = '039_v2_4_1_add_force_unique_partial_index'
down_revision = '038_v2_4_1_drop_agent_engine_id_unique'
branch_labels = None
depends_on = None


PARTIAL_INDEX_NAME = 'idx_agent_engine_id_strict'
NON_UNIQUE_INDEX_NAME = 'idx_agent_engine_id'


def _get_inspector():
    return sa.inspect(op.get_bind())


def _column_exists(table_name: str, column_name: str) -> bool:
    return column_name in {c['name'] for c in _get_inspector().get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    return any(idx['name'] == index_name for idx in _get_inspector().get_indexes(table_name))


def upgrade():
    # 1. Add the column (default false preserves existing rows' semantics).
    if not _column_exists('agents', 'force_unique'):
        op.add_column(
            'agents',
            sa.Column(
                'force_unique',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # 2. Heal any pre-existing duplicate engine_ids: mark all but the first
    #    registered as force_unique=true so they don't violate the partial
    #    unique index we're about to create. Production users won't hit this
    #    (migration 037 prevented duplicates); dev/test envs might.
    op.execute(sa.text(
        """
        UPDATE agents
        SET force_unique = 1
        WHERE id IN (
            SELECT a.id FROM agents a
            INNER JOIN (
                SELECT engine_id, MIN(registered_at) AS first_at
                FROM agents
                GROUP BY engine_id
                HAVING COUNT(*) > 1
            ) dups
              ON a.engine_id = dups.engine_id
              AND a.registered_at > dups.first_at
        )
        """
    ))

    # 3. Restore the non-unique performance index if it was accidentally dropped
    #    by migration 038's batch_alter_table table-recreation. Idempotent.
    if not _index_exists('agents', NON_UNIQUE_INDEX_NAME):
        op.create_index(NON_UNIQUE_INDEX_NAME, 'agents', ['engine_id'])

    # 4. Partial unique index: enforce engine_id uniqueness only for rows
    #    that did NOT opt into FORCE_UNIQUE_REGISTRATION. Rows with
    #    force_unique=true (cloned-VM agents) are explicitly allowed to
    #    duplicate engine_ids.
    if not _index_exists('agents', PARTIAL_INDEX_NAME):
        op.create_index(
            PARTIAL_INDEX_NAME,
            'agents',
            ['engine_id'],
            unique=True,
            sqlite_where=sa.text('force_unique = 0'),
            postgresql_where=sa.text('force_unique = false'),
        )


def downgrade():
    if _index_exists('agents', PARTIAL_INDEX_NAME):
        op.drop_index(PARTIAL_INDEX_NAME, 'agents')
    # Leave NON_UNIQUE_INDEX_NAME in place — it predates this migration on a
    # well-applied 037→038 chain, so dropping it would over-correct.
    if _column_exists('agents', 'force_unique'):
        op.drop_column('agents', 'force_unique')
