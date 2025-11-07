# Alert Rules

DockMon v2 features a completely redesigned alert system with powerful metric-based and event-driven alerting capabilities. Create sophisticated monitoring rules with fine-grained control over when and how you receive notifications.

---

## Overview

The v2 alert system provides three types of alert rules:

- **Metric-Based Alerts** - Trigger when container/host metrics exceed thresholds (CPU > 80%, Memory > 90%, etc.)
- **Event-Driven Alerts** - Trigger on Docker events (container stopped, OOM killed, unhealthy, etc.)
- **Health Check Alerts** - Trigger when HTTP/HTTPS health checks fail for containers

Each alert rule consists of:
- **Name and description** - Clear identification of what the rule monitors
- **Severity level** - info, warning, or critical
- **Scope** - Containers or hosts
- **Target selection** - Specific resources or tag-based filtering
- **Trigger conditions** - Thresholds for metrics or event types for events
- **Notification channels** - Where to send alerts (Discord, Slack, Telegram, Pushover, Gotify, SMTP)
- **Cooldown period** - Minimum time between repeated alerts
- **Advanced options** - Grace periods, clear thresholds, custom templates

---

## Breaking Changes from v1

DockMon v2 uses a completely different alert architecture:

**What Changed:**
- **v1 used "events" and "states"** - v2 uses "metric-based" and "event-driven" alerts
- **v1 rules monitored specific containers** - v2 supports tag-based filtering and advanced selectors
- **v1 had simple triggers** - v2 has sliding windows, occurrence counts, and clear conditions
- **v1 alerts were immediate** - v2 supports grace periods and sustained breach detection

**Migration Required:**
- v1 alert rules are NOT automatically migrated to v2
- You must recreate your alert rules using the new v2 system
- v2 provides more flexibility and power than v1

---

## Creating Alert Rules

### From the Dashboard

1. Navigate to **Alert Rules** page (sidebar)
2. Click **Create Rule**
3. Configure the rule (see sections below)
4. Click **Save Rule**

### Rule Configuration

#### 1. Basic Information

**Rule Name**
Choose a descriptive name that indicates what the rule monitors:
- Good: "Production Database High CPU"
- Good: "Critical Services Container Stopped"
- Good: "Host Memory Warning"
- Bad: "Rule 1" (not descriptive)

**Description** (optional)
Add context about why this rule exists and what action to take.

Example:
```
High CPU usage on production database. Check for slow queries or
missing indexes. Consider scaling if sustained.
```

**Severity**
Choose the alert severity level:
- **info** - Informational alerts (e.g., container started)
- **warning** - Non-critical issues (e.g., high CPU)
- **critical** - Critical issues requiring immediate action (e.g., container died)

#### 2. Scope

Select what type of resource this rule monitors:

- **Container** - Monitor Docker containers
- **Host** - Monitor Docker hosts

#### 3. Alert Type (Kind)

The rule "kind" determines what condition triggers the alert.

**Event-Driven Kinds:**
- `container_stopped` - Container exited or died
- `unhealthy` - Container health check failed (Docker native)
- `health_check_failed` - HTTP/HTTPS health check failed (DockMon custom)
- `host_disconnected` / `host_down` - Docker host went offline
- `update_available` - Container image update detected
- `update_completed` - Container update finished successfully
- `update_failed` - Container update failed

**Metric-Based Kinds:**
You define custom kinds for metric rules (e.g., `cpu_high`, `memory_critical`, `disk_full`)

#### 4. Target Selection

Choose which containers or hosts this rule applies to.

**Container Selection:**

**Option A: Specific Containers**
Select individual containers from the list. Each container shows:
- Container name
- Host name
- Current status

**Option B: All Containers**
Select "Monitor all containers" to automatically monitor every container across all hosts.

Benefits:
- No need to update rule when adding new containers
- Automatically monitors future containers
- Works across all hosts

**Option C: Tag-Based Selection**
Filter containers by tags:
```json
{
  "include_all": false,
  "tags": ["production", "critical"]
}
```
Matches containers with ANY of the specified tags.

**Option D: Advanced Selectors**
Use JSON selectors for complex filtering:

```json
{
  "include_all": true,
  "should_run": true,
  "tags": ["production"]
}
```

Selector options:
- `include_all` - Match all containers (boolean)
- `include` - List of specific container names
- `should_run` - Filter by desired state (true = should_run, false = on_demand)
- `tags` - Container must have ANY of these tags
- `container_name` - Exact match or `regex:pattern`
- `container_id` - Exact container ID match

**Host Selection:**

Similar to container selection:

```json
{
  "include_all": true,
  "tags": ["production"]
}
```

Host selector options:
- `include_all` - Match all hosts (boolean)
- `include` - List of specific host IDs
- `tags` - Host must have ANY of these tags
- `host_name` - Exact match or `regex:pattern`
- `host_id` - Exact host ID match

---

## Metric-Based Alert Rules

Metric-based rules trigger when container or host metrics exceed thresholds for a specified duration.

### Available Metrics

**Container Metrics:**
- `cpu_percent` - CPU usage percentage (0-100)
- `memory_percent` - Memory usage percentage (0-100)
- `memory_usage` - Memory usage in bytes
- `memory_limit` - Memory limit in bytes
- `network_rx_bytes` - Network received bytes
- `network_tx_bytes` - Network transmitted bytes
- `block_read_bytes` - Disk read bytes
- `block_write_bytes` - Disk write bytes

**Host Metrics:**
- `docker_cpu_workload_pct` - Docker host CPU workload percentage
- `docker_mem_workload_pct` - Docker host memory workload percentage
- `disk_free_pct` - Disk free space percentage
- `disk_used_pct` - Disk used space percentage
- `unhealthy_count` - Number of unhealthy containers
- `container_count` - Total number of containers

### Threshold Configuration

**Operator**
Choose the comparison operator:
- `>=` - Greater than or equal to
- `<=` - Less than or equal to
- `>` - Greater than
- `<` - Less than
- `==` - Equal to

**Threshold**
The value to compare against.

Example: CPU > 80 means alert when CPU exceeds 80%

**Duration** (optional)
How long the threshold must be breached before alerting (in seconds).

Example: Duration = 300 (5 minutes) means CPU must be > 80% for 5 minutes

**Occurrences** (optional)
Number of breach observations required within the duration window.

Example: Occurrences = 3, Duration = 300 means CPU must breach threshold at least 3 times in 5 minutes

### Clear Conditions

Configure when to automatically resolve the alert.

**Clear Threshold** (optional)
Value below which the condition is considered resolved.

Example: Threshold = 90, Clear Threshold = 70 means:
- Alert when CPU > 90%
- Resolve when CPU < 70%

**Clear Duration** (optional)
How long the metric must stay below clear threshold before resolving (in seconds).

Example: Clear Duration = 60 means metric must stay below clear threshold for 1 minute

**Use Case for Clear Duration:**
Prevent alert flapping by requiring sustained improvement before resolving.

### Example: High CPU Alert

```yaml
Name: Production Database High CPU
Description: Alert when database CPU exceeds 80% for 5 minutes
Severity: warning
Scope: container
Kind: cpu_high

Metric: cpu_percent
Operator: >=
Threshold: 80
Duration: 300 (5 minutes)
Occurrences: 3 (at least 3 observations in 5 minutes)

Clear Threshold: 60
Clear Duration: 120 (2 minutes below 60%)

Container Selector:
  include: ["postgres-production"]

Cooldown: 900 seconds (15 minutes)
Channels: [Discord #alerts, Pushover]
```

**How it works:**
1. DockMon samples CPU every 10 seconds
2. If CPU >= 80% at least 3 times within 5 minutes → Alert fires
3. Alert won't fire again for 15 minutes (cooldown)
4. If CPU drops below 60% for 2 minutes → Alert auto-resolves
5. If CPU spikes again → New alert (if cooldown expired)

### Example: High Memory Alert

```yaml
Name: All Containers Memory Warning
Description: Alert when any container exceeds 90% memory
Severity: warning
Scope: container
Kind: memory_high

Metric: memory_percent
Operator: >=
Threshold: 90
Duration: 180 (3 minutes)

Clear Threshold: 75
Clear Duration: 60 (1 minute)

Container Selector:
  include_all: true
  should_run: true  # Only "should run" containers

Cooldown: 600 seconds (10 minutes)
Channels: [Telegram @ops, Discord #monitoring]
```

### Example: Host Disk Space Critical

```yaml
Name: Host Disk Space Critical
Description: Alert when host disk usage exceeds 95%
Severity: critical
Scope: host
Kind: disk_critical

Metric: disk_used_pct
Operator: >=
Threshold: 95
Duration: 0 (immediate)

Host Selector:
  include_all: true

Cooldown: 3600 seconds (1 hour)
Channels: [Discord #critical, Pushover, SMTP]
```

---

## Event-Driven Alert Rules

Event-driven rules trigger immediately when specific Docker events occur.

### Available Event Types

**Container Events:**

| Kind | Description | When It Fires |
|------|-------------|---------------|
| `container_stopped` | Container exited or died | Container state changes to `exited` or `dead` |
| `unhealthy` | Docker health check failed | Container health status changes to `unhealthy` |
| `health_check_failed` | HTTP health check failed | DockMon HTTP/HTTPS health check fails |
| `update_available` | New image version detected | Registry check finds newer image |
| `update_completed` | Container update succeeded | Container successfully updated to new image |
| `update_failed` | Container update failed | Container update encountered error |

**Host Events:**

| Kind | Description | When It Fires |
|------|-------------|---------------|
| `host_disconnected` | Host went offline | Connection to Docker daemon lost |
| `host_down` | Host is down | Host failed to respond to health checks |

### Event Rule Configuration

Event-driven rules do NOT use metrics, thresholds, or durations. They fire immediately when the event occurs.

**Required fields:**
- Name
- Severity
- Scope (container or host)
- Kind (event type)
- Target selection (which containers/hosts)
- Notification channels

**Optional fields:**
- Cooldown (prevent spam)
- Grace period (delay before first notification)
- Custom template

### Example: Container Stopped Alert

```yaml
Name: Critical Services Down
Description: Immediate alert when critical containers stop
Severity: critical
Scope: container
Kind: container_stopped

Container Selector:
  include: ["nginx", "postgres", "redis"]

Cooldown: 300 seconds (5 minutes)
Grace Period: 0 (immediate)
Channels: [Discord #critical, Pushover, Telegram @oncall]
```

**How it works:**
1. DockMon detects container state change to `exited` or `dead`
2. Checks if container matches selector
3. If yes → Alert fires immediately
4. Notification sent to all channels
5. Cooldown prevents duplicate notifications for 5 minutes

### Example: Container Unhealthy Alert

```yaml
Name: Production Containers Health Check
Description: Alert when containers fail health checks
Severity: warning
Scope: container
Kind: unhealthy

Container Selector:
  include_all: true
  tags: ["production"]

Cooldown: 600 seconds (10 minutes)
Channels: [Slack #health-checks]
```

### Example: Host Disconnected Alert

```yaml
Name: Host Offline
Description: Alert when any Docker host goes offline
Severity: critical
Scope: host
Kind: host_disconnected

Host Selector:
  include_all: true

Cooldown: 900 seconds (15 minutes)
Channels: [Discord #infrastructure, SMTP alerts@company.com]
```

### Example: Update Notifications

```yaml
Name: Container Updates Available
Description: Notify when container image updates are available
Severity: info
Scope: container
Kind: update_available

Container Selector:
  include_all: true
  should_run: true

Cooldown: 86400 seconds (24 hours)
Channels: [Slack #updates]
```

---

## Alert Behavior

### Cooldown Period

Prevents notification spam by enforcing minimum time between alerts for the same condition.

**How it works:**
- Alert fires at 10:00 AM → Notification sent
- Same condition at 10:05 AM → Notification suppressed (within cooldown)
- Same condition at 10:20 AM → Notification sent (cooldown expired)

**Cooldown is per-rule-per-target:**
- Different containers trigger separate alerts
- Different rules for same container trigger separate alerts
- Same rule for same container respects cooldown

**Recommended values:**
- **300 seconds (5 min)** - Critical alerts, need quick feedback
- **900 seconds (15 min)** - Most production alerts (default)
- **3600 seconds (1 hour)** - Non-critical or noisy alerts

### Grace Period

Delays the FIRST notification for a new alert.

**Use case:** Avoid alerts during brief transient conditions.

Example:
```yaml
Grace Period: 300 seconds (5 minutes)
```

**How it works:**
1. Condition first detected at 10:00 AM
2. Grace period starts (no notification)
3. If still breaching at 10:05 AM → Notification sent
4. If resolved before 10:05 AM → No notification (transient)

**Note:** Grace period only applies to the first notification. Subsequent occurrences use cooldown.

### Clear Duration (Metric Rules Only)

For metric-based rules, clear_duration prevents notifications for transient spikes.

**Two purposes:**
1. **Alert persistence**: Require sustained breach before alerting
2. **Auto-resolution**: Require sustained recovery before resolving

Example:
```yaml
Threshold: 90
Duration: 300
Clear Threshold: 70
Clear Duration: 120
```

**Scenario 1: CPU spikes then recovers quickly**
- 10:00 - CPU hits 95% (breach starts)
- 10:02 - CPU drops to 65% (breach ends)
- Duration not met (only 2 min, need 5 min) → No alert

**Scenario 2: Sustained high CPU**
- 10:00 - CPU hits 95% (breach starts)
- 10:05 - Still above 90% → Alert fires (5 min duration met)
- 10:10 - CPU drops to 65% (clear starts)
- 10:12 - Still below 70% for 2 min → Alert auto-resolves

### Suppress During Updates

Prevent alerts when containers are being updated.

```yaml
Suppress During Updates: true
```

**Use case:** Avoid "container stopped" alerts when you're intentionally updating containers.

**How it works:**
- DockMon tracks active container updates
- If alert would fire during update → Suppressed
- After update completes → Normal alerting resumes

---

## Notification Channels

### Configuring Channels

Before creating alert rules, set up notification channels:

1. Navigate to **Notifications** page
2. Add channels (Discord, Slack, Telegram, Pushover, Gotify, SMTP)
3. Test each channel
4. Return to Alert Rules and select channels

See [Notifications](Notifications) for detailed setup.

### Multi-Channel Alerts

Select multiple channels for redundancy:

```yaml
Channels:
  - Discord #critical
  - Telegram @ops_team
  - Pushover Mobile
  - SMTP ops@company.com
```

All channels receive the same alert.

**Best practice:** Use multiple channels for critical alerts to ensure delivery.

---

## Alert Templates

Customize notification message format using template variables.

### Template Configuration

**Global Templates:**
Navigate to Settings and configure default templates:
- `alert_template` - Default template for all alerts
- `alert_template_metric` - Metric-based alerts
- `alert_template_state_change` - State change events
- `alert_template_health` - Health check failures

**Per-Rule Templates:**
Override global template in rule configuration:
```yaml
Custom Template: |
  Critical Alert!
  Container: {CONTAINER_NAME}
  Host: {HOST_NAME}
  CPU: {CURRENT_VALUE}% (threshold: {THRESHOLD}%)
  Time: {TIMESTAMP}
```

### Template Variables

#### Basic Entity Info
| Variable | Description | Example |
|----------|-------------|---------|
| `{CONTAINER_NAME}` | Container name | `postgres-production` |
| `{CONTAINER_ID}` | Short container ID (12 chars) | `a1b2c3d4e5f6` |
| `{HOST_NAME}` | Docker host name | `Production Server` |
| `{HOST_ID}` | Host identifier | `7be442c9-24bc-4047-b33a` |
| `{IMAGE}` | Docker image name | `postgres:15-alpine` |
| `{LABELS}` | Container/host labels | `env=prod, app=web` |

#### Alert Info
| Variable | Description | Example |
|----------|-------------|---------|
| `{SEVERITY}` | Alert severity | `critical` |
| `{KIND}` | Alert kind | `cpu_high` |
| `{TITLE}` | Alert title | `High CPU Usage` |
| `{MESSAGE}` | Alert message | `CPU usage exceeded threshold` |
| `{SCOPE_TYPE}` | Alert scope | `Container` |
| `{SCOPE_ID}` | Scope identifier | `container-id` |
| `{STATE}` | Alert state | `firing` |

#### Temporal Info
| Variable | Description | Example |
|----------|-------------|---------|
| `{TIMESTAMP}` | Full timestamp | `2025-10-18 14:23:45` |
| `{TIME}` | Time only | `14:23:45` |
| `{DATE}` | Date only | `2025-10-18` |
| `{FIRST_SEEN}` | When alert first triggered | `2025-10-18 14:20:00` |
| `{LAST_SEEN}` | Last time alert fired | `2025-10-18 14:23:45` |

#### Rule Context
| Variable | Description | Example |
|----------|-------------|---------|
| `{RULE_NAME}` | Alert rule name | `High CPU Warning` |
| `{RULE_ID}` | Alert rule ID | `rule-123-abc` |
| `{TRIGGERED_BY}` | What triggered the alert | `system` |

#### Metric-Based Alerts
| Variable | Description | Example |
|----------|-------------|---------|
| `{CURRENT_VALUE}` | Current metric value | `92.5` |
| `{THRESHOLD}` | Alert threshold | `80` |

#### Event-Driven Alerts (State Changes)
| Variable | Description | Example |
|----------|-------------|---------|
| `{OLD_STATE}` | Previous container state | `running` |
| `{NEW_STATE}` | New container state | `exited` |
| `{EVENT_TYPE}` | Docker event type | `die` |
| `{EXIT_CODE}` | Container exit code | `137 (SIGKILL)` |

#### Health Check Alerts
| Variable | Description | Example |
|----------|-------------|---------|
| `{HEALTH_CHECK_URL}` | URL being monitored | `http://localhost:8080/health` |
| `{CONSECUTIVE_FAILURES}` | Consecutive failures vs threshold | `3/3 consecutive` |
| `{FAILURE_THRESHOLD}` | Failure threshold | `3` |
| `{RESPONSE_TIME}` | HTTP response time | `1250ms` |
| `{ERROR_MESSAGE}` | Error message | `Connection refused` |

#### Container Update Alerts
| Variable | Description | Example |
|----------|-------------|---------|
| `{UPDATE_STATUS}` | Update status | `Available` |
| `{CURRENT_IMAGE}` | Current image tag | `nginx:1.24` |
| `{LATEST_IMAGE}` | Latest available image tag | `nginx:1.25` |
| `{CURRENT_DIGEST}` | Current image digest | `sha256:abc123...` |
| `{LATEST_DIGEST}` | Latest image digest | `sha256:def456...` |
| `{PREVIOUS_IMAGE}` | Image before update | `nginx:1.24` |
| `{NEW_IMAGE}` | Image after update | `nginx:1.25` |
| `{ERROR_MESSAGE}` | Error message (for failed updates) | `Pull timeout` |

### Example Templates

**Metric Alert Template:**
```
Alert: {RULE_NAME}

Container: {CONTAINER_NAME} on {HOST_NAME}
Metric: {METRIC} = {CURRENT_VALUE} (threshold: {OPERATOR} {THRESHOLD})
Severity: {SEVERITY}
Time: {TIMESTAMP}
```

**Container Stopped Template:**
```
Container Stopped!

Container: {CONTAINER_NAME}
Host: {HOST_NAME}
Previous State: {OLD_STATE}
Exit Code: {EXIT_CODE}
Time: {TIMESTAMP}
```

**Minimal Template:**
```
{CONTAINER_NAME}: {METRIC}={CURRENT_VALUE} (>{THRESHOLD}) at {TIME}
```

---

## Managing Alert Rules

### Viewing Rules

The Alert Rules page displays:
- Rule name and description
- Severity badge (info/warning/critical)
- Scope (container/host)
- Kind (alert type)
- Target count (e.g., "3 containers" or "All containers")
- Enabled status
- Notification channels

### Editing Rules

1. Click **Edit** on a rule
2. Modify any settings
3. Click **Save**

**Note:** Editing a rule increments its version number. Active alerts reference the rule version that created them.

### Enabling/Disabling Rules

Toggle the **Enabled** switch to activate or deactivate a rule.

**Use cases for disabling:**
- Planned maintenance
- Temporary development work
- Testing configuration changes
- Reducing alert noise

**Disabled rules:**
- Don't evaluate conditions
- Don't send notifications
- Remain configured for quick re-enable

### Deleting Rules

1. Click **Delete** on a rule
2. Confirm deletion

**Warning:** Deletion cannot be undone.

**What happens:**
- Rule is permanently deleted
- Active alerts from this rule remain in alert history
- Future evaluations of this rule stop

**Best practice:** Disable instead of delete if you might need the rule again.

---

## Alert History

### Viewing Alerts

Navigate to **Alerts** page to view:
- Active alerts (state: open)
- Snoozed alerts (state: snoozed)
- Resolved alerts (state: resolved)

**Alert details:**
- Title and message
- Severity and kind
- First seen / last seen timestamps
- Occurrence count
- Current metric value (if metric-based)
- Rule that triggered it

### Acknowledging Alerts

**Resolve Alert:**
Manually mark an alert as resolved:
1. Click on alert
2. Click **Resolve**
3. Enter optional reason
4. Confirm

**Snooze Alert:**
Temporarily suppress an alert for a duration:
1. Click on alert
2. Click **Snooze**
3. Choose duration (1 min to 7 days)
4. Confirm

**Add Annotation:**
Add notes to an alert for team communication:
1. Click on alert
2. Click **Add Note**
3. Enter text
4. Save

### Alert Statistics

View alert statistics on the Alerts page:
- Total alerts
- Open alerts count
- Snoozed alerts count
- Resolved alerts count
- Breakdown by severity (critical/warning/info)

---

## Best Practices

### Rule Design

**Do's:**
- **Use descriptive names** - "Production DB High CPU" not "Rule 1"
- **Set appropriate severity** - Reserve "critical" for urgent issues
- **Use cooldowns wisely** - Balance responsiveness vs. noise
- **Test before enabling** - Verify rule matches expected targets
- **Document why** - Use description field to explain purpose
- **Use tag-based selection** - More flexible than specific container names
- **Combine metric duration with occurrences** - Prevent false positives from spikes

**Don'ts:**
- **Don't set cooldown too low** - Causes alert fatigue (<5 minutes)
- **Don't create duplicate rules** - Consolidate similar monitoring
- **Don't alert on everything** - Alert fatigue reduces effectiveness
- **Don't use zero duration for noisy metrics** - Transient spikes cause spam
- **Don't forget clear conditions** - Alerts should auto-resolve when possible

### Alert Fatigue Prevention

**Strategies:**
1. **Appropriate severity** - Use "info" for non-actionable events
2. **Longer cooldowns** - 15-30 minutes for non-critical alerts
3. **Grace periods** - Skip transient conditions
4. **Clear thresholds** - Auto-resolve when condition clears
5. **Tag-based rules** - One rule for multiple containers
6. **Blackout windows** - Silence during maintenance
7. **Regular review** - Tune or disable noisy rules

### Production Alerting Strategy

**Three-tier approach:**

**Tier 1: Critical Alerts (severity: critical)**
- Container stopped unexpectedly
- OOM killed
- Host disconnected
- Disk > 95%
- Cooldown: 5-10 minutes
- Channels: Multiple (Discord, Pushover, SMTP)

**Tier 2: Warning Alerts (severity: warning)**
- High CPU (>80% for 5 min)
- High memory (>90% for 3 min)
- Health check failures
- Disk > 85%
- Cooldown: 15-30 minutes
- Channels: Primary channel (Discord or Slack)

**Tier 3: Info Alerts (severity: info)**
- Container started
- Updates available
- Container created
- Cooldown: 1-24 hours
- Channels: Low-priority channel

### Tag-Based Organization

Use tags for flexible rule targeting:

**Example tag structure:**
- Environment: `production`, `staging`, `dev`
- Criticality: `critical`, `important`, `low-priority`
- Team: `backend`, `frontend`, `infrastructure`
- Function: `database`, `cache`, `web`, `queue`

**Example rules using tags:**
```yaml
# Alert on all production containers
Container Selector:
  include_all: true
  tags: ["production"]

# Alert only on critical production databases
Container Selector:
  include_all: true
  tags: ["production", "critical", "database"]
```

**Benefits:**
- Single rule covers multiple containers
- Add new containers without updating rules
- Organize by function/team/environment
- Rules survive container renames

---

## Troubleshooting

### Alerts Not Triggering

**Checklist:**
1. **Rule enabled?** - Check enabled status
2. **Target matches?** - Verify container/host matches selector
3. **Metric threshold correct?** - Check operator and threshold value
4. **Duration met?** - For metric rules, must breach for full duration
5. **Cooldown active?** - Check last alert time, may be in cooldown
6. **Notification channels configured?** - Verify channels exist and are enabled
7. **Blackout window active?** - Check Settings > Blackout Windows
8. **Grace period?** - First alert may be delayed by grace period

**Debug steps:**
1. Navigate to Alert Rules
2. Find the rule
3. Check "Last Evaluated" timestamp
4. Check "Last Triggered" timestamp
5. View Alert History for past triggers
6. Test notification channel independently

### Too Many Alerts

**Solutions:**
1. **Increase cooldown** - 15min → 30min → 1hr
2. **Increase duration** - Require sustained breach (5-10 minutes)
3. **Add occurrences** - Require multiple breaches within window
4. **Adjust thresholds** - 80% → 90% to reduce sensitivity
5. **Use clear duration** - Prevent notifications for transient spikes
6. **Disable noisy rules** - Temporary or permanent
7. **Add blackout windows** - Suppress during known noisy periods
8. **Use tags instead of all containers** - Target specific subset

### False Positives

**Metric Rules:**
- **Add duration** - Require sustained breach (300+ seconds)
- **Add occurrences** - Require multiple observations
- **Use clear duration** - Prevent alerts for brief spikes
- **Adjust threshold** - Make less sensitive

**Event Rules:**
- **Use suppress_during_updates** - Ignore intentional stops
- **Add grace period** - Skip transient events
- **Increase cooldown** - Reduce duplicate notifications
- **Refine selectors** - Exclude specific containers

### Alerts Not Resolving

**Metric Rules with Clear Conditions:**
1. **Check clear threshold** - May not be dropping low enough
2. **Check clear duration** - May not staying below long enough
3. **Verify auto-resolve enabled** - Clear threshold must be set
4. **Check metric still being collected** - Container may be stopped

**Manual Resolution:**
Navigate to Alerts and manually resolve stuck alerts.

### Alert Shows Wrong Value

**Metric alerts:**
- Values are sampled every 10 seconds (default evaluation interval)
- Alert shows value at time of breach detection
- For real-time values, check container stats on dashboard

**Event alerts:**
- Shows event context at time of trigger
- Exit codes may be null if container removed immediately

### Rule Not Matching Expected Containers

**Container Selector Issues:**

1. **Check tag assignment** - Container may not have expected tags
2. **Check should_run filter** - May be filtering out containers
3. **Check include/include_all** - May have conflicting settings
4. **Verify container name** - Exact match required unless using regex
5. **Check host_id** - May be filtering by wrong host

**Debug:**
Use browser developer tools to inspect rule JSON:
```json
{
  "container_selector_json": {
    "include_all": false,
    "include": ["nginx", "postgres"],
    "tags": ["production"]
  }
}
```

---

## Advanced Topics

### Alert Rule Dependencies

Create alert chains where one rule depends on another.

**Use case:** Only alert if both conditions are true.

Example:
```yaml
Rule 1: High CPU (id: rule-cpu-high)
Rule 2: High Memory
  depends_on: ["rule-cpu-high"]
```

**Behavior:** Rule 2 only fires if Rule 1 is also active.

**Note:** Not all alert engines support this. Check DockMon version.

### Alert Annotations

Add metadata to alerts for debugging or team communication.

**Via API:**
```bash
POST /api/alerts/{alert_id}/annotations
{
  "text": "Investigated - caused by batch job",
  "user": "ops_team"
}
```

**Use cases:**
- Document root cause
- Track who investigated
- Link to incident tickets
- Note remediation actions

### Custom Alert Kinds

Create custom kinds for your specific use cases:

**Metric-based custom kind:**
```yaml
Kind: database_connection_pool_exhausted
Metric: connection_count
Threshold: 95
Operator: >=
```

**Event-based custom kind:**
```yaml
Kind: deployment_completed
(Triggered by custom event from CI/CD pipeline)
```

### Regex Selectors

Use regex for dynamic container/host matching:

**Container name pattern:**
```json
{
  "container_name": "regex:^web-.*-prod$"
}
```
Matches: `web-api-prod`, `web-frontend-prod`

**Host name pattern:**
```json
{
  "host_name": "regex:^prod-.*"
}
```
Matches: `prod-server-1`, `prod-server-2`

**Warning:** Avoid complex regex that could cause ReDoS (Regular Expression Denial of Service).

---

## Related Documentation

- [Notifications](Notifications) - Setting up notification channels
- [Blackout Windows](Blackout-Windows) - Scheduled quiet hours
- [Tags](Tags) - Container and host tagging
- [Settings](Settings) - Global alert configuration
- [API Reference](API-Reference) - Alert API endpoints

---

## Migration from v1 to v2

### Key Differences

| Feature | v1 | v2 |
|---------|----|----|
| **Alert Types** | Events and states | Metric-based and event-driven |
| **Target Selection** | Container list | Selectors with tags/regex |
| **Thresholds** | None | Metric thresholds with operators |
| **Sliding Windows** | No | Yes (duration + occurrences) |
| **Auto-Resolution** | No | Yes (clear thresholds) |
| **Grace Periods** | No | Yes |
| **Templates** | Global only | Global + per-rule |
| **Severity Levels** | Implicit | Explicit (info/warning/critical) |

### Migration Steps

1. **Review v1 rules** - Document what each rule monitors
2. **Map to v2 equivalents:**
   - v1 "container die" → v2 `container_stopped` event rule
   - v1 "container exited state" → v2 `container_stopped` event rule
   - v1 "container OOM" → v2 `unhealthy` event rule
3. **Recreate in v2** - Create new rules with v2 configuration
4. **Add enhancements:**
   - Use tags instead of specific container names
   - Add clear conditions for auto-resolution
   - Configure appropriate durations and cooldowns
5. **Test** - Verify rules trigger as expected
6. **Disable v1 rules** - Once v2 rules proven working
7. **Delete v1 rules** - After observation period

### Example Migration

**v1 Rule:**
```
Name: Production Containers
Trigger Events: die, oom
Trigger States: exited, dead
Containers: nginx, postgres, redis
Channels: Discord #alerts
Cooldown: 15 minutes
```

**v2 Equivalent:**
```yaml
Name: Production Containers Stopped
Severity: critical
Scope: container
Kind: container_stopped

Container Selector:
  include: ["nginx", "postgres", "redis"]
  # Better: tags: ["production", "critical"]

Cooldown: 900 seconds (15 minutes)
Channels: [Discord #alerts]
```

**v2 Enhanced:**
```yaml
Name: Critical Production Services
Severity: critical
Scope: container
Kind: container_stopped

Container Selector:
  include_all: true
  tags: ["production", "critical"]
  should_run: true

Suppress During Updates: true
Cooldown: 300 seconds (5 minutes - more responsive)
Channels: [Discord #critical, Pushover, SMTP ops@company.com]
Custom Template: |
  CRITICAL: Production Service Down!

  Container: {CONTAINER_NAME}
  Host: {HOST_NAME}
  Exit Code: {EXIT_CODE}
  Time: {TIMESTAMP}

  Immediate action required!
```

---

## FAQ

**Q: Can one container trigger multiple alert rules?**

A: Yes. Different rules (different rule IDs) can create separate alerts for the same container.

**Q: What happens if I rename a container?**

A: Rules using specific container names will no longer match. Use tags or `include_all` to avoid this issue.

**Q: How often are metrics evaluated?**

A: Default is every 10 seconds. Configurable via Settings > Evaluation Interval.

**Q: Can I silence alerts temporarily?**

A: Yes. Use Blackout Windows or snooze individual alerts.

**Q: Do alerts automatically resolve?**

A: Metric-based alerts auto-resolve when clear conditions are met. Event-based alerts require manual resolution.

**Q: Can I alert on custom metrics?**

A: Currently limited to built-in metrics. Custom metrics support planned for future release.

**Q: What's the difference between cooldown and grace period?**

A:
- **Grace period**: Delays FIRST notification (transient spike protection)
- **Cooldown**: Delays SUBSEQUENT notifications (spam prevention)

**Q: How do I prevent alerts during container updates?**

A: Enable "Suppress During Updates" in rule configuration.

**Q: Can I send different alerts to different channels?**

A: Yes. Create separate rules with different channel configurations.

**Q: What's the maximum cooldown period?**

A: 86400 seconds (24 hours)

**Q: Can I use wildcards in container names?**

A: Use regex selectors: `"container_name": "regex:^web-.*"`

---

## Need Help?

- [Troubleshooting Guide](Troubleshooting)
- [GitHub Discussions](https://github.com/darthnorse/dockmon/discussions)
- [Report an Issue](https://github.com/darthnorse/dockmon/issues)
