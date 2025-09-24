#!/bin/bash

# DockMon Update Script
# Updates both the system and DockMon to latest versions
# Place this in scripts/update.sh in your repository

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions for colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Header
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}       DockMon System Update Tool       ${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_error "This script must be run as root!"
    print_info "Try: sudo update"
    exit 1
fi

# Step 1: Update Debian packages
echo -e "${BLUE}Step 1: Updating Debian System${NC}"
echo "════════════════════════════════════"
print_info "Updating package lists..."
apt-get update

print_info "Upgrading installed packages..."
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

print_info "Performing distribution upgrade..."
DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y

print_info "Removing unnecessary packages..."
apt-get autoremove -y

print_info "Cleaning package cache..."
apt-get autoclean

print_success "System update completed!"
echo ""

# Step 2: Update DockMon
echo -e "${BLUE}Step 2: Updating DockMon${NC}"
echo "════════════════════════════════════"

# Check if DockMon directory exists
if [ ! -d "/opt/dockmon" ]; then
    print_error "DockMon directory not found at /opt/dockmon"
    print_info "Attempting to clone repository..."
    cd /opt
    git clone https://github.com/darthnorse/dockmon.git
    if [ $? -ne 0 ]; then
        print_error "Failed to clone DockMon repository"
        exit 1
    fi
fi

# Navigate to DockMon directory
cd /opt/dockmon

# Store current version (if exists)
if [ -f "src/index.html" ]; then
    OLD_VERSION=$(grep -oP 'DockMon v\K[0-9.]+' src/index.html | head -1 || echo "unknown")
else
    OLD_VERSION="not installed"
fi

print_info "Current version: $OLD_VERSION"

# Fetch latest changes
print_info "Fetching latest updates from GitHub..."
git fetch origin

# Check if there are updates
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    print_info "DockMon is already up to date"
else
    print_info "Updates available, pulling latest version..."
    
    # Pull latest changes
    git pull origin main
    
    if [ $? -ne 0 ]; then
        print_warning "Git pull failed, attempting to reset..."
        git reset --hard origin/main
    fi
    
    # Get new version
    NEW_VERSION=$(grep -oP 'DockMon v\K[0-9.]+' src/index.html | head -1 || echo "unknown")
    print_success "Updated DockMon from v$OLD_VERSION to v$NEW_VERSION"
fi

# Update the web application
print_info "Deploying updated application..."
cp -f /opt/dockmon/src/index.html /var/www/html/index.html

if [ $? -eq 0 ]; then
    print_success "Application deployed successfully!"
else
    print_error "Failed to deploy application"
    exit 1
fi

# Restart nginx to ensure everything is fresh
print_info "Restarting web server..."
systemctl restart nginx

if systemctl is-active --quiet nginx; then
    print_success "Web server restarted successfully!"
else
    print_error "Web server failed to restart"
    exit 1
fi

echo ""

# Step 3: Check for script updates
echo -e "${BLUE}Step 3: Checking for Script Updates${NC}"
echo "════════════════════════════════════"

# Check if this update script itself needs updating
if [ -f "/opt/dockmon/scripts/update.sh" ]; then
    if ! cmp -s "/opt/dockmon/scripts/update.sh" "/usr/local/bin/update"; then
        print_info "Update script has a newer version, updating..."
        cp -f /opt/dockmon/scripts/update.sh /usr/local/bin/update
        chmod +x /usr/local/bin/update
        print_success "Update script updated! Please run 'update' again if needed."
    else
        print_info "Update script is current"
    fi
fi

echo ""

# Summary
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}        Update Complete! ✅              ${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}Summary:${NC}"
echo "• System packages: Updated"
echo "• DockMon application: $([ "$LOCAL" = "$REMOTE" ] && echo "Already current" || echo "Updated")"
echo "• Web server: Running"
echo ""
echo -e "${BLUE}DockMon Access:${NC}"
echo "• Web Interface: http://$(hostname -I | awk '{print $1}')"
echo ""

# Check if reboot is required
if [ -f /var/run/reboot-required ]; then
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}⚠️  REBOOT REQUIRED${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "A system reboot is required to complete updates."
    echo "Please run: reboot"
    echo ""
fi

exit 0