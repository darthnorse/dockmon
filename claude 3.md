# 🚨 DOCKMON DEVELOPMENT GUIDELINES

## PRE-IMPLEMENTATION CHECKLIST (MANDATORY)

**BEFORE writing ANY code for non-trivial features, complete this checklist and present to user:**

### 1. Requirements Analysis
- [ ] What changes in the system? (state, database records, files, containers, etc.)
- [ ] What is the expected behavior on success?
- [ ] What is the expected behavior on failure?
- [ ] What needs to be rolled back if operation fails?

### 2. CRUD Analysis (Database Operations)
- [ ] What records are **Created**?
- [ ] What records are **Read**?
- [ ] What records are **Updated**? (List ALL fields that change)
- [ ] What records are **Deleted**?
- [ ] **CRITICAL**: When entities are recreated (containers, etc.), does the database ID need updating?

### 3. State Flow Analysis
- [ ] Document success path: What state changes occur? In what order?
- [ ] Document failure paths: For each failure point, what state are we in?
- [ ] Document rollback logic: What gets rolled back? What stays committed?
- [ ] Identify commitment points: After what operation is the change "done"?

### 4. Database Consistency Check
- [ ] If a Docker container is recreated, does it get a new ID? → Database MUST update
- [ ] If a file is renamed/moved, do database paths need updating?
- [ ] Are composite keys maintained correctly?
- [ ] Will any records become orphaned?

### 5. API Data Flow Validation (CRITICAL - Prevents Most Common Bugs)
**For any feature that stores user preferences or state:**
- [ ] **Write Path**: Identify ALL endpoints that WRITE data (POST/PUT/PATCH)
- [ ] **Read Path**: Identify ALL endpoints that READ data (GET)
- [ ] **Data Completeness**: Does the GET endpoint return ALL fields that the frontend needs?
- [ ] **Round Trip Test**: Can the frontend GET data, modify it, POST it back, and GET it again with the same values?

**Common Bug Pattern to Avoid:**
```
❌ WRONG: POST endpoint saves data, but GET endpoint doesn't return it
- Frontend POSTs dismissed_version
- Frontend GETs settings (missing dismissed_version)
- Frontend reloads → data lost!

✅ CORRECT: POST and GET are symmetric
- Frontend POSTs dismissed_version
- Frontend GETs settings (includes dismissed_version)
- Frontend reloads → data persists!
```

**Validation Questions:**
- [ ] If user refreshes page, will their action persist?
- [ ] Are we using local state when we should fetch from backend?
- [ ] Does the GET endpoint include user-specific data when needed?
- [ ] Have we tested the full round-trip: GET → modify → POST → GET?

### 6. Standards Acknowledgment
- [ ] Confirm SHORT IDs (12 chars) will be used everywhere
- [ ] Confirm composite keys `{host_id}:{container_id}` will be used
- [ ] Confirm async wrappers will be used for all Docker SDK calls
- [ ] Confirm timestamps will have 'Z' suffix for frontend

### 7. Test-Driven Development (TDD) Plan (MANDATORY)
**TDD is non-negotiable for ALL non-trivial features going forward.**

**Requirements:**
- [ ] Write FAILING tests FIRST (RED phase)
- [ ] Implement code to make tests pass (GREEN phase)
- [ ] Refactor for quality (REFACTOR phase)
- [ ] Tests cover happy path + edge cases + failure scenarios
- [ ] Backend: Unit tests (pytest) + Integration tests where appropriate
- [ ] Frontend: Playwright E2E tests for user flows

**Test Plan Format:**
```
## Test Plan (RED Phase)

**Backend Tests:**
- Test file: backend/tests/unit/test_feature.py
- Test cases: [list each test case]
- Expected: All tests FAIL (feature not implemented yet)

**Frontend Tests:**
- Test file: ui/tests/e2e/feature.spec.ts
- Test cases: [list each test case]
- Expected: All tests FAIL (feature not implemented yet)

**After RED phase:** Implement code to achieve GREEN phase
```

### 8. Present Plan to User
**Format:**
```
## Implementation Plan

**What changes:** [List all state/database/file changes]

**CRUD Operations:**
- Create: [...]
- Read: [...]
- Update: [fields that change]
- Delete: [...]

**State Flow:**
1. Success: [step by step with state changes]
2. Failure: [what gets rolled back]

**Database Consistency:**
- [Explain how DB stays consistent with reality]

**TDD Approach:**
- RED: Write failing tests [list test files]
- GREEN: Implement feature to pass tests
- REFACTOR: Clean up code

**Awaiting approval to proceed.**
```

**DO NOT start coding until user approves the plan.**

---

# 🚨 CRITICAL ARCHITECTURAL RULES

## Container ID Format Standards
- **ALWAYS use SHORT container IDs (12 characters)** - Never use full 64-char IDs
- Docker containers have TWO ID formats:
  - SHORT ID: 12 characters (e.g., `67c5d2141338`) - **USE THIS EVERYWHERE**
  - FULL ID: 64 characters (e.g., `67c5d214133846c397f4d9947f28cb513377db1fcc74633efd0d13793c45d4f2`) - **NEVER USE**
- When extracting from Docker API: `dc.id[:12]` or use `container.short_id`
- When extracting from Go service events: Already truncated to 12 chars in event_manager.go
- Container model `id` field MUST be SHORT ID (12 chars)
- Frontend sends/receives SHORT IDs via `container.id`
- **This is a recurring issue - if you see FULL IDs anywhere, stop and fix immediately**

## Composite Keys (Multi-Host Operations)
- **ALWAYS use composite keys** for any container-related storage/lookups to prevent collisions with cloned VMs
- Format: `f"{host_id}:{container_id}"` where:
  - `host_id`: FULL UUID (e.g., `7be442c9-24bc-4047-b33a-41bbf51ea2f9`)
  - `container_id`: SHORT ID (12 chars, e.g., `67c5d2141338`)
- Use composite keys for:
  - Database storage (tags, auto-restart configs, desired states)
  - In-memory caches (state tracking, restart attempts, restarting containers)
  - Stats/sparkline lookups
  - Event tracking
- Example: `container_key = f"{container.host_id}:{container.short_id}"`
- **NEVER** use just `container_id` alone for multi-host operations

## Database Consistency (CRITICAL)

### Container Recreation Rules
**When a Docker container is recreated (stopped + removed + created), it gets a NEW Docker ID.**

**Database MUST be updated:**
```python
# WRONG - Database becomes orphaned
old_container.stop()
old_container.remove()
new_container = client.containers.create(...)  # Gets NEW ID
# Database still has old container ID → BROKEN

# CORRECT - Update database with new ID
old_composite_key = f"{host_id}:{old_container_id}"
new_container = client.containers.create(...)
new_composite_key = f"{host_id}:{new_container.short_id}"
record.container_id = new_composite_key  # Update to new ID
session.commit()
```

**Critical Database Rules:**
- Container recreated → Update `container_id` field in ALL related tables
- File renamed/moved → Update all path references
- Entity deleted → Cascade delete or set null on foreign keys
- Every physical change MUST have database equivalent
- Use transactions: Commit only when physical state matches DB state

## Database Migrations (Rock-Solid Strategy)

### Migration Naming Convention (Version-Aligned)
**ALWAYS use version-aligned naming** - makes it impossible to forget what changed in each release.

**Pattern:**
```
backend/alembic/versions/YYYYMMDD_HHMM_XXX_vMAJOR_MINOR_PATCH_upgrade.py
```

**Examples:**
```
20251017_1200_001_v2_0_0_upgrade.py    # v2.0.0 changes
20251022_1200_002_v2_0_1_upgrade.py    # v2.0.1 changes
20251123_1200_003_v2_0_2_upgrade.py    # v2.0.2 changes
```

**Inside migration file:**
```python
"""v2.0.1 upgrade - Brief description

Revision ID: 002_v2_0_1
Revises: 001_v2_0_0
Create Date: 2025-10-22

CHANGES IN v2.0.1:
- Add changelog_url column to container_updates
- Add changelog_source column to container_updates
- Add changelog_checked_at column to container_updates
"""

# revision identifiers, used by Alembic.
revision = '002_v2_0_1'
down_revision = '001_v2_0_0'
branch_labels = None
depends_on = None
```

### Migration Strategy: Self-Contained Migrations

**Philosophy: Migrations are SOURCE OF TRUTH for schema evolution**

Every migration file explicitly defines ALL changes for that version. This makes migrations:
- **Self-documenting** - Read the file to know exactly what changed
- **Testable** - Each migration can be tested independently
- **Debuggable** - No hidden dependencies on models

**The system uses SEPARATE paths for fresh installs and upgrades:**

1. **Fresh Install Path:**
   - No `alembic_version` table exists
   - `Base.metadata.create_all()` creates all tables with latest schema (uses models in database.py)
   - Database stamped as HEAD (no migrations run)
   - Fast, clean, production-ready
   - **Validation**: Schema must match what migrations would create

2. **V1 Upgrade Path:**
   - Has `global_settings` table but no `app_version` column (v1.1.3 indicator)
   - Backup created automatically
   - Migrations run sequentially: 001 → 002 → 003 → HEAD
   - Each migration explicitly creates new tables and alters existing ones
   - Schema validation after migrations
   - Cleanup of legacy v1 tables

3. **V2+ Upgrade Path:**
   - `alembic_version` table exists
   - Compare current version vs HEAD
   - If current == HEAD → skip (idempotent)
   - If current < HEAD → backup → migrate → validate → cleanup
   - Automatic backup created before migrations
   - Schema validation after migrations

**Key Files:**
- `backend/migrate.py` - Migration orchestration (runs at container startup)
- `backend/alembic/versions/*.py` - Individual migration files (self-contained)
- `backend/database.py` - Current schema models (for fresh installs)

### How to Add New Migrations (e.g., v2.0.2)

**Step 1: Create migration file (self-contained)**
```bash
# File: backend/alembic/versions/20251123_1200_003_v2_0_2_upgrade.py

"""v2.0.2 upgrade - Backup configurations

Revision ID: 003_v2_0_2
Revises: 002_v2_0_1
Create Date: 2025-11-23

CHANGES IN v2.0.2:
- Create backup_configs table (NEW TABLE)
- Add last_backup_at column to container_updates
- Add performance index on event_logs.created_at
- Update app_version to '2.0.2'
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

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

    # Change 1: Create backup_configs table (EXPLICITLY)
    # Do NOT rely on Base.metadata.create_all() - migrations must be self-contained
    if not table_exists('backup_configs'):
        op.create_table(
            'backup_configs',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('container_id', sa.Text(), nullable=False, unique=True),
            sa.Column('host_id', sa.Text(), sa.ForeignKey('docker_hosts.id', ondelete='CASCADE'), nullable=False),
            sa.Column('enabled', sa.Boolean(), server_default='0', nullable=False),
            sa.Column('schedule_cron', sa.Text(), nullable=True),
            sa.Column('retention_days', sa.Integer(), server_default='7'),
            sa.Column('backup_path', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )

    # Change 2: Add last_backup_at column to existing table
    if not column_exists('container_updates', 'last_backup_at'):
        op.add_column('container_updates',
            sa.Column('last_backup_at', sa.DateTime(), nullable=True))

    # Change 3: Add performance index
    if not table_exists('event_logs'):
        # Table doesn't exist, skip index creation
        pass
    else:
        # Check if index already exists before creating
        bind = op.get_bind()
        inspector = inspect(bind)
        indexes = [idx['name'] for idx in inspector.get_indexes('event_logs')]
        if 'idx_event_logs_created_at' not in indexes:
            op.create_index('idx_event_logs_created_at', 'event_logs', ['created_at'])

    # Change 4: Update app_version
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
    op.drop_index('idx_event_logs_created_at', 'event_logs')
    op.drop_column('container_updates', 'last_backup_at')
    op.drop_table('backup_configs')
```

**Step 2: Add validation rules to migrate.py**
```python
# In backend/migrate.py, function _validate_schema():

validations = {
    '001_v2_0_0': {
        'tables': ['containers', 'container_updates', 'docker_hosts', 'event_logs'],
    },
    '002_v2_0_1': {
        'container_updates_columns': ['changelog_url', 'changelog_source', 'changelog_checked_at'],
    },
    '003_v2_0_2': {  # ADD THIS
        'tables': ['backup_configs'],
        'container_updates_columns': ['last_backup_at'],
    },
}
```

**Step 3: Update database.py models**
```python
# Add new columns/tables to SQLAlchemy models
class ContainerUpdate(Base):
    # ... existing columns ...
    last_backup_at = Column(DateTime, nullable=True)  # NEW
```

**Step 4: Test migration paths**
- Fresh install v2.0.2
- Upgrade v2.0.0 → v2.0.2 (applies 002 + 003)
- Upgrade v2.0.1 → v2.0.2 (applies 003 only)
- Container restart (should be instant)

### Migration Rules (CRITICAL)

1. **Migrations are self-contained** - Explicitly create ALL new tables with `op.create_table()`, don't rely on `Base.metadata.create_all()`
2. **One migration file per version release** - Bundle all changes for a version in one file
3. **Defensive checks** - Always use `column_exists()`, `table_exists()` checks before adding/creating
4. **Idempotent** - Migrations must be safe to run multiple times
5. **Schema validation** - Add rules to `_validate_schema()` in migrate.py for EVERY migration
6. **No destructive operations** - Never drop tables/columns without user consent
7. **Test all upgrade paths** - v1.1.3→latest, v2.0.0→latest, v2.0.1→latest, fresh install
8. **Update app_version** - ALWAYS update `global_settings.app_version` to match the migration version

### Preventing Schema Drift

**Schema drift** occurs when fresh installs (via `Base.metadata.create_all()`) create different schemas than migrations produce.

**Prevention Strategy:**

1. **Schema Validation Catches Drift:**
   - Both fresh install and upgrade paths run `_validate_schema()`
   - If fresh install creates different schema than migrations, validation FAILS immediately
   - This is your safety net

2. **When Changing Models in database.py:**
   ```python
   # MANDATORY WORKFLOW:
   # 1. Update the model in database.py
   # 2. Create a new migration that makes the SAME change
   # 3. Update _validate_schema() to check for the change
   # 4. Test BOTH fresh install AND upgrade paths
   ```

3. **Example - Adding a new column:**
   ```python
   # Step 1: Update database.py
   class ContainerUpdate(Base):
       # ... existing columns ...
       backup_enabled = Column(Boolean, default=False)  # NEW

   # Step 2: Create migration 003_v2_0_2 that adds the column
   def upgrade():
       if not column_exists('container_updates', 'backup_enabled'):
           op.add_column('container_updates',
               sa.Column('backup_enabled', sa.Boolean(), server_default='0'))

   # Step 3: Update _validate_schema()
   validations = {
       '003_v2_0_2': {
           'container_updates_columns': ['backup_enabled'],
       },
   }

   # Step 4: Test both paths
   # - Fresh install: create_all() → validation passes
   # - Upgrade: migration adds column → validation passes
   ```

4. **Validation Equality:**
   - Fresh install schema MUST equal final migration schema
   - Same tables, same columns, same indexes, same foreign keys
   - If they differ, `_validate_schema()` fails and blocks startup

5. **Trust the Validation:**
   - If validation passes for BOTH fresh install and upgrade, schema is consistent
   - No need to manually compare schemas
   - Validation is your automated guarantee

### Migration Testing Checklist

**Before releasing a version with schema changes:**
- [ ] Fresh install creates all tables correctly
- [ ] Fresh install stamps correct revision ID
- [ ] Previous version → new version upgrade succeeds
- [ ] Container restart is instant (idempotent check works)
- [ ] Backup created before migration
- [ ] Schema validation passes
- [ ] All defensive checks work (`column_exists`, etc.)
- [ ] Alembic revision chain is correct (`revision` → `down_revision`)

### Upgrade Path Examples

**v2.0.0 → v2.0.1:**
```
1. detect: alembic_version exists (upgrade path)
2. current: 001_v2_0_0, HEAD: 002_v2_0_1
3. backup: dockmon.db.backup-001_v2_0_0-to-002_v2_0_1
4. apply: 002_v2_0_1_upgrade.py
5. validate: changelog columns exist
6. cleanup: remove backup
```

**v2.0.0 → v2.0.2 (skipping v2.0.1):**
```
1. detect: alembic_version exists
2. current: 001_v2_0_0, HEAD: 003_v2_0_2
3. backup: dockmon.db.backup-001_v2_0_0-to-003_v2_0_2
4. apply: 002_v2_0_1_upgrade.py, then 003_v2_0_2_upgrade.py
5. validate: all columns exist
6. cleanup: remove backup
```

**Fresh install v2.0.2:**
```
1. detect: no alembic_version (fresh install path)
2. Base.metadata.create_all() - creates all tables at once
3. stamp: 003_v2_0_2 (no migrations run)
4. validate: all tables/columns exist
```

### Common Migration Issues

**Issue: Migration runs but columns missing**
- **Cause:** Forgot defensive check, column creation skipped
- **Fix:** Add `if not column_exists(...)` wrapper

**Issue: Fresh install fails with "column already exists"**
- **Cause:** Migration tries to add column that `create_all()` already created
- **Fix:** Add defensive check in migration

**Issue: Upgrade skipped even though new migration exists**
- **Cause:** Old idempotency bug (fixed in current migrate.py)
- **Solution:** Current code compares current vs HEAD correctly

**Issue: Container won't start after failed migration**
- **Cause:** Schema validation failed
- **Recovery:** Restore backup: `docker cp dockmon.db.backup-* dockmon:/app/data/dockmon.db`

## State Management Rules

### State Tracking
- **Identify all state types**: Code state, database state, container state, file state
- **Every state change must be consistent**: If container gets new ID, database MUST update
- **Track commitment points**: Know when an operation is "done" and can't be rolled back
- **Exception handlers must check state**: Don't rollback if already committed to database

### Commitment Point Pattern
```python
# Track whether the operation has been committed
operation_committed = False

try:
    # ... do work ...

    # Commit to database = commitment point
    session.commit()
    operation_committed = True  # Mark as committed

    # ... post-commit operations (logging, cleanup, etc.) ...

except Exception as e:
    # Check if we committed before failing
    if operation_committed:
        # DO NOT ROLLBACK - operation succeeded
        # Just log the post-commit failure
        logger.error(f"Operation succeeded but post-commit ops failed: {e}")
    else:
        # Safe to rollback - operation never committed
        rollback_operation()
```

### State Logging
- Log state transitions: `logger.debug(f"State: {old_state} → {new_state}")`
- Log commitment points: `logger.debug("Operation committed to database")`
- Log rollback decisions: `logger.warning("Rolling back - operation not committed")`

---

# MANDATORY SELF-REVIEW PROTOCOL

**After implementing ANY feature, complete this checklist BEFORE claiming "production ready".**

**For each checklist item, show your work by citing line numbers.**

## Database Review
- [ ] **Traced every CRUD operation**: List each Create/Read/Update/Delete with line numbers
- [ ] **Verified all IDs are updated when entities recreate**: Cite where container ID is updated after recreation
- [ ] **Checked for orphaned records**: Confirm database stays consistent with physical state
- [ ] **Confirmed composite keys are consistent**: All multi-host operations use `{host_id}:{container_id}`

## State Flow Review
- [ ] **Traced success path**: Document each state change with line numbers
- [ ] **Traced each failure path**: For each failure point, document what state we're in
- [ ] **Verified rollback doesn't destroy committed changes**: Cite commitment point check in exception handler
- [ ] **Checked exception handlers respect commitment points**: Show where `operation_committed` flag is checked

## Standards Review
- [ ] **All container IDs are SHORT (12 chars)**: List all container ID usages, confirm `.short_id` or `[:12]`
- [ ] **All Docker calls use async_docker_call()**: List all Docker SDK calls, confirm wrapped
- [ ] **All composite keys use {host_id}:{container_id} format**: List all composite key constructions
- [ ] **All timestamps have 'Z' suffix for frontend**: List all timestamp returns to frontend

## API Data Flow Review (CRITICAL)
**For any feature that involves user preferences or state:**
- [ ] **List ALL write endpoints**: Document every POST/PUT/PATCH with file:line
- [ ] **List ALL read endpoints**: Document every GET that returns related data with file:line
- [ ] **Verify data symmetry**: Confirm GET returns ALL fields that POST/PUT writes
- [ ] **Test persistence**: Describe what happens if user does action → refresh page
- [ ] **Check local state usage**: Confirm no local-only state that should persist

**Example verification format:**
```
WRITE: POST /api/user/dismiss-dockmon-update (main.py:2884)
  - Writes: dismissed_dockmon_update_version

READ: GET /api/settings (main.py:1592)
  - Returns: dismissed_dockmon_update_version ✓

PERSISTENCE TEST: User dismisses update → page refresh → banner stays dismissed ✓
```

## Edge Cases Analysis
- [ ] **What if operation succeeds but logging fails?** Document behavior
- [ ] **What if database commits but event emission fails?** Document behavior (no rollback!)
- [ ] **What if network fails mid-operation?** Document cleanup/recovery
- [ ] **What if backup creation fails?** Document error handling and alerts
- [ ] **Every early return/abort: Is event emitted?** List all early returns, verify event emission (UPDATE_FAILED, etc.)
- [ ] **Every early return/abort: Are users notified?** Verify alerts will fire for all failure scenarios

## Memory & Resource Review
- [ ] **No memory leaks**: Confirm all resources cleaned up (containers, files, connections)
- [ ] **No stale connections**: Docker clients managed properly
- [ ] **Set cleanup in finally blocks**: Cite line numbers of cleanup code
- [ ] **Database sessions scoped properly**: Confirm context managers used

## Code Quality Review
- [ ] **No duplicate code**: Reusable functions for repeated logic
- [ ] **No dead code**: Removed unused imports, variables, functions
- [ ] **No hacky workarounds**: Production-quality implementation
- [ ] **Clear error messages**: Include context for debugging
- [ ] **Docstrings updated**: All class/method docstrings reflect actual behavior (not outdated)
- [ ] **Workflow documentation updated**: If process changed, update docstring workflow steps

**Only after ALL boxes checked and work shown: claim "production ready"**

---

# CODE STANDARDS

## General Principles
- Be sure to typecheck when you're done making a series of code changes
- Always use industry best practices
- Never duplicate code, if there is functionality used multiple times, make this a reusable function
- Make sure memory management is rock solid. Pay extra attention to memory leaks and stale connections
- Check for async/await issues
- Limit file sizes to around 800-900 lines of code, after that split things out
- Follow DRY principles
- Follow CRUD principles
- Don't check in code to Github until user gives specific instructions to do so
- Screenshots are always put in the folder /Users/patrikrunald/Documents/temp
- **NEVER use emojis in code** - No emojis in log messages, comments, docstrings, or any code output (professional tone only)

## Code Quality Philosophy
- **NEVER use hacky solutions or workarounds** - always implement the correct, scalable solution
- When faced with a choice between a quick hack and proper architecture, ALWAYS choose proper architecture
- Code must be production-ready: clean, maintainable, performant, and scalable
- If user asks for something multiple times, it means you didn't do it properly the first time
- **Do comprehensive reviews, not incremental fixes** - find ALL instances of an issue, not just the obvious ones

## Python Import Standards
- **ALWAYS place imports at the top of the file** (PEP 8 standard)
- Never use local imports inside functions unless there's a specific technical reason
- Makes dependencies explicit and visible
- Better IDE support, linting, and refactoring

**Valid reasons for local imports (rare):**
1. Breaking circular import dependencies
2. Lazy loading heavy/expensive modules (pandas, numpy) in rarely-called functions
3. Optional dependencies with try/except patterns
4. Dynamic plugin systems

❌ **WRONG**: Local import without technical justification
```python
def my_endpoint():
    from database import SomeModel  # No reason for this to be local
    # ... use SomeModel ...
```

✅ **CORRECT**: Import at top of file
```python
# At top of file
from database import SomeModel

def my_endpoint():
    # ... use SomeModel ...
```

**Performance note:** Local imports add overhead on every function call (dictionary lookup), while top-level imports happen once at module load time.

## Timestamp Formatting Standards
- **ALWAYS append 'Z' to `.isoformat()` when returning timestamps to frontend**
- Pattern: `datetime_obj.isoformat() + 'Z'` (indicates UTC timezone)
- Why: SQLite stores naive datetimes (no timezone info), but frontend needs UTC indicator for proper local timezone conversion
- Example: `"last_checked_at": dt.isoformat() + 'Z' if dt else None`
- Applies to: All API endpoints, WebSocket messages, and any data sent to frontend
- Exception: Internal database JSON state storage (parsed back with `fromisoformat()`) doesn't need 'Z'
- **This is a recurring issue** - timestamps without 'Z' will display in UTC instead of converting to browser's local timezone

## TypeScript Standards
- Strict TypeScript with zero `any` tolerance
- NEVER use browser `alert()`, `confirm()`, or `prompt()` - always use custom in-app dialogs/modals

---

# WORKFLOW & DEPLOYMENT

## Testing
- Prefer running single tests, not the whole test suite, for performance

## Frontend Deployment (Fast - No Rebuild)
1. `npm --prefix ui run type-check` - verify TypeScript
2. `npm --prefix ui run build` - build production bundle
3. `DOCKER_HOST= docker cp ui/dist/. dockmon:/usr/share/nginx/html/` - hot deploy to running container

This avoids slow container rebuilds and deploys changes instantly

## Backend Deployment
- When updating .py files it's enough to copy the files into the container and do a restart without --no-cache
- Example: `DOCKER_HOST= docker cp backend/main.py dockmon:/app/backend/main.py && DOCKER_HOST= docker restart dockmon`

---

# STARTUP CHECKLIST

When starting a new session:

1. **Read this CLAUDE.md file completely** (you're doing it now!)
2. Familiarize yourself with the DockMon v2 codebase
3. Understand the architecture and features
4. **Before making any changes involving container IDs, re-read the Container ID Format Standards section**
5. **Before implementing any feature, complete the Pre-Implementation Checklist**
6. **After implementing any feature, complete the Mandatory Self-Review Protocol**

---

# COMMON PITFALLS & REMINDERS

## Database Consistency Failures
❌ **WRONG**: Container recreated but database not updated
```python
new_container = client.containers.create(...)
# Database still has old ID → BROKEN
```

✅ **CORRECT**: Update database with new container ID
```python
new_container = client.containers.create(...)
record.container_id = f"{host_id}:{new_container.short_id}"
session.commit()
```

## Rollback After Commitment
❌ **WRONG**: Rollback after database commit
```python
session.commit()  # Committed!
# ... some post-commit operation fails ...
rollback()  # Destroys committed state!
```

✅ **CORRECT**: Check commitment state before rollback
```python
operation_committed = False
session.commit()
operation_committed = True
# ... exception occurs ...
if not operation_committed:
    rollback()  # Safe - not committed yet
```

## Container ID Format
❌ **WRONG**: Using full 64-char ID
```python
container_id = container.id  # 64 chars
```

✅ **CORRECT**: Using short 12-char ID
```python
container_id = container.short_id  # 12 chars
# or
container_id = container.id[:12]
```

## Async/Await with Docker SDK
❌ **WRONG**: Blocking Docker call in async function
```python
async def update_container():
    container = client.containers.get(id)  # Blocks event loop!
```

✅ **CORRECT**: Async wrapper for Docker SDK
```python
async def update_container():
    container = await async_docker_call(client.containers.get, id)
```

## Local Imports (Anti-Pattern)
❌ **WRONG**: Importing inside functions without technical reason
```python
def my_endpoint():
    from database import SomeModel  # Unnecessary local import
    return session.query(SomeModel).all()
```

✅ **CORRECT**: Import at top of file (PEP 8)
```python
# At top of file with other imports
from database import SomeModel

def my_endpoint():
    return session.query(SomeModel).all()
```

**Why this matters:**
- Local imports run on every function call (overhead)
- Top-level imports run once at module load
- Makes dependencies visible and explicit
- Better IDE/linting support

---

# WORKFLOW & DEPLOYMENT

## Test-Driven Development (TDD) - MANDATORY

**TDD is non-negotiable for ALL non-trivial features going forward.**

### TDD Workflow: RED → GREEN → REFACTOR

**1. RED Phase: Write Failing Tests First**
- Write tests that describe desired behavior
- All tests should FAIL (feature not implemented yet)
- Tests verify: happy path + edge cases + error handling
- Backend: pytest unit tests + integration tests where needed
- Frontend: Playwright E2E tests for user flows

**2. GREEN Phase: Implement Code**
- Write minimal code to make tests pass
- Focus on functionality, not perfection
- All tests should now PASS

**3. REFACTOR Phase: Clean Up**
- Improve code quality while keeping tests green
- Extract duplicated logic
- Improve naming and structure
- Ensure production-ready quality

### Test Structure

**Backend Tests (pytest):**
```
backend/tests/
├── unit/               # Fast, isolated tests
│   └── test_feature.py
├── integration/        # Tests with database, external services
│   └── test_feature_integration.py
└── performance/        # Load and stress tests
    └── test_feature_performance.py
```

**Frontend Tests (Playwright):**
```
ui/tests/
├── e2e/                # End-to-end user flows
│   └── feature.spec.ts
└── fixtures/           # Reusable test data and helpers
    └── feature.ts
```

### Example TDD Workflow

```
FEATURE: Save deployment as template

RED PHASE:
1. Write test: test_save_deployment_as_template_success()
2. Write test: test_save_deployment_as_template_duplicate_name()
3. Write E2E: "User clicks Save as Template, template appears in list"
4. Run tests → ALL FAIL ✓

GREEN PHASE:
1. Implement POST /api/deployments/{id}/save-as-template endpoint
2. Implement SaveAsTemplateDialog component
3. Add button to DeploymentsPage
4. Run tests → ALL PASS ✓

REFACTOR PHASE:
1. Extract duplicate validation logic
2. Improve error messages
3. Add JSDoc comments
4. Run tests → ALL STILL PASS ✓
```

### Testing Checklist

**Before claiming "feature complete":**
- [ ] RED phase: All tests written and failing
- [ ] GREEN phase: All tests passing
- [ ] REFACTOR phase: Code clean and production-ready
- [ ] Happy path covered
- [ ] Edge cases covered (empty inputs, invalid data, etc.)
- [ ] Error handling covered (network errors, validation failures, etc.)
- [ ] E2E tests verify user workflows
- [ ] Tests are fast (unit tests < 100ms each)
- [ ] Tests are reliable (no flaky tests)
- Always refer to CLAUDE.MD before doing code changes to ensure a plan is created and TDD is followed