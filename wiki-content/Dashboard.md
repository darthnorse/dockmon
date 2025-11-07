# Dashboard

The Dashboard is your central command center for monitoring all Docker containers and hosts. It provides real-time insights, customizable layouts, and multiple viewing modes to suit your workflow.

## Overview

DockMon's dashboard combines flexibility with power, offering:
- **Drag-and-drop customization** - Arrange widgets to match your priorities
- **Real-time updates** - WebSocket-powered live data refresh every 2 seconds
- **Multiple view modes** - Choose between compact, standard, and expanded layouts
- **Flexible grouping** - Group hosts by tags or view all hosts together
- **Persistent layouts** - Your customizations sync across devices via database storage

## View Modes

The dashboard supports three view modes, each optimized for different use cases:

### Compact Mode
**Best for**: Quick overview, many hosts, limited screen space

Compact mode displays hosts in a dense list format with:
- Single-line host entries
- Status indicators (online/offline/error)
- Quick-access actions
- Minimal visual footprint

**When to use**: Managing 10+ hosts, quick status checks, mobile/tablet devices

### Standard Mode
**Best for**: Balanced view with essential metrics

Standard mode presents hosts in a 4-column grid with:
- Container count and status breakdown
- Key metrics at a glance
- Click-to-expand container details
- Moderate screen space usage

**When to use**: Daily monitoring, desktop displays, 5-20 hosts

### Expanded Mode
**Best for**: Detailed monitoring, power users

Expanded mode shows hosts in a 3-column grid with:
- Full container lists per host
- Detailed resource metrics
- All actions visible
- Maximum information density

**When to use**: Troubleshooting, detailed analysis, large monitors

## Dashboard Widgets

The widget dashboard provides real-time monitoring through five specialized widgets:

### 1. Host Stats Widget
**Displays**:
- Total hosts count
- Online hosts count
- Offline hosts count
- Error hosts count

**Updates**: Real-time via WebSocket
**Size**: 2 columns × 2 rows (minimum)

### 2. Container Stats Widget
**Displays**:
- Total containers count
- Running containers count
- Stopped containers count
- Error containers count

**Updates**: Real-time via WebSocket
**Size**: 2 columns × 2 rows (minimum)

### 3. Recent Events Widget
**Displays**:
- Latest 10 container events
- Event types (started, stopped, died, etc.)
- Timestamps
- Container and host names

**Updates**: Real-time via WebSocket
**Size**: 3 columns × 2 rows (minimum)

**Features**:
- Click events to view full details
- Color-coded event types
- Auto-scroll to latest events

### 4. Active Alerts Widget
**Displays**:
- Current active alerts
- Alert severity levels (critical, error, warning, info)
- Affected containers/hosts
- Alert rule names

**Updates**: Real-time via WebSocket
**Size**: 3 columns × 2 rows (minimum)

**Features**:
- Color-coded severity indicators
- Click to view alert details
- Alert count by severity

### 5. Updates Widget
**Displays**:
- Containers with available updates
- Current vs. available versions
- Update status
- Last check time

**Updates**: Polling (configurable interval)
**Size**: 2 columns × 2 rows (minimum)

**Features**:
- Click to update individual containers
- Batch update actions
- Version comparison

## Widget Layout Customization

### Drag and Drop
1. **Click and hold** the top area of any widget (drag handle)
2. **Drag** the widget to your desired position
3. **Release** to drop the widget in place
4. Layout **auto-saves** after 1 second of inactivity

### Resize Widgets
1. **Hover** over widget corners to reveal resize handles
2. **Drag** handles to adjust width/height
3. Widgets snap to a **12-column grid** system
4. Minimum sizes enforced to prevent content clipping

### Reset Layout
Click the **"Reset Layout"** button in the dashboard header to restore the default widget arrangement:
- Host Stats (top left)
- Container Stats (top center-left)
- Updates (top center-right)
- Recent Events (top right)
- Active Alerts (far right)

**Note**: Resetting layout is immediate and cannot be undone. Your custom layout will be lost.

## Grouping Modes

### Group by None (Default)
Displays all hosts in a flat list/grid based on view mode.

### Group by Tags
Groups hosts by their primary (first) tag:
- **Collapsible sections** - Expand/collapse tag groups independently
- **Drag-and-drop within groups** - Rearrange hosts within each tag group
- **Untagged group** - Hosts without tags appear in a special "Untagged" section
- **Persistent state** - Collapsed/expanded state saved per group

**Use cases**:
- Organizing by environment (production, staging, development)
- Separating by purpose (web servers, databases, cache)
- Grouping by team or project

## KPI Bar

The KPI (Key Performance Indicator) bar displays high-level metrics across all monitored resources:

**Displays**:
- Total hosts (with online/offline breakdown)
- Total containers (with running/stopped breakdown)
- Active alerts count
- Available updates count

**Toggle visibility**: Settings → Dashboard → Show KPI Bar

## Real-Time Updates

The dashboard uses WebSocket connections for instant updates:

### Update Frequency
- **Container states**: Instant (event-driven)
- **Statistics**: Every 2 seconds
- **Events**: Instant (as they occur)
- **Alerts**: Instant (as they trigger)

### Connection Status
A status indicator in the header shows WebSocket connection state:
- **Green dot**: Connected, receiving updates
- **Yellow dot**: Connecting/reconnecting
- **Red dot**: Disconnected, no real-time updates

### Reconnection
If connection is lost, DockMon automatically:
1. Attempts reconnection every 3 seconds
2. Uses exponential backoff (up to 30 seconds)
3. Falls back to polling if WebSocket unavailable

## Dashboard Settings

Access via **Settings → Dashboard**

### Available Options

**Show KPI Bar** (default: enabled)
- Display high-level metrics bar at top of dashboard
- Recommended for users monitoring multiple hosts

**Show Stats Widgets** (default: disabled)
- Display the widget grid (Host Stats, Container Stats, etc.)
- Enable for detailed real-time monitoring
- Disable to maximize space for host cards

**Dashboard View Mode** (default: standard)
- Compact: Dense list view
- Standard: Balanced grid with 4 columns
- Expanded: Detailed grid with 3 columns

**Group By** (default: none)
- None: Flat list/grid of all hosts
- Tags: Group hosts by primary tag

## Best Practices

### For Small Deployments (1-5 hosts)
- **View mode**: Expanded
- **Widgets**: Enable for detailed monitoring
- **Grouping**: None (unless tags provide meaningful organization)
- **KPI Bar**: Optional (redundant with few hosts)

### For Medium Deployments (5-20 hosts)
- **View mode**: Standard
- **Widgets**: Enable key widgets (Container Stats, Active Alerts)
- **Grouping**: By tags (production/staging/dev)
- **KPI Bar**: Enabled

### For Large Deployments (20+ hosts)
- **View mode**: Compact
- **Widgets**: Critical alerts and updates only
- **Grouping**: Essential - by environment or purpose
- **KPI Bar**: Enabled for quick overview

### Widget Organization Tips
1. **Place critical widgets top-left** (primary focus area)
2. **Group related widgets** (stats together, alerts together)
3. **Size widgets proportionally** to their importance
4. **Use vertical space efficiently** on wide monitors

### Performance Optimization
- **Disable unused widgets** to reduce WebSocket traffic
- **Use compact mode** for 20+ hosts to reduce DOM size
- **Collapse inactive tag groups** to improve render performance
- **Close unused browser tabs** running DockMon to free resources

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `R` | Refresh dashboard data |
| `Esc` | Close open modals/drawers |
| `1-5` | Switch view mode (when available) |

## Troubleshooting

### Widgets Not Updating
**Problem**: Widgets show stale data
**Solutions**:
1. Check WebSocket connection indicator (should be green)
2. Refresh browser page (`Ctrl+R` / `Cmd+R`)
3. Check browser console for connection errors
4. Verify DockMon backend is running (`docker ps | grep dockmon`)

### Layout Changes Not Saving
**Problem**: Dashboard resets to default layout on refresh
**Solutions**:
1. Wait 1 second after dragging (auto-save delay)
2. Check browser console for save errors
3. Verify database connection is healthy
4. Check browser local storage quota (Settings → Application → Storage)

### Slow Performance
**Problem**: Dashboard is laggy or unresponsive
**Solutions**:
1. Switch to Compact view mode
2. Disable unused widgets
3. Reduce number of visible hosts (use grouping + collapse)
4. Clear browser cache and reload
5. Close other browser tabs

### Missing Widgets
**Problem**: Widget grid doesn't appear
**Solutions**:
1. Enable in Settings → Dashboard → Show Stats Widgets
2. Verify widgets aren't pushed below viewport (scroll down)
3. Reset layout to defaults

## Related Documentation

- [Container Operations](Container-Operations.md) - Managing individual containers
- [Settings](Settings.md) - Customizing dashboard preferences
- [Event Viewer](https://github.com/darthnorse/dockmon/wiki/Event-Viewer) - Detailed event analysis
- [Alerts](https://github.com/darthnorse/dockmon/wiki/Alerts) - Alert rules and notifications
