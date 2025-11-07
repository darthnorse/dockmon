# Welcome to DockMon

![DockMon](https://img.shields.io/badge/DockMon-v2.0-blue.svg)

DockMon is a comprehensive Docker container monitoring and management platform with real-time monitoring, intelligent auto-restart, multi-channel alerting, and complete event logging.

> **Upgrading from v1?** See the [Migration Guide](Migration-Guide) for step-by-step instructions on upgrading to v2.0.

## Quick Links

- **[Quick Start](Quick-Start)** - Get DockMon running in 5 minutes
- **[Installation](Installation)** - Detailed installation guides for all platforms
- **[User Guide](Dashboard)** - Learn how to use DockMon
- **[Configuration](Configuration)** - Configure alerts, notifications, and settings
- **[What's New in v2](Whats-New-v2)** - Explore new features and improvements

## Key Features

- **Multi-Host Monitoring** - Monitor containers across unlimited Docker hosts (local and remote)
- **Customizable Dashboard** - Drag-and-drop widgets, personalized layouts, and real-time WebSocket updates
- **Container Tagging** - Organize and filter containers with custom tags
- **Bulk Operations** - Perform actions on multiple containers simultaneously
- **Intelligent Auto-Restart** - Per-container auto-restart with configurable retry logic and backoff
- **Automatic Updates** - Auto-update containers when new images are available
- **Health Checks** - HTTP/HTTPS endpoint monitoring with customizable intervals
- **Enhanced Alerting** - Metric-based and event-based alerts via Discord, Slack, Telegram, Pushover
- **Event Logging** - Comprehensive audit trail of all container and system events
- **Secure** - Session-based authentication, rate limiting, mTLS for remote hosts
- **Mobile-Friendly** - Responsive design that works on all devices

## Documentation Structure

### Getting Started
Start here if you're new to DockMon:
1. [Quick Start](Quick-Start) - Deploy DockMon in 5 minutes
2. [Installation](Installation) - Platform-specific installation guides
3. [First Time Setup](First-Time-Setup) - Initial configuration

### User Guide
Learn how to use DockMon:
- [Dashboard Overview](Dashboard) - Understanding the dashboard and customization
- [Managing Hosts](Managing-Hosts) - Add and manage Docker hosts
- [Container Operations](Container-Operations) - Start, stop, restart containers
- [Container Tags](Container-Tags) - Organize containers with custom tags
- [Bulk Operations](Bulk-Operations) - Manage multiple containers at once
- [Auto-Restart](Auto-Restart) - Configure automatic container restart
- [Health Checks](Health-Checks) - Monitor container HTTP/HTTPS endpoints
- [Automatic Updates](Automatic-Updates) - Keep containers up-to-date automatically

### Configuration
Configure DockMon for your needs:
- [Alert Rules](Alert-Rules) - Set up container alerts
- [Notifications](Notifications) - Configure Discord, Slack, Telegram, Pushover
- [Blackout Windows](Blackout-Windows) - Schedule quiet hours
- [Settings](Settings) - Global settings and preferences

### Advanced Topics
- [Remote Docker Setup](Remote-Docker-Setup) - Monitor remote Docker hosts
- [Security Guide](Security-Guide) - Security best practices
- [API Reference](API-Reference) - REST and WebSocket APIs

### Development
- [Development Setup](Development-Setup) - Set up local development environment
- [Architecture](Architecture) - System architecture overview
- [Technology Stack](Technology-Stack) - React 18, Go 1.23, Python 3.13, Alpine Linux
- [Contributing](Contributing) - How to contribute to DockMon
- [Testing](Testing) - Running tests

### Help
- [Troubleshooting](Troubleshooting) - Common issues and solutions
- [FAQ](FAQ) - Frequently asked questions

## Community & Support

- [Report Issues](https://github.com/darthnorse/dockmon/issues)
- [Discussions](https://github.com/darthnorse/dockmon/discussions)
- [Star on GitHub](https://github.com/darthnorse/dockmon)

## License

DockMon is released under the [MIT License](https://github.com/darthnorse/dockmon/blob/main/LICENSE).