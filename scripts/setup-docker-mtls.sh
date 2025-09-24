#!/bin/bash

# DockMon Docker mTLS Setup Script
# This script generates certificates for secure Docker remote API access

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
CERT_DIR="$HOME/.docker/certs"
DAYS_VALID=365
HOST_NAME=""
HOST_IP=""

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
            shift 2
            ;;
        --days)
            DAYS_VALID="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --host HOSTNAME   Hostname for the Docker host (e.g., docker.example.com)"
            echo "  --ip IP_ADDRESS   IP address for the Docker host"
            echo "  --dir PATH        Directory to store certificates (default: ~/.docker/certs)"
            echo "  --days DAYS       Certificate validity in days (default: 365)"
            echo "  --help           Show this help message"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

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
openssl req -new -x509 -days $DAYS_VALID -key ca-key.pem -sha256 -out ca.pem -subj "/C=US/ST=State/L=City/O=DockMon/CN=DockMon CA" 2>/dev/null

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
openssl x509 -req -days $DAYS_VALID -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -out server-cert.pem -extfile extfile.cnf 2>/dev/null

print_info "Generating Client certificates for DockMon..."

# Generate client private key
openssl genrsa -out client-key.pem 4096 2>/dev/null

# Generate client certificate request
openssl req -subj '/CN=DockMon Client' -new -key client-key.pem -out client.csr 2>/dev/null

# Create extensions file for client certificate
echo "extendedKeyUsage = clientAuth" > extfile-client.cnf

# Sign client certificate
openssl x509 -req -days $DAYS_VALID -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -out client-cert.pem -extfile extfile-client.cnf 2>/dev/null

# Clean up temporary files
rm -f *.csr extfile*.cnf ca.srl

# Set appropriate permissions
chmod 400 *-key.pem
chmod 444 *.pem

print_info "Certificates generated successfully!"
echo ""
print_info "Certificate files created in: $CERT_DIR"
echo "  - ca.pem           : Certificate Authority"
echo "  - server-cert.pem  : Server certificate"
echo "  - server-key.pem   : Server private key (keep secure!)"
echo "  - client-cert.pem  : Client certificate for DockMon"
echo "  - client-key.pem   : Client private key for DockMon (keep secure!)"
echo ""

# Generate systemd override configuration
print_info "Generating systemd override configuration..."

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
print_info "Next Steps:"
print_info "==================================="
echo ""
echo "1. Copy server certificates to Docker host (if not already there):"
echo "   sudo mkdir -p /etc/docker/certs"
echo "   sudo cp $CERT_DIR/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/"
echo "   sudo chmod 400 /etc/docker/certs/*-key.pem"
echo ""
echo "2. Configure Docker daemon for mTLS:"
echo "   sudo mkdir -p /etc/systemd/system/docker.service.d/"
echo "   sudo cp $CERT_DIR/docker-override.conf /etc/systemd/system/docker.service.d/override.conf"
echo ""
echo "   Or edit the override file manually:"
echo "   sudo systemctl edit docker"
echo ""
echo "3. Restart Docker:"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl restart docker"
echo ""
echo "4. Test the connection:"
echo "   docker --tlsverify \\"
echo "     --tlscacert=$CERT_DIR/ca.pem \\"
echo "     --tlscert=$CERT_DIR/client-cert.pem \\"
echo "     --tlskey=$CERT_DIR/client-key.pem \\"
echo "     -H=tcp://$HOST_NAME:2376 version"
echo ""
echo "5. In DockMon, add this host with:"
echo "   - URL: tcp://$HOST_NAME:2376"
echo "   - CA Certificate: $CERT_DIR/ca.pem"
echo "   - Client Certificate: $CERT_DIR/client-cert.pem"
echo "   - Client Key: $CERT_DIR/client-key.pem"
echo ""
print_warn "IMPORTANT: Keep the private keys (*.key.pem) secure!"
print_warn "Never commit certificates to version control!"

# Offer to test the connection if Docker is running locally
if command -v docker &> /dev/null && [ -S /var/run/docker.sock ]; then
    echo ""
    read -p "Do you want to configure Docker for mTLS now? (requires sudo) (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Configuring Docker daemon..."

        # Create certificate directory
        sudo mkdir -p /etc/docker/certs

        # Copy certificates
        sudo cp "$CERT_DIR"/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/
        sudo chmod 400 /etc/docker/certs/*-key.pem
        sudo chmod 444 /etc/docker/certs/*.pem

        # Create systemd override
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

        # Wait for Docker to start
        sleep 3

        print_info "Testing mTLS connection..."
        if docker --tlsverify \
            --tlscacert="$CERT_DIR/ca.pem" \
            --tlscert="$CERT_DIR/client-cert.pem" \
            --tlskey="$CERT_DIR/client-key.pem" \
            -H=tcp://localhost:2376 version > /dev/null 2>&1; then
            print_info "✅ mTLS configuration successful! Docker is now secured."
        else
            print_error "Failed to connect with mTLS. Check Docker logs: sudo journalctl -u docker -n 50"
        fi
    fi
fi

print_info "Setup complete!"