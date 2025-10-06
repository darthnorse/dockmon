# DockMon Branch Strategy

## Branch Structure

```
main (production v1.12)
├── v1-maintenance (long-lived, v1 bugfixes during v2 migration)
└── dev (development v2)
    └── feature/* (short-lived feature branches)
```

---

## Branch Purposes

### `main` - Production v1.12
- **Purpose:** Stable production code (v1.12.x)
- **Deploy from:** This branch
- **Updates:** Only from v1-maintenance (critical bugfixes) or release branches (v2.0.0+)
- **Protected:** Yes

### `v1-maintenance` - V1 Bugfixes
- **Purpose:** Critical v1 bugfixes during v2 development (Week 1-8)
- **Created from:** main (v1.12.0)
- **Merges to:** main (for production deployment)
- **Backport to:** dev (if bug affects v2 backend)
- **Lifespan:** Until v1 EOL (~30 days after v2.0 release)

### `dev` - V2 Development
- **Purpose:** Integration branch for v2 development
- **Created from:** main (v1.12.0)
- **Receives from:** feature/* branches
- **Merges to:** main (when v2.0 is ready)
- **Protected:** Status checks required

### `feature/*` - Feature Branches
- **Purpose:** Individual v2 features (short-lived)
- **Created from:** dev
- **Merges to:** dev
- **Naming:**
  - `feature/cookie-auth` - New feature
  - `fix/websocket-reconnect` - Bug fix
  - `refactor/api-client` - Refactoring
  - `test/e2e-playwright` - Tests
  - `docs/api-spec` - Documentation

---

## Common Workflows

### 🐛 V1 Critical Bugfix (during v2 development)

```bash
# Start from v1-maintenance
git checkout v1-maintenance
git pull origin v1-maintenance

# Create bugfix branch
git checkout -b fix/container-restart-hang

# Fix the bug
# ... edit backend/main.py or src/js/app.js ...

# Commit and push
git add .
git commit -m "fix: Container restart hangs on network errors"
git push -u origin fix/container-restart-hang

# Create PR: fix/container-restart-hang → v1-maintenance
# After merge:
git checkout v1-maintenance
git pull
git tag v1.12.1
git push origin v1.12.1

# Deploy v1.12.1 to production

# If bug affects v2 backend, backport:
git checkout dev
git cherry-pick <commit-sha>
git push origin dev
```

---

### ✨ V2 Feature Development

```bash
# Start from dev
git checkout dev
git pull origin dev

# Create feature branch
git checkout -b feature/cookie-auth

# Implement feature
# ... edit backend/api/v2/auth.py ...

# Commit frequently
git add backend/api/v2/auth.py
git commit -m "feat(auth): Add cookie-based session authentication"

git add backend/tests/test_auth.py
git commit -m "test(auth): Add login/logout tests"

# Push and create PR
git push -u origin feature/cookie-auth

# Create PR: feature/cookie-auth → dev
# After CI passes + review, merge to dev
```

---

### 📦 Weekly Integration (merge features to dev)

```bash
# Ensure dev is up to date
git checkout dev
git pull origin dev

# Features are merged via GitHub PRs
# Run tests locally before pushing
pytest backend/tests/
# (later: pnpm test when frontend exists)

# Push to dev
git push origin dev
```

---

### 🚀 V2 Release (End of Week 8)

```bash
# Ensure dev is stable
git checkout dev
pytest backend/tests/
pnpm test
pnpm build

# Create release branch
git checkout -b release/v2.0.0

# Bump versions
# backend/version.py: VERSION = "2.0.0"
# frontend/package.json: "version": "2.0.0"

git commit -am "chore: Bump version to 2.0.0"

# Create PR: release/v2.0.0 → main
# After approval, merge to main

# Tag release
git checkout main
git pull
git tag v2.0.0
git push origin v2.0.0

# Merge back to dev
git checkout dev
git merge main
git push origin dev
```

---

## Branch Lifecycle

**Week 1 (Today):**
```
main ──────────────────> (v1.12.0 stable)
  │
  ├─> v1-maintenance ──> (ready for v1 bugfixes)
  │
  └─> dev ─────────────> (v2 development starts)
```

**Week 2-8 (Development):**
```
main ──────────────────────> (still v1.12.0)
  │
  ├─> v1-maintenance ──────> v1.12.1 (critical fixes)
  │
  └─> dev ──> feature/auth ──┐
         └──> feature/ui ─────┴─> (v2 development)
```

**Week 8 (Release):**
```
dev ──> release/v2.0.0 ──> main (v2.0.0 deployed)
```

**Week 9+ (Post-release):**
```
main ────────────────────> (v2.0.0 production)
  │
  ├─> v1-maintenance ────> (keep 30 days, then archive)
  │
  └─> dev ───────────────> (v2.1 development)
```

---

## When to Delete Branches

| Branch | Delete When |
|--------|-------------|
| `main` | Never |
| `dev` | Never |
| `v1-maintenance` | 30-60 days after v2.0 release |
| `feature/*` | Immediately after merge to dev |
| `release/*` | After merge to main (or keep for audit) |

---

## Current Status

- ✅ `main` - v1.12.0 (stable production)
- ✅ `v1-maintenance` - v1.12.0 (ready for bugfixes)
- ✅ `dev` - v1.12.0 (v2 development branch)

**Next:** Start Phase 1 development on `dev` branch with feature branches!

---

**Created:** 2025-10-06
**Last Updated:** 2025-10-06
