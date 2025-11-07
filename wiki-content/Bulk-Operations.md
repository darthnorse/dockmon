# Bulk Operations

Perform actions on multiple containers simultaneously with DockMon v2's powerful bulk operation system.

---

## Overview

Bulk operations allow you to manage multiple containers at once, saving time and reducing repetitive tasks. DockMon v2's bulk operation system features real-time progress tracking, intelligent rate limiting, and detailed error reporting.

**Key features:**
- **Multi-container selection** - Select containers via checkboxes with filtering
- **Parallel execution** - Actions run concurrently with rate limiting per host
- **Real-time progress** - Live WebSocket updates showing operation status
- **Partial success handling** - Some containers can succeed while others fail
- **Detailed error reporting** - See exactly which containers failed and why
- **Operation history** - Track completed bulk operations

**Supported operations:**
- Start containers
- Stop containers
- Restart containers
- Add tags
- Remove tags
- Enable/disable auto-restart
- Enable/disable auto-update
- Set desired state

---

## Starting a Bulk Operation

### Step 1: Enable Bulk Select Mode

1. Navigate to the **Container Dashboard**
2. Look for the **Bulk Select** toggle in the toolbar (checkbox icon)
3. Click to enable bulk select mode
4. Checkboxes appear next to each container

**Tip:** Use filters (tags, host, search) to narrow down containers before selecting.

### Step 2: Select Containers

**Method 1: Manual Selection**
- Click checkboxes next to containers you want to operate on
- Selected count appears in the toolbar (e.g., "5 selected")
- Click again to deselect

**Method 2: Select All (Filtered)**
- Click **Select All** button in toolbar
- Selects all containers currently visible (respects filters)
- Maximum: 100 containers at once (safety limit)

**Method 3: Tag-Based Selection**
1. Filter by tag(s) first
2. Click **Select All**
3. All containers with those tags are selected

**Example:** Select all production containers
```
1. Filter by tag: "production"
2. Click "Select All"
3. → 45 containers selected
```

### Step 3: Choose Bulk Action

1. Click the **Bulk Actions** dropdown button
2. Select the action you want to perform:
   - **Start** - Start all selected containers
   - **Stop** - Stop all selected containers
   - **Restart** - Restart all selected containers
   - **Add Tags** - Add tag(s) to all selected containers
   - **Remove Tags** - Remove tag(s) from all selected containers
   - **Set Auto-Restart** - Enable/disable auto-restart
   - **Set Auto-Update** - Enable/disable auto-update
   - **Set Desired State** - Set desired state (should_run, on_demand)

3. If the action requires parameters (tags, settings), a dialog appears
4. Enter parameters and click **Confirm**

### Step 4: Monitor Progress

**Real-time status panel:**
- Appears at the bottom of the screen when operation starts
- Shows overall progress (e.g., "15/45 completed")
- Lists containers with their current status:
  - **Queued** (gray) - Waiting to process
  - **Running** (blue) - Currently executing
  - **Success** (green) - Completed successfully
  - **Error** (red) - Failed with error message
  - **Skipped** (yellow) - Skipped (already in desired state)

**Progress updates:**
- Container status updates in real-time via WebSocket
- No need to refresh the page
- Operation continues in background if you navigate away

### Step 5: Review Results

**When operation completes:**
- Final status shows: Completed, Partial, or Failed
- **Completed** - All containers succeeded
- **Partial** - Some succeeded, some failed
- **Failed** - All containers failed

**Summary statistics:**
```
Total: 45 containers
Success: 42 containers
Errors: 2 containers
Skipped: 1 container
```

**Detailed results:**
- Expand each container to see status and error message
- Click container name to jump to container details
- Export results (optional, if implemented)

---

## Bulk Operation Types

### Start Containers

**Action:** Start all selected stopped containers

**Behavior:**
- Containers already running are skipped
- Containers start in parallel (rate limited)
- Uses Docker's native start command

**Use cases:**
- Start all containers after maintenance
- Resume services after backup
- Start all containers in a specific environment

**Example:**
```
1. Filter by tag: "staging"
2. Filter by state: "exited"
3. Select all → 12 containers
4. Bulk Actions → Start
5. → 12 containers start in parallel
```

### Stop Containers

**Action:** Stop all selected running containers

**Behavior:**
- Sends SIGTERM, waits 10 seconds, then SIGKILL
- Containers already stopped are skipped
- Graceful shutdown with timeout

**Use cases:**
- Stop all containers before host maintenance
- Stop all containers in an environment for backup
- Emergency stop for troubleshooting

**Example:**
```
1. Filter by host: "Dev-Server"
2. Select all running containers → 25 containers
3. Bulk Actions → Stop
4. → All containers stop gracefully
```

**Warning:** Stopping critical containers may cause downtime. Double-check your selection before confirming.

### Restart Containers

**Action:** Restart all selected containers

**Behavior:**
- Equivalent to stop + start
- 10 second graceful shutdown timeout
- Containers restart in parallel
- Containers already stopped are started

**Use cases:**
- Apply configuration changes (environment variables, volumes)
- Clear container state issues
- Refresh services after image updates

**Example:**
```
1. Filter by tag: "web-tier"
2. Select all → 8 containers
3. Bulk Actions → Restart
4. → All web-tier containers restart
```

**Tip:** For updates, consider using [Automatic Updates](Automatic-Updates) instead of manual restart.

### Add Tags

**Action:** Add one or more tags to selected containers

**Behavior:**
- Tags are added to existing tags (not replaced)
- Duplicate tags are ignored
- Custom tags are stored in DockMon database

**Use cases:**
- Tag newly deployed containers
- Add organizational tags in bulk
- Mark containers for maintenance

**Dialog options:**
- **Tags to add:** Comma-separated list (e.g., `production,critical`)
- **Tag validation:** Alphanumeric, hyphens, underscores only

**Example:**
```
1. Filter by compose project: "compose:myapp"
2. Select all → 5 containers
3. Bulk Actions → Add Tags
4. Enter: "production,critical"
5. → All containers tagged with "production" and "critical"
```

See [Container Tagging](Container-Tagging) for tag management details.

### Remove Tags

**Action:** Remove one or more tags from selected containers

**Behavior:**
- Only removes custom tags (not automatic tags)
- Tags not present are ignored
- Container keeps other tags

**Use cases:**
- Remove obsolete tags
- Change container categorization
- Remove temporary tags

**Dialog options:**
- **Tags to remove:** Comma-separated list

**Example:**
```
1. Filter by tag: "needs-update"
2. Select all → 10 containers
3. Bulk Actions → Remove Tags
4. Enter: "needs-update"
5. → Tag removed from all containers
```

### Set Auto-Restart

**Action:** Enable or disable auto-restart for selected containers

**Behavior:**
- Enables/disables DockMon's auto-restart feature
- Independent of Docker's restart policy
- Settings stored in DockMon database

**Dialog options:**
- **Enable auto-restart:** Yes/No
- **Max retries:** Number of restart attempts (default: 3)
- **Retry delay:** Seconds between retries (default: 30)

**Use cases:**
- Enable auto-restart for all production containers
- Disable auto-restart during maintenance
- Configure consistent restart policies

**Example:**
```
1. Filter by tag: "production"
2. Select all → 30 containers
3. Bulk Actions → Set Auto-Restart
4. Enable: Yes, Max retries: 5, Delay: 60s
5. → All production containers have auto-restart enabled
```

See [Auto-Restart](Auto-Restart) for configuration details.

### Set Auto-Update

**Action:** Enable or disable automatic updates for selected containers

**Behavior:**
- Enables/disables DockMon's auto-update feature
- Configures floating tag mode (exact, minor, major, latest)
- Updates run on schedule (daily by default)

**Dialog options:**
- **Enable auto-update:** Yes/No
- **Floating tag mode:**
  - `exact` - Only update to exact tag (no floating)
  - `minor` - Update to latest minor version (e.g., 1.2.x → 1.2.5)
  - `major` - Update to latest major version (e.g., 1.x → 1.9)
  - `latest` - Always update to :latest

**Use cases:**
- Enable auto-update for development containers
- Configure safe update strategy for production
- Disable auto-update for stable containers

**Example:**
```
1. Filter by tag: "staging"
2. Select all → 20 containers
3. Bulk Actions → Set Auto-Update
4. Enable: Yes, Mode: minor
5. → All staging containers auto-update to latest minor version
```

See [Automatic Updates](Automatic-Updates) for details.

### Set Desired State

**Action:** Set desired container state for monitoring

**Behavior:**
- Sets expected state for DockMon monitoring
- Used for auto-restart decisions
- Options: should_run, on_demand, unspecified

**Dialog options:**
- **Desired State:**
  - `should_run` - Container should always be running (auto-restart if stopped)
  - `on_demand` - Container runs only when needed (don't auto-restart)
  - `unspecified` - No desired state (default)

**Use cases:**
- Mark production containers as should_run
- Mark maintenance containers as on_demand
- Configure monitoring expectations

**Example:**
```
1. Filter by tag: "critical"
2. Select all → 15 containers
3. Bulk Actions → Set Desired State
4. State: should_run
5. → All critical containers marked as should_run
```

---

## Rate Limiting and Performance

### Per-Host Rate Limiting

DockMon enforces **5 concurrent operations per host** to prevent overloading Docker daemons.

**Why rate limiting?**
- Prevents Docker API overload
- Avoids network saturation
- Maintains system stability
- Reduces error rates

**How it works:**
```
Selected: 50 containers across 5 hosts
→ Each host processes max 5 containers at once
→ Total: Up to 25 concurrent operations
→ Remaining containers queue until slots available
```

**Example timeline:**
```
0s:  25 containers start processing (5 per host)
2s:  10 containers complete → 10 more start
4s:  15 more complete → 15 more start
6s:  All 50 containers complete
```

### Operation Timeouts

**Per-container timeout:** 60 seconds

**Behavior:**
- If operation takes >60s, it's marked as error
- Prevents hung operations from blocking queue
- Rare in practice (most operations complete in <5s)

### Scalability Limits

**Maximum containers per operation:** 100

**Reason:** UI/UX performance and WebSocket message size

**Workaround for >100 containers:**
1. Run multiple smaller operations
2. Use tag filtering to create logical groups
3. Contact support for bulk operation API (no UI limits)

---

## Error Handling

### Partial Success

**Scenario:** 45 containers selected, 42 succeed, 3 fail

**Behavior:**
- Operation completes with status "Partial"
- Successful containers show green checkmarks
- Failed containers show red X with error messages
- You can retry failed containers individually

**Example errors:**
```
Container "postgres": Error - Container not found (deleted during operation)
Container "redis": Error - Connection timeout to host
Container "nginx": Skipped - Already running
```

### Common Errors

#### "Container not found"

**Cause:** Container was deleted between selection and execution

**Solution:** Refresh container list and retry

#### "Connection timeout to host"

**Cause:** Host is offline or network issues

**Solution:** Check host connectivity, retry when online

#### "Permission denied"

**Cause:** Docker socket permissions issue

**Solution:** Check DockMon's Docker socket access

#### "Already in desired state"

**Status:** Skipped (not an error)

**Cause:** Container is already running (for start), stopped (for stop), etc.

**Solution:** No action needed - this is expected behavior

### Retry Failed Operations

**Option 1: Retry Individual Containers**
1. Review failed containers in results panel
2. Click container name to open details
3. Manually execute action (start, stop, etc.)

**Option 2: Retry Failed Group**
1. Note which containers failed
2. Create new bulk operation with only those containers
3. Execute

**Option 3: Investigate and Fix**
1. Check error messages
2. Fix underlying issues (host connectivity, permissions, etc.)
3. Retry

---

## Best Practices

### Before Starting Bulk Operations

**1. Double-check selection**
- Review selected containers carefully
- Use filters to narrow scope
- Check selected count matches expectations

**2. Test on small subset first**
- Select 2-3 containers
- Run operation
- Verify behavior
- Then select all

**3. Consider impact**
- Will this cause downtime?
- Do you have a rollback plan?
- Is there a maintenance window?

**4. Use appropriate filters**
- Tag filtering prevents mistakes
- Host filtering isolates impact
- State filtering ensures correct targets

### During Bulk Operations

**1. Monitor progress**
- Watch for unexpected errors
- Check error messages immediately
- Cancel operation if something looks wrong (refresh page)

**2. Don't navigate away**
- Stay on page to monitor progress
- Operations continue in background but you lose visibility

**3. Note failed containers**
- Save error messages for troubleshooting
- Check why failures occurred

### After Bulk Operations

**1. Verify results**
- Check container states match expectations
- Review error messages
- Test critical services

**2. Clean up**
- Remove temporary tags (if used)
- Update documentation
- Note any issues for future operations

**3. Document changes**
- Record what was changed
- Note any issues encountered
- Update runbooks if needed

---

## Use Cases and Examples

### Example 1: Maintenance Window - Restart All Services

**Scenario:** Monthly maintenance requires restarting all production containers

**Steps:**
```
1. Announce maintenance window
2. Filter by tag: "production"
3. Select all → 50 containers
4. Bulk Actions → Restart
5. Monitor progress (expect 2-3 minutes)
6. Verify services are healthy
7. Announce completion
```

**Pro tip:** Create a checklist for monthly maintenance to ensure consistency.

### Example 2: Emergency Stop - Database Corruption

**Scenario:** Database corruption detected, need to stop all apps accessing DB immediately

**Steps:**
```
1. Filter by tag: "uses-postgres"
2. Select all → 15 containers
3. Bulk Actions → Stop
4. → All apps stop within 10 seconds
5. Fix database corruption
6. Restart apps with Bulk Actions → Start
```

**Time saved:** 5 minutes vs. stopping 15 containers manually

### Example 3: New Deployment - Tag and Configure

**Scenario:** Deployed 20 new microservices, need to tag and configure them

**Steps:**
```
1. Filter by compose project: "compose:ecommerce-v2"
2. Select all → 20 containers
3. Bulk Actions → Add Tags
   - Enter: "production,v2,needs-monitoring"
4. Wait for completion
5. Keep same selection
6. Bulk Actions → Set Auto-Restart
   - Enable: Yes, Max retries: 5, Delay: 60s
7. Keep same selection
8. Bulk Actions → Set Auto-Update
   - Enable: Yes, Mode: minor
9. Done - all containers tagged and configured
```

**Time saved:** 15 minutes vs. configuring 20 containers individually

### Example 4: Environment Promotion - Staging to Production

**Scenario:** Promote staging containers to production

**Steps:**
```
1. Filter by tag: "staging-ready"
2. Select all → 12 containers
3. Bulk Actions → Add Tags
   - Enter: "production"
4. Keep same selection
5. Bulk Actions → Remove Tags
   - Enter: "staging-ready"
6. Keep same selection
7. Bulk Actions → Set Auto-Restart
   - Enable: Yes
8. Done - containers promoted to production
```

### Example 5: Clean Up Old Tags

**Scenario:** Remove "needs-update" tag from containers that have been updated

**Steps:**
```
1. Filter by tag: "needs-update"
2. Review list to verify all are updated
3. Select all → 25 containers
4. Bulk Actions → Remove Tags
   - Enter: "needs-update"
5. → Tag removed from all containers
6. Tag filter clears (no containers have that tag anymore)
```

---

## Troubleshooting

### Bulk Operation Not Starting

**Symptom:** Click bulk action but nothing happens

**Check:**
1. Are containers selected? (Check selected count)
2. Is operation already running? (Check for status panel)
3. Are you connected to WebSocket? (Check network tab)

**Solution:** Refresh page and retry

### Operation Stuck at "Running"

**Symptom:** Operation shows running but no progress for >5 minutes

**Possible causes:**
1. WebSocket connection lost
2. Backend crashed
3. Docker daemon unresponsive on remote host

**Solution:**
1. Refresh page to check actual status
2. Check DockMon backend logs: `docker logs dockmon`
3. Check host connectivity
4. Contact support if issue persists

### Some Containers Always Fail

**Symptom:** Same containers fail in every bulk operation

**Check:**
1. Error message details
2. Host connectivity
3. Container state (maybe deleted?)
4. Permissions

**Solution:** Fix underlying issue before retrying

### Progress Updates Not Showing

**Symptom:** Operation started but progress panel is blank

**Cause:** WebSocket connection issue

**Solution:**
1. Check browser console for WebSocket errors
2. Refresh page
3. Check if WebSocket is blocked by firewall/proxy

---

## Keyboard Shortcuts

**Bulk select mode:**
- `b` - Toggle bulk select mode
- `a` - Select all (when in bulk mode)
- `Escape` - Clear selection and exit bulk mode

**During operation:**
- `Escape` - Close status panel (operation continues in background)

---

## Related Documentation

- [Container Tagging](Container-Tagging) - Organize containers for bulk selection
- [Container Operations](Container-Operations) - Individual container actions
- [Automatic Updates](Automatic-Updates) - Auto-update configuration
- [Auto-Restart](Auto-Restart) - Auto-restart configuration

---

## API Reference

Bulk operations can also be triggered via API for automation:

**Endpoint:** `POST /api/v2/batch`

**Request body:**
```json
{
  "scope": "container",
  "action": "restart",
  "container_ids": ["abc123", "def456", "ghi789"],
  "params": {}
}
```

**Response:**
```json
{
  "job_id": "job_abc123def456",
  "status": "queued"
}
```

**Check status:** `GET /api/v2/batch/{job_id}`

See API documentation for full details.

---

## Need Help?

- [Troubleshooting Guide](Troubleshooting)
- [GitHub Discussions](https://github.com/darthnorse/dockmon/discussions)
- [Report an Issue](https://github.com/darthnorse/dockmon/issues)
