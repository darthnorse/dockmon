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
#   AGENT_VERSION        - Optional. Agent version to install (default: latest agent-v* release)
#   TZ                   - Optional. Timezone (default: UTC)
#   INSECURE_SKIP_VERIFY - Optional. Skip TLS verification (default: false)
#   AGENT_NAME           - Optional. Display name shown in DockMon panel (defaults to OS hostname)
#   FORCE_UNIQUE_REGISTRATION - Optional. Set to "true" for cloned VMs (shared engine_id) to register as a distinct host. Requires AGENT_NAME.
#   DATA_PATH            - Optional. Data directory (default: /var/lib/dockmon-agent)
#   AGENT_STACKS_DIR     - Optional. Stack storage directory (default: $DATA_PATH/stacks)
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

# Determine agent version to install
if [ -z "$AGENT_VERSION" ]; then
    log_info "Finding latest agent release..."
    # Query GitHub API for latest agent-v* release
    LATEST_TAG=$(curl -fsSL "https://api.github.com/repos/darthnorse/dockmon/releases" | \
        grep -o '"tag_name": "agent-v[^"]*"' | head -1 | cut -d'"' -f4)

    if [ -n "$LATEST_TAG" ]; then
        AGENT_VERSION="${LATEST_TAG#agent-v}"
        log_info "Latest agent version: $AGENT_VERSION"
    else
        log_warn "No agent release found, will try Docker image fallback"
        AGENT_VERSION="latest"
    fi
else
    log_info "Using specified agent version: $AGENT_VERSION"
fi

# Select a SHA-256 tool for verifying the downloaded release binary
if command -v sha256sum >/dev/null 2>&1; then
    SHA256_CMD="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
    SHA256_CMD="shasum -a 256"
else
    SHA256_CMD=""
fi

# Download binary
log_info "Downloading DockMon agent v${AGENT_VERSION}..."
BINARY_NAME="dockmon-agent-linux-${ARCH}"
DOWNLOAD_URL="https://github.com/darthnorse/dockmon/releases/download/agent-v${AGENT_VERSION}/${BINARY_NAME}"
CHECKSUM_URL="https://github.com/darthnorse/dockmon/releases/download/agent-v${AGENT_VERSION}/checksums.txt"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if curl -fsSL -o "${TMP_DIR}/${BINARY_NAME}" "$DOWNLOAD_URL"; then
    # Verify the release binary against the release checksums before trusting it
    if curl -fsSL -o "${TMP_DIR}/checksums.txt" "$CHECKSUM_URL"; then
        EXPECTED_SHA="$(grep " ${BINARY_NAME}\$" "${TMP_DIR}/checksums.txt" | awk '{print $1}' | head -1)"
        if [ -z "$EXPECTED_SHA" ]; then
            log_error "checksums.txt has no entry for ${BINARY_NAME} - refusing to install an unverified binary"
            exit 1
        fi
        if [ -z "$SHA256_CMD" ]; then
            log_error "Neither sha256sum nor shasum is available to verify the download - aborting"
            exit 1
        fi
        ACTUAL_SHA="$($SHA256_CMD "${TMP_DIR}/${BINARY_NAME}" | awk '{print $1}')"
        if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
            log_error "SHA256 verification FAILED for ${BINARY_NAME}"
            log_error "  expected: ${EXPECTED_SHA}"
            log_error "  actual:   ${ACTUAL_SHA}"
            log_error "Aborting - the download may be corrupt or tampered with."
            exit 1
        fi
        log_info "SHA256 verification passed"
    else
        log_warn "Could not fetch checksums.txt for agent-v${AGENT_VERSION}."
        log_warn "Installing the binary WITHOUT integrity verification - only continue if you trust this network and source."
    fi
    mv "${TMP_DIR}/${BINARY_NAME}" "$INSTALL_PATH"
else
    log_warn "Release download failed, trying to extract from Docker image..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed and release binary not available"
        exit 1
    fi

    DOCKER_TAG="${AGENT_VERSION}"
    log_warn "Docker image fallback: ghcr.io/darthnorse/dockmon-agent:${DOCKER_TAG} is NOT checksum-verified by this installer."
    if [ "$DOCKER_TAG" = "latest" ]; then
        log_warn "Using the mutable ':latest' tag - pin AGENT_VERSION to a specific release for a reproducible, auditable install."
    fi

    log_info "Pulling Docker image ghcr.io/darthnorse/dockmon-agent:${DOCKER_TAG}..."
    docker pull "ghcr.io/darthnorse/dockmon-agent:${DOCKER_TAG}"
    docker create --name temp-dockmon-agent "ghcr.io/darthnorse/dockmon-agent:${DOCKER_TAG}"
    docker cp temp-dockmon-agent:/app/dockmon-agent "$INSTALL_PATH"
    docker rm temp-dockmon-agent
fi

chmod +x "$INSTALL_PATH"
log_info "Installed binary to $INSTALL_PATH"

# Verify binary is executable (don't run it - agent requires config)
if ! file "$INSTALL_PATH" | grep -q "executable"; then
    log_error "Downloaded file is not a valid executable"
    exit 1
fi

# Create data directory
log_info "Creating data directory: $DATA_PATH"
mkdir -p "$DATA_PATH"

# Build the environment for systemd. Secrets (REGISTRATION_TOKEN) go into a
# root-only EnvironmentFile rather than the world-readable unit file, so these
# are plain KEY=value lines (no Environment= prefix / quoting).
ENV_FILE_CONTENT="DOCKMON_URL=${DOCKMON_URL}
REGISTRATION_TOKEN=${REGISTRATION_TOKEN}
DATA_PATH=${DATA_PATH}
TZ=${TZ}"

if [ -n "$INSECURE_SKIP_VERIFY" ] && [ "$INSECURE_SKIP_VERIFY" = "true" ]; then
    ENV_FILE_CONTENT="${ENV_FILE_CONTENT}
INSECURE_SKIP_VERIFY=true"
fi

if [ -n "$AGENT_NAME" ]; then
    # Reject characters that could inject additional EnvironmentFile assignments:
    # control chars (newlines/tabs/CR) would start a new KEY=value line; double
    # quotes and backslashes get special-cased by systemd's parser. Display names
    # with spaces, dashes, dots, etc. are fine.
    case "$AGENT_NAME" in
        *[[:cntrl:]]*|*'"'*|*'\'*)
            log_error "AGENT_NAME contains forbidden characters (newlines, tabs, double quotes, or backslashes). Use printable characters only."
            exit 1
            ;;
    esac
    ENV_FILE_CONTENT="${ENV_FILE_CONTENT}
AGENT_NAME=${AGENT_NAME}"
fi

if [ -n "$FORCE_UNIQUE_REGISTRATION" ]; then
    # Match the truthy values Go's strconv.ParseBool accepts so the installer
    # behavior aligns with what the agent binary will actually honour.
    case "$FORCE_UNIQUE_REGISTRATION" in
        true|TRUE|True|t|T|1)
            if [ -z "$AGENT_NAME" ]; then
                log_error "FORCE_UNIQUE_REGISTRATION=${FORCE_UNIQUE_REGISTRATION} requires AGENT_NAME to also be set"
                exit 1
            fi
            ENV_FILE_CONTENT="${ENV_FILE_CONTENT}
FORCE_UNIQUE_REGISTRATION=true"
            ;;
        false|FALSE|False|f|F|0)
            # Explicit false — accept silently, matches strconv.ParseBool semantics.
            ;;
        *)
            log_error "FORCE_UNIQUE_REGISTRATION must be a boolean (true/false, 1/0, t/f) — got: '${FORCE_UNIQUE_REGISTRATION}'"
            exit 1
            ;;
    esac
fi

# Write secrets to a root-only EnvironmentFile (contains REGISTRATION_TOKEN).
# umask 077 closes the brief window where the file would otherwise be
# world-readable between creation and chmod.
ENV_DIR="/etc/dockmon-agent"
ENV_FILE="${ENV_DIR}/agent.env"
log_info "Writing agent environment to ${ENV_FILE} (root-only)..."
mkdir -p "$ENV_DIR"
chmod 700 "$ENV_DIR"
OLD_UMASK="$(umask)"
umask 077
cat > "$ENV_FILE" << EOF
${ENV_FILE_CONTENT}
EOF
umask "$OLD_UMASK"
chmod 600 "$ENV_FILE"

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
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_PATH}
Restart=always
RestartSec=10

# Hardening (conservative subset - verified safe with Docker socket access).
NoNewPrivileges=true
ProtectHome=true
PrivateTmp=true
# Stricter confinement is available but must be validated per host (Docker
# socket path, LXC/NAS quirks) before enabling. To opt in, uncomment and keep
# ReadWritePaths covering the agent data dir (identity/token + stacks):
#ProtectSystem=strict
#ReadWritePaths=${DATA_PATH}

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
