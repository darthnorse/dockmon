# Remote Docker Setup

Monitor Docker hosts on remote servers with secure mTLS authentication.

## ⚠️ Security Warning

**NEVER expose Docker's API without TLS!**

Exposing Docker's API without TLS gives anyone who can reach the port **COMPLETE control** over your host system. They can:
- Run any container with host privileges
- Access all files on your system
- Install cryptocurrency miners
- Compromise your entire network

**Always use mTLS (mutual TLS) for production systems.**

---

## Table of Contents

- [Quick Setup with Script (Recommended)](#quick-setup-with-script-recommended)
- [Manual mTLS Setup](#manual-mtls-setup)
- [Platform-Specific Guides](#platform-specific-guides)
- [Troubleshooting](#troubleshooting)
- [Insecure Setup (Development Only)](#insecure-setup-development-only)

---

## Quick Setup with Script (Recommended)

We provide an automated script that generates certificates and provides platform-specific configuration instructions.

### Download and Run Script

On your **remote Docker host** (the server you want to monitor):

```bash
# Download the script
curl -sSL https://raw.githubusercontent.com/darthnorse/dockmon/main/scripts/setup-docker-mtls.sh -o setup-docker-mtls.sh

# Make it executable
chmod +x setup-docker-mtls.sh

# Run with default settings
./setup-docker-mtls.sh

# Or with custom hostname/IP
./setup-docker-mtls.sh --host myserver.local --ip 192.168.1.100
```

### What the Script Does

1. **Checks for existing certificates** (unRAID 7.x generates them automatically)
2. Generates Certificate Authority (CA) if needed
3. Generates server certificates if needed
4. Generates client certificates if needed
5. Detects your system type (systemd, unRAID, Synology, etc.)
6. Shows **exact commands** to configure Docker for your system
7. Creates configuration files ready to use

**Note for unRAID users:**
- **unRAID 7.x** (fresh install): Certificates are auto-generated in `/boot/config/docker-tls/`
- **unRAID 6.x** (upgraded): May have certificates in `/boot/config/docker/certs/`
- The script automatically detects and uses existing certificates

### What You Need to Do

The script is **non-destructive** - it generates everything but doesn't modify your Docker daemon.

**You must manually:**
1. Follow the platform-specific instructions the script provides
2. Apply the Docker daemon configuration
3. Restart Docker service
4. Copy certificate contents to DockMon

### Example Output

```
========================================
mTLS Setup Complete!
========================================

Certificates generated in: /home/user/.docker/certs

CA Certificate:     ca.pem
Server Certificate: server-cert.pem
Server Key:         server-key.pem
Client Certificate: client-cert.pem
Client Key:         client-key.pem

DETECTED SYSTEM: Linux with systemd

========================================
CONFIGURATION INSTRUCTIONS
========================================

1. Copy certificates to system directory:
   sudo mkdir -p /etc/docker/certs
   sudo cp /home/user/.docker/certs/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/
   sudo chmod 400 /etc/docker/certs/*-key.pem

2. Apply systemd override:
   sudo mkdir -p /etc/systemd/system/docker.service.d/
   sudo cp /home/user/.docker/certs/docker-override.conf /etc/systemd/system/docker.service.d/override.conf

3. Restart Docker:
   sudo systemctl daemon-reload
   sudo systemctl restart docker

4. Verify Docker is listening on port 2376:
   ss -tlnp | grep 2376

========================================
ADD TO DOCKMON
========================================

In DockMon, add host with:
- URL: tcp://192.168.1.100:2376
- CA Certificate: Contents of ca.pem
- Client Certificate: Contents of client-cert.pem
- Client Key: Contents of client-key.pem
```

### Add Host in DockMon

After configuring Docker on the remote host:

#### Step 1: Get Certificate Contents

On the **remote host**, display the certificate contents:

```bash
# Show CA certificate
cat ~/.docker/certs/ca.pem

# Show client certificate
cat ~/.docker/certs/client-cert.pem

# Show client key
cat ~/.docker/certs/client-key.pem
```

Copy each certificate's full content (including `-----BEGIN CERTIFICATE-----` and `-----END CERTIFICATE-----` lines).

#### Step 2: Add Host in DockMon

1. In DockMon, go to **Host Management**
2. Click **"Add Host"**
3. Enter:
   - **Name:** Descriptive name (e.g., "Production Server")
   - **URL:** `tcp://[remote-ip]:2376`
   - **CA Certificate:** Paste the **entire contents** of `ca.pem`
   - **Client Certificate:** Paste the **entire contents** of `client-cert.pem`
   - **Client Key:** Paste the **entire contents** of `client-key.pem`
4. Click **"Test Connection"**
5. If successful, click **"Save"**

**Example of what to paste:**
```
-----BEGIN CERTIFICATE-----
MIIDXTCCAkWgAwIBAgIJAKZ7... (many lines)
...
-----END CERTIFICATE-----
```

---

## Manual mTLS Setup

If you prefer manual setup or the script doesn't work for your system.

See [mTLS Configuration](mTLS-Configuration) for complete manual setup instructions.

---

## Platform-Specific Guides

The setup script auto-detects and provides instructions for:

### Tested Platforms
- **Linux with systemd** (Ubuntu, Debian, RHEL, Fedora, CentOS)
- **unRAID** (6.9+)

### ⚠️ Untested (Use with Caution)
- **Synology DSM**
- **QNAP**
- **TrueNAS**
- **Alpine Linux** (OpenRC)

**Note for Alpine Linux users:** DockMon v2 uses Alpine 3.x with OpenSSL 3.x, which has stricter certificate validation. Ensure your mTLS certificates include proper Subject Alternative Names (SANs) for hostname/IP matching.

See [Platform Guides](Platform-Guides) for detailed platform-specific instructions.

---

## Connection Formats

### Local Docker Socket
```
unix:///var/run/docker.sock
```
**Use for:** DockMon monitoring local Docker (automatic)

### Remote Docker (Insecure)
```
tcp://192.168.1.100:2375
```
**Use for:** Development/testing ONLY
⚠️ **NEVER use in production!**

### Remote Docker (Secure with mTLS)
```
tcp://192.168.1.100:2376
```
**Use for:** Production remote monitoring
**Always use port 2376 with TLS certificates**

---

## Troubleshooting

### Connection Refused

**Error:**
```
Failed to establish connection: [Errno 111] Connection refused
```

**Solutions:**
1. Verify Docker is listening:
   ```bash
   ss -tlnp | grep docker
   # Should show: 0.0.0.0:2376
   ```

2. Check firewall:
   ```bash
   sudo ufw status
   sudo iptables -L
   ```

3. Test connectivity from DockMon:
   ```bash
   docker exec dockmon telnet [remote-ip] 2376
   ```

### Certificate Verification Failed

**Error:**
```
SSL: CERTIFICATE_VERIFY_FAILED
```

**Solutions:**
1. Verify you're using matching certificates (CA, cert, key)
2. Check certificate wasn't regenerated on remote host
3. Verify certificate hasn't expired
4. Ensure hostname/IP matches certificate SAN

**v2-specific:** DockMon v2 uses Alpine Linux with OpenSSL 3.x, which enforces stricter certificate validation:
- Certificates **must** include Subject Alternative Names (SANs)
- Hostname/IP in DockMon URL must match certificate SAN entries
- If upgrading from v1, you may need to regenerate certificates with proper SANs
- Use the setup script which automatically generates OpenSSL 3.x-compatible certificates

### Docker Won't Start After Configuration

**Error:**
```
Failed to start docker.service
```

**Solutions:**
1. Check Docker logs:
   ```bash
   sudo journalctl -u docker -n 50
   ```

2. Verify certificate permissions:
   ```bash
   ls -l /etc/docker/certs/
   # Keys should be mode 400 or 600
   ```

3. Check configuration syntax:
   ```bash
   sudo dockerd --validate
   ```

4. Revert configuration and restart:
   ```bash
   sudo rm /etc/systemd/system/docker.service.d/override.conf
   sudo systemctl daemon-reload
   sudo systemctl restart docker
   ```

### Port Already in Use

**Error:**
```
Cannot start service: port 2376 already allocated
```

**Solutions:**
1. Check what's using the port:
   ```bash
   sudo lsof -i :2376
   ```

2. Use a different port in Docker configuration
3. Stop the conflicting service

### unRAID: Missing Unix Socket (Docker Won't Start)

**Error:**
```
Docker daemon... Failed.
Cannot connect to the Docker daemon at unix:///var/run/docker.sock
```

**Cause:** The `DOCKER_OPTS` in `/boot/config/docker.cfg` is missing the unix socket.

**Solution:**
Ensure your `DOCKER_OPTS` includes **both** the unix socket and tcp socket:

```bash
DOCKER_OPTS="-H unix:///var/run/docker.sock -H tcp://0.0.0.0:2376 --tlsverify --tlscacert=/boot/config/docker-tls/ca.pem --tlscert=/boot/config/docker-tls/server-cert.pem --tlskey=/boot/config/docker-tls/server-key.pem"
```

**Important:** Docker needs the unix socket for local docker commands and the tcp socket for remote access.

### unRAID: Certificate Locations

**unRAID 7.x (fresh install):**
- Certificates auto-generated in: `/boot/config/docker-tls/`
- Includes: `ca.pem`, `client-cert.pem`, `client-key.pem`, `server-cert.pem`, `server-key.pem`

**unRAID 6.x (upgraded system):**
- May have certificates in: `/boot/config/docker/certs/`
- Check both locations if you're unsure

**To check which location you have:**
```bash
ls -la /boot/config/docker-tls/
ls -la /boot/config/docker/certs/
```

The mTLS setup script automatically detects and uses existing certificates from either location.

For more troubleshooting, see [Troubleshooting](Troubleshooting).

---

## Insecure Setup (Development Only)

⚠️ **ONLY use this for isolated test environments!**

### Prerequisites
- Isolated network (no internet exposure)
- Test/development environment only
- You understand the security risks

### Linux with systemd

1. Create systemd override:
   ```bash
   sudo systemctl edit docker
   ```

2. Add configuration:
   ```ini
   [Service]
   ExecStart=
   ExecStart=/usr/bin/dockerd -H unix:///var/run/docker.sock -H tcp://0.0.0.0:2375
   ```

3. Restart Docker:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart docker
   ```

### unRAID

1. Stop Docker:
   - Settings → Docker → Enable Docker: **No** → Apply

2. Edit configuration:
   ```bash
   nano /boot/config/docker.cfg
   ```

   Add:
   ```
   DOCKER_OPTS="-H tcp://0.0.0.0:2375"
   ```

3. Start Docker:
   - Settings → Docker → Enable Docker: **Yes** → Apply

### Add to DockMon

Use URL: `tcp://192.168.1.100:2375` (note port **2375**, not 2376)

Leave all certificate fields empty.

---

## Security Best Practices

### Required
- Always use mTLS for remote connections
- Never expose Docker API without TLS
- Use firewall rules to restrict access to specific IPs
- Monitor Docker logs for unauthorized access attempts

### Recommended
- Rotate certificates every 90-365 days
- Use strong passphrases for certificate keys
- Store private keys securely (never commit to git)
- Use VPN for additional security layer
- Enable Docker audit logging

### Certificate Storage
- DockMon stores certificates in SQLite database with 600 permissions
- Database file is created with secure permissions (600)
- Certificates are encrypted at rest by filesystem

### Network Security
```
Internet → [Firewall] → [VPN (optional)] → Docker port 2376 → Docker daemon
```

Recommended firewall rules:
```bash
# Allow only from DockMon server
sudo ufw allow from [dockmon-ip] to any port 2376

# Or use IP whitelist
sudo iptables -A INPUT -p tcp --dport 2376 -s [dockmon-ip] -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 2376 -j DROP
```

---

## Next Steps

- [Platform Guides](Platform-Guides) - Platform-specific detailed instructions
- [mTLS Configuration](mTLS-Configuration) - Manual certificate generation
- [Security Guide](Security-Guide) - Comprehensive security best practices
- [Managing Hosts](Managing-Hosts) - Managing multiple Docker hosts in DockMon