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
DAYS_VALID=365
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

# Override cert directory if not custom set and system detected
if [ -z "$CUSTOM_CERT_DIR" ]; then
    case $SYSTEM_TYPE in
        unraid)
            CERT_DIR="/boot/config/docker-tls"
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

# Generate CA certificate
openssl req -new -x509 -days $DAYS_VALID -key ca-key.pem -sha256 -out ca.pem \
    -subj "/C=US/ST=State/L=City/O=DockMon/CN=DockMon CA" 2>/dev/null

print_info "Generating Server certificates..."

# Generate server private key
openssl genrsa -out server-key.pem 4096 2>/dev/null

# Generate server certificate request
openssl req -subj "/CN=$HOST_NAME" -sha256 -new -key server-key.pem -out server.csr 2>/dev/null

# Create extensions file for server certificate
cat > extfile.cnf <<EOF
subjectAltName = DNS:$HOST_NAME,DNS:localhost,IP:$HOST_IP,IP:127.0.0.1
extendedKeyUsage = serverAuth
EOF

# Sign server certificate
openssl x509 -req -days $DAYS_VALID -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem \
    -CAcreateserial -out server-cert.pem -extfile extfile.cnf 2>/dev/null

print_info "Generating Client certificates for DockMon..."

# Generate client private key
openssl genrsa -out client-key.pem 4096 2>/dev/null

# Generate client certificate request
openssl req -subj '/CN=DockMon Client' -new -key client-key.pem -out client.csr 2>/dev/null

# Create extensions file for client certificate
echo "extendedKeyUsage = clientAuth" > extfile-client.cnf

# Sign client certificate
openssl x509 -req -days $DAYS_VALID -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem \
    -CAcreateserial -out client-cert.pem -extfile extfile-client.cnf 2>/dev/null

# Clean up temporary files
rm -f *.csr extfile*.cnf ca.srl

# Set appropriate permissions
chmod 400 *-key.pem
chmod 444 *.pem

print_info "Certificates generated successfully!"
echo ""

# System-specific configuration
case $SYSTEM_TYPE in
    unraid)
        print_system "Configuring for unRAID..."

        # Create Docker daemon configuration for unRAID
        cat > "$CERT_DIR/docker-daemon.json" <<EOF
{
    "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"],
    "tls": true,
    "tlsverify": true,
    "tlscacert": "$CERT_DIR/ca.pem",
    "tlscert": "$CERT_DIR/server-cert.pem",
    "tlskey": "$CERT_DIR/server-key.pem"
}
EOF

        print_info "==================================="
        print_info "unRAID Configuration Instructions:"
        print_info "==================================="
        echo ""
        echo "Option 1: Configure via unRAID Web UI (Recommended):"
        echo "1. Go to Settings → Docker in your unRAID Web UI"
        echo "2. Click 'Advanced View'"
        echo "3. Stop the Docker service"
        echo "4. In 'Extra Parameters', add:"
        echo "   -H tcp://0.0.0.0:2376 --tlsverify --tlscacert=$CERT_DIR/ca.pem --tlscert=$CERT_DIR/server-cert.pem --tlskey=$CERT_DIR/server-key.pem"
        echo "5. Apply and start the Docker service"
        echo ""
        echo "Option 2: Configure via Command Line:"
        echo "1. Stop Docker:"
        echo "   /etc/rc.d/rc.docker stop"
        echo ""
        echo "2. Edit /boot/config/docker.cfg and add:"
        echo "   DOCKER_OPTS=\"-H tcp://0.0.0.0:2376 --tlsverify --tlscacert=$CERT_DIR/ca.pem --tlscert=$CERT_DIR/server-cert.pem --tlskey=$CERT_DIR/server-key.pem\""
        echo ""
        echo "3. Start Docker:"
        echo "   /etc/rc.d/rc.docker start"
        echo ""
        echo "Option 3: Make changes persistent across reboots:"
        echo "1. Edit /boot/config/go and add before the last line:"
        echo "   # Docker mTLS"
        echo "   echo 'DOCKER_OPTS=\"-H tcp://0.0.0.0:2376 --tlsverify --tlscacert=$CERT_DIR/ca.pem --tlscert=$CERT_DIR/server-cert.pem --tlskey=$CERT_DIR/server-key.pem\"' >> /boot/config/docker.cfg"
        echo ""
        print_warn "NOTE: Certificates are stored in $CERT_DIR which persists across reboots"
        ;;

    synology)
        print_system "Configuring for Synology NAS..."

        print_info "==================================="
        print_info "Synology Configuration Instructions:"
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

    systemd)
        print_system "Configuring for systemd-based Linux..."

        # Generate systemd override
        OVERRIDE_FILE="$CERT_DIR/docker-override.conf"
        cat > "$OVERRIDE_FILE" <<EOF
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd \\
    -H unix:///var/run/docker.sock \\
    -H tcp://0.0.0.0:2376 \\
    --tlsverify \\
    --tlscacert=$CERT_DIR/ca.pem \\
    --tlscert=$CERT_DIR/server-cert.pem \\
    --tlskey=$CERT_DIR/server-key.pem
EOF

        print_info "==================================="
        print_info "SystemD Configuration Instructions:"
        print_info "==================================="
        echo ""
        echo "1. Copy certificates to system directory:"
        echo "   sudo mkdir -p /etc/docker/certs"
        echo "   sudo cp $CERT_DIR/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/"
        echo "   sudo chmod 400 /etc/docker/certs/*-key.pem"
        echo ""
        echo "2. Configure Docker daemon:"
        echo "   sudo mkdir -p /etc/systemd/system/docker.service.d/"
        echo "   sudo cp $CERT_DIR/docker-override.conf /etc/systemd/system/docker.service.d/override.conf"
        echo ""
        echo "3. Restart Docker:"
        echo "   sudo systemctl daemon-reload"
        echo "   sudo systemctl restart docker"
        ;;

    *)
        print_warn "Manual configuration required for $SYSTEM_TYPE"
        print_info "Generic configuration files have been created."
        ;;
esac

echo ""
print_info "==================================="
print_info "Testing & Connection Instructions:"
print_info "==================================="
echo ""
echo "Test the mTLS connection:"
echo "  docker --tlsverify \\"
echo "    --tlscacert=$CERT_DIR/ca.pem \\"
echo "    --tlscert=$CERT_DIR/client-cert.pem \\"
echo "    --tlskey=$CERT_DIR/client-key.pem \\"
echo "    -H=tcp://$HOST_IP:2376 version"
echo ""
echo "In DockMon, add this host with:"
echo "  URL: tcp://$HOST_IP:2376"
echo "  CA Certificate: $CERT_DIR/ca.pem"
echo "  Client Certificate: $CERT_DIR/client-cert.pem"
echo "  Client Key: $CERT_DIR/client-key.pem"
echo ""
print_warn "IMPORTANT: Keep the private keys (*-key.pem) secure!"
print_warn "Never commit certificates to version control!"

# Offer to test the connection if Docker is available
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
                sudo mkdir -p /etc/docker/certs
                sudo cp "$CERT_DIR"/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/
                sudo chmod 400 /etc/docker/certs/*-key.pem
                sudo chmod 444 /etc/docker/certs/*.pem

                sudo mkdir -p /etc/systemd/system/docker.service.d/
                cat <<EOF | sudo tee /etc/systemd/system/docker.service.d/override.conf > /dev/null
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
                sudo systemctl daemon-reload
                sudo systemctl restart docker

                sleep 3

                print_info "Testing mTLS connection..."
                if docker --tlsverify \
                    --tlscacert="$CERT_DIR/ca.pem" \
                    --tlscert="$CERT_DIR/client-cert.pem" \
                    --tlskey="$CERT_DIR/client-key.pem" \
                    -H=tcp://localhost:2376 version > /dev/null 2>&1; then
                    print_info "✅ mTLS configuration successful!"
                else
                    print_error "Failed to connect. Check logs: sudo journalctl -u docker -n 50"
                fi
                ;;
            *)
                print_warn "Automatic configuration not available for $SYSTEM_TYPE"
                ;;
        esac
    fi
fi

print_info "Setup complete!"