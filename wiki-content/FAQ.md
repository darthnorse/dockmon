# Frequently Asked Questions (FAQ)

Quick answers to common questions about DockMon.

## General Questions

### What is DockMon?

DockMon is a comprehensive Docker container monitoring and management platform with real-time monitoring, intelligent auto-restart, multi-channel alerting, and event logging. It helps you keep track of Docker containers across multiple hosts and automatically recover from failures.

**Current version:** v2.0.0 (major rewrite with enhanced security and performance)

### Is DockMon free?

Yes! DockMon is open source and released under the MIT License. Free for personal and commercial use.

### What's new in v2?

DockMon v2 is a complete rewrite with significant improvements:

**Architecture:**
- React frontend (replaced legacy UI)
- Alpine Linux base (minimal attack surface)
- Go stats service (high performance, memory-safe)
- Python 3.13 backend
- SQLAlchemy 2.0 with Alembic migrations

**Security:**
- OpenSSL 3.x (stricter certificate validation)
- Supervisor process management
- Enhanced rate limiting
- Improved audit logging

**Performance:**
- Multi-stage Docker build (smaller image)
- Optimized container stats collection
- Faster WebSocket updates

See the [Migration Guide](Migration-Guide) for upgrade instructions.

### Does DockMon work with Docker Swarm or Kubernetes?

Currently, DockMon is designed for standalone Docker hosts and Docker Compose. Swarm and Kubernetes support is not currently available but may be added in future versions.

### Can DockMon monitor containers on remote servers?

Yes! DockMon can monitor Docker hosts anywhere on your network using secure mTLS connections. See [Remote Docker Setup](Remote-Docker-Setup).

---

## Installation & Setup

### What are the system requirements?

**DockMon v2 Requirements:**

**Minimum:**
- Docker Engine 20.10+
- Docker Compose 2.0+
- 2GB RAM
- 1GB disk space
- Port 8001 available

**Recommended:**
- Docker Engine 24.0+
- Docker Compose 2.20+
- 4GB RAM
- 5GB disk space

**Note:** v2 has a smaller footprint than v1 thanks to Alpine Linux and multi-stage builds.

### Can I run DockMon without Docker?

No, DockMon requires Docker to run and to monitor containers. It's distributed as a Docker container for ease of deployment and security isolation.

### Why do I see a certificate warning when accessing DockMon?

DockMon uses a self-signed SSL certificate for HTTPS. This is normal and secure for private use. Your browser warns you because the certificate isn't issued by a trusted authority. You can safely proceed or [replace with your own certificate](Security-Guide#tls-certificate).

### Can I change the port from 8001?

Yes! Edit `docker-compose.yml`:

```yaml
ports:
  - "8002:443"  # Use any available port
```

Then restart: `docker compose restart`

---

## Features & Functionality

### How does auto-restart work?

When enabled for a container, DockMon monitors its status. If the container stops or crashes, DockMon automatically attempts to restart it (with configurable retry attempts and delays). See [Auto-Restart](Auto-Restart).

### Can I monitor containers on multiple Docker hosts?

Yes! DockMon supports unlimited Docker hosts. Add hosts via the Host Management page. Each host can have its own containers, and all are visible in one unified dashboard.

### Does DockMon replace Docker's built-in restart policies?

No, DockMon's auto-restart works alongside Docker's restart policies. DockMon provides more granular control and visibility, but Docker's policies continue to function.

### How real-time is the monitoring?

DockMon uses WebSockets for real-time updates. Container status changes appear in the dashboard within 1-2 seconds. You can adjust the polling interval in Settings (default: 10 seconds).

### Can I customize the dashboard layout?

Yes! DockMon features a drag-and-drop dashboard:
- Drag widgets to rearrange
- Resize widgets by dragging corners
- Lock/unlock with the lock button
- Your layout is automatically saved

---

## Notifications & Alerts

### What notification services are supported?

DockMon supports:
- Discord (webhooks)
- Slack (incoming webhooks)
- Telegram (bot API)
- Pushover (push notifications)

See [Notifications](Notifications) for setup guides.

### Can I send alerts to multiple channels?

Yes! Each alert rule can notify multiple channels. For example, send critical alerts to both Discord and PagerDuty, while warnings only go to Slack.

### How do I prevent notification spam?

Use these features:
1. **Cooldown periods** - Prevent repeated alerts (default: 15 minutes)
2. **Blackout windows** - Schedule quiet hours (e.g., during maintenance)
3. **Specific trigger conditions** - Only alert on critical events

See [Alert Rules](Alert-Rules) and [Blackout Windows](Blackout-Windows).

### Can I customize notification messages?

Yes! Use custom templates with variables like `{CONTAINER_NAME}`, `{HOST_NAME}`, `{OLD_STATE}`, `{NEW_STATE}`, etc. See [Notifications](Notifications#custom-alert-templates).

---

## Security

### Is DockMon secure?

DockMon implements security best practices:
- Session-based authentication
- Bcrypt password hashing
- HTTPS-only
- Rate limiting
- Security audit logging
- Backend localhost-only binding

See [Security Guide](Security-Guide) for details.

### Why does DockMon need access to the Docker socket?

DockMon requires `/var/run/docker.sock` to monitor and control containers. This is inherent to Docker container management. See [Security Guide](Security-Guide#docker-socket-access) for implications and mitigations.

### Can I expose DockMon to the internet?

**No, we do NOT recommend this.** DockMon has Docker socket access, which means a compromised instance = compromised host. Use VPN (WireGuard, OpenVPN, Tailscale) for remote access. See [Security Guide](Security-Guide#remote-access).

### How do I reset the admin password?

Use the command-line tool:

```bash
docker exec -it dockmon python /app/backend/reset_password.py admin --interactive
```

See [First Time Setup](First-Time-Setup#if-you-forget-your-password).

---

## Remote Monitoring

### How do I monitor Docker on a remote server?

1. Configure Docker daemon on remote server to accept TLS connections
2. Generate mTLS certificates (use our automated script)
3. Add remote host in DockMon with certificates

See [Remote Docker Setup](Remote-Docker-Setup) for detailed instructions.

### Do I need to install anything on remote servers?

No additional software is needed on remote servers. You only need to configure the Docker daemon to accept secure connections and generate certificates.

### Can I monitor Docker on unRAID?

Yes! See [Platform Guides](Platform-Guides#unraid) for unRAID-specific instructions.

### Can I monitor Docker on Synology/QNAP NAS?

Yes! See platform-specific guides:
- [Synology DSM](Platform-Guides#synology-nas)
- [QNAP](Platform-Guides#qnap-nas)

---

## Performance

### How many containers can DockMon handle?

DockMon has been tested with:
- 100+ containers (no issues)
- 10+ hosts (no issues)

Performance depends on your hardware and polling interval.

### Why is the dashboard slow with many containers?

Solutions:
1. Increase polling interval (Settings → 30s or 60s)
2. Increase DockMon RAM allocation
3. Use faster storage for database
4. Remove unused hosts

See [Troubleshooting](Troubleshooting#performance-issues).

### Does DockMon use a lot of resources?

**Typical usage:**
- CPU: 1-5%
- RAM: 200-500MB
- Disk: <100MB (plus logs)

Resource usage scales with number of containers and polling frequency.

---

## Data & Backup

### Where is data stored?

All data is stored in a Docker volume: `dockmon_data`

**Contains:**
- SQLite database (`dockmon.db`)
- TLS certificates for remote hosts
- Event logs
- Configuration

### How do I backup DockMon?

```bash
# Backup database
docker cp dockmon:/app/data/dockmon.db ./backup/

# Backup entire data volume
docker run --rm \
  -v dockmon_data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/dockmon-backup.tar.gz /data
```

### How do I restore from backup?

```bash
# Stop DockMon
docker compose down

# Restore database
docker cp ./backup/dockmon.db dockmon:/app/data/

# Or restore entire volume
docker run --rm \
  -v dockmon_data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/dockmon-backup.tar.gz -C /

# Start DockMon
docker compose up -d
```

### How long are event logs kept?

Default: 30 days

Configure in Settings → Event Retention. You can also manually clean up old events.

---

## Version & Upgrades

### Should I upgrade to v2?

**Yes, if:**
- You want better security (Alpine, OpenSSL 3.x)
- You want better performance (Go stats service)
- You want modern UI (React frontend)
- You're starting fresh

**Wait if:**
- You have complex custom alert rules (need manual recreation)
- You rely on v1-specific features
- You need time to regenerate mTLS certificates

### Can I downgrade from v2 to v1?

Not recommended. v2 uses a different database schema and alert system. Downgrading requires:

1. Backup v2 database
2. Restore v1 database backup
3. Manually reconfigure hosts and alerts

### What breaks when upgrading from v1 to v2?

**Requires recreation:**
- Alert rules (schema changed)
- mTLS certificates (OpenSSL 3.x stricter validation)

**Automatically migrated:**
- Hosts and configurations
- Container history
- Event logs
- User accounts

See [Migration Guide](Migration-Guide) for detailed upgrade instructions.

---

## Updates & Upgrades

### How do I update DockMon?

**For v2 updates (v2.x to v2.y):**

```bash
cd dockmon
git pull
docker compose down
docker compose build --no-cache
docker compose up -d
```

Your data is preserved in the `dockmon_data` volume.

**For v1 to v2 upgrade:**

See the [Migration Guide](Migration-Guide) for detailed instructions. The v1→v2 upgrade includes automatic database migration but requires manual steps for certificates and alert rules.

### Will updates break my configuration?

No, updates preserve all configuration:
- Hosts and credentials
- Alert rules
- Notification channels
- Settings
- Dashboard layout

The database schema is automatically migrated if needed.

### How do I check my DockMon version?

**Check version:**
```bash
# Method 1: Check Python version and Alpine release
docker exec dockmon python -c "import sys; print(f'Python {sys.version}')"
docker exec dockmon cat /etc/alpine-release

# Method 2: Check Git tag (if installed from source)
cd dockmon
git describe --tags

# Method 3: Check Docker image tag
docker inspect dockmon | grep -A5 Labels
```

**v2 indicators:**
- Python 3.13
- Alpine Linux 3.x
- Supervisor process manager
- Go stats service on port 8081

---

## Troubleshooting

### DockMon won't start after update

**v2-specific checks:**

```bash
# View logs
docker logs dockmon

# Check supervisor status
docker exec dockmon supervisorctl status

# Check individual service logs
docker exec dockmon cat /var/log/supervisor/backend-stderr.log
docker exec dockmon cat /var/log/supervisor/nginx-stderr.log
docker exec dockmon cat /var/log/supervisor/stats-service-stderr.log

# Try rebuilding without cache
docker compose down
docker compose build --no-cache
docker compose up -d
```

### v2 upgrade failed - how do I rollback?

**Rollback to v1:**

```bash
# Stop v2
docker compose down

# Checkout v1 tag
git fetch --tags
git checkout v1.1.3

# Restore v1 database backup
docker cp ./backups/dockmon-pre-v2.db dockmon:/app/data/dockmon.db

# Rebuild and start
docker compose build --no-cache
docker compose up -d
```

**Note:** This requires a pre-upgrade backup. Always backup before upgrading!

### Containers not showing up

1. Verify host is "online"
2. Check host connection (Test Connection button)
3. Verify Docker is running on remote host
4. Check TLS certificates are correct

**v2-specific:**
5. If upgraded from v1, regenerate mTLS certificates (OpenSSL 3.x requires SANs)
6. Check Go stats service is running: `docker exec dockmon supervisorctl status stats-service`

See [Troubleshooting](Troubleshooting#container-management).

### Notifications not working

1. Test the notification channel (Test button)
2. Verify alert rule is enabled
3. Check cooldown period
4. Check blackout window

**v2-specific:**
5. If upgraded from v1, recreate alert rules (v2 uses new alert system)
6. Verify notification webhook URLs are still valid

See [Troubleshooting](Troubleshooting#notification-problems).

---

## Contributing

### How can I contribute?

- Report bugs: [GitHub Issues](https://github.com/darthnorse/dockmon/issues)
- Request features: [GitHub Discussions](https://github.com/darthnorse/dockmon/discussions)
- Submit PRs: See [Contributing](Contributing)
- Improve docs: Edit this wiki!

### Can I translate DockMon?

Internationalization (i18n) is not currently supported but is planned for future versions. Follow [GitHub Discussions](https://github.com/darthnorse/dockmon/discussions) for updates.

---

## Still have questions?

- Check the [Wiki](Home) for detailed documentation
- [Report a bug](https://github.com/darthnorse/dockmon/issues)
- [Ask in Discussions](https://github.com/darthnorse/dockmon/discussions)
- Email: [your-email] (TODO: add your email)