# Phase 1 Testing & Validation Plan

**Current Setup:** DockMon v1.1.2 running in Docker
**Goal:** Validate Phase 1 (v2 backend) works correctly without breaking v1

---

## Testing Strategy

We'll test in 3 stages:

1. **Local Python Tests** (no Docker) - Fast validation
2. **Docker Build Test** - Ensure Phase 1 works in container
3. **Live Integration Test** - Validate v1 still works, v2 works

---

## Stage 1: Local Python Tests (Recommended First)

### 1.1 Install Dependencies Locally

```bash
# Option A: Using system Python (if allowed)
cd /Users/patrikrunald/Documents/CodeProjects/dockmon/backend
python3 -m pip install --user --break-system-packages \
  alembic==1.13.1 \
  argon2-cffi==23.1.0 \
  itsdangerous==2.1.2 \
  pytest==7.4.3 \
  pytest-asyncio==0.21.1 \
  pytest-cov==4.1.0

# Option B: Using virtual environment (cleaner)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 1.2 Run Database Migration (Test Database)

```bash
cd /Users/patrikrunald/Documents/CodeProjects/dockmon/backend

# Create test database (separate from Docker)
mkdir -p test_data

# Run migration
PYTHONPATH=/Users/patrikrunald/Documents/CodeProjects/dockmon/backend \
  alembic upgrade head

# Verify migration
sqlite3 test_data/dockmon.db "SELECT name FROM sqlite_master WHERE type='table';"
# Should show: user_prefs table
```

### 1.3 Run Pytest Suite

```bash
cd /Users/patrikrunald/Documents/CodeProjects/dockmon/backend

# Run all tests
pytest tests/v2/ -v

# Run with coverage
pytest tests/v2/ --cov=auth --cov=api/v2 --cov-report=term-missing

# Run security tests only
pytest tests/v2/ -m security -v
```

**Expected:** All tests pass (or close to passing)

---

## Stage 2: Docker Build Test

### 2.1 Rebuild Docker Image with Phase 1 Changes

```bash
cd /Users/patrikrunald/Documents/CodeProjects/dockmon

# Build new image (don't start yet)
docker compose build

# Check image size
docker images | grep dockmon
```

### 2.2 Test Build Includes New Dependencies

```bash
# Check if alembic is installed in image
docker run --rm dockmon:latest pip list | grep -E "alembic|argon2|itsdangerous"
```

**Expected:** All 3 packages should be listed

---

## Stage 3: Live Integration Test

### 3.1 Backup Current v1.1.2 Data

```bash
# Export current database
docker exec dockmon sqlite3 /app/data/dockmon.db ".backup /app/data/backup_v1.1.2.db"

# Copy backup to host
docker cp dockmon:/app/data/backup_v1.1.2.db ./backup_v1.1.2.db

# Verify backup
sqlite3 backup_v1.1.2.db "SELECT * FROM users;"
```

### 3.2 Stop Current Container

```bash
docker compose down
```

### 3.3 Start New Container with Phase 1

```bash
# Start with new image
docker compose up -d

# Watch logs
docker compose logs -f
```

### 3.4 Run Migration Inside Container

```bash
# Enter container
docker exec -it dockmon bash

# Navigate to backend
cd /app/backend

# Run migration
alembic upgrade head

# Verify migration
sqlite3 /app/data/dockmon.db "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
# Should show: user_prefs (new table)

# Exit container
exit
```

### 3.5 Test v1 Still Works

```bash
# Test v1 frontend (should work unchanged)
open https://localhost:8001

# Test v1 API (should work unchanged)
curl -k https://localhost:8001/api/hosts
```

**Expected:** v1.1.2 UI and API work exactly as before

### 3.6 Test v2 API Endpoints

```bash
# Test v2 login (cookie-based)
curl -X POST https://localhost:8001/api/v2/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your_password"}' \
  -c cookies.txt -k

# Test v2 preferences (requires cookie)
curl https://localhost:8001/api/v2/user/preferences \
  -b cookies.txt -k

# Test v2 logout
curl -X POST https://localhost:8001/api/v2/auth/logout \
  -b cookies.txt -k
```

**Expected:** v2 endpoints work, return proper JSON

---

## Stage 4: Rollback Plan (If Needed)

### If Phase 1 Breaks Something

```bash
# Stop new container
docker compose down

# Checkout v1.1.2 code
git checkout main

# Restore backup database
docker compose up -d
docker cp backup_v1.1.2.db dockmon:/app/data/dockmon.db
docker restart dockmon

# Verify v1.1.2 works
open https://localhost:8001
```

---

## Testing Checklist

### Pre-Testing

- [ ] Backup current v1.1.2 database
- [ ] Note current git branch (`feature/alembic-setup`)
- [ ] Document current working v1.1.2 state

### Stage 1: Local Tests

- [ ] Install Python dependencies
- [ ] Run Alembic migration (test DB)
- [ ] Run pytest suite (all tests)
- [ ] Verify 80%+ coverage
- [ ] Check for security test failures

### Stage 2: Docker Build

- [ ] Build new Docker image
- [ ] Verify dependencies in image
- [ ] Check image size (reasonable)

### Stage 3: Integration

- [ ] Stop current container
- [ ] Start new container
- [ ] Run migration in container
- [ ] Verify database schema updated
- [ ] Test v1 frontend (unchanged)
- [ ] Test v1 API (unchanged)
- [ ] Test v2 login API
- [ ] Test v2 preferences API
- [ ] Test v2 logout API

### Validation

- [ ] No errors in Docker logs
- [ ] v1 UI fully functional
- [ ] v2 API returns proper responses
- [ ] HttpOnly cookies set correctly
- [ ] Database has user_prefs table
- [ ] No memory leaks (check `docker stats`)

---

## Expected Results

### ✅ Success Indicators

1. **All pytest tests pass** (63 tests)
2. **v1.1.2 UI works unchanged** (no breaking changes)
3. **v2 API endpoints respond correctly** (200 status)
4. **Database migration successful** (user_prefs table exists)
5. **No errors in Docker logs**
6. **Memory usage stable** (no leaks)

### ❌ Failure Indicators

1. Pytest tests fail
2. v1 UI broken
3. v2 API returns 500 errors
4. Migration fails
5. Container won't start
6. Memory usage grows unbounded

---

## Quick Commands Reference

```bash
# Run local tests
cd backend
pytest tests/v2/ -v

# Rebuild Docker
docker compose build

# Restart with new code
docker compose down && docker compose up -d

# Watch logs
docker compose logs -f

# Enter container
docker exec -it dockmon bash

# Run migration in container
docker exec dockmon bash -c "cd /app/backend && alembic upgrade head"

# Check tables
docker exec dockmon sqlite3 /app/data/dockmon.db "SELECT name FROM sqlite_master WHERE type='table';"

# Rollback to v1.1.2
git checkout main && docker compose down && docker compose up -d
```

---

**Next Steps:**

1. Start with Stage 1 (local tests) - fastest validation
2. If tests pass, proceed to Stage 2 (Docker build)
3. If build works, proceed to Stage 3 (integration)
4. Document any issues found

**Ready to start?** Run the commands in order and let me know results!
