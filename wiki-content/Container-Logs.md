# Container Logs

The Container Logs viewer provides real-time access to container logs with support for viewing multiple containers simultaneously. This powerful tool is designed for debugging, monitoring, and troubleshooting containerized applications.

## Overview

DockMon v2 provides integrated container log viewing with real-time updates and advanced filtering. Access container logs by clicking any container card in the Dashboard to open the container details view with tabs for Overview, Stats, Health, and **Logs**.

**Note:** If you have "Simplified Workflow" disabled in Settings → Dashboard, clicking a container will open a drawer instead, which also provides access to the Logs tab.

## Accessing Container Logs

### Primary Method (Default)

1. Click on any container card in the Dashboard
2. The container details view opens (or drawer if Simplified Workflow is disabled)
3. Click the **Logs** tab
4. View real-time logs for that container

## Log Viewer Features

### Real-Time Updates
- **Auto-refresh** - Logs update automatically every 2-3 seconds
- **Live streaming** - See new log entries as they occur
- **Manual refresh** - Click refresh button to force update
- **Pause/Resume** - Toggle auto-refresh on/off as needed

### Filtering & Search
- **Text Search** - Real-time filtering by keyword or pattern
- **Line Count** - Select how many lines to display:
  - 50 lines (fast loading)
  - 100 lines (default)
  - 200 lines
  - 500 lines
  - 1000 lines
  - All lines (may be slow for large logs)
- **Timestamps** - Toggle timestamp display on/off
- **Since/Until** - Filter logs by time range

### Display Options
- **Newest First** (default) - Most recent logs at the top
- **Oldest First** - Chronological order from start
- **Wrap Lines** - Toggle line wrapping for long log entries
- **Monospace Font** - Fixed-width font for better readability

### Export & Actions
- **Download Logs** - Export current view to `.txt` file
- **Copy to Clipboard** - Copy selected or all logs
- **Clear Display** - Clear the current view (doesn't delete logs from container)
- **Full Screen** - Expand logs to full screen view (desktop only)

## Log Display Format

### With Timestamps
```
2025-10-18T14:23:45.123Z  nginx: 192.168.1.100 - - [18/Oct/2025:14:23:45 +0000] "GET /api/health HTTP/1.1" 200 158
```

### Without Timestamps
```
nginx: 192.168.1.100 - - [18/Oct/2025:14:23:45 +0000] "GET /api/health HTTP/1.1" 200 158
```

### Log Levels with Color Coding
DockMon automatically detects and highlights log levels:
- **ERROR/FATAL** - Red text
- **WARN/WARNING** - Yellow text
- **INFO** - Blue text
- **DEBUG/TRACE** - Gray text

**Note**: Some applications include their own timestamps in log messages. The DockMon timestamp shows when the log was received from Docker.

## Performance Optimization

### Smart Loading
- Logs are fetched on-demand when you open the Logs tab
- Automatic pagination for containers with large log volumes
- Efficient WebSocket streaming for real-time updates
- Client-side caching reduces API calls

### Resource Management
- Auto-refresh pauses when tab is not visible
- Configurable line limits prevent memory issues
- Search filtering happens client-side for instant results
- Background polling adapts to system load

### Best Practices for Large Logs
- Start with 100-200 lines, increase if needed
- Use text search to narrow down relevant entries
- Export logs if you need to analyze all historical data
- Consider using Docker's native logging drivers for long-term storage

## Use Cases

### Debugging Applications
- **Monitor Startup** - Watch initialization logs when container starts
- **Track Requests** - Follow HTTP requests through the application
- **Find Errors** - Search for error keywords and stack traces
- **Verify Config** - Check configuration loading and environment variables

### Troubleshooting Crashes
- **Check Exit Codes** - Review logs before container stopped
- **Find OOM Events** - Search for out-of-memory errors
- **Review Stack Traces** - Export and analyze full error traces
- **Compare Versions** - Check logs from different image versions

### Performance Analysis
- **Response Times** - Monitor API response times in logs
- **Database Queries** - Track slow queries and connection issues
- **Resource Warnings** - Watch for memory/CPU warnings
- **Request Patterns** - Identify traffic spikes and patterns

### Development & Testing
- **Live Debugging** - Watch logs during development and testing
- **Integration Testing** - Verify service communication via logs
- **Environment Validation** - Check configuration in different environments
- **Feature Verification** - Confirm new features are logging correctly

## Keyboard Shortcuts

Enhance your log viewing experience with keyboard shortcuts:

- `Ctrl/Cmd + F` - Focus search box
- `Ctrl/Cmd + R` - Refresh logs
- `Ctrl/Cmd + K` - Clear display
- `Ctrl/Cmd + D` - Download logs
- `Space` - Pause/Resume auto-refresh
- `Esc` - Close drawer/modal
- `↑/↓` - Scroll through logs
- `Home/End` - Jump to top/bottom

## Best Practices

### Effective Log Analysis
- **Start Narrow** - Begin with 50-100 lines, expand if needed
- **Use Search** - Filter for error keywords, request IDs, or specific events
- **Check Timestamps** - Correlate events across containers using timestamps
- **Watch Patterns** - Look for repeated errors or warning patterns
- **Export First** - Download logs before clearing if you need to reference them later

### Real-Time Monitoring
- **Keep Auto-Refresh On** - Stay updated with live container output
- **Monitor Startup** - Watch logs during container restarts to catch initialization issues
- **Track Errors** - Search for "error", "fatal", "exception" to spot problems quickly
- **Correlate Events** - Cross-reference logs with Events page for full context

### Troubleshooting
- **Check Exit Codes** - Look for "exit code" in logs when containers crash
- **Review Startup** - First 100 lines often reveal configuration issues
- **Search Stack Traces** - Filter for complete error stack traces
- **Compare Hosts** - Check logs from same container on different hosts for inconsistencies

### Performance Tips
- **Limit Line Count** - Use 100-200 lines for daily monitoring
- **Pause When Reading** - Disable auto-refresh while analyzing specific entries
- **Clear Old Logs** - Clear display periodically during long debugging sessions
- **Use Time Filters** - Filter by time range to focus on specific incidents

## Limitations

- **Docker Log Driver Dependent** - Only works with json-file and journald log drivers
- **No Historical Storage** - DockMon doesn't store logs; fetched from Docker in real-time
- **Large Log Performance** - Containers with massive logs (10k+ lines) may load slowly
- **No Multi-Container View** - v2 focuses on single-container log viewing for clarity
- **Line Limit** - Maximum 1000 lines per fetch to prevent browser performance issues

## Tips

- **Quick Access**: Click any container card → Logs tab for instant log access
- **Smart Search**: Search is case-insensitive and searches across all visible log lines
- **Auto-Scroll**: New logs automatically scroll to bottom when auto-refresh is on
- **Line Wrapping**: Enable line wrap for long log entries (toggle in display options)
- **Context Switching**: Keep drawer open and switch between Overview, Stats, and Logs tabs
- **Export Format**: Downloaded logs include timestamps and are formatted for easy reading
- **Follow Mode**: Keep newest-first sorting with auto-refresh to "follow" logs like `tail -f`

## Related Pages

- [Event Viewer](Event-Viewer) - System-wide event audit trail
- [Container Operations](Container-Operations) - Managing containers
- [Managing Hosts](Managing-Hosts) - Multi-host container access
- [Troubleshooting](Troubleshooting) - Common issues and solutions
