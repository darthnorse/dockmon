# Notifications

Configure multi-channel notifications to get alerts when containers go down or experience issues.

## Supported Services

DockMon v2 supports the following notification channels:

- **Discord** - Discord webhooks
- **Slack** - Slack incoming webhooks
- **Telegram** - Telegram bot API
- **Pushover** - Pushover push notifications
- **Gotify** - Self-hosted notification server
- **SMTP** - Email notifications via SMTP

All channels support rich message formatting with container details, host information, alert context, and timestamps.

## Adding a Notification Channel

### Step 1: Create Channel in DockMon

1. Navigate to **Settings** in the sidebar
2. Scroll down to the **Notification Channels** section
3. Click **"Add Channel"** button
4. Fill in details:
   - **Name:** Descriptive name (e.g., "Production Alerts Discord")
   - **Type:** Select service (Telegram, Discord, Slack, Pushover, Gotify, Email/SMTP)
   - **Configuration:** Enter service-specific details (see below)
   - **Enabled:** Check to activate (enabled by default)
5. Click **"Test"** to verify configuration (optional but recommended)
6. Click **"Save"**

### Step 2: Link to Alert Rule

Notification channels must be linked to Alert Rules to receive notifications. When creating or editing an alert rule, select which notification channels should receive alerts. See [Alert Rules](Alert-Rules) for detailed instructions.

---

## Discord Setup

Discord webhooks are the easiest way to get alerts in Discord channels.

### Create Discord Webhook

1. **Open Discord** and go to your server
2. **Right-click on a channel** → **Edit Channel**
3. Go to **Integrations** → **Webhooks**
4. Click **"Create Webhook"** or **"New Webhook"**
5. **Customize:**
   - Name: `DockMon` (or your preference)
   - Avatar: Optional custom icon
   - Channel: Select where alerts should appear
6. **Copy the Webhook URL** (looks like `https://discord.com/api/webhooks/...`)
7. Click **"Save"**

### Add to DockMon

1. In DockMon, navigate to **Settings** → **Notification Channels**
2. Click **"Add Channel"**
3. Enter:
   - **Name:** `Production Discord` (or your preference)
   - **Type:** `Discord`
   - **Webhook URL:** Paste the URL you copied
   - **Enabled:** Checked (default)
4. Click **"Test"** - you should see a test message in Discord
5. Click **"Save"**

### Example Configuration

```json
{
  "name": "Discord Alerts",
  "type": "discord",
  "config": {
    "webhook_url": "https://discord.com/api/webhooks/1234567890/AbCdEfGhIjKlMnOpQrStUvWxYz"
  },
  "enabled": true
}
```

### Discord Message Format

DockMon sends formatted Discord embeds with:
- **Color coding:** Red for errors, Green for recovery
- **Container name** and status
- **Host information**
- **Timestamp**
- **Alert rule name**

---

## Slack Setup

Slack incoming webhooks allow DockMon to post messages to Slack channels.

### Create Slack Webhook

1. **Go to Slack API:** https://api.slack.com/apps
2. Click **"Create New App"** → **"From scratch"**
3. **App Name:** `DockMon`
4. **Workspace:** Select your workspace
5. Click **"Create App"**
6. In the left sidebar, click **"Incoming Webhooks"**
7. **Toggle "Activate Incoming Webhooks"** to ON
8. Scroll down and click **"Add New Webhook to Workspace"**
9. **Select a channel** where alerts should appear
10. Click **"Allow"**
11. **Copy the Webhook URL** (looks like `https://hooks.slack.com/services/...`)

### Add to DockMon

1. In DockMon, navigate to **Settings** → **Notification Channels**
2. Click **"Add Channel"**
3. Enter:
   - **Name:** `Slack Alerts` (or your preference)
   - **Type:** `Slack`
   - **Webhook URL:** Paste the URL you copied
   - **Enabled:** Checked (default)
4. Click **"Test"** - you should see a test message in Slack
5. Click **"Save"**

### Example Configuration

```json
{
  "name": "Slack Alerts",
  "type": "slack",
  "config": {
    "webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX"
  },
  "enabled": true
}
```

---

## Telegram Setup

Telegram requires a bot token and chat ID.

### Step 1: Create Telegram Bot

1. **Open Telegram** and search for `@BotFather`
2. Start a chat and send `/newbot`
3. **Choose a name** for your bot (e.g., `DockMon Alerts`)
4. **Choose a username** (must end in `bot`, e.g., `dockmon_alerts_bot`)
5. **Copy the bot token** (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 2: Get Chat ID

**Option A: Use a User Chat**
1. Search for `@userinfobot` in Telegram
2. Start a chat with it
3. It will reply with your **user ID** (e.g., `123456789`)

**Option B: Use a Group Chat**
1. Create a new group in Telegram
2. Add your bot to the group
3. Add `@userinfobot` to the group
4. The bot will display the **group chat ID** (looks like `-987654321`)
5. Remove `@userinfobot` from the group

### Add to DockMon

1. In DockMon, navigate to **Settings** → **Notification Channels**
2. Click **"Add Channel"**
3. Enter:
   - **Name:** `Telegram Alerts`
   - **Type:** `Telegram`
   - **Bot Token:** Paste bot token from BotFather
   - **Chat ID:** Paste your user ID or group chat ID
   - **Enabled:** Checked (default)
4. Click **"Test"** - you should receive a test message in Telegram
5. Click **"Save"**

### Example Configuration

```json
{
  "name": "Telegram Alerts",
  "type": "telegram",
  "config": {
    "bot_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
    "chat_id": "123456789"
  },
  "enabled": true
}
```

---

## Pushover Setup

Pushover provides reliable push notifications to iOS, Android, and desktop.

### Step 1: Create Pushover Account

1. **Sign up** at https://pushover.net
2. **Download the Pushover app** on your device
3. Log in to the app with your account

### Step 2: Create Application

1. **Go to:** https://pushover.net/apps/build
2. Click **"Create an Application/API Token"**
3. Fill in:
   - **Name:** `DockMon`
   - **Type:** Application
   - **Description:** Docker container monitoring alerts
   - **URL:** `https://github.com/darthnorse/dockmon` (optional)
4. Accept terms and click **"Create Application"**
5. **Copy the API Token/Key** (looks like `azGDORePK8gMaC0QOYAMyEEuzJnyUi`)

### Step 3: Get User Key

1. On your Pushover dashboard, you'll see **"Your User Key"**
2. **Copy the user key** (looks like `uQiRzpo4DXghDmr9QzzfQu27cmVRsG`)

### Add to DockMon

1. In DockMon, navigate to **Settings** → **Notification Channels**
2. Click **"Add Channel"**
3. Enter:
   - **Name:** `Pushover Alerts`
   - **Type:** `Pushover`
   - **App Token:** Paste application API token
   - **User Key:** Paste your user key
   - **Enabled:** Checked (default)
4. Click **"Test"** - you should receive a push notification
5. Click **"Save"**

### Example Configuration

```json
{
  "name": "Pushover Alerts",
  "type": "pushover",
  "config": {
    "app_token": "azGDORePK8gMaC0QOYAMyEEuzJnyUi",
    "user_key": "uQiRzpo4DXghDmr9QzzfQu27cmVRsG"
  },
  "enabled": true
}
```

---

## Gotify Setup

Gotify is a self-hosted notification server perfect for privacy-conscious users.

### Step 1: Install Gotify Server

**Using Docker (Recommended):**

```bash
docker run -d \
  --name gotify \
  -p 8080:80 \
  -v /path/to/gotify/data:/app/data \
  gotify/server
```

**Using Docker Compose:**

```yaml
version: "3"
services:
  gotify:
    image: gotify/server
    ports:
      - "8080:80"
    volumes:
      - /path/to/gotify/data:/app/data
    restart: unless-stopped
```

Access Gotify at `http://your-server-ip:8080`

Default credentials: `admin` / `admin` (change immediately!)

### Step 2: Create Gotify Application

1. **Log in to Gotify** web interface
2. Click **"Apps"** in the sidebar
3. Click **"Create Application"**
4. Enter:
   - **Name:** `DockMon`
   - **Description:** Docker container monitoring alerts
5. Click **"Create"**
6. **Copy the token** that appears (looks like `AaBbCcDd123456`)

⚠️ **Important:** The token is only shown once! Save it immediately.

### Add to DockMon

1. In DockMon, navigate to **Settings** → **Notification Channels**
2. Click **"Add Channel"**
3. Enter:
   - **Name:** `Gotify Alerts`
   - **Type:** `Gotify`
   - **Server URL:** Your Gotify server URL (e.g., `http://192.168.1.100:8080`)
   - **App Token:** Paste the token you copied
   - **Enabled:** Checked (default)
4. Click **"Test"** - you should see a notification in Gotify
5. Click **"Save"**

### Example Configuration

```json
{
  "name": "Gotify Alerts",
  "type": "gotify",
  "config": {
    "server_url": "http://192.168.1.100:8080",
    "app_token": "AaBbCcDd123456"
  },
  "enabled": true
}
```

### Priority Levels

Gotify notifications include priority levels:
- **Priority 5 (Normal):** Info messages, container starts/stops
- **Priority 8 (High):** Critical events, container crashes, OOM events

### Mobile App

Download the Gotify mobile app:
- **Android:** [Google Play](https://play.google.com/store/apps/details?id=com.github.gotify)
- **F-Droid:** [F-Droid Store](https://f-droid.org/packages/com.github.gotify/)

Configure the app to point to your Gotify server URL.

---

## SMTP Setup (Email)

Send email notifications using any SMTP server (Gmail, Outlook, custom server, etc.).

### Gmail Setup (Recommended for Testing)

Gmail requires an **App Password** (not your regular password).

#### Step 1: Enable 2-Factor Authentication

1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** if not already enabled

#### Step 2: Create App Password

1. Go to https://myaccount.google.com/apppasswords
2. Select:
   - **App:** Mail
   - **Device:** Other (Custom name) → Enter `DockMon`
3. Click **"Generate"**
4. **Copy the 16-character password** (looks like `abcd efgh ijkl mnop`)

### Add to DockMon

1. In DockMon, navigate to **Settings** → **Notification Channels**
2. Click **"Add Channel"**
3. Enter:
   - **Name:** `Email Alerts`
   - **Type:** `Email (SMTP)`
   - **SMTP Server:** `smtp.gmail.com` (or your SMTP server)
   - **SMTP Port:** `587` (STARTTLS) or `465` (SSL/TLS)
   - **Username:** Your email address
   - **Password:** App password (for Gmail) or your email password
   - **From Email:** Your email address
   - **To Email:** Destination email address (can be the same)
   - **Use TLS/STARTTLS:** Checked (for ports 587/465)
   - **Enabled:** Checked (default)
4. Click **"Test"** - you should receive a test email
5. Click **"Save"**

### Example Configuration (Gmail)

```json
{
  "name": "Email Alerts",
  "type": "smtp",
  "config": {
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "your-email@gmail.com",
    "smtp_password": "abcd efgh ijkl mnop",
    "from_email": "your-email@gmail.com",
    "to_email": "alerts@example.com",
    "use_tls": true
  },
  "enabled": true
}
```

### Common SMTP Servers

| Provider | SMTP Server | Port | TLS |
|----------|-------------|------|-----|
| **Gmail** | `smtp.gmail.com` | 587 or 465 | ✓ |
| **Outlook/Hotmail** | `smtp-mail.outlook.com` | 587 | ✓ |
| **Yahoo** | `smtp.mail.yahoo.com` | 587 or 465 | ✓ |
| **iCloud** | `smtp.mail.me.com` | 587 | ✓ |
| **Office 365** | `smtp.office365.com` | 587 | ✓ |
| **SendGrid** | `smtp.sendgrid.net` | 587 | ✓ |
| **Mailgun** | `smtp.mailgun.org` | 587 | ✓ |

### Custom SMTP Server

For self-hosted or corporate SMTP servers:

1. Contact your IT department for:
   - SMTP server hostname
   - Port number (usually 25, 587, or 465)
   - Authentication credentials
   - TLS requirements
2. Enter these details in DockMon SMTP configuration
3. Test to verify

### Email Format

DockMon sends **multipart emails** with:
- **Plain text version** - For email clients that don't support HTML
- **HTML version** - Styled with dark theme for readability

### Troubleshooting SMTP

**Authentication Failed:**
- For Gmail: Use App Password, not regular password
- Verify username is the full email address
- Check password is entered correctly (no spaces)

**Connection Errors:**
- Verify SMTP server hostname is correct
- Check port number (587 for STARTTLS, 465 for SSL/TLS, 25 for unencrypted)
- Verify firewall allows outbound SMTP connections
- For self-hosted: Check server is accessible from DockMon container

**TLS Errors:**
- Port 587: Enable "Use TLS/STARTTLS"
- Port 465: Enable "Use TLS/STARTTLS"
- Port 25: Disable "Use TLS/STARTTLS" (unencrypted - not recommended)

**Missing Dependency:**
If you see "SMTP support requires 'aiosmtplib' package":
```bash
# Install in DockMon container
docker exec -it dockmon pip install aiosmtplib
```

Or rebuild DockMon with the dependency included.

---

## Custom Alert Templates

DockMon v2 provides powerful template customization for alert notifications with multiple template levels and extensive variable substitution.

### Template Priority

Templates are selected in the following priority order:

1. **Custom Rule Template** - Template defined on individual alert rules (highest priority)
2. **Category Template** - Alert category-specific templates (metric, state change, health, update)
3. **Global Default Template** - System-wide default template
4. **Built-in Fallback** - Hard-coded templates by alert kind (lowest priority)

### Available Variables

All templates support these variables with automatic substitution:

| Variable | Description | Example |
|----------|-------------|---------|
| **Container/Host Info** | | |
| `{CONTAINER_NAME}` | Container name | `nginx-proxy` |
| `{CONTAINER_ID}` | Short container ID (12 chars) | `a1b2c3d4e5f6` |
| `{HOST_NAME}` | Docker host name | `Production Server` |
| `{HOST_ID}` | Host identifier | `7be442c9-24bc-4047-b33a-41bbf51ea2f9` |
| `{IMAGE}` | Docker image name | `nginx:latest` |
| **Alert Context** | | |
| `{SEVERITY}` | Alert severity level | `CRITICAL`, `WARNING`, `INFO` |
| `{KIND}` | Alert kind/type | `container_stopped`, `cpu_high` |
| `{TITLE}` | Alert title | `Container Stopped - nginx-proxy` |
| `{MESSAGE}` | Alert message | `Container exited unexpectedly` |
| `{STATE}` | Alert state | `firing`, `resolved` |
| `{RULE_NAME}` | Alert rule that triggered | `Critical Containers` |
| `{RULE_ID}` | Alert rule ID | `rule_456` |
| **State Changes** | | |
| `{OLD_STATE}` | Previous container state | `running` |
| `{NEW_STATE}` | Current container state | `exited` |
| `{EXIT_CODE}` | Container exit code (formatted) | `137 (SIGKILL - Force killed / OOM)` |
| `{EVENT_TYPE}` | Docker event type | `container_die` |
| **Timestamps** | | |
| `{TIMESTAMP}` | Full timestamp (local timezone) | `2025-09-29 14:23:45` |
| `{TIME}` | Time only | `14:23:45` |
| `{DATE}` | Date only | `2025-09-29` |
| `{FIRST_SEEN}` | When alert first occurred | `2025-09-29 14:20:00` |
| `{LAST_SEEN}` | Most recent occurrence | `2025-09-29 14:23:45` |
| **Metrics** | | |
| `{CURRENT_VALUE}` | Current metric value | `85.5` (for CPU %), `450MB` (for memory) |
| `{THRESHOLD}` | Configured threshold | `80` (for 80% threshold) |
| **Container Updates** | | |
| `{UPDATE_STATUS}` | Update status | `Available`, `Succeeded`, `Failed` |
| `{CURRENT_IMAGE}` | Current image tag | `nginx:1.24` |
| `{LATEST_IMAGE}` | Latest available image | `nginx:1.25` |
| `{CURRENT_DIGEST}` | Current image digest | `sha256:abc123...` |
| `{LATEST_DIGEST}` | Latest image digest | `sha256:def456...` |
| `{PREVIOUS_IMAGE}` | Previous image (for updates) | `nginx:1.23` |
| `{NEW_IMAGE}` | New image (for updates) | `nginx:1.24` |
| `{ERROR_MESSAGE}` | Error message (conditional) | `Pull failed: timeout` |
| **Health Checks** | | |
| `{HEALTH_CHECK_URL}` | Health check endpoint (conditional) | `http://localhost:8080/health` |
| `{CONSECUTIVE_FAILURES}` | Failure count (conditional) | `3/5 consecutive` |
| `{FAILURE_THRESHOLD}` | Max failures allowed | `5` |
| `{RESPONSE_TIME}` | Response time (conditional) | `1250ms` |
| **Other** | | |
| `{LABELS}` | Container labels | `env=prod, tier=frontend` |
| `{SCOPE_TYPE}` | Alert scope | `Container`, `Host`, `Service` |
| `{TRIGGERED_BY}` | Trigger source | `state_monitor`, `metric_monitor` |

**Note:** Conditional variables like `{ERROR_MESSAGE}`, `{HEALTH_CHECK_URL}`, etc. only appear when relevant data exists. Otherwise, they are removed from the final message.

### Default Templates by Category

DockMon v2 includes specialized templates for different alert types:

**State Change Alerts:**
```markdown
🚨 **{SEVERITY} Alert: {KIND}**

**Container:** {CONTAINER_NAME}
**Host:** {HOST_NAME}
**State change:** {OLD_STATE} to {NEW_STATE}
**Exit code:** {EXIT_CODE}
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}
```

**Metric Alerts (CPU, Memory, Disk):**
```markdown
🚨 **{SEVERITY} Alert: {KIND}**

**Container:** {CONTAINER_NAME}
**Host:** {HOST_NAME}
**Current Value:** {CURRENT_VALUE} (threshold: {THRESHOLD})
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}
```

**Health Check Alerts:**
```markdown
🏥 **{SEVERITY} Alert: Health Check Failed**

**Container:** {CONTAINER_NAME}
**Host:** {HOST_NAME}
**Status:** {OLD_STATE} → {NEW_STATE}
{HEALTH_CHECK_URL}{ERROR_MESSAGE}{CONSECUTIVE_FAILURES}{RESPONSE_TIME}
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}
```

**Update Alerts:**
```markdown
🔄 **Container Update - {UPDATE_STATUS}**

**Container:** `{CONTAINER_NAME}`
**Host:** {HOST_NAME}
**Current:** {CURRENT_IMAGE}
**Latest:** {LATEST_IMAGE}
**Digest:** {LATEST_DIGEST}
**Time:** {TIMESTAMP}
**Update Status:** {UPDATE_STATUS}
**Rule:** {RULE_NAME}
```

### Example Templates

**Simple:**
```
Alert: {CONTAINER_NAME} on {HOST_NAME} changed from {OLD_STATE} to {NEW_STATE}
```

**Detailed:**
```
Container Alert

Container: {CONTAINER_NAME} ({CONTAINER_ID})
Host: {HOST_NAME}
Status: {OLD_STATE} → {NEW_STATE}
Image: {IMAGE}
Time: {TIMESTAMP}
Triggered by: {RULE_NAME}
```

**Minimal:**
```
{CONTAINER_NAME}: {NEW_STATE} at {TIME}
```

### Customizing Templates

**Global Default Template:**
1. Navigate to **Settings** → **Alert & Notifications**
2. Scroll to **Default Alert Template** section
3. Edit the template using variables above
4. Click **"Save"**

**Category-Specific Templates:**
1. Navigate to **Settings** → **Alert & Notifications**
2. Find the category template section (Metric, State Change, Health, Update)
3. Edit the template for that category
4. Click **"Save"**

**Per-Rule Custom Templates:**
1. Navigate to **Settings** → **Alert Rules**
2. Edit an existing rule or create a new one
3. Expand the **Advanced Options** section
4. Enter a custom template in the **Custom Template** field
5. Click **"Save Rule"**

Templates support Markdown formatting for bold (`**text**`), code blocks (`` `text` ``), and line breaks.

---

## Testing Notifications

### Test a Channel

1. Navigate to **Settings** → **Notification Channels**
2. Find the channel you want to test in the list
3. Click the **"Test"** button (icon button to the right of the channel)
4. You should receive a test notification within seconds

### Test Message Content

Test messages include:
- DockMon branding
- "This is a test notification" message
- Current timestamp
- Channel configuration confirmation

### Troubleshooting Tests

**No notification received?**
- Verify webhook URL / credentials are correct
- Check channel is **Enabled**
- For Discord: Verify channel permissions
- For Telegram: Verify bot is in the chat
- For Pushover: Verify app is installed and logged in
- For Gotify: Verify server URL is accessible and token is correct
- For SMTP: Verify credentials and check spam/junk folder

**Error messages:**
- `401 Unauthorized` - Invalid credentials
- `404 Not Found` - Webhook URL is incorrect
- `429 Too Many Requests` - Rate limited, wait and try again
- `Network error` - Check internet connection

---

## Managing Notification Channels

### Edit a Channel

1. Navigate to **Settings** → **Notification Channels**
2. Click the **Edit** icon (pencil) next to the channel
3. Modify any configuration fields
4. Optionally click **"Test"** to verify changes
5. Click **"Save"**

### Enable/Disable a Channel

**Quick Toggle:**
1. Navigate to **Settings** → **Notification Channels**
2. Click the **Power** icon next to the channel
3. Channel is immediately enabled/disabled
4. Disabled channels won't send notifications but remain configured

**Via Edit:**
1. Click the **Edit** icon on the channel
2. Toggle the **"Enabled"** checkbox
3. Click **"Save"**

### Delete a Channel

⚠️ **Warning:** Deleting a channel affects linked alert rules.

1. Navigate to **Settings** → **Notification Channels**
2. Click the **Delete** icon (trash) next to the channel
3. Review the deletion confirmation dialog showing:
   - Which alert rules use this channel
   - Whether any rules will be deleted (if they only use this channel)
4. Confirm deletion

**What happens:**
- Channel is permanently deleted
- Alert rules using ONLY this channel may be affected (warned before deletion)
- Alert rules with multiple channels have this channel removed but remain active
- You can re-create the channel later if needed

---

## Best Practices

### Channel Organization

**Separate channels by priority:**
- `Critical Alerts` - Production containers
- `Warning Alerts` - Non-critical containers
- `Info Alerts` - General notifications

**Separate channels by team:**
- `DevOps Team` - Infrastructure alerts
- `Dev Team` - Application alerts
- `Management` - Summary notifications

### Rate Limiting

To avoid notification spam:
- Use [Alert Rules](Alert-Rules) with **cooldown periods** (e.g., 15 minutes)
- Use [Blackout Windows](Blackout-Windows) for maintenance periods
- Group related containers in the same alert rule

### Alert Fatigue

Prevent alert fatigue by:
- Only alerting on **critical** state changes
- Using **appropriate cooldown** periods
- Testing alert rules before enabling
- Regularly reviewing and tuning alert rules

---

## Next Steps

- [Alert Rules](Alert-Rules) - Create rules to trigger these notifications
- [Blackout Windows](Blackout-Windows) - Schedule quiet hours
- [Configuration](Configuration) - Advanced notification settings