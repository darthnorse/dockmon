# Quick Start

Get DockMon v2 running in under 5 minutes!

> **Note:** This guide is for DockMon v2 with the modern React interface. If you're upgrading from v1, see the [Migration Guide](Migration-Guide).

## 1. Choose Your Platform

DockMon runs on any system with Docker. Pick your installation method:

- **Linux** (Ubuntu, Debian, RHEL, Fedora, etc.) - [Docker Compose Installation](Installation#docker-compose-recommended)
- **unRAID** - [Installation Guide](Installation#unraid) - Tested
- **Synology NAS** - [Installation Guide](Installation#synology-nas) - ⚠️ Untested
- **QNAP NAS** - [Installation Guide](Installation#qnap-nas) - ⚠️ Untested
- **Other platforms** - [Full Installation Guide](Installation)

Follow the installation instructions for your platform, then return here to continue setup.

---

## 2. Access DockMon

Open your browser and navigate to:

```
https://localhost:8001
```

⚠️ **You'll see a security warning** because DockMon uses a self-signed certificate. This is normal and expected.

**To proceed:**
- Chrome/Edge: Click "Advanced" → "Proceed to localhost (unsafe)"
- Firefox: Click "Advanced" → "Accept the Risk and Continue"
- Safari: Click "Show Details" → "visit this website"

## 3. First Login

**Default Credentials:**
- Username: `admin`
- Password: `dockmon123`

⚠️ **IMPORTANT:** You'll be required to change the password immediately on first login. Use a strong password!

## 4. What's Next?

### Automatic Local Docker Setup

DockMon automatically adds your local Docker instance on first startup. You should immediately see:
- Your local Docker host listed
- All running containers
- Real-time status updates

### Configure Remote Hosts (Optional)

Want to monitor Docker on other servers? See:
- [Managing Hosts](Managing-Hosts) - Add remote Docker hosts
- [Remote Docker Setup](Remote-Docker-Setup) - Configure secure remote connections

### Set Up Alerts (Optional)

Get notified when containers go down:
1. [Configure Notification Channels](Notifications) - Discord, Slack, Telegram, Pushover, Gotify, SMTP
2. [Create Alert Rules](Alert-Rules) - Define which containers to monitor

### Explore the Dashboard

DockMon v2 features a modern React-based interface with customizable widgets:

- **Dashboard Widgets** - Drag-and-drop customizable dashboard with widgets for hosts, containers, events, alerts, and updates
- **Real-Time Statistics** - Live CPU, memory, network metrics with sparkline graphs
- **Container Management** - View containers grouped by host or tags with bulk operations
- **Start/Stop/Restart** - Manage individual containers or multiple containers at once
- **Auto-Restart Toggle** - Enable automatic restart for critical containers
- **Real-Time Updates** - WebSocket-powered live updates, no refresh needed

## Verifying Installation

Check that everything is working:

```bash
# Check container status
docker ps | grep dockmon

# View logs
docker logs dockmon

# Check health
curl -k https://localhost:8001/health
```

You should see:
- Container status: `healthy`
- Logs showing successful startup
- Health check returning `{"status":"healthy"}`

## Troubleshooting

### Container shows as "unhealthy"

Wait 30-60 seconds for the health check to pass. If it remains unhealthy:

```bash
# Check logs for errors
docker logs dockmon --tail 50

# Restart the container
docker compose restart
```

### Can't access https://localhost:8001

1. Verify the container is running: `docker ps`
2. Check if port 8001 is in use: `lsof -i :8001`
3. Try accessing via IP: `https://127.0.0.1:8001`

### "Connection refused" error

The backend might still be starting. Wait 30 seconds and try again.

### More Issues?

See the [Troubleshooting](Troubleshooting) page for detailed solutions.

## Next Steps

- [First Time Setup](First-Time-Setup) - Complete initial configuration and explore v2 features
- [Dashboard Overview](Dashboard) - Learn about customizable widgets and views
- [Managing Hosts](Managing-Hosts) - Add remote Docker hosts
- [Container Tags](Container-Tags) - Organize containers with tags
- [Event Viewer](Event-Viewer) - Explore the comprehensive event log
- [Container Logs](Container-Logs) - View real-time logs from multiple containers
- [Configuration](Configuration) - Configure alerts, notifications, and automatic updates