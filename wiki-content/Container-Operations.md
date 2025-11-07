# Container Operations

DockMon provides comprehensive container management capabilities, from basic lifecycle operations to advanced batch actions and detailed inspection.

## Overview

Container operations in DockMon allow you to:
- **Control container lifecycle** (start, stop, restart)
- **View real-time logs** from running containers
- **Inspect configurations** and environment variables
- **Monitor resource usage** (CPU, memory, network I/O)
- **Manage container tags** for organization
- **Configure policies** (auto-restart, desired state, auto-update)
- **Perform bulk operations** on multiple containers simultaneously

## Container Table

The container table is your primary interface for viewing and managing containers.

### Columns

| Column | Description |
|--------|-------------|
| **Select** | Checkbox for bulk operations |
| **Status** | Visual indicator of container state (running, stopped, etc.) |
| **Name** | Container name with clickable tags |
| **Policy** | Auto-restart, desired state, and auto-update icons |
| **Alerts** | Active alert count by severity (critical/error/warning/info) |
| **Updates** | Update availability indicator |
| **Host** | Docker host where container runs |
| **Uptime** | Time since container creation |
| **CPU%** | Current CPU usage percentage |
| **RAM** | Current memory usage |
| **Actions** | Start, stop, restart, logs, view details buttons |

### Status Indicators

Containers display color-coded status icons:

| Status | Color | Icon | Description |
|--------|-------|------|-------------|
| **Running** | Green | Filled circle | Container is actively running |
| **Stopped/Exited** | Red | Filled circle | Container has exited |
| **Created** | Gray | Filled circle | Container created but never started |
| **Paused** | Yellow | Filled circle | Container is paused (frozen) |
| **Restarting** | Blue | Spinning circle | Container is currently restarting |
| **Dead** | Red | Filled circle | Container is in dead state (unrecoverable) |

### Policy Icons

Three icons indicate container automation policies:

**Auto-Restart Icon**:
- **Blue refresh icon**: Auto-restart enabled
- **Gray crossed-out refresh**: Auto-restart disabled
- Hover for tooltip with current status

**Desired State Icon**:
- **Green filled play**: Should be running (and currently running)
- **Black play**: Should be running (but currently stopped)
- **Yellow warning triangle**: Should be running but is exited (attention needed!)
- **Gray clock**: On-demand (no desired state)

**Auto-Update Icon**:
- **Amber package icon**: Auto-update enabled
- No icon: Auto-update disabled
- Hover for tooltip with current status

## Basic Operations

### Start Container

**Requirements**: Container must be in stopped/exited/created state

**Methods**:
1. **Quick action**: Click green **Play** icon in Actions column
2. **Details modal**: Open container → Actions tab → Start button
3. **Bulk action**: Select multiple containers → Bulk Actions bar → Start

**Behavior**:
- Starts container using Docker API
- Updates status in real-time via WebSocket
- Shows success/error toast notification
- If auto-restart enabled, monitoring begins immediately

### Stop Container

**Requirements**: Container must be running

**Methods**:
1. **Quick action**: Click red **Stop** icon in Actions column
2. **Details modal**: Open container → Actions tab → Stop button
3. **Bulk action**: Select multiple containers → Bulk Actions bar → Stop

**Behavior**:
- Sends SIGTERM signal (graceful shutdown)
- Waits 10 seconds for graceful exit
- Forces stop (SIGKILL) if container doesn't exit
- Updates status in real-time via WebSocket

**Note**: Stopping a container with `desired_state: should_run` will trigger a warning icon, as the container will likely be auto-restarted if auto-restart is enabled.

### Restart Container

**Requirements**: Container must be running

**Methods**:
1. **Quick action**: Click blue **Restart** icon in Actions column
2. **Details modal**: Open container → Actions tab → Restart button
3. **Bulk action**: Select multiple containers → Bulk Actions bar → Restart

**Behavior**:
- Stops container gracefully (SIGTERM + 10s timeout)
- Starts container with same configuration
- Useful for applying environment changes or clearing memory leaks
- Resets uptime counter

**Use cases**:
- Apply configuration changes that require restart
- Clear memory leaks in long-running containers
- Recover from hung state
- Force reload of application code

## Container Details

### Opening Details View

**Default behavior** (Simplified Workflow enabled):
- Click container card to open full-screen details view with all tabs

**Alternative behavior** (Simplified Workflow disabled):
- Click container card to open drawer (quick view from the side)
- The drawer provides quick access to container information

**Toggle workflow**: Settings → Dashboard → Simplified Workflow

### Details Tabs

#### Info Tab
Displays comprehensive container information:

**Container Metadata**:
- Container ID (12-character short ID)
- Image name and tag
- Created timestamp
- Host assignment

**Configuration**:
- Environment variables (with masking for sensitive values)
- Volumes and mounts
- Network settings
- Port mappings
- Labels

**Runtime State**:
- Current status
- Exit code (if stopped)
- PID (process ID)
- Restart count

#### Logs Tab
Real-time container log viewer:

**Features**:
- **Live streaming**: Logs update in real-time via WebSocket
- **Tail options**: Last 100, 500, 1000 lines, or all
- **Search/filter**: Find specific log entries
- **Copy to clipboard**: Export logs for analysis
- **Auto-scroll**: Toggle automatic scrolling to latest entries
- **Timestamps**: Show/hide log timestamps
- **Color coding**: ANSI color support for formatted logs

**Best practices**:
- Start with 100 lines for quick debugging
- Use search to find error patterns
- Disable auto-scroll when analyzing historical logs
- Copy logs before container restart (logs are ephemeral)

#### Events Tab
Container event history:

**Displays**:
- All events for this specific container
- Event type (start, stop, die, restart, etc.)
- Timestamp with millisecond precision
- Exit codes (for stop/die events)
- Context information

**Useful for**:
- Diagnosing crash loops
- Understanding restart patterns
- Audit trail for container lifecycle

#### Tags Tab
Container tag management:

**Features**:
- View all tags (derived + custom)
- Add custom tags
- Remove custom tags
- Tag autocomplete (suggests existing tags)

**Tag types**:
- **Derived tags** (automatic, cannot be removed):
  - Docker Compose project tags (from `com.docker.compose.project` label)
  - Docker Swarm service tags (from `com.docker.swarm.service.name` label)
- **Custom tags** (user-defined, can be removed):
  - Any user-added tags via UI or bulk operations

**Use cases**:
- Organize containers by environment (production, staging, dev)
- Group by purpose (web, database, cache)
- Mark for specific alert rules
- Enable tag-based filtering in dashboard

#### Health Check Tab
Configure HTTP/HTTPS health checks:

**Configuration**:
- Endpoint URL (e.g., `http://localhost:8080/health`)
- Check interval (seconds)
- Timeout (seconds)
- Failure threshold (consecutive failures before action)
- Auto-restart on failure (toggle)

**Status**:
- Last check time
- Last check result (success/failure)
- Failure count
- Next check time (countdown)

**Use cases**:
- Monitor web application availability
- Auto-restart services that hang but don't crash
- Detect and recover from deadlocks
- Ensure critical services remain responsive

#### Auto-Restart Tab
Configure automatic restart behavior:

**Settings**:
- **Enable/Disable**: Toggle auto-restart for this container
- **Max retries**: Maximum restart attempts before giving up (0-10)
- **Retry delay**: Seconds to wait between restart attempts (5-300)
- **Backoff strategy**: Linear or exponential delay increase

**Status**:
- Current restart attempt count
- Last restart time
- Next retry time (if in retry loop)

**Best practices**:
- **Always-on services**: Enable with 5+ retries
- **One-shot tasks**: Disable auto-restart
- **Flaky services**: Use exponential backoff with longer delays
- **Critical infrastructure**: Enable with alerts on failures

#### Updates Tab
Container image update management:

**Displays**:
- Current image tag
- Available image tag (if update exists)
- Last update check time
- Update history

**Actions**:
- Check for updates now
- Update to latest version
- View update changelog (if available)
- Configure auto-update settings

**Auto-update configuration**:
- **Enable auto-update**: Automatically update when new version available
- **Floating tag mode**: How to handle version tags
  - `allow`: Allow updates for floating tags (e.g., `latest`, `stable`)
  - `prevent`: Skip updates for floating tags (only update pinned versions)
- **Update schedule**: When to check and apply updates

## Bulk Operations

Select multiple containers to perform batch actions efficiently.

### Selecting Containers

**Methods**:
1. **Individual**: Click checkbox next to each container
2. **All visible**: Click checkbox in table header
3. **Filter + select all**: Apply search/filter → Select all visible

**Selection count**: Displayed in floating bulk action bar

### Bulk Action Bar

When containers are selected, a bar appears at the bottom with:

**Actions**:
- **Start**: Start all selected stopped containers
- **Stop**: Stop all selected running containers
- **Restart**: Restart all selected running containers
- **Clear selection**: Deselect all containers

**Tag management**:
- **Add tags**: Apply tags to all selected containers
- **Remove tags**: Remove tags from all selected containers

**Policy management**:
- **Enable auto-restart**: Turn on auto-restart for all selected
- **Disable auto-restart**: Turn off auto-restart for all selected
- **Set desired state**: Set to "Should Run" or "On-Demand"
- **Configure auto-update**: Enable/disable for all selected

### Batch Job Progress

Bulk operations run as background jobs with progress tracking:

**Progress panel displays**:
- Overall progress percentage
- Succeeded container count
- Failed container count
- Per-container status (pending, running, success, failed)
- Error messages for failures

**Features**:
- Real-time progress updates
- Cancellable operations
- Detailed error reporting
- Success/failure summary

**Best practices**:
- Start with small batches (5-10 containers) to verify behavior
- Monitor first batch job before scheduling larger operations
- Review failed containers and retry manually if needed
- Don't close browser during batch operations (job continues server-side)

## Search and Filtering

### Global Search

The search box filters containers by:
- Container name
- Image name
- Host name
- Tags

**Examples**:
- `nginx` - Find all nginx containers
- `production` - Find all containers tagged "production"
- `web-server` - Find containers on host named "web-server"

### Advanced Filtering

**Filter by status**:
- Click column header → Sort by status
- Groups running/stopped containers together

**Filter by host**:
- Click host name in container row
- Shows only containers on that host
- URL updates to include `?hostId=<id>` for shareable links

**Filter by tag**:
- Click tag chip on container
- Shows only containers with that tag
- Useful for environment-based views

## Common Workflows

### Troubleshooting a Crashed Container

1. **Identify the problem**:
   - Check status column for exit code
   - Look for red "exited" status
   - Check alerts for error notifications

2. **Review logs**:
   - Open container details → Logs tab
   - Search for "error", "exception", "fatal"
   - Note timestamp of last successful operation

3. **Inspect configuration**:
   - Info tab → Check environment variables
   - Verify volume mounts are correct
   - Check port conflicts

4. **Review events**:
   - Events tab → Look for restart loops
   - Check frequency of crashes
   - Note exit codes

5. **Fix and restart**:
   - Address root cause (config, resources, dependencies)
   - Click Restart to test fix
   - Monitor logs for successful startup

### Rolling Restart for Updates

When config changes require restart without downtime:

1. **Tag containers** by instance role (e.g., "web-1", "web-2", "web-3")
2. **Restart in batches**:
   - Select containers with tag "web-1"
   - Bulk Actions → Restart
   - Wait for completion and health check success
   - Repeat for "web-2", "web-3", etc.

3. **Monitor**:
   - Watch for successful startup in logs
   - Verify health checks pass
   - Check error rates in application metrics

### Maintenance Window

Prepare for scheduled maintenance:

1. **Enable blackout window** (Settings → Alerts → Blackout Windows)
2. **Stop non-critical services**:
   - Filter by tag "non-critical"
   - Select all
   - Bulk Actions → Stop

3. **Perform maintenance** (database migration, host updates, etc.)

4. **Restart services**:
   - Select all stopped containers
   - Bulk Actions → Start
   - Verify all containers started successfully

5. **Disable blackout window** when complete

## Best Practices

### Container Lifecycle

**DO**:
- Use descriptive container names (include purpose and instance number)
- Tag containers by environment, purpose, and team
- Set desired state for always-on services
- Enable auto-restart for critical services
- Monitor logs during first 5 minutes after start

**DON'T**:
- Restart containers without checking logs first
- Stop containers without understanding impact on dependent services
- Enable auto-restart for one-shot jobs or migration tasks
- Ignore yellow warning icons (desired state mismatch)

### Log Management

**DO**:
- Use structured logging (JSON) in applications for easy parsing
- Implement log rotation in containers (prevent disk fill)
- Copy important logs before container restart
- Search logs before requesting full output (performance)

**DON'T**:
- Stream all logs for high-traffic containers (resource intensive)
- Store sensitive data in logs (passwords, tokens, PII)
- Rely on logs as persistent storage (use external logging service)

### Tag Organization

**DO**:
- Use consistent tag naming (lowercase, hyphen-separated)
- Create tag hierarchy (environment → purpose → instance)
- Document tag meanings in team wiki
- Remove obsolete tags to keep system clean

**DON'T**:
- Create too many tags (hard to manage)
- Use special characters in tags (can break filtering)
- Tag every container with every category (loses meaning)

## Troubleshooting

### Container Won't Start

**Possible causes**:
1. **Port conflict**: Another container using same port
2. **Volume conflict**: Volume mounted by another container
3. **Missing dependency**: Database or service not ready
4. **Resource limits**: Insufficient CPU/RAM on host
5. **Image missing**: Image pulled incorrectly or deleted

**Solutions**:
- Check logs for specific error message
- Review Info tab → Port mappings for conflicts
- Verify host resource availability
- Check Events tab for repeated crash pattern

### Container Stuck in Restarting State

**Possible causes**:
1. **Crash loop**: Application crashes immediately after start
2. **Auto-restart loop**: Auto-restart enabled with low retry delay
3. **Health check failure**: Container stops due to failed health checks

**Solutions**:
- Disable auto-restart temporarily
- Check logs for error during startup
- Review health check configuration (URL, timeout, threshold)
- Increase retry delay to allow debugging time

### Logs Not Updating

**Possible causes**:
1. **WebSocket disconnected**: Connection lost to backend
2. **Container stopped**: Can't stream logs from stopped container
3. **Browser tab inactive**: Browser throttles inactive tabs
4. **Log buffer full**: Too many logs, reaching rate limit

**Solutions**:
- Check WebSocket connection indicator (green dot in header)
- Verify container is running
- Refresh browser tab
- Reduce log tail size (100 instead of 1000)

## Related Documentation

- [Dashboard](Dashboard.md) - Dashboard overview and customization
- [Auto-Restart](Auto-Restart.md) - Detailed auto-restart configuration
- [Blackout Windows](Blackout-Windows.md) - Schedule maintenance periods
- [Alerts](https://github.com/darthnorse/dockmon/wiki/Alerts) - Alert rules and notifications
