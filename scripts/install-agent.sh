#!/bin/bash
#
# DockMon Agent Install Script
# https://github.com/darthnorse/dockmon
#
# Usage (run as root):
#   curl -fsSL https://raw.githubusercontent.com/darthnorse/dockmon/main/scripts/install-agent.sh | \
#     DOCKMON_URL=https://your-server REGISTRATION_TOKEN=your-token bash
#
# Optional environment variables:
#   DOCKMON_URL          - Required. URL of your DockMon server
#   REGISTRATION_TOKEN   - Required. One-time registration token from DockMon
#   TZ                   - Optional. Timezone (default: UTC)
#   INSECURE_SKIP_VERIFY - Optional. Skip TLS verification (default: false)
#   DATA_PATH            - Optional. Data directory (default: /var/lib/dockmon-agent)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check required variables
if [ -z "$DOCKMON_URL" ]; then
    log_error "DOCKMON_URL is required"
    echo "Usage: curl -fsSL .../install-agent.sh | sudo DOCKMON_URL=https://... REGISTRATION_TOKEN=... bash"
    exit 1
fi

if [ -z "$REGISTRATION_TOKEN" ]; then
    log_error "REGISTRATION_TOKEN is required"
    echo "Usage: curl -fsSL .../install-agent.sh | sudo DOCKMON_URL=https://... REGISTRATION_TOKEN=... bash"
    exit 1
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    log_error "This script must be run as root (use sudo)"
    exit 1
fi

# Set defaults
DATA_PATH="${DATA_PATH:-/var/lib/dockmon-agent}"
TZ="${TZ:-UTC}"
INSTALL_PATH="/usr/local/bin/dockmon-agent"
SERVICE_FILE="/etc/systemd/system/dockmon-agent.service"

# Detect architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        ARCH="amd64"
        ;;
    aarch64|arm64)
        ARCH="arm64"
        ;;
    *)
        log_error "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

log_info "Detected architecture: $ARCH"

# Check for existing installation
if systemctl is-active --quiet dockmon-agent 2>/dev/null; then
    log_warn "DockMon agent is already running. Stopping it..."
    systemctl stop dockmon-agent
fi

# Download binary
log_info "Downloading DockMon agent..."
DOWNLOAD_URL="https://github.com/darthnorse/dockmon/releases/latest/download/dockmon-agent-linux-${ARCH}"

if ! curl -fsSL -o "$INSTALL_PATH" "$DOWNLOAD_URL"; then
    log_warn "Release download failed, trying to extract from Docker image..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed and release binary not available"
        exit 1
    fi

    docker pull ghcr.io/darthnorse/dockmon-agent:latest
    docker create --name temp-dockmon-agent ghcr.io/darthnorse/dockmon-agent:latest
    docker cp temp-dockmon-agent:/app/dockmon-agent "$INSTALL_PATH"
    docker rm temp-dockmon-agent
fi

chmod +x "$INSTALL_PATH"
log_info "Installed binary to $INSTALL_PATH"

# Verify binary
if ! "$INSTALL_PATH" --version &>/dev/null 2>&1; then
    # Some binaries don't have --version, just check it's executable
    if ! file "$INSTALL_PATH" | grep -q "executable"; then
        log_error "Downloaded file is not a valid executable"
        exit 1
    fi
fi

# Create data directory
log_info "Creating data directory: $DATA_PATH"
mkdir -p "$DATA_PATH"

# Build environment lines for systemd
ENV_LINES="Environment=\"DOCKMON_URL=${DOCKMON_URL}\"
Environment=\"REGISTRATION_TOKEN=${REGISTRATION_TOKEN}\"
Environment=\"DATA_PATH=${DATA_PATH}\"
Environment=\"TZ=${TZ}\""

if [ -n "$INSECURE_SKIP_VERIFY" ] && [ "$INSECURE_SKIP_VERIFY" = "true" ]; then
    ENV_LINES="${ENV_LINES}
Environment=\"INSECURE_SKIP_VERIFY=true\""
fi

# Create systemd service file
log_info "Creating systemd service..."
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=DockMon Agent
Documentation=https://github.com/darthnorse/dockmon
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
${ENV_LINES}
ExecStart=${INSTALL_PATH}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and start service
log_info "Starting DockMon agent..."
systemctl daemon-reload
systemctl enable dockmon-agent
systemctl start dockmon-agent

# Wait a moment and check status
sleep 2

if systemctl is-active --quiet dockmon-agent; then
    log_info "DockMon agent installed and running successfully!"
    echo ""
    echo "Useful commands:"
    echo "  sudo systemctl status dockmon-agent   # Check status"
    echo "  sudo journalctl -u dockmon-agent -f   # View logs"
    echo "  sudo systemctl restart dockmon-agent  # Restart"
    echo ""
else
    log_error "Agent failed to start. Check logs with: journalctl -u dockmon-agent -e"
    exit 1
fi
