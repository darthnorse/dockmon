# Blackout Windows

Blackout Windows allow you to schedule maintenance periods during which alerts are suppressed, preventing notification storms during planned downtime.

## Overview

Blackout Windows provide:
- **Scheduled maintenance periods** - Define when alerts should be suppressed
- **Day-of-week selection** - Set recurring windows for specific days
- **Overnight window support** - Windows can span across midnight
- **Post-blackout checks** - Automatic container health verification after windows end
- **Real-time status** - Dashboard banner shows active blackout windows
- **Multiple windows** - Create as many blackout windows as needed

## How It Works

### During Blackout Window

When a blackout window is active:

1. **Alert notifications are suppressed**:
   - State change alerts (container stopped, died)
   - Metric alerts (CPU, memory thresholds)
   - Health check alerts
   - Update notifications

2. **Events continue logging**:
   - All container events are recorded
   - Event Viewer shows all activity
   - Audit trail remains complete

3. **Auto-restart is deferred**:
   - Containers that stop during blackout are not immediately restarted
   - Restart attempts queued for after blackout ends

4. **Dashboard shows banner**:
   - Yellow banner at top of page
   - "Blackout Window Active: [window name]"
   - Tooltip shows window details

### After Blackout Window Ends

When a blackout window ends:

1. **Post-blackout health check runs**:
   - All containers across all hosts are checked
   - Problematic states identified (exited, dead, paused)

2. **Deferred alerts are sent**:
   - Alerts for containers found in failed state
   - Note added: "Container found in [state] after maintenance window ended"
   - Sent through configured alert channels

3. **Auto-restart resumes**:
   - Containers with `desired_state: should_run` are restarted
   - Normal auto-restart logic applies
   - Retry counters reset

4. **Dashboard banner removed**:
   - Yellow banner disappears
   - WebSocket broadcasts status change to all clients

## Configuration

### Creating a Blackout Window

**Access**: Settings → Alerts → Blackout Windows

**Steps**:
1. Click **"Add Blackout Window"** button
2. Configure window parameters:
   - **Name**: Descriptive name (e.g., "Weekend Maintenance")
   - **Days**: Select days of week (Monday=0, Sunday=6)
   - **Start Time**: When blackout begins (24-hour format)
   - **End Time**: When blackout ends (24-hour format)
   - **Enabled**: Toggle to activate/deactivate
3. Click **"Save"** to create window

### Window Parameters

| Parameter | Format | Example | Description |
|-----------|--------|---------|-------------|
| **Name** | Text (1-100 chars) | "Nightly Backups" | Human-readable identifier |
| **Days** | Array of integers 0-6 | `[0,1,2,3,4]` | Mon-Fri = 0-4, Sat=5, Sun=6 |
| **Start Time** | HH:MM (24-hour) | `22:00` | When blackout begins |
| **End Time** | HH:MM (24-hour) | `06:00` | When blackout ends |
| **Enabled** | Boolean | `true` | Whether window is active |

### Editing a Blackout Window

1. Navigate to Settings → Alerts → Blackout Windows
2. Click **"Edit"** button next to window
3. Modify parameters as needed
4. Click **"Save"** to update

**Note**: Changes to blackout windows take effect immediately. If editing a currently active window, the new schedule applies right away.

### Deleting a Blackout Window

1. Navigate to Settings → Alerts → Blackout Windows
2. Click **"Delete"** button next to window
3. Confirm deletion in modal dialog

**Warning**: Deletion is immediate and cannot be undone. If a window is currently active when deleted, alerts resume immediately.

## Window Types

### Recurring Windows

Windows that repeat on scheduled days each week.

**Use cases**:
- Nightly backup windows (every night 02:00-04:00)
- Weekend maintenance (Saturday-Sunday all day)
- Weekly deployment windows (Thursday 20:00-23:00)

**Example**: Nightly database maintenance
```
Name: Nightly DB Maintenance
Days: [0,1,2,3,4,5,6]  (Every day)
Start Time: 02:00
End Time: 04:00
Enabled: true
```

### Single-Day Windows

Windows that occur on specific day of week.

**Use cases**:
- Monday morning deployments
- Friday afternoon team updates
- Sunday infrastructure upgrades

**Example**: Monday morning deployment window
```
Name: Monday Deployments
Days: [0]  (Monday only)
Start Time: 08:00
End Time: 10:00
Enabled: true
```

### Overnight Windows

Windows that span midnight (start time > end time).

**Use cases**:
- Late night maintenance (23:00 - 02:00)
- Overnight backups (22:00 - 06:00)
- Extended deployments (20:00 - 08:00)

**Example**: Overnight maintenance
```
Name: Overnight Maintenance
Days: [0,1,2,3,4]  (Mon-Fri)
Start Time: 23:00
End Time: 02:00
Enabled: true
```

**How overnight windows work**:
- If current time >= start time: Check if today is in window days
- If current time < end time: Check if yesterday is in window days
- Handles day-of-week transition correctly

**Example scenario**:
- Window: Monday 23:00 - 02:00
- Current time: Tuesday 01:00
- **Result**: Blackout is active (started Monday night, ends Tuesday morning)

## Best Practices

### When to Use Blackout Windows

**DO use blackout windows for**:
- Scheduled infrastructure maintenance
- Planned container updates/restarts
- Database migration periods
- Network maintenance windows
- Testing disaster recovery procedures
- Large-scale configuration changes

**DON'T use blackout windows for**:
- Regular container restarts (use auto-restart instead)
- Unplanned outages (alerts should fire)
- Individual container maintenance (stop alerts per container instead)
- Permanent alert suppression (fix the root cause or disable alert rule)

### Window Duration

**Short windows** (1-2 hours):
- Specific deployment tasks
- Quick database migrations
- Container image updates

**Medium windows** (2-4 hours):
- Infrastructure upgrades
- Multi-step deployments
- Batch processing jobs

**Long windows** (4+ hours):
- Overnight backups
- Data warehouse updates
- Extended maintenance periods

**Avoid**:
- Windows longer than 8 hours (hard to justify maintenance that long)
- Overlapping windows (simplify to single window if possible)

### Naming Conventions

Use descriptive, specific names:

**Good names**:
- "Nightly Database Backups (02:00-04:00)"
- "Weekend Infrastructure Upgrades"
- "Thursday Production Deployments"

**Poor names**:
- "Maintenance"
- "Window 1"
- "Test"

**Benefits**:
- Clear purpose when reviewing active blackouts
- Easier to communicate with team
- Better audit trail in logs

### Day Selection

**Full week** (all 7 days):
- Daily backup windows
- Continuous batch processing
- Regular health check maintenance

**Weekdays only** (Mon-Fri):
- Business hours deployments
- Office-hours maintenance
- Development/testing cycles

**Weekends only** (Sat-Sun):
- Non-business-critical upgrades
- Extended testing periods
- Low-traffic maintenance

**Specific day**:
- Weekly deployment day
- Monthly patch Tuesday
- Scheduled vendor maintenance

## Monitoring and Status

### Active Blackout Banner

When a blackout window is active:
- **Yellow banner** appears at top of all pages
- Text: "Blackout Window Active: [Window Name]"
- **Clock icon** indicates scheduled maintenance
- **Tooltip on hover** shows window details (start/end time, days)

### WebSocket Updates

Blackout status changes broadcast in real-time:
- All connected clients receive updates
- Banner appears/disappears automatically
- No page refresh required

### Event Logging

Blackout window transitions are logged:
- "Blackout window started: [name]"
- "Blackout window ended: [name]"
- "Post-blackout check: X containers checked, Y in failed state"

**View logs**: Event Viewer → Filter by event type "system"

## Post-Blackout Behavior

### Container Health Check

After each blackout window ends, DockMon:

1. **Scans all hosts** for container states
2. **Identifies problematic containers**:
   - State: exited
   - State: dead
   - State: paused
   - State: removing

3. **Records findings**:
   - Container name and ID
   - Host name
   - State
   - Exit code (if applicable)
   - Image name

4. **Sends alerts** for matched alert rules:
   - Only sends if container matches alert rule selectors
   - Includes note: "Container found in [state] after maintenance window ended"
   - Respects alert cooldown periods

### Alert Rule Matching

Post-blackout alerts trigger only if:
- **Alert rule exists** for state change events
- **Container matches** rule's container selector
- **State matches** rule's trigger states
- **Cooldown period** has elapsed since last alert

**Example alert rule** for post-blackout checks:
```
Name: Post-Maintenance Container Failures
Scope: Container
Kind: State Change
Trigger States: [exited, dead]
Severity: Error
Cooldown: 300 seconds
```

### Auto-Restart Behavior

After blackout ends:
- **Containers with `desired_state: should_run`** are restarted
- **Auto-restart logic applies** as normal
- **Retry counters reset** (blackout doesn't count as failed attempt)
- **Alerts sent** if restart fails

## Troubleshooting

### Blackout Not Activating

**Symptoms**:
- Alerts still being sent during scheduled window
- No blackout banner showing

**Diagnosis**:
1. Verify window is enabled (Settings → Alerts → Blackout Windows)
2. Check current day is in window's days array
3. Verify current time is within window (times are in server local time)

**Solutions**:
- Enable window if disabled
- Add current day to days array
- Adjust start/end times to match server time

### Alerts Not Resuming After Blackout

**Symptoms**:
- Blackout banner gone but no alerts received
- Containers in failed state but no notifications

**Diagnosis**:
1. Check alert rules are enabled (Settings → Alerts)
2. Verify notification channels are configured (Settings → Notifications)
3. Review alert cooldown periods (may still be in cooldown)
4. Check container matches alert rule selectors

**Solutions**:
- Enable alert rules if disabled
- Configure notification channels
- Wait for cooldown to expire
- Adjust alert rule selectors to match containers

### Overnight Window Not Working

**Symptoms**:
- Window activates at wrong time
- Window doesn't span midnight correctly

**Diagnosis**:
1. Verify start time > end time (e.g., 23:00 > 02:00)
2. Check both days are in days array (if window should span two days)
3. Review event logs for window start/end times

**Solutions**:
- Ensure start time is later than end time
- Add both days to days array (e.g., Monday night to Tuesday morning = [0,1])

## Common Use Cases

### Nightly Backup Window

**Scenario**: Database backups run 02:00-04:00 every night, containers restart during backup

**Configuration**:
```
Name: Nightly Database Backups
Days: [0,1,2,3,4,5,6]  (Every day)
Start Time: 02:00
End Time: 04:00
Enabled: true
```

### Weekly Deployment Window

**Scenario**: Production deployments occur Thursday evenings 20:00-23:00

**Configuration**:
```
Name: Thursday Production Deployment
Days: [3]  (Thursday)
Start Time: 20:00
End Time: 23:00
Enabled: true
```

### Weekend Infrastructure Upgrade

**Scenario**: Major infrastructure upgrades happen Saturday-Sunday all day

**Configuration**:
```
Name: Weekend Infrastructure Upgrades
Days: [5,6]  (Saturday, Sunday)
Start Time: 00:00
End Time: 23:59
Enabled: true
```

### Monthly Patch Window

**Scenario**: OS patches applied first Tuesday of each month, 03:00-05:00

**Configuration**:
```
Name: Monthly Patch Tuesday
Days: [1]  (Tuesday only)
Start Time: 03:00
End Time: 05:00
Enabled: true
```

**Note**: This blackout will apply to EVERY Tuesday. To limit to first Tuesday only, you'll need to manually enable/disable each month, or use external scheduling to update blackout via API.

## Related Documentation

- [Auto-Restart](Auto-Restart.md) - Auto-restart behavior during blackouts
- [Alerts](https://github.com/darthnorse/dockmon/wiki/Alerts) - Alert rules and notifications
- [Settings](Settings.md) - Global configuration
- [Container Operations](Container-Operations.md) - Managing containers during maintenance
