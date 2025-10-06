# Git Workflow Quick Reference

## Daily Development Commands

### Starting a New Feature (V2 Development)

```bash
# 1. Ensure dev is up to date
git checkout dev
git pull origin dev

# 2. Create feature branch
git checkout -b feature/your-feature-name

# Examples:
# git checkout -b feature/cookie-auth
# git checkout -b feature/user-preferences-api
# git checkout -b feature/dashboard-kpis
```

### Working on a Feature

```bash
# Make changes, then commit
git add .
git commit -m "feat(scope): Description of change"

# Commit message format:
# feat(auth): Add cookie-based sessions
# fix(api): Fix dashboard KPI calculation
# test(auth): Add login/logout tests
# refactor(api): Extract common response handlers
# docs(api): Document v2 endpoints
```

### Pushing Feature to GitHub

```bash
# First push (creates remote branch)
git push -u origin feature/your-feature-name

# Subsequent pushes
git push
```

### Creating Pull Request

1. Go to GitHub: https://github.com/darthnorse/dockmon
2. Click "Compare & pull request" button
3. **Base branch:** `dev` ← **Compare branch:** `feature/your-feature-name`
4. Add description, reviewers (if applicable)
5. Create PR
6. After merge, delete feature branch locally:

```bash
git checkout dev
git pull origin dev
git branch -d feature/your-feature-name
```

---

## V1 Bugfix Workflow

### Critical V1 Bug During V2 Development

```bash
# 1. Switch to v1-maintenance
git checkout v1-maintenance
git pull origin v1-maintenance

# 2. Create bugfix branch
git checkout -b fix/short-bug-description

# Examples:
# git checkout -b fix/container-restart-hang
# git checkout -b fix/memory-leak-stats-service

# 3. Fix the bug (edit v1 code only)
# backend/main.py, src/js/app.js, stats-service/main.go

# 4. Commit
git add .
git commit -m "fix: Short description of fix"

# 5. Push and create PR to v1-maintenance
git push -u origin fix/short-bug-description

# 6. After merge, tag new v1 patch version
git checkout v1-maintenance
git pull
git tag v1.12.1  # Increment patch version
git push origin v1.12.1

# 7. If bug affects v2 backend, backport to dev
git checkout dev
git cherry-pick <commit-sha-from-v1-maintenance>
git push origin dev
```

---

## Common Scenarios

### Scenario: Your Feature Branch is Behind `dev`

```bash
# Option 1: Rebase (cleaner history)
git checkout feature/your-feature
git fetch origin
git rebase origin/dev

# If conflicts, resolve them, then:
git add .
git rebase --continue

# Force push (rewrites history on your feature branch)
git push --force-with-lease

# Option 2: Merge (simpler, preserves history)
git checkout feature/your-feature
git merge origin/dev
git push
```

### Scenario: You Committed to Wrong Branch

```bash
# If you committed to dev instead of feature branch:
git checkout dev
git log  # Find your commit SHA

git checkout -b feature/your-feature  # Create feature branch
# Commit is now on feature branch

git checkout dev
git reset --hard origin/dev  # Reset dev to remote state
```

### Scenario: Need to Undo Last Commit

```bash
# Undo commit but keep changes
git reset --soft HEAD~1

# Undo commit and discard changes (dangerous!)
git reset --hard HEAD~1
```

### Scenario: View Differences Between Branches

```bash
# See what's in dev but not in main
git log main..dev --oneline

# See file differences
git diff main..dev

# See changes in a specific file
git diff main..dev -- backend/api/v2/auth.py
```

---

## Branch Status Checks

### See Current Branch

```bash
git branch
# * dev  (asterisk shows current branch)
```

### See All Branches (Local + Remote)

```bash
git branch -a
```

### See Which Commits Are in Each Branch

```bash
git log --oneline --graph --all --decorate
```

---

## Cleanup Commands

### Delete Local Feature Branch (After Merge)

```bash
git branch -d feature/your-feature  # Safe delete (only if merged)
git branch -D feature/your-feature  # Force delete (use with caution)
```

### Delete Remote Feature Branch

```bash
git push origin --delete feature/your-feature
```

### Prune Stale Remote Branches

```bash
git fetch --prune  # Remove remote branches that no longer exist
```

---

## Stashing Changes (Temporary Save)

### Save Work in Progress

```bash
# Save all uncommitted changes
git stash

# Save with a message
git stash save "Work in progress on auth feature"

# List stashes
git stash list
```

### Restore Stashed Changes

```bash
# Apply most recent stash
git stash pop

# Apply specific stash
git stash apply stash@{1}

# Delete stash
git stash drop stash@{0}
```

---

## Viewing History

### See Recent Commits

```bash
git log --oneline -10  # Last 10 commits
git log --oneline --graph  # With graph
```

### See What Changed in a Commit

```bash
git show <commit-sha>
git show HEAD  # Most recent commit
git show HEAD~1  # One commit before HEAD
```

### See File History

```bash
git log -- backend/api/v2/auth.py
git log -p -- backend/api/v2/auth.py  # With diffs
```

---

## Emergency: Undo Everything

### Reset to Remote State (Discard All Local Changes)

```bash
git fetch origin
git reset --hard origin/dev  # Replace dev with your branch name
```

### Reset Specific File to Remote State

```bash
git checkout origin/dev -- backend/main.py
```

---

## Weekly Sync Routine

```bash
# Every Monday (or start of work session)
git checkout dev
git pull origin dev

git checkout v1-maintenance
git pull origin v1-maintenance

git checkout dev  # Back to dev for work
```

---

## Commit Message Conventions

Format: `type(scope): description`

**Types:**
- `feat` - New feature
- `fix` - Bug fix
- `refactor` - Code restructuring (no behavior change)
- `test` - Add/update tests
- `docs` - Documentation changes
- `chore` - Build, dependencies, configs

**Scopes:**
- `auth` - Authentication/sessions
- `api` - API endpoints
- `db` - Database changes
- `ui` - Frontend (when exists)
- `docker` - Docker/deployment

**Examples:**
```
feat(auth): Add cookie-based session authentication
fix(api): Fix dashboard KPI race condition
test(auth): Add login/logout integration tests
refactor(db): Extract database connection to separate module
docs(api): Document v2 REST endpoints
chore(deps): Upgrade FastAPI to 0.104.1
```

---

## Help Commands

```bash
git status              # See what's changed
git diff                # See unstaged changes
git diff --staged       # See staged changes
git log --help          # Full documentation for any command
git reflog              # See ALL local actions (recovery tool)
```

---

## Current Branch Setup

- **main** - v1.12.0 production (protected)
- **v1-maintenance** - v1 bugfixes (merge to main)
- **dev** - v2 development (merge features here)
- **feature/*** - Individual features (merge to dev)

**Default branch for new PRs:** `dev`

---

**Need help?** Check [BRANCH_STRATEGY.md](../BRANCH_STRATEGY.md) for detailed workflows.
