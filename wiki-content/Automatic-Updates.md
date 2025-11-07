# Automatic Updates

Keep your containers up-to-date automatically with DockMon v2's intelligent update system.

---

## Overview

DockMon v2's automatic update system monitors your container images for new versions and can automatically pull and recreate containers when updates are available. This ensures your services stay current with the latest security patches and features while minimizing manual intervention.

**Key features:**
- **Automatic update detection** - Daily scheduled check at configurable time
- **Manual check trigger** - "Check All Now" button for immediate update detection
- **Update validation policies** - Protect critical containers (databases, proxies, etc.)
- **Flexible update strategies** - Control how aggressively containers update
- **Multi-registry support** - Docker Hub, GHCR, LSCR, Quay.io
- **Manual updates** - Update containers individually or in bulk
- **Safe update process** - Pull new image, backup old container, create new container, rollback on failure
- **Complete configuration preservation** - All Docker settings preserved (14 fields)
- **Compose awareness** - Optional skipping of Docker Compose containers
- **Update history** - Track when containers were updated
- **Floating tag modes** - Track exact tags, minor versions, major versions, or :latest
- **Health check validation** - Configurable health verification after updates (default: 10 seconds)

---

## How Automatic Updates Work

### Update Detection Workflow

1. **Scheduled check** (once per day at configured time, default: 02:00 AM)
2. **Container scan** - Get all containers from all hosts
3. **Image digest comparison**:
   - Get current image digest (what container is running)
   - Resolve floating tag in registry (what's available)
   - Compare digests to detect updates
4. **Update available** - Store in database and emit event
5. **Validation check** - Apply update policies (see [Update Validation Policies](#update-validation-policies))
6. **Auto-update** (if enabled and allowed) - Pull new image and recreate container
7. **Notification** - Alert via configured channels (optional)

**Example:**
```
Container: nginx
Current image: nginx:1.24.0 (digest: sha256:abc123...)
Check registry: nginx:1.24.0 resolves to sha256:def456...
Result: Update available (digests differ)
Validation: ALLOW (no patterns matched)
→ If auto-update enabled: Pull nginx:1.24.0 and recreate container
```

---

## Update Validation Policies

**New in v2:** DockMon can automatically protect critical containers from unintended updates by using validation patterns. This prevents accidental updates to databases, reverse proxies, and other critical infrastructure.

### How Validation Works

DockMon checks containers against validation rules in **priority order**:

1. **Docker labels** - Container label `com.dockmon.update.policy` (highest priority)
2. **Per-container setting** - Override set in container's Updates tab
3. **Global patterns** - Pattern matching against image/container name
4. **Default** - ALLOW (if no rules match)

### Validation Results

**ALLOW (Green):**
- Update proceeds immediately
- No user confirmation required
- Best for non-critical containers

**WARN (Yellow):**
- Shows confirmation dialog before updating
- Displays reason (e.g., "Matched databases pattern: postgres")
- User can proceed or cancel
- Auto-updates skipped (requires manual confirmation)
- Best for important containers that need review

**BLOCK (Red):**
- Update button disabled
- Must change policy to proceed
- Best for containers that should never auto-update

### Global Validation Patterns

**Location:** Settings → Container Updates → Update Validation Policies

**Built-in Categories** (23 default patterns):

#### Databases (11 patterns)
- postgres, mysql, mariadb, mongodb, mongo
- redis, sqlite, mssql, cassandra
- influxdb, elasticsearch

**Why protect databases?**
- Data integrity risk during updates
- May require backup before updating
- Schema migrations may be needed
- Downtime can affect entire application

#### Proxies (5 patterns)
- traefik, nginx, caddy, haproxy, envoy

**Why protect proxies?**
- Single point of entry for all traffic
- Configuration changes may break routing
- Downtime affects all services

#### Monitoring (4 patterns)
- grafana, prometheus, alertmanager, uptime-kuma

**Why protect monitoring?**
- Updates during incidents = blind
- Dashboard changes may affect troubleshooting

#### Critical (3 patterns)
- portainer, watchtower, dockmon

**Why protect critical infrastructure?**
- Self-updates can cause issues
- Need careful review before updating

### Managing Global Patterns

**Enable/Disable Categories:**
1. Navigate to Settings → Container Updates → Update Validation Policies
2. Toggle category switch (Databases, Proxies, etc.)
3. All patterns in category enabled/disabled together

**Expandable Pattern Lists:**
- Click chevron to see all patterns in category
- Patterns shown in grid layout (responsive)

**Add Custom Patterns:**
1. Scroll to "Custom Patterns" section
2. Enter pattern (e.g., "myapp", "company-api")
3. Click "Add Pattern"
4. Pattern matches against container name and image name (case-insensitive)

**Delete Custom Patterns:**
- Click X button next to custom pattern
- Built-in patterns cannot be deleted (only disabled)

**Examples:**
```
Custom pattern: "myapp"
Matches:
  ✅ Container name: myapp-prod
  ✅ Image name: company/myapp:latest
  ❌ Container name: other-service
```

### Per-Container Policy Override

**Location:** Container Details → Updates tab → Update Policy selector

**Override global patterns for specific containers:**

**Options:**
- **Use Global Settings** (default) - Use global patterns and Docker labels
- **Always Allow** - Bypass all patterns, always allow updates
- **Warn Before Update** - Always show confirmation, even if no pattern matches
- **Block Updates** - Never allow updates (manual override required)

**Use cases:**
- **Allow postgres on dev host** - Override WARN to ALLOW for development database
- **Block production API** - Override ALLOW to BLOCK for critical production service
- **Warn for custom service** - Add warning for service not in default patterns

**How to set:**
1. Open container details
2. Go to Updates tab
3. Select policy from dropdown (below Tracking Mode)
4. Change saved immediately
5. Toast confirmation shown

### Docker Label Override

**Highest priority** - Set policy via Docker label (useful for Docker Compose)

**Label:** `com.dockmon.update.policy`
**Values:** `allow`, `warn`, `block`

**Example Docker Compose:**
```yaml
version: '3.8'
services:
  database:
    image: postgres:14
    labels:
      - "com.dockmon.update.policy=block"  # Never auto-update

  api:
    image: myapp:latest
    labels:
      - "com.dockmon.update.policy=allow"  # Always allow auto-update
```

**Example Docker CLI:**
```bash
docker run -d \
  --label com.dockmon.update.policy=warn \
  --name critical-service \
  nginx:latest
```

### Validation Workflow Example

**Scenario:** Update postgres container

**Priority Check:**
1. Check Docker label: Not set
2. Check per-container override: Not set
3. Check global patterns: ✅ Matches "databases/postgres"
4. Result: **WARN**

**User Experience:**
1. User clicks "Update Now"
2. Confirmation modal appears:
   - Title: "Confirm Container Update"
   - Icon: Database icon (blue)
   - Reason: "Matched databases pattern: postgres"
   - Recommendation: "Review update notes and ensure you have backups"
   - Buttons: "Cancel" | "Update Anyway"
3. User clicks "Update Anyway"
4. Update proceeds with force flag
5. Normal update flow continues

---

## Floating Tag Modes

Floating tag modes control which image version DockMon tracks for updates.

### Respect Tag (Default)

**Mode:** `exact` (internal value)

**Behavior:** Use the image tag defined in your container or Compose configuration

**Example:**
```
Container with fixed tag: nginx:1.24.0
Tracks: nginx:1.24.0 (exact version)
Updates: When nginx:1.24.0 digest changes (rare - usually rebuild)
Does NOT update to: nginx:1.24.1 or nginx:1.25.0

Container with floating tag: nginx:latest
Tracks: nginx:latest
Updates: Whenever :latest tag is updated in registry
```

**Use case:**
- Respect the intent of your original configuration
- Fixed tags (e.g., 1.24.0) provide version stability
- Floating tags (e.g., :latest) provide automatic updates

**Pros:**
- ✅ Honors your original tag choice
- ✅ Fixed tags = predictable, stable
- ✅ Floating tags = automatic updates
- ✅ No breaking changes for fixed tags

**Cons:**
- ❌ Fixed tags miss new versions unless manually updated
- ❌ Floating tags may introduce breaking changes

### Minor Version Tracking

**Mode:** `minor`

**Behavior:** Track latest minor version within the same major version

**Example:**
```
Container image: nginx:1.24.0
Tracks: nginx:1.24 (or nginx:1.24.x conceptually)
Updates to: nginx:1.24.1, nginx:1.24.2, nginx:1.24.3...
Does NOT update to: nginx:1.25.0 or nginx:2.0.0
```

**Use case:**
- Production containers wanting patch updates
- Services using semantic versioning
- Balance between stability and currency

**Pros:**
- ✅ Automatic patch updates (security fixes)
- ✅ Stays within minor version (compatible changes only)
- ✅ Good for production

**Cons:**
- ❌ Misses new minor versions
- ❌ Requires semantic versioning adherence by image maintainers

**How it works:**
- Image `nginx:1.24.0` → DockMon tracks `nginx:1.24`
- Registry resolves `nginx:1.24` → latest digest (e.g., 1.24.3)
- Compares to current digest
- Updates if newer

### Major Version Tracking

**Mode:** `major`

**Behavior:** Track latest version within the same major version

**Example:**
```
Container image: nginx:1.24.0
Tracks: nginx:1 (or nginx:1.x conceptually)
Updates to: nginx:1.24.1, nginx:1.25.0, nginx:1.26.0...
Does NOT update to: nginx:2.0.0 or nginx:3.0.0
```

**Use case:**
- Development/staging environments
- Services with good backward compatibility
- Staying current within major version

**Pros:**
- ✅ Automatic minor and patch updates
- ✅ Stays within major version (no breaking changes)
- ✅ Good for staging

**Cons:**
- ❌ May introduce unexpected behavior changes
- ❌ Requires major version in image tag

**How it works:**
- Image `nginx:1.24.0` → DockMon tracks `nginx:1`
- Registry resolves `nginx:1` → latest digest (e.g., 1.26.5)
- Compares to current digest
- Updates if newer

### Latest Tag Tracking

**Mode:** `latest`

**Behavior:** Always track :latest tag

**Example:**
```
Container image: nginx:latest
Tracks: nginx:latest
Updates to: Any new build tagged as :latest
```

**Use case:**
- Development environments only
- Bleeding edge testing
- Quick prototypes

**Pros:**
- ✅ Always up-to-date
- ✅ Simplest configuration

**Cons:**
- ❌ Unpredictable updates (may include breaking changes)
- ❌ **NOT recommended for production**
- ❌ Can introduce instability

**Warning:** Using `:latest` in production is an anti-pattern. Use specific versions instead.

---

## Configuring Automatic Updates

### Per-Container Configuration

#### Method 1: Container Details

1. Navigate to **Container Dashboard**
2. Click container to open **Details** view
3. Go to **Updates** tab
4. Configure settings:
   - **Enable auto-update:** Toggle on/off
   - **Tracking Mode:** Select mode using radio buttons with descriptions:
     - **Respect Tag** - Use the image tag from your configuration (default)
     - **Minor Updates (X.Y.z)** - Track patch updates (e.g., 1.25.3 → 1.25.x)
     - **Major Updates (X.y.z)** - Track all updates in major version (e.g., 1.25.3 → 1.x)
     - **Always Latest** - Track :latest tag (not recommended for production)
   - **Update Policy:** Select policy (Use Global Settings, Always Allow, Warn Before Update, Block Updates) ← **NEW**
   - **Current image:** Shows current running image
   - **Latest available:** Shows latest available image (if checked recently)
   - **Update available:** Shows if update is available
5. Changes saved automatically

#### Method 2: Bulk Configuration

1. Filter containers (by tag, host, etc.)
2. Enable **Bulk Select** mode
3. Select containers
4. **Bulk Actions** → **Set Auto-Update**
5. Configure:
   - **Enable:** Yes/No
   - **Tracking mode:** Respect Tag/Minor Updates/Major Updates/Always Latest
6. Click **Apply**
7. Monitor bulk operation progress

See [Bulk Operations](Bulk-Operations) for bulk configuration details.

### Global Settings

**Location:** Settings → Container Updates

**Configuration:**

**Update Check Schedule:**
- **Daily Update Check Time:** Time of day to check for updates (24-hour format, default: 02:00 AM)
  - System checks once per day at this time
  - Click "Check All Now" to trigger immediate check

**Safety Settings:**
- **Skip Docker Compose containers:** Toggle to exclude Compose-managed containers from auto-updates (default: enabled)
- **Health Check Timeout:** Maximum time to wait for health checks after updating (10-600 seconds, default: 10)
  - **New in v2:** Reduced from 120s to 10s for faster updates
  - Containers with HEALTHCHECK: Waits up to 10s for "healthy" status
  - Containers without HEALTHCHECK: Waits 10s and verifies still running

**Update Validation Policies:** ← **NEW**
- **Databases:** Toggle all database patterns on/off (11 patterns)
- **Proxies:** Toggle all proxy patterns on/off (5 patterns)
- **Monitoring:** Toggle all monitoring patterns on/off (4 patterns)
- **Critical:** Toggle all critical patterns on/off (3 patterns)
- **Custom Patterns:** Add your own patterns

---

## Manual Update Check

### Check Single Container

1. Open container details
2. Go to **Updates** tab
3. Click **Check for Updates Now**
4. DockMon queries registry and updates status
5. Result shown: "Update available" or "Up to date"

**Use case:** Immediately check if new version is available before scheduled scan.

### Check All Containers

**Location:** Settings → Container Updates

1. Click **Check All Now**
2. Background job starts
3. Progress shown in notification
4. Results: "45 checked, 5 updates found"
5. Check Event Log for details

**Use case:** After deploying new images, force immediate check across fleet.

---

## Update Execution

### Automatic Update Process

When auto-update is enabled and an update is detected:

1. **Validation check:** ← **NEW**
   - Apply update policies (labels → per-container → patterns → default)
   - If BLOCK: Skip update, emit event
   - If WARN: Skip auto-update, require manual confirmation
   - If ALLOW: Proceed to next step

2. **Pre-update checks:**
   - Verify new image exists in registry
   - Check host connectivity
   - Verify permissions

3. **Pull new image:**
   - Download new image to host
   - Verify digest matches registry

4. **Backup old container:** ← **NEW**
   - Stop old container (SIGTERM → 10s → SIGKILL)
   - Rename to backup (e.g., `nginx` → `nginx-backup-20251019`)
   - Keeps old container for rollback

5. **Create new container:**
   - Extract full configuration from old container
   - **Preserves all settings** (14 Docker config fields): ← **NEW**
     - Environment variables
     - Volumes (bind mounts + named volumes)
     - Port bindings
     - Restart policy
     - Privileged mode
     - Capabilities (CapAdd/CapDrop)
     - Devices
     - **SecurityOpt (AppArmor/SELinux)** ← **NEW**
     - **Tmpfs mounts** ← **NEW**
     - **Ulimits (resource limits)** ← **NEW**
     - **Custom DNS servers** ← **NEW**
     - **ExtraHosts (/etc/hosts entries)** ← **NEW**
     - **IPC mode (namespace sharing)** ← **NEW**
     - **PID mode (process visibility)** ← **NEW**
     - **Shm size (shared memory)** ← **NEW**
   - Use new image
   - Same container name
   - Start immediately

6. **Health verification:** ← **IMPROVED**
   - Wait up to 10 seconds (reduced from 120s)
   - If container has HEALTHCHECK: Wait for "healthy" status
   - If no HEALTHCHECK: Wait 10s and verify still running
   - If fails: Automatic rollback to backup

7. **Rollback on failure:** ← **NEW**
   - If health check fails:
     - Stop new container
     - Remove new container
     - Restore backup container (rename back to original name)
     - Start old container
     - Emit UPDATE_FAILED event
     - Alert fired (if configured)

8. **Success cleanup:**
   - Remove backup container
   - Update database with new container ID (4 tables) ← **FIXED**
   - Emit UPDATE_COMPLETED event
   - Old image kept (for manual rollback if needed)

**Example timeline:**
```
0s:   Update detected for nginx:1.24.0 → 1.24.1
1s:   Validation check: ALLOW (no patterns matched)
2s:   Pull nginx:1.24.1 (2 minutes)
122s: Stop nginx container (10s graceful shutdown)
132s: Rename to nginx-backup-20251019
133s: Create new container with nginx:1.24.1
      → All 14 config fields preserved
134s: Start new container
135s: Health check (10s timeout)
      → Container has HEALTHCHECK, waiting for healthy...
138s: Health check passed (healthy)
139s: Update database (4 tables with new container ID)
140s: Remove backup container
141s: Update complete ✅
```

**Example rollback timeline:**
```
0s:   Update detected for postgres:14.1 → 14.2
1s:   Validation check: WARN (matched databases pattern)
2s:   Auto-update skipped (requires manual confirmation)
      → Event emitted: UPDATE_SKIPPED (validation: warn)
```

### Manual Update Trigger

**From container details:**
1. Open container
2. Go to **Updates** tab
3. Click **Update Now** (if update available)
4. **If validation = WARN:** ← **NEW**
   - Confirmation modal appears
   - Shows reason (e.g., "Matched databases pattern: postgres")
   - User can cancel or click "Update Anyway"
5. **If validation = ALLOW:**
   - Update proceeds immediately
6. Monitor progress in real-time (progress bar)

**Use case:** Apply critical security update immediately, don't wait for scheduled check.

---

## Configuration Preservation

**New in v2:** DockMon now preserves **all** Docker container configuration during updates. This ensures zero configuration drift and prevents subtle bugs.

### All Preserved Settings (14 fields)

| Setting | Description | Use Case |
|---------|-------------|----------|
| **Volumes** | Bind mounts + named volumes | Data persistence |
| **Ports** | Port bindings | Network access |
| **RestartPolicy** | Auto-restart behavior | High availability |
| **Privileged** | Privileged mode | Docker-in-Docker |
| **CapAdd/CapDrop** | Linux capabilities | Fine-grained permissions |
| **Devices** | Device access | GPU, USB devices |
| **SecurityOpt** | AppArmor/SELinux | Enhanced security |
| **Tmpfs** | Temporary filesystems | Performance (e.g., /tmp) |
| **Ulimits** | Resource limits | File descriptors, memory |
| **DNS** | Custom DNS servers | Internal name resolution |
| **ExtraHosts** | /etc/hosts entries | Custom hostnames |
| **IpcMode** | IPC namespace | Shared memory |
| **PidMode** | PID namespace | Process visibility |
| **ShmSize** | Shared memory size | Databases, Chrome headless |

**What this means:**
- ✅ Updates are truly transparent (zero config loss)
- ✅ No manual reconfiguration after updates
- ✅ Advanced Docker features fully supported
- ✅ Production-grade reliability

**Example - Postgres with custom shm:**
```bash
# Original container
docker run -d --name postgres \
  --shm-size 2g \
  -e POSTGRES_PASSWORD=secret \
  postgres:14.1

# After DockMon update to 14.2
# ✅ Shm size preserved: 2GB
# ✅ Environment preserved: POSTGRES_PASSWORD=secret
# ✅ Volume data intact
# ✅ No manual intervention required
```

---

## Compose Container Handling

### Why Skip Compose Containers?

**Problem:** Docker Compose containers are managed as a group. Updating one container may cause issues if other containers in the stack aren't updated.

**DockMon's approach:**

**Option 1: Skip Compose containers (default)**
- Containers with `com.docker.compose.project` label are skipped
- You update the entire stack manually with `docker-compose pull && docker-compose up -d`
- Ensures stack consistency

**Option 2: Allow Compose containers**
- DockMon updates Compose containers individually
- May cause version mismatches within stack
- **Use with caution**

**Recommendation:** Keep default (skip Compose containers) for production. Update entire stack with Compose commands.

### Updating Compose Stacks

**Manual method:**
```bash
# On host with docker-compose.yml
cd /path/to/compose
docker-compose pull
docker-compose up -d
```

**Automation options:**
1. **CI/CD pipeline** - Trigger Compose update from CI/CD
2. **Cron job** - Schedule Compose updates on host
3. **Ansible/Terraform** - Update via infrastructure-as-code

---

## Update Safety and Rollback

### Safety Features

**Pre-update validation:**
- Verify image exists in registry
- Check image digest matches expected
- Verify host has disk space
- Test host connectivity
- **Apply validation policies** ← **NEW**

**Graceful shutdown:**
- SIGTERM before SIGKILL
- 10 second grace period
- Allows services to clean up

**Configuration preservation:** ← **ENHANCED**
- All 14 Docker config fields preserved
- Zero configuration drift
- Includes security settings (AppArmor, SELinux)
- Includes advanced settings (tmpfs, ulimits, IPC, etc.)

**Backup before update:** ← **NEW**
- Old container renamed (not removed)
- Available for automatic rollback
- Removed only after successful health check

**Health verification:** ← **IMPROVED**
- 10-second timeout (down from 120s)
- Checks HEALTHCHECK status if defined
- Verifies container still running
- **Automatic rollback if fails** ← **NEW**

### Automatic Rollback

**New in v2:** If update fails health check, DockMon automatically rolls back.

**Rollback triggers:**
- Container fails to start
- Container exits during health check
- HEALTHCHECK reports "unhealthy"
- Container doesn't respond within 10s

**Rollback process:**
1. Stop new (failing) container
2. Remove new container
3. Restore backup (rename back to original name)
4. Start old container
5. Verify old container starts successfully
6. Emit UPDATE_FAILED event
7. Alert fired (if configured)

**Example:**
```
Update postgres:14.1 → 14.2
→ New container starts
→ Health check: postgres fails to accept connections
→ Automatic rollback triggered
→ Old container (14.1) restored
→ Service back online in <30 seconds
→ Alert sent to ops team
```

### Manual Rollback

**If you need to roll back manually (e.g., discovered issue later):**

**Method 1: Via Event Log**
1. Navigate to Event Log
2. Find UPDATE_COMPLETED event for container
3. Note old image digest
4. Stop new container
5. Recreate with old image:
```bash
docker stop container-name
docker rm container-name
docker run -d --name container-name [same config] old-image@sha256:digest
```

**Method 2: Via Docker Images**
```bash
# List images to find old version
docker images | grep container-name

# Stop and remove new container
docker stop container-name
docker rm container-name

# Recreate with old image
docker run -d --name container-name [same config] old-image:old-tag
```

**Or use Docker Compose rollback:**
```bash
# In compose directory
docker-compose down
git checkout previous-version  # If using version control
docker-compose up -d
```

---

## Update History and Logs

### Event Log

All update events are logged in the **Event Log**:

**Event types:**
- `UPDATE_AVAILABLE` - New version detected
- `UPDATE_SKIPPED` - Validation blocked/warned, skipping auto-update ← **NEW**
- `UPDATE_STARTED` - Update process began
- `UPDATE_COMPLETED` - Update succeeded
- `UPDATE_FAILED` - Update failed (includes automatic rollback events) ← **ENHANCED**

**Event details:**
```
Container: nginx
Old image: nginx:1.24.0@sha256:abc123...
New image: nginx:1.24.1@sha256:def456...
Validation: ALLOW
Status: Completed
Duration: 15 seconds (down from 125s)
Timestamp: 2025-10-19 02:15:33 UTC
```

**Validation events:** ← **NEW**
```
Container: postgres
Validation: WARN
Reason: Matched databases pattern: postgres
Action: Auto-update skipped (requires manual confirmation)
```

**Filter events:**
1. Navigate to **Event Log**
2. Filter by event type: "Update"
3. Filter by container name
4. Filter by date range

---

## Best Practices

### Choosing Tracking Mode

**Production:**
- Use **Respect Tag** for critical services (honors your tag choice)
- Use **Minor Updates** for services with good semantic versioning
- **Never** use **Always Latest**

**Staging:**
- Use **Minor Updates** or **Major Updates** to test updates before production
- Good testing ground for update process

**Development:**
- Use **Major Updates** or **Always Latest** for bleeding edge
- Acceptable to have occasional breakage

### Update Validation Strategy

**Recommended Setup:** ← **NEW**

**1. Enable all built-in patterns:**
- Databases: WARN (require confirmation)
- Proxies: WARN (require confirmation)
- Monitoring: WARN (review before updating)
- Critical: WARN (review before updating)

**2. Add custom patterns for your services:**
```
Custom patterns:
- "company-api" (your main API)
- "payment-processor" (critical service)
- "auth-service" (authentication)
```

**3. Set per-container overrides as needed:**
```
Development postgres → Override to ALLOW
Production API → Override to BLOCK
Staging nginx → Keep WARN (default)
```

**4. Use Docker labels for Compose stacks:**
```yaml
version: '3.8'
services:
  database:
    labels:
      - "com.dockmon.update.policy=block"

  cache:
    labels:
      - "com.dockmon.update.policy=allow"
```

### Update Scheduling

**Recommendations:**
- **Production:** Schedule daily check during low-traffic periods (e.g., 02:00 AM)
- **Staging:** Use "Check All Now" button more frequently to catch issues early
- **Development:** Use "Check All Now" button frequently for rapid iteration

**Avoid:**
- ❌ Updating during peak hours
- ❌ Updating all containers simultaneously (use staggered updates)
- ❌ Updating without monitoring

### Testing Strategy

**1. Test in staging first:**
```
1. Enable auto-update on staging containers (Minor Updates mode)
2. Enable validation patterns
3. Monitor for 1 week
4. If stable, enable on production (Respect Tag mode)
```

**2. Canary deployments:**
```
1. Tag one production container with "canary"
2. Enable auto-update for canary only
3. Override validation to ALLOW for canary
4. Monitor canary for 24 hours
5. If stable, enable for remaining production containers
```

**3. Blue-green updates:**
```
1. Deploy new version alongside old (different port)
2. Test new version
3. Switch traffic to new version
4. Remove old version
```

### Monitoring

**After enabling auto-update:**
- Monitor Event Log for update events
- Watch for UPDATE_SKIPPED events (validation warnings) ← **NEW**
- Set up alerts for UPDATE_FAILED events
- Check container health after updates
- Review update frequency (are updates too frequent?)
- Verify configuration preservation (check specialized containers)

**Alert rule examples:**
```
Name: Update Failed
Trigger: Event type = UPDATE_FAILED
Action: Send notification to #ops-alerts

Name: Critical Container Update Skipped
Trigger: Event type = UPDATE_SKIPPED, Container tag = critical
Action: Send notification to #ops-review
```

---

## Troubleshooting

### Update Not Detected

**Symptom:** New version exists but DockMon says "Up to date"

**Check:**
1. When was last check? (May not have run yet)
2. Tracking mode correct? (If mode=Respect Tag with fixed tag, won't detect minor version updates)
3. Image tag format correct? (e.g., `nginx:1.24.0` not `nginx:latest`)
4. Registry accessible? (Check network, authentication)

**Solution:**
- Click **Check for Updates Now**
- Verify tracking mode setting
- Check registry credentials

### Update Skipped (Validation)

**Symptom:** Update available but auto-update not triggered ← **NEW**

**Check:**
1. Open Event Log
2. Look for UPDATE_SKIPPED event
3. Check validation reason

**Common reasons:**
- "Matched databases pattern: postgres" → Database protection active
- "Matched proxies pattern: nginx" → Proxy protection active
- "Per-container policy: block" → Container specifically blocked

**Solutions:**
- **Expected behavior:** Review update notes, then click "Update Now" and confirm
- **Override global pattern:** Set per-container policy to ALLOW
- **Disable category:** Settings → Updates → Toggle category off
- **Remove custom pattern:** Delete custom pattern if no longer needed

### Update Failed

**Symptom:** Update triggered but failed with error

**Common errors:**

#### "Image pull failed: authentication required"

**Cause:** Private image requires registry authentication

**Solution:** Configure registry credentials in Settings → Updates → Registry Authentication

#### "Container failed to start after update"

**Cause:** New image has breaking changes or configuration incompatibility

**Solution:**
1. Check Event Log for failure details
2. Verify automatic rollback occurred ← **NEW**
3. Check container logs: `docker logs container-name`
4. Investigate breaking changes
5. Update configuration before retrying

#### "Health check failed after update"

**Cause:** New container didn't pass health verification ← **NEW**

**Solution:**
1. Verify automatic rollback restored old container
2. Check why new version failed health check
3. Test new version manually in staging
4. Fix issues before enabling auto-update

#### "Timeout waiting for image pull"

**Cause:** Large image, slow network, or registry issues

**Solution:**
- Check network connectivity
- Check registry status
- Large images may take longer than health check timeout (this is OK - timeout is for health verification, not image pull)

### Update Loop

**Symptom:** Container updates repeatedly, over and over

**Cause:** New image digest changes frequently or is unstable

**Solution:**
1. Check if image is using `:latest` tag (don't use in production)
2. Switch to specific version tag
3. Disable auto-update temporarily
4. Investigate why image digests are changing

### Configuration Lost After Update

**Symptom:** Container missing settings after update (e.g., tmpfs, custom DNS) ← **NEW**

**This should NOT happen** in v2. If it does:

**Check:**
1. What configuration was lost? (tmpfs, ulimits, DNS, etc.)
2. Was it set via docker run or docker-compose?
3. Check Event Log for UPDATE_COMPLETED event

**Report:**
If configuration is lost, this is a bug. Please report:
- Container name
- Lost configuration (specific field)
- Event Log entry for the update
- Docker inspect output before/after update

**Workaround:**
1. Manually recreate container with lost config
2. Disable auto-update until bug is resolved

---

## Migration from Manual Updates

### Step 1: Inventory Current State

**Identify containers:**
```
1. Which containers do you update manually?
2. How often do you update them?
3. What's your current testing process?
4. Which are critical? (databases, proxies, etc.)
```

### Step 2: Configure Validation Policies ← **NEW**

**Before enabling auto-update:**
```
1. Navigate to Settings → Container Updates → Update Validation Policies
2. Enable all built-in categories (Databases, Proxies, Monitoring, Critical)
3. Add custom patterns for your critical services
4. Test validation by clicking "Update Now" on protected container
   → Should show confirmation dialog
```

### Step 3: Start with Staging

**Enable auto-update on staging:**
```
1. Filter by tag: "staging"
2. Bulk Actions → Set Auto-Update
3. Enable: Yes, Mode: Minor Updates
4. Validation: Will use global patterns (WARN for critical containers)
5. Monitor for 1 week
```

### Step 4: Expand to Production

**Gradual rollout:**
```
Week 1: Enable for non-critical production containers (Respect Tag mode)
        → Review validation policies, add custom patterns as needed
Week 2: Enable for important containers (Respect Tag mode)
        → Per-container overrides for special cases
Week 3: Enable for critical containers (Respect Tag mode)
        → Keep validation on WARN (manual confirmation required)
Week 4: Review and adjust
        → Check Event Log for UPDATE_SKIPPED events
        → Optimize validation patterns
```

### Step 5: Optimize

**Review update frequency:**
- Are updates too frequent? Adjust tracking mode (Major Updates → Minor Updates)
- Are updates too infrequent? Adjust tracking mode (Respect Tag → Minor Updates)
- Are too many updates skipped? Review validation patterns
- Use "Check All Now" button to trigger checks outside of daily schedule when needed

---

## Related Documentation

- [Container Operations](Container-Operations) - Manual container updates
- [Health Checks](Health-Checks) - Health check integration
- [Bulk Operations](Bulk-Operations) - Bulk auto-update configuration
- [Alert Rules](Alert-Rules) - Alert on update failures

---

## Need Help?

- [Troubleshooting Guide](Troubleshooting)
- [GitHub Discussions](https://github.com/darthnorse/dockmon/discussions)
- [Report an Issue](https://github.com/darthnorse/dockmon/issues)
