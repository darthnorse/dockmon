# First Time Setup

Complete initial configuration after installing DockMon v2.

> **Note:** This guide covers the DockMon v2 interface with React, customizable widgets, and new features like container tags, bulk operations, and automatic updates.

## 1. Initial Login

### Access DockMon

Open your browser and navigate to:
```
https://localhost:8001
```
or
```
https://[your-server-ip]:8001
```

⚠️ **SSL Certificate Warning:** You'll see a security warning because DockMon uses a self-signed certificate. This is normal. Click "Advanced" and proceed.

### Login

**Default Credentials:**
- Username: `admin`
- Password: `dockmon123`

## 2. Change Password (Required)

⚠️ **You will be forced to change the password on first login.**

**Password Requirements:**
- Minimum 8 characters
- Mix of uppercase and lowercase
- Include numbers
- Include special characters (recommended)

**Example strong password:** `Dockm0n!Secur3`

### If You Forget Your Password

You can reset it from the command line:

```bash
# Auto-generate new password
docker exec dockmon python /app/backend/reset_password.py admin

# Set specific password
docker exec dockmon python /app/backend/reset_password.py admin --password YourNewPass123

# Interactive mode
docker exec -it dockmon python /app/backend/reset_password.py admin --interactive
```

## 3. Verify Local Docker Configuration

DockMon automatically configures local Docker monitoring on first run.

### Check Your Dashboard

You should see:
- **"Local Docker"** host listed
- All running containers visible
- Green "online" status indicator
- Real-time container updates

### If Local Docker Isn't Showing

This is rare, but if local Docker didn't auto-configure:

1. Click **"Add Host"** button
2. Enter:
   - **Name:** `Local Docker`
   - **URL:** `unix:///var/run/docker.sock`
   - Leave TLS fields empty
3. Click **"Test Connection"** then **"Save"**

## 4. Explore the Dashboard

Take a tour of the modern v2 interface:

### Top Bar
- **DockMon** logo (click to return to dashboard)
- **Navigation menu** - Quick access to all pages
- **User menu** (top-right) - Account settings, logout

### Main Navigation Pages
- **Dashboard** - Customizable widget-based overview with real-time stats
- **Hosts** - Manage Docker hosts with detailed metrics and connection status
- **Containers** - Table view of all containers with bulk operations and filtering
- **Events** - Complete event log viewer with filtering and search
- **Logs** - Real-time container logs viewer (multiple containers simultaneously)
- **Alert Rules** - Configure alert rules and triggers
- **Settings** - Global settings, notifications, blackout windows

### Dashboard Widgets (Drag & Drop)
The v2 dashboard features customizable widgets:
- **Host Stats** - Overview of all Docker hosts with CPU/memory metrics
- **Container Stats** - Running, stopped, and total container counts
- **Updates** - Containers with available image updates
- **Recent Events** - Latest container events
- **Active Alerts** - Current triggered alerts

**Widget Features:**
- **Drag & Drop** - Rearrange widgets by dragging the top area
- **Resize** - Drag corners to resize widgets
- **Reset Layout** - Click "Reset Layout" button to restore defaults
- **Persistent** - Layout saved automatically and synced across devices

### Container Management
- **Grouped Views** - Group containers by host or tags
- **Bulk Operations** - Start, stop, or restart multiple containers at once
- **Tag System** - Auto-derived tags from Docker labels plus custom tags
- **Real-Time Stats** - CPU, memory, network I/O with sparkline graphs
- **Details View** - Click any container for detailed info, logs, and events

## 5. Configure Remote Hosts (Optional)

Want to monitor Docker on other servers?

### Prerequisites
- Remote Docker host accessible via network
- mTLS configured for security (highly recommended)

### Quick Add Remote Host

1. Go to **Host Management** page
2. Click **"Add Host"**
3. Enter host details:
   - **Name:** Descriptive name (e.g., "Production Server")
   - **URL:** `tcp://192.168.1.100:2376` (use port 2376 for TLS)
   - **TLS Certificates:** Paste CA cert, client cert, client key

For detailed instructions, see [Remote Docker Setup](Remote-Docker-Setup).

## 6. Set Up Notifications (Optional)

Get notified when containers go down.

### Step 1: Add Notification Channel

1. Go to **Notifications** page
2. Click **"Add Channel"**
3. Choose a service:
   - **Discord** - Requires webhook URL
   - **Slack** - Requires webhook URL
   - **Telegram** - Requires bot token and chat ID
   - **Pushover** - Requires app token and user key
4. Test the channel
5. Save

For detailed setup instructions, see [Notifications](Notifications).

### Step 2: Create Alert Rule

DockMon v2 features an advanced alert rule engine with multiple trigger types:

1. Go to **Alert Rules** page
2. Click **"Create Alert Rule"**
3. Configure:
   - **Name:** Descriptive name (e.g., "Critical Containers Down")
   - **Trigger Type:** Choose from:
     - **Event-based** - Trigger on container events (die, stop, start, etc.)
     - **State-based** - Trigger when container enters specific state (exited, dead, etc.)
     - **Metric-based** - Trigger on CPU/memory thresholds
   - **Containers:** Select which containers to monitor (by name pattern or tags)
   - **Notification Channels:** Select your notification channel(s)
   - **Cooldown:** Prevent alert spam (e.g., 15 minutes)
4. Enable and save

For detailed instructions, see [Alert Rules](Alert-Rules).

## 7. Configure Auto-Restart (Optional)

Automatically restart containers that crash or stop unexpectedly.

### Enable for a Container

In the v2 interface, you can enable auto-restart from multiple places:
1. **Dashboard view** - Toggle auto-restart on host cards
2. **Containers page** - Use the container table actions
3. **Container details** - Toggle in the detailed container view

### Configure Retry Settings

1. Go to **Settings** page
2. Under **Auto-Restart Settings:**
   - **Max Retries:** Number of restart attempts (0-10)
   - **Retry Delay:** Seconds between attempts (5-300)
3. Save settings

For more details, see [Auto-Restart](Auto-Restart).

## 8. Customize Global Settings

The v2 Settings page is organized into sections:

1. Go to **Settings** page
2. Configure settings across different sections:
   - **System Settings:**
     - Polling Interval - How often to check container status
     - Connection Timeout - Docker API timeout
     - Event Retention - How long to keep event logs
   - **Auto-Restart Settings:**
     - Max Retries - Default retry attempts
     - Retry Delay - Seconds between restart attempts
   - **Container Updates:**
     - Enable/disable automatic update checks
     - Update check schedule
     - Auto-update containers (with optional tag patterns)
   - **Notification Channels:**
     - Configure Discord, Slack, Telegram, Pushover, Gotify, SMTP
   - **Blackout Windows:**
     - Schedule maintenance periods to suppress alerts
   - **Alert Templates:**
     - Customize notification message templates
3. Save changes in each section

## 9. Security Recommendations

### Change Password Regularly
- Go to **Account** (user menu)
- Change password every 90 days

### Secure Docker Socket
⚠️ DockMon requires `/var/run/docker.sock` access, which provides root-equivalent access.

**Best practices:**
- Don't expose DockMon to the internet
- Use VPN for remote access
- Keep DockMon updated
- Monitor security audit logs

See [Security Guide](Security-Guide) for detailed recommendations.

### Event Logging
DockMon v2 automatically logs all events:
- Container lifecycle events (start, stop, die, restart)
- Container state changes
- Host connection events
- User actions and configuration changes

View the complete event log in the **Events** page with:
- Real-time updates via WebSocket
- Advanced filtering by host, container, event type, and time range
- Full-text search
- Export capabilities

## 10. Optional Features

### Blackout Windows (Quiet Hours)
Suppress alerts during maintenance windows.

1. Go to **Settings** page
2. Scroll to **Blackout Windows** section
3. Add blackout window:
   - **Name:** e.g., "Nightly Maintenance"
   - **Time:** Start and end times
   - **Days:** Which days of the week
   - **Enabled:** Toggle to activate
4. Save

See [Blackout Windows](Blackout-Windows) for details.

### Custom Alert Templates
Customize notification messages.

1. Go to **Settings** page
2. Scroll to **Alert Templates** section
3. Edit template using variables:
   - `{CONTAINER_NAME}` - Container name
   - `{HOST_NAME}` - Host name
   - `{OLD_STATE}` → `{NEW_STATE}` - State change
   - `{TIMESTAMP}` - When it happened
4. Save template

See [Notifications](Notifications) for all available variables.

### Container Tags
Organize containers with tags (v2 feature):

- **Auto-derived tags** - DockMon automatically creates tags from Docker labels
- **Custom tags** - Add your own tags to containers
- **Group by tags** - View containers grouped by tags on the Hosts page
- **Tag-based alerts** - Create alert rules targeting specific tags

Manage tags in the container details view or use bulk tag operations on the Containers page.

### Automatic Updates
Keep containers up-to-date automatically:

1. Go to **Settings** page → **Container Updates** section
2. Configure:
   - **Enable update checks** - Check for new image versions
   - **Update schedule** - When to check (daily, weekly, etc.)
   - **Auto-update** - Automatically update containers
   - **Tag filters** - Only update containers with specific tags
3. View available updates in the **Updates** widget on the dashboard

See [Container Updates](Container-Updates) for details.

## Troubleshooting Setup

### Can't Login After Password Change
Reset password via command line:
```bash
docker exec dockmon python /app/backend/reset_password.py admin --interactive
```

### Local Docker Not Showing Containers
1. Verify Docker socket is mounted: `docker inspect dockmon | grep docker.sock`
2. Check DockMon has access: `docker exec dockmon ls -l /var/run/docker.sock`
3. Restart DockMon: `docker compose restart`

### Notifications Not Working
1. Test the notification channel (click "Test" button)
2. Check alert rule is enabled
3. Verify container matches the alert rule pattern
4. Check cooldown period hasn't been triggered

For more help, see [Troubleshooting](Troubleshooting).

## Next Steps

Now that setup is complete, explore the v2 features:
- [Dashboard Overview](Dashboard) - Learn about widget customization and views
- [Managing Hosts](Managing-Hosts) - Add remote Docker hosts
- [Container Operations](Container-Operations) - Manage containers and bulk operations
- [Container Tags](Container-Tags) - Organize with tags
- [Event Viewer](Event-Viewer) - Explore the event log
- [Container Logs](Container-Logs) - View real-time logs
- [Configuration](Configuration) - Advanced configuration options