# Migration Loop Fix for v2.0.1 → v2.1.0 Upgrade

## Problem Summary

When upgrading from v2.0.1 to v2.1.0, the migration enters an infinite loop:
- Migration runs upgrade from `004_v2_0_3` → `005_v2_1_0`
- Migration appears to complete but version stays at `004_v2_0_3`
- Container restarts and tries migration again
- Loop repeats every ~600ms

## Root Cause

The v2.1.0 migration was failing silently and rolling back the transaction, but Alembic wasn't reporting the error. The most likely cause is:

1. **Foreign key constraint violation** - deployments table references `users.id`
2. **CHECK constraint issues** - New constraints may be incompatible with existing data
3. **Index creation failures** - Duplicate indexes or naming conflicts

## Changes Made

### 1. Enhanced migrate.py (backend/migrate.py)

Added explicit version verification after migration:

```python
# After command.upgrade(alembic_cfg, "head")
final_version = _get_current_version(engine)
logger.info(f"After upgrade, database version: {final_version}")

if final_version != head_version:
    raise RuntimeError(
        f"Migration appeared to succeed but version not updated! "
        f"Expected {head_version}, got {final_version}. "
        f"This usually means the migration rolled back due to a constraint violation or error."
    )
```

This will catch silent rollbacks and provide a clear error message.

### 2. Enhanced v2.1.0 Migration (backend/alembic/versions/20251025_1200_005_v2_1_0_upgrade.py)

Added comprehensive logging throughout the migration:

- Logs prerequisite table checks (docker_hosts, users, global_settings)
- Logs each table creation step
- Logs index creation
- Logs constraint additions
- Logs app_version update

This will show exactly which step is failing.

## Deployment Instructions

### Option 1: Rebuild Container (Recommended)

```bash
# Stop the running container
docker stop dockmon

# Remove old container
docker rm dockmon

# Rebuild the image with fixes
docker build -t dockmon:latest -f docker/Dockerfile .

# Start fresh container (your database will be preserved in the volume)
docker run -d \
  --name dockmon \
  -p 443:443 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v dockmon-data:/app/data \
  --restart unless-stopped \
  dockmon:latest

# Watch the logs for detailed migration output
docker logs -f dockmon
```

### Option 2: Hot Copy (Faster, No Rebuild)

```bash
# Copy the fixed files into the running container
docker cp backend/migrate.py dockmon:/app/backend/migrate.py
docker cp backend/alembic/versions/20251025_1200_005_v2_1_0_upgrade.py dockmon:/app/backend/alembic/versions/20251025_1200_005_v2_1_0_upgrade.py

# Restart the container
docker restart dockmon

# Watch the logs
docker logs -f dockmon
```

## What to Look For in Logs

With the enhanced logging, you should now see:

### Success Path
```
Starting v2.1.0 migration...
Existing tables: ['users', 'docker_hosts', 'global_settings', ...]
All prerequisite tables exist, proceeding with migration...
Creating deployments table...
Creating indexes for deployments table...
Deployments table created successfully
...
After upgrade, database version: 005_v2_1_0
Migrations completed successfully
Schema validation passed
```

### Failure Path (New Error Details)
```
Starting v2.1.0 migration...
Existing tables: [...]
Creating deployments table...
ERROR: <specific error message>
Migration failed: <detailed exception>
Database version after failure: 004_v2_0_3
```

## Expected Outcomes

1. **If migration succeeds**: Container will start normally, logs will show "Migration completed successfully"

2. **If migration still fails**: You'll now see a clear error message indicating:
   - Which table creation failed
   - What constraint was violated
   - The exact SQL error

3. **If prerequisite tables are missing**: You'll see "Cannot run v2.1.0 migration: Missing required tables: [...]"

## Troubleshooting

### If logs show "Missing required tables"

The database may be corrupted. Check which tables exist:
```bash
docker exec dockmon sqlite3 /app/data/dockmon.db ".tables"
```

### If logs show foreign key constraint error

There may be an issue with the users table:
```bash
docker exec dockmon sqlite3 /app/data/dockmon.db "SELECT id, username FROM users;"
```

### If migration still loops after fix

1. Check if multiple containers are running:
   ```bash
   docker ps -a | grep dockmon
   ```

2. Check database locks:
   ```bash
   docker exec dockmon fuser /app/data/dockmon.db
   ```

3. Check for backup files that may indicate previous failures:
   ```bash
   docker exec dockmon ls -la /app/data/
   ```

## Next Steps

After deploying the fix:

1. **Capture the new logs** - The detailed logging will show exactly what's failing
2. **Share the logs** - If it still fails, the error message will be clear and actionable
3. **Check database state** - If needed, we can examine the actual database structure

## Safety Notes

- Your database is backed up automatically before each migration attempt
- Backups are stored as `/app/data/dockmon.db.backup-004_v2_0_3-to-005_v2_1_0`
- If migration fails, the backup is preserved
- To restore: `docker cp dockmon:/app/data/dockmon.db.backup-<version> ./backup.db`

## Files Modified

- `backend/migrate.py` - Added version verification and enhanced error logging
- `backend/alembic/versions/20251025_1200_005_v2_1_0_upgrade.py` - Added step-by-step logging

No changes to database schema or migration logic - only added diagnostics.
