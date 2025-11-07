# DockMon Wiki Content

This directory contains all the prepared wiki documentation for DockMon.

## 📚 Wiki Pages Created

✅ **Home.md** - Wiki homepage with navigation
✅ **_Sidebar.md** - Navigation sidebar
✅ **Quick-Start.md** - 5-minute quick start guide
✅ **Installation.md** - Platform-specific installation guides
✅ **First-Time-Setup.md** - Initial configuration walkthrough
✅ **Notifications.md** - Notification channel setup (Discord, Slack, Telegram, Pushover)
✅ **Remote-Docker-Setup.md** - Remote Docker monitoring with mTLS
✅ **Security-Guide.md** - Comprehensive security documentation
✅ **Troubleshooting.md** - Common issues and solutions
✅ **FAQ.md** - Frequently asked questions

## 🚀 How to Upload to GitHub Wiki

### Step 1: Initialize the Wiki (First Time Only)

1. Go to: https://github.com/darthnorse/dockmon/wiki
2. Click **"Create the first page"** button
3. **Title:** `Home`
4. **Content:** Type anything (e.g., "Initial page")
5. Click **"Save Page"**

This creates the wiki repository on GitHub.

### Step 2: Run the Upload Script

```bash
cd wiki-content
./upload-wiki.sh
```

The script will:
- Clone the wiki repository
- Copy all markdown files
- Commit and push to GitHub
- Clean up temporary files

### Step 3: Verify

Visit https://github.com/darthnorse/dockmon/wiki to see your beautiful new documentation!

## 📝 Manual Upload (Alternative)

If the script doesn't work, you can upload manually:

```bash
# Clone the wiki repository
git clone https://github.com/darthnorse/dockmon.wiki.git
cd dockmon.wiki

# Copy all content
cp /path/to/wiki-content/*.md .

# Commit and push
git add .
git commit -m "Update wiki documentation"
git push origin master
```

## ✏️ Editing the Wiki

### Via GitHub Web Interface
1. Go to https://github.com/darthnorse/dockmon/wiki
2. Click any page
3. Click "Edit" button
4. Make changes
5. Save

### Via Git (Recommended for Bulk Changes)
```bash
# Clone
git clone https://github.com/darthnorse/dockmon.wiki.git
cd dockmon.wiki

# Make changes
vim Home.md

# Commit and push
git add .
git commit -m "Update documentation"
git push origin master
```

## 📋 Wiki Structure

```
Home.md                    # Wiki homepage
_Sidebar.md               # Navigation (auto-appears on all pages)

Getting Started:
├── Quick-Start.md
├── Installation.md
└── First-Time-Setup.md

Configuration:
├── Notifications.md
└── (more to be added)

Advanced:
├── Remote-Docker-Setup.md
├── Security-Guide.md
└── (more to be added)

Help:
├── Troubleshooting.md
└── FAQ.md
```

## 🔮 Future Wiki Pages to Create

These pages are referenced but not yet created:

**User Guide:**
- Dashboard.md - Dashboard overview
- Managing-Hosts.md - Host management guide
- Container-Operations.md - Container management
- Auto-Restart.md - Auto-restart configuration
- Alert-Rules.md - Alert rule configuration
- Blackout-Windows.md - Quiet hours setup
- Settings.md - Global settings

**Advanced:**
- mTLS-Configuration.md - Manual mTLS setup
- Platform-Guides.md - Platform-specific guides
- API-Reference.md - REST and WebSocket API
- WebSocket-API.md - WebSocket protocol

**Development:**
- Development-Setup.md - Local development
- Architecture.md - System architecture
- Contributing.md - Contribution guidelines
- Testing.md - Running tests

**Other:**
- Configuration.md - General configuration reference

## 📄 License

All documentation is part of DockMon and licensed under MIT License.