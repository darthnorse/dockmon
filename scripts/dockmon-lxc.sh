#!/bin/bash

# DockMon LXC Container Auto-Creation Script for Proxmox
# Run this script on your Proxmox host to automatically create and configure DockMon
# Usage: bash create-dockmon-lxc.sh

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default Configuration (modify as needed)
CONTAINER_ID=""  # Leave empty for next available ID
CONTAINER_NAME="dockmon"
TEMPLATE="debian-12-standard_12.2-1_amd64.tar.zst"
STORAGE="local-lvm"
DISK_SIZE="4"
MEMORY="512"
SWAP="512"
CORES="1"
BRIDGE="vmbr0"
IP_CONFIG="dhcp"  # Set to "dhcp" or specify like "192.168.1.100/24"
GATEWAY=""  # Set if using static IP, e.g., "192.168.1.1"
DNS=""  # Leave empty for host settings or set like "8.8.8.8"
SSH_KEY=""  # Optional: path to SSH public key file
START_ON_BOOT="1"  # 1 for yes, 0 for no
PROXMOX_NODE=$(hostname)

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
    for ctid in $(pct list | tail -n +2 | awk '{print $1}'); do
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

# Interactive configuration
echo -e "${BLUE}Current Configuration:${NC}"
echo "══════════════════════════════════════"
echo "Node: $PROXMOX_NODE"
echo "Template: $TEMPLATE"
echo "Storage: $STORAGE"
echo "Disk Size: ${DISK_SIZE}GB"
echo "Memory: ${MEMORY}MB"
echo "CPU Cores: $CORES"
echo "Network Bridge: $BRIDGE"
echo "IP Configuration: $IP_CONFIG"
echo ""

read -p "Do you want to use these settings? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    print_info "Enter custom configuration (press Enter to keep defaults):"
    
    read -p "Storage [$STORAGE]: " input
    STORAGE=${input:-$STORAGE}
    
    read -p "Disk Size in GB [$DISK_SIZE]: " input
    DISK_SIZE=${input:-$DISK_SIZE}
    
    read -p "Memory in MB [$MEMORY]: " input
    MEMORY=${input:-$MEMORY}
    
    read -p "CPU Cores [$CORES]: " input
    CORES=${input:-$CORES}
    
    read -p "Network Bridge [$BRIDGE]: " input
    BRIDGE=${input:-$BRIDGE}
    
    read -p "IP Config (dhcp or IP/MASK) [$IP_CONFIG]: " input
    IP_CONFIG=${input:-$IP_CONFIG}
    
    if [[ $IP_CONFIG != "dhcp" ]]; then
        read -p "Gateway IP: " GATEWAY
        read -p "DNS Server [8.8.8.8]: " input
        DNS=${input:-"8.8.8.8"}
    fi
fi

# Get or assign container ID
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

# Check if template exists
print_info "Checking for Debian template..."
TEMPLATE_PATH="/var/lib/vz/template/cache/$TEMPLATE"

if [ ! -f "$TEMPLATE_PATH" ]; then
    print_warning "Template not found. Attempting to download Debian 12..."
    pveam update
    pveam download local debian-12-standard_12.2-1_amd64.tar.zst
    
    if [ ! -f "$TEMPLATE_PATH" ]; then
        print_error "Failed to download template!"
        exit 1
    fi
fi

print_success "Template ready: $TEMPLATE"

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
print_info "Creating LXC container..."

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
    --password

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

# Start the container
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

# Install DockMon inside the container
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

# Summary
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}           DockMon Installation Complete! 🎉             ${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}Container Details:${NC}"
echo "══════════════════════════════════════"
echo "Container ID: $CONTAINER_ID"
echo "Container Name: $CONTAINER_NAME"
echo "IP Address: $CONTAINER_IP"
echo "Memory: ${MEMORY}MB"
echo "Disk Size: ${DISK_SIZE}GB"
echo "CPU Cores: $CORES"
echo ""
echo -e "${BLUE}Access DockMon:${NC}"
echo "══════════════════════════════════════"
echo -e "Web Interface: ${GREEN}http://$CONTAINER_IP${NC}"
echo -e "SSH Access: ${GREEN}ssh root@$CONTAINER_IP${NC}"
echo ""
echo -e "${BLUE}Container Management:${NC}"
echo "══════════════════════════════════════"
echo "Start:    pct start $CONTAINER_ID"
echo "Stop:     pct stop $CONTAINER_ID"
echo "Restart:  pct restart $CONTAINER_ID"
echo "Console:  pct console $CONTAINER_ID"
echo "Remove:   pct destroy $CONTAINER_ID"
echo ""
echo -e "${YELLOW}Note:${NC} Default nginx serves on port 80"
echo -e "${YELLOW}Note:${NC} To update DockMon, run inside container:"
echo "      cd /opt/dockmon && git pull"
echo "      cp src/index.html /var/www/html/index.html"
echo ""
echo -e "${GREEN}Enjoy DockMon!${NC} 🐳"