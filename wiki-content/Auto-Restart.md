# Auto-Restart

DockMon's intelligent auto-restart system automatically recovers containers from failures, ensuring high availability for critical services.

## Overview

The auto-restart feature provides:
- **Per-container configuration** - Fine-grained control over which containers auto-restart
- **Configurable retry logic** - Set maximum attempts and delays
- **Exponential backoff** - Prevent restart storms during persistent failures
- **Integration with alerts** - Get notified when containers repeatedly fail
- **Desired state tracking** - Ensure containers stay in intended state
- **Global defaults** - Set system-wide auto-restart behavior

## How It Works

### Detection

DockMon continuously monitors container states via Docker events and periodic polling. When a container transitions to an exited, dead, or stopped state, the auto-restart system evaluates whether to attempt recovery.

### Decision Process

For each stopped container, DockMon checks:

1. **Is auto-restart enabled for this container?**
   - Checks database configuration
   - Falls back to global default if not explicitly configured

2. **Has max retry limit been reached?**
   - Tracks attempt count per container
   - Resets counter after successful restart
   - Gives up after max attempts exceeded

3. **Is retry delay satisfied?**
   - Enforces minimum delay between attempts
   - Applies backoff strategy (linear or exponential)
   - Prevents rapid restart loops

4. **Is blackout window active?**
   - Defers restart during maintenance windows
   - Queues for execution after blackout ends

5. **Is container already restarting?**
   - Prevents concurrent restart attempts
   - Tracks in-progress operations

### Restart Action

When all conditions are met:

1. **Wait for retry delay** (respecting backoff strategy)
2. **Attempt container start** via Docker API
3. **Monitor result**:
   - Success: Reset attempt counter, resume monitoring
   - Failure: Increment counter, calculate next retry delay
4. **Send alert** if configured (on failure or max retries exceeded)

## Configuration

### Per-Container Configuration

**Access**: Container Details → Auto-Restart Tab

**Settings**:

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| **Enabled** | On/Off | Global default | Enable auto-restart for this container |
| **Max Retries** | 0-10 | 3 | Maximum restart attempts before giving up |
| **Retry Delay** | 5-300 seconds | 30 | Base delay between restart attempts |
| **Backoff Strategy** | Linear/Exponential | Linear | How delay increases with each retry |

### Global Default Configuration

**Access**: Settings → System → Auto-Restart Defaults

**Settings**:
- **Default Auto-Restart**: Enable/disable auto-restart for new containers
- **Default Max Retries**: System-wide max retry count
- **Default Retry Delay**: System-wide base retry delay

**Note**: Global defaults only apply to containers without explicit configuration. Changing global defaults does not affect containers with existing configurations.

## Retry Strategies

### Linear Backoff (Default)

Delay remains constant for all retry attempts.

**Example** (30-second delay):
- Attempt 1: Wait 30 seconds
- Attempt 2: Wait 30 seconds
- Attempt 3: Wait 30 seconds

**Use cases**:
- Services with predictable startup time
- Network-dependent services (waiting for DNS/routing)
- Database-dependent applications

### Exponential Backoff

Delay doubles with each retry attempt.

**Example** (30-second base delay):
- Attempt 1: Wait 30 seconds
- Attempt 2: Wait 60 seconds (2^1 × 30)
- Attempt 3: Wait 120 seconds (2^2 × 30)
- Attempt 4: Wait 240 seconds (2^3 × 30)

**Use cases**:
- Flaky services with intermittent failures
- Services that need time to recover (memory leaks, cache warmup)
- Protecting against restart storms

**Maximum delay cap**: 300 seconds (5 minutes) to prevent indefinite waits

## Desired State Management

Desired state works in conjunction with auto-restart to maintain container availability.

### Desired States

| State | Behavior | Icon |
|-------|----------|------|
| **Should Run** | Container should always be running | Green play icon |
| **On-Demand** | Container runs only when manually started | Gray clock icon |
| **Unspecified** | No desired state (legacy containers) | No icon |

### Should Run

When a container's desired state is "Should Run":
- **Auto-restart activates** when container stops unexpectedly
- **Warning icon displays** if container is stopped but should be running
- **Alerts trigger** if container remains stopped beyond retry limit

**Use cases**:
- Web servers
- API services
- Background workers
- Databases

### On-Demand

When a container's desired state is "On-Demand":
- **Auto-restart does NOT activate** (even if enabled)
- **No warnings** when container is stopped
- **Manual start required** each time

**Use cases**:
- One-time migration scripts
- Development/testing containers
- Scheduled jobs (cron-like containers)
- Manual intervention tools

**Note**: Setting desired state to "On-Demand" effectively disables auto-restart for that container, even if auto-restart is enabled.

## Status Tracking

### Restart Attempt Counter

DockMon tracks restart attempts per container using composite keys (`host_id:container_id`):

- **Increments** on each failed restart attempt
- **Resets to zero** when:
  - Container successfully starts and runs for 60+ seconds
  - Auto-restart is manually disabled
  - Max retries exceeded (gives up)
- **Persists across DockMon restarts** (stored in memory, not database)

### Restarting Status

Containers in the process of being restarted show:
- **Blue spinning circle** in status column
- **"Restarting" label**
- **Disabled action buttons** (cannot start/stop during restart)

### Failure Tracking

When auto-restart fails:
1. **Event logged** to Events table (visible in Event Viewer)
2. **Alert triggered** if alert rule configured for exit state
3. **Attempt counter incremented**
4. **Next retry scheduled** based on backoff strategy

## Integration with Alerts

Auto-restart failures can trigger alert notifications.

### Alert Rule Configuration

**Create alert rule**:
1. Navigate to Settings → Alerts
2. Create new rule or edit existing
3. Configure:
   - **Scope**: Container
   - **Kind**: State Change
   - **Trigger States**: `exited`, `dead`
   - **Container Selector**: All containers or specific containers
   - **Notify Channels**: Your preferred channels (Telegram, Discord, etc.)

**Alert message includes**:
- Container name and ID
- Host name
- Exit code
- Restart attempt count
- Max retries remaining
- Timestamp

### Suppression During Blackout Windows

Auto-restart attempts are deferred during blackout windows:
- **Stops accumulating during blackout**: Containers that stop during maintenance windows are not immediately restarted
- **Queued for evaluation**: After blackout ends, DockMon checks all stopped containers
- **Bulk restart**: Containers with `desired_state: should_run` are restarted after blackout
- **Alerts sent for failures**: Post-blackout checks trigger alerts for containers still in failed state

See [Blackout Windows](Blackout-Windows.md) for details.

## Best Practices

### When to Enable Auto-Restart

**DO enable for**:
- Production web servers
- Critical API services
- Database containers
- Message queue workers
- Reverse proxies and load balancers
- Monitoring and logging services

**DON'T enable for**:
- One-time migration scripts
- Data import/export jobs
- Development containers
- Test/CI containers
- Containers that should fail-fast

### Retry Configuration Guidelines

**Low-risk services** (can restart frequently):
- Max retries: 5-10
- Retry delay: 10-15 seconds
- Backoff: Linear

**Example**: Static file servers, caches

**Medium-risk services** (restart has some cost):
- Max retries: 3-5
- Retry delay: 30-60 seconds
- Backoff: Exponential

**Example**: Application servers, APIs

**High-risk services** (restart is expensive):
- Max retries: 1-3
- Retry delay: 60-120 seconds
- Backoff: Exponential

**Example**: Databases, stateful services

### Desired State Best Practices

**Always set desired state** for new containers:
- Production services: "Should Run"
- Development/testing: "On-Demand"
- One-shot tasks: "On-Demand"

**Benefits**:
- Clear operational intent
- Visual indicators for mismatches
- Better alert targeting
- Easier troubleshooting

### Alert Integration

**Alert on**:
- First restart attempt (informational)
- Max retries exceeded (critical)
- Exit code changes (error)
- Restart patterns (warning - possible crash loop)

**Alert channels**:
- Critical services: Multiple channels (Telegram + Email)
- Standard services: Primary channel only
- Development: Low-priority channel or disabled

## Monitoring and Troubleshooting

### Viewing Auto-Restart Status

**Dashboard**:
- Auto-restart icon in Policy column (blue refresh = enabled)
- Desired state icon in Policy column
- Warning triangle if container should be running but isn't

**Container Details**:
- Auto-Restart tab shows full configuration
- Current restart attempt count
- Last restart timestamp
- Next retry time (if in retry loop)

**Events Tab**:
- Filter by container
- Look for "container_stopped", "container_started" events
- Check exit codes for patterns

### Common Issues

#### Container in Restart Loop

**Symptoms**:
- Container repeatedly starts and stops
- High restart attempt count
- Spinning "restarting" status

**Diagnosis**:
1. Check logs for startup errors
2. Review exit codes in Events tab
3. Look for resource constraints (CPU, memory, disk)
4. Check dependencies (database, network, volumes)

**Solutions**:
- Disable auto-restart temporarily
- Fix root cause (config, resources, code)
- Increase retry delay to allow debugging
- Set desired state to "On-Demand" until fixed

#### Auto-Restart Not Working

**Symptoms**:
- Container stops but doesn't restart
- No restart attempts logged

**Diagnosis**:
1. Verify auto-restart is enabled (Container Details → Auto-Restart tab)
2. Check desired state (should be "Should Run")
3. Look for blackout window (Settings → Alerts)
4. Review max retries (may have been exceeded)
5. Check DockMon logs for errors

**Solutions**:
- Enable auto-restart if disabled
- Set desired state to "Should Run"
- Wait for blackout window to end
- Reset retry counter (disable/re-enable auto-restart)
- Check DockMon container logs: `docker logs dockmon`

#### Too Many Restart Attempts

**Symptoms**:
- Service frequently restarts
- High resource usage from restart overhead
- Alert storm from repeated failures

**Diagnosis**:
1. Check logs for error patterns
2. Review container resource limits (memory, CPU)
3. Check host resource availability
4. Look for external dependency failures (database, API)

**Solutions**:
- Increase resource limits if needed
- Fix application bugs causing crashes
- Add health checks to detect issues earlier
- Use exponential backoff to reduce restart frequency
- Reduce max retries to fail faster

### Resetting Retry Counter

To reset a container's restart attempt counter:

1. **Disable auto-restart**:
   - Container Details → Auto-Restart tab
   - Toggle "Enabled" to Off
   - Save

2. **Re-enable auto-restart**:
   - Toggle "Enabled" to On
   - Save

This clears the attempt counter and resets retry timing.

## Advanced Scenarios

### Coordinated Restarts

For multi-container applications requiring startup order:

1. **Disable auto-restart** for dependent containers
2. **Use desired state** instead ("Should Run")
3. **Create health checks** for dependency detection
4. **Monitor via events** for manual intervention
5. **Or use Docker Compose** with `depends_on` and health checks

**Why**: Auto-restart doesn't coordinate between containers. Use orchestration tools (Docker Compose, Kubernetes) for complex startup dependencies.

### Flapping Detection

To detect containers that repeatedly restart (flapping):

1. **Create alert rule**:
   - Trigger: Container state change to "exited"
   - Occurrences: 3 within 60 seconds
   - Severity: Warning

2. **Review alerts** for patterns
3. **Investigate logs** for root cause
4. **Disable auto-restart** for flapping containers until fixed

### Graceful Degradation

For non-critical services that should fail gracefully:

1. **Set low max retries** (1-2 attempts)
2. **Use exponential backoff**
3. **Create informational alerts** (not critical)
4. **Set desired state** to "On-Demand"

**Example**: Optional caching services, analytics collectors

## Related Documentation

- [Container Operations](Container-Operations.md) - Managing container lifecycle
- [Blackout Windows](Blackout-Windows.md) - Maintenance periods and alert suppression
- [Alerts](https://github.com/darthnorse/dockmon/wiki/Alerts) - Alert rules and notifications
- [Settings](Settings.md) - Global configuration options
