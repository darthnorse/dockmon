# Settings

The Settings page provides centralized configuration for DockMon's global behavior, user preferences, and system parameters.

## Overview

Settings are organized into five main categories:
- **Dashboard** - Customize dashboard layout and behavior
- **Alerts** - Configure alert rules and blackout windows
- **Notifications** - Set up notification channels (Telegram, Discord, etc.)
- **Container Updates** - Manage automatic update settings
- **System** - Global application configuration

## Accessing Settings

**Navigation**: Click **Settings** icon in sidebar or navigate to `/settings`

**Tabs**: Click tab headers to switch between categories

**Persistence**: Settings are saved automatically when changed (unless noted otherwise)

## Dashboard Settings

Configure how the dashboard displays and behaves.

### View Mode

**Options**:
- **Compact**: Dense list view for many hosts
- **Standard**: Balanced grid with 4 columns
- **Expanded**: Detailed grid with 3 columns

**Default**: Standard

**When to change**:
- Compact: Managing 20+ hosts, limited screen space
- Standard: Most users, balanced information density
- Expanded: Large monitors, detailed monitoring needs

### Group By

**Options**:
- **None**: Flat list/grid of all hosts
- **Tags**: Group hosts by primary (first) tag

**Default**: None

**Benefits of grouping by tags**:
- Organize by environment (production, staging, dev)
- Separate by purpose (web, database, cache)
- Collapsible sections for better organization

### Show KPI Bar

**Toggle**: Enable/disable high-level metrics bar

**Default**: Enabled

**KPI Bar displays**:
- Total hosts (with online/offline count)
- Total containers (with running/stopped count)
- Active alerts count
- Available updates count

**Recommendation**: Enable for multi-host setups, optional for single host

### Show Stats Widgets

**Toggle**: Enable/disable dashboard widget grid

**Default**: Disabled

**Widget grid includes**:
- Host Stats widget
- Container Stats widget
- Recent Events widget
- Active Alerts widget
- Updates widget

**Performance note**: Disabling widgets reduces WebSocket traffic and DOM size, improving performance on large deployments.

### Simplified Workflow

**Toggle**: Enable/disable simplified container interaction workflow

**Default**: Enabled

**Behavior**:
- **Enabled** (default): Clicking container card opens full-screen details view immediately
- **Disabled**: Clicking container card opens drawer (side panel) for quick access

**When to use**:
- Enabled: Prefer full details immediately, touch devices, simpler interaction
- Disabled: Prefer quick preview before full details, desktop power users

## Alert Settings

Configure alert rules, templates, and blackout windows.

### Alert Rules

See [Alerts documentation](https://github.com/darthnorse/dockmon/wiki/Alerts) for comprehensive alert rule configuration.

**Quick access from Settings**:
- View all alert rules
- Create new rules
- Enable/disable existing rules
- Edit rule parameters

### Blackout Windows

Schedule maintenance periods to suppress alerts.

See [Blackout Windows](Blackout-Windows.md) for comprehensive documentation.

**Quick configuration**:
1. Click **"Add Blackout Window"**
2. Set name, days, start/end times
3. Enable/disable as needed
4. Save

**Common patterns**:
- Nightly backups (daily 02:00-04:00)
- Weekend maintenance (Sat-Sun all day)
- Weekly deployments (Thursday 20:00-23:00)

### Alert Message Templates

Customize alert notification text using template variables.

**Available templates**:
- **Default template**: Used when no specific template matches
- **State change template**: Container started/stopped/died events
- **Metric threshold template**: CPU/memory/disk threshold breaches
- **Health check template**: HTTP health check failures

**Template variables**:
```
{container_name}     - Container name
{container_id}       - Container short ID (12 chars)
{host_name}          - Docker host name
{host_id}            - Docker host ID
{old_state}          - Previous container state
{new_state}          - Current container state
{exit_code}          - Exit code (if stopped)
{timestamp}          - Event timestamp
{image}              - Container image name
{metric}             - Metric name (CPU, memory, etc.)
{threshold}          - Alert threshold value
{current_value}      - Current metric value
{severity}           - Alert severity (info/warning/error/critical)
```

**Example template**:
```
⚠️ Container Alert: {container_name}

Host: {host_name}
State: {old_state} → {new_state}
Exit Code: {exit_code}
Time: {timestamp}

Image: {image}
```

**Tips**:
- Use emojis for visual impact (🔴 critical, ⚠️ warning, ℹ️ info)
- Keep templates concise for mobile notifications
- Include essential info only (container name, host, state)
- Test templates with sample alerts before production use

## Notification Settings

Configure channels for alert delivery.

### Supported Channels

DockMon supports six notification channels:
- **Telegram** - Instant messaging bot
- **Discord** - Webhook integration
- **Slack** - Webhook integration
- **Pushover** - Mobile push notifications
- **Gotify** - Self-hosted push notifications
- **SMTP/Email** - Standard email delivery

See [Notifications documentation](https://github.com/darthnorse/dockmon/wiki/Notifications) for setup guides.

### Channel Configuration

Each channel requires specific credentials:

**Telegram**:
- Bot token (from @BotFather)
- Chat ID (from @userinfobot)

**Discord**:
- Webhook URL (from Server Settings → Integrations)

**Slack**:
- Webhook URL (from Slack App configuration)

**Pushover**:
- App token
- User key

**Gotify**:
- Server URL
- App token

**SMTP/Email**:
- SMTP server address
- Port (25, 465, 587)
- Username
- Password
- From address
- To address(es)
- TLS/SSL settings

### Testing Channels

After configuring a channel:
1. Click **"Send Test"** button
2. Verify notification received
3. Adjust settings if needed

**Test message includes**:
- Test identifier
- Timestamp
- DockMon instance name
- Channel type

## Container Update Settings

Configure automatic container image updates.

See [Container Updates documentation](https://github.com/darthnorse/dockmon/wiki/Container-Updates) for comprehensive guide.

### Global Update Settings

**Daily Update Check Time**:
- Time of day to check for container updates
- 24-hour format (e.g., 02:00 AM)
- Default: 02:00 AM
- System checks once per day at this time

**Skip Docker Compose containers**:
- Toggle to exclude Docker Compose-managed containers from auto-updates
- Default: Enabled (Compose containers are skipped)
- Manual updates still allowed with confirmation

**Health Check Timeout**:
- Maximum time to wait for health checks after updating a container
- Range: 10-600 seconds
- Default: 120 seconds
- Ensures container is healthy before marking update as successful

### Per-Container Override

Global settings can be overridden per-container:
- Navigate to Container Details → Updates tab
- Enable auto-update for specific container
- Set container-specific floating tag mode
- Configure update notification preferences

## System Settings

Global application configuration and operational parameters.

### Auto-Restart Defaults

**Default auto-restart enabled**:
- Whether new containers have auto-restart enabled by default
- Default: False (must explicitly enable per-container)

**Default max retries**:
- Maximum restart attempts for new containers
- Range: 0-10
- Default: 3

**Default retry delay**:
- Seconds between restart attempts for new containers
- Range: 5-300 seconds
- Default: 30 seconds

**Note**: These defaults only apply to new containers or containers without explicit configuration. Changing defaults does not affect existing container configs.

See [Auto-Restart](Auto-Restart.md) for detailed auto-restart documentation.

### Polling Interval

**Container data polling**:
- How often to poll Docker API for container states
- Range: 1-300 seconds
- Default: 2 seconds

**Recommendation**:
- High-traffic environments: 5-10 seconds (reduce API load)
- Critical monitoring: 1-2 seconds (faster detection)
- Low-priority hosts: 30-60 seconds (minimal overhead)

**Note**: Polling complements WebSocket events. Some events (metrics updates) use polling, while lifecycle events (start/stop) use real-time events.

### Connection Timeout

**Docker API timeout**:
- Maximum seconds to wait for Docker API response
- Range: 1-60 seconds
- Default: 10 seconds

**When to adjust**:
- Slow networks: Increase to 30-60 seconds
- Fast local connections: Decrease to 5 seconds
- Remote hosts over VPN: Increase to 20-30 seconds

### Rate Limiting

**API request rate limit**:
- Maximum requests per minute per client
- Range: 10-1000 requests/minute
- Default: 100 requests/minute

**Purpose**: Prevent abuse and resource exhaustion from runaway scripts or malicious clients

**When to adjust**:
- High-frequency automation: Increase to 500-1000
- Public-facing instances: Decrease to 50-100
- Internal use only: Increase to 1000 (or disable)

### Timezone

**Timezone offset**:
- Minutes from UTC (-720 to +720)
- Used for blackout window calculations
- Used for event timestamps in UI

**Common values**:
- PST (UTC-8): -480
- EST (UTC-5): -300
- GMT (UTC+0): 0
- CET (UTC+1): +60
- JST (UTC+9): +540

**Setting your timezone**:
1. Find your timezone's UTC offset (Google "UTC offset [city]")
2. Convert hours to minutes (multiply by 60)
3. Enter positive for east of UTC, negative for west
4. Save

### Session Management

**Session timeout**:
- Minutes of inactivity before auto-logout
- Range: 5-1440 minutes (24 hours)
- Default: 120 minutes (2 hours)

**Session renewal**:
- Automatically renew session on activity
- Default: Enabled

**Recommendation**:
- Production environments: 60-120 minutes
- Development environments: 480-1440 minutes
- Shared computers: 30-60 minutes

### Data Retention

**Event log retention**:
- Days to keep container events in database
- Range: 1-365 days
- Default: 90 days

**Alert history retention**:
- Days to keep resolved alerts in database
- Range: 1-365 days
- Default: 30 days

**Container history retention**:
- Days to keep historical container records (for deleted containers)
- Range: 1-365 days
- Default: 30 days

**Cleanup schedule**:
- How often to run cleanup job
- Options: Daily, Weekly
- Default: Daily at 03:00

**Impact**:
- Shorter retention: Smaller database, faster queries
- Longer retention: Better historical analysis, larger database

### Backup and Restore

**Automatic backups**:
- Enable automatic database backups
- Frequency: Daily, Weekly
- Retention: Number of backups to keep (1-30)
- Location: `/data/backups/` in container

**Manual backup**:
1. Click **"Create Backup Now"** button
2. Backup file generated with timestamp
3. Download from `/data/backups/` volume

**Restore from backup**:
1. Stop DockMon container
2. Replace `/data/dockmon.db` with backup file
3. Start DockMon container
4. Verify data restored correctly

**Backup includes**:
- All hosts and configurations
- Container history
- Event logs
- Alert rules and history
- User accounts and preferences
- Notification channel configs

**Backup excludes**:
- Real-time stats (CPU, memory - ephemeral)
- WebSocket connections
- Active sessions

### System Information

**Read-only information**:
- DockMon version
- Database version
- Database size
- Event log count
- Container count
- Host count
- Last backup time
- Uptime

**Use for**:
- Verifying version after update
- Monitoring database growth
- Troubleshooting support requests

## Advanced Configuration

### Environment Variables

Some advanced settings are configured via environment variables (Docker Compose/run command):

**Database path**:
```yaml
DOCKMON_DB_PATH=/data/dockmon.db
```

**Log level**:
```yaml
LOG_LEVEL=INFO  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
```

**WebSocket port**:
```yaml
WEBSOCKET_PORT=8765
```

**Backend port**:
```yaml
BACKEND_PORT=5000
```

**Frontend port**:
```yaml
FRONTEND_PORT=80
```

**TLS/mTLS**:
```yaml
DOCKMON_TLS_CERT=/certs/server.crt
DOCKMON_TLS_KEY=/certs/server.key
DOCKMON_CA_CERT=/certs/ca.crt  # For mTLS
```

See [Installation documentation](https://github.com/darthnorse/dockmon/wiki/Installation) for complete environment variable reference.

## Best Practices

### Dashboard Configuration

**Small deployments (1-5 hosts)**:
- View mode: Expanded
- Group by: None
- Show widgets: Yes
- Show KPI bar: Optional

**Medium deployments (5-20 hosts)**:
- View mode: Standard
- Group by: Tags
- Show widgets: Yes (essential widgets only)
- Show KPI bar: Yes

**Large deployments (20+ hosts)**:
- View mode: Compact
- Group by: Tags
- Show widgets: No (performance)
- Show KPI bar: Yes

### Alert Configuration

**Production environments**:
- Create alert rules for all critical services
- Use multiple notification channels (redundancy)
- Set appropriate cooldown periods (5-15 minutes)
- Test alerts before production deployment
- Configure blackout windows for maintenance

**Development environments**:
- Lower priority alerts (info/warning only)
- Single notification channel
- Longer cooldown periods (30-60 minutes)
- Optional: Disable alerts entirely

### Notification Channels

**Critical services**:
- Primary: Telegram (instant mobile)
- Secondary: Email (persistent record)
- Tertiary: Discord/Slack (team visibility)

**Standard services**:
- Primary: Discord/Slack (team channel)
- Secondary: Email

**Development/Testing**:
- Single channel: Email or lowest-priority channel

### System Configuration

**Polling intervals**:
- Production: 2-5 seconds (balanced)
- Development: 10-30 seconds (lower overhead)
- Low-priority: 60+ seconds (minimal resources)

**Connection timeouts**:
- Local Docker: 5-10 seconds
- Remote Docker (LAN): 15-20 seconds
- Remote Docker (VPN): 30-60 seconds

**Data retention**:
- High-frequency environments: 30-60 days (prevent database bloat)
- Low-frequency environments: 90-180 days (better history)
- Compliance requirements: Match retention policies

## Troubleshooting

### Settings Not Saving

**Symptoms**: Changes revert after page refresh

**Solutions**:
1. Check browser console for errors
2. Verify DockMon backend is running
3. Check database permissions (volume mount writable)
4. Clear browser cache and retry

### Performance Issues

**Symptoms**: Slow dashboard, high CPU/memory usage

**Solutions**:
1. Increase polling interval (Settings → System)
2. Disable stats widgets (Settings → Dashboard)
3. Use Compact view mode
4. Reduce data retention periods
5. Enable database cleanup (Settings → System → Data Retention)

### Timezone Issues

**Symptoms**: Blackout windows activate at wrong time, event timestamps incorrect

**Solutions**:
1. Verify timezone offset (Settings → System → Timezone)
2. Calculate offset correctly:
   - West of UTC = negative (e.g., PST = -480)
   - East of UTC = positive (e.g., JST = +540)
3. Test blackout window with short duration
4. Check server time: `docker exec dockmon date`

### Notification Failures

**Symptoms**: Alerts not received, "Send Test" fails

**Solutions**:
1. Verify channel credentials (Settings → Notifications)
2. Click "Send Test" and check for error messages
3. Check network connectivity from DockMon container
4. Review DockMon logs: `docker logs dockmon | grep notification`
5. Verify channel is enabled in alert rule

## Related Documentation

- [Dashboard](Dashboard.md) - Dashboard customization and view modes
- [Auto-Restart](Auto-Restart.md) - Auto-restart configuration
- [Blackout Windows](Blackout-Windows.md) - Maintenance window scheduling
- [Alerts](https://github.com/darthnorse/dockmon/wiki/Alerts) - Alert rules and configuration
- [Notifications](https://github.com/darthnorse/dockmon/wiki/Notifications) - Notification channel setup
- [Container Updates](https://github.com/darthnorse/dockmon/wiki/Container-Updates) - Automatic update configuration
