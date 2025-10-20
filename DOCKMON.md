# DockMon - Session Onboarding Guide

**Purpose:** Read this at the start of each session to understand DockMon's architecture, codebase, and development workflow.

---

## What is DockMon?

**DockMon** is a self-hosted Docker monitoring and management platform with a focus on container updates, health monitoring, and alert management across multiple Docker hosts.

**Core Features:**
- Multi-host Docker monitoring (local + remote TCP hosts)
- Container update detection and management (manual + automatic)
- Update validation policies (protect critical containers like databases, proxies)
- HTTP/HTTPS health checks with configurable intervals
- Alert system with Pushover integration
- Real-time WebSocket updates for live container status
- Container operations (start, stop, restart, logs, stats)
- Auto-restart on failure with backoff
- Tag-based container organization
- User authentication and RBAC

**Current Version:** v2.0.0 (upgraded from v1.1.3)

---

## Architecture Overview

### Technology Stack

**Backend:**
- Python 3.11 with FastAPI
- SQLite database with SQLAlchemy ORM
- Docker SDK for Python (with async wrappers to prevent event loop blocking)
- Alembic for database migrations
- APScheduler for periodic jobs (update checks, stats collection)
- WebSocket for real-time updates
- EventBus pattern for decoupled event handling

**Frontend:**
- React 18 with TypeScript (strict mode)
- Vite for build tooling
- TanStack React Query for API state management
- TailwindCSS for styling
- Lucide React for icons
- React Router for navigation
- Zustand for local state (WebSocket, auth)

**Deployment:**
- Docker container with multi-process supervision (supervisord)
- Nginx serves frontend static files
- Python backend on port 8000
- Stats collection service (separate process)
- Single SQLite database file at `/app/data/dockmon.db`

### Key Design Patterns

**1. Composite Keys for Multi-Host:**
- Format: `{host_id}:{container_id}` where host_id is UUID, container_id is SHORT (12 chars)
- Used in: `container_updates`, `container_http_health_checks`, event tracking
- Prevents collisions when monitoring cloned VMs with duplicate container IDs

**2. Container ID Format (CRITICAL):**
- **ALWAYS use SHORT IDs (12 characters)** - Never full 64-char IDs
- Extract with: `container.short_id` or `container.id[:12]`
- This is a recurring issue - verify in every file that touches container IDs

**3. Async Docker Calls:**
- Docker SDK is synchronous - wraps all calls with `async_docker_call()` to prevent blocking
- Pattern: `await async_docker_call(client.containers.get, container_id)`

**4. Event Bus Pattern:**
- Centralized EventBus coordinates: event logging, alert evaluation, WebSocket broadcasts
- Services emit events via `bus.emit(Event(...))`, subscribers handle independently
- Decouples event producers from consumers

**5. Commitment Point Pattern:**
- Track when database commits succeed to avoid incorrect rollbacks
- Pattern:
  ```python
  operation_committed = False
  try:
      session.commit()
      operation_committed = True
      # post-commit operations
  except Exception as e:
      if operation_committed:
          # Don't rollback - operation succeeded
          return True
      else:
          rollback()
  ```

**6. Update Validation Priority:**
```
1. Container Label (dockmon.update_policy=allow/warn/block)
2. Per-Container Policy (database override)
3. Pattern Match (databases, proxies, monitoring, critical, custom)
4. Default (allow)
```

---

## Project Structure

```
dockmon/
├── backend/
│   ├── main.py                    # FastAPI app, API endpoints
│   ├── database.py                # SQLAlchemy models, migrations
│   ├── event_bus.py               # Event coordination system
│   ├── event_logger.py            # Database event logging
│   ├── websocket/
│   │   └── connection.py          # WebSocket manager
│   ├── docker_monitor/
│   │   ├── monitor.py             # Main DockerMonitor class
│   │   ├── periodic_jobs.py       # Scheduled tasks (update checks, stats)
│   │   ├── container_discovery.py # Container state synchronization
│   │   └── stats_manager.py       # CPU/memory stats collection
│   ├── updates/
│   │   ├── update_executor.py     # Container update logic
│   │   ├── update_checker.py      # Update detection
│   │   ├── container_validator.py # Update validation policies
│   │   └── registry_adapter.py    # Docker registry API
│   ├── alerts/
│   │   ├── evaluation_service.py  # Alert rule evaluation
│   │   └── engine.py              # Alert matching engine
│   ├── health_check/
│   │   └── http_checker.py        # HTTP/HTTPS health checks
│   ├── auth/
│   │   └── jwt_handler.py         # JWT authentication
│   ├── utils/
│   │   └── async_docker.py        # Async Docker SDK wrappers
│   └── alembic/
│       └── versions/              # Database migrations
│
├── ui/
│   ├── src/
│   │   ├── features/
│   │   │   ├── containers/        # Container management UI
│   │   │   ├── alerts/            # Alert configuration UI
│   │   │   ├── settings/          # Settings pages
│   │   │   └── auth/              # Login/logout
│   │   ├── components/ui/         # Reusable UI components
│   │   ├── lib/
│   │   │   └── api/               # API client
│   │   └── stores/                # Zustand state stores
│   └── package.json
│
├── wiki-content/                  # User documentation (Markdown)
├── CLAUDE.md                      # Development guidelines (MANDATORY)
├── DOCKMON.md                     # This file
└── data/                          # SQLite database (gitignored)
```

---

## Database Schema (Key Tables)

**containers** - Container metadata and current state
- Composite key: `(host_id, id)` where id is SHORT container ID (12 chars)

**container_updates** - Update status and version tracking
- Primary key: `container_id` (composite format: `{host_id}:{container_id}`)
- Tracks: current_image, latest_image, update_available

**update_policies** - Validation rules for protected containers
- Categories: databases, proxies, monitoring, critical, custom
- Fields: category, pattern, enabled

**container_desired_states** - User preferences per container
- Fields: custom_tags, update_policy (allow/warn/block), auto_update_enabled

**auto_restart_configs** - Auto-restart behavior
- Composite key: `(host_id, container_id)` - SHORT ID only

**container_http_health_checks** - HTTP/HTTPS monitoring
- Primary key: `container_id` (composite format)
- Fields: url, interval_seconds, current_status

**event_logs** - System event history
- Stores all events: updates, state changes, alerts, errors

**alerts** - Active alerts
- Dedup key format: `{rule_id}|{kind}|{scope}:{scope_id}`

---

## Development Workflow

### Reading CLAUDE.md (MANDATORY)

**Before ANY code changes:**
```
Read /Users/patrikrunald/Documents/CodeProjects/dockmon/CLAUDE.md
```

Contains:
- Pre-implementation checklist (requirements, CRUD, state flow, database consistency)
- Mandatory self-review protocol
- Container ID standards
- Composite key standards
- Async/await patterns
- Timestamp formatting (must append 'Z' for frontend)
- Database consistency rules
- Common pitfalls

### Typical Development Flow

1. **Read CLAUDE.md** to understand standards
2. **Complete pre-implementation checklist** if feature is non-trivial
3. **Implement changes** following standards
4. **Test locally** before deployment
5. **Deploy to container** using fast deployment methods
6. **Complete mandatory self-review** before claiming "production ready"

### Fast Deployment (No Container Rebuild)

**Backend (Python files):**
```bash
# Copy file to container
DOCKER_HOST= docker cp backend/main.py dockmon:/app/backend/main.py

# Restart container
DOCKER_HOST= docker restart dockmon
```

**Frontend (UI changes):**
```bash
# Type check
npm --prefix ui run type-check

# Build production bundle
npm --prefix ui run build

# Deploy to running container (instant!)
DOCKER_HOST= docker cp ui/dist/. dockmon:/usr/share/nginx/html/
```

**Database migrations:**
- Alembic migrations run automatically on container startup
- Manual migration: Add column directly via SQLite if needed

### Common Commands

**Check logs:**
```bash
DOCKER_HOST= docker logs dockmon --since 5m
DOCKER_HOST= docker logs dockmon --tail 50
```

**Check container status:**
```bash
DOCKER_HOST= docker ps --filter name=dockmon
```

**Access database:**
```bash
DOCKER_HOST= docker exec dockmon python3 -c "
import sqlite3
conn = sqlite3.connect('/app/data/dockmon.db')
cursor = conn.cursor()
# SQL queries here
conn.close()
"
```

**Test Python syntax:**
```bash
python3 -m py_compile backend/main.py
```

---

## Critical Standards (From CLAUDE.md)

### 1. Container IDs - ALWAYS SHORT (12 chars)
```python
# ✅ CORRECT
container_id = container.short_id  # "a8a3f133e9dd"
container_id = container.id[:12]

# ❌ WRONG
container_id = container.id  # "a8a3f133e9dd1234..." (64 chars)
```

### 2. Composite Keys - Multi-Host Operations
```python
# ✅ CORRECT
composite_key = f"{host_id}:{container_id}"
# "07453b25-6a4c-4d74-878e-c9634e174d53:a8a3f133e9dd"

# ❌ WRONG - Will have collisions across hosts
key = container_id
```

### 3. Async Docker Calls - Prevent Event Loop Blocking
```python
# ✅ CORRECT
container = await async_docker_call(client.containers.get, container_id)

# ❌ WRONG - Blocks event loop
container = client.containers.get(container_id)
```

### 4. Timestamps - Frontend Needs 'Z' Suffix
```python
# ✅ CORRECT
"timestamp": dt.isoformat() + 'Z'

# ❌ WRONG - Frontend can't convert to local time
"timestamp": dt.isoformat()
```

### 5. Database Consistency - Update IDs When Containers Recreate
```python
# When container is recreated (stopped + removed + created):
old_container_id = "a8a3f133e9dd"
new_container = client.containers.create(...)
new_container_id = new_container.short_id  # "4b0adf0827ed"

# MUST update database:
record.container_id = f"{host_id}:{new_container_id}"
session.commit()
```

---

## Important Files to Reference

**Coding Standards:**
- `CLAUDE.md` - Pre-implementation checklist, self-review protocol, standards

**API Documentation:**
- `backend/main.py` - All REST endpoints with docstrings
- Lines 902-1013: Manual update execution
- Lines 1143-1278: Update policy management

**Update System:**
- `backend/updates/update_executor.py` - Core update logic, backup/rollback
- `backend/updates/container_validator.py` - Validation rules
- `backend/updates/update_checker.py` - Registry queries

**Event System:**
- `backend/event_bus.py` - Event coordination
- `backend/event_logger.py` - Database logging

**Frontend Hooks:**
- `ui/src/features/containers/hooks/useContainerUpdates.ts` - Update mutations
- `ui/src/features/containers/hooks/useUpdatePolicies.ts` - Policy management

**User Documentation:**
- `wiki-content/` - Markdown docs for features

---

## Common Issues & Solutions

### Issue: ModuleNotFoundError after adding new Python file
**Solution:** Must copy file to container and restart
```bash
DOCKER_HOST= docker cp backend/new_file.py dockmon:/app/backend/new_file.py
DOCKER_HOST= docker restart dockmon
```

### Issue: UI changes not appearing
**Solution:** Rebuild and redeploy frontend
```bash
npm --prefix ui run build
DOCKER_HOST= docker cp ui/dist/. dockmon:/usr/share/nginx/html/
```

### Issue: Database migration not running
**Solution:**
1. Check migration file exists in container
2. Verify alembic_version table has correct version
3. Migrations run on container startup - check logs

### Issue: Empty table after migration (like update_policies bug)
**Solution:** Migration may check `if not _table_exists()` but table was created by `Base.metadata.create_all()` - need to check if table is EMPTY, not just if it exists

### Issue: Container update breaks volume mounts
**Solution:** `_extract_container_config()` properly handles volumes - verify HostConfig.Binds is being parsed correctly

---

## Testing Checklist

**Before claiming "production ready":**
- [ ] TypeScript type check passes: `npm --prefix ui run type-check`
- [ ] Python syntax valid: `python3 -m py_compile <file>`
- [ ] Manual testing of feature in UI
- [ ] Check logs for errors: `DOCKER_HOST= docker logs dockmon --since 5m`
- [ ] Database consistency verified (no orphaned records)
- [ ] Mandatory self-review protocol completed (CLAUDE.md)
- [ ] All SHORT IDs verified (12 chars, not 64)
- [ ] All Docker SDK calls wrapped with async_docker_call()
- [ ] All timestamps have 'Z' suffix for frontend

---

## Session Startup Checklist

When starting a new session:

1. ✅ Read this file (DOCKMON.md)
2. ✅ Read CLAUDE.md for development standards
3. ✅ Understand the current task context
4. ✅ Identify which files will be modified
5. ✅ Complete pre-implementation checklist if non-trivial
6. ✅ Reference architecture patterns above
7. ✅ Deploy and test changes
8. ✅ Complete mandatory self-review before claiming done

---

## Quick Reference

**Environment:**
- Database: `/app/data/dockmon.db` (inside container)
- Backend port: 8000
- Frontend: Nginx serving from `/usr/share/nginx/html/`
- Docker host: Uses `DOCKER_HOST=` prefix for remote operations

**User:**
- Username: admin
- System manages authentication via JWT tokens

**Important Patterns:**
- Event emission: `await bus.emit(Event(...))`
- Database sessions: `with db.get_session() as session:`
- Progress broadcasts: `await _broadcast_progress(host_id, container_id, stage, percent, message)`
- Composite keys: `f"{host_id}:{container_id}"`
- SHORT IDs only: `container.short_id` or `container.id[:12]`

**Common Gotchas:**
- Container recreation = new ID = must update database
- Docker SDK calls must use async wrappers
- Frontend timestamps need 'Z' suffix
- Composite keys required for multi-host
- Update validation has priority order (label > per-container > pattern > default)

---

**Ready to code!** 🚀
