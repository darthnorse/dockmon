#!/bin/bash

# Generate self-signed SSL certificates for DockMon
# These certificates are for development/internal use only

CERT_DIR="./docker/certs"
CERT_DAYS=3650  # 10 years

# Create certificate directory
mkdir -p "$CERT_DIR"

# Generate private key
openssl genrsa -out "$CERT_DIR/dockmon.key" 2048

# Generate certificate signing request
openssl req -new -key "$CERT_DIR/dockmon.key" \
  -out "$CERT_DIR/dockmon.csr" \
  -subj "/C=US/ST=State/L=City/O=DockMon/CN=localhost"

# Generate self-signed certificate
openssl x509 -req -days $CERT_DAYS \
  -in "$CERT_DIR/dockmon.csr" \
  -signkey "$CERT_DIR/dockmon.key" \
  -out "$CERT_DIR/dockmon.crt"

# Create a combined certificate file for nginx
cat "$CERT_DIR/dockmon.crt" "$CERT_DIR/dockmon.key" > "$CERT_DIR/dockmon.pem"

# Set appropriate permissions
chmod 600 "$CERT_DIR/dockmon.key"
chmod 644 "$CERT_DIR/dockmon.crt"
chmod 600 "$CERT_DIR/dockmon.pem"

# Clean up CSR
rm "$CERT_DIR/dockmon.csr"

echo "✅ SSL certificates generated successfully in $CERT_DIR"
echo "   - Certificate: $CERT_DIR/dockmon.crt"
echo "   - Private Key: $CERT_DIR/dockmon.key"
echo "   - Combined PEM: $CERT_DIR/dockmon.pem"