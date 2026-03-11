# Security Scanning CI Design

**Date:** 2026-03-05
**Scope:** Add scanner config files to suppress accepted findings, and a GitHub Actions workflow to run all security scanners.

## Workflow

**File:** `.github/workflows/security-scan.yml`

**Triggers:** PRs to main/dev, weekly schedule, manual dispatch.

**Jobs (parallel):**
1. codeql — GitHub's built-in (Python + Go)
2. go-security — gosec + govulncheck
3. python-security — bandit
4. frontend-security — npm audit
5. container-security — trivy + hadolint
6. semgrep — multi-language

## Config Files

| File | Purpose |
|---|---|
| `.trivyignore` | DS-0002 (already exists) |
| `.hadolint.yaml` | Ignore DL3018, DL3059 |
| `.bandit` | Skip B104, B108, B608 |
| `.gosec.yaml` | Exclude G402, G304, G702, G204, G117, G104, G118 |
| `.semgrepignore` | Ignore alembic migrations, test SQL patterns |

## Constraints

- Separate from publish pipelines
- No inline code comments
- Scanners exit 0 when only accepted findings remain
