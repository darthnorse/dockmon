# DockMon v1.1.0 Roadmap

## Planned Features

### 1. CPU/RAM Graphs in Host Widget Header
- Add real-time CPU and RAM usage graphs to each host widget
- Display mini sparkline charts showing recent usage trends
- Update graphs automatically as metrics are received
- Visual feedback to quickly identify resource-constrained hosts

### 2. CPU/RAM in Container Modal
- Show detailed CPU and RAM usage for individual containers
- Display current usage percentage and absolute values
- Include historical trend graphs
- Help users identify resource-heavy containers

### 3. Auto-Update of Container Images at Schedule
- Allow users to configure automatic container image updates
- Set update schedules per container or globally
- Options for update frequency (daily, weekly, custom cron)
- Safety features:
  - Backup before update
  - Rollback on failure
  - Update windows/blackout periods
  - Notifications on update success/failure
- Manual override to skip scheduled updates

## Implementation Notes
- Use ES6 modules where appropriate
- Maintain backward compatibility with existing features
- Add new API endpoints for metrics collection
- Ensure mobile responsiveness for new UI elements
- Add comprehensive error handling and logging

## Version Changes
- Update login page: "DockMon v1.1.0"
- Update about section with new version number
- Update changelog with new features
