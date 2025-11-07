# Event Viewer

The Event Viewer provides a comprehensive audit trail of all activities within DockMon, allowing you to track container state changes, system events, alerts, notifications, and user actions.

## Overview

Every significant action in DockMon generates an event log entry with detailed information including:
- **Timestamp** - When the event occurred
- **Category** - Type of event (Container, Host, Alert, Notification, System, User)
- **Severity** - Importance level (Critical, Error, Warning, Info, Debug)
- **Host/Container** - Which resource was affected
- **Event Details** - Description of what happened
- **State Changes** - Before/after states for container events

## Accessing the Event Viewer

Navigate to **Events** in the sidebar. The Events page displays a comprehensive table-based event log viewer with advanced filtering and search capabilities.

## Features

### Real-Time Updates
Events appear in real-time as they occur via WebSocket connection. No manual refresh needed.

### Advanced Filtering

Filter events by:
- **Time Range** - Last hour, 6 hours, 12 hours, 24 hours, 48 hours, 7 days, 30 days, or all time
- **Category** - Container, Host, Alert, Notification, System, User (multi-select)
- **Severity** - Critical, Error, Warning, Info, Debug (multi-select)
- **Host** - Filter by specific Docker host (multi-select with search)
- **Container** - Filter by specific container (multi-select with search)
- **Search** - Real-time search across event titles and messages

### Sorting

Toggle between:
- **Newest First** (default) - Most recent events at the top
- **Oldest First** - Chronological order from earliest

### Pagination

Events are paginated with dynamic page sizing based on your screen height (typically 15-35 events per page) for optimal performance. Navigate between pages using the controls at the bottom. The page size automatically adjusts to fit your viewport.

## Event Categories

### Container Events
- State changes (started, stopped, paused, unpaused, restarted)
- Container created or removed
- Container renamed
- Auto-restart triggered
- Manual operations (start, stop, restart, kill)

### Host Events
- Host connected or disconnected
- Connection errors
- Host added or removed
- TLS/mTLS configuration changes

### Alert Events
- Alert rule triggered
- Alert rule created, modified, or deleted
- Escalation to critical severity

### Notification Events
- Notification sent successfully
- Notification delivery failed
- Channel configuration tested
- Notification channels added, modified, or deleted

### System Events
- DockMon service started or stopped
- Database operations
- Configuration changes
- Session management (login/logout)

### User Events
- User login/logout
- Settings changes
- Manual actions performed via UI

## Event Severity Levels

Events are categorized by severity to help you prioritize:

- 🔴 **Critical** - Immediate attention required (e.g., critical alerts, system failures)
- 🟠 **Error** - Something failed (e.g., connection errors, notification delivery failures)
- 🟡 **Warning** - Potential issues (e.g., container unhealthy, approaching limits)
- 🔵 **Info** - Normal operations (e.g., container started, alert created)
- ⚪ **Debug** - Detailed diagnostic information

## Persistence

All events are stored in the DockMon database and persist across container restarts. The database is stored in the Docker volume, ensuring your audit trail is never lost.

## Best Practices

### Regular Review
- Check events daily to stay informed about system activity
- Review critical and error events immediately
- Use time range filters to focus on recent activity

### Troubleshooting
- Search for container or host names when debugging issues
- Filter by severity "Error" or "Critical" to identify problems
- Review events before and after issues to understand what changed

### Compliance & Auditing
- Export event logs for compliance reporting (future feature)
- Use the event viewer to track who did what and when
- Filter by category "User" to see manual operations

### Performance
- Use time range filters to limit results on systems with many events
- The default "Last 24 hours" filter provides good balance of recent history and performance
- Older events remain accessible by changing the time range to "All time"

## Tips

- **Quick Search**: Use the search box to find specific containers, hosts, or error messages in real-time
- **Multiple Filters**: Combine category, severity, host, and container filters for precise results
- **Flexible Sorting**: Toggle between "Newest First" and "Oldest First" - your preference is saved
- **Multi-Select Filters**: Select multiple categories, severities, hosts, or containers simultaneously
- **Export Events**: Download filtered event data for offline analysis or reporting
- **Dynamic Sizing**: The event viewer automatically adapts to your screen height for optimal viewing
- **Filter Persistence**: Your filter selections are remembered during your session

## Related Pages

- [Alert Rules](Alert-Rules) - Configure alerts that generate events
- [Notifications](Notifications) - Notification events are logged here
- [Managing Hosts](Managing-Hosts) - Host connection events
- [Container Operations](Container-Operations) - Container state change events
