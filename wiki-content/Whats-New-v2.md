# What's New in v2.0.0

> **DockMon v2.0.0** is a complete rewrite with modern architecture, advanced monitoring capabilities, and a beautiful new React-based UI.

## 🎨 Modern User Interface

### Complete React Rewrite
- Built with **React 18 + TypeScript + Vite**
- Beautiful dark theme using **Tailwind CSS** and **shadcn/ui**
- Fully responsive - works on desktop, tablet, and mobile
- Real-time updates via WebSocket
- Smooth animations and loading states

### Enhanced Dashboard
- **Multiple view modes**: Grid, Grouped by host, Compact grouped
- **Group by tags**: Organize by Compose projects, custom tags, or no grouping
- **KPI widgets**: System status at a glance
- **Real-time sparklines**: CPU, memory, network charts per container
- **Smart filtering**: Instant filter by host, state, tags
- **Bulk selection**: Multi-select containers for batch operations

### User Preferences
- **Persistent settings**: Your view preferences saved per user
- **Dashboard layout**: Your chosen view mode and grouping remembered
- **Filter persistence**: Last used filters restored on page load
- **Dark theme**: Optimized for long monitoring sessions

## 🚨 Advanced Alert System

### Flexible Alert Rules
- **Metric-driven alerts**: Monitor CPU, memory, disk usage with thresholds
- **Event-driven alerts**: Container stopped, health check failures, updates available
- **Smart targeting**: Alert on all resources, specific selections, or tag-based filters
- **Alert deduplication**: Prevent spam with configurable cooldowns and occurrence thresholds

### Multi-Channel Notifications
- **6 notification channels**: Telegram, Discord, Slack, Pushover, Gotify, SMTP
- **Custom templates**: Override default messages per rule or globally
- **Exponential backoff**: Automatic retry with intelligent backoff on failures
- **Channel management**: Enable/disable channels, test before saving

### Alert Management
- **Alert history**: View all fired alerts with filtering
- **Alert annotations**: Add notes and context to alerts
- **Auto-resolve**: Automatically resolve alerts when conditions clear
- **Snooze alerts**: Temporarily silence specific alerts
- **Suppression**: Suppress alerts during container updates

## 🔄 Container Update Management

### Update Detection
- **Automatic checking**: Daily checks for new container images
- **Floating tag tracking**: Monitor `latest`, `stable`, or semantic versions
- **Multi-registry support**: DockerHub, GHCR, and custom private registries
- **Update status**: Clear indication of which containers have updates

### Update Policies
- **Pattern-based rules**: Allow, warn, or block updates by pattern
- **Built-in categories**: Pre-configured patterns for databases, proxies, critical services
- **Custom patterns**: Create your own update validation rules
- **Compose-aware**: Optionally skip Docker Compose containers

### Update Execution
- **One-click updates**: Update containers with a single click
- **Batch updates**: Update multiple containers simultaneously
- **Progress tracking**: Real-time progress for each update
- **Automatic rollback**: Rollback on failure with backup creation
- **Update alerts**: Get notified when updates complete or fail

### Private Registry Support
- **Encrypted credentials**: Store registry credentials securely
- **Multiple registries**: DockerHub, GHCR, custom registries
- **Per-image auth**: Automatic authentication per container

## 🏥 HTTP Health Checks

### Custom Health Monitoring
- **HTTP/HTTPS endpoints**: Monitor web services and APIs
- **Flexible configuration**: Custom headers, auth, timeouts, SSL verification
- **Method support**: GET, POST, HEAD requests
- **Expected status codes**: Define success criteria (200, 200-299, etc.)

### Health Check Features
- **Auto-restart integration**: Restart containers after consecutive failures
- **Alert integration**: Trigger alerts on health check failures
- **History tracking**: Success/failure counts and response times
- **Status dashboard**: Visual health indicators per container

## 🎯 Container Organization

### Tagging System
- **Auto-derived tags**: Automatically extract from Docker Compose labels
- **Custom tags**: Add your own organizational tags
- **Bulk tagging**: Apply tags to multiple containers at once
- **Tag-based filtering**: Quickly find containers by tag
- **Tag-based alerting**: Create alerts targeting specific tags

### Desired State Tracking
- **Should Run**: Containers that should always be running
- **On-Demand**: Containers that run as needed
- **Alert severity**: Different alert rules for different container types

## 🏢 Multi-Host Management

### Host Organization
- **Host tagging**: Organize hosts with custom tags (prod, staging, region)
- **Bulk operations**: Add, edit, delete multiple hosts
- **Security status**: Visual indicators for mTLS-secured connections
- **Host metrics**: CPU, memory, disk usage per Docker host
- **System info**: OS version, Docker version, daemon uptime

### Enhanced Host Views
- **Host drawer**: Quick overview without leaving the page
- **Host modal**: Detailed view with containers, events, metrics
- **Connection status**: Real-time connection monitoring
- **Container count**: See containers per host at a glance

## 📅 Blackout Windows

### Scheduled Maintenance
- **Blackout periods**: Suppress alerts during planned maintenance
- **Recurring schedules**: Daily, weekly, or one-time windows
- **Visual indicators**: Banner shows when blackout is active
- **Flexible timing**: Configure start/end times and days of week

## 🔐 Security Enhancements

### Authentication & Authorization
- **Session-based auth**: Secure HTTP-only session cookies
- **Password management**: Change password from user menu
- **Rate limiting**: Protection against brute force attacks
- **API security**: All endpoints require authentication

### Encrypted Storage
- **Registry credentials**: Private registry passwords encrypted at rest
- **Secure transmission**: All communication over HTTPS
- **mTLS support**: Client certificate authentication for Docker hosts

## 📖 Event Logging & Audit Trail

### Comprehensive Event System
- **Event categories**: Container, host, system, alert, notification events
- **Event correlation**: Related events linked with correlation IDs
- **Rich filtering**: Filter by category, severity, host, container, time
- **Full-text search**: Search across event titles and messages
- **Real-time updates**: Events appear instantly via WebSocket

### Event Details
- **Performance metrics**: Event timing for debugging
- **Context information**: Full details for troubleshooting
- **Export capability**: Download events for analysis

## 📦 Container Details Enhancement

### Tabbed Interface
- **Info tab**: Ports, volumes, environment, restart policy
- **Updates tab**: Update status, policies, execution
- **Health Check tab**: HTTP health check configuration
- **Alerts tab**: Alerts specific to this container
- **Events tab**: Container-specific event history
- **Logs tab**: Real-time container logs with filtering

### Live Logs
- **Real-time streaming**: See logs as they happen
- **Log filtering**: Filter by keywords
- **Auto-scroll**: Follow mode for live monitoring
- **Multi-container**: View logs from multiple containers

## 🔧 Technical Improvements

### Backend Architecture
- **Event bus**: Decoupled event processing
- **Batch job manager**: Queue-based batch operations
- **Stats history**: Historical data for sparkline charts
- **Composite keys**: Proper multi-host container identification
- **Async Docker SDK**: Non-blocking Docker operations
- **Database migrations**: Alembic-based schema management

### Frontend Architecture
- **React Query**: Intelligent caching and background refetch
- **Type safety**: Full TypeScript coverage with strict mode
- **Component library**: Reusable shadcn/ui components
- **Adaptive polling**: Efficient polling with visibility API
- **WebSocket reconnection**: Automatic reconnection with backoff

### Performance Optimizations
- **50% fewer API calls**: Intelligent caching with React Query
- **WebSocket updates**: No constant polling needed
- **Lazy loading**: Container details loaded on demand
- **Optimized rendering**: Virtual scrolling for large lists
- **Async wrappers**: Non-blocking Docker SDK calls

## 🔄 Migration from v1

### What's Preserved
- ✅ Hosts and configurations
- ✅ Container history
- ✅ Event logs
- ✅ User accounts

### What Needs Reconfiguration
- ⚠️ Alert rules (new alert system)
- ⚠️ mTLS certificates (OpenSSL 3.x requirements)

### Migration Steps
1. **Backup your database** before upgrading
2. Pull the v2.0.0 Docker image
3. Stop and remove the v1 container
4. Start the v2 container (migration runs automatically)
5. Regenerate mTLS certificates for remote hosts
6. Recreate alert rules using the new system

See the [Migration Guide](https://github.com/darthnorse/dockmon/wiki/Migration-Guide) for detailed instructions.

## 🎁 Quality of Life Improvements

- **Toast notifications**: Instant feedback for all actions
- **Loading skeletons**: Better perceived performance
- **Keyboard shortcuts**: Navigate faster (coming in v2.1)
- **Persistent filters**: Your filters remembered
- **Smart defaults**: Sensible default configurations
- **Error messages**: Clear, actionable error descriptions

## 🐛 Bug Fixes from v1

- Fixed container ID collision issues with composite keys
- Fixed memory leaks in stats monitoring
- Fixed WebSocket reconnection race conditions
- Fixed alert deduplication edge cases
- Fixed timezone handling for timestamps
- Improved error handling throughout

---

**Ready to upgrade?** See the [Installation Guide](https://github.com/darthnorse/dockmon/wiki/Installation) to get started!

**Questions?** Join the [Discussions](https://github.com/darthnorse/dockmon/discussions) or check the [FAQ](https://github.com/darthnorse/dockmon/wiki/FAQ).
