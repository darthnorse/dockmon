#!/bin/bash

# DockMon Docker mTLS Setup Script (Unified Edition)
# Automatically detects and configures for standard Linux, unRAID, Synology, etc.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
DAYS_VALID=3650
HOST_NAME=""
HOST_IP=""
SYSTEM_TYPE="unknown"
DOCKER_RESTART_CMD=""
DOCKER_CONFIG_METHOD=""

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_system() {
    echo -e "${BLUE}[SYSTEM]${NC} $1"
}

# Detect if running as root
USER_ID=$(id -u)

# Helper function to run commands with sudo only if needed
run_as_root() {
    if [ "$USER_ID" -ne 0 ]; then
        sudo "$@"
    else
        "$@"
    fi
}

# Detect system type
detect_system() {
    print_info "Detecting system type..."

    # Check for unRAID
    if [ -f "/etc/unraid-version" ] || [ -d "/boot/config" ]; then
        SYSTEM_TYPE="unraid"
        UNRAID_VERSION=$(cat /etc/unraid-version 2>/dev/null || echo "Unknown")
        print_system "Detected unRAID ($UNRAID_VERSION)"
        CERT_DIR="/boot/config/docker-tls"
        DOCKER_RESTART_CMD="/etc/rc.d/rc.docker restart"
        DOCKER_CONFIG_METHOD="unraid"
        return 0
    fi

    # Check for Synology
    if [ -f "/etc/synoinfo.conf" ]; then
        SYSTEM_TYPE="synology"
        print_system "Detected Synology NAS"
        CERT_DIR="/volume1/docker/certs"
        DOCKER_RESTART_CMD="synoservicectl --restart pkgctl-Docker"
        DOCKER_CONFIG_METHOD="synology"
        return 0
    fi

    # Check for QNAP
    if [ -f "/etc/config/qpkg.conf" ]; then
        SYSTEM_TYPE="qnap"
        print_system "Detected QNAP NAS"
        CERT_DIR="/share/docker/certs"
        DOCKER_RESTART_CMD="/etc/init.d/container-station.sh restart"
        DOCKER_CONFIG_METHOD="qnap"
        return 0
    fi

    # Check for TrueNAS/FreeNAS
    if [ -f "/etc/version" ] && grep -q "TrueNAS\|FreeNAS" /etc/version 2>/dev/null; then
        SYSTEM_TYPE="truenas"
        print_system "Detected TrueNAS/FreeNAS"
        CERT_DIR="/mnt/tank/docker/certs"
        DOCKER_RESTART_CMD="service docker restart"
        DOCKER_CONFIG_METHOD="truenas"
        return 0
    fi

    # Check for systemd-based systems (standard Linux)
    if command -v systemctl &> /dev/null && systemctl list-units --full -all | grep -q "docker.service"; then
        SYSTEM_TYPE="systemd"
        print_system "Detected systemd-based Linux"
        CERT_DIR="$HOME/.docker/certs"
        DOCKER_RESTART_CMD="sudo systemctl restart docker"
        DOCKER_CONFIG_METHOD="systemd"
        return 0
    fi

    # Check for OpenRC (Alpine Linux, etc.)
    if command -v rc-service &> /dev/null; then
        SYSTEM_TYPE="openrc"
        print_system "Detected OpenRC-based system"
        CERT_DIR="$HOME/.docker/certs"
        DOCKER_RESTART_CMD="sudo rc-service docker restart"
        DOCKER_CONFIG_METHOD="openrc"
        return 0
    fi

    # Default fallback
    SYSTEM_TYPE="generic"
    print_warn "Could not detect specific system type, using generic configuration"
    CERT_DIR="$HOME/.docker/certs"
    DOCKER_CONFIG_METHOD="manual"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --host)
            HOST_NAME="$2"
            shift 2
            ;;
        --ip)
            HOST_IP="$2"
            shift 2
            ;;
        --dir)
            CERT_DIR="$2"
            CUSTOM_CERT_DIR=true
            shift 2
            ;;
        --days)
            DAYS_VALID="$2"
            shift 2
            ;;
        --system)
            SYSTEM_TYPE="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --host HOSTNAME   Hostname for the Docker host"
            echo "  --ip IP_ADDRESS   IP address for the Docker host"
            echo "  --dir PATH        Directory to store certificates"
            echo "  --days DAYS       Certificate validity in days (default: 365)"
            echo "  --system TYPE     Force system type (unraid|synology|systemd|manual)"
            echo "  --help           Show this help message"
            echo ""
            echo "Supported Systems:"
            echo "  - unRAID         Automatic detection and configuration"
            echo "  - Synology       Automatic detection and configuration"
            echo "  - QNAP           Automatic detection and configuration"
            echo "  - TrueNAS        Automatic detection and configuration"
            echo "  - SystemD Linux  Standard Linux with systemd"
            echo "  - Generic        Manual configuration required"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Detect system if not specified
if [ "$SYSTEM_TYPE" = "unknown" ] || [ -z "$SYSTEM_TYPE" ]; then
    detect_system
fi

# Security check: Detect if Docker is exposed insecurely
check_insecure_docker() {
    print_info "Checking for insecure Docker configuration..."

    INSECURE_DETECTED=false

    # Check if port 2375 (insecure Docker) is listening on all interfaces
    if command -v ss &> /dev/null; then
        if ss -tlnp 2>/dev/null | grep -q ":2375.*0\.0\.0\.0"; then
            INSECURE_DETECTED=true
        fi
    elif command -v netstat &> /dev/null; then
        if netstat -tlnp 2>/dev/null | grep -q ":2375.*0\.0\.0\.0"; then
            INSECURE_DETECTED=true
        fi
    fi

    if [ "$INSECURE_DETECTED" = true ]; then
        echo ""
        print_error "========================================"
        print_error "SECURITY WARNING: Insecure Docker Detected!"
        print_error "========================================"
        echo ""
        print_warn "Your Docker daemon is configured to accept remote connections"
        print_warn "on port 2375 WITHOUT TLS encryption. This is a serious security risk!"
        echo ""
        print_warn "Anyone who can reach port 2375 has COMPLETE control over your system."
        echo ""

        # Recommend Agent instead of mTLS
        print_info "========================================"
        print_info "RECOMMENDATION: Use the DockMon Agent"
        print_info "========================================"
        echo ""
        echo "Instead of configuring mTLS, we recommend installing the DockMon Agent:"
        echo ""
        echo "  - No need to expose any ports"
        echo "  - Agent connects outbound to your DockMon server"
        echo "  - Works through NAT and firewalls"
        echo "  - Simpler setup with token-based authentication"
        echo ""
        echo "To install the Agent, generate a token in DockMon's Add Host dialog"
        echo "and run the provided docker command on this host."
        echo ""
        echo "See: https://github.com/darthnorse/dockmon/wiki/Remote-Docker-Setup"
        echo ""

        read -p "Do you want to disable insecure remote Docker access? (Y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            disable_insecure_docker
        else
            print_warn "Continuing with mTLS setup. The insecure configuration will remain until you configure mTLS."
        fi
        echo ""
    fi
}

# Disable insecure Docker remote access
disable_insecure_docker() {
    print_info "Disabling insecure Docker remote access..."

    case $SYSTEM_TYPE in
        systemd)
            # Check for systemd override
            if [ -f /etc/systemd/system/docker.service.d/override.conf ]; then
                print_info "Found Docker systemd override, checking configuration..."

                # Check if it contains insecure TCP binding
                if grep -q "tcp://0\.0\.0\.0:2375" /etc/systemd/system/docker.service.d/override.conf; then
                    print_info "Removing insecure TCP binding from systemd override..."

                    # Backup the file
                    BACKUP_FILE="/etc/systemd/system/docker.service.d/override.conf.insecure-backup-$(date +%Y%m%d-%H%M%S)"
                    run_as_root cp /etc/systemd/system/docker.service.d/override.conf "$BACKUP_FILE"
                    print_info "Backed up to: $BACKUP_FILE"

                    # Create new override with only unix socket
                    cat <<EOF | run_as_root tee /etc/systemd/system/docker.service.d/override.conf > /dev/null
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd -H unix:///var/run/docker.sock
EOF

                    print_info "Restarting Docker daemon..."
                    run_as_root systemctl daemon-reload
                    run_as_root systemctl restart docker

                    sleep 2

                    # Verify it's no longer listening
                    if ss -tlnp 2>/dev/null | grep -q ":2375"; then
                        print_error "Port 2375 is still open. Manual intervention may be required."
                    else
                        print_info "Docker is now only accessible via local Unix socket."
                        print_info "Remote access has been disabled."
                    fi
                else
                    print_warn "Override file exists but doesn't contain the expected insecure configuration."
                    print_warn "Please check /etc/systemd/system/docker.service.d/override.conf manually."
                fi
            else
                # Check daemon.json
                if [ -f /etc/docker/daemon.json ]; then
                    print_warn "Docker configuration found in /etc/docker/daemon.json"
                    print_warn "Please manually remove any 'hosts' entries that expose port 2375"
                    print_warn "Then restart Docker: sudo systemctl restart docker"
                else
                    print_warn "Could not find Docker override configuration."
                    print_warn "The insecure binding may be in a non-standard location."
                fi
            fi
            ;;
        unraid)
            print_info "For unRAID, please update /boot/config/docker.cfg:"
            echo ""
            echo "1. Edit /boot/config/docker.cfg"
            echo "2. Remove or comment out any DOCKER_OPTS with tcp://0.0.0.0:2375"
            echo "3. Restart Docker via Settings → Docker"
            ;;
        *)
            print_warn "Automatic disabling not available for $SYSTEM_TYPE"
            print_warn "Please manually configure Docker to only listen on the Unix socket."
            ;;
    esac
}

# Run security check
check_insecure_docker

# Override cert directory if not custom set and system detected
if [ -z "$CUSTOM_CERT_DIR" ]; then
    case $SYSTEM_TYPE in
        unraid)
            # Check for existing certificates in both new and legacy locations
            if [ -f "/boot/config/docker-tls/ca.pem" ] && [ -f "/boot/config/docker-tls/client-cert.pem" ]; then
                CERT_DIR="/boot/config/docker-tls"
                UNRAID_EXISTING_CERTS=true
            elif [ -f "/boot/config/docker/certs/ca.pem" ] && [ -f "/boot/config/docker/certs/client-cert.pem" ]; then
                CERT_DIR="/boot/config/docker/certs"
                UNRAID_EXISTING_CERTS=true
            else
                CERT_DIR="/boot/config/docker-tls"
                UNRAID_EXISTING_CERTS=false
            fi
            ;;
        synology)
            CERT_DIR="/volume1/docker/certs"
            ;;
        qnap)
            CERT_DIR="/share/docker/certs"
            ;;
        truenas)
            CERT_DIR="/mnt/tank/docker/certs"
            ;;
    esac
fi

# Detect hostname and IP if not provided
if [ -z "$HOST_NAME" ]; then
    HOST_NAME=$(hostname -f 2>/dev/null || hostname)
    print_info "Using detected hostname: $HOST_NAME"
fi

if [ -z "$HOST_IP" ]; then
    # Try to get the primary IP address
    if command -v ip &> /dev/null; then
        HOST_IP=$(ip route get 1 2>/dev/null | grep -oP 'src \K\S+' || echo "")
    fi
    if [ -z "$HOST_IP" ]; then
        HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
    fi
    print_info "Using detected IP: $HOST_IP"
fi

print_info "==================================="
print_info "DockMon Docker mTLS Setup"
print_system "Platform: $SYSTEM_TYPE"
print_info "==================================="
print_info "Hostname: $HOST_NAME"
print_info "IP Address: $HOST_IP"
print_info "Certificate Directory: $CERT_DIR"
print_info "Validity Period: $DAYS_VALID days"
echo ""

# Create certificate directory
mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

# Check if certificates already exist
if [ -f "ca.pem" ] || [ -f "server-cert.pem" ] || [ -f "client-cert.pem" ]; then
    print_warn "Existing certificates found in $CERT_DIR"
    read -p "Do you want to overwrite them? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Exiting without changes"
        exit 0
    fi
    # Backup existing certificates
    BACKUP_DIR="$CERT_DIR/backup-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    mv -f *.pem "$BACKUP_DIR" 2>/dev/null || true
    print_info "Existing certificates backed up to: $BACKUP_DIR"
fi

print_info "Generating Certificate Authority (CA)..."

# Generate CA private key
openssl genrsa -out ca-key.pem 4096 2>/dev/null

# Create CA config file with X.509 v3 extensions (compatible with all OpenSSL versions)
cat > ca.cnf <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_ca
prompt = no

[req_distinguished_name]
C = US
ST = State
L = City
O = DockMon
CN = DockMon CA

[v3_ca]
keyUsage = critical, keyCertSign, cRLSign
basicConstraints = critical, CA:TRUE
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer:always
EOF

# Generate CA certificate with proper X.509 v3 extensions for Alpine Linux compatibility
openssl req -new -x509 -days $DAYS_VALID -key ca-key.pem -sha256 -out ca.pem \
    -config ca.cnf 2>/dev/null

print_info "Generating Server certificates..."

# Generate server private key
openssl genrsa -out server-key.pem 4096 2>/dev/null

# Generate server certificate request
openssl req -subj "/CN=$HOST_NAME" -sha256 -new -key server-key.pem -out server.csr 2>/dev/null

# Create extensions file for server certificate with proper X.509 v3 extensions
cat > extfile.cnf <<EOF
subjectAltName = DNS:$HOST_NAME,DNS:localhost,IP:$HOST_IP,IP:127.0.0.1
extendedKeyUsage = serverAuth
keyUsage = critical, digitalSignature, keyEncipherment
basicConstraints = CA:FALSE
authorityKeyIdentifier = keyid,issuer
EOF

# Sign server certificate
openssl x509 -req -days $DAYS_VALID -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem \
    -CAcreateserial -out server-cert.pem -extfile extfile.cnf 2>/dev/null

print_info "Generating Client certificates for DockMon..."

# Generate client private key
openssl genrsa -out client-key.pem 4096 2>/dev/null

# Generate client certificate request
openssl req -subj '/CN=DockMon Client' -new -key client-key.pem -out client.csr 2>/dev/null

# Create extensions file for client certificate with proper X.509 v3 extensions
cat > extfile-client.cnf <<EOF
extendedKeyUsage = clientAuth
keyUsage = critical, digitalSignature, keyEncipherment
basicConstraints = CA:FALSE
authorityKeyIdentifier = keyid,issuer
EOF

# Sign client certificate
openssl x509 -req -days $DAYS_VALID -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem \
    -CAcreateserial -out client-cert.pem -extfile extfile-client.cnf 2>/dev/null

# Clean up temporary files
rm -f *.csr *.cnf ca.srl

# Set appropriate permissions
chmod 444 *.pem
chmod 400 *-key.pem

print_info "Certificates generated successfully!"
echo ""

# System-specific setup
case $SYSTEM_TYPE in
    unraid)
        print_system "Configuring for unRAID..."

        if [ "$UNRAID_EXISTING_CERTS" = true ]; then
            print_info "Found existing Docker TLS certificates in: $CERT_DIR"
            print_warn "unRAID 7.x automatically generates Docker TLS certificates on fresh installs"
            print_warn "You can use these existing certificates instead of generating new ones"
            echo ""
        fi
        ;;

    synology)
        print_system "Configuring for Synology NAS..."
        print_warn "NOTE: Synology support is UNTESTED - proceed at your own risk"
        ;;

    qnap)
        print_system "Configuring for QNAP NAS..."
        print_warn "NOTE: QNAP support is UNTESTED - proceed at your own risk"
        ;;

    truenas)
        print_system "Configuring for TrueNAS..."
        print_warn "NOTE: TrueNAS support is UNTESTED - proceed at your own risk"
        ;;

    systemd)
        print_system "Configuring for systemd-based Linux..."

        # Generate systemd override with correct paths for /etc/docker/certs
        OVERRIDE_FILE="$CERT_DIR/docker-override.conf"
        cat > "$OVERRIDE_FILE" <<EOF
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd \\
    -H unix:///var/run/docker.sock \\
    -H tcp://0.0.0.0:2376 \\
    --tlsverify \\
    --tlscacert=/etc/docker/certs/ca.pem \\
    --tlscert=/etc/docker/certs/server-cert.pem \\
    --tlskey=/etc/docker/certs/server-key.pem
EOF
        ;;

    *)
        print_warn "Manual configuration required for $SYSTEM_TYPE"
        print_info "Generic configuration files have been created"
        ;;
esac

echo ""
echo "========================================"
echo "ADD HOST TO DOCKMON"
echo "========================================"
echo ""
echo "Step 1: Display and copy certificate contents:"
echo ""
echo "   # Display CA Certificate (copy entire output including BEGIN/END lines)"
echo "   cat $CERT_DIR/ca.pem"
echo ""
echo "   # Display Client Certificate (copy entire output including BEGIN/END lines)"
echo "   cat $CERT_DIR/client-cert.pem"
echo ""
echo "   # Display Client Key (copy entire output including BEGIN/END lines)"
echo "   cat $CERT_DIR/client-key.pem"
echo ""
echo "Step 2: Add host in DockMon web interface:"
echo "   1. Go to Host Management page"
echo "   2. Click 'Add Host' button"
echo "   3. Fill in:"
echo "      - Name: [Your descriptive name]"
echo "      - URL: tcp://$HOST_IP:2376"
echo "      - CA Certificate: [Paste ENTIRE contents of ca.pem]"
echo "      - Client Certificate: [Paste ENTIRE contents of client-cert.pem]"
echo "      - Client Key: [Paste ENTIRE contents of client-key.pem]"
echo "   4. Click 'Test Connection'"
echo "   5. If successful, click 'Save'"
echo ""
print_warn "IMPORTANT: Keep the private keys (*-key.pem) secure!"
print_warn "Never commit certificates to version control!"

# Offer to configure Docker automatically if available
if [ "$SYSTEM_TYPE" != "manual" ] && command -v docker &> /dev/null; then
    echo ""
    read -p "Do you want to configure Docker for mTLS now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        case $SYSTEM_TYPE in
            unraid)
                print_warn "Please configure Docker manually via unRAID Web UI as described above"
                print_info "After configuration, restart Docker with: /etc/rc.d/rc.docker restart"
                ;;
            systemd)
                print_info "Configuring Docker daemon..."

                # Check if override.conf already exists and warn user
                if [ -f /etc/systemd/system/docker.service.d/override.conf ]; then
                    echo ""
                    print_warn "Existing Docker daemon override configuration found!"
                    echo ""
                    echo "Current configuration:"
                    run_as_root cat /etc/systemd/system/docker.service.d/override.conf | head -15
                    echo ""
                    read -p "This will be REPLACED with mTLS configuration. Continue? (y/N): " -n 1 -r
                    echo ""
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        print_info "Configuration cancelled. Manual setup instructions available by re-running and selecting 'N'"
                        exit 0
                    fi

                    BACKUP_FILE="/etc/systemd/system/docker.service.d/override.conf.backup-$(date +%Y%m%d-%H%M%S)"
                    run_as_root cp /etc/systemd/system/docker.service.d/override.conf "$BACKUP_FILE"
                    print_info "Backed up existing override.conf to: $BACKUP_FILE"
                fi

                run_as_root mkdir -p /etc/docker/certs
                run_as_root cp "$CERT_DIR"/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/
                run_as_root chmod 400 /etc/docker/certs/*-key.pem
                run_as_root chmod 444 /etc/docker/certs/*.pem

                run_as_root mkdir -p /etc/systemd/system/docker.service.d/
                cat <<EOF | run_as_root tee /etc/systemd/system/docker.service.d/override.conf > /dev/null
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd \\
    -H unix:///var/run/docker.sock \\
    -H tcp://0.0.0.0:2376 \\
    --tlsverify \\
    --tlscacert=/etc/docker/certs/ca.pem \\
    --tlscert=/etc/docker/certs/server-cert.pem \\
    --tlskey=/etc/docker/certs/server-key.pem
EOF

                print_info "Restarting Docker daemon..."
                run_as_root systemctl daemon-reload
                run_as_root systemctl restart docker

                sleep 3

                print_info "Testing mTLS connection..."
                if docker --tlsverify \
                    --tlscacert="$CERT_DIR/ca.pem" \
                    --tlscert="$CERT_DIR/client-cert.pem" \
                    --tlskey="$CERT_DIR/client-key.pem" \
                    -H=tcp://localhost:2376 version > /dev/null 2>&1; then
                    print_info "✅ mTLS configuration successful!"
                    echo ""
                    print_info "Test the connection from your local machine:"
                    echo "  docker --tlsverify \\"
                    echo "    --tlscacert=$CERT_DIR/ca.pem \\"
                    echo "    --tlscert=$CERT_DIR/client-cert.pem \\"
                    echo "    --tlskey=$CERT_DIR/client-key.pem \\"
                    echo "    -H=tcp://$HOST_IP:2376 version"
                else
                    if [ "$USER_ID" -ne 0 ]; then
                        print_error "Failed to connect. Check logs: sudo journalctl -u docker -n 50"
                    else
                        print_error "Failed to connect. Check logs: journalctl -u docker -n 50"
                    fi
                fi
                ;;
            *)
                print_warn "Automatic configuration not available for $SYSTEM_TYPE"
                ;;
        esac
    else
        # User selected No - show manual instructions based on system type
        echo ""
        case $SYSTEM_TYPE in
            systemd)
                print_info "==================================="
                print_info "Manual Configuration Instructions:"
                print_info "==================================="
                echo ""
                echo "1. Backup existing Docker override (if it exists):"
                echo "   [ -f /etc/systemd/system/docker.service.d/override.conf ] && \\"
                echo "     sudo cp /etc/systemd/system/docker.service.d/override.conf \\"
                echo "     /etc/systemd/system/docker.service.d/override.conf.backup-\$(date +%Y%m%d-%H%M%S)"
                echo ""
                echo "2. Copy certificates to system directory:"
                echo "   sudo mkdir -p /etc/docker/certs"
                echo "   sudo cp $CERT_DIR/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/"
                echo "   sudo chmod 400 /etc/docker/certs/*-key.pem"
                echo "   sudo chmod 444 /etc/docker/certs/*.pem"
                echo ""
                echo "3. Configure Docker daemon:"
                echo "   sudo mkdir -p /etc/systemd/system/docker.service.d/"
                echo "   sudo cp $CERT_DIR/docker-override.conf /etc/systemd/system/docker.service.d/override.conf"
                echo ""
                echo "4. Restart Docker:"
                echo "   sudo systemctl daemon-reload"
                echo "   sudo systemctl restart docker"
                echo ""
                echo "5. Test the mTLS connection:"
                echo "   docker --tlsverify \\"
                echo "     --tlscacert=$CERT_DIR/ca.pem \\"
                echo "     --tlscert=$CERT_DIR/client-cert.pem \\"
                echo "     --tlskey=$CERT_DIR/client-key.pem \\"
                echo "     -H=tcp://$HOST_IP:2376 version"
                ;;
            unraid)
                print_info "==================================="
                print_info "unRAID Configuration Instructions:"
                print_info "==================================="
                echo ""
                echo "To enable Docker remote access with TLS on unRAID:"
                echo ""
                echo "1. Stop Docker service:"
                echo "   - Via Web UI: Settings → Docker → Set 'Enable Docker' to No → Apply"
                echo "   - Via SSH: /etc/rc.d/rc.docker stop"
                echo ""
                echo "2. Backup existing Docker configuration:"
                echo "   cp /boot/config/docker.cfg /boot/config/docker.cfg.backup-\$(date +%Y%m%d-%H%M%S)"
                echo ""
                echo "3. Edit /boot/config/docker.cfg via SSH:"
                echo "   nano /boot/config/docker.cfg"
                echo ""
                echo "4. Add or update the DOCKER_OPTS line:"
                echo "   DOCKER_OPTS=\"-H unix:///var/run/docker.sock -H tcp://0.0.0.0:2376 \\"
                echo "     --tlsverify \\"
                echo "     --tlscacert=$CERT_DIR/ca.pem \\"
                echo "     --tlscert=$CERT_DIR/server-cert.pem \\"
                echo "     --tlskey=$CERT_DIR/server-key.pem\""
                echo ""
                echo "5. Start Docker service:"
                echo "   - Via Web UI: Settings → Docker → Set 'Enable Docker' to Yes → Apply"
                echo "   - Via SSH: /etc/rc.d/rc.docker start"
                echo ""
                echo "6. Test the connection:"
                echo "   docker --tlsverify \\"
                echo "     --tlscacert=$CERT_DIR/ca.pem \\"
                echo "     --tlscert=$CERT_DIR/client-cert.pem \\"
                echo "     --tlskey=$CERT_DIR/client-key.pem \\"
                echo "     -H=tcp://$HOST_IP:2376 version"
                ;;
            synology)
                print_info "==================================="
                print_info "Synology Configuration Instructions (UNTESTED):"
                print_info "==================================="
                echo ""
                echo "1. Open Synology DSM Web UI"
                echo "2. Go to Package Center → Docker"
                echo "3. Stop Docker package"
                echo "4. SSH into your Synology and run:"
                echo "   sudo vi /var/packages/Docker/etc/dockerd.json"
                echo "5. Add the following configuration:"
                echo '   {'
                echo '     "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"],'
                echo '     "tls": true,'
                echo '     "tlsverify": true,'
                echo "     \"tlscacert\": \"$CERT_DIR/ca.pem\","
                echo "     \"tlscert\": \"$CERT_DIR/server-cert.pem\","
                echo "     \"tlskey\": \"$CERT_DIR/server-key.pem\""
                echo '   }'
                echo "6. Start Docker package from Package Center"
                ;;
        esac
    fi
fi

print_info "Setup complete!"