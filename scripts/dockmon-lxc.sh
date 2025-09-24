#!/bin/bash

# DockMon LXC Container Auto-Creation Script for Proxmox
# Run this script on your Proxmox host to automatically create and configure DockMon
# Usage: bash dockmon-lxc.sh

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default Configuration (modify as needed)
CONTAINER_ID=""  # Leave empty for next available ID
CONTAINER_NAME="dockmon"
DEBIAN_VERSION=""  # Will be selected by user
TEMPLATE=""  # Will be set based on Debian version
STORAGE="local-lvm"
DISK_SIZE="4"
MEMORY="512"
SWAP="512"
CORES="1"
BRIDGE="vmbr0"
IP_CONFIG="dhcp"  # Set to "dhcp" or specify like "192.168.1.100/24"
GATEWAY=""  # Set if using static IP, e.g., "192.168.1.1"
DNS=""  # Leave empty for host settings or set like "8.8.8.8"
ROOT_PASSWORD=""  # Will be set by user
SSH_KEY=""  # Optional: path to SSH public key file
START_ON_BOOT="1"  # 1 for yes, 0 for no
PROXMOX_NODE=$(hostname)

# Template options
DEBIAN_12_TEMPLATE="debian-12-standard_12.2-1_amd64.tar.zst"
DEBIAN_13_TEMPLATE="debian-13-standard_13.0-1_amd64.tar.zst"

# GitHub repository
GITHUB_REPO="https://github.com/darthnorse/dockmon.git"

# Function to print colored output
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

print_cyan() {
    echo -e "${CYAN}$1${NC}"
}

# Header
clear
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}     DockMon LXC Container Auto-Creation for Proxmox     ${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""

# Check if running on Proxmox
if [ ! -f /etc/pve/version ]; then
    print_error "This script must be run on a Proxmox VE host!"
    exit 1
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_error "This script must be run as root!"
    exit 1
fi

# Function to get next available container ID
get_next_ctid() {
    local max_id=100
    for ctid in $(pct list 2>/dev/null | tail -n +2 | awk '{print $1}'); do
        if [ "$ctid" -ge "$max_id" ]; then
            max_id=$((ctid + 1))
        fi
    done
    echo $max_id
}

# Function to check if container ID exists
check_ctid_exists() {
    pct status $1 &>/dev/null
    return $?
}

# Function to validate IP address format
validate_ip() {
    if [[ $1 =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        return 0
    fi
    return 1
}

# Function to validate IP with CIDR
validate_ip_cidr() {
    if [[ $1 =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$ ]]; then
        return 0
    fi
    return 1
}

# Select Debian version
echo -e "${CYAN}Step 1: Select Debian Version${NC}"
echo "══════════════════════════════════════"
echo "1) Debian 12 (Bookworm) - Stable, Recommended"
echo "2) Debian 13 (Trixie) - Testing"
echo ""

while true; do
    read -p "Select Debian version (1 or 2): " debian_choice
    case $debian_choice in
        1)
            DEBIAN_VERSION="12"
            TEMPLATE=$DEBIAN_12_TEMPLATE
            print_success "Selected Debian 12 (Bookworm)"
            break
            ;;
        2)
            DEBIAN_VERSION="13"
            TEMPLATE=$DEBIAN_13_TEMPLATE
            print_success "Selected Debian 13 (Trixie)"
            break
            ;;
        *)
            print_error "Invalid selection. Please enter 1 or 2"
            ;;
    esac
done
echo ""

# Set root password
echo -e "${CYAN}Step 2: Set Root Password${NC}"
echo "══════════════════════════════════════"
echo "Enter the root password for the container"
echo "(Password will not be visible while typing)"
echo ""

while true; do
    read -s -p "Enter root password: " ROOT_PASSWORD
    echo
    read -s -p "Confirm root password: " ROOT_PASSWORD_CONFIRM
    echo
    
    if [ "$ROOT_PASSWORD" != "$ROOT_PASSWORD_CONFIRM" ]; then
        print_error "Passwords do not match! Please try again."
        echo ""
    elif [ -z "$ROOT_PASSWORD" ]; then
        print_error "Password cannot be empty! Please try again."
        echo ""
    else
        print_success "Root password set successfully"
        break
    fi
done
echo ""

# Select storage
echo -e "${CYAN}Step 3: Select Storage${NC}"
echo "══════════════════════════════════════"
print_info "Available storage pools:"
echo ""
pvesm status | grep -E "^[[:alnum:]]" | awk '{printf "  %-20s %s\n", $1, "(" $2 ")"}'
echo ""

while true; do
    read -p "Select storage pool [$STORAGE]: " input
    STORAGE=${input:-$STORAGE}
    
    # Verify storage exists
    if pvesm status | grep -q "^$STORAGE "; then
        print_success "Selected storage: $STORAGE"
        break
    else
        print_error "Storage pool '$STORAGE' not found. Please select from the list above."
    fi
done
echo ""

# Configuration options
echo -e "${CYAN}Step 4: Container Configuration${NC}"
echo "══════════════════════════════════════"
echo -e "${BLUE}Default Configuration:${NC}"
echo "  Node: $PROXMOX_NODE"
echo "  Storage: $STORAGE (selected)"
echo "  Disk Size: ${DISK_SIZE}GB"
echo "  Memory: ${MEMORY}MB"
echo "  CPU Cores: $CORES"
echo "  Network Bridge: $BRIDGE"
echo "  IP Configuration: $IP_CONFIG"
echo "  Start on Boot: $([ $START_ON_BOOT -eq 1 ] && echo 'Yes' || echo 'No')"
echo ""

read -p "Do you want to customize these settings? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    print_info "Enter custom configuration (press Enter to keep defaults):"
    echo ""
    
    # Disk size
    read -p "Disk Size in GB [$DISK_SIZE]: " input
    DISK_SIZE=${input:-$DISK_SIZE}
    
    # Memory
    read -p "Memory in MB [$MEMORY]: " input
    MEMORY=${input:-$MEMORY}
    
    # CPU cores
    read -p "CPU Cores [$CORES]: " input
    CORES=${input:-$CORES}
    
    # Network bridge
    print_cyan "Available bridges:"
    ip link show type bridge | grep -E "^[0-9]+" | awk -F': ' '{print "  - " $2}'
    read -p "Network Bridge [$BRIDGE]: " input
    BRIDGE=${input:-$BRIDGE}
    
    # IP configuration
    echo ""
    print_cyan "IP Configuration:"
    echo "  1) DHCP (automatic)"
    echo "  2) Static IP"
    read -p "Select IP configuration (1 or 2) [1]: " ip_choice
    
    if [ "$ip_choice" == "2" ]; then
        while true; do
            read -p "Enter IP address with CIDR (e.g., 192.168.1.100/24): " IP_CONFIG
            if validate_ip_cidr "$IP_CONFIG"; then
                break
            else
                print_error "Invalid IP format. Please use format: 192.168.1.100/24"
            fi
        done
        
        while true; do
            read -p "Enter Gateway IP: " GATEWAY
            if validate_ip "$GATEWAY"; then
                break
            else
                print_error "Invalid gateway IP format"
            fi
        done
        
        read -p "DNS Server [8.8.8.8]: " input
        DNS=${input:-"8.8.8.8"}
    else
        IP_CONFIG="dhcp"
    fi
    
    # Start on boot
    read -p "Start container on boot? (y/n) [y]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        START_ON_BOOT="0"
    fi
fi
echo ""

# SSH key option
read -p "Do you want to add an SSH public key for root access? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Enter path to SSH public key file: " SSH_KEY
    if [ ! -f "$SSH_KEY" ]; then
        print_warning "SSH key file not found, skipping SSH key configuration"
        SSH_KEY=""
    fi
fi
echo ""

# Get or assign container ID
echo -e "${CYAN}Step 5: Container ID Assignment${NC}"
echo "══════════════════════════════════════"

if [ -z "$CONTAINER_ID" ]; then
    CONTAINER_ID=$(get_next_ctid)
    print_info "Using next available Container ID: $CONTAINER_ID"
else
    if check_ctid_exists $CONTAINER_ID; then
        print_error "Container ID $CONTAINER_ID already exists!"
        read -p "Use next available ID? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            CONTAINER_ID=$(get_next_ctid)
            print_info "Using Container ID: $CONTAINER_ID"
        else
            exit 1
        fi
    fi
fi
echo ""

# Check if template exists
echo -e "${CYAN}Step 6: Template Preparation${NC}"
echo "══════════════════════════════════════"
print_info "Checking for Debian $DEBIAN_VERSION template..."
TEMPLATE_PATH="/var/lib/vz/template/cache/$TEMPLATE"

if [ ! -f "$TEMPLATE_PATH" ]; then
    print_warning "Template not found. Attempting to download Debian $DEBIAN_VERSION..."
    pveam update
    
    # Try to download the template
    if ! pveam download local $TEMPLATE 2>/dev/null; then
        print_warning "Standard template not available, searching for alternatives..."
        
        # Find available Debian templates
        available_templates=$(pveam available | grep "debian-$DEBIAN_VERSION" | awk '{print $2}')
        
        if [ -n "$available_templates" ]; then
            echo "Available Debian $DEBIAN_VERSION templates:"
            echo "$available_templates" | nl
            read -p "Select template number: " template_num
            TEMPLATE=$(echo "$available_templates" | sed -n "${template_num}p")
            TEMPLATE_PATH="/var/lib/vz/template/cache/$TEMPLATE"
            pveam download local $TEMPLATE
        else
            print_error "No Debian $DEBIAN_VERSION templates available!"
            exit 1
        fi
    fi
    
    if [ ! -f "$TEMPLATE_PATH" ]; then
        print_error "Failed to download template!"
        exit 1
    fi
fi

print_success "Template ready: $TEMPLATE"
echo ""

# Build network configuration
if [ "$IP_CONFIG" == "dhcp" ]; then
    NET_CONFIG="name=eth0,bridge=$BRIDGE,ip=dhcp"
else
    NET_CONFIG="name=eth0,bridge=$BRIDGE,ip=$IP_CONFIG"
    if [ -n "$GATEWAY" ]; then
        NET_CONFIG="$NET_CONFIG,gw=$GATEWAY"
    fi
fi

# Create the container
echo -e "${CYAN}Step 7: Creating LXC Container${NC}"
echo "══════════════════════════════════════"
print_info "Creating container with ID $CONTAINER_ID..."

# Create temporary file for password
PASS_FILE=$(mktemp)
echo -e "$ROOT_PASSWORD\n$ROOT_PASSWORD" > "$PASS_FILE"

# Create container with password from file
pct create $CONTAINER_ID "$TEMPLATE_PATH" \
    --hostname $CONTAINER_NAME \
    --storage $STORAGE \
    --rootfs $STORAGE:$DISK_SIZE \
    --memory $MEMORY \
    --swap $SWAP \
    --cores $CORES \
    --net0 $NET_CONFIG \
    --features nesting=1 \
    --unprivileged 1 \
    --onboot $START_ON_BOOT \
    --password < "$PASS_FILE"

# Remove temporary password file
rm -f "$PASS_FILE"

if [ $? -ne 0 ]; then
    print_error "Failed to create container!"
    exit 1
fi

print_success "Container $CONTAINER_ID created successfully!"

# Set DNS if specified
if [ -n "$DNS" ]; then
    pct set $CONTAINER_ID --nameserver "$DNS"
fi

# Add SSH key if provided
if [ -n "$SSH_KEY" ] && [ -f "$SSH_KEY" ]; then
    print_info "Adding SSH key..."
    pct set $CONTAINER_ID --ssh-public-keys "$SSH_KEY"
fi
echo ""

# Start the container
echo -e "${CYAN}Step 8: Starting Container${NC}"
echo "══════════════════════════════════════"
print_info "Starting container..."
pct start $CONTAINER_ID

# Wait for container to be ready
print_info "Waiting for container to be ready..."
sleep 10

# Get container IP
print_info "Getting container IP address..."
for i in {1..30}; do
    CONTAINER_IP=$(pct exec $CONTAINER_ID -- ip -4 addr show eth0 2>/dev/null | grep inet | awk '{print $2}' | cut -d/ -f1)
    if [ -n "$CONTAINER_IP" ]; then
        break
    fi
    sleep 2
done

if [ -z "$CONTAINER_IP" ]; then
    print_warning "Could not determine container IP address"
    CONTAINER_IP="<container-ip>"
fi
echo ""

# Install DockMon inside the container
echo -e "${CYAN}Step 9: Installing DockMon${NC}"
echo "══════════════════════════════════════"
print_info "Installing DockMon in the container..."

# Create installation script
cat << 'INSTALL_SCRIPT' > /tmp/install-dockmon.sh
#!/bin/bash
set -e

# Update system
echo "Updating system packages..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

# Install required packages
echo "Installing nginx and git..."
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx git curl

# Clone DockMon repository
echo "Cloning DockMon repository..."
cd /opt
git clone https://github.com/darthnorse/dockmon.git

# Copy application to web root
echo "Setting up DockMon..."
cp /opt/dockmon/src/index.html /var/www/html/index.html

# Configure nginx to start on boot
systemctl enable nginx
systemctl restart nginx

# Create a simple systemd service for DockMon
cat << 'SERVICE' > /etc/systemd/system/dockmon.service
[Unit]
Description=DockMon Web Interface
After=network.target nginx.service
Requires=nginx.service

[Service]
Type=oneshot
ExecStart=/bin/true
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable dockmon.service

# Create update script
echo "Creating update script..."
cat << 'UPDATE_SCRIPT' > /usr/local/bin/update
#!/bin/bash

# DockMon Update Script
# Updates both the system and DockMon to latest versions

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions for colored output
print_info() {
    echo -e "\${BLUE}[INFO]\${NC} \$1"
}

print_success() {
    echo -e "\${GREEN}[SUCCESS]\${NC} \$1"
}

print_error() {
    echo -e "\${RED}[ERROR]\${NC} \$1"
}

print_warning() {
    echo -e "\${YELLOW}[WARNING]\${NC} \$1"
}

# Header
echo -e "\${GREEN}════════════════════════════════════════\${NC}"
echo -e "\${GREEN}       DockMon System Update Tool       \${NC}"
echo -e "\${GREEN}════════════════════════════════════════\${NC}"
echo ""

# Check if running as root
if [ "\$EUID" -ne 0 ]; then 
    print_error "This script must be run as root!"
    print_info "Try: sudo update"
    exit 1
fi

# Step 1: Update Debian packages
echo -e "\${BLUE}Step 1: Updating Debian System\${NC}"
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
echo -e "\${BLUE}Step 2: Updating DockMon\${NC}"
echo "════════════════════════════════════"

# Check if DockMon directory exists
if [ ! -d "/opt/dockmon" ]; then
    print_error "DockMon directory not found at /opt/dockmon"
    print_info "Attempting to clone repository..."
    cd /opt
    git clone https://github.com/darthnorse/dockmon.git
    if [ \$? -ne 0 ]; then
        print_error "Failed to clone DockMon repository"
        exit 1
    fi
fi

# Navigate to DockMon directory
cd /opt/dockmon

# Store current version (if exists)
if [ -f "src/index.html" ]; then
    OLD_VERSION=\$(grep -oP 'DockMon v\K[0-9.]+' src/index.html | head -1 || echo "unknown")
else
    OLD_VERSION="not installed"
fi

print_info "Current version: \$OLD_VERSION"

# Fetch latest changes
print_info "Fetching latest updates from GitHub..."
git fetch origin

# Check if there are updates
LOCAL=\$(git rev-parse HEAD)
REMOTE=\$(git rev-parse origin/main)

if [ "\$LOCAL" = "\$REMOTE" ]; then
    print_info "DockMon is already up to date"
else
    print_info "Updates available, pulling latest version..."
    
    # Pull latest changes
    git pull origin main
    
    if [ \$? -ne 0 ]; then
        print_warning "Git pull failed, attempting to reset..."
        git reset --hard origin/main
    fi
    
    # Get new version
    NEW_VERSION=\$(grep -oP 'DockMon v\K[0-9.]+' src/index.html | head -1 || echo "unknown")
    print_success "Updated DockMon from v\$OLD_VERSION to v\$NEW_VERSION"
fi

# Update the web application
print_info "Deploying updated application..."
cp -f /opt/dockmon/src/index.html /var/www/html/index.html

if [ \$? -eq 0 ]; then
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
echo -e "\${BLUE}Step 3: Checking for Script Updates\${NC}"
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
echo -e "\${GREEN}════════════════════════════════════════\${NC}"
echo -e "\${GREEN}        Update Complete! ✅              \${NC}"
echo -e "\${GREEN}════════════════════════════════════════\${NC}"
echo ""
echo -e "\${BLUE}Summary:\${NC}"
echo "• System packages: Updated"
echo "• DockMon application: \$([ "\$LOCAL" = "\$REMOTE" ] && echo "Already current" || echo "Updated")"
echo "• Web server: Running"
echo ""
echo -e "\${BLUE}DockMon Access:\${NC}"
echo "• Web Interface: http://\$(hostname -I | awk '{print \$1}')"
echo ""

# Check if reboot is required
if [ -f /var/run/reboot-required ]; then
    echo -e "\${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\${NC}"
    echo -e "\${YELLOW}⚠️  REBOOT REQUIRED\${NC}"
    echo -e "\${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\${NC}"
    echo "A system reboot is required to complete updates."
    echo "Please run: reboot"
    echo ""
fi

exit 0
UPDATE_SCRIPT

# Make update script executable and accessible
chmod +x /usr/local/bin/update

# Create shorter alias
ln -sf /usr/local/bin/update /usr/local/bin/dockmon-update

# Also create the update script in the repository for future updates
mkdir -p /opt/dockmon/scripts
cp /usr/local/bin/update /opt/dockmon/scripts/update.sh
chmod +x /opt/dockmon/scripts/update.sh

echo "DockMon installation completed!"
INSTALL_SCRIPT

# Copy and execute installation script in container
pct push $CONTAINER_ID /tmp/install-dockmon.sh /tmp/install-dockmon.sh
pct exec $CONTAINER_ID -- chmod +x /tmp/install-dockmon.sh
pct exec $CONTAINER_ID -- /tmp/install-dockmon.sh

# Clean up
rm /tmp/install-dockmon.sh

# Final status check
print_info "Verifying installation..."
if pct exec $CONTAINER_ID -- systemctl is-active nginx >/dev/null 2>&1; then
    print_success "Nginx is running"
else
    print_warning "Nginx might not be running properly"
fi
echo ""

# Summary
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}           DockMon Installation Complete! 🎉             ${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}Container Details:${NC}"
echo "══════════════════════════════════════"
echo "Container ID:     $CONTAINER_ID"
echo "Container Name:   $CONTAINER_NAME"
echo "Debian Version:   $DEBIAN_VERSION"
echo "IP Address:       $CONTAINER_IP"
echo "Memory:           ${MEMORY}MB"
echo "Disk Size:        ${DISK_SIZE}GB"
echo "CPU Cores:        $CORES"
echo "Start on Boot:    $([ $START_ON_BOOT -eq 1 ] && echo 'Yes' || echo 'No')"
echo ""
echo -e "${BLUE}Access DockMon:${NC}"
echo "══════════════════════════════════════"
echo -e "Web Interface:    ${GREEN}http://$CONTAINER_IP${NC}"
echo -e "SSH Access:       ${GREEN}ssh root@$CONTAINER_IP${NC}"
echo ""
echo -e "${BLUE}Container Management:${NC}"
echo "══════════════════════════════════════"
echo "Start:     pct start $CONTAINER_ID"
echo "Stop:      pct stop $CONTAINER_ID"
echo "Restart:   pct restart $CONTAINER_ID"
echo "Console:   pct console $CONTAINER_ID"
echo "Remove:    pct destroy $CONTAINER_ID"
echo ""
echo -e "${YELLOW}Notes:${NC}"
echo "• Default nginx serves on port 80"
echo "• Root password: (the password you set)"
echo "• To update DockMon, run inside container:"
echo "    cd /opt/dockmon && git pull"
echo "    cp src/index.html /var/www/html/index.html"
echo ""
echo -e "${GREEN}Enjoy DockMon!${NC} 🐳"